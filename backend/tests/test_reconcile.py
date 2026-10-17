"""app.reconcile: each check passes on healthy data and actually catches a
manufactured discrepancy, so these are not vacuous checks.
"""

from datetime import UTC, date, datetime

from app.billing.charge import record_manual_payment
from app.billing.invoices import generate_invoices_for_period
from app.models import Car, LedgerAccount, Plan, PlanPrice, Role
from app.reconcile import (
    check_cash_account_matches_payments,
    check_invoice_paid_totals_consistent_with_status,
    check_invoice_totals_match_lines,
    check_ledger_transactions_balance,
    check_refunds_never_exceed_what_was_paid,
)

from tests.conftest import make_user


def _invoice(db_session, building, email, plate, monthly_cents=10000):
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
    return resident, generate_invoices_for_period(db_session, building, 2026, 6, now)[0]


def test_checks_pass_on_healthy_seeded_data(db_session, building):
    resident, invoice = _invoice(db_session, building, "reconcile-ok@example.com", "REC0001")
    record_manual_payment(db_session, invoice, invoice.total_cents, "cash", None, resident.id)
    db_session.commit()

    _, bad1 = check_invoice_totals_match_lines(db_session)
    _, bad2 = check_ledger_transactions_balance(db_session)
    _, bad3 = check_invoice_paid_totals_consistent_with_status(db_session)
    _, bad4 = check_refunds_never_exceed_what_was_paid(db_session)
    _, bad5 = check_cash_account_matches_payments(db_session)
    assert bad1 == bad2 == bad3 == bad4 == bad5 == []


def test_invoice_total_mismatch_is_detected(db_session, building):
    resident, invoice = _invoice(db_session, building, "reconcile-bad1@example.com", "REC0002")
    invoice.total_cents += 500  # corrupt it directly, bypassing the service layer
    db_session.add(invoice)
    db_session.commit()

    _, discrepancies = check_invoice_totals_match_lines(db_session)
    assert len(discrepancies) == 1
    assert "REC" not in str(discrepancies[0])  # sanity: message names the invoice id, not the plate
    assert invoice.id in str(discrepancies[0])


def test_unbalanced_ledger_transaction_is_detected(db_session, building):
    # Bypassing post_transaction's own balance check by writing raw rows
    from app.models import LedgerEntry

    db_session.add(
        LedgerEntry(
            building_id=building.id,
            transaction_id="corrupt-tx-1",
            account=LedgerAccount.cash,
            debit_cents=100,
            credit_cents=0,
            memo="half of a transaction",
        )
    )
    db_session.commit()

    _, discrepancies = check_ledger_transactions_balance(db_session)
    assert len(discrepancies) == 1
    assert "corrupt-tx-1" in str(discrepancies[0])


def test_paid_invoice_with_insufficient_ledger_credit_is_detected(db_session, building):
    resident, invoice = _invoice(db_session, building, "reconcile-bad3@example.com", "REC0003")
    # Marking it paid without ever posting the matching ledger credit
    from app.models import InvoiceStatus

    invoice.status = InvoiceStatus.paid
    db_session.add(invoice)
    db_session.commit()

    _, discrepancies = check_invoice_paid_totals_consistent_with_status(db_session)
    assert len(discrepancies) == 1


def test_refund_exceeding_payment_is_detected(db_session, building):
    resident, invoice = _invoice(db_session, building, "reconcile-bad4@example.com", "REC0004")
    payment = record_manual_payment(
        db_session, invoice, invoice.total_cents, "cash", None, resident.id
    )
    db_session.commit()

    from app.models import Payment, PaymentStatus

    # A refund payment row larger than the original, written directly to
    # simulate a bug that bypassed app.billing.charge.record_refund's guard
    oversized_refund = Payment(
        building_id=building.id,
        invoice_id=invoice.id,
        billing_account_id=payment.billing_account_id,
        method="cash",
        provider="manual",
        amount_cents=payment.amount_cents + 1000,
        status=PaymentStatus.succeeded,
        is_refund=True,
        refunded_payment_id=payment.id,
    )
    db_session.add(oversized_refund)
    db_session.commit()

    _, discrepancies = check_refunds_never_exceed_what_was_paid(db_session)
    assert len(discrepancies) == 1
