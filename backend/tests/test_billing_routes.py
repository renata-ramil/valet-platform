"""Resident billing routes: summary, invoices, receipt, payment methods, autopay, pay."""

from datetime import UTC, date, datetime

from app.billing.invoices import generate_invoices_for_period
from app.models import Car, Plan, PlanPrice, Role

from tests.conftest import make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _resident_with_invoice(client, db_session, building, email, plate, monthly_cents=12000):
    resident = make_user(db_session, building.id, Role.resident, email)
    plan = Plan(building_id=building.id, name="Standard", size_class="sedan")
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        PlanPrice(plan_id=plan.id, effective_month=date(2020, 1, 1), monthly_cents=monthly_cents)
    )
    db_session.commit()
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
    return resident, invoice


def test_billing_summary_lists_cars_and_amount_due(client, db_session, building):
    resident, invoice = _resident_with_invoice(
        client, db_session, building, "summary@example.com", "SUM0001", monthly_cents=20000
    )
    csrf = _login(client, "summary@example.com")
    response = client.get("/billing/summary", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    body = response.json()
    assert body["amount_due_cents"] == 20000
    assert body["autopay_enabled"] is False
    assert len(body["cars"]) == 1
    assert body["cars"][0]["license_plate"] == "SUM0001"


def test_invoice_list_and_detail(client, db_session, building):
    resident, invoice = _resident_with_invoice(
        client, db_session, building, "list@example.com", "LST0001"
    )
    csrf = _login(client, "list@example.com")

    listing = client.get("/billing/invoices", headers={"X-CSRF-Token": csrf})
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = client.get(f"/billing/invoices/{invoice.id}", headers={"X-CSRF-Token": csrf})
    assert detail.status_code == 200
    assert detail.json()["total_cents"] == invoice.total_cents
    assert len(detail.json()["lines"]) == 1


def test_receipt_is_a_valid_pdf(client, db_session, building):
    resident, invoice = _resident_with_invoice(
        client, db_session, building, "receipt@example.com", "REC0001"
    )
    csrf = _login(client, "receipt@example.com")

    response = client.get(f"/billing/invoices/{invoice.id}/receipt", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-1.4")
    assert response.content.rstrip().endswith(b"%%EOF")


def test_payment_method_setup_list_and_delete(client, db_session, building):
    resident, invoice = _resident_with_invoice(
        client, db_session, building, "method@example.com", "MTH0001"
    )
    csrf = _login(client, "method@example.com")

    setup = client.post(
        "/billing/payment-methods/setup",
        json={"kind": "card", "fake_token": "ok"},
        headers={"X-CSRF-Token": csrf},
    )
    assert setup.status_code == 201, setup.text
    method_id = setup.json()["id"]
    assert setup.json()["last4"]

    listing = client.get("/billing/payment-methods", headers={"X-CSRF-Token": csrf})
    assert len(listing.json()) == 1

    delete = client.delete(f"/billing/payment-methods/{method_id}", headers={"X-CSRF-Token": csrf})
    assert delete.status_code == 204

    listing_after = client.get("/billing/payment-methods", headers={"X-CSRF-Token": csrf})
    assert listing_after.json() == []


def test_cannot_remove_only_method_while_autopay_is_on(client, db_session, building):
    resident, invoice = _resident_with_invoice(
        client, db_session, building, "autopay@example.com", "AUT0001"
    )
    csrf = _login(client, "autopay@example.com")

    setup = client.post(
        "/billing/payment-methods/setup",
        json={"kind": "card", "fake_token": "ok"},
        headers={"X-CSRF-Token": csrf},
    )
    method_id = setup.json()["id"]

    enable = client.patch(
        "/billing/autopay", json={"enabled": True}, headers={"X-CSRF-Token": csrf}
    )
    assert enable.status_code == 200
    assert enable.json()["autopay_enabled"] is True

    delete = client.delete(f"/billing/payment-methods/{method_id}", headers={"X-CSRF-Token": csrf})
    assert delete.status_code == 409

    disable = client.patch(
        "/billing/autopay", json={"enabled": False}, headers={"X-CSRF-Token": csrf}
    )
    assert disable.status_code == 200
    delete_after = client.delete(
        f"/billing/payment-methods/{method_id}", headers={"X-CSRF-Token": csrf}
    )
    assert delete_after.status_code == 204


def test_pay_invoice_with_declining_card_marks_payment_failed(client, db_session, building):
    resident, invoice = _resident_with_invoice(
        client, db_session, building, "decline@example.com", "DEC0001"
    )
    csrf = _login(client, "decline@example.com")

    setup = client.post(
        "/billing/payment-methods/setup",
        json={"kind": "card", "fake_token": "decline"},
        headers={"X-CSRF-Token": csrf},
    )
    method_id = setup.json()["id"]

    pay = client.post(
        f"/billing/invoices/{invoice.id}/pay",
        json={"payment_method_id": method_id},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "decline-attempt-1"},
    )
    assert pay.status_code == 200
    assert pay.json()["status"] == "failed"

    detail = client.get(f"/billing/invoices/{invoice.id}", headers={"X-CSRF-Token": csrf})
    assert detail.json()["status"] != "paid"


def test_pay_invoice_with_working_card_marks_invoice_paid(client, db_session, building):
    resident, invoice = _resident_with_invoice(
        client, db_session, building, "succeed@example.com", "SUC0001"
    )
    csrf = _login(client, "succeed@example.com")

    setup = client.post(
        "/billing/payment-methods/setup",
        json={"kind": "card", "fake_token": "ok"},
        headers={"X-CSRF-Token": csrf},
    )
    method_id = setup.json()["id"]

    pay = client.post(
        f"/billing/invoices/{invoice.id}/pay",
        json={"payment_method_id": method_id},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "succeed-attempt-1"},
    )
    assert pay.status_code == 200
    assert pay.json()["status"] == "succeeded"

    detail = client.get(f"/billing/invoices/{invoice.id}", headers={"X-CSRF-Token": csrf})
    assert detail.json()["status"] == "paid"
    assert detail.json()["paid_cents"] == invoice.total_cents
