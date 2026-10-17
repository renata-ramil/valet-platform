import hashlib
from datetime import UTC, datetime

from app.audit import BrokenChainError, append_event, compute_hash, verify_all
from app.db import Base
from app.models import Building, Car, Request, RequestEvent, RequestSource, RequestState, User
from app.security import hash_password
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _seed_tamper_db():
    """A database with no append-only trigger installed, standing in for an
    attacker (or a database admin) who can bypass it, for example a Postgres
    superuser running ALTER TABLE ... DISABLE TRIGGER, or anyone with direct
    file access to the SQLite file. This is the scenario docs/threat-model.md
    calls out: the trigger stops ordinary app-level tampering, not a
    privileged database attacker, so the hash chain has to catch that case."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    building = Building(name="Harbor Tower", timezone="UTC")
    session.add(building)
    session.commit()
    user = User(
        building_id=building.id,
        email="resident@example.com",
        password_hash=hash_password("password123"),
        role="resident",
        full_name="Test Resident",
    )
    session.add(user)
    session.commit()
    car = Car(
        building_id=building.id,
        owner_id=user.id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate="ABC123",
    )
    session.add(car)
    session.commit()

    request = Request(
        building_id=building.id,
        owner_id=user.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=datetime.now(UTC),
        state=RequestState.queued,
    )
    session.add(request)
    session.flush()
    append_event(session, request, "created", {"source": "on_demand"}, actor_id=user.id)
    append_event(session, request, "assigned", {}, actor_id=user.id)
    append_event(session, request, "delivered", {}, actor_id=user.id)
    session.commit()
    return session, request


def test_tampering_a_stored_event_is_detected_and_pinpointed():
    session, request = _seed_tamper_db()
    assert verify_all(session) == []

    middle_event = (
        session.query(RequestEvent).filter_by(request_id=request.id, sequence=2).one()
    )
    session.execute(
        text("UPDATE request_events SET payload = :payload WHERE id = :id"),
        {"payload": '{"tampered":"true"}', "id": middle_event.id},
    )
    session.commit()
    session.expire_all()

    errors = verify_all(session)
    assert len(errors) == 1
    assert isinstance(errors[0], BrokenChainError)
    assert errors[0].event_id == middle_event.id
    assert errors[0].position == 1
    assert "does not match" in errors[0].reason

    lines = [
        "Audit tamper demonstration",
        "",
        "Seeded a request with 3 events (created, assigned, delivered) then",
        "modified the middle event's payload with a raw UPDATE, bypassing the",
        "append-only trigger the way a privileged database attacker could.",
        "",
        f"make audit output: BROKEN CHAIN: {errors[0]}",
    ]
    from pathlib import Path

    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / "tamper_demo.txt").write_text("\n".join(lines) + "\n")


def test_append_only_trigger_blocks_update_through_the_app_db(db_session, building):
    from tests.conftest import make_car, make_user

    user = make_user(db_session, building.id)
    car = make_car(db_session, building.id, user.id)
    request = Request(
        building_id=building.id,
        owner_id=user.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=datetime.now(UTC),
        state=RequestState.queued,
    )
    db_session.add(request)
    db_session.flush()
    append_event(db_session, request, "created", {}, actor_id=user.id)
    db_session.commit()

    event = request.events[0]
    event.payload = '{"hacked":"true"}'
    db_session.add(event)
    raised = False
    try:
        db_session.commit()
    except Exception:
        db_session.rollback()
        raised = True
    assert raised, "the append-only trigger should reject an UPDATE on request_events"


def test_deleting_an_event_breaks_the_sequence_and_is_detected():
    session, request = _seed_tamper_db()

    middle_event_id = (
        session.query(RequestEvent).filter_by(request_id=request.id, sequence=2).one().id
    )
    session.execute(text("DELETE FROM request_events WHERE id = :id"), {"id": middle_event_id})
    session.commit()
    session.expire_all()

    errors = verify_all(session)
    assert len(errors) == 1
    assert "sequence" in errors[0].reason
    assert "deleted" in errors[0].reason


def test_hash_is_order_and_content_sensitive():
    base = compute_hash("req-1", "created", '{"a":1}', None)
    assert base == compute_hash("req-1", "created", '{"a":1}', None)
    assert base != compute_hash("req-1", "created", '{"a":2}', None)
    assert base != compute_hash("req-1", "assigned", '{"a":1}', None)
    assert base != compute_hash("req-1", "created", '{"a":1}', "some-prev-hash")
    assert len(base) == len(hashlib.sha256(b"x").hexdigest())
