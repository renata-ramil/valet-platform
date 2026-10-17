import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audit import append_event, verify_request_chain
from app.db import Base, SessionLocal, engine
from app.lifecycle import resident_label, validate_transition
from app.models import (
    Building,
    Car,
    Request,
    RequestEvent,
    RequestSource,
    RequestState,
    Role,
    Schedule,
    User,
)
from app.schedule_engine import materialize_schedule
from app.security import hash_password


def main() -> None:
    print("Creating tables for the demo run")
    Base.metadata.create_all(engine)
    db = SessionLocal()

    try:
        building = Building(name="Harbor Tower", timezone="America/Los_Angeles")
        db.add(building)
        db.commit()
        db.refresh(building)
        print(f"Building: {building.name} ({building.timezone})")

        resident = User(
            building_id=building.id,
            email="demo-lifecycle@harbortower.example.com",
            password_hash=hash_password("demopass123"),
            role=Role.resident,
            full_name="Demo Resident",
        )
        db.add(resident)
        db.commit()
        db.refresh(resident)

        car = Car(
            building_id=building.id,
            owner_id=resident.id,
            make="Honda",
            model="Civic",
            color="blue",
            license_plate="DEMO01",
        )
        db.add(car)
        db.commit()
        db.refresh(car)

        schedule = Schedule(
            building_id=building.id,
            car_id=car.id,
            owner_id=resident.id,
            ready_by_local_time=time(8, 0),
            active_from=date(2020, 1, 1),
        )
        schedule.weekdays = [0, 1, 2, 3, 4]  # weekdays, the 8 AM leave-every-day story
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        print("\nMaterializing one week of the weekday 8:00 AM schedule")
        now = datetime.now(UTC)
        tz = ZoneInfo(building.timezone)
        for offset in range(7):
            simulated_now = (now + timedelta(days=offset)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            created = materialize_schedule(db, schedule, building, simulated_now, window_hours=24)
            db.commit()
            for request in created:
                local_dt = request.ready_by.astimezone(tz)
                print(
                    f"  local_date={request.local_date} "
                    f"local_time={local_dt.strftime('%Y-%m-%d %H:%M %Z')} "
                    f"utc={request.ready_by.strftime('%Y-%m-%d %H:%M UTC')}"
                )

        print("\nWalking one on-demand request through every state")
        demo_request = Request(
            building_id=building.id,
            owner_id=resident.id,
            car_id=car.id,
            source=RequestSource.on_demand,
            ready_by=now,
            state=RequestState.queued,
        )
        db.add(demo_request)
        db.flush()
        append_event(db, demo_request, "created", {"source": "on_demand"}, actor_id=resident.id)
        db.commit()
        print(f"  {demo_request.state} -> {resident_label(RequestState(demo_request.state))}")

        for target in [
            RequestState.assigned,
            RequestState.retrieving,
            RequestState.en_route,
            RequestState.delivered,
        ]:
            validate_transition(RequestState(demo_request.state), target)
            demo_request.state = target
            append_event(db, demo_request, target.value, {}, actor_id=resident.id)
            db.add(demo_request)
            db.commit()
            print(f"  {demo_request.state} -> {resident_label(RequestState(demo_request.state))}")

        print("\nVerifying the hash chain for this request")
        events = list(
            db.query(RequestEvent)
            .filter_by(request_id=demo_request.id)
            .order_by(RequestEvent.created_at)
        )
        verify_request_chain(events)
        print(f"  chain OK across {len(events)} events")
        for event in events:
            print(f"    {event.type}: hash={event.hash[:16]}... prev={str(event.prev_hash)[:16]}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
