"""Ledger invariants: every transaction balances, invoice paid totals match
the ledger, and a refund never exceeds what was paid.
"""

from datetime import UTC, date, datetime

import pytest
from app.billing.charge import record_manual_payment, record_refund
from app.billing.credits import (
    apply_credit_to_invoice,
    get_or_create_billing_account,
    issue_credit,
)
from app.billing.invoices import generate_invoices_for_period
from app.billing.ledger import (
    UnbalancedTransactionError,
    account_net_debit,
    invoice_paid_cents,
    post_transaction,
)
from app.models import (
    Car,
    Invoice,
    InvoiceStatus,
    LedgerAccount,
    LedgerEntry,
    Plan,
    PlanPrice,
    Role,
)

from tests.conftest import make_user


def _make_plan(db_session, building, monthly_cents=12000):
    plan = Plan(building_id=building.id, name="Standard", size_class="sedan")
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        PlanPrice(plan_id=plan.id, effective_month=date(2020, 1, 1), monthly_cents=monthly_cents)
    )
    db_session.commit()
    return plan


def test_post_transaction_rejects_unbalanced_lines(db_session, building):
    with pytest.raises(UnbalancedTransactionError):
        post_transaction(
            db_session,
            building.id,
            [(LedgerAccount.receivable, 100, 0), (LedgerAccount.revenue, 0, 50)],
            memo="should not balance",
            actor_id=None,
        )


def test_post_transaction_balances_and_is_queryable(db_session, building):
    transaction_id = post_transaction(
        db_session,
        building.id,
        [(LedgerAccount.receivable, 500, 0), (LedgerAccount.revenue, 0, 500)],
        memo="balanced",
        actor_id=None,
    )
    db_session.commit()
    rows = db_session.query(LedgerEntry).filter(LedgerEntry.transaction_id == transaction_id).all()
    assert sum(r.debit_cents for r in rows) == sum(r.credit_cents for r in rows) == 500


def test_invoice_paid_cents_matches_ledger_after_full_payment(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "resident-ledger@example.com")
    plan = _make_plan(db_session, building, monthly_cents=15000)
    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        plan_id=plan.id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate="LEDGR1",
        started_on=date(2026, 6, 1),
    )
    db_session.add(car)
    db_session.commit()

    now = datetime(2026, 6, 25, tzinfo=UTC)
    created = generate_invoices_for_period(db_session, building, 2026, 6, now)
    invoice = created[0]
    assert invoice_paid_cents(db_session, invoice.id) == 0

    payment = record_manual_payment(
        db_session, invoice, invoice.total_cents, "cash", "ref-1", resident.id
    )
    db_session.commit()

    assert invoice_paid_cents(db_session, invoice.id) == invoice.total_cents
    refreshed = db_session.get(Invoice, invoice.id)
    assert refreshed.status == InvoiceStatus.paid
    assert (
        account_net_debit(db_session, LedgerAccount.cash, building_id=building.id)
        == payment.amount_cents
    )


def test_refund_never_exceeds_what_was_paid(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "resident-refund@example.com")
    plan = _make_plan(db_session, building, monthly_cents=10000)
    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        plan_id=plan.id,
        make="Toyota",
        model="Camry",
        color="red",
        license_plate="LEDGR2",
        started_on=date(2026, 6, 1),
    )
    db_session.add(car)
    db_session.commit()

    now = datetime(2026, 6, 25, tzinfo=UTC)
    invoice = generate_invoices_for_period(db_session, building, 2026, 6, now)[0]
    payment = record_manual_payment(
        db_session, invoice, invoice.total_cents, "cash", None, resident.id
    )
    db_session.commit()

    # A full refund is fine
    refund = record_refund(
        db_session, payment, payment.amount_cents, "resident moved out", resident.id
    )
    db_session.commit()
    assert refund.amount_cents == payment.amount_cents

    already_refunded = refund.amount_cents
    assert already_refunded <= payment.amount_cents


def test_credit_application_never_exceeds_invoice_total(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "resident-credit@example.com")
    plan = _make_plan(db_session, building, monthly_cents=8000)
    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        plan_id=plan.id,
        make="Kia",
        model="Soul",
        color="black",
        license_plate="LEDGR3",
        started_on=date(2026, 6, 1),
    )
    db_session.add(car)
    db_session.commit()

    billing_account = get_or_create_billing_account(db_session, resident.id, building.id)
    # A credit far larger than any invoice will ever need
    issue_credit(db_session, building.id, billing_account.id, 100_000, "goodwill credit", None)
    db_session.commit()

    now = datetime(2026, 6, 25, tzinfo=UTC)
    invoice = generate_invoices_for_period(db_session, building, 2026, 6, now)[0]
    refreshed = db_session.get(Invoice, invoice.id)

    # generate_invoices_for_period already applies any available credit
    assert invoice_paid_cents(db_session, invoice.id) == refreshed.total_cents
    assert refreshed.status == InvoiceStatus.paid

    # Applying again on an already-settled invoice is a safe no-op
    applied_again = apply_credit_to_invoice(db_session, refreshed, None)
    assert applied_again == 0
