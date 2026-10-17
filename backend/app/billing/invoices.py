"""Invoice generation: idempotent per resident and period, safe to run twice."""

from collections import defaultdict
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.credits import apply_credit_to_invoice, get_or_create_billing_account
from app.billing.ledger import post_invoice_issued, post_invoice_voided, post_transaction
from app.billing.proration import month_bounds, next_month, prorate_car_charge
from app.models import (
    Building,
    Car,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    LedgerAccount,
    PlanPrice,
)
from app.schedule_engine import local_to_utc


def plan_price_cents(db: Session, plan_id: str, on_date: date) -> int:
    month_start = date(on_date.year, on_date.month, 1)
    price = db.scalar(
        select(PlanPrice)
        .where(PlanPrice.plan_id == plan_id, PlanPrice.effective_month <= month_start)
        .order_by(PlanPrice.effective_month.desc())
        .limit(1)
    )
    if price is None:
        raise ValueError(f"No price found for plan {plan_id} effective on or before {month_start}")
    return price.monthly_cents


def _line_description(car: Car) -> str:
    plate = car.nickname or car.license_plate
    return f"{car.make} {car.model} ({plate})"


def generate_invoices_for_period(
    db: Session,
    building: Building,
    year: int,
    month: int,
    now: datetime,
    actor_id: str | None = None,
) -> list[Invoice]:
    """Creates one invoice per resident with a billable car for this period.

    Safe to call twice: a resident who already has a non-adjustment invoice
    for this period is skipped entirely, so no duplicate lines or invoices
    are ever created.
    """
    period_start, period_end = month_bounds(year, month)
    due_at = local_to_utc(period_start, time(0, 0), building.timezone)

    cars = list(
        db.scalars(select(Car).where(Car.building_id == building.id, Car.plan_id.is_not(None)))
    )
    cars_by_resident: dict[str, list[Car]] = defaultdict(list)
    for car in cars:
        if car.started_on > period_end:
            continue
        if car.ended_on is not None and car.ended_on < period_start:
            continue
        cars_by_resident[car.owner_id].append(car)

    created: list[Invoice] = []
    total_residents = len(cars_by_resident)
    for index, (resident_id, resident_cars) in enumerate(cars_by_resident.items(), start=1):
        billing_account = get_or_create_billing_account(db, resident_id, building.id)
        existing = db.scalar(
            select(Invoice).where(
                Invoice.billing_account_id == billing_account.id,
                Invoice.period_start == period_start,
                Invoice.is_adjustment.is_(False),
            )
        )
        if existing is not None:
            continue

        lines_data = []
        total_cents = 0
        for car in resident_cars:
            monthly_cents = plan_price_cents(db, car.plan_id, period_start)
            amount, days_active, days_in_period = prorate_car_charge(
                monthly_cents, car.started_on, car.ended_on, period_start, period_end
            )
            if amount <= 0:
                continue
            lines_data.append((car, amount, days_active, days_in_period))
            total_cents += amount
        if not lines_data:
            continue

        invoice = Invoice(
            building_id=building.id,
            resident_id=resident_id,
            billing_account_id=billing_account.id,
            period_start=period_start,
            period_end=period_end,
            status=InvoiceStatus.open,
            total_cents=0,
            due_at=due_at,
            issued_at=now,
            is_adjustment=False,
        )
        db.add(invoice)
        db.flush()
        for car, amount, days_active, days_in_period in lines_data:
            db.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    car_id=car.id,
                    plan_id=car.plan_id,
                    description=_line_description(car),
                    amount_cents=amount,
                    days_active=days_active,
                    days_in_month=days_in_period,
                )
            )
        invoice.total_cents = total_cents
        db.add(invoice)
        db.flush()

        post_invoice_issued(db, invoice, actor_id=actor_id)
        apply_credit_to_invoice(db, invoice, actor_id=actor_id)
        append_audit_event(
            db,
            building.id,
            "invoice",
            invoice.id,
            "issued",
            {
                "total_cents": total_cents,
                "period_start": str(period_start),
                "car_count": len(lines_data),
            },
            actor_id=actor_id,
        )
        created.append(invoice)
        if index % 20 == 0 or index == total_residents:
            print(f"  generated {index}/{total_residents} invoices for {period_start}")

    db.commit()
    return created


def apply_new_car_billing(
    db: Session, car: Car, building: Building, now: datetime, actor_id: str | None = None
) -> Invoice | None:
    """Bills a newly added car into the next period's invoice, per decision 5.

    If next month's invoice was already issued and is still open or past
    due, a line is added to it. If next month has no invoice yet, the
    regular monthly run will bill this car naturally (its started_on is
    already in the database), so nothing happens here. If next month's
    invoice exists but is no longer open (paid, processing or void), a new
    adjustment invoice due immediately is created instead.
    """
    if car.plan_id is None:
        return None
    local_today = now.astimezone(ZoneInfo(building.timezone)).date()
    next_year, next_m = next_month(local_today.year, local_today.month)
    next_start, next_end = month_bounds(next_year, next_m)
    if car.started_on > next_end:
        return None

    billing_account = get_or_create_billing_account(db, car.owner_id, building.id)
    monthly_cents = plan_price_cents(db, car.plan_id, next_start)
    amount, days_active, days_in_period = prorate_car_charge(
        monthly_cents, car.started_on, car.ended_on, next_start, next_end
    )
    if amount <= 0:
        return None

    existing_invoice = db.scalar(
        select(Invoice).where(
            Invoice.billing_account_id == billing_account.id,
            Invoice.period_start == next_start,
            Invoice.is_adjustment.is_(False),
        )
    )

    if existing_invoice is None:
        # The regular monthly run has not billed this period yet; it will
        # pick up this car naturally when it does
        return None

    if existing_invoice.status in (InvoiceStatus.open, InvoiceStatus.past_due):
        db.add(
            InvoiceLine(
                invoice_id=existing_invoice.id,
                car_id=car.id,
                plan_id=car.plan_id,
                description=_line_description(car),
                amount_cents=amount,
                days_active=days_active,
                days_in_month=days_in_period,
            )
        )
        existing_invoice.total_cents += amount
        db.add(existing_invoice)
        db.flush()
        post_transaction(
            db,
            building.id,
            [(LedgerAccount.receivable, amount, 0), (LedgerAccount.revenue, 0, amount)],
            memo=f"Added car {car.id} to invoice {existing_invoice.id}",
            actor_id=actor_id,
            invoice_id=existing_invoice.id,
            billing_account_id=billing_account.id,
        )
        append_audit_event(
            db,
            building.id,
            "invoice",
            existing_invoice.id,
            "line_added",
            {"car_id": car.id, "amount_cents": amount},
            actor_id=actor_id,
        )
        return existing_invoice

    # Already paid, processing or void: a new adjustment invoice due now
    invoice = Invoice(
        building_id=building.id,
        resident_id=car.owner_id,
        billing_account_id=billing_account.id,
        period_start=next_start,
        period_end=next_end,
        status=InvoiceStatus.open,
        total_cents=amount,
        due_at=now,
        issued_at=now,
        is_adjustment=True,
    )
    db.add(invoice)
    db.flush()
    db.add(
        InvoiceLine(
            invoice_id=invoice.id,
            car_id=car.id,
            plan_id=car.plan_id,
            description=_line_description(car),
            amount_cents=amount,
            days_active=days_active,
            days_in_month=days_in_period,
        )
    )
    db.flush()
    post_invoice_issued(db, invoice, actor_id=actor_id)
    append_audit_event(
        db,
        building.id,
        "invoice",
        invoice.id,
        "issued_adjustment",
        {"car_id": car.id, "amount_cents": amount},
        actor_id=actor_id,
    )
    return invoice


def void_invoice(db: Session, invoice: Invoice, actor_id: str | None, reason: str) -> Invoice:
    if invoice.status not in (InvoiceStatus.draft, InvoiceStatus.open):
        raise ValueError("Only a draft or open invoice can be voided")
    post_invoice_voided(db, invoice, actor_id=actor_id)
    invoice.status = InvoiceStatus.void
    invoice.voided_at = datetime.now(UTC)
    db.add(invoice)
    db.flush()
    append_audit_event(
        db, invoice.building_id, "invoice", invoice.id, "voided", {"reason": reason}, actor_id
    )
    return invoice
