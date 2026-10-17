import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim.simulation import run_scenario

SMALL_PARAMS = {
    "building": {
        "num_lanes": 6,
        "max_depth": 4,
        "num_valets": 3,
        "background_occupancy_fraction": 0.1,
    },
    "duration_hours": 24,
    "commuters": {
        "count": 8,
        "ready_by_hour": 8.0,
        "ready_by_jitter_minutes_std": 10,
        "skip_probability": 0.05,
    },
    "on_demand": {
        "base_rate_per_hour": 0.3,
        "peak_multiplier": 2.0,
        "peak_hours": [7, 10],
    },
    "evening_event": {"enabled": False},
    "valet_absence": {"probability": 0.0},
}


def test_same_seed_is_reproducible():
    result_a = run_scenario(SMALL_PARAMS, seed=42)
    result_b = run_scenario(SMALL_PARAMS, seed=42)
    waits_a = [r.wait_seconds for r in result_a.requests]
    waits_b = [r.wait_seconds for r in result_b.requests]
    assert waits_a == waits_b
    assert len(waits_a) > 0


def test_different_seeds_produce_different_results():
    result_a = run_scenario(SMALL_PARAMS, seed=1)
    result_b = run_scenario(SMALL_PARAMS, seed=2)
    waits_a = [r.wait_seconds for r in result_a.requests]
    waits_b = [r.wait_seconds for r in result_b.requests]
    assert waits_a != waits_b


def test_every_request_eventually_delivered_within_the_day():
    result = run_scenario(SMALL_PARAMS, seed=5)
    assert len(result.requests) > 0
    for record in result.requests:
        assert record.delivered_at is not None
        assert record.relocations >= 0


def test_valet_absence_reduces_active_valets():
    params = dict(SMALL_PARAMS)
    params["valet_absence"] = {"probability": 1.0}
    result = run_scenario(params, seed=9)
    assert result.absent_valets == {"valet-0", "valet-1", "valet-2"}


def test_runs_across_many_seeds_without_crashing():
    for seed in range(30):
        result = run_scenario(SMALL_PARAMS, seed=seed)
        assert all(r.delivered_at is not None for r in result.requests)


def test_pre_staging_runs_without_crashing_across_many_seeds():
    for seed in range(30):
        result = run_scenario(SMALL_PARAMS, seed=seed, pre_staging=True)
        assert all(r.delivered_at is not None for r in result.requests)


def test_fcfs_dispatch_mode_runs_without_crashing():
    for seed in range(10):
        result = run_scenario(SMALL_PARAMS, seed=seed, dispatch_mode="fcfs")
        assert all(r.delivered_at is not None for r in result.requests)


def test_pre_staging_never_loses_or_duplicates_cars():
    result = run_scenario(SMALL_PARAMS, seed=11, pre_staging=True)
    car_ids = [r.car_id for r in result.requests]
    assert len(car_ids) == len(set(car_ids))
    assert result.restages_completed >= 0
