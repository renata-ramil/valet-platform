from app.models import Role

from tests.conftest import make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_resident_creates_and_sees_own_ticket(client, db_session, building):
    make_user(db_session, building.id, email="resident@example.com")
    csrf = _login(client, "resident@example.com")
    created = client.post(
        "/tickets",
        json={"subject": "Car scratched", "message": "There is a scratch on my door"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    ticket_id = created.json()["id"]

    listing = client.get("/tickets", headers={"X-CSRF-Token": csrf})
    assert len(listing.json()) == 1

    fetched = client.get(f"/tickets/{ticket_id}", headers={"X-CSRF-Token": csrf})
    assert fetched.status_code == 200
    assert len(fetched.json()["messages"]) == 1


def test_other_resident_cannot_see_ticket(client, db_session, building):
    make_user(db_session, building.id, email="resident1@example.com")
    make_user(db_session, building.id, email="resident2@example.com")
    csrf1 = _login(client, "resident1@example.com")
    created = client.post(
        "/tickets",
        json={"subject": "Help", "message": "Need help"},
        headers={"X-CSRF-Token": csrf1},
    ).json()
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf1})

    csrf2 = _login(client, "resident2@example.com")
    response = client.get(f"/tickets/{created['id']}", headers={"X-CSRF-Token": csrf2})
    assert response.status_code == 403


def test_manager_sees_all_tickets_in_building(client, db_session, building):
    make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.manager, "manager@example.com")
    csrf_resident = _login(client, "resident@example.com")
    client.post(
        "/tickets",
        json={"subject": "Help", "message": "Need help"},
        headers={"X-CSRF-Token": csrf_resident},
    )
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_manager = _login(client, "manager@example.com")
    listing = client.get("/tickets", headers={"X-CSRF-Token": csrf_manager})
    assert len(listing.json()) == 1


def test_staff_reply_moves_ticket_to_waiting(client, db_session, building):
    make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, building.id, Role.support, "support@example.com")
    csrf_resident = _login(client, "resident@example.com")
    created = client.post(
        "/tickets",
        json={"subject": "Help", "message": "Need help"},
        headers={"X-CSRF-Token": csrf_resident},
    ).json()
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_support = _login(client, "support@example.com")
    client.post(
        f"/tickets/{created['id']}/messages",
        json={"body": "Looking into it"},
        headers={"X-CSRF-Token": csrf_support},
    )
    fetched = client.get(f"/tickets/{created['id']}", headers={"X-CSRF-Token": csrf_support})
    assert fetched.json()["status"] == "waiting"


def test_resolve_ticket_requires_staff(client, db_session, building):
    make_user(db_session, building.id, email="resident@example.com")
    csrf = _login(client, "resident@example.com")
    created = client.post(
        "/tickets",
        json={"subject": "Help", "message": "Need help"},
        headers={"X-CSRF-Token": csrf},
    ).json()
    response = client.patch(
        f"/tickets/{created['id']}/status",
        json={"status": "resolved"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 403


def test_cross_building_ticket_access_is_404(client, db_session, building):
    from app.models import Building

    other_building = Building(name="Other Building", timezone="America/Los_Angeles")
    db_session.add(other_building)
    db_session.commit()
    db_session.refresh(other_building)

    make_user(db_session, building.id, email="resident@example.com")
    make_user(db_session, other_building.id, Role.manager, "manager2@example.com")

    csrf_resident = _login(client, "resident@example.com")
    created = client.post(
        "/tickets",
        json={"subject": "Help", "message": "Need help"},
        headers={"X-CSRF-Token": csrf_resident},
    ).json()
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_manager2 = _login(client, "manager2@example.com")
    response = client.get(f"/tickets/{created['id']}", headers={"X-CSRF-Token": csrf_manager2})
    assert response.status_code == 404
