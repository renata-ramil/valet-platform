"""Security cases specific to fleet and billing, per docs/BILLING.md:
cross-resident isolation, residents
blocked from car CRUD, server-computed amounts, double-submit idempotency,
self-approval blocked, a stale TOTP step-up blocked, and the plate
uniqueness boundary at the building edge.
"""

from datetime import UTC, date, datetime, timedelta

import pyotp
from app.billing.credits import get_or_create_billing_account
from app.billing.invoices import generate_invoices_for_period
from app.fleet_service import create_car
from app.models import (
    ApprovalKind,
    ApprovalRequest,
    ApprovalStatus,
    Building,
    Car,
    Payment,
    PaymentMethod,
    Plan,
    PlanPrice,
    Role,
    UserSession,
)
from app.security import SESSION_COOKIE_NAME

from tests.conftest import make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _make_plan(db_session, building, monthly_cents=10000):
    plan = Plan(building_id=building.id, name="Standard", size_class="sedan")
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        PlanPrice(plan_id=plan.id, effective_month=date(2020, 1, 1), monthly_cents=monthly_cents)
    )
    db_session.commit()
    return plan


def _resident_with_invoice_and_method(db_session, building, email, plate, monthly_cents=10000):
    resident = make_user(db_session, building.id, Role.resident, email)
    plan = _make_plan(db_session, building, monthly_cents)
    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        plan_id=plan.id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate=plate,
        started_on=date(2026, 6, 1),
    )
    db_session.add(car)
    db_session.commit()

    now = datetime(2026, 6, 25, tzinfo=UTC)
    invoice = generate_invoices_for_period(db_session, building, 2026, 6, now)[0]

    billing_account = get_or_create_billing_account(db_session, resident.id, building.id)
    method = PaymentMethod(
        billing_account_id=billing_account.id,
        provider="fake",
        provider_customer_id=f"fake_cus_{billing_account.id}",
        provider_method_id="fake_pm_sec_test",
        kind="card",
        brand="visa",
        last4="4242",
    )
    db_session.add(method)
    db_session.commit()
    return resident, car, invoice, method


def test_resident_a_gets_404_on_resident_bs_invoices_methods_cars(client, db_session, building):
    resident_a, car_a, invoice_a, method_a = _resident_with_invoice_and_method(
        db_session, building, "sec-a@example.com", "SECA001"
    )
    resident_b, car_b, invoice_b, method_b = _resident_with_invoice_and_method(
        db_session, building, "sec-b@example.com", "SECB001"
    )

    login = _login(client, "sec-a@example.com")
    csrf = login["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    assert client.get(f"/billing/invoices/{invoice_b.id}", headers=headers).status_code == 404
    assert (
        client.get(f"/billing/invoices/{invoice_b.id}/receipt", headers=headers).status_code == 404
    )
    assert (
        client.delete(f"/billing/payment-methods/{method_b.id}", headers=headers).status_code == 404
    )
    assert client.get(f"/cars/{car_b.id}", headers=headers).status_code == 403


def test_resident_blocked_from_car_crud_through_any_route(client, db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "crud@example.com")
    login = _login(client, "crud@example.com")
    headers = {"X-CSRF-Token": login["csrf_token"]}

    create = client.post(
        "/cars",
        json={"make": "Honda", "model": "Civic", "color": "blue", "license_plate": "CRUD001"},
        headers=headers,
    )
    assert create.status_code == 403

    manager_create = client.post(
        "/manager/cars",
        json={
            "resident_id": resident.id,
            "make": "Honda",
            "model": "Civic",
            "color": "blue",
            "license_plate": "CRUD002",
        },
        headers=headers,
    )
    assert manager_create.status_code == 403

    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate="CRUD003",
    )
    db_session.add(car)
    db_session.commit()

    delete = client.delete(f"/cars/{car.id}", headers=headers)
    assert delete.status_code == 403

    end = client.post(f"/manager/cars/{car.id}/end", json={}, headers=headers)
    assert end.status_code == 403


def test_server_computes_payment_amount_not_the_client(client, db_session, building):
    resident, car, invoice, method = _resident_with_invoice_and_method(
        db_session, building, "amount@example.com", "AMT0001", monthly_cents=12345
    )
    login = _login(client, "amount@example.com")
    headers = {"X-CSRF-Token": login["csrf_token"], "Idempotency-Key": "forge-1"}

    response = client.post(
        f"/billing/invoices/{invoice.id}/pay",
        json={"payment_method_id": method.id, "amount_cents": 1, "total_cents": 1},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payment_id = response.json()["id"]
    payment = db_session.get(Payment, payment_id)
    # The forged amount_cents in the request body is not even a field the
    # schema accepts; the server always charges the invoice's own total
    assert payment.amount_cents == invoice.total_cents
    assert payment.amount_cents != 1


def test_double_submitted_payment_charges_once(client, db_session, building):
    resident, car, invoice, method = _resident_with_invoice_and_method(
        db_session, building, "double@example.com", "DBL0001"
    )
    login = _login(client, "double@example.com")
    headers = {"X-CSRF-Token": login["csrf_token"], "Idempotency-Key": "double-click-1"}
    body = {"payment_method_id": method.id}

    first = client.post(f"/billing/invoices/{invoice.id}/pay", json=body, headers=headers)
    second = client.post(f"/billing/invoices/{invoice.id}/pay", json=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    payments = list(db_session.query(Payment).filter(Payment.invoice_id == invoice.id).all())
    assert len(payments) == 1


def _enroll_and_confirm_totp(client, db_session, email):
    login = _login(client, email)
    csrf = login["csrf_token"]
    enroll = client.post("/auth/totp/enroll", headers={"X-CSRF-Token": csrf})
    secret = enroll.json()["secret"]
    code = pyotp.TOTP(secret).now()
    confirm = client.post("/auth/totp/confirm", json={"code": code}, headers={"X-CSRF-Token": csrf})
    new_csrf = confirm.json()["csrf_token"]
    client.post("/auth/logout", headers={"X-CSRF-Token": new_csrf})
    return secret


def _login_with_totp(client, email, secret):
    login = client.post("/auth/login", json={"email": email, "password": "password123"})
    challenge_id = login.json()["challenge_id"]
    code = pyotp.TOTP(secret).now()
    verify = client.post("/auth/totp/verify", json={"challenge_id": challenge_id, "code": code})
    assert verify.status_code == 200, verify.text
    return verify.json()["csrf_token"]


def test_requester_cannot_approve_their_own_refund(client, db_session, building):
    manager = make_user(db_session, building.id, Role.manager, "self-approve@example.com")
    secret = _enroll_and_confirm_totp(client, db_session, "self-approve@example.com")
    csrf = _login_with_totp(client, "self-approve@example.com", secret)

    resident, car, invoice, method = _resident_with_invoice_and_method(
        db_session, building, "self-approve-resident@example.com", "SAP0001"
    )
    billing_account = get_or_create_billing_account(db_session, resident.id, building.id)
    approval = ApprovalRequest(
        building_id=building.id,
        kind=ApprovalKind.credit,
        invoice_id=invoice.id,
        billing_account_id=billing_account.id,
        amount_cents=50000,
        reason="large goodwill credit",
        requested_by=manager.id,
    )
    db_session.add(approval)
    db_session.commit()

    response = client.post(
        f"/manager/approvals/{approval.id}/decide",
        json={"approve": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 403
    assert "own request" in response.json()["detail"]
    assert db_session.get(ApprovalRequest, approval.id).status == ApprovalStatus.pending


def test_stale_totp_stepup_blocks_money_action(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "stale@example.com")
    secret = _enroll_and_confirm_totp(client, db_session, "stale@example.com")
    csrf = _login_with_totp(client, "stale@example.com", secret)

    resident, car, invoice, method = _resident_with_invoice_and_method(
        db_session, building, "stale-resident@example.com", "STL0001"
    )

    # Backdating the session's step-up stamp past the 10 minute window,
    # simulating a manager who authenticated a while ago
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = db_session.get(UserSession, session_id)
    session.totp_verified_at = datetime.now(UTC) - timedelta(minutes=11)
    db_session.add(session)
    db_session.commit()

    response = client.post(
        f"/manager/invoices/{invoice.id}/record-payment",
        json={"amount_cents": 100, "method": "cash"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "stale-1"},
    )
    assert response.status_code == 403
    assert "step-up" in response.json()["detail"]


def test_fresh_totp_stepup_allows_money_action(client, db_session, building):
    make_user(db_session, building.id, Role.manager, "fresh@example.com")
    secret = _enroll_and_confirm_totp(client, db_session, "fresh@example.com")
    csrf = _login_with_totp(client, "fresh@example.com", secret)

    resident, car, invoice, method = _resident_with_invoice_and_method(
        db_session, building, "fresh-resident@example.com", "FRS0001"
    )

    response = client.post(
        f"/manager/invoices/{invoice.id}/record-payment",
        json={"amount_cents": invoice.total_cents, "method": "cash"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "fresh-1"},
    )
    assert response.status_code == 200, response.text


def test_plate_collision_same_building_409_cross_building_allowed(db_session, building):
    manager = make_user(db_session, building.id, Role.manager, "plate-manager@example.com")
    resident = make_user(db_session, building.id, Role.resident, "plate-resident@example.com")
    plan = _make_plan(db_session, building)

    create_car(
        db_session,
        building,
        manager,
        resident.id,
        "Honda",
        "Civic",
        "blue",
        "DUPLICATE1",
        plan.id,
        None,
    )

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        create_car(
            db_session,
            building,
            manager,
            resident.id,
            "Toyota",
            "Camry",
            "red",
            "DUPLICATE1",
            plan.id,
            None,
        )
    assert exc_info.value.status_code == 409

    other_building = Building(name="Other Tower", timezone="UTC")
    db_session.add(other_building)
    db_session.commit()
    other_manager = make_user(
        db_session, other_building.id, Role.manager, "other-manager@example.com"
    )
    other_resident = make_user(
        db_session, other_building.id, Role.resident, "other-resident@example.com"
    )
    other_plan = _make_plan(db_session, other_building)

    other_car = create_car(
        db_session,
        other_building,
        other_manager,
        other_resident.id,
        "Honda",
        "Civic",
        "blue",
        "DUPLICATE1",
        other_plan.id,
        None,
    )
    assert other_car.license_plate == "DUPLICATE1"
