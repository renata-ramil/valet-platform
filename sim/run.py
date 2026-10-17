import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml

from sim.metrics import ScenarioMetrics, compute_metrics
from sim.simulation import SimResult, run_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"

DEFAULT_SEEDS = 30


def load_scenario(name: str) -> dict:
    path = SCENARIOS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No scenario file at {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def run_seeds(params: dict, seeds: int) -> list[SimResult]:
    results = []
    for seed in range(seeds):
        results.append(run_scenario(params, seed=seed))
        if (seed + 1) % 5 == 0 or seed == seeds - 1:
            print(f"  seed {seed + 1}/{seeds} done")
    return results


def write_figure(scenario_name: str, results: list[SimResult], out_path: Path) -> None:
    all_waits_minutes = [
        r.wait_seconds / 60.0
        for result in results
        for r in result.requests
        if r.delivered_at is not None
    ]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(all_waits_minutes, bins=40, color="#1e293b")
    ax.axvline(0, color="#dc2626", linestyle="--", linewidth=1, label="ready_by")
    ax.set_xlabel("Minutes late (negative = early)")
    ax.set_ylabel("Requests")
    ax.set_title(f"{scenario_name}: delivery wait distribution across all seeds")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def write_report(
    scenario_name: str, metrics: ScenarioMetrics, seeds: int, figure_path: Path
) -> str:
    lines = [
        f"# Baseline results: {scenario_name}",
        "",
        "All numbers below are simulated, from the digital twin in sim/, not from a",
        "pilot building. They use the baseline policies: nearest-free spot assignment",
        f"and a deadline-priority dispatcher, across {seeds} random seeds.",
        "",
        "## Metrics",
        "",
        "| Metric | Value | 95% CI |",
        "|---|---|---|",
        f"| Requests delivered (all seeds) | {metrics.requests_delivered} | |",
        (
            f"| Relocations per retrieval | {metrics.relocations_per_retrieval.point:.3g} | "
            f"{metrics.relocations_per_retrieval.low:.3g} to "
            f"{metrics.relocations_per_retrieval.high:.3g} |"
        ),
        (
            f"| Wait p50 (seconds, negative = early) | {metrics.wait_p50_seconds.point:.3g} | "
            f"{metrics.wait_p50_seconds.low:.3g} to {metrics.wait_p50_seconds.high:.3g} |"
        ),
        (
            f"| Wait p95 (seconds) | {metrics.wait_p95_seconds.point:.3g} | "
            f"{metrics.wait_p95_seconds.low:.3g} to {metrics.wait_p95_seconds.high:.3g} |"
        ),
        (
            f"| On-time rate, scheduled requests | {metrics.on_time_rate_scheduled.point:.1%} | "
            f"{metrics.on_time_rate_scheduled.low:.1%} to "
            f"{metrics.on_time_rate_scheduled.high:.1%} |"
        ),
        (
            f"| Valet utilization | {metrics.valet_utilization.point:.1%} | "
            f"{metrics.valet_utilization.low:.1%} to {metrics.valet_utilization.high:.1%} |"
        ),
        "",
        f"![wait distribution]({figure_path.name})",
        "",
        "On-time rate is computed over scheduled requests only (commuter and evening",
        "sources); on-demand requests have no advance ready-by to be early or late",
        "against by construction.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    args = parser.parse_args()

    params = load_scenario(args.scenario)
    print(f"Running scenario {args.scenario} across {args.seeds} seeds")
    start = time.time()
    results = run_seeds(params, args.seeds)
    elapsed = time.time() - start
    print(f"Done in {elapsed:.1f}s")

    metrics = compute_metrics(results)

    REPORTS_DIR.mkdir(exist_ok=True)
    figure_path = REPORTS_DIR / f"baseline_{args.scenario}.png"
    write_figure(args.scenario, results, figure_path)

    report = write_report(args.scenario, metrics, args.seeds, figure_path)
    report_path = REPORTS_DIR / f"baseline_{args.scenario}.md"
    report_path.write_text(report)
    print(f"Wrote {report_path}")
    print(f"Wrote {figure_path}")


if __name__ == "__main__":
    main()
