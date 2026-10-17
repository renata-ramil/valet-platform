import random
import statistics
from dataclasses import dataclass

from sim.simulation import RequestRecord, SimResult


@dataclass
class Interval:
    point: float
    low: float
    high: float

    def __str__(self) -> str:
        return f"{self.point:.3g} (95% CI {self.low:.3g} to {self.high:.3g})"


def bootstrap_ci(
    values: list[float], statistic=statistics.mean, n_resamples: int = 2000, seed: int = 0
) -> Interval:
    if not values:
        return Interval(float("nan"), float("nan"), float("nan"))
    rng = random.Random(seed)
    point = statistic(values)
    if len(values) == 1:
        return Interval(point, point, point)
    resampled = []
    n = len(values)
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        resampled.append(statistic(sample))
    resampled.sort()
    low = resampled[int(0.025 * n_resamples)]
    high = resampled[int(0.975 * n_resamples) - 1]
    return Interval(point, low, high)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return ordered[index]


@dataclass
class ScenarioMetrics:
    seeds_run: int
    requests_delivered: int
    relocations_per_retrieval: Interval
    wait_p50_seconds: Interval
    wait_p95_seconds: Interval
    on_time_rate_scheduled: Interval
    valet_utilization: Interval


def _valet_utilization(result: SimResult, requests: list[RequestRecord]) -> float:
    busy = sum(
        (r.delivered_at - r.retrieval_started_at)
        for r in requests
        if r.delivered_at is not None and r.retrieval_started_at is not None
    )
    num_valets = len(result.valet_busy_seconds) or 1
    capacity_seconds = num_valets * result.duration_seconds
    return busy / capacity_seconds if capacity_seconds else 0.0


def compute_metrics(results: list[SimResult]) -> ScenarioMetrics:
    relocations_per_seed = []
    wait_p50_per_seed = []
    wait_p95_per_seed = []
    on_time_per_seed = []
    utilization_per_seed = []
    total_delivered = 0

    for result in results:
        delivered = [r for r in result.requests if r.delivered_at is not None]
        total_delivered += len(delivered)
        if delivered:
            relocations_per_seed.append(
                sum(r.relocations for r in delivered) / len(delivered)
            )
            waits = [r.wait_seconds for r in delivered]
            wait_p50_per_seed.append(percentile(waits, 0.50))
            wait_p95_per_seed.append(percentile(waits, 0.95))

        scheduled = [r for r in delivered if r.source in ("commuter", "evening")]
        if scheduled:
            on_time_per_seed.append(
                sum(1 for r in scheduled if r.on_time) / len(scheduled)
            )

        utilization_per_seed.append(_valet_utilization(result, delivered))

    return ScenarioMetrics(
        seeds_run=len(results),
        requests_delivered=total_delivered,
        relocations_per_retrieval=bootstrap_ci(relocations_per_seed, seed=1),
        wait_p50_seconds=bootstrap_ci(wait_p50_per_seed, seed=2),
        wait_p95_seconds=bootstrap_ci(wait_p95_per_seed, seed=3),
        on_time_rate_scheduled=bootstrap_ci(on_time_per_seed, seed=4),
        valet_utilization=bootstrap_ci(utilization_per_seed, seed=5),
    )
