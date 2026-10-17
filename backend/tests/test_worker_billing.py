"""Worker jobs: issue_invoices, charge_autopay, retry_failed, mark_past_due,
send_notifications. Each is called with an injectable clock so behavior at
a specific date is deterministic and testable, and each is safe to call
twice for the same day.
"""

from datetime import UTC, date, datetime

from app.billing.credits import get_or_create_billing_account
from app.billing.ledger import invoice_paid_cents
from app.models import (
    Car,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    Plan,
    PlanPrice,
    Role,
)
from app.worker_billing import charge_autopay, issue_invoices, mark_past_due, retry_failed

from tests.conftest import make_user


def _plan(db_session, building, monthly_cents=10000):
    plan = Plan(building_id=building.id, name="Worker Plan", size_class="sedan")
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        PlanPrice(plan_id=plan.id, effective_month=date(2020, 1, 1), monthly_cents=monthly_cents)
    )
    db_session.commit()
    return plan


def _car(db_session, building, resident, plan, plate, started_on):
    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        plan_id=plan.id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate=plate,
        started_on=started_on,
    )
    db_session.add(car)
    db_session.commit()
    return car


def test_issue_invoices_only_fires_on_or_after_the_20th(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "issue@example.com")
    plan = _plan(db_session, building)
    _car(db_session, building, resident, plan, "ISS0001", date(2026, 7, 1))

    before = datetime(2026, 6, 19, 18, 0, tzinfo=UTC)
    created_before = issue_invoices(db_session, before)
    assert created_before == 0

    on_the_day = datetime(2026, 6, 20, 18, 0, tzinfo=UTC)
    created_on_day = issue_invoices(db_session, on_the_day)
    assert created_on_day == 1

    # Calling again the same day (or later) creates no duplicate
    again = issue_invoices(db_session, datetime(2026, 6, 21, 18, 0, tzinfo=UTC))
    assert again == 0


def test_charge_autopay_charges_open_invoices_on_the_1st(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "charge@example.com")
    plan = _plan(db_session, building, monthly_cents=9000)
    _car(db_session, building, resident, plan, "CHG0001", date(2026, 5, 1))

    issue_invoices(db_session, datetime(2026, 5, 20, 18, 0, tzinfo=UTC))
    invoice = db_session.query(Invoice).filter(Invoice.building_id == building.id).one()

    billing_account = get_or_create_billing_account(db_session, resident.id, building.id)
    method = PaymentMethod(
        billing_account_id=billing_account.id,
        provider="fake",
        provider_customer_id="cus_1",
        provider_method_id="pm_1",
        kind="card",
        brand="visa",
        last4="4242",
    )
    db_session.add(method)
    db_session.flush()
    billing_account.autopay_enabled = True
    billing_account.default_payment_method_id = method.id
    db_session.add(billing_account)
    db_session.commit()

    not_yet = charge_autopay(db_session, datetime(2026, 5, 31, 18, 0, tzinfo=UTC))
    assert not_yet == 0

    charged = charge_autopay(db_session, datetime(2026, 6, 1, 18, 0, tzinfo=UTC))
    assert charged == 1
    assert invoice_paid_cents(db_session, invoice.id) == invoice.total_cents
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.paid

    # Running again the same day does not double charge
    again = charge_autopay(db_session, datetime(2026, 6, 1, 18, 0, tzinfo=UTC))
    assert again == 0
    payments = list(db_session.query(Payment).filter(Payment.invoice_id == invoice.id))
    assert len(payments) == 1


def test_retry_failed_retries_on_day_3_and_7_only(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "retry@example.com")
    plan = _plan(db_session, building, monthly_cents=5000)
    _car(db_session, building, resident, plan, "RTY0001", date(2026, 5, 1))
    issue_invoices(db_session, datetime(2026, 5, 20, 18, 0, tzinfo=UTC))
    invoice = db_session.query(Invoice).filter(Invoice.building_id == building.id).one()

    billing_account = get_or_create_billing_account(db_session, resident.id, building.id)
    method = PaymentMethod(
        billing_account_id=billing_account.id,
        provider="fake",
        provider_customer_id="cus_2",
        provider_method_id="pm_fail",
        kind="card",
        brand="visa",
        last4="0002",
        fake_behavior="decline",
    )
    db_session.add(method)
    db_session.flush()
    billing_account.autopay_enabled = True
    billing_account.default_payment_method_id = method.id
    db_session.add(billing_account)
    db_session.commit()

    charge_autopay(db_session, datetime(2026, 6, 1, 18, 0, tzinfo=UTC))
    assert db_session.query(Payment).filter(Payment.invoice_id == invoice.id).count() == 1

    # Day 2: no retry yet
    assert retry_failed(db_session, datetime(2026, 6, 3, 18, 0, tzinfo=UTC)) == 0
    # Day 3: retries (still declining)
    assert retry_failed(db_session, datetime(2026, 6, 4, 18, 0, tzinfo=UTC)) == 1
    assert db_session.query(Payment).filter(Payment.invoice_id == invoice.id).count() == 2
    # Same day again: no second retry
    assert retry_failed(db_session, datetime(2026, 6, 4, 18, 0, tzinfo=UTC)) == 0
    # Day 7 (after the latest failure on day 3): retries again
    assert retry_failed(db_session, datetime(2026, 6, 7, 18, 0, tzinfo=UTC)) == 1
    assert db_session.query(Payment).filter(Payment.invoice_id == invoice.id).count() == 3


def test_mark_past_due_from_the_2nd(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "pastdue@example.com")
    plan = _plan(db_session, building, monthly_cents=6000)
    _car(db_session, building, resident, plan, "PDU0001", date(2026, 5, 1))
    issue_invoices(db_session, datetime(2026, 5, 20, 18, 0, tzinfo=UTC))
    invoice = db_session.query(Invoice).filter(Invoice.building_id == building.id).one()

    marked_day1 = mark_past_due(db_session, datetime(2026, 6, 1, 18, 0, tzinfo=UTC))
    assert marked_day1 == 0
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.open

    marked_day2 = mark_past_due(db_session, datetime(2026, 6, 2, 18, 0, tzinfo=UTC))
    assert marked_day2 == 1
    assert db_session.get(Invoice, invoice.id).status == InvoiceStatus.past_due
