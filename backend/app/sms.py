"""Twilio-shaped inbound SMS command channel. POST /sms/inbound verifies the
request signature, matches the sender's phone number to a resident, and
handles two commands: "car" brings the car now, and a time like "7pm" books
a delivery for that time today. Unknown senders or unrecognized text get a
polite generic reply; nothing is ever created for a phone number that
doesn't match a known resident."""

import base64
import hashlib
import hmac
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import append_event
from app.models import Building, Car, Request, RequestSource, RequestState, User
from app.notifications import notify_state_change
from app.tasks import generate_tasks_for_request

_TIME_PATTERN = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*$", re.IGNORECASE)


def _aware(dt: datetime) -> datetime:
    # SQLite drops tzinfo on read; without normalizing, a naive value here
    # gets reinterpreted as system-local time by astimezone() instead of UTC
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def verify_twilio_signature(
    auth_token: str, url: str, params: dict[str, str], signature: str
) -> bool:
    # Twilio's signing scheme: base64(HMAC-SHA1(auth_token, url + sorted key+value pairs))
    data = url
    for key in sorted(params):
        data += key + params[key]
    expected = base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _parse_time_today(text: str, tz: ZoneInfo) -> datetime | None:
    match = _TIME_PATTERN.match(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3).lower()
    if not (1 <= hour <= 12 and 0 <= minute < 60):
        return None
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    now_local = datetime.now(tz)
    return now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _create_sms_request(db: Session, user: User, ready_by: datetime | None) -> Request:
    car = db.scalar(select(Car).where(Car.owner_id == user.id).order_by(Car.created_at).limit(1))
    if car is None:
        raise ValueError("no car on file")

    now = datetime.now(UTC)
    if ready_by is None:
        ready_by = now
        state = RequestState.queued
    else:
        if ready_by.tzinfo is None:
            ready_by = ready_by.replace(tzinfo=UTC)
        else:
            ready_by = ready_by.astimezone(UTC)
        state = (
            RequestState.queued
            if ready_by <= now + timedelta(minutes=30)
            else RequestState.scheduled
        )

    request = Request(
        building_id=user.building_id,
        owner_id=user.id,
        car_id=car.id,
        source=RequestSource.sms,
        ready_by=ready_by,
        state=state,
    )
    db.add(request)
    db.flush()
    append_event(db, request, "created", {"source": "sms"}, actor_id=user.id)
    if state == RequestState.queued:
        generate_tasks_for_request(db, request)
    db.commit()
    db.refresh(request)
    if state == RequestState.queued:
        notify_state_change(user, "Called", "")
    return request


def handle_inbound_sms(db: Session, from_number: str, body: str) -> str:
    user = db.scalar(select(User).where(User.phone_number == from_number, User.is_active.is_(True)))
    if user is None:
        return (
            "This number isn't linked to a Valet account. Add your phone "
            "number in the app to use text commands."
        )

    text = (body or "").strip().lower()
    building = db.get(Building, user.building_id)
    tz = ZoneInfo(building.timezone) if building else UTC

    if text == "car":
        try:
            request = _create_sms_request(db, user, ready_by=None)
        except ValueError:
            return "You don't have a car on file yet. Add one in the app first."
        local_ready = _aware(request.ready_by).astimezone(tz).strftime("%-I:%M %p")
        return f"On it. Your car will be ready by about {local_ready}."

    parsed_time = _parse_time_today(text, tz)
    if parsed_time is not None:
        try:
            request = _create_sms_request(db, user, ready_by=parsed_time)
        except ValueError:
            return "You don't have a car on file yet. Add one in the app first."
        local_ready = _aware(request.ready_by).astimezone(tz).strftime("%-I:%M %p")
        return f"Booked. Your car will be ready by {local_ready} today."

    return (
        'Text "car" to bring your car now, or a time like "7pm" to book '
        "a delivery today."
    )
