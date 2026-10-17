"""Tool layer for the support assistant.

Every function here takes a SupportContext built from the authenticated
session (never from model-supplied arguments) and operates only on that
user's own rows, scoped to their building. No function accepts a user id,
owner id, or building id as an argument: identity always comes from the
context, never from the model, so the model cannot ask a tool to act on
someone else's data even if a prompt injection convinces it to try.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import scoped_query
from app.lifecycle import resident_label
from app.models import (
    Car,
    RequestState,
    RescheduleProposal,
    Schedule,
    Ticket,
    TicketMessage,
    User,
)
from app.security import hash_password, verify_password

PROPOSAL_LIFETIME = timedelta(minutes=10)
ACTIVE_REQUEST_STATES = (
    RequestState.scheduled,
    RequestState.queued,
    RequestState.assigned,
    RequestState.retrieving,
    RequestState.en_route,
)


@dataclass
class SupportContext:
    db: Session
    user: User


class ToolError(Exception):
    """A user-facing error from a tool call (not found, expired, etc)."""


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def get_my_requests(ctx: SupportContext, limit: int = 5) -> list[dict]:
    from app.models import Request

    rows = ctx.db.scalars(
        select(Request)
        .where(Request.building_id == ctx.user.building_id, Request.owner_id == ctx.user.id)
        .order_by(Request.created_at.desc())
        .limit(limit)
    ).all()
    results = []
    for r in rows:
        car = ctx.db.get(Car, r.car_id)
        results.append(
            {
                "request_id": r.id,
                "car": f"{car.color} {car.make} {car.model}" if car else "unknown car",
                "state": r.state,
                "resident_label": resident_label(RequestState(r.state)),
                "ready_by": _aware(r.ready_by).isoformat(),
            }
        )
    return results


def get_request_status(ctx: SupportContext, request_id: str | None = None) -> dict:
    from app.models import Request

    query = scoped_query(Request, ctx.user.building_id).where(Request.owner_id == ctx.user.id)
    if request_id:
        query = query.where(Request.id == request_id)
    else:
        query = query.where(Request.state.in_(ACTIVE_REQUEST_STATES)).order_by(
            Request.created_at.desc()
        )
    request = ctx.db.scalar(query)
    if request is None:
        raise ToolError(
            "No matching request found for this account"
            if request_id
            else "No active request right now"
        )
    car = ctx.db.get(Car, request.car_id)
    return {
        "request_id": request.id,
        "car": f"{car.color} {car.make} {car.model}" if car else "unknown car",
        "state": request.state,
        "resident_label": resident_label(RequestState(request.state)),
        "ready_by": _aware(request.ready_by).isoformat(),
    }


def list_my_schedules(ctx: SupportContext) -> list[dict]:
    rows = ctx.db.scalars(
        scoped_query(Schedule, ctx.user.building_id).where(Schedule.owner_id == ctx.user.id)
    ).all()
    results = []
    for s in rows:
        car = ctx.db.get(Car, s.car_id)
        results.append(
            {
                "schedule_id": s.id,
                "car": f"{car.color} {car.make} {car.model}" if car else "unknown car",
                "weekdays": s.weekdays,
                "ready_by_local_time": s.ready_by_local_time.strftime("%H:%M"),
                "paused_until": str(s.paused_until) if s.paused_until else None,
            }
        )
    return results


_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _get_owned_schedule(ctx: SupportContext, schedule_id: str) -> Schedule:
    schedule = ctx.db.scalar(
        scoped_query(Schedule, ctx.user.building_id).where(Schedule.id == schedule_id)
    )
    if schedule is None or schedule.owner_id != ctx.user.id:
        raise ToolError("No matching schedule found for this account")
    return schedule


def propose_reschedule(
    ctx: SupportContext,
    schedule_id: str,
    change_type: str,
    weekdays: list[int] | None = None,
    ready_by_local_time: str | None = None,
    paused_until: str | None = None,
) -> dict:
    """Builds a proposed change and stores it with a one-time token. Does
    nothing else: the schedule is untouched until confirm_reschedule runs
    with the exact token, which only the UI holds after the resident taps
    Confirm on the rendered proposal card."""
    schedule = _get_owned_schedule(ctx, schedule_id)

    if change_type == "time_change":
        if not weekdays or not ready_by_local_time:
            raise ToolError("A time change needs both weekdays and a time")
        hour, minute = (int(p) for p in ready_by_local_time.split(":"))
        days = ", ".join(_WEEKDAY_NAMES[d] for d in sorted(set(weekdays)))
        description = f"Change ready time to {hour:02d}:{minute:02d} on {days}"
        proposal = RescheduleProposal(
            building_id=ctx.user.building_id,
            owner_id=ctx.user.id,
            schedule_id=schedule.id,
            change_type=change_type,
            description=description,
            proposed_weekdays=",".join(str(d) for d in sorted(set(weekdays))),
            proposed_ready_by_local_time=datetime(2000, 1, 1, hour, minute).time(),
        )
    elif change_type == "skip_next":
        description = "Skip the next scheduled pickup"
        proposal = RescheduleProposal(
            building_id=ctx.user.building_id,
            owner_id=ctx.user.id,
            schedule_id=schedule.id,
            change_type=change_type,
            description=description,
        )
    elif change_type == "pause":
        if not paused_until:
            raise ToolError("A pause needs an until date")
        description = f"Pause this schedule until {paused_until}"
        proposal = RescheduleProposal(
            building_id=ctx.user.building_id,
            owner_id=ctx.user.id,
            schedule_id=schedule.id,
            change_type=change_type,
            description=description,
            proposed_paused_until=date.fromisoformat(paused_until),
        )
    else:
        raise ToolError(f"Unknown change type: {change_type}")

    token = secrets.token_urlsafe(24)
    proposal.token_hash = hash_password(token)
    proposal.expires_at = datetime.now(UTC) + PROPOSAL_LIFETIME
    ctx.db.add(proposal)
    ctx.db.commit()
    ctx.db.refresh(proposal)

    return {
        "proposal_id": proposal.id,
        "description": description,
        "confirmation_token": token,
        "expires_in_seconds": int(PROPOSAL_LIFETIME.total_seconds()),
    }


def confirm_reschedule(ctx: SupportContext, proposal_id: str, token: str) -> dict:
    """Applies a previously proposed change. Only reachable with the exact
    token issued by propose_reschedule; the chat endpoint only calls this
    in direct response to a UI-originated confirm action, never from model
    output alone, so no amount of persuasive chat text can trigger it."""
    proposal = ctx.db.get(RescheduleProposal, proposal_id)
    if (
        proposal is None
        or proposal.owner_id != ctx.user.id
        or proposal.building_id != ctx.user.building_id
    ):
        raise ToolError("No matching proposal found")
    if proposal.used_at is not None:
        raise ToolError("This proposal was already confirmed")
    if _aware(proposal.expires_at) < datetime.now(UTC):
        raise ToolError("This proposal has expired, ask me to propose the change again")
    if not verify_password(proposal.token_hash, token):
        raise ToolError("Invalid confirmation token")

    schedule = ctx.db.get(Schedule, proposal.schedule_id)
    if schedule is None or schedule.owner_id != ctx.user.id:
        raise ToolError("The underlying schedule no longer exists")

    if proposal.change_type == "time_change":
        schedule.weekdays = [int(d) for d in proposal.proposed_weekdays.split(",")]
        schedule.ready_by_local_time = proposal.proposed_ready_by_local_time
    elif proposal.change_type == "pause":
        schedule.paused_until = proposal.proposed_paused_until
    elif proposal.change_type == "skip_next":
        from app.models import ExceptionKind, ScheduleException

        next_date = date.today() + timedelta(days=1)
        ctx.db.add(
            ScheduleException(
                schedule_id=schedule.id, local_date=next_date, kind=ExceptionKind.skip
            )
        )

    proposal.used_at = datetime.now(UTC)
    ctx.db.add(schedule)
    ctx.db.add(proposal)
    ctx.db.commit()

    return {"status": "confirmed", "description": proposal.description}


def create_ticket(ctx: SupportContext, subject: str, message: str) -> dict:
    ticket = Ticket(building_id=ctx.user.building_id, resident_id=ctx.user.id, subject=subject)
    ctx.db.add(ticket)
    ctx.db.flush()
    ctx.db.add(TicketMessage(ticket_id=ticket.id, author_id=ctx.user.id, body=message))
    ctx.db.commit()
    ctx.db.refresh(ticket)
    return {"ticket_id": ticket.id, "status": ticket.status}


def escalate_to_human(ctx: SupportContext, reason: str, transcript: str) -> dict:
    subject = f"Escalated: {reason}"[:200]
    return create_ticket(ctx, subject=subject, message=transcript)
