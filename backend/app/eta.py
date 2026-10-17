import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models import Request

# Heuristic used until a calibrated artifact exists
DEFAULT_RETRIEVAL_MINUTES = 12


@dataclass
class EtaEstimate:
    median_minutes: float
    p90_minutes: float
    calibrated: bool


class EtaProvider(Protocol):
    def predict_minutes(self, request: Request) -> int: ...

    def predict_interval(self, request: Request) -> EtaEstimate: ...


class HeuristicEtaProvider:
    def predict_minutes(self, request: Request) -> int:
        return DEFAULT_RETRIEVAL_MINUTES

    def predict_interval(self, request: Request) -> EtaEstimate:
        return EtaEstimate(
            median_minutes=DEFAULT_RETRIEVAL_MINUTES,
            p90_minutes=DEFAULT_RETRIEVAL_MINUTES,
            calibrated=False,
        )


class CalibratedEtaProvider:
    """Loads the latest calibrated ETA artifact from ml/registry.py (LightGBM
    quantile models plus a conformal margin, trained in ml/eta/run.py on simulated
    history). Falls back to the heuristic automatically if nothing is trained yet.

    Feature note: queue length, free valets, blockers and lane depth come from the
    live garage/queue state in the simulator's training data, but this live-app
    provider only has cheap, no-DB-query features available at the call sites that
    use it today (hour of day from the request's ready_by). It uses the model's
    learned relationship for those features and the population average for the
    rest, which is a documented simplification, not the full feature parity the
    simulator has; see docs/KNOWN-ISSUES.md.
    """

    def __init__(self):
        from ml.registry import load_latest

        payload, metadata = load_latest("eta")
        self._available = payload is not None
        if self._available:
            self._models = payload["models"]
            self._calibration = payload["calibration"]
            self._metadata = metadata

    def _features(self, request: Request) -> list[list[float]]:
        hour_of_day = request.ready_by.astimezone(UTC).hour + request.ready_by.minute / 60.0
        # Population-average placeholders for features this call site can't see
        # without a database query (see class docstring)
        return [[2.0, 3.0, 0.5, 2.0, hour_of_day, 1.0]]

    def predict_interval(self, request: Request) -> EtaEstimate:
        if not self._available:
            return HeuristicEtaProvider().predict_interval(request)
        X = self._features(request)
        p50 = self._models[0.5].predict(X)[0]
        p90 = self._models[0.9].predict(X)[0]
        margin = self._calibration.margin
        return EtaEstimate(
            median_minutes=float(max(1.0, p50 / 60.0)),
            p90_minutes=float(max(1.0, (p90 + margin) / 60.0)),
            calibrated=True,
        )

    def predict_minutes(self, request: Request) -> int:
        return round(self.predict_interval(request).p90_minutes)


_provider: EtaProvider | None = None


def get_eta_provider() -> EtaProvider:
    global _provider
    if _provider is None:
        calibrated = CalibratedEtaProvider()
        _provider = calibrated if calibrated._available else HeuristicEtaProvider()
    return _provider


def reset_eta_provider() -> None:
    global _provider
    _provider = None


def start_by(request: Request, provider: EtaProvider | None = None) -> datetime:
    provider = provider or get_eta_provider()
    minutes = provider.predict_minutes(request)
    return request.ready_by - timedelta(minutes=minutes)
