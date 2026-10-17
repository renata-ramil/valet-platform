import json
from datetime import UTC, datetime

import pytest
from app.audit import BrokenChainError, verify_all, verify_subject_chain
from app.models import (
    AuditEvent,
    Building,
    CarStatus,
    ParkingSpot,
    Request,
    RequestSource,
    RequestState,
    Role,
    Task,
    TaskType,
)

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _seed_garage(db_session, building_id):
    # Laying out a small 2x2 garage so assign_spot_for_car has somewhere to park
    for lane in range(1, 3):
        for depth in range(1, 3):
            db_session.add(ParkingSpot(building_id=building_id, lane=lane, depth=depth))
    db_session.commit()


def _make_delivered_request(db_session, building, resident, car):
    request = Request(
        building_id=building.id,
        owner_id=resident.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=datetime.now(UTC),
        state=RequestState.delivered,
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)
    return request


def test_car_search_matches_partial_plate_case_insensitive(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    make_car(db_session, building.id, resident.id, "VF4821")

    csrf = _login(client, "valet@example.com")
    response = client.get("/valet/car-search?plate=f48", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    plates = [c["license_plate"] for c in response.json()]
    assert "VF4821" in plates


def test_car_search_excludes_ended_cars(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id, "END0001")
    car.status = CarStatus.ended
    db_session.add(car)
    db_session.commit()

    csrf = _login(client, "valet@example.com")
    response = client.get("/valet/car-search?plate=END0001", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json() == []


def test_car_search_no_match_returns_empty_list(client, db_session, building):
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    csrf = _login(client, "valet@example.com")
    response = client.get("/valet/car-search?plate=ZZZZZZ", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json() == []


def test_car_search_blocked_for_resident(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_car(db_session, building.id, resident.id, "RES0001")
    csrf = _login(client, "resident@example.com")
    response = client.get("/valet/car-search?plate=RES", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403


def test_car_arrived_creates_park_task_and_logs_event(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id, "ARR0001")
    _make_delivered_request(db_session, building, resident, car)

    csrf = _login(client, "valet@example.com")
    response = client.post(f"/valet/cars/{car.id}/arrived", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "park_task_created"

    task = db_session.get(Task, body["task_id"])
    assert task.type == TaskType.park
    assert task.state == "pending"

    events = list(
        db_session.query(AuditEvent)
        .filter(AuditEvent.subject_type == "task", AuditEvent.subject_id == task.id)
        .order_by(AuditEvent.sequence)
    )
    assert len(events) == 1
    assert events[0].type == "car_arrived"
    payload = json.loads(events[0].payload)
    assert payload["car_id"] == car.id


def test_car_arrived_with_no_prior_request_is_conflict(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id, "NOREQ01")

    csrf = _login(client, "valet@example.com")
    response = client.post(f"/valet/cars/{car.id}/arrived", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409


def test_resident_cannot_use_car_arrived(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id, "RESA001")
    _make_delivered_request(db_session, building, resident, car)

    csrf = _login(client, "resident@example.com")
    response = client.post(f"/valet/cars/{car.id}/arrived", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403


def test_car_arrived_is_building_scoped(client, db_session, building):
    other_building = Building(name="Other Tower", timezone="UTC")
    db_session.add(other_building)
    db_session.commit()

    other_resident = make_user(db_session, other_building.id, email="other-resident@example.com")
    other_car = make_car(db_session, other_building.id, other_resident.id, "OTH0001")
    _make_delivered_request(db_session, other_building, other_resident, other_car)

    make_user(db_session, building.id, Role.valet, "valet@example.com")
    csrf = _login(client, "valet@example.com")
    response = client.post(f"/valet/cars/{other_car.id}/arrived", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 404


def test_complete_park_task_assigns_spot_and_logs_parked_and_key_returned(
    client, db_session, building
):
    _seed_garage(db_session, building.id)
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id, "PARK001")
    _make_delivered_request(db_session, building, resident, car)

    csrf = _login(client, "valet@example.com")
    arrived = client.post(f"/valet/cars/{car.id}/arrived", headers={"X-CSRF-Token": csrf}).json()
    task_id = arrived["task_id"]

    response = client.post(f"/valet/tasks/{task_id}/complete-park", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "parked"
    assert body["lane"] is not None
    assert body["depth"] is not None

    db_session.refresh(car)
    assert car.parking_spot_id is not None

    events = list(
        db_session.query(AuditEvent)
        .filter(AuditEvent.subject_type == "task", AuditEvent.subject_id == task_id)
        .order_by(AuditEvent.sequence)
    )
    assert [e.type for e in events] == ["car_arrived", "parked", "key_returned"]


def test_complete_park_task_twice_is_conflict(client, db_session, building):
    _seed_garage(db_session, building.id)
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id, "TWICE01")
    _make_delivered_request(db_session, building, resident, car)

    csrf = _login(client, "valet@example.com")
    arrived = client.post(f"/valet/cars/{car.id}/arrived", headers={"X-CSRF-Token": csrf}).json()
    task_id = arrived["task_id"]
    client.post(f"/valet/tasks/{task_id}/complete-park", headers={"X-CSRF-Token": csrf})

    response = client.post(f"/valet/tasks/{task_id}/complete-park", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409


def test_full_custody_chain_logs_all_six_actions_and_verifies(client, db_session, building):
    _seed_garage(db_session, building.id)
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id, "CUST001")

    csrf_resident = _login(client, "resident@example.com")
    created = client.post(
        "/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf_resident}
    ).json()
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_valet = _login(client, "valet@example.com")
    for target in ["assigned", "retrieving", "en_route", "delivered"]:
        resp = client.post(
            f"/requests/{created['id']}/transition",
            json={"target_state": target},
            headers={"X-CSRF-Token": csrf_valet},
        )
        assert resp.status_code == 200, resp.text

    arrived = client.post(
        f"/valet/cars/{car.id}/arrived", headers={"X-CSRF-Token": csrf_valet}
    ).json()
    complete = client.post(
        f"/valet/tasks/{arrived['task_id']}/complete-park", headers={"X-CSRF-Token": csrf_valet}
    )
    assert complete.status_code == 200, complete.text

    event_types = [
        e.type
        for e in db_session.query(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.sequence)
    ]
    for expected in (
        "key_taken",
        "car_retrieved",
        "delivered_at_lobby",
        "car_arrived",
        "parked",
        "key_returned",
    ):
        assert expected in event_types, f"{expected} missing from {event_types}"

    assert verify_all(db_session) == []


def test_tampering_a_valet_event_payload_breaks_the_chain(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id, "TAMP001")
    _make_delivered_request(db_session, building, resident, car)

    csrf = _login(client, "valet@example.com")
    arrived = client.post(f"/valet/cars/{car.id}/arrived", headers={"X-CSRF-Token": csrf}).json()

    events = list(
        db_session.query(AuditEvent)
        .filter(AuditEvent.subject_type == "task", AuditEvent.subject_id == arrived["task_id"])
        .order_by(AuditEvent.sequence)
    )
    # The DB trigger blocks a raw UPDATE (covered in test_audit_tamper.py); this
    # flips a byte on the loaded object to prove verify_subject_chain detects it
    events[0].payload = events[0].payload.replace("car_id", "tampered")
    with pytest.raises(BrokenChainError):
        verify_subject_chain(events)
