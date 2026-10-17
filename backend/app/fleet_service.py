"""Manager-only fleet operations: car CRUD, resident directory, CSV import, invites.

Residents never reach any of this directly (see app/routers/cars.py, which
returns 403 on POST and DELETE); only the /manager/* routes call in here.
"""

import csv
import io
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.billing.credits import end_car_credit
from app.billing.invoices import apply_new_car_billing
from app.models import (
    Building,
    Car,
    CarRequest,
    CarRequestAction,
    CarStatus,
    InviteCode,
    Plan,
    Role,
    Schedule,
    Ticket,
    TicketMessage,
    User,
)
from app.spot_assignment import assign_spot_for_car

CSV_FIELDS = [
    "email",
    "full_name",
    "unit",
    "plate",
    "make",
    "model",
    "color",
    "plan_name",
    "started_on",
]


def _status_for_start_date(started_on: date, today: date) -> CarStatus:
    return CarStatus.pending if started_on > today else CarStatus.active


def _today_in_building(building: Building) -> date:
    from zoneinfo import ZoneInfo

    return datetime.now(UTC).astimezone(ZoneInfo(building.timezone)).date()


def create_car(
    db: Session,
    building: Building,
    manager: User,
    resident_id: str,
    make: str,
    model: str,
    color: str,
    license_plate: str,
    plan_id: str | None,
    started_on: date | None,
    size_class: str | None = None,
    nickname: str | None = None,
) -> Car:
    resident = db.get(User, resident_id)
    if resident is None or resident.building_id != building.id or resident.role != Role.resident:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resident not found")

    if plan_id is not None:
        plan = db.get(Plan, plan_id)
        if plan is None or plan.building_id != building.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")

    today = _today_in_building(building)
    effective_start = started_on or today
    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        plan_id=plan_id,
        make=make,
        model=model,
        color=color,
        license_plate=license_plate.upper().strip(),
        status=_status_for_start_date(effective_start, today),
        started_on=effective_start,
        size_class=size_class,
        nickname=nickname,
        created_by=manager.id,
    )
    db.add(car)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That plate is already active in this building"
        ) from exc

    assign_spot_for_car(db, car)
    append_audit_event(
        db,
        building.id,
        "car",
        car.id,
        "created",
        {
            "resident_id": resident.id,
            "license_plate": car.license_plate,
            "plan_id": plan_id,
            "started_on": str(effective_start),
        },
        actor_id=manager.id,
    )
    if plan_id is not None:
        apply_new_car_billing(db, car, building, datetime.now(UTC), actor_id=manager.id)
    db.commit()
    db.refresh(car)
    return car


def update_car(
    db: Session,
    building: Building,
    manager: User,
    car: Car,
    updates: dict,
) -> Car:
    before = {
        "make": car.make,
        "model": car.model,
        "color": car.color,
        "license_plate": car.license_plate,
        "plan_id": car.plan_id,
        "size_class": car.size_class,
        "nickname": car.nickname,
    }
    if "license_plate" in updates and updates["license_plate"] is not None:
        updates["license_plate"] = updates["license_plate"].upper().strip()
    for field_name, value in updates.items():
        if value is not None:
            setattr(car, field_name, value)
    db.add(car)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That plate is already active in this building"
        ) from exc

    append_audit_event(
        db,
        building.id,
        "car",
        car.id,
        "updated",
        {"before": before, "updates": updates},
        manager.id,
    )
    db.commit()
    db.refresh(car)
    return car


def end_car(db: Session, building: Building, manager: User, car: Car, ended_on: date) -> Car:
    if car.status == CarStatus.ended:
        raise HTTPException(status.HTTP_409_CONFLICT, "Car is already ended")

    car.status = CarStatus.ended
    car.ended_on = ended_on
    db.add(car)

    schedules = list(db.scalars(select(Schedule).where(Schedule.car_id == car.id)))
    for schedule in schedules:
        if schedule.active_until is None or schedule.active_until > ended_on:
            schedule.active_until = ended_on
            db.add(schedule)
    db.flush()

    credit_cents = end_car_credit(db, car, building, datetime.now(UTC), actor_id=manager.id)

    append_audit_event(
        db,
        building.id,
        "car",
        car.id,
        "ended",
        {"ended_on": str(ended_on), "credit_cents": credit_cents},
        manager.id,
    )
    db.commit()
    db.refresh(car)
    return car


def list_residents(
    db: Session, building: Building, search: str | None = None, unit: str | None = None
) -> list[User]:
    query = select(User).where(User.building_id == building.id, User.role == Role.resident)
    if unit:
        query = query.where(User.unit == unit)
    residents = list(db.scalars(query))
    if search:
        needle = search.lower()
        residents = [
            r for r in residents if needle in r.full_name.lower() or needle in r.email.lower()
        ]
    return residents


@dataclass
class ImportRowResult:
    row_number: int
    status: str  # ok or error
    detail: str
    email: str | None = None
    license_plate: str | None = None


@dataclass
class ImportResult:
    dry_run: bool
    rows: list[ImportRowResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "ok")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "error")


def import_cars_csv(
    db: Session, building: Building, manager: User, csv_text: str, dry_run: bool
) -> ImportResult:
    """Each row is validated and applied independently inside its own savepoint,
    so one bad row never blocks the rest. When dry_run is true, every savepoint
    is rolled back at the end so nothing is persisted."""
    reader = csv.DictReader(io.StringIO(csv_text))
    result = ImportResult(dry_run=dry_run)
    today = _today_in_building(building)

    for row_number, row in enumerate(reader, start=2):
        savepoint = db.begin_nested()
        try:
            email = (row.get("email") or "").strip().lower()
            resident = db.scalar(
                select(User).where(User.building_id == building.id, User.email == email)
            )
            if resident is None or resident.role != Role.resident:
                raise ValueError(f"No resident found with email {email!r}")

            plan_name = (row.get("plan_name") or "").strip()
            plan = db.scalar(
                select(Plan).where(Plan.building_id == building.id, Plan.name == plan_name)
            )
            if plan is None:
                raise ValueError(f"No plan found named {plan_name!r}")

            started_on_raw = (row.get("started_on") or "").strip()
            started_on = date.fromisoformat(started_on_raw) if started_on_raw else today

            plate = (row.get("plate") or "").strip().upper()
            if not plate:
                raise ValueError("Missing plate")

            car = Car(
                building_id=building.id,
                owner_id=resident.id,
                plan_id=plan.id,
                make=(row.get("make") or "").strip() or "Unknown",
                model=(row.get("model") or "").strip() or "Unknown",
                color=(row.get("color") or "").strip() or "unknown",
                license_plate=plate,
                status=_status_for_start_date(started_on, today),
                started_on=started_on,
                created_by=manager.id,
            )
            db.add(car)
            db.flush()
            assign_spot_for_car(db, car)
            append_audit_event(
                db,
                building.id,
                "car",
                car.id,
                "imported",
                {"resident_id": resident.id, "license_plate": plate, "row": row_number},
                manager.id,
            )
            savepoint.commit()
            result.rows.append(ImportRowResult(row_number, "ok", "Created", email, plate))
        except (ValueError, IntegrityError) as exc:
            savepoint.rollback()
            detail = str(exc.orig) if isinstance(exc, IntegrityError) else str(exc)
            if isinstance(exc, IntegrityError):
                detail = "Plate already active in this building"
            result.rows.append(
                ImportRowResult(row_number, "error", detail, row.get("email"), row.get("plate"))
            )
        if row_number % 20 == 0:
            print(f"  processed {row_number} import rows")

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return result


def create_car_request(
    db: Session,
    building: Building,
    resident: User,
    action: CarRequestAction,
    car_id: str | None,
    plate: str | None,
    make: str | None,
    model: str | None,
    color: str | None,
    note: str | None,
) -> CarRequest:
    if car_id is not None:
        car = db.scalar(select(Car).where(Car.id == car_id, Car.building_id == building.id))
        if car is None or car.owner_id != resident.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Car not found")

    subject = f"Car request: {action.value}"
    body_parts = [f"Action: {action.value}"]
    for label, value in (
        ("Plate", plate),
        ("Make", make),
        ("Model", model),
        ("Color", color),
        ("Note", note),
    ):
        if value:
            body_parts.append(f"{label}: {value}")
    ticket = Ticket(
        building_id=building.id,
        resident_id=resident.id,
        subject=subject,
        kind="car_request",
    )
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(ticket_id=ticket.id, author_id=resident.id, body="\n".join(body_parts)))

    car_request = CarRequest(
        ticket_id=ticket.id,
        building_id=building.id,
        resident_id=resident.id,
        action=action,
        car_id=car_id,
        plate=plate,
        make=make,
        model=model,
        color=color,
        note=note,
    )
    db.add(car_request)
    db.flush()
    append_audit_event(
        db,
        building.id,
        "car_request",
        car_request.id,
        "submitted",
        {"action": action.value, "plate": plate},
        resident.id,
    )
    db.commit()
    db.refresh(car_request)
    return car_request


def prefill_car_request(db: Session, car_request: CarRequest) -> dict:
    """What decision 16 calls prefilling the add-car payload for a manager."""
    return {
        "resident_id": car_request.resident_id,
        "make": car_request.make or "",
        "model": car_request.model or "",
        "color": car_request.color or "",
        "license_plate": car_request.plate or "",
        "note": car_request.note,
        "action": str(car_request.action),
        "car_id": car_request.car_id,
    }


def invite_resident(
    db: Session, building: Building, manager: User, unit: str, max_uses: int = 1
) -> InviteCode:
    invite = InviteCode(
        building_id=building.id,
        code=secrets.token_urlsafe(8),
        role=Role.resident,
        max_uses=max_uses,
        unit=unit,
    )
    db.add(invite)
    db.flush()
    append_audit_event(
        db, building.id, "invite_code", invite.id, "created", {"unit": unit}, manager.id
    )
    db.commit()
    db.refresh(invite)
    return invite
