"""Billing worker jobs: issue_invoices, charge_autopay, retry_failed,
send_notifications, mark_past_due. Each takes an injectable clock (`now`)
so it is testable at any date, runs in each building's local time, and is
safe to call more than once for the same day.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.charge import charge_invoice
from app.billing.invoices import generate_invoices_for_period
from app.billing.ledger import invoice_paid_cents
from app.billing.proration import next_month
from app.models import (
    BillingAccount,
    Building,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    User,
)
from app.notifications import get_notification_adapter
from app.payments.registry import get_payment_provider


def _local_today(building: Building, now: datetime):
    return now.astimezone(ZoneInfo(building.timezone)).date()


def issue_invoices(db: Session, now: datetime | None = None) -> int:
    """On and after the 20th local, issues next month's invoices for every
    building. generate_invoices_for_period is itself idempotent, so calling
    this more than once on or after the 20th creates no duplicates."""
    now = now or datetime.now(UTC)
    buildings = list(db.scalars(select(Building)))
    created_total = 0
    for index, building in enumerate(buildings, start=1):
        local_today = _local_today(building, now)
        if local_today.day >= 20:
            year, month = next_month(local_today.year, local_today.month)
            created = generate_invoices_for_period(db, building, year, month, now)
            created_total += len(created)
        if index % 10 == 0 or index == len(buildings):
            print(f"[issue_invoices] processed {index}/{len(buildings)} buildings")
    return created_total


def charge_autopay(db: Session, now: datetime | None = None) -> int:
    """On the 1st local, charges every open/past due invoice whose resident
    has autopay on and a default payment method, once per invoice per day."""
    now = now or datetime.now(UTC)
    buildings = list(db.scalars(select(Building)))
    charged = 0
    provider = get_payment_provider()
    for building in buildings:
        local_today = _local_today(building, now)
        if local_today.day != 1:
            continue
        invoices = list(
            db.scalars(
                select(Invoice).where(
                    Invoice.building_id == building.id,
                    Invoice.status.in_([InvoiceStatus.open, InvoiceStatus.past_due]),
                    Invoice.period_start == local_today.replace(day=1),
                )
            )
        )
        for index, invoice in enumerate(invoices, start=1):
            if invoice_paid_cents(db, invoice.id) >= invoice.total_cents:
                continue
            account = db.get(BillingAccount, invoice.billing_account_id)
            if (
                account is None
                or not account.autopay_enabled
                or not account.default_payment_method_id
            ):
                continue
            already_today = db.scalar(
                select(Payment).where(
                    Payment.invoice_id == invoice.id,
                    Payment.created_at
                    >= datetime.combine(local_today, datetime.min.time()).replace(tzinfo=UTC),
                )
            )
            if already_today is not None:
                continue
            method = db.get(PaymentMethod, account.default_payment_method_id)
            if method is None or not method.is_active:
                continue
            attempt_no = (
                len(list(db.scalars(select(Payment).where(Payment.invoice_id == invoice.id)))) + 1
            )
            charge_invoice(
                db,
                provider,
                invoice,
                method,
                f"{invoice.id}:{attempt_no}",
                attempt_no,
                actor_id=None,
                now=now,
            )
            charged += 1
            if index % 20 == 0 or index == len(invoices):
                print(f"[charge_autopay] {building.name}: charged {index}/{len(invoices)} invoices")
    db.commit()
    return charged


def retry_failed(db: Session, now: datetime | None = None) -> int:
    """Retries a failed autopay attempt 3 and 7 days after the failure."""
    now = now or datetime.now(UTC)
    provider = get_payment_provider()
    retried = 0
    buildings = list(db.scalars(select(Building)))
    for building in buildings:
        local_today = _local_today(building, now)
        invoices = list(
            db.scalars(
                select(Invoice).where(
                    Invoice.building_id == building.id,
                    Invoice.status.in_([InvoiceStatus.open, InvoiceStatus.past_due]),
                )
            )
        )
        for invoice in invoices:
            if invoice_paid_cents(db, invoice.id) >= invoice.total_cents:
                continue
            account = db.get(BillingAccount, invoice.billing_account_id)
            if (
                account is None
                or not account.autopay_enabled
                or not account.default_payment_method_id
            ):
                continue
            payments = list(
                db.scalars(
                    select(Payment)
                    .where(Payment.invoice_id == invoice.id)
                    .order_by(Payment.created_at.desc())
                )
            )
            if not payments or payments[0].status != PaymentStatus.failed:
                continue
            last_failed = payments[0]
            failed_date = last_failed.created_at.astimezone(ZoneInfo(building.timezone)).date()
            days_since = (local_today - failed_date).days
            if days_since not in (3, 7):
                continue
            already_today = any(
                p.created_at.astimezone(ZoneInfo(building.timezone)).date() == local_today
                for p in payments
            )
            if already_today:
                continue
            method = db.get(PaymentMethod, account.default_payment_method_id)
            if method is None or not method.is_active:
                continue
            attempt_no = len(payments) + 1
            charge_invoice(
                db,
                provider,
                invoice,
                method,
                f"{invoice.id}:{attempt_no}",
                attempt_no,
                actor_id=None,
                now=now,
            )
            retried += 1
    db.commit()
    print(f"[retry_failed] retried {retried} invoices")
    return retried


def mark_past_due(db: Session, now: datetime | None = None) -> int:
    """From the 2nd local, an unpaid open invoice becomes past_due. Never
    blocks a car request; purely a visibility state (docs/BILLING.md decision 13)."""
    now = now or datetime.now(UTC)
    marked = 0
    buildings = list(db.scalars(select(Building)))
    for building in buildings:
        local_today = _local_today(building, now)
        invoices = list(
            db.scalars(
                select(Invoice).where(
                    Invoice.building_id == building.id, Invoice.status == InvoiceStatus.open
                )
            )
        )
        for invoice in invoices:
            due_local = invoice.due_at.astimezone(ZoneInfo(building.timezone)).date()
            if local_today > due_local and invoice_paid_cents(db, invoice.id) < invoice.total_cents:
                invoice.status = InvoiceStatus.past_due
                db.add(invoice)
                append_audit_event(
                    db, building.id, "invoice", invoice.id, "past_due", {}, actor_id=None
                )
                marked += 1
    db.commit()
    print(f"[mark_past_due] marked {marked} invoices past due")
    return marked


def send_notifications(db: Session, now: datetime | None = None) -> int:
    """Dunning: at most one notification per resident per day, in priority
    order (receipt/failure for something that happened today, then the
    reminder, then past-due, then the final notice on day 10). Nothing is
    sent after day 10 except the manager's list."""
    now = now or datetime.now(UTC)
    sent = 0
    buildings = list(db.scalars(select(Building)))
    adapter = get_notification_adapter()
    for building in buildings:
        local_today = _local_today(building, now)
        notified_today: set[str] = set()
        invoices = list(db.scalars(select(Invoice).where(Invoice.building_id == building.id)))

        for invoice in invoices:
            if invoice.resident_id in notified_today:
                continue
            resident = db.get(User, invoice.resident_id)
            if resident is None:
                continue

            payments_today = [
                p
                for p in db.scalars(select(Payment).where(Payment.invoice_id == invoice.id))
                if p.created_at.astimezone(ZoneInfo(building.timezone)).date() == local_today
            ]
            succeeded_today = [p for p in payments_today if p.status == PaymentStatus.succeeded]
            failed_today = [p for p in payments_today if p.status == PaymentStatus.failed]

            if (
                invoice.issued_at is not None
                and invoice.issued_at.astimezone(ZoneInfo(building.timezone)).date() == local_today
            ):
                adapter.send(resident, f"Your invoice for {invoice.period_start} is ready.")
                notified_today.add(invoice.resident_id)
                sent += 1
            elif succeeded_today:
                adapter.send(resident, f"We received your payment for invoice {invoice.id}.")
                notified_today.add(invoice.resident_id)
                sent += 1
            elif failed_today:
                adapter.send(
                    resident,
                    f"Your payment for invoice {invoice.id} did not go through. "
                    f"Pay it at /billing/invoices/{invoice.id}.",
                )
                notified_today.add(invoice.resident_id)
                sent += 1
            else:
                account = db.get(BillingAccount, invoice.billing_account_id)
                due_local = invoice.due_at.astimezone(ZoneInfo(building.timezone)).date()
                days_past_due = (local_today - due_local).days
                if invoice.status in (InvoiceStatus.open, InvoiceStatus.past_due):
                    if days_past_due == -3 and account is not None and not account.autopay_enabled:
                        adapter.send(resident, f"Invoice {invoice.id} is due in 3 days.")
                        notified_today.add(invoice.resident_id)
                        sent += 1
                    elif days_past_due == 4:
                        adapter.send(resident, f"Invoice {invoice.id} is 5 days past due.")
                        notified_today.add(invoice.resident_id)
                        sent += 1
                    elif days_past_due == 9:
                        adapter.send(
                            resident, f"Final notice: invoice {invoice.id} is 10 days past due."
                        )
                        notified_today.add(invoice.resident_id)
                        sent += 1
        print(f"[send_notifications] {building.name}: sent {len(notified_today)} notifications")
    return sent


def run_all(db: Session, now: datetime | None = None) -> dict:
    """Runs every billing job once, in a sensible order, and returns counts."""
    now = now or datetime.now(UTC)
    results = {
        "issued": issue_invoices(db, now),
        "charged": charge_autopay(db, now),
        "retried": retry_failed(db, now),
        "past_due": mark_past_due(db, now),
        "notified": send_notifications(db, now),
    }
    print(f"[worker_billing] run_all: {results}")
    return results
