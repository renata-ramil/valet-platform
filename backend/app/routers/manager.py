import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_csrf, require_role
from app.models import InviteCode, Request, RequestState, Role, Task, User
from app.ratelimit import rate_limit
from app.schemas import (
    InviteCodeCreate,
    InviteCodeResponse,
    ManagerDashboardResponse,
    WhatIfResponse,
)
from app.whatif import run_whatif

router = APIRouter(
    prefix="/manager",
    tags=["manager"],
    dependencies=[Depends(require_csrf)],
)

TIMELINE_BUCKET_MINUTES = 15
TIMELINE_HOURS = 12


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@router.post(
    "/invite-codes",
    status_code=status.HTTP_201_CREATED,
    response_model=InviteCodeResponse,
    dependencies=[Depends(rate_limit("invite-code", limit=10, window_seconds=60))],
)
def create_invite_code(
    payload: InviteCodeCreate,
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> InviteCode:
    invite = InviteCode(
        building_id=user.building_id,
        code=secrets.token_urlsafe(8),
        role=payload.role,
        max_uses=payload.max_uses,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


@router.get("/dashboard", response_model=ManagerDashboardResponse)
def dashboard(
    user: User = Depends(require_role(Role.manager)),
    db: Session = Depends(get_db),
) -> ManagerDashboardResponse:
    requests = list(db.scalars(select(Request).where(Request.building_id == user.building_id)))

    counts_by_state: dict[str, int] = {}
    for request in requests:
        counts_by_state[request.state] = counts_by_state.get(request.state, 0) + 1

    valets = list(
        db.scalars(
            select(User).where(User.building_id == user.building_id, User.role == Role.valet)
        )
    )
    open_tasks = list(
        db.scalars(
            select(Task).where(
                Task.building_id == user.building_id, Task.state.in_(("pending", "in_progress"))
            )
        )
    )
    tasks_by_valet: dict[str, Task] = {}
    for task in open_tasks:
        if task.assigned_valet_id:
            tasks_by_valet[task.assigned_valet_id] = task
    valet_roster = [
        {
            "valet_id": valet.id,
            "full_name": valet.full_name,
            "current_task_id": tasks_by_valet[valet.id].id if valet.id in tasks_by_valet else None,
            "current_task_type": tasks_by_valet[valet.id].type
            if valet.id in tasks_by_valet
            else None,
        }
        for valet in valets
    ]

    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    delivered_today = [
        r
        for r in requests
        if r.state == RequestState.delivered and _aware(r.created_at) >= today_start
    ]
    on_time_rate_today: float | None = None
    if delivered_today:
        on_time_count = 0
        for request in delivered_today:
            ready_by = _aware(request.ready_by)
            last_event = max(request.events, key=lambda e: e.created_at, default=None)
            delivered_at = _aware(last_event.created_at if last_event else request.created_at)
            if delivered_at <= ready_by:
                on_time_count += 1
        on_time_rate_today = round(on_time_count / len(delivered_today), 3)

    bucket_count = (TIMELINE_HOURS * 60) // TIMELINE_BUCKET_MINUTES
    timeline = []
    for i in range(bucket_count):
        bucket_start = now + timedelta(minutes=i * TIMELINE_BUCKET_MINUTES)
        bucket_end = bucket_start + timedelta(minutes=TIMELINE_BUCKET_MINUTES)
        count = 0
        for request in requests:
            ready_by = _aware(request.ready_by)
            if bucket_start <= ready_by < bucket_end and request.state in (
                RequestState.scheduled,
                RequestState.queued,
                RequestState.assigned,
                RequestState.retrieving,
            ):
                count += 1
        timeline.append({"bucket_start": bucket_start.isoformat(), "count": count})

    return ManagerDashboardResponse(
        counts_by_state=counts_by_state,
        valet_roster=valet_roster,
        on_time_rate_today=on_time_rate_today,
        timeline=timeline,
    )


@router.get(
    "/what-if",
    response_model=WhatIfResponse,
    dependencies=[Depends(rate_limit("manager-whatif", limit=20, window_seconds=60))],
)
def what_if(
    valet_count: int,
    demand_multiplier: float,
    user: User = Depends(require_role(Role.manager)),
) -> WhatIfResponse:
    if not (1 <= valet_count <= 20):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "valet_count must be between 1 and 20")
    if not (0.1 <= demand_multiplier <= 3.0):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "demand_multiplier must be between 0.1 and 3.0"
        )
    result = run_whatif(valet_count, demand_multiplier)
    return WhatIfResponse(**result)
