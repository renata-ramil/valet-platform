from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_audit_event
from app.eta import start_by
from app.models import Car, ParkingSpot, Request, RequestState, Task, TaskType


def generate_tasks_for_request(db: Session, request: Request) -> list[Task]:
    retrieve = Task(
        building_id=request.building_id,
        request_id=request.id,
        type=TaskType.retrieve,
        planned_start_at=start_by(request),
    )
    deliver = Task(
        building_id=request.building_id,
        request_id=request.id,
        type=TaskType.deliver,
        planned_start_at=request.ready_by,
    )
    db.add(retrieve)
    db.add(deliver)
    return [retrieve, deliver]


def _tasks_for_request(db: Session, request_id: str) -> list[Task]:
    return list(db.scalars(select(Task).where(Task.request_id == request_id)))


def sync_tasks_on_transition(
    db: Session, request: Request, target_state: RequestState, valet_id: str | None
) -> None:
    tasks = _tasks_for_request(db, request.id)
    retrieve_task = next((t for t in tasks if t.type == TaskType.retrieve), None)
    deliver_task = next((t for t in tasks if t.type == TaskType.deliver), None)
    now = datetime.now(UTC)

    if target_state == RequestState.assigned and valet_id:
        for task in (retrieve_task, deliver_task):
            if task is not None:
                task.assigned_valet_id = valet_id
                db.add(task)
    elif target_state == RequestState.retrieving and retrieve_task is not None:
        retrieve_task.state = "in_progress"
        db.add(retrieve_task)
        append_audit_event(
            db,
            request.building_id,
            "task",
            retrieve_task.id,
            "key_taken",
            {"valet_id": valet_id, "car_id": request.car_id},
            actor_id=valet_id,
        )
    elif target_state == RequestState.en_route:
        if retrieve_task is not None:
            retrieve_task.state = "done"
            retrieve_task.completed_at = now
            db.add(retrieve_task)
            # Logging the spot the car left, then freeing it so a newly
            # arrived car can be assigned there
            payload = {"valet_id": valet_id, "car_id": request.car_id}
            car = db.get(Car, request.car_id)
            if car is not None and car.parking_spot_id:
                spot = db.get(ParkingSpot, car.parking_spot_id)
                if spot is not None:
                    payload["lane"] = spot.lane
                    payload["depth"] = spot.depth
                    spot.is_occupied = False
                    db.add(spot)
                car.parking_spot_id = None
                db.add(car)
            append_audit_event(
                db,
                request.building_id,
                "task",
                retrieve_task.id,
                "car_retrieved",
                payload,
                actor_id=valet_id,
            )
        if deliver_task is not None:
            deliver_task.state = "in_progress"
            db.add(deliver_task)
    elif target_state == RequestState.delivered and deliver_task is not None:
        deliver_task.state = "done"
        deliver_task.completed_at = now
        db.add(deliver_task)
        append_audit_event(
            db,
            request.building_id,
            "task",
            deliver_task.id,
            "delivered_at_lobby",
            {"valet_id": valet_id, "car_id": request.car_id},
            actor_id=valet_id,
        )


def create_park_task(db: Session, request: Request) -> Task:
    task = Task(
        building_id=request.building_id,
        request_id=request.id,
        type=TaskType.park,
        planned_start_at=datetime.now(UTC),
    )
    db.add(task)
    return task
