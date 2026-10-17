import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_feed import UnsafeUrlError, fetch_and_parse, generate_feed, propose_deliveries
from app.db import get_db
from app.deps import get_current_user, require_csrf
from app.lifecycle import resident_label
from app.models import Request, RequestState, User
from app.ratelimit import rate_limit

router = APIRouter(prefix="/calendar", tags=["calendar"])

FEED_WINDOW_DAYS = 14
UPCOMING_STATES = (RequestState.scheduled, RequestState.queued, RequestState.assigned)


class ImportRequest(BaseModel):
    ics_url: str


@router.post("/token", dependencies=[Depends(require_csrf)])
def issue_calendar_token(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not user.calendar_token:
        user.calendar_token = secrets.token_urlsafe(24)
        db.add(user)
        db.commit()
    return {"feed_path": f"/calendar/feed/{user.calendar_token}.ics"}


@router.get(
    "/feed/{token}.ics",
    dependencies=[Depends(rate_limit("calendar-feed", limit=30, window_seconds=60))],
)
def calendar_feed(token: str, db: Session = Depends(get_db)) -> Response:
    user = db.scalar(select(User).where(User.calendar_token == token))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown feed token")

    now = datetime.now(UTC)
    window_end = now + timedelta(days=FEED_WINDOW_DAYS)
    requests = db.scalars(
        select(Request).where(
            Request.owner_id == user.id,
            Request.state.in_(UPCOMING_STATES),
            Request.ready_by >= now,
            Request.ready_by <= window_end,
        )
    ).all()
    events = [
        {
            "id": r.id,
            "ready_by": r.ready_by if r.ready_by.tzinfo else r.ready_by.replace(tzinfo=UTC),
            "summary": f"Car ready ({resident_label(RequestState(r.state))})",
        }
        for r in requests
    ]
    ics = generate_feed(user.full_name, events)
    return Response(content=ics, media_type="text/calendar")


@router.post(
    "/import",
    dependencies=[
        Depends(require_csrf),
        Depends(rate_limit("calendar-import", limit=5, window_seconds=60)),
    ],
)
def import_calendar(
    payload: ImportRequest, user: User = Depends(get_current_user)
) -> dict:
    try:
        events = fetch_and_parse(payload.ics_url)
    except UnsafeUrlError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not fetch calendar: {exc}"
        ) from exc

    proposals = propose_deliveries(events)
    return {"proposals": proposals}
