from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.models import ExceptionKind, Request, Schedule, ScheduleException
from app.schedule_engine import local_to_utc, materialize_all_schedules, materialize_schedule
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from tests.conftest import make_car, make_user


def _make_schedule(db_session, building, weekdays=(0, 1, 2, 3, 4), ready_time=time(8, 0)):
    resident = make_user(db_session, building.id, email="schedule-owner@example.com")
    car = make_car(db_session, building.id, resident.id)
    schedule = Schedule(
        building_id=building.id,
        car_id=car.id,
        owner_id=resident.id,
        ready_by_local_time=ready_time,
        active_from=date(2020, 1, 1),
    )
    schedule.weekdays = list(weekdays)
    db_session.add(schedule)
    db_session.commit()
    db_session.refresh(schedule)
    return schedule


def test_materializing_twice_is_idempotent(db_session, building):
    schedule = _make_schedule(db_session, building)
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)  # a Monday at noon UTC

    first = materialize_schedule(db_session, schedule, building, now)
    db_session.commit()
    second = materialize_schedule(db_session, schedule, building, now)
    db_session.commit()

    assert len(first) > 0
    assert len(second) == 0

    all_requests = list(db_session.query(Request).filter(Request.schedule_id == schedule.id))
    local_dates = [r.local_date for r in all_requests]
    assert len(local_dates) == len(set(local_dates))


def test_materialized_request_local_time_matches_schedule(db_session, building):
    schedule = _make_schedule(db_session, building, ready_time=time(8, 0))
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)

    created = materialize_schedule(db_session, schedule, building, now)
    db_session.commit()

    assert len(created) > 0
    tz = ZoneInfo(building.timezone)
    for request in created:
        local_dt = request.ready_by.astimezone(tz)
        assert local_dt.hour == 8
        assert local_dt.minute == 0
        assert local_dt.weekday() in schedule.weekdays


def test_skip_exception_prevents_materialization(db_session, building):
    schedule = _make_schedule(db_session, building)
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    tomorrow = (now.astimezone(ZoneInfo(building.timezone)).date())

    db_session.add(
        ScheduleException(
            schedule_id=schedule.id, local_date=tomorrow, kind=ExceptionKind.skip
        )
    )
    db_session.commit()

    created = materialize_schedule(db_session, schedule, building, now)
    db_session.commit()
    created_dates = {r.local_date for r in created}
    assert tomorrow not in created_dates


def test_override_exception_changes_ready_time(db_session, building):
    schedule = _make_schedule(db_session, building, ready_time=time(8, 0))
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    today = now.astimezone(ZoneInfo(building.timezone)).date()

    db_session.add(
        ScheduleException(
            schedule_id=schedule.id,
            local_date=today,
            kind=ExceptionKind.override,
            override_local_time=time(9, 30),
        )
    )
    db_session.commit()

    created = materialize_schedule(db_session, schedule, building, now)
    db_session.commit()
    todays_request = next(r for r in created if r.local_date == today)
    local_dt = todays_request.ready_by.astimezone(ZoneInfo(building.timezone))
    assert (local_dt.hour, local_dt.minute) == (9, 30)


def test_paused_schedule_does_not_materialize(db_session, building):
    schedule = _make_schedule(db_session, building)
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    schedule.paused_until = date(2026, 1, 31)
    db_session.add(schedule)
    db_session.commit()

    created = materialize_schedule(db_session, schedule, building, now)
    assert created == []


def test_materialize_all_schedules_commits_across_schedules(db_session, building):
    _make_schedule(db_session, building, weekdays=(0, 1, 2, 3, 4))
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    created = materialize_all_schedules(db_session, now=now)
    assert len(created) > 0


def test_spring_forward_gap_does_not_crash(db_session, building):
    # 2026-03-08 is the US spring forward date in America/Los_Angeles; 2:30 AM does not exist
    schedule = _make_schedule(
        db_session, building, weekdays=(0, 1, 2, 3, 4, 5, 6), ready_time=time(2, 30)
    )
    now = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    created = materialize_schedule(db_session, schedule, building, now, window_hours=72)
    db_session.commit()
    assert isinstance(created, list)


def test_fall_back_repeated_hour_does_not_crash(db_session, building):
    # 2026-11-01 is the US fall back date in America/Los_Angeles; 1:30 AM happens twice
    schedule = _make_schedule(
        db_session, building, weekdays=(0, 1, 2, 3, 4, 5, 6), ready_time=time(1, 30)
    )
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    created = materialize_schedule(db_session, schedule, building, now, window_hours=72)
    db_session.commit()
    assert isinstance(created, list)


@given(st.sampled_from([date(2026, 3, 8), date(2026, 11, 1), date(2026, 6, 15)]))
@hyp_settings(deadline=None, max_examples=10)
def test_8am_schedule_survives_both_dst_transitions(local_date):
    tz = ZoneInfo("America/Los_Angeles")
    utc_time = local_to_utc(local_date, time(8, 0), "America/Los_Angeles")
    back_to_local = utc_time.astimezone(tz)
    assert back_to_local.date() == local_date
    assert back_to_local.hour == 8
    assert back_to_local.minute == 0
