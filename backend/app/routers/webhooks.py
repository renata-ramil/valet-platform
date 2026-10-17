import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.charge import mark_payment_failed, mark_payment_succeeded
from app.db import get_db
from app.models import Payment, PaymentMethod, WebhookEvent
from app.payments.base import SignatureVerificationError
from app.payments.registry import get_payment_provider

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Verifies the signature, stores each provider event id once (replays are
    a no-op) and converges payment state whichever order the API response and
    this webhook arrive in. Works the same way under FakeProvider (signed with
    its own shared secret) as under the real Stripe signature.
    """
    raw_body = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    provider = get_payment_provider()
    try:
        event = provider.verify_webhook(raw_body, signature)
    except SignatureVerificationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook signature") from exc

    event_id = event.get("id")
    event_type = event.get("type", "")
    if not event_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing event id")

    existing = db.scalar(select(WebhookEvent).where(WebhookEvent.provider_event_id == event_id))
    if existing is not None:
        # Replay protection: the same provider event id never acts twice
        return {"status": "ignored_duplicate"}

    record = WebhookEvent(
        provider=provider.name,
        provider_event_id=event_id,
        event_type=event_type,
        payload=json.dumps(event, default=str),
    )
    db.add(record)
    db.flush()

    data_object = (event.get("data") or {}).get("object") or {}
    subject_id = data_object.get("id")

    if event_type == "payment_intent.succeeded" and subject_id:
        payment = db.scalar(select(Payment).where(Payment.provider_payment_id == subject_id))
        if payment is not None:
            mark_payment_succeeded(db, payment, actor_id=None)
    elif event_type == "payment_intent.payment_failed" and subject_id:
        payment = db.scalar(select(Payment).where(Payment.provider_payment_id == subject_id))
        if payment is not None:
            reason = (data_object.get("last_payment_error") or {}).get("message", "payment_failed")
            mark_payment_failed(db, payment, reason, actor_id=None)
    elif event_type == "setup_intent.succeeded" and subject_id and provider.name == "stripe":
        method = db.scalar(
            select(PaymentMethod).where(PaymentMethod.provider_method_id == subject_id)
        )
        if method is not None:
            details = provider.resolve_setup_intent(subject_id)
            method.provider_method_id = details.provider_method_id
            method.kind = details.kind
            method.brand = details.brand
            method.last4 = details.last4
            method.exp_month = details.exp_month
            method.exp_year = details.exp_year
            method.is_active = True
            db.add(method)

    record.processed_at = datetime.now(UTC)
    db.add(record)
    db.commit()
    return {"status": "processed", "type": event_type}
