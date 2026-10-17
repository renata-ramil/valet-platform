"""Charging a payment method against an invoice, and converging the result
whether it arrives through the synchronous API call or a later webhook."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.ledger import post_payment_succeeded, post_refund
from app.models import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.payments.base import MethodDetails, PaymentProvider


def _method_to_details(method: PaymentMethod) -> MethodDetails:
    return MethodDetails(
        provider_customer_id=method.provider_customer_id,
        provider_method_id=method.provider_method_id,
        kind=method.kind,
        brand=method.brand,
        last4=method.last4,
        exp_month=method.exp_month,
        exp_year=method.exp_year,
        fake_behavior=method.fake_behavior,
    )


_STATUS_MAP = {
    "succeeded": PaymentStatus.succeeded,
    "failed": PaymentStatus.failed,
    "requires_action": PaymentStatus.requires_action,
    "processing": PaymentStatus.pending,
}


def mark_payment_succeeded(
    db: Session, payment: Payment, actor_id: str | None = None, now: datetime | None = None
) -> None:
    """Idempotent: a no-op if this payment already succeeded. Called from the
    synchronous charge path and from the webhook path, whichever arrives first."""
    if payment.status == PaymentStatus.succeeded:
        return
    now = now or datetime.now(UTC)
    payment.status = PaymentStatus.succeeded
    payment.settled_at = now
    db.add(payment)
    db.flush()
    post_payment_succeeded(db, payment, actor_id=actor_id)

    invoice = db.get(Invoice, payment.invoice_id)
    from app.billing.ledger import invoice_paid_cents

    if invoice is not None and invoice_paid_cents(db, invoice.id) >= invoice.total_cents:
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now
        db.add(invoice)
    append_audit_event(
        db,
        payment.building_id,
        "payment",
        payment.id,
        "succeeded",
        {"amount_cents": payment.amount_cents, "invoice_id": payment.invoice_id},
        actor_id=actor_id,
    )


def mark_payment_failed(
    db: Session, payment: Payment, failure_reason: str, actor_id: str | None = None
) -> None:
    if payment.status == PaymentStatus.failed:
        return
    payment.status = PaymentStatus.failed
    payment.failure_reason = failure_reason
    db.add(payment)
    db.flush()
    append_audit_event(
        db,
        payment.building_id,
        "payment",
        payment.id,
        "failed",
        {"failure_reason": failure_reason},
        actor_id=actor_id,
    )


def charge_invoice(
    db: Session,
    provider: PaymentProvider,
    invoice: Invoice,
    method: PaymentMethod,
    idempotency_key: str,
    attempt_no: int,
    actor_id: str | None = None,
    now: datetime | None = None,
) -> Payment:
    """Charges `method` for the invoice's total. `now` is the worker's or the
    request's own clock: it stamps the Payment's created_at so day-based
    logic (retry_failed, dunning) works correctly under a simulated clock in
    tests, not only against the real wall clock.
    """
    now = now or datetime.now(UTC)
    details = _method_to_details(method)
    result = provider.charge(details, invoice.total_cents, idempotency_key)

    # mark_payment_succeeded guards against re-running on an already
    # succeeded payment (that is what makes a replayed webhook a no-op), so
    # a freshly succeeding charge must not start out already marked
    # succeeded here, or that guard would skip the ledger posting entirely
    initial_status = (
        PaymentStatus.pending if result.status == "succeeded" else _STATUS_MAP[result.status]
    )
    payment = Payment(
        building_id=invoice.building_id,
        invoice_id=invoice.id,
        billing_account_id=invoice.billing_account_id,
        method=method.kind,
        provider=provider.name,
        provider_payment_id=result.provider_payment_id,
        amount_cents=invoice.total_cents,
        status=initial_status,
        attempt_no=attempt_no,
        idempotency_key=idempotency_key,
        failure_reason=result.failure_reason,
        actor_id=actor_id,
        created_at=now,
    )
    db.add(payment)
    db.flush()

    if result.status == "succeeded":
        mark_payment_succeeded(db, payment, actor_id=actor_id, now=now)
    elif result.status == "failed":
        append_audit_event(
            db,
            invoice.building_id,
            "payment",
            payment.id,
            "failed",
            {"failure_reason": result.failure_reason},
            actor_id=actor_id,
        )
    else:
        if invoice.status == InvoiceStatus.open:
            invoice.status = InvoiceStatus.processing
            db.add(invoice)
        append_audit_event(
            db,
            invoice.building_id,
            "payment",
            payment.id,
            result.status,
            {},
            actor_id=actor_id,
        )
    return payment


def record_manual_payment(
    db: Session,
    invoice: Invoice,
    amount_cents: int,
    method: str,
    reference: str | None,
    actor_id: str,
    now: datetime | None = None,
) -> Payment:
    now = now or datetime.now(UTC)
    payment = Payment(
        building_id=invoice.building_id,
        invoice_id=invoice.id,
        billing_account_id=invoice.billing_account_id,
        method=method,
        provider="manual",
        amount_cents=amount_cents,
        status=PaymentStatus.succeeded,
        reference=reference,
        actor_id=actor_id,
        created_at=now,
        settled_at=now,
    )
    db.add(payment)
    db.flush()
    post_payment_succeeded(db, payment, actor_id=actor_id)
    from app.billing.ledger import invoice_paid_cents

    if invoice_paid_cents(db, invoice.id) >= invoice.total_cents:
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = now
        db.add(invoice)
    append_audit_event(
        db,
        invoice.building_id,
        "payment",
        payment.id,
        "recorded_manual",
        {"amount_cents": amount_cents, "method": method, "reference": reference},
        actor_id=actor_id,
    )
    return payment


def record_refund(
    db: Session,
    original_payment: Payment,
    amount_cents: int,
    reason: str,
    actor_id: str,
    now: datetime | None = None,
) -> Payment:
    now = now or datetime.now(UTC)
    refund = Payment(
        building_id=original_payment.building_id,
        invoice_id=original_payment.invoice_id,
        billing_account_id=original_payment.billing_account_id,
        method=original_payment.method,
        provider=original_payment.provider,
        amount_cents=amount_cents,
        status=PaymentStatus.succeeded,
        is_refund=True,
        refunded_payment_id=original_payment.id,
        reason=reason,
        actor_id=actor_id,
        created_at=now,
        settled_at=now,
    )
    db.add(refund)
    db.flush()
    post_refund(
        db,
        original_payment.building_id,
        original_payment.billing_account_id,
        amount_cents,
        f"Refund of payment {original_payment.id}: {reason}",
        actor_id,
        invoice_id=original_payment.invoice_id,
        payment_id=refund.id,
    )
    append_audit_event(
        db,
        original_payment.building_id,
        "payment",
        refund.id,
        "refunded",
        {
            "amount_cents": amount_cents,
            "reason": reason,
            "original_payment_id": original_payment.id,
        },
        actor_id=actor_id,
    )
    return refund
