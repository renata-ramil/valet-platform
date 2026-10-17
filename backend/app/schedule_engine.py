from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_event
from app.models import (
    Building,
    ExceptionKind,
    Request,
    RequestSource,
    RequestState,
    Schedule,
    ScheduleException,
)

MATERIALIZE_WINDOW_HOURS = 48
LOOKAHEAD_DAYS = 3


def local_to_utc(local_date: date, local_time: time, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    naive = datetime.combine(local_date, local_time)
    aware = naive.replace(tzinfo=tz)
    return aware.astimezone(UTC)


def _effective_time_for_date(
    schedule: Schedule, local_date: date, exceptions_by_date: dict[date, ScheduleException]
) -> time | None:
    exception = exceptions_by_date.get(local_date)
    if exception is not None:
        if exception.kind == ExceptionKind.skip:
            return None
        return exception.override_local_time
    return schedule.ready_by_local_time


def _is_active_on(schedule: Schedule, local_date: date) -> bool:
    if local_date.weekday() not in schedule.weekdays:
        return False
    if local_date < schedule.active_from:
        return False
    if schedule.active_until is not None and local_date > schedule.active_until:
        return False
    if schedule.paused_until is not None and local_date <= schedule.paused_until:
        return False
    return True


def materialize_schedule(
    db: Session,
    schedule: Schedule,
    building: Building,
    now: datetime,
    window_hours: int = MATERIALIZE_WINDOW_HOURS,
) -> list[Request]:
    local_today = now.astimezone(ZoneInfo(building.timezone)).date()
    window_end = now + timedelta(hours=window_hours)

    exceptions = list(
        db.scalars(select(ScheduleException).where(ScheduleException.schedule_id == schedule.id))
    )
    exceptions_by_date = {e.local_date: e for e in exceptions}

    created: list[Request] = []
    for offset in range(LOOKAHEAD_DAYS):
        candidate_date = local_today + timedelta(days=offset)
        if not _is_active_on(schedule, candidate_date):
            continue
        effective_time = _effective_time_for_date(schedule, candidate_date, exceptions_by_date)
        if effective_time is None:
            continue

        ready_by_utc = local_to_utc(candidate_date, effective_time, building.timezone)
        if not (now <= ready_by_utc <= window_end):
            continue

        existing = db.scalar(
            select(Request).where(
                Request.schedule_id == schedule.id, Request.local_date == candidate_date
            )
        )
        if existing is not None:
            continue

        request = Request(
            building_id=schedule.building_id,
            owner_id=schedule.owner_id,
            car_id=schedule.car_id,
            source=RequestSource.scheduled,
            ready_by=ready_by_utc,
            state=RequestState.scheduled,
            schedule_id=schedule.id,
            local_date=candidate_date,
        )
        db.add(request)
        db.flush()
        append_event(
            db,
            request,
            "created",
            {"source": "schedule", "schedule_id": schedule.id, "local_date": str(candidate_date)},
            actor_id=None,
        )
        created.append(request)

    return created


def materialize_all_schedules(
    db: Session, now: datetime | None = None, window_hours: int = MATERIALIZE_WINDOW_HOURS
) -> list[Request]:
    now = now or datetime.now(UTC)
    created: list[Request] = []
    schedules = list(db.scalars(select(Schedule)))
    buildings_by_id = {b.id: b for b in db.scalars(select(Building))}
    for schedule in schedules:
        building = buildings_by_id[schedule.building_id]
        created.extend(materialize_schedule(db, schedule, building, now, window_hours))
    db.commit()
    return created
