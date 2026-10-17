from app.models import Role, Task, TaskType

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_creating_on_demand_request_generates_retrieve_and_deliver_tasks(
    client, db_session, building
):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")

    created = client.post(
        "/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf}
    ).json()
    assert created["state"] == "queued"

    tasks = db_session.query(Task).filter(Task.request_id == created["id"]).all()
    types = sorted(t.type for t in tasks)
    assert types == sorted([TaskType.retrieve, TaskType.deliver])
    for task in tasks:
        assert task.planned_start_at is not None


def test_scheduled_future_request_does_not_generate_tasks_yet(client, db_session, building):
    from datetime import UTC, datetime, timedelta

    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")

    far_future = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    created = client.post(
        "/requests",
        json={"car_id": car.id, "ready_by": far_future},
        headers={"X-CSRF-Token": csrf},
    ).json()
    assert created["state"] == "scheduled"

    tasks = db_session.query(Task).filter(Task.request_id == created["id"]).all()
    assert tasks == []


def test_transition_assigns_tasks_to_valet(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf_resident = _login(client, "resident@example.com")
    created = client.post(
        "/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf_resident}
    ).json()
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_valet = _login(client, "valet@example.com")
    client.post(
        f"/requests/{created['id']}/transition",
        json={"target_state": "assigned"},
        headers={"X-CSRF-Token": csrf_valet},
    )

    tasks = db_session.query(Task).filter(Task.request_id == created["id"]).all()
    assert all(t.assigned_valet_id is not None for t in tasks)
