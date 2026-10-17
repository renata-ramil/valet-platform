"""FakeProvider behavior: success, decline then retry success, requires_action,
delayed bank settlement, and both webhook orderings (before and after the
API response)."""

import json
from datetime import UTC, date, datetime

from app.billing.charge import charge_invoice, mark_payment_succeeded
from app.billing.invoices import generate_invoices_for_period
from app.models import Car, Invoice, InvoiceStatus, Payment, PaymentStatus, Plan, PlanPrice, Role
from app.payments.fake_provider import FakeProvider

from tests.conftest import make_user


def _invoice_for_resident(db_session, building, monthly_cents=10000):
    resident = make_user(
        db_session, building.id, Role.resident, f"payer-{monthly_cents}@example.com"
    )
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
        license_plate=f"PAY{monthly_cents}"[:8],
        started_on=date(2026, 6, 1),
    )
    db_session.add(car)
    db_session.commit()

    now = datetime(2026, 6, 25, tzinfo=UTC)
    invoice = generate_invoices_for_period(db_session, building, 2026, 6, now)[0]
    return resident, invoice


def _method(provider, billing_account_id, fake_token):
    details = provider.setup_payment_method(
        billing_account_id, "resident@example.com", "card", fake_token
    )
    return details


def test_fake_provider_success(db_session, building):
    resident, invoice = _invoice_for_resident(db_session, building, 11000)
    provider = FakeProvider()
    details = _method(provider, "fake-account", "ok")
    from app.models import PaymentMethod

    method = PaymentMethod(
        billing_account_id=invoice.billing_account_id,
        provider="fake",
        provider_customer_id=details.provider_customer_id,
        provider_method_id=details.provider_method_id,
        kind=details.kind,
        brand=details.brand,
        last4=details.last4,
        fake_behavior=details.fake_behavior,
    )
    db_session.add(method)
    db_session.commit()

    payment = charge_invoice(
        db_session, provider, invoice, method, f"{invoice.id}:1", 1, actor_id=None
    )
    db_session.commit()
    assert payment.status == PaymentStatus.succeeded
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.paid


def test_fake_provider_decline_then_retry_success(db_session, building):
    resident, invoice = _invoice_for_resident(db_session, building, 12000)
    provider = FakeProvider()
    from app.models import PaymentMethod

    declining = _method(provider, "fake-account", "decline")
    method = PaymentMethod(
        billing_account_id=invoice.billing_account_id,
        provider="fake",
        provider_customer_id=declining.provider_customer_id,
        provider_method_id=declining.provider_method_id,
        kind=declining.kind,
        brand=declining.brand,
        last4=declining.last4,
        fake_behavior=declining.fake_behavior,
    )
    db_session.add(method)
    db_session.commit()

    first = charge_invoice(
        db_session, provider, invoice, method, f"{invoice.id}:1", 1, actor_id=None
    )
    db_session.commit()
    assert first.status == PaymentStatus.failed
    assert first.failure_reason == "card_declined"
    assert db_session.get(Invoice, invoice.id).status != InvoiceStatus.paid

    # Resident updates their card to a working one and retries
    working = _method(provider, "fake-account", "ok")
    method.provider_method_id = working.provider_method_id
    method.fake_behavior = working.fake_behavior
    db_session.add(method)
    db_session.commit()

    second = charge_invoice(
        db_session, provider, invoice, method, f"{invoice.id}:2", 2, actor_id=None
    )
    db_session.commit()
    assert second.status == PaymentStatus.succeeded
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.paid


def test_fake_provider_requires_action(db_session, building):
    resident, invoice = _invoice_for_resident(db_session, building, 9000)
    provider = FakeProvider()
    from app.models import PaymentMethod

    details = _method(provider, "fake-account", "requires_action")
    method = PaymentMethod(
        billing_account_id=invoice.billing_account_id,
        provider="fake",
        provider_customer_id=details.provider_customer_id,
        provider_method_id=details.provider_method_id,
        kind=details.kind,
        brand=details.brand,
        last4=details.last4,
        fake_behavior=details.fake_behavior,
    )
    db_session.add(method)
    db_session.commit()

    payment = charge_invoice(
        db_session, provider, invoice, method, f"{invoice.id}:1", 1, actor_id=None
    )
    db_session.commit()
    assert payment.status == PaymentStatus.requires_action
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.processing


def test_fake_provider_delayed_bank_settlement_then_webhook_settles(db_session, building, client):
    resident, invoice = _invoice_for_resident(db_session, building, 7000)
    provider = FakeProvider()
    from app.models import PaymentMethod

    details = _method(provider, "fake-account", "delayed_settle")
    method = PaymentMethod(
        billing_account_id=invoice.billing_account_id,
        provider="fake",
        provider_customer_id=details.provider_customer_id,
        provider_method_id=details.provider_method_id,
        kind=details.kind,
        brand=details.brand,
        last4=details.last4,
        fake_behavior=details.fake_behavior,
    )
    db_session.add(method)
    db_session.commit()

    payment = charge_invoice(
        db_session, provider, invoice, method, f"{invoice.id}:1", 1, actor_id=None
    )
    db_session.commit()
    assert payment.status == PaymentStatus.pending
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.processing

    # A few days later the bank settlement completes; this is signalled by
    # a webhook, which converges the state regardless of arrival order
    event = {
        "id": "evt_settle_1",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": payment.provider_payment_id}},
    }
    body = json.dumps(event).encode()
    signature = provider.sign(body)
    response = client.post(
        "/webhooks/stripe", content=body, headers={"Stripe-Signature": signature}
    )
    assert response.status_code == 200
    assert db_session.get(Payment, payment.id).status == PaymentStatus.succeeded
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.paid


def test_webhook_before_api_response_is_idempotent_with_api_response_after(
    db_session, building, client
):
    """The webhook can arrive first; mark_payment_succeeded is a no-op the
    second time, whichever path calls it second."""
    resident, invoice = _invoice_for_resident(db_session, building, 8000)
    provider = FakeProvider()
    from app.models import PaymentMethod

    details = _method(provider, "fake-account", "delayed_settle")
    method = PaymentMethod(
        billing_account_id=invoice.billing_account_id,
        provider="fake",
        provider_customer_id=details.provider_customer_id,
        provider_method_id=details.provider_method_id,
        kind=details.kind,
        brand=details.brand,
        last4=details.last4,
        fake_behavior=details.fake_behavior,
    )
    db_session.add(method)
    db_session.commit()

    payment = charge_invoice(
        db_session, provider, invoice, method, f"{invoice.id}:1", 1, actor_id=None
    )
    db_session.commit()

    # Webhook arrives first
    event = {
        "id": "evt_settle_2",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": payment.provider_payment_id}},
    }
    body = json.dumps(event).encode()
    signature = provider.sign(body)
    first_response = client.post(
        "/webhooks/stripe", content=body, headers={"Stripe-Signature": signature}
    )
    assert first_response.status_code == 200
    assert db_session.get(Payment, payment.id).status == PaymentStatus.succeeded

    # The API-side call also tries to mark it succeeded (as if the original
    # HTTP request were still resolving); this must be a safe no-op
    mark_payment_succeeded(db_session, db_session.get(Payment, payment.id), actor_id=None)
    db_session.commit()
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.paid

    # A replayed webhook changes nothing further
    replay_response = client.post(
        "/webhooks/stripe", content=body, headers={"Stripe-Signature": signature}
    )
    assert replay_response.status_code == 200
    assert replay_response.json()["status"] == "ignored_duplicate"


def test_webhook_bad_signature_is_rejected(client):
    body = json.dumps(
        {"id": "evt_bad", "type": "payment_intent.succeeded", "data": {"object": {}}}
    ).encode()
    response = client.post(
        "/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": "sha256=not-a-real-signature"},
    )
    assert response.status_code == 400
