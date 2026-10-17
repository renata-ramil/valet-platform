"""Manager fleet routes: car CRUD, CSV import, resident invites, plans and
car requests. Also the end-to-end billing check: a manager-added car
shows up prorated on the next generated invoice.
"""

from datetime import UTC, date, datetime

from app.billing.invoices import generate_invoices_for_period
from app.billing.proration import month_bounds, prorate_cents
from app.models import Building, Car, Role

from tests.conftest import make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _make_plan(client, csrf, name="Standard", monthly_cents=15000):
    response = client.post(
        "/manager/plans",
        json={"name": name, "size_class": "sedan", "monthly_cents": monthly_cents},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manager_adds_car_and_next_invoice_has_prorated_line(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "fleet-manager@example.com")
    resident = make_user(db_session, building.id, Role.resident, "fleet-resident@example.com")
    csrf = _login(client, "fleet-manager@example.com")
    plan = _make_plan(client, csrf, monthly_cents=15000)

    # The plan's price takes effect "this month" (app.plan_service.create_plan
    # anchors it to the real current date), so the billing period under test
    # must be the real current month too, not a hardcoded one
    today = date.today()
    period_year, period_month = today.year, today.month
    _, period_end_probe = month_bounds(period_year, period_month)
    started_on = date(period_year, period_month, min(10, period_end_probe.day))

    create = client.post(
        "/manager/cars",
        json={
            "resident_id": resident.id,
            "make": "Honda",
            "model": "Civic",
            "color": "blue",
            "license_plate": "FLEET001",
            "plan_id": plan["id"],
            "started_on": started_on.isoformat(),
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert create.status_code == 201, create.text
    car_body = create.json()
    assert car_body["status"] in ("active", "pending")

    now = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    building_obj = db_session.get(Building, building.id)
    created = generate_invoices_for_period(db_session, building_obj, period_year, period_month, now)
    assert len(created) == 1
    invoice = created[0]
    assert len(invoice.lines) == 1
    line = invoice.lines[0]

    period_start, period_end = month_bounds(period_year, period_month)
    days_in_month = (period_end - period_start).days + 1
    days_active = (period_end - started_on).days + 1
    expected = prorate_cents(15000, days_active, days_in_month)

    assert line.amount_cents == expected
    assert 0 < line.amount_cents < 15000
    assert invoice.total_cents == expected


def test_manager_updates_car_nickname_and_plate(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "update-manager@example.com")
    resident = make_user(db_session, building.id, Role.resident, "update-resident@example.com")
    csrf = _login(client, "update-manager@example.com")

    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate="UPD0001",
    )
    db_session.add(car)
    db_session.commit()

    response = client.patch(
        f"/manager/cars/{car.id}",
        json={"license_plate": "UPD0002", "nickname": "Weekend car"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json()["license_plate"] == "UPD0002"
    assert response.json()["nickname"] == "Weekend car"


def test_manager_ends_car_sets_ended_status_and_schedule_cutoff(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "end-manager@example.com")
    resident = make_user(db_session, building.id, Role.resident, "end-resident@example.com")
    csrf = _login(client, "end-manager@example.com")
    plan = _make_plan(client, csrf, name="End Plan")

    create = client.post(
        "/manager/cars",
        json={
            "resident_id": resident.id,
            "make": "Honda",
            "model": "Civic",
            "color": "blue",
            "license_plate": "END0001",
            "plan_id": plan["id"],
            "started_on": date(2026, 1, 1).isoformat(),
        },
        headers={"X-CSRF-Token": csrf},
    )
    car_id = create.json()["id"]

    end = client.post(
        f"/manager/cars/{car_id}/end",
        json={"ended_on": "2026-06-15"},
        headers={"X-CSRF-Token": csrf},
    )
    assert end.status_code == 200, end.text
    assert end.json()["status"] == "ended"
    assert end.json()["ended_on"] == "2026-06-15"

    # Ending it again is a conflict, not a silent no-op
    again = client.post(
        f"/manager/cars/{car_id}/end",
        json={"ended_on": "2026-06-20"},
        headers={"X-CSRF-Token": csrf},
    )
    assert again.status_code == 409


def test_csv_import_dry_run_does_not_persist_then_commit_does(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "import-manager@example.com")
    make_user(db_session, building.id, Role.resident, "import-resident@example.com")
    csrf = _login(client, "import-manager@example.com")
    plan = _make_plan(client, csrf, name="Import Plan")

    csv_text = (
        "email,full_name,unit,plate,make,model,color,plan_name,started_on\n"
        f"import-resident@example.com,,,IMP0001,Honda,Civic,blue,{plan['name']},2026-01-01\n"
        "nobody@example.com,,,IMP0002,Toyota,Camry,red,NoSuchPlan,2026-01-01\n"
    )

    dry_run = client.post(
        "/manager/cars/import",
        json={"csv_text": csv_text, "dry_run": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert dry_run.status_code == 200, dry_run.text
    body = dry_run.json()
    assert body["ok_count"] == 1
    assert body["error_count"] == 1
    assert body["dry_run"] is True

    cars_after_dry_run = list(
        db_session.query(Car).filter(Car.building_id == building.id, Car.license_plate == "IMP0001")
    )
    assert cars_after_dry_run == []

    commit = client.post(
        "/manager/cars/import",
        json={"csv_text": csv_text, "dry_run": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert commit.status_code == 200
    assert commit.json()["ok_count"] == 1

    cars_after_commit = list(
        db_session.query(Car).filter(Car.building_id == building.id, Car.license_plate == "IMP0001")
    )
    assert len(cars_after_commit) == 1


def test_resident_invite_is_tied_to_a_unit(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "invite-manager@example.com")
    csrf = _login(client, "invite-manager@example.com")

    response = client.post(
        "/manager/residents/invite",
        json={"unit": "12B", "max_uses": 3},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    code = response.json()["code"]

    register = client.post(
        "/auth/register",
        json={
            "invite_code": code,
            "email": "newresident@example.com",
            "password": "supersecret1",
            "full_name": "New Resident",
        },
    )
    assert register.status_code == 201

    csrf2 = _login(client, "newresident@example.com", password="supersecret1")
    me = client.get("/auth/me", headers={"X-CSRF-Token": csrf2})
    assert me.json()["role"] == "resident"
    from app.models import User

    new_user = db_session.query(User).filter(User.email == "newresident@example.com").one()
    assert new_user.unit == "12B"


def test_car_request_creates_ticket_and_manager_can_list_and_prefill(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "carreq-manager@example.com")
    make_user(db_session, building.id, Role.resident, "carreq-resident@example.com")
    csrf_resident = _login(client, "carreq-resident@example.com")

    request = client.post(
        "/cars/requests",
        json={
            "action": "add",
            "plate": "REQ0001",
            "make": "Honda",
            "model": "Civic",
            "color": "black",
            "note": "New car for the garage",
        },
        headers={"X-CSRF-Token": csrf_resident},
    )
    assert request.status_code == 201, request.text
    car_request = request.json()
    assert car_request["action"] == "add"
    client.post("/auth/logout", headers={"X-CSRF-Token": csrf_resident})

    csrf_manager = _login(client, "carreq-manager@example.com")
    listing = client.get("/manager/car-requests", headers={"X-CSRF-Token": csrf_manager})
    assert listing.status_code == 200
    assert any(r["id"] == car_request["id"] for r in listing.json())

    prefill = client.get(
        f"/manager/car-requests/{car_request['id']}/prefill", headers={"X-CSRF-Token": csrf_manager}
    )
    assert prefill.status_code == 200
    assert prefill.json()["license_plate"] == "REQ0001"
    assert prefill.json()["make"] == "Honda"


def test_plan_price_change_and_impact_preview(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "plan-manager@example.com")
    resident = make_user(db_session, building.id, Role.resident, "plan-resident@example.com")
    csrf = _login(client, "plan-manager@example.com")
    plan = _make_plan(client, csrf, name="Impact Plan", monthly_cents=10000)

    create_car = client.post(
        "/manager/cars",
        json={
            "resident_id": resident.id,
            "make": "Honda",
            "model": "Civic",
            "color": "blue",
            "license_plate": "IMPACT01",
            "plan_id": plan["id"],
            "started_on": "2026-01-01",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert create_car.status_code == 201

    today = date.today()
    next_year, next_month_num = (
        (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    )
    effective_month = date(next_year, next_month_num, 1).isoformat()

    preview = client.post(
        f"/manager/plans/{plan['id']}/price-preview",
        json={"monthly_cents": 12000, "effective_month": effective_month},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["affected_car_count"] == 1
    assert body["monthly_revenue_change_cents"] == 2000

    apply = client.post(
        f"/manager/plans/{plan['id']}/price",
        json={"monthly_cents": 12000, "effective_month": effective_month},
        headers={"X-CSRF-Token": csrf},
    )
    assert apply.status_code == 200
    assert (
        apply.json()["current_monthly_cents"] == 10000
    )  # unchanged until the future month arrives

    archive = client.post(f"/manager/plans/{plan['id']}/archive", headers={"X-CSRF-Token": csrf})
    assert archive.status_code == 200
    assert archive.json()["archived"] is True
