from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_csrf, scoped_query
from app.models import Building, Car, ExceptionKind, Role, Schedule, ScheduleException, User
from app.schedule_engine import materialize_all_schedules
from app.schemas import (
    PauseUntilRequest,
    ScheduleCreate,
    ScheduleExceptionCreate,
    ScheduleResponse,
)

router = APIRouter(prefix="/schedules", tags=["schedules"], dependencies=[Depends(require_csrf)])


def _get_schedule_or_404(db: Session, user: User, schedule_id: str) -> Schedule:
    schedule = db.scalar(
        scoped_query(Schedule, user.building_id).where(Schedule.id == schedule_id)
    )
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    if schedule.owner_id != user.id and user.role not in (Role.manager,):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this schedule")
    return schedule


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ScheduleResponse)
def create_schedule(
    payload: ScheduleCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Schedule:
    car = db.scalar(scoped_query(Car, user.building_id).where(Car.id == payload.car_id))
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Car not found")
    if car.owner_id != user.id and user.role not in (Role.manager,):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this car")

    schedule = Schedule(
        building_id=user.building_id,
        car_id=car.id,
        owner_id=car.owner_id,
        ready_by_local_time=payload.ready_by_local_time,
        active_from=payload.active_from,
        active_until=payload.active_until,
    )
    schedule.weekdays = payload.weekdays
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get("", response_model=list[ScheduleResponse])
def list_schedules(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Schedule]:
    query = scoped_query(Schedule, user.building_id)
    if user.role not in (Role.manager,):
        query = query.where(Schedule.owner_id == user.id)
    return list(db.scalars(query))


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Schedule:
    return _get_schedule_or_404(db, user, schedule_id)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    schedule = _get_schedule_or_404(db, user, schedule_id)
    db.delete(schedule)
    db.commit()


@router.post("/{schedule_id}/exceptions", status_code=status.HTTP_201_CREATED)
def add_exception(
    schedule_id: str,
    payload: ScheduleExceptionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule = _get_schedule_or_404(db, user, schedule_id)
    exception = ScheduleException(
        schedule_id=schedule.id,
        local_date=payload.local_date,
        kind=payload.kind,
        override_local_time=payload.override_local_time,
    )
    db.add(exception)
    db.commit()
    return {"status": "created", "local_date": str(payload.local_date), "kind": payload.kind}


@router.post("/{schedule_id}/skip-tomorrow")
def skip_tomorrow(
    schedule_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    schedule = _get_schedule_or_404(db, user, schedule_id)
    building = db.get(Building, schedule.building_id)
    local_today = datetime.now(UTC).astimezone(ZoneInfo(building.timezone)).date()
    tomorrow = local_today + timedelta(days=1)
    exception = ScheduleException(
        schedule_id=schedule.id, local_date=tomorrow, kind=ExceptionKind.skip
    )
    db.add(exception)
    db.commit()
    return {"status": "skipped", "local_date": str(tomorrow)}


@router.post("/{schedule_id}/pause-until")
def pause_until(
    schedule_id: str,
    payload: PauseUntilRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    schedule = _get_schedule_or_404(db, user, schedule_id)
    schedule.paused_until = payload.paused_until
    db.add(schedule)
    db.commit()
    return {"status": "paused", "paused_until": str(payload.paused_until)}


@router.post("/materialize")
def materialize_now(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if user.role not in (Role.manager,):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only managers can trigger materialization")
    created = materialize_all_schedules(db)
    return {"created": len(created)}
