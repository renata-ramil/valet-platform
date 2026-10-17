from datetime import UTC, datetime, timedelta

from app.models import Role

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_resident_creates_on_demand_request_and_sees_it(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")

    response = client.post("/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "queued"
    assert body["resident_label"] == "Called"

    listing = client.get("/requests", headers={"X-CSRF-Token": csrf})
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_ready_by_is_serialized_with_explicit_timezone(client, db_session, building):
    # Regression: SQLite drops tzinfo on read, so without normalizing before
    # serialization, ready_by came back without a 'Z'/offset and browsers
    # misparsed it as local time instead of UTC, showing the wrong clock time
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")
    response = client.post("/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf})
    body = response.json()
    assert body["ready_by"].endswith("Z") or "+00:00" in body["ready_by"]
    assert body["created_at"].endswith("Z") or "+00:00" in body["created_at"]


def test_request_with_ready_by_too_soon_is_rejected(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")

    soon = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    response = client.post(
        "/requests",
        json={"car_id": car.id, "ready_by": soon},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 400


def test_cancel_request_then_cancel_again_is_conflict(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")
    created = client.post(
        "/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf}
    ).json()

    first_cancel = client.post(f"/requests/{created['id']}/cancel", headers={"X-CSRF-Token": csrf})
    assert first_cancel.status_code == 200
    assert first_cancel.json()["state"] == "cancelled"

    second_cancel = client.post(f"/requests/{created['id']}/cancel", headers={"X-CSRF-Token": csrf})
    assert second_cancel.status_code == 409


def test_resident_cannot_transition_request(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")
    created = client.post(
        "/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf}
    ).json()

    response = client.post(
        f"/requests/{created['id']}/transition",
        json={"target_state": "assigned"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 403


def test_valet_can_transition_request_through_lifecycle(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf_resident = _login(client, "resident@example.com")
    created = client.post(
        "/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf_resident}
    ).json()
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_valet = _login(client, "valet@example.com")
    for target in ["assigned", "retrieving", "en_route", "delivered"]:
        response = client.post(
            f"/requests/{created['id']}/transition",
            json={"target_state": target},
            headers={"X-CSRF-Token": csrf_valet},
        )
        assert response.status_code == 200, response.text
        assert response.json()["state"] == target

    final = client.get(f"/requests/{created['id']}", headers={"X-CSRF-Token": csrf_valet})
    assert final.json()["resident_label"] == "Delivered"
