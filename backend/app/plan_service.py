"""Plan catalog: creation, scheduled price changes, and an impact preview."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.invoices import plan_price_cents
from app.billing.proration import month_bounds, next_month
from app.models import Building, Car, CarStatus, Plan, PlanPrice, User


def _today_in_building(building: Building) -> date:
    return datetime.now(UTC).astimezone(ZoneInfo(building.timezone)).date()


def _first_of_next_month(building: Building) -> date:
    today = _today_in_building(building)
    year, month = next_month(today.year, today.month)
    start, _ = month_bounds(year, month)
    return start


def create_plan(
    db: Session,
    building: Building,
    manager: User,
    name: str,
    size_class: str,
    monthly_cents: int,
) -> Plan:
    if monthly_cents < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "monthly_cents cannot be negative")
    today = _today_in_building(building)
    plan = Plan(building_id=building.id, name=name, size_class=size_class)
    db.add(plan)
    db.flush()
    db.add(
        PlanPrice(
            plan_id=plan.id,
            effective_month=date(today.year, today.month, 1),
            monthly_cents=monthly_cents,
        )
    )
    db.flush()
    append_audit_event(
        db,
        building.id,
        "plan",
        plan.id,
        "created",
        {"name": name, "size_class": size_class, "monthly_cents": monthly_cents},
        manager.id,
    )
    db.commit()
    db.refresh(plan)
    return plan


def schedule_price_change(
    db: Session,
    building: Building,
    manager: User,
    plan: Plan,
    monthly_cents: int,
    effective_month: date,
) -> PlanPrice:
    if monthly_cents < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "monthly_cents cannot be negative")
    if effective_month.day != 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "effective_month must be the first of a month"
        )
    earliest_allowed = _first_of_next_month(building)
    if effective_month < earliest_allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"effective_month must be on or after {earliest_allowed} (a future billing month)",
        )
    existing = db.scalar(
        select(PlanPrice).where(
            PlanPrice.plan_id == plan.id, PlanPrice.effective_month == effective_month
        )
    )
    if existing is not None:
        existing.monthly_cents = monthly_cents
        db.add(existing)
        db.flush()
        price = existing
    else:
        price = PlanPrice(
            plan_id=plan.id, effective_month=effective_month, monthly_cents=monthly_cents
        )
        db.add(price)
        db.flush()
    append_audit_event(
        db,
        building.id,
        "plan",
        plan.id,
        "price_scheduled",
        {"effective_month": str(effective_month), "monthly_cents": monthly_cents},
        manager.id,
    )
    db.commit()
    db.refresh(price)
    return price


def archive_plan(db: Session, building: Building, manager: User, plan: Plan) -> Plan:
    plan.archived = True
    db.add(plan)
    db.flush()
    append_audit_event(db, building.id, "plan", plan.id, "archived", {}, manager.id)
    db.commit()
    db.refresh(plan)
    return plan


def impact_preview(
    db: Session, building: Building, plan: Plan, monthly_cents: int, effective_month: date
) -> dict:
    """Affected cars and the monthly revenue change a price change would cause."""
    active_cars = list(
        db.scalars(
            select(Car).where(
                Car.building_id == building.id,
                Car.plan_id == plan.id,
                Car.status != CarStatus.ended,
            )
        )
    )
    try:
        current_cents = plan_price_cents(db, plan.id, effective_month)
    except ValueError:
        current_cents = 0
    delta_per_car = monthly_cents - current_cents
    return {
        "plan_id": plan.id,
        "effective_month": str(effective_month),
        "current_monthly_cents": current_cents,
        "new_monthly_cents": monthly_cents,
        "affected_car_count": len(active_cars),
        "affected_cars": [
            {"car_id": c.id, "owner_id": c.owner_id, "license_plate": c.license_plate}
            for c in active_cars
        ],
        "monthly_revenue_change_cents": delta_per_car * len(active_cars),
    }
