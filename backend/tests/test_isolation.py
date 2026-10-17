import pytest
from app.models import Role

from tests.conftest import make_car, make_invite, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


@pytest.fixture()
def two_buildings(db_session):
    from app.models import Building

    building_a = Building(name="Building A", timezone="America/Los_Angeles")
    building_b = Building(name="Building B", timezone="America/Los_Angeles")
    db_session.add_all([building_a, building_b])
    db_session.commit()
    db_session.refresh(building_a)
    db_session.refresh(building_b)

    resident_a = make_user(db_session, building_a.id, Role.resident, "resident_a@example.com")
    resident_b = make_user(db_session, building_b.id, Role.resident, "resident_b@example.com")
    manager_a = make_user(db_session, building_a.id, Role.manager, "manager_a@example.com")

    return {
        "building_a": building_a,
        "building_b": building_b,
        "resident_a": resident_a,
        "resident_b": resident_b,
        "manager_a": manager_a,
    }


def test_resident_cannot_see_another_buildings_car(client, db_session, two_buildings):
    car = make_car(db_session, two_buildings["building_a"].id, two_buildings["resident_a"].id)
    car_id = car.id

    csrf_b = _login(client, "resident_b@example.com")
    response = client.get(f"/cars/{car_id}", headers={"X-CSRF-Token": csrf_b})
    assert response.status_code == 404


def test_resident_cannot_see_another_residents_car_same_building(
    client, db_session, two_buildings
):
    car = make_car(db_session, two_buildings["building_a"].id, two_buildings["resident_a"].id)
    car_id = car.id

    make_user(
        db_session, two_buildings["building_a"].id, Role.resident, "resident_a2@example.com"
    )
    csrf_a2 = _login(client, "resident_a2@example.com")
    response = client.get(f"/cars/{car_id}", headers={"X-CSRF-Token": csrf_a2})
    assert response.status_code == 403


def test_manager_in_same_building_can_see_resident_car(client, db_session, two_buildings):
    car = make_car(db_session, two_buildings["building_a"].id, two_buildings["resident_a"].id)
    car_id = car.id

    csrf_manager = _login(client, "manager_a@example.com")
    response = client.get(f"/cars/{car_id}", headers={"X-CSRF-Token": csrf_manager})
    assert response.status_code == 200


def test_resident_cannot_create_invite_code(client, db_session, two_buildings):
    csrf_a = _login(client, "resident_a@example.com")
    response = client.post(
        "/manager/invite-codes",
        json={"role": "resident", "max_uses": 1},
        headers={"X-CSRF-Token": csrf_a},
    )
    assert response.status_code == 403


def test_manager_can_create_invite_code(client, db_session, two_buildings):
    csrf_manager = _login(client, "manager_a@example.com")
    response = client.post(
        "/manager/invite-codes",
        json={"role": "resident", "max_uses": 1},
        headers={"X-CSRF-Token": csrf_manager},
    )
    assert response.status_code == 201
    assert response.json()["code"]


def test_invite_code_from_building_a_registers_into_building_a(client, db_session, two_buildings):
    invite = make_invite(db_session, two_buildings["building_a"].id, Role.resident)
    response = client.post(
        "/auth/register",
        json={
            "invite_code": invite.code,
            "email": "newcomer@example.com",
            "password": "supersecret1",
            "full_name": "New Comer",
        },
    )
    assert response.status_code == 201
    assert response.json()["building_id"] == two_buildings["building_a"].id


ROUTE_MATRIX = [
    ("GET", "/cars", None),
    ("GET", "/auth/me", None),
]


@pytest.mark.parametrize("method,path,body", ROUTE_MATRIX)
def test_unauthenticated_requests_are_rejected(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401
