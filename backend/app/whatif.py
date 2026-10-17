"""The manager what-if panel: run a short simulation (10 seeds, a few
seconds) for a given valet count and demand multiplier and report p95
wait, on-time rate, and relocations per retrieval with confidence
intervals, plotted against the current staffing. A precomputed grid is the
fallback when a live run would be too slow to answer synchronously (used
here as the fallback if the simulation import or run itself fails, so the
manager always gets an answer)."""

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WHATIF_SEEDS = 10
SCENARIO_NAME = "weekday_peak"

# A coarse precomputed grid (matching sim/experiments.py's sensitivity sweep
# shape), used only if the live simulation can't run in this process (for
# example sim/ isn't importable). Every number here is copied from
# reports/policies_summary.md's sensitivity sweep table, so even the
# fallback is a real saved result, not invented.
PRECOMPUTED_GRID = {
    (4, 0.5): {"on_time_rate": 0.72, "wait_p95_seconds": 210, "relocations_per_retrieval": 0.30},
    (4, 1.0): {"on_time_rate": 0.55, "wait_p95_seconds": 310, "relocations_per_retrieval": 0.42},
    (4, 1.5): {"on_time_rate": 0.41, "wait_p95_seconds": 430, "relocations_per_retrieval": 0.55},
    (6, 0.5): {"on_time_rate": 0.80, "wait_p95_seconds": 170, "relocations_per_retrieval": 0.28},
    (6, 1.0): {"on_time_rate": 0.66, "wait_p95_seconds": 260, "relocations_per_retrieval": 0.38},
    (6, 1.5): {"on_time_rate": 0.50, "wait_p95_seconds": 360, "relocations_per_retrieval": 0.48},
    (8, 0.5): {"on_time_rate": 0.86, "wait_p95_seconds": 140, "relocations_per_retrieval": 0.25},
    (8, 1.0): {"on_time_rate": 0.74, "wait_p95_seconds": 220, "relocations_per_retrieval": 0.34},
    (8, 1.5): {"on_time_rate": 0.59, "wait_p95_seconds": 320, "relocations_per_retrieval": 0.44},
}


def _nearest_grid_point(valet_count: int, demand_multiplier: float) -> tuple[int, float]:
    valet_options = (4, 6, 8)
    demand_options = (0.5, 1.0, 1.5)
    nearest_valet = min(valet_options, key=lambda v: abs(v - valet_count))
    nearest_demand = min(demand_options, key=lambda d: abs(d - demand_multiplier))
    return nearest_valet, nearest_demand


def run_whatif(valet_count: int, demand_multiplier: float) -> dict:
    try:
        return _run_live(valet_count, demand_multiplier)
    except Exception as exc:  # noqa: BLE001
        point = _nearest_grid_point(valet_count, demand_multiplier)
        fallback = dict(PRECOMPUTED_GRID[point])
        fallback["source"] = "precomputed_grid"
        fallback["note"] = f"Live simulation unavailable ({exc}); nearest precomputed point used"
        return fallback


def _run_live(valet_count: int, demand_multiplier: float) -> dict:
    from sim.experiments import POLICY_VARIANTS, load_scenario, run_variant
    from sim.metrics import bootstrap_ci

    base_params = load_scenario(SCENARIO_NAME)
    params = copy.deepcopy(base_params)
    params["building"]["num_valets"] = valet_count
    params["commuters"]["count"] = round(base_params["commuters"]["count"] * demand_multiplier)
    params["on_demand"]["base_rate_per_hour"] = (
        base_params["on_demand"]["base_rate_per_hour"] * demand_multiplier
    )

    relocations, waits, on_times = run_variant(
        params, POLICY_VARIANTS["everything"], WHATIF_SEEDS, rows=[]
    )
    relocations = [v for v in relocations if v is not None]
    waits = [v for v in waits if v is not None]
    on_times = [v for v in on_times if v is not None]

    on_time_ci = bootstrap_ci(on_times, seed=1)
    wait_ci = bootstrap_ci(waits, seed=2)
    reloc_ci = bootstrap_ci(relocations, seed=3)

    return {
        "source": "live_simulation",
        "seeds": WHATIF_SEEDS,
        "on_time_rate": on_time_ci.point,
        "on_time_rate_ci": [on_time_ci.low, on_time_ci.high],
        "wait_p95_seconds": wait_ci.point,
        "wait_p95_seconds_ci": [wait_ci.low, wait_ci.high],
        "relocations_per_retrieval": reloc_ci.point,
        "relocations_per_retrieval_ci": [reloc_ci.low, reloc_ci.high],
    }
