"""Resident billing summary: what's owed, autopay state, and current cars."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.credits import get_or_create_billing_account
from app.billing.invoices import plan_price_cents
from app.billing.ledger import invoice_paid_cents
from app.models import (
    Building,
    Car,
    CarStatus,
    Invoice,
    InvoiceStatus,
    Plan,
    User,
)


def resident_billing_summary(db: Session, resident: User, building: Building) -> dict:
    billing_account = get_or_create_billing_account(db, resident.id, building.id)

    unpaid = list(
        db.scalars(
            select(Invoice).where(
                Invoice.billing_account_id == billing_account.id,
                Invoice.status.in_(
                    [InvoiceStatus.open, InvoiceStatus.past_due, InvoiceStatus.processing]
                ),
            )
        )
    )
    amount_due_cents = 0
    due_dates = []
    for invoice in unpaid:
        remaining = invoice.total_cents - invoice_paid_cents(db, invoice.id)
        if remaining > 0:
            amount_due_cents += remaining
            due_dates.append(invoice.due_at)

    paid_invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.billing_account_id == billing_account.id,
                Invoice.status == InvoiceStatus.paid,
            )
        )
    )
    paid_through: date | None = max((i.period_end for i in paid_invoices), default=None)

    cars = list(
        db.scalars(select(Car).where(Car.owner_id == resident.id, Car.status != CarStatus.ended))
    )
    today = date.today()
    car_summaries = []
    for car in cars:
        plan_name = None
        monthly_cents = None
        if car.plan_id is not None:
            plan = db.get(Plan, car.plan_id)
            plan_name = plan.name if plan else None
            try:
                monthly_cents = plan_price_cents(db, car.plan_id, today)
            except ValueError:
                monthly_cents = None
        car_summaries.append(
            {
                "car_id": car.id,
                "license_plate": car.license_plate,
                "plan_name": plan_name,
                "monthly_cents": monthly_cents,
            }
        )

    return {
        "amount_due_cents": amount_due_cents,
        "due_date": min(due_dates).date() if due_dates else None,
        "autopay_enabled": billing_account.autopay_enabled,
        "paid_through": paid_through,
        "cars": car_summaries,
    }
