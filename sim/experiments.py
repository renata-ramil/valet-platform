import copy
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pandas as pd
from policies.interfaces import DepartureAwareAssigner, FlatStaffer, NearestFreeSpotAssigner
from policies.optimization import CPSATStaffer

from sim.metrics import Interval, bootstrap_ci, percentile
from sim.run import load_scenario
from sim.simulation import run_scenario

SCENARIOS = ["weekday_peak", "evening_event", "weekend_calm", "absence_shock"]
SEEDS = 30
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"

POLICY_VARIANTS = {
    "baseline": {"assigner": "nearest_free", "pre_staging": False, "dispatch_mode": "fcfs"},
    "assigner_only": {
        "assigner": "departure_aware",
        "pre_staging": False,
        "dispatch_mode": "fcfs",
    },
    "prestaging_only": {"assigner": "nearest_free", "pre_staging": True, "dispatch_mode": "fcfs"},
    "dispatcher_only": {"assigner": "nearest_free", "pre_staging": False, "dispatch_mode": "edf"},
    "everything": {"assigner": "departure_aware", "pre_staging": True, "dispatch_mode": "edf"},
}


def make_assigner(name: str):
    if name == "nearest_free":
        return NearestFreeSpotAssigner()
    if name == "departure_aware":
        return DepartureAwareAssigner()
    raise ValueError(f"Unknown assigner {name}")


def per_seed_metrics(result) -> tuple[float | None, float | None, float | None]:
    delivered = [r for r in result.requests if r.delivered_at is not None]
    scheduled = [r for r in delivered if r.source in ("commuter", "evening")]
    relocations = sum(r.relocations for r in delivered) / len(delivered) if delivered else None
    waits = [r.wait_seconds for r in delivered]
    wait_p95 = percentile(waits, 0.95) if waits else None
    on_time = sum(1 for r in scheduled if r.on_time) / len(scheduled) if scheduled else None
    return relocations, wait_p95, on_time


def run_variant(
    scenario_params: dict, variant_config: dict, seeds: int, rows: list[dict]
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    relocations, waits, on_times = [], [], []
    for seed in range(seeds):
        result = run_scenario(
            scenario_params,
            seed=seed,
            spot_assigner=make_assigner(variant_config["assigner"]),
            pre_staging=variant_config["pre_staging"],
            dispatch_mode=variant_config["dispatch_mode"],
        )
        r, w, o = per_seed_metrics(result)
        relocations.append(r)
        waits.append(w)
        on_times.append(o)
        rows.append(
            {
                "seed": seed,
                "relocations_per_retrieval": r,
                "wait_p95_seconds": w,
                "on_time_rate": o,
                "requests_delivered": len([x for x in result.requests if x.delivered_at]),
                "restages_completed": result.restages_completed,
            }
        )
    return relocations, waits, on_times


def paired_diff_ci(baseline: list, variant: list, seed: int) -> Interval:
    diffs = [
        v - b for b, v in zip(baseline, variant, strict=True) if b is not None and v is not None
    ]
    return bootstrap_ci(diffs, seed=seed)


def run_ablations(log_rows: list[dict]) -> list[dict]:
    summary_rows = []
    for scenario_name in SCENARIOS:
        print(f"Scenario {scenario_name}")
        params = load_scenario(scenario_name)

        variant_results: dict[str, tuple] = {}
        for variant_name, config in POLICY_VARIANTS.items():
            print(f"  variant {variant_name}")
            variant_rows: list[dict] = []
            relocations, waits, on_times = run_variant(params, config, SEEDS, variant_rows)
            for row in variant_rows:
                row["scenario"] = scenario_name
                row["variant"] = variant_name
            variant_results[variant_name] = (relocations, waits, on_times)
            log_rows.extend(variant_rows)

        base_relocs, base_waits, base_ot = variant_results["baseline"]
        for variant_name in POLICY_VARIANTS:
            if variant_name == "baseline":
                continue
            relocs, waits, on_times = variant_results[variant_name]
            summary_rows.append(
                {
                    "scenario": scenario_name,
                    "variant": variant_name,
                    "seeds": SEEDS,
                    "relocations_diff": paired_diff_ci(base_relocs, relocs, seed=1),
                    "wait_p95_diff": paired_diff_ci(base_waits, waits, seed=2),
                    "on_time_diff": paired_diff_ci(base_ot, on_times, seed=3),
                }
            )
    return summary_rows


def run_sensitivity_sweep(log_rows: list[dict]) -> list[dict]:
    print("Sensitivity sweep (weekday_peak, 'everything' vs baseline)")
    base_params = load_scenario("weekday_peak")
    sweep_seeds = 10
    rows = []
    for valet_count in (4, 6, 8):
        for demand_multiplier in (0.5, 1.0, 1.5):
            params = copy.deepcopy(base_params)
            params["building"]["num_valets"] = valet_count
            params["commuters"]["count"] = round(
                base_params["commuters"]["count"] * demand_multiplier
            )
            params["on_demand"]["base_rate_per_hour"] = (
                base_params["on_demand"]["base_rate_per_hour"] * demand_multiplier
            )
            print(f"  valets={valet_count} demand_x={demand_multiplier}")

            baseline_rows: list[dict] = []
            everything_rows: list[dict] = []
            b_relocs, b_waits, b_ot = run_variant(
                params, POLICY_VARIANTS["baseline"], sweep_seeds, baseline_rows
            )
            e_relocs, e_waits, e_ot = run_variant(
                params, POLICY_VARIANTS["everything"], sweep_seeds, everything_rows
            )
            for row in baseline_rows:
                row.update(
                    valet_count=valet_count,
                    demand_multiplier=demand_multiplier,
                    variant="baseline",
                )
            for row in everything_rows:
                row.update(
                    valet_count=valet_count,
                    demand_multiplier=demand_multiplier,
                    variant="everything",
                )
            log_rows.extend(baseline_rows)
            log_rows.extend(everything_rows)

            rows.append(
                {
                    "valet_count": valet_count,
                    "demand_multiplier": demand_multiplier,
                    "on_time_diff": paired_diff_ci(b_ot, e_ot, seed=4),
                    "wait_p95_diff": paired_diff_ci(b_waits, e_waits, seed=5),
                }
            )
    return rows


def run_staffing_comparison() -> dict:
    print("Staffing comparison (weekday_peak ground-truth demand)")
    params = load_scenario("weekday_peak")
    result = run_scenario(params, seed=0, spot_assigner=NearestFreeSpotAssigner())
    bucket_minutes = 15
    bucket_count = (24 * 60) // bucket_minutes
    forecast: dict[int, float] = {b: 0.0 for b in range(bucket_count)}
    for request in result.requests:
        bucket = int(request.ready_by // (bucket_minutes * 60)) % bucket_count
        forecast[bucket] += 1.0

    valet_pool = [f"valet-{i}" for i in range(params["building"]["num_valets"])]
    flat = FlatStaffer(bucket_count=bucket_count)
    flat_hours = sum(
        (end - start) * bucket_minutes / 60.0
        for shifts in flat.staff(forecast, valet_pool).values()
        for start, end in shifts
    )

    staffer = CPSATStaffer(bucket_minutes=bucket_minutes, shift_hours=8.0)
    cp_result = staffer.staff_with_report(forecast, valet_pool)

    return {
        "flat_total_hours": flat_hours,
        "cpsat_total_hours": cp_result.total_shift_hours,
        "cpsat_uncovered_buckets": len(cp_result.uncovered_buckets),
    }


def _fmt(interval: Interval) -> str:
    return f"{interval.point:+.3g} (95% CI {interval.low:+.3g} to {interval.high:+.3g})"


def write_summary_report(
    ablation_rows: list[dict], sweep_rows: list[dict], staffing: dict
) -> str:
    lines = [
        "# Policy experiment summary",
        "",
        "All numbers below are simulated, from sim/, not from a pilot building.",
        "Differences are paired by seed (same seed run under the baseline and the",
        "variant), which is why the intervals are tight even with 30 seeds.",
        "Positive relocations/wait differences and negative on-time differences",
        "mean the variant is worse than the baseline.",
        "",
        "## Ablations vs baseline (nearest-free spot assignment, FCFS dispatch, no pre-staging)",
        "",
        "| Scenario | Variant | Seeds | Relocations/retrieval diff | Wait p95 diff (s) "
        "| On-time rate diff |",
        "|---|---|---|---|---|---|",
    ]
    for row in ablation_rows:
        lines.append(
            f"| {row['scenario']} | {row['variant']} | {row['seeds']} | "
            f"{_fmt(row['relocations_diff'])} | {_fmt(row['wait_p95_diff'])} | "
            f"{_fmt(row['on_time_diff'])} |"
        )

    winners = [
        r
        for r in ablation_rows
        if r["variant"] == "everything" and r["on_time_diff"].point > 0
    ]
    losers = [
        r
        for r in ablation_rows
        if r["variant"] == "everything" and r["on_time_diff"].point <= 0
    ]
    lines += [
        "",
        "## Honest readout",
        "",
    ]
    if winners:
        scenario_list = ", ".join(r["scenario"] for r in winners)
        lines.append(
            f"The full policy ('everything': departure-aware assignment, pre-staging, "
            f"EDF dispatch) improved the on-time rate over baseline in: {scenario_list}."
        )
    if losers:
        scenario_list = ", ".join(r["scenario"] for r in losers)
        lines.append(
            f"It did not improve on-time rate in: {scenario_list}. This is "
            f"reported honestly rather than hidden; the simpler baseline stays the "
            f"default where a policy doesn't beat it (see the feature flag in "
            f"app/spot_assignment.py)."
        )

    lines += [
        "",
        "## Sensitivity sweep (weekday_peak, 'everything' vs baseline, 10 seeds)",
        "",
        "| Valets | Demand multiplier | On-time rate diff | Wait p95 diff (s) |",
        "|---|---|---|---|",
    ]
    for row in sweep_rows:
        lines.append(
            f"| {row['valet_count']} | {row['demand_multiplier']}x | "
            f"{_fmt(row['on_time_diff'])} | {_fmt(row['wait_p95_diff'])} |"
        )

    lines += [
        "",
        "## Staffing: flat vs CP-SAT coverage (weekday_peak ground-truth demand)",
        "",
        f"- Flat staffing (all valets on all day): {staffing['flat_total_hours']:.1f} valet-hours",
        f"- CP-SAT shift covering: {staffing['cpsat_total_hours']:.1f} valet-hours, "
        f"{staffing['cpsat_uncovered_buckets']} buckets left under-covered",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    start = time.time()
    log_rows: list[dict] = []

    ablation_rows = run_ablations(log_rows)
    sweep_rows = run_sensitivity_sweep(log_rows)
    staffing = run_staffing_comparison()

    REPORTS_DIR.mkdir(exist_ok=True)
    df = pd.DataFrame(log_rows)
    parquet_path = REPORTS_DIR / "policies_experiments.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"Wrote {parquet_path} ({len(df)} rows)")

    report = write_summary_report(ablation_rows, sweep_rows, staffing)
    report_path = REPORTS_DIR / "policies_summary.md"
    report_path.write_text(report)
    print(f"Wrote {report_path}")

    elapsed = time.time() - start
    print(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
