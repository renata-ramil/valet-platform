from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.db import get_db
from app.deps import require_csrf, require_role, scoped_query
from app.lifecycle import resident_label
from app.models import (
    Car,
    CarStatus,
    ParkingSpot,
    Request,
    RequestState,
    Role,
    Task,
    TaskType,
    User,
)
from app.schemas import (
    CarArrivedResponse,
    CarSearchResult,
    ParkTaskCompleteResponse,
    RequestResponse,
    TaskResponse,
    ValetQueueItem,
)
from app.spot_assignment import assign_spot_for_car
from app.tasks import create_park_task

router = APIRouter(prefix="/valet", tags=["valet"], dependencies=[Depends(require_csrf)])

OPEN_TASK_STATES = ("pending", "in_progress")
OPEN_REQUEST_STATES = (
    RequestState.queued,
    RequestState.assigned,
    RequestState.retrieving,
    RequestState.en_route,
)


@router.get("/queue", response_model=list[ValetQueueItem])
def get_queue(
    user: User = Depends(require_role(Role.valet, Role.manager)),
    db: Session = Depends(get_db),
) -> list[ValetQueueItem]:
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.building_id == user.building_id, Task.state.in_(OPEN_TASK_STATES))
            .order_by(Task.planned_start_at)
        )
    )
    now = datetime.now(UTC)
    items: list[ValetQueueItem] = []
    for task in tasks:
        request = db.get(Request, task.request_id)
        if request is None:
            continue
        # A park task (Car arrived) rides on the car's most recent request,
        # which is usually already in its terminal delivered state by then,
        # so only retrieve/deliver tasks are gated on an open request state
        if task.type != TaskType.park and RequestState(request.state) not in OPEN_REQUEST_STATES:
            continue
        car = db.get(Car, request.car_id)
        spot = db.get(ParkingSpot, car.parking_spot_id) if car.parking_spot_id else None
        planned = task.planned_start_at
        if planned.tzinfo is None:
            planned = planned.replace(tzinfo=UTC)
        minutes_to_deadline = (planned - now).total_seconds() / 60
        items.append(
            ValetQueueItem(
                task=TaskResponse.model_validate(task),
                request=RequestResponse(
                    id=request.id,
                    owner_id=request.owner_id,
                    car_id=request.car_id,
                    source=request.source,
                    ready_by=request.ready_by,
                    state=request.state,
                    resident_label=resident_label(RequestState(request.state)),
                    schedule_id=request.schedule_id,
                    created_at=request.created_at,
                    events=[],
                ),
                car=car,
                lane=spot.lane if spot else None,
                depth=spot.depth if spot else None,
                minutes_to_deadline=round(minutes_to_deadline, 1),
            )
        )
    return items


@router.get("/car-search", response_model=list[CarSearchResult])
def search_cars(
    plate: str = Query(min_length=1, max_length=20),
    user: User = Depends(require_role(Role.valet, Role.manager)),
    db: Session = Depends(get_db),
) -> list[CarSearchResult]:
    # Matching any active car whose plate contains the search text anywhere,
    # case insensitive; a pending or ended car never shows up here
    cars = list(
        db.scalars(
            scoped_query(Car, user.building_id)
            .where(Car.status == CarStatus.active, Car.license_plate.ilike(f"%{plate}%"))
            .order_by(Car.license_plate)
        )
    )
    return [
        CarSearchResult(
            id=car.id,
            license_plate=car.license_plate,
            make=car.make,
            model=car.model,
            color=car.color,
            owner_name=car.owner.full_name,
        )
        for car in cars
    ]


@router.post("/cars/{car_id}/arrived", response_model=CarArrivedResponse)
def car_arrived(
    car_id: str,
    user: User = Depends(require_role(Role.valet, Role.manager)),
    db: Session = Depends(get_db),
) -> CarArrivedResponse:
    car = db.scalar(scoped_query(Car, user.building_id).where(Car.id == car_id))
    if car is None or car.status != CarStatus.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Car not found")

    # Attaching the park task to the car's most recent request, the trip
    # this returning car just finished
    request = db.scalar(
        select(Request).where(Request.car_id == car.id).order_by(Request.created_at.desc()).limit(1)
    )
    if request is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This car has no prior request to attach a park task to"
        )

    task = create_park_task(db, request)
    db.flush()
    append_audit_event(
        db,
        user.building_id,
        "task",
        task.id,
        "car_arrived",
        {"valet_id": user.id, "car_id": car.id, "license_plate": car.license_plate},
        actor_id=user.id,
    )
    db.commit()
    db.refresh(task)
    return CarArrivedResponse(status="park_task_created", task_id=task.id, request_id=request.id)


@router.post("/tasks/{task_id}/complete-park", response_model=ParkTaskCompleteResponse)
def complete_park_task(
    task_id: str,
    user: User = Depends(require_role(Role.valet, Role.manager)),
    db: Session = Depends(get_db),
) -> ParkTaskCompleteResponse:
    task = db.scalar(scoped_query(Task, user.building_id).where(Task.id == task_id))
    if task is None or task.type != TaskType.park:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Park task not found")
    if task.state not in OPEN_TASK_STATES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This park task is already complete")

    request = db.get(Request, task.request_id)
    car = db.get(Car, request.car_id)
    spot = assign_spot_for_car(db, car)

    task.state = "done"
    task.completed_at = datetime.now(UTC)
    db.add(task)

    parked_payload = {"valet_id": user.id, "car_id": car.id}
    if spot is not None:
        parked_payload["lane"] = spot.lane
        parked_payload["depth"] = spot.depth
    append_audit_event(
        db, user.building_id, "task", task.id, "parked", parked_payload, actor_id=user.id
    )
    append_audit_event(
        db,
        user.building_id,
        "task",
        task.id,
        "key_returned",
        {"valet_id": user.id, "car_id": car.id},
        actor_id=user.id,
    )
    db.commit()
    return ParkTaskCompleteResponse(
        status="parked",
        task_id=task.id,
        lane=spot.lane if spot else None,
        depth=spot.depth if spot else None,
    )
