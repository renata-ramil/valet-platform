from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit import append_event
from app.db import get_db
from app.deps import get_current_user, require_csrf, scoped_query
from app.eta import get_eta_provider
from app.events import building_channel, get_event_bus
from app.lifecycle import IllegalTransitionError, resident_label, validate_transition
from app.models import Building, Car, Request, RequestSource, RequestState, Role, User
from app.notifications import notify_state_change
from app.schemas import RequestCreate, RequestEventResponse, RequestResponse, TransitionRequest
from app.settings import settings
from app.tasks import generate_tasks_for_request, sync_tasks_on_transition

router = APIRouter(prefix="/requests", tags=["requests"], dependencies=[Depends(require_csrf)])


ACTIVE_ETA_STATES = (
    RequestState.scheduled,
    RequestState.queued,
    RequestState.assigned,
    RequestState.retrieving,
    RequestState.en_route,
)


def _aware(dt: datetime) -> datetime:
    # SQLite drops tzinfo on read; without it, datetimes serialize without a 'Z'
    # and browsers misparse them as local time instead of UTC
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _to_response(request: Request) -> RequestResponse:
    eta_ready_by = None
    eta_latest = None
    eta_calibrated = False
    if RequestState(request.state) in ACTIVE_ETA_STATES:
        estimate = get_eta_provider().predict_interval(request)
        now = datetime.now(UTC)
        eta_ready_by = now + timedelta(minutes=estimate.median_minutes)
        eta_latest = now + timedelta(minutes=estimate.p90_minutes)
        eta_calibrated = estimate.calibrated

    return RequestResponse(
        id=request.id,
        owner_id=request.owner_id,
        car_id=request.car_id,
        source=request.source,
        ready_by=_aware(request.ready_by),
        state=request.state,
        resident_label=resident_label(RequestState(request.state)),
        schedule_id=request.schedule_id,
        created_at=_aware(request.created_at),
        events=[
            RequestEventResponse(
                type=event.type, payload=event.payload, created_at=_aware(event.created_at)
            )
            for event in request.events
        ],
        eta_ready_by=eta_ready_by,
        eta_latest=eta_latest,
        eta_calibrated=eta_calibrated,
    )


def _publish_update(request: Request) -> None:
    response = _to_response(request)
    payload = response.model_dump(mode="json")
    payload["type"] = "request_update"
    bus = get_event_bus()
    bus.publish(request.owner_id, payload)
    bus.publish(building_channel(request.building_id), payload)


def _notify(db: Session, request: Request) -> None:
    building = db.get(Building, request.building_id)
    local_time = request.ready_by.astimezone(ZoneInfo(building.timezone)).strftime("%-I:%M %p")
    owner = db.get(User, request.owner_id)
    notify_state_change(owner, resident_label(RequestState(request.state)), local_time)


def _get_request_or_404(db: Session, user: User, request_id: str) -> Request:
    request = db.scalar(scoped_query(Request, user.building_id).where(Request.id == request_id))
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if request.owner_id != user.id and user.role not in (Role.manager, Role.valet):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this request")
    return request


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RequestResponse)
def create_request(
    payload: RequestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Request:
    car = db.scalar(scoped_query(Car, user.building_id).where(Car.id == payload.car_id))
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Car not found")
    if car.owner_id != user.id and user.role not in (Role.manager,):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this car")

    now = datetime.now(UTC)
    if payload.ready_by is None:
        ready_by = now
        state = RequestState.queued
    else:
        ready_by = payload.ready_by
        if ready_by.tzinfo is None:
            ready_by = ready_by.replace(tzinfo=UTC)
        if ready_by < now + timedelta(minutes=settings.min_lead_minutes):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"ready_by must be at least {settings.min_lead_minutes} minutes in the future",
            )
        state = (
            RequestState.queued
            if ready_by <= now + timedelta(minutes=30)
            else RequestState.scheduled
        )

    request = Request(
        building_id=user.building_id,
        owner_id=car.owner_id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=ready_by,
        state=state,
    )
    db.add(request)
    db.flush()
    append_event(db, request, "created", {"source": "on_demand"}, actor_id=user.id)
    if state == RequestState.queued:
        generate_tasks_for_request(db, request)
    db.commit()
    db.refresh(request)
    _publish_update(request)
    if state == RequestState.queued:
        _notify(db, request)
    return _to_response(request)


@router.get("", response_model=list[RequestResponse])
def list_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list:
    query = scoped_query(Request, user.building_id)
    if user.role not in (Role.manager, Role.valet):
        query = query.where(Request.owner_id == user.id)
    requests = list(db.scalars(query))
    return [_to_response(r) for r in requests]


@router.get("/{request_id}", response_model=RequestResponse)
def get_request(
    request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    request = _get_request_or_404(db, user, request_id)
    return _to_response(request)


@router.post("/{request_id}/cancel", response_model=RequestResponse)
def cancel_request(
    request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    request = _get_request_or_404(db, user, request_id)
    try:
        validate_transition(RequestState(request.state), RequestState.cancelled)
    except IllegalTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    request.state = RequestState.cancelled
    append_event(db, request, RequestState.cancelled.value, {}, actor_id=user.id)
    db.add(request)
    db.commit()
    db.refresh(request)
    _publish_update(request)
    return _to_response(request)


@router.post("/{request_id}/transition", response_model=RequestResponse)
def transition_request(
    request_id: str,
    payload: TransitionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role not in (Role.valet, Role.manager):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only valets and managers can transition requests"
        )
    request = db.scalar(scoped_query(Request, user.building_id).where(Request.id == request_id))
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    try:
        validate_transition(RequestState(request.state), payload.target_state)
    except IllegalTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    request.state = payload.target_state
    append_event(db, request, payload.target_state.value, {}, actor_id=user.id)
    sync_tasks_on_transition(db, request, payload.target_state, user.id)
    db.add(request)
    db.commit()
    db.refresh(request)
    _publish_update(request)
    if payload.target_state in (RequestState.en_route, RequestState.delivered):
        _notify(db, request)
    return _to_response(request)
