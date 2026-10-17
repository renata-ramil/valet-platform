from app.models import Role

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_dashboard_counts_reflect_requests(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.manager, "manager@example.com")
    car = make_car(db_session, building.id, resident.id)
    csrf_resident = _login(client, "resident@example.com")
    client.post("/requests", json={"car_id": car.id}, headers={"X-CSRF-Token": csrf_resident})
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_manager = _login(client, "manager@example.com")
    response = client.get("/manager/dashboard", headers={"X-CSRF-Token": csrf_manager})
    assert response.status_code == 200
    body = response.json()
    assert body["counts_by_state"]["queued"] == 1
    assert len(body["timeline"]) == 48


def test_dashboard_requires_manager_role(client, db_session, building):
    make_user(db_session, building.id, email="resident@example.com")
    csrf = _login(client, "resident@example.com")
    response = client.get("/manager/dashboard", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403


def test_dashboard_computes_on_time_rate_for_delivered_requests(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    make_user(db_session, building.id, Role.manager, "manager@example.com")
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
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_valet})

    csrf_manager = _login(client, "manager@example.com")
    response = client.get("/manager/dashboard", headers={"X-CSRF-Token": csrf_manager})
    assert response.status_code == 200
    assert response.json()["on_time_rate_today"] is not None


def test_valet_roster_shows_current_task(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.valet, "valet@example.com")
    make_user(db_session, building.id, Role.manager, "manager@example.com")
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
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_valet})

    csrf_manager = _login(client, "manager@example.com")
    response = client.get("/manager/dashboard", headers={"X-CSRF-Token": csrf_manager})
    roster = response.json()["valet_roster"]
    assert len(roster) == 1
    assert roster[0]["current_task_id"] is not None
