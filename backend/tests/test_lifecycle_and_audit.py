from datetime import UTC, datetime

import pytest
from app.audit import append_event, verify_request_chain
from app.lifecycle import IllegalTransitionError, resident_label, validate_transition
from app.models import Request, RequestEvent, RequestSource, RequestState

from tests.conftest import make_car, make_user


def test_valid_transitions_pass():
    validate_transition(RequestState.queued, RequestState.assigned)
    validate_transition(RequestState.assigned, RequestState.retrieving)
    validate_transition(RequestState.retrieving, RequestState.en_route)
    validate_transition(RequestState.en_route, RequestState.delivered)


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransitionError):
        validate_transition(RequestState.queued, RequestState.delivered)


def test_delivered_is_terminal_and_the_resident_confirms_nothing():
    with pytest.raises(IllegalTransitionError):
        validate_transition(RequestState.delivered, RequestState.queued)


def test_terminal_states_have_no_outgoing_transitions():
    for terminal in (RequestState.delivered, RequestState.cancelled, RequestState.failed):
        with pytest.raises(IllegalTransitionError):
            validate_transition(terminal, RequestState.queued)


def test_resident_labels_map_internal_states():
    assert resident_label(RequestState.scheduled) == "Scheduled"
    assert resident_label(RequestState.queued) == "Called"
    assert resident_label(RequestState.assigned) == "Called"
    assert resident_label(RequestState.en_route) == "On the way"
    assert resident_label(RequestState.delivered) == "Delivered"


def _make_request(db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = make_car(db_session, building.id, resident.id)
    request = Request(
        building_id=building.id,
        owner_id=resident.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=datetime.now(UTC),
        state=RequestState.queued,
    )
    db_session.add(request)
    db_session.flush()
    return request


def test_event_chain_verifies_when_untampered(db_session, building):
    request = _make_request(db_session, building)
    append_event(db_session, request, "created", {"source": "on_demand"}, actor_id=None)
    append_event(db_session, request, RequestState.assigned.value, {}, actor_id=None)
    append_event(db_session, request, RequestState.retrieving.value, {}, actor_id=None)
    db_session.commit()

    events = list(
        db_session.query(RequestEvent)
        .filter(RequestEvent.request_id == request.id)
        .order_by(RequestEvent.created_at)
    )
    verify_request_chain(events)


def test_tampered_payload_breaks_the_chain(db_session, building):
    from app.audit import BrokenChainError

    request = _make_request(db_session, building)
    append_event(db_session, request, "created", {"source": "on_demand"}, actor_id=None)
    append_event(db_session, request, RequestState.assigned.value, {}, actor_id=None)
    db_session.commit()

    events = list(
        db_session.query(RequestEvent)
        .filter(RequestEvent.request_id == request.id)
        .order_by(RequestEvent.created_at)
    )
    # The DB trigger blocks raw UPDATEs (covered separately below), so this test
    # flips a byte on the loaded object to prove verify_request_chain itself detects it
    tampered_payload = events[0].payload.replace("on_demand", "tampered")
    events[0].payload = tampered_payload
    with pytest.raises(BrokenChainError):
        verify_request_chain(events)


def test_append_only_trigger_blocks_update(db_session, building):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    request = _make_request(db_session, building)
    event = append_event(db_session, request, "created", {"source": "on_demand"}, actor_id=None)
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE request_events SET type = 'hacked' WHERE id = :id").bindparams(id=event.id)
        )
        db_session.commit()
    db_session.rollback()


def test_append_only_trigger_blocks_delete(db_session, building):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    request = _make_request(db_session, building)
    event = append_event(db_session, request, "created", {"source": "on_demand"}, actor_id=None)
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("DELETE FROM request_events WHERE id = :id").bindparams(id=event.id)
        )
        db_session.commit()
    db_session.rollback()
