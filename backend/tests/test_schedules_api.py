from app.models import Role

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_resident_creates_schedule_and_materializes(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.manager, "manager@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")

    schedule = client.post(
        "/schedules",
        json={
            "car_id": car.id,
            "weekdays": [0, 1, 2, 3, 4],
            "ready_by_local_time": "08:00:00",
            "active_from": "2020-01-01",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert schedule.status_code == 201
    schedule_id = schedule.json()["id"]

    skip = client.post(
        f"/schedules/{schedule_id}/skip-tomorrow", headers={"X-CSRF-Token": csrf}
    )
    assert skip.status_code == 200

    client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    csrf_manager = _login(client, "manager@example.com")
    materialize = client.post("/schedules/materialize", headers={"X-CSRF-Token": csrf_manager})
    assert materialize.status_code == 200
    assert "created" in materialize.json()


def test_pause_until_stops_materialization_endpoint(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf = _login(client, "resident@example.com")
    schedule = client.post(
        "/schedules",
        json={
            "car_id": car.id,
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "ready_by_local_time": "08:00:00",
            "active_from": "2020-01-01",
        },
        headers={"X-CSRF-Token": csrf},
    ).json()

    pause = client.post(
        f"/schedules/{schedule['id']}/pause-until",
        json={"paused_until": "2099-01-01"},
        headers={"X-CSRF-Token": csrf},
    )
    assert pause.status_code == 200

    fetched = client.get(f"/schedules/{schedule['id']}", headers={"X-CSRF-Token": csrf})
    assert fetched.json()["paused_until"] == "2099-01-01"
