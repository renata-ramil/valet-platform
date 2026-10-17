import csv
import io
import json
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.charge import record_manual_payment, record_refund
from app.billing.credits import apply_credit_to_invoice, issue_credit
from app.billing.invoices import void_invoice
from app.billing.ledger import invoice_paid_cents
from app.billing.proration import month_bounds
from app.db import get_db
from app.deps import require_csrf, require_money_stepup, require_role
from app.idempotency import find_cached_response, require_idempotency_key, store_response
from app.models import (
    ApprovalKind,
    ApprovalRequest,
    ApprovalStatus,
    AuditEvent,
    Invoice,
    InvoiceStatus,
    LedgerEntry,
    Payment,
    PaymentStatus,
    Role,
    User,
)
from app.payments.registry import get_payment_provider
from app.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    IssueCreditRequest,
    PaymentResponse,
    RecordPaymentRequest,
    RefundRequest,
    VoidRequest,
)

router = APIRouter(
    prefix="/manager", tags=["manager-billing"], dependencies=[Depends(require_csrf)]
)

READ_ROLES = (Role.manager, Role.support)


def _invoice_or_404(db: Session, building_id: str, invoice_id: str) -> Invoice:
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.building_id == building_id)
    )
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


@router.get("/billing/overview")
def billing_overview(
    month: str = Query(..., description="YYYY-MM"),
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    year, month_num = (int(part) for part in month.split("-"))
    period_start, period_end = month_bounds(year, month_num)

    invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.building_id == user.building_id, Invoice.period_start == period_start
            )
        )
    )
    billed_cents = sum(i.total_cents for i in invoices)
    collected_cents = sum(invoice_paid_cents(db, i.id) for i in invoices)
    outstanding_cents = billed_cents - collected_cents
    past_due_count = sum(1 for i in invoices if i.status == InvoiceStatus.past_due)

    autopay_accounts = len({i.billing_account_id for i in invoices})
    from app.models import BillingAccount

    autopay_on = len(
        [
            1
            for i in invoices
            if db.get(BillingAccount, i.billing_account_id)
            and db.get(BillingAccount, i.billing_account_id).autopay_enabled
        ]
    )
    autopay_share = round(autopay_on / autopay_accounts, 3) if autopay_accounts else 0.0

    days_in_month = (period_end - period_start).days + 1
    collection_curve = []
    for day in range(1, days_in_month + 1):
        day_date = date(year, month_num, day)
        collected_by_day = sum(
            p.amount_cents
            for i in invoices
            for p in db.scalars(select(Payment).where(Payment.invoice_id == i.id)).all()
            if p.status == PaymentStatus.succeeded
            and p.settled_at is not None
            and p.settled_at.date() <= day_date
        )
        collection_curve.append({"day": day, "collected_cents": collected_by_day})

    needs_attention = [
        {
            "invoice_id": i.id,
            "resident_id": i.resident_id,
            "status": i.status,
            "total_cents": i.total_cents,
            "paid_cents": invoice_paid_cents(db, i.id),
            "due_at": i.due_at.isoformat(),
        }
        for i in invoices
        if i.status in (InvoiceStatus.past_due, InvoiceStatus.processing)
    ]

    return {
        "month": month,
        "billed_cents": billed_cents,
        "collected_cents": collected_cents,
        "outstanding_cents": outstanding_cents,
        "past_due_count": past_due_count,
        "autopay_share": autopay_share,
        "collection_curve": collection_curve,
        "needs_attention": needs_attention,
    }


@router.get("/invoices")
def manager_list_invoices(
    status_filter: str | None = Query(default=None, alias="status"),
    resident_id: str | None = Query(default=None),
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(Invoice).where(Invoice.building_id == user.building_id)
    if status_filter:
        query = query.where(Invoice.status == status_filter)
    if resident_id:
        query = query.where(Invoice.resident_id == resident_id)
    invoices = list(db.scalars(query.order_by(Invoice.period_start.desc())))
    return [
        {
            "id": i.id,
            "resident_id": i.resident_id,
            "period_start": str(i.period_start),
            "period_end": str(i.period_end),
            "status": i.status,
            "total_cents": i.total_cents,
            "paid_cents": invoice_paid_cents(db, i.id),
            "due_at": i.due_at.isoformat(),
            "is_adjustment": i.is_adjustment,
        }
        for i in invoices
    ]


@router.get("/invoices/{invoice_id}")
def manager_invoice_detail(
    invoice_id: str,
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    invoice = _invoice_or_404(db, user.building_id, invoice_id)
    payments = list(db.scalars(select(Payment).where(Payment.invoice_id == invoice.id)))
    ledger = list(db.scalars(select(LedgerEntry).where(LedgerEntry.invoice_id == invoice.id)))
    audit_events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.subject_type == "invoice", AuditEvent.subject_id == invoice.id)
            .order_by(AuditEvent.sequence)
        )
    )
    return {
        "id": invoice.id,
        "resident_id": invoice.resident_id,
        "period_start": str(invoice.period_start),
        "period_end": str(invoice.period_end),
        "status": invoice.status,
        "total_cents": invoice.total_cents,
        "paid_cents": invoice_paid_cents(db, invoice.id),
        "due_at": invoice.due_at.isoformat(),
        "is_adjustment": invoice.is_adjustment,
        "lines": [
            {
                "id": line.id,
                "car_id": line.car_id,
                "description": line.description,
                "amount_cents": line.amount_cents,
                "days_active": line.days_active,
                "days_in_month": line.days_in_month,
            }
            for line in invoice.lines
        ],
        "payments": [
            {
                "id": p.id,
                "method": p.method,
                "provider": p.provider,
                "amount_cents": p.amount_cents,
                "status": p.status,
                "is_refund": p.is_refund,
                "created_at": p.created_at.isoformat(),
            }
            for p in payments
        ],
        "ledger_entries": [
            {
                "id": e.id,
                "account": e.account,
                "debit_cents": e.debit_cents,
                "credit_cents": e.credit_cents,
                "memo": e.memo,
                "created_at": e.created_at.isoformat(),
            }
            for e in ledger
        ],
        "audit_events": [
            {
                "type": e.type,
                "payload": json.loads(e.payload),
                "created_at": e.created_at.isoformat(),
            }
            for e in audit_events
        ],
    }


@router.post("/invoices/{invoice_id}/record-payment", response_model=PaymentResponse)
def manager_record_payment(
    invoice_id: str,
    payload: RecordPaymentRequest,
    user: User = Depends(require_money_stepup),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
) -> PaymentResponse:
    path = f"/manager/invoices/{invoice_id}/record-payment"
    cached = find_cached_response(db, user, idempotency_key, "POST", path)
    if cached is not None:
        return PaymentResponse(**json.loads(cached.response_body))

    invoice = _invoice_or_404(db, user.building_id, invoice_id)
    payment = record_manual_payment(
        db, invoice, payload.amount_cents, payload.method, payload.reference, user.id
    )
    db.commit()
    db.refresh(payment)
    response = PaymentResponse.model_validate(payment)
    store_response(
        db,
        user.building_id,
        user,
        idempotency_key,
        "POST",
        path,
        200,
        response.model_dump(mode="json"),
    )
    db.commit()
    return response


@router.post("/invoices/{invoice_id}/credit")
def manager_issue_credit(
    invoice_id: str,
    payload: IssueCreditRequest,
    user: User = Depends(require_money_stepup),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    from app.settings import settings

    path = f"/manager/invoices/{invoice_id}/credit"
    cached = find_cached_response(db, user, idempotency_key, "POST", path)
    if cached is not None:
        return json.loads(cached.response_body)

    invoice = _invoice_or_404(db, user.building_id, invoice_id)

    if payload.amount_cents >= settings.refund_approval_threshold_cents:
        approval = ApprovalRequest(
            building_id=user.building_id,
            kind=ApprovalKind.credit,
            invoice_id=invoice.id,
            billing_account_id=invoice.billing_account_id,
            amount_cents=payload.amount_cents,
            reason=payload.reason,
            requested_by=user.id,
        )
        db.add(approval)
        db.flush()
        append_audit_event(
            db,
            user.building_id,
            "approval_request",
            approval.id,
            "proposed",
            {"kind": "credit", "amount_cents": payload.amount_cents, "invoice_id": invoice.id},
            user.id,
        )
        db.commit()
        db.refresh(approval)
        response = {
            "status": "pending_approval",
            "approval": ApprovalResponse.model_validate(approval).model_dump(mode="json"),
        }
    else:
        issue_credit(
            db,
            user.building_id,
            invoice.billing_account_id,
            payload.amount_cents,
            payload.reason,
            user.id,
            invoice.id,
        )
        apply_credit_to_invoice(db, invoice, user.id)
        db.commit()
        response = {
            "status": "applied",
            "invoice_id": invoice.id,
            "amount_cents": payload.amount_cents,
        }

    store_response(db, user.building_id, user, idempotency_key, "POST", path, 200, response)
    db.commit()
    return response


@router.post("/invoices/{invoice_id}/refund")
def manager_refund(
    invoice_id: str,
    payload: RefundRequest,
    user: User = Depends(require_money_stepup),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
) -> dict:
    from app.settings import settings

    path = f"/manager/invoices/{invoice_id}/refund"
    cached = find_cached_response(db, user, idempotency_key, "POST", path)
    if cached is not None:
        return json.loads(cached.response_body)

    invoice = _invoice_or_404(db, user.building_id, invoice_id)
    original_payment = db.scalar(
        select(Payment).where(Payment.id == payload.payment_id, Payment.invoice_id == invoice.id)
    )
    if original_payment is None or original_payment.status != PaymentStatus.succeeded:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Original payment not found")

    already_refunded = sum(
        p.amount_cents
        for p in db.scalars(
            select(Payment).where(Payment.refunded_payment_id == original_payment.id)
        )
    )
    if payload.amount_cents > original_payment.amount_cents - already_refunded:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Refund amount exceeds what was paid")

    if payload.amount_cents >= settings.refund_approval_threshold_cents:
        approval = ApprovalRequest(
            building_id=user.building_id,
            kind=ApprovalKind.refund,
            invoice_id=invoice.id,
            billing_account_id=invoice.billing_account_id,
            amount_cents=payload.amount_cents,
            reason=payload.reason,
            original_payment_id=original_payment.id,
            requested_by=user.id,
        )
        db.add(approval)
        db.flush()
        append_audit_event(
            db,
            user.building_id,
            "approval_request",
            approval.id,
            "proposed",
            {"kind": "refund", "amount_cents": payload.amount_cents, "invoice_id": invoice.id},
            user.id,
        )
        db.commit()
        db.refresh(approval)
        response = {
            "status": "pending_approval",
            "approval": ApprovalResponse.model_validate(approval).model_dump(mode="json"),
        }
    else:
        if original_payment.provider != "manual":
            provider = get_payment_provider()
            if original_payment.provider_payment_id:
                provider.refund(original_payment.provider_payment_id, payload.amount_cents)
        record_refund(db, original_payment, payload.amount_cents, payload.reason, user.id)
        db.commit()
        response = {
            "status": "refunded",
            "invoice_id": invoice.id,
            "amount_cents": payload.amount_cents,
        }

    store_response(db, user.building_id, user, idempotency_key, "POST", path, 200, response)
    db.commit()
    return response


@router.post("/invoices/{invoice_id}/void")
def manager_void_invoice(
    invoice_id: str,
    payload: VoidRequest,
    user: User = Depends(require_money_stepup),
    db: Session = Depends(get_db),
) -> dict:
    invoice = _invoice_or_404(db, user.building_id, invoice_id)
    try:
        void_invoice(db, invoice, user.id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return {"status": "voided", "invoice_id": invoice.id}


@router.post("/invoices/{invoice_id}/resend-receipt")
def manager_resend_receipt(
    invoice_id: str,
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    invoice = _invoice_or_404(db, user.building_id, invoice_id)
    from app.notifications import get_notification_adapter

    resident = db.get(User, invoice.resident_id)
    get_notification_adapter().send(
        resident, f"Your receipt for invoice {invoice.id} has been resent."
    )
    append_audit_event(db, user.building_id, "invoice", invoice.id, "receipt_resent", {}, user.id)
    db.commit()
    return {"status": "sent"}


@router.get("/approvals", response_model=list[ApprovalResponse])
def manager_list_approvals(
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> list[ApprovalResponse]:
    approvals = list(
        db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.building_id == user.building_id)
            .order_by(ApprovalRequest.created_at.desc())
        )
    )
    return [ApprovalResponse.model_validate(a) for a in approvals]


@router.post("/approvals/{approval_id}/decide")
def manager_decide_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    user: User = Depends(require_money_stepup),
    db: Session = Depends(get_db),
) -> dict:
    approval = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id, ApprovalRequest.building_id == user.building_id
        )
    )
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval request not found")
    if approval.status != ApprovalStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Approval request already decided")
    if approval.requested_by == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The requester cannot approve their own request"
        )

    approval.approved_by = user.id
    approval.decided_at = datetime.now(UTC)

    if payload.approve:
        approval.status = ApprovalStatus.approved
        invoice = db.get(Invoice, approval.invoice_id) if approval.invoice_id else None
        if approval.kind == ApprovalKind.credit and invoice is not None:
            issue_credit(
                db,
                user.building_id,
                approval.billing_account_id,
                approval.amount_cents,
                approval.reason,
                user.id,
                invoice.id,
            )
            apply_credit_to_invoice(db, invoice, user.id)
        elif approval.kind == ApprovalKind.refund:
            if approval.original_payment_id is not None:
                original_payment = db.get(Payment, approval.original_payment_id)
                if original_payment.provider != "manual":
                    provider = get_payment_provider()
                    if original_payment.provider_payment_id:
                        provider.refund(original_payment.provider_payment_id, approval.amount_cents)
                record_refund(db, original_payment, approval.amount_cents, approval.reason, user.id)
            else:
                # A stranded-credit refund proposal with no original payment to reverse:
                # recorded as a cash refund straight out of the credits account
                from app.billing.ledger import post_refund

                post_refund(
                    db,
                    user.building_id,
                    approval.billing_account_id,
                    approval.amount_cents,
                    f"Approved refund for approval {approval.id}",
                    user.id,
                )
    else:
        approval.status = ApprovalStatus.rejected

    db.add(approval)
    append_audit_event(
        db,
        user.building_id,
        "approval_request",
        approval.id,
        "approved" if payload.approve else "rejected",
        {"decided_by": user.id},
        user.id,
    )
    db.commit()
    db.refresh(approval)
    return {
        "status": approval.status,
        "approval": ApprovalResponse.model_validate(approval).model_dump(mode="json"),
    }


@router.get("/billing/month-close.csv")
def month_close_csv(
    month: str = Query(..., description="YYYY-MM"),
    user: User = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> Response:
    year, month_num = (int(part) for part in month.split("-"))
    period_start, _ = month_bounds(year, month_num)
    invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.building_id == user.building_id, Invoice.period_start == period_start
            )
        )
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["invoice_id", "resident_id", "status", "total_cents", "paid_cents", "due_at"])
    for invoice in invoices:
        writer.writerow(
            [
                invoice.id,
                invoice.resident_id,
                invoice.status,
                invoice.total_cents,
                invoice_paid_cents(db, invoice.id),
                invoice.due_at.isoformat(),
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=month-close-{month}.csv"},
    )
