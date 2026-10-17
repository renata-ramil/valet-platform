import json
import time

import anyio
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.db import SessionLocal
from app.events import building_channel, get_event_bus
from app.models import Role, User
from app.security import SESSION_COOKIE_NAME, get_valid_session

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15
POLL_TIMEOUT_SECONDS = 1.0


def _authenticate_for_stream(request: Request, *allowed_roles: Role) -> User:
    """Authenticating with a short-lived session, closed before the stream
    opens, rather than Depends(get_current_user)'s normal get_db session.

    FastAPI only tears down a yield-based dependency once its endpoint's
    response fully finishes, and for a StreamingResponse that means "once
    the stream itself closes": for an SSE connection, that can be minutes
    or hours away. Authenticating through the ordinary dependency chain
    would hold that db session, and whatever lock its own transaction
    needs, open for the entire SSE connection instead of just the moment
    of the auth check.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    db = SessionLocal()
    try:
        session = get_valid_session(db, session_id)
        if session is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
        user = db.get(User, session.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
        if allowed_roles and user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this role")
        db.expunge(user)
        return user
    finally:
        db.close()


def _sse_response(request: Request, channel: str) -> StreamingResponse:
    bus = get_event_bus()
    raw_last_event_id = request.headers.get("last-event-id")
    last_event_id = int(raw_last_event_id) if raw_last_event_id else None
    subscription = bus.subscribe(channel, last_event_id)

    async def event_generator():
        last_heartbeat = time.monotonic()
        try:
            while True:
                if await request.is_disconnected():
                    break
                item = await anyio.to_thread.run_sync(subscription.get, POLL_TIMEOUT_SECONDS)
                if item is None:
                    now = time.monotonic()
                    if now - last_heartbeat >= HEARTBEAT_SECONDS:
                        yield ": heartbeat\n\n"
                        last_heartbeat = now
                    continue
                event_id, payload = item
                event_type = payload.get("type", "message")
                yield f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(payload)}\n\n"
                last_heartbeat = time.monotonic()
        finally:
            bus.unsubscribe(channel, subscription)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/events")
async def stream_events(request: Request):
    user = _authenticate_for_stream(request)
    return _sse_response(request, user.id)


@router.get("/events/building")
async def stream_building_events(request: Request):
    user = _authenticate_for_stream(request, Role.manager, Role.valet)
    return _sse_response(request, building_channel(user.building_id))
