from datetime import UTC, datetime, timedelta

from app.eta import (
    DEFAULT_RETRIEVAL_MINUTES,
    CalibratedEtaProvider,
    HeuristicEtaProvider,
    get_eta_provider,
    start_by,
)
from app.models import Request, RequestSource, RequestState


def _request():
    return Request(
        building_id="b",
        owner_id="o",
        car_id="c",
        source=RequestSource.on_demand,
        ready_by=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        state=RequestState.queued,
    )


def test_heuristic_provider_returns_constant():
    provider = HeuristicEtaProvider()
    estimate = provider.predict_interval(_request())
    assert estimate.median_minutes == DEFAULT_RETRIEVAL_MINUTES
    assert estimate.p90_minutes == DEFAULT_RETRIEVAL_MINUTES
    assert estimate.calibrated is False


def test_start_by_uses_p90_minutes_as_the_lead_time():
    request = _request()
    result = start_by(request, provider=HeuristicEtaProvider())
    assert result == request.ready_by - timedelta(minutes=DEFAULT_RETRIEVAL_MINUTES)


def test_get_eta_provider_falls_back_to_heuristic_when_nothing_trained(monkeypatch, tmp_path):
    import ml.registry as registry

    monkeypatch.setattr(registry, "ARTIFACTS_DIR", tmp_path / "artifacts")
    provider = get_eta_provider()
    assert isinstance(provider, HeuristicEtaProvider)


def test_calibrated_provider_reports_unavailable_without_a_trained_artifact(
    monkeypatch, tmp_path
):
    import ml.registry as registry

    monkeypatch.setattr(registry, "ARTIFACTS_DIR", tmp_path / "artifacts")
    provider = CalibratedEtaProvider()
    assert provider._available is False
    estimate = provider.predict_interval(_request())
    assert estimate.calibrated is False
