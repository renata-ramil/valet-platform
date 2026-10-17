from app.models import Role

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_queue_lists_open_tasks_sorted_by_planned_start(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf_resident = _login(client, "resident@example.com")
    client.post("/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf_resident})
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_valet = _login(client, "valet@example.com")
    response = client.get("/valet/queue", headers={"X-CSRF-Token": csrf_valet})
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2  # retrieve and deliver tasks
    assert items[0]["minutes_to_deadline"] <= items[1]["minutes_to_deadline"]


def test_resident_cannot_see_valet_queue(client, db_session, building):
    make_user(db_session, building.id, email="resident@example.com")
    csrf = _login(client, "resident@example.com")
    response = client.get("/valet/queue", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403


def test_completed_tasks_drop_off_the_queue(client, db_session, building):
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
        client.post(
            f"/requests/{created['id']}/transition",
            json={"target_state": target},
            headers={"X-CSRF-Token": csrf_valet},
        )

    response = client.get("/valet/queue", headers={"X-CSRF-Token": csrf_valet})
    assert response.json() == []
