import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim.metrics import bootstrap_ci, compute_metrics, percentile
from sim.simulation import RequestRecord, SimResult


def test_percentile_median_of_odd_list():
    assert percentile([1, 2, 3], 0.5) == 2


def test_percentile_p95_of_sorted_list():
    values = list(range(1, 101))
    assert percentile(values, 0.95) >= 95


def test_bootstrap_ci_contains_the_point_estimate():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    interval = bootstrap_ci(values, seed=1)
    assert interval.low <= interval.point <= interval.high


def test_bootstrap_ci_single_value_is_a_point():
    interval = bootstrap_ci([5.0], seed=1)
    assert interval.point == interval.low == interval.high == 5.0


def test_bootstrap_ci_empty_is_nan():
    interval = bootstrap_ci([], seed=1)
    assert interval.point != interval.point  # NaN != NaN


def _record(source="commuter", relocations=0, wait=0.0, on_time=True, delivered=True):
    return RequestRecord(
        request_id="r",
        car_id="c",
        source=source,
        request_time=0.0,
        ready_by=100.0,
        hour_of_day=8.0,
        queue_length_at_request=0,
        free_valets_at_request=1,
        retrieval_started_at=0.0 if delivered else None,
        delivered_at=100.0 + wait if delivered else None,
        relocations=relocations,
        on_time=on_time,
        wait_seconds=wait,
    )


def test_compute_metrics_averages_across_seeds():
    result_a = SimResult(requests=[_record(wait=10.0)], duration_seconds=3600.0)
    result_a.valet_busy_seconds = {"v1": 0.0}
    result_b = SimResult(requests=[_record(wait=20.0)], duration_seconds=3600.0)
    result_b.valet_busy_seconds = {"v1": 0.0}

    metrics = compute_metrics([result_a, result_b])
    assert metrics.seeds_run == 2
    assert metrics.requests_delivered == 2
    assert metrics.wait_p50_seconds.point > 0


def test_compute_metrics_on_time_rate_excludes_on_demand():
    on_demand_record = _record(source="on_demand", on_time=False, wait=500.0)
    commuter_record = _record(source="commuter", on_time=True, wait=0.0)
    result = SimResult(requests=[on_demand_record, commuter_record], duration_seconds=3600.0)
    result.valet_busy_seconds = {"v1": 0.0}
    metrics = compute_metrics([result])
    assert metrics.on_time_rate_scheduled.point == 1.0
