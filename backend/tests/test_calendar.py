from datetime import UTC, datetime, timedelta

from app.calendar_feed import UnsafeUrlError, generate_feed, parse_ics, propose_deliveries
from app.models import Request, RequestSource, RequestState, Role

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.json()["csrf_token"]


SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1@example.com
SUMMARY:Dinner downtown
LOCATION:123 Main St
DTSTART:{with_location}
END:VEVENT
BEGIN:VEVENT
UID:2@example.com
SUMMARY:Phone call
DTSTART:{no_location}
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_extracts_summary_start_and_location():
    start = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
    text = SAMPLE_ICS.format(with_location=start, no_location=start)
    events = parse_ics(text)
    assert len(events) == 2
    assert events[0].summary == "Dinner downtown"
    assert events[0].location == "123 Main St"
    assert events[1].location is None


def test_propose_deliveries_only_for_events_with_a_future_location():
    now = datetime.now(UTC)
    text = SAMPLE_ICS.format(
        with_location=(now + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ"),
        no_location=(now + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ"),
    )
    events = parse_ics(text)
    proposals = propose_deliveries(events, now=now)
    assert len(proposals) == 1
    assert proposals[0]["event_summary"] == "Dinner downtown"
    proposed_ready_by = datetime.fromisoformat(proposals[0]["proposed_ready_by"])
    event_start = datetime.fromisoformat(proposals[0]["event_start"])
    assert (event_start - proposed_ready_by) == timedelta(minutes=15)


def test_propose_deliveries_skips_past_events():
    now = datetime.now(UTC)
    text = SAMPLE_ICS.format(
        with_location=(now - timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ"),
        no_location=(now + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ"),
    )
    events = parse_ics(text)
    proposals = propose_deliveries(events, now=now)
    assert proposals == []


def test_generate_feed_round_trips_through_parse_ics():
    ready_by = datetime.now(UTC) + timedelta(days=1)
    event = {"id": "abc", "ready_by": ready_by, "summary": "Car ready"}
    ics = generate_feed("Test Resident", [event])
    events = parse_ics(ics)
    assert len(events) == 1
    assert events[0].summary == "Car ready"
    assert abs((events[0].start - ready_by).total_seconds()) < 1


def test_import_rejects_localhost_url():
    from app.calendar_feed import fetch_and_parse

    raised = False
    try:
        fetch_and_parse("http://localhost/whatever.ics")
    except UnsafeUrlError:
        raised = True
    assert raised


def test_feed_requires_a_valid_token(client):
    response = client.get("/calendar/feed/not-a-real-token.ics")
    assert response.status_code == 404


def test_feed_returns_only_the_owners_upcoming_requests(client, db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "cal-resident@example.com")
    other = make_user(db_session, building.id, Role.resident, "cal-other@example.com")
    car = make_car(db_session, building.id, resident.id, "CAL001")
    other_car = make_car(db_session, building.id, other.id, "CAL002")

    ready_by = datetime.now(UTC) + timedelta(days=2)
    db_session.add(
        Request(
            building_id=building.id, owner_id=resident.id, car_id=car.id,
            source=RequestSource.scheduled, ready_by=ready_by, state=RequestState.scheduled,
        )
    )
    db_session.add(
        Request(
            building_id=building.id, owner_id=other.id, car_id=other_car.id,
            source=RequestSource.scheduled, ready_by=ready_by, state=RequestState.scheduled,
        )
    )
    db_session.commit()

    csrf = _login(client, resident.email)
    token_response = client.post("/calendar/token", headers={"X-CSRF-Token": csrf})
    feed_path = token_response.json()["feed_path"]

    feed = client.get(feed_path)
    assert feed.status_code == 200
    assert feed.text.count("BEGIN:VEVENT") == 1


def test_import_endpoint_requires_auth(client):
    response = client.post("/calendar/import", json={"ics_url": "http://localhost/x.ics"})
    assert response.status_code == 401
