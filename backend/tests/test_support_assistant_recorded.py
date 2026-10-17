"""Recorded-response mode for the live model path: fakes the Anthropic
client's return values so the tool-calling loop in
app.support_assistant._run_live_model is exercised without a network call
or an API key. This is what `make test` actually runs; a live key is not
required for this suite to pass."""

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import patch

from app.models import Request, RequestSource, RequestState, Role, Schedule
from app.support_assistant import run_support_turn
from app.support_tools import SupportContext

from tests.conftest import make_car, make_user


def _resident_with_schedule(db_session, building):
    resident = make_user(db_session, building.id, Role.resident, "resident@example.com")
    car = make_car(db_session, building.id, resident.id, "REC001")
    request = Request(
        building_id=building.id,
        owner_id=resident.id,
        car_id=car.id,
        source=RequestSource.on_demand,
        ready_by=datetime.now(UTC),
        state=RequestState.queued,
    )
    db_session.add(request)
    schedule = Schedule(
        building_id=building.id,
        car_id=car.id,
        owner_id=resident.id,
        ready_by_local_time=time(8, 0),
        active_from=date.today(),
    )
    schedule.weekdays = [0, 1, 2, 3, 4]
    db_session.add(schedule)
    db_session.commit()
    return resident, schedule


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(name, input_, block_id="tool_1"):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=input_)


def _message(content, stop_reason, input_tokens=50, output_tokens=20):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_recorded_tool_use_then_text_calls_get_request_status(db_session, building, monkeypatch):
    resident, _ = _resident_with_schedule(db_session, building)
    ctx = SupportContext(db=db_session, user=resident)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-recorded")
    monkeypatch.setenv("SUPPORT_MODEL", "recorded-test-model")

    responses = [
        _message(
            [_tool_use_block("get_request_status", {})],
            stop_reason="tool_use",
        ),
        _message(
            [_text_block("Your car is called, ready shortly.")],
            stop_reason="end_turn",
        ),
    ]

    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: responses.pop(0))
    )
    with patch("anthropic.Anthropic", return_value=fake_client):
        result = run_support_turn(ctx, [], "where is my car")

    assert result.used_live_model is True
    assert result.tool_calls[0].name == "get_request_status"
    assert "ready" in result.reply.lower()
    assert result.input_tokens == 100
    assert result.output_tokens == 40


def test_recorded_mode_never_exposes_confirm_reschedule_as_a_tool(
    db_session, building, monkeypatch
):
    """The recorded response simulates a model that tries to call a tool
    named confirm_reschedule anyway (as if persuaded by injected text).
    Since confirm_reschedule is not in TOOL_DISPATCH's model-facing set,
    the dispatcher must reject it rather than silently applying a change."""
    resident, schedule = _resident_with_schedule(db_session, building)
    ctx = SupportContext(db=db_session, user=resident)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-recorded")
    monkeypatch.setenv("SUPPORT_MODEL", "recorded-test-model")

    responses = [
        _message(
            [_tool_use_block("confirm_reschedule", {"proposal_id": "x", "token": "y"})],
            stop_reason="tool_use",
        ),
        _message([_text_block("Done.")], stop_reason="end_turn"),
    ]
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: responses.pop(0))
    )
    with patch("anthropic.Anthropic", return_value=fake_client):
        result = run_support_turn(ctx, [], "confirm it")

    assert result.tool_calls[0].error is not None
    assert "unknown tool" in result.tool_calls[0].error.lower()
    db_session.refresh(schedule)
    assert schedule.ready_by_local_time == time(8, 0)


def test_falls_back_to_rule_based_when_live_call_raises(db_session, building, monkeypatch):
    resident, _ = _resident_with_schedule(db_session, building)
    ctx = SupportContext(db=db_session, user=resident)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-recorded")
    monkeypatch.setenv("SUPPORT_MODEL", "recorded-test-model")

    def _boom(**kwargs):
        raise RuntimeError("simulated network failure")

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=_boom))
    with patch("anthropic.Anthropic", return_value=fake_client):
        result = run_support_turn(ctx, [], "where is my car")

    assert result.used_live_model is False
    assert result.tool_calls[0].name == "get_request_status"
