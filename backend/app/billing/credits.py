"""Resident credit balance: issuing, applying, and the stranded-credit refund proposal."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.ledger import now_utc, post_credit_applied, post_credit_issued
from app.billing.proration import month_bounds, prorate_cents
from app.models import (
    ApprovalKind,
    ApprovalRequest,
    ApprovalStatus,
    BillingAccount,
    Building,
    Car,
    CreditBalance,
    Invoice,
    InvoiceStatus,
)


def get_or_create_billing_account(
    db: Session, resident_id: str, building_id: str
) -> BillingAccount:
    account = db.scalar(select(BillingAccount).where(BillingAccount.resident_id == resident_id))
    if account is not None:
        return account
    account = BillingAccount(building_id=building_id, resident_id=resident_id)
    db.add(account)
    db.flush()
    db.add(CreditBalance(billing_account_id=account.id, balance_cents=0))
    db.flush()
    return account


def get_credit_balance(db: Session, billing_account_id: str) -> CreditBalance:
    balance = db.scalar(
        select(CreditBalance).where(CreditBalance.billing_account_id == billing_account_id)
    )
    if balance is not None:
        return balance
    balance = CreditBalance(billing_account_id=billing_account_id, balance_cents=0)
    db.add(balance)
    db.flush()
    return balance


def issue_credit(
    db: Session,
    building_id: str,
    billing_account_id: str,
    amount_cents: int,
    memo: str,
    actor_id: str | None,
    invoice_id: str | None = None,
) -> CreditBalance:
    if amount_cents <= 0:
        raise ValueError("Credit amount must be positive")
    post_credit_issued(
        db, building_id, billing_account_id, amount_cents, memo, actor_id, invoice_id
    )
    balance = get_credit_balance(db, billing_account_id)
    balance.balance_cents += amount_cents
    balance.updated_at = now_utc()
    db.add(balance)
    db.flush()
    append_audit_event(
        db,
        building_id,
        "credit_balance",
        billing_account_id,
        "issued",
        {"amount_cents": amount_cents, "memo": memo, "invoice_id": invoice_id},
        actor_id=actor_id,
    )
    return balance


def apply_credit_to_invoice(db: Session, invoice: Invoice, actor_id: str | None) -> int:
    """Applies as much stored credit as the invoice needs (and has), never over."""
    from app.billing.ledger import invoice_paid_cents

    balance = get_credit_balance(db, invoice.billing_account_id)
    if balance.balance_cents <= 0:
        return 0
    already_paid = invoice_paid_cents(db, invoice.id)
    remaining = invoice.total_cents - already_paid
    if remaining <= 0:
        return 0
    apply_amount = min(balance.balance_cents, remaining)
    if apply_amount <= 0:
        return 0

    post_credit_applied(db, invoice, apply_amount, actor_id)
    balance.balance_cents -= apply_amount
    balance.updated_at = now_utc()
    db.add(balance)
    db.flush()

    new_paid = invoice_paid_cents(db, invoice.id)
    if new_paid >= invoice.total_cents and invoice.status in (
        InvoiceStatus.open,
        InvoiceStatus.past_due,
        InvoiceStatus.processing,
    ):
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now_utc()
        db.add(invoice)

    append_audit_event(
        db,
        invoice.building_id,
        "invoice",
        invoice.id,
        "credit_applied",
        {"amount_cents": apply_amount},
        actor_id=actor_id,
    )
    return apply_amount


def create_refund_proposal(
    db: Session,
    building_id: str,
    billing_account_id: str,
    amount_cents: int,
    reason: str,
    requested_by: str,
) -> ApprovalRequest:
    proposal = ApprovalRequest(
        building_id=building_id,
        kind=ApprovalKind.refund,
        billing_account_id=billing_account_id,
        amount_cents=amount_cents,
        reason=reason,
        requested_by=requested_by,
        status=ApprovalStatus.pending,
    )
    db.add(proposal)
    db.flush()
    append_audit_event(
        db,
        building_id,
        "approval_request",
        proposal.id,
        "proposed",
        {"kind": "refund", "amount_cents": amount_cents, "reason": reason},
        actor_id=requested_by,
    )
    return proposal


def end_car_credit(db: Session, car: Car, building: Building, now, actor_id: str | None) -> int:
    """Credits unused days in the current billing month when a car is ended.

    Applies the credit to the resident's most relevant open invoice right
    away when one exists; otherwise it becomes a refund proposal per
    docs/BILLING.md decision 5 (a final credit with no next invoice).
    """
    from app.billing.invoices import plan_price_cents

    if car.plan_id is None or car.ended_on is None:
        return 0

    local_today = now.astimezone(ZoneInfo(building.timezone)).date()
    period_start, period_end = month_bounds(local_today.year, local_today.month)
    unused_start = max(car.ended_on + timedelta(days=1), period_start)
    if unused_start > period_end:
        return 0
    unused_days = (period_end - unused_start).days + 1
    days_in_period = (period_end - period_start).days + 1

    try:
        monthly_cents = plan_price_cents(db, car.plan_id, period_start)
    except ValueError:
        return 0
    credit_amount = prorate_cents(monthly_cents, unused_days, days_in_period)
    if credit_amount <= 0:
        return 0

    billing_account = get_or_create_billing_account(db, car.owner_id, building.id)
    issue_credit(
        db,
        building.id,
        billing_account.id,
        credit_amount,
        f"Unused days credit for ended car {car.id}",
        actor_id,
    )

    open_invoice = db.scalar(
        select(Invoice)
        .where(
            Invoice.billing_account_id == billing_account.id,
            Invoice.status.in_([InvoiceStatus.open, InvoiceStatus.past_due]),
        )
        .order_by(Invoice.period_start.desc())
    )
    if open_invoice is not None:
        apply_credit_to_invoice(db, open_invoice, actor_id)
    else:
        remaining_cars = db.scalar(
            select(Car).where(
                Car.owner_id == car.owner_id,
                Car.building_id == building.id,
                Car.id != car.id,
                Car.status != "ended",
            )
        )
        if remaining_cars is None and actor_id is not None:
            # No other active car and nothing open to apply to: propose a refund
            balance = get_credit_balance(db, billing_account.id)
            if balance.balance_cents > 0:
                create_refund_proposal(
                    db,
                    building.id,
                    billing_account.id,
                    balance.balance_cents,
                    f"Unused days credit for ended car {car.id} with no upcoming invoice",
                    actor_id,
                )
    return credit_amount
