from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.charge import charge_invoice
from app.billing.credits import get_or_create_billing_account
from app.billing.ledger import invoice_paid_cents
from app.billing.receipt import build_receipt_pdf, invoice_receipt_lines
from app.billing.summary import resident_billing_summary
from app.db import get_db
from app.deps import require_csrf, require_role
from app.idempotency import find_cached_response, require_idempotency_key, store_response
from app.models import (
    Building,
    Invoice,
    InvoiceStatus,
    PaymentMethod,
    Role,
    User,
)
from app.payments.registry import get_payment_provider
from app.schemas import (
    AutopayUpdateRequest,
    BillingSummaryResponse,
    InvoiceLineResponse,
    InvoiceResponse,
    PayInvoiceRequest,
    PaymentMethodResponse,
    PaymentMethodSetupRequest,
    PaymentResponse,
)

router = APIRouter(prefix="/billing", tags=["billing"], dependencies=[Depends(require_csrf)])


def _invoice_or_404(db: Session, user: User, invoice_id: str) -> Invoice:
    billing_account = get_or_create_billing_account(db, user.id, user.building_id)
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.billing_account_id == billing_account.id
        )
    )
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


def _invoice_to_response(db: Session, invoice: Invoice) -> InvoiceResponse:
    return InvoiceResponse(
        id=invoice.id,
        resident_id=invoice.resident_id,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        status=invoice.status,
        total_cents=invoice.total_cents,
        paid_cents=invoice_paid_cents(db, invoice.id),
        due_at=invoice.due_at,
        issued_at=invoice.issued_at,
        paid_at=invoice.paid_at,
        is_adjustment=invoice.is_adjustment,
        lines=[InvoiceLineResponse.model_validate(line) for line in invoice.lines],
    )


@router.get("/summary", response_model=BillingSummaryResponse)
def summary(
    user: User = Depends(require_role(Role.resident)), db: Session = Depends(get_db)
) -> BillingSummaryResponse:
    building = db.get(Building, user.building_id)
    return BillingSummaryResponse(**resident_billing_summary(db, user, building))


@router.get("/invoices", response_model=list[InvoiceResponse])
def list_invoices(
    user: User = Depends(require_role(Role.resident)), db: Session = Depends(get_db)
) -> list[InvoiceResponse]:
    billing_account = get_or_create_billing_account(db, user.id, user.building_id)
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(Invoice.billing_account_id == billing_account.id)
            .order_by(Invoice.period_start.desc())
        )
    )
    return [_invoice_to_response(db, invoice) for invoice in invoices]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: str,
    user: User = Depends(require_role(Role.resident)),
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    invoice = _invoice_or_404(db, user, invoice_id)
    return _invoice_to_response(db, invoice)


@router.get("/invoices/{invoice_id}/receipt")
def get_receipt(
    invoice_id: str,
    user: User = Depends(require_role(Role.resident)),
    db: Session = Depends(get_db),
) -> Response:
    invoice = _invoice_or_404(db, user, invoice_id)
    building = db.get(Building, user.building_id)
    paid_cents = invoice_paid_cents(db, invoice.id)
    lines = invoice_receipt_lines(
        building.name,
        user.full_name,
        invoice.id,
        str(invoice.period_start),
        str(invoice.period_end),
        invoice.status,
        invoice.total_cents,
        paid_cents,
        [(line.description, line.amount_cents) for line in invoice.lines],
    )
    pdf_bytes = build_receipt_pdf(lines)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=invoice-{invoice.id}.pdf"},
    )


@router.get("/payment-methods", response_model=list[PaymentMethodResponse])
def list_payment_methods(
    user: User = Depends(require_role(Role.resident)), db: Session = Depends(get_db)
) -> list[PaymentMethodResponse]:
    billing_account = get_or_create_billing_account(db, user.id, user.building_id)
    methods = list(
        db.scalars(
            select(PaymentMethod).where(
                PaymentMethod.billing_account_id == billing_account.id,
                PaymentMethod.is_active.is_(True),
            )
        )
    )
    return [PaymentMethodResponse.model_validate(m) for m in methods]


@router.post(
    "/payment-methods/setup",
    status_code=status.HTTP_201_CREATED,
    response_model=PaymentMethodResponse,
)
def setup_payment_method(
    payload: PaymentMethodSetupRequest,
    user: User = Depends(require_role(Role.resident)),
    db: Session = Depends(get_db),
) -> PaymentMethodResponse:
    billing_account = get_or_create_billing_account(db, user.id, user.building_id)
    provider = get_payment_provider()
    details = provider.setup_payment_method(
        billing_account.id, user.email, payload.kind.value, payload.fake_token
    )
    method = PaymentMethod(
        billing_account_id=billing_account.id,
        provider=provider.name,
        provider_customer_id=details.provider_customer_id,
        provider_method_id=details.provider_method_id,
        kind=details.kind,
        brand=details.brand,
        last4=details.last4,
        exp_month=details.exp_month,
        exp_year=details.exp_year,
        fake_behavior=details.fake_behavior,
        is_active=not details.pending,
    )
    db.add(method)
    db.flush()
    if billing_account.default_payment_method_id is None:
        billing_account.default_payment_method_id = method.id
        db.add(billing_account)
    append_audit_event(
        db,
        user.building_id,
        "payment_method",
        method.id,
        "created",
        {"kind": details.kind, "last4": details.last4},
        user.id,
    )
    db.commit()
    db.refresh(method)
    response = PaymentMethodResponse.model_validate(method)
    response.pending = details.pending
    response.client_secret = details.client_secret
    return response


@router.delete("/payment-methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment_method(
    method_id: str, user: User = Depends(require_role(Role.resident)), db: Session = Depends(get_db)
) -> None:
    billing_account = get_or_create_billing_account(db, user.id, user.building_id)
    method = db.scalar(
        select(PaymentMethod).where(
            PaymentMethod.id == method_id, PaymentMethod.billing_account_id == billing_account.id
        )
    )
    if method is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment method not found")

    active_count = len(
        list(
            db.scalars(
                select(PaymentMethod).where(
                    PaymentMethod.billing_account_id == billing_account.id,
                    PaymentMethod.is_active.is_(True),
                )
            )
        )
    )
    if billing_account.autopay_enabled and active_count <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot remove the only payment method while autopay is on",
        )

    method.is_active = False
    db.add(method)
    if billing_account.default_payment_method_id == method.id:
        billing_account.default_payment_method_id = None
        db.add(billing_account)
    append_audit_event(db, user.building_id, "payment_method", method.id, "removed", {}, user.id)
    db.commit()


@router.patch("/autopay", response_model=BillingSummaryResponse)
def update_autopay(
    payload: AutopayUpdateRequest,
    user: User = Depends(require_role(Role.resident)),
    db: Session = Depends(get_db),
) -> BillingSummaryResponse:
    billing_account = get_or_create_billing_account(db, user.id, user.building_id)
    if payload.enabled and billing_account.default_payment_method_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Add a payment method before turning on autopay"
        )
    billing_account.autopay_enabled = payload.enabled
    db.add(billing_account)
    append_audit_event(
        db,
        user.building_id,
        "billing_account",
        billing_account.id,
        "autopay_updated",
        {"enabled": payload.enabled},
        user.id,
    )
    db.commit()
    building = db.get(Building, user.building_id)
    return BillingSummaryResponse(**resident_billing_summary(db, user, building))


@router.post("/invoices/{invoice_id}/pay", response_model=PaymentResponse)
def pay_invoice(
    invoice_id: str,
    payload: PayInvoiceRequest,
    user: User = Depends(require_role(Role.resident)),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
) -> PaymentResponse:
    cached = find_cached_response(
        db, user, idempotency_key, "POST", f"/billing/invoices/{invoice_id}/pay"
    )
    if cached is not None:
        import json

        return PaymentResponse(**json.loads(cached.response_body))

    invoice = _invoice_or_404(db, user, invoice_id)
    if invoice.status not in (InvoiceStatus.open, InvoiceStatus.past_due):
        raise HTTPException(status.HTTP_409_CONFLICT, "Invoice is not payable in its current state")

    billing_account = get_or_create_billing_account(db, user.id, user.building_id)
    method_id = payload.payment_method_id or billing_account.default_payment_method_id
    if method_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No payment method on file")
    method = db.scalar(
        select(PaymentMethod).where(
            PaymentMethod.id == method_id,
            PaymentMethod.billing_account_id == billing_account.id,
            PaymentMethod.is_active.is_(True),
        )
    )
    if method is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment method not found")

    provider = get_payment_provider()
    attempt_no = 1
    payment = charge_invoice(
        db, provider, invoice, method, f"{invoice.id}:{attempt_no}", attempt_no, actor_id=user.id
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
        f"/billing/invoices/{invoice_id}/pay",
        status.HTTP_200_OK,
        response.model_dump(mode="json"),
    )
    db.commit()
    return response
