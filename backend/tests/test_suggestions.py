from datetime import UTC, datetime, timedelta

from app.audit import append_event
from app.models import Request, RequestSource, RequestState

from tests.conftest import make_car, make_user


def _login(client, email, password="password123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_no_suggestions_without_history(client, db_session, building):
    make_user(db_session, building.id, email="resident@example.com")
    csrf = _login(client, "resident@example.com")
    response = client.get("/suggestions", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json() == []


def test_suggests_a_recurring_weekday_slot(client, db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)

    base = datetime(2026, 1, 5, 8, 5, tzinfo=UTC)  # a Monday
    for week in range(6):
        for weekday_offset in range(5):  # Mon-Fri
            created_at = base + timedelta(weeks=week, days=weekday_offset)
            request = Request(
                building_id=building.id,
                owner_id=resident.id,
                car_id=car.id,
                source=RequestSource.on_demand,
                ready_by=created_at,
                state=RequestState.delivered,
                created_at=created_at,
            )
            db_session.add(request)
            db_session.flush()
            append_event(db_session, request, "created", {}, actor_id=resident.id)
    db_session.commit()

    csrf = _login(client, "resident@example.com")
    response = client.get("/suggestions", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    suggestions = response.json()
    assert len(suggestions) == 1
    assert sorted(suggestions[0]["weekdays"]) == [0, 1, 2, 3, 4]
    assert suggestions[0]["ready_by_local_time"].startswith("08:0")
    assert suggestions[0]["recurrence_probability"] >= 0.6
