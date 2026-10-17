import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from ml.habits.model import detect_recurring_slots
from ml.registry import save_artifact

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MAX_WEEKS = 12


def _simulate_resident(
    rng: random.Random, has_routine: bool, weeks: int
) -> tuple[pd.DataFrame, set[tuple[tuple[int, ...], float]]]:
    """Returns (history, ground_truth). ground_truth is a set of (weekdays, time)
    routines this synthetic resident actually follows (empty if none)."""
    rows = []
    ground_truth = set()
    if has_routine:
        routine_weekdays = tuple(sorted(rng.sample(range(5), k=rng.choice([1, 5]))))
        routine_time = rng.uniform(7 * 60, 9 * 60)
        ground_truth.add((routine_weekdays, routine_time))
        for week in range(weeks):
            for weekday in routine_weekdays:
                if rng.random() < 0.85:  # occasional skip
                    jitter = rng.gauss(0, 8)
                    rows.append(
                        {
                            "weekday": weekday,
                            "time_minutes": routine_time + jitter,
                            "week_index": week,
                        }
                    )
    # Background noise: a few unrelated one-off requests for every resident
    for week in range(weeks):
        for _ in range(rng.randint(0, 2)):
            rows.append(
                {
                    "weekday": rng.randint(0, 6),
                    "time_minutes": rng.uniform(0, 24 * 60),
                    "week_index": week,
                }
            )
    return pd.DataFrame(rows), ground_truth


def _matches_ground_truth(
    suggestion, ground_truth: set[tuple[tuple[int, ...], float]]
) -> bool:
    for weekdays, time_minutes in ground_truth:
        if set(suggestion.weekdays) == set(weekdays) and abs(
            suggestion.time_minutes - time_minutes
        ) <= 20:
            return True
    return False


def _generate_residents(n_residents: int, seed: int) -> list[tuple[pd.DataFrame, set, bool]]:
    rng = random.Random(seed)
    residents = []
    for i in range(n_residents):
        has_routine = i % 2 == 0  # half with a routine, half without (control)
        history, ground_truth = _simulate_resident(rng, has_routine, MAX_WEEKS)
        residents.append((history, ground_truth, has_routine))
    return residents


def evaluate_at_weeks(residents: list[tuple[pd.DataFrame, set, bool]], weeks: int) -> dict:
    true_positives = 0
    false_positives = 0
    false_negatives = 0

    for full_history, ground_truth, _has_routine in residents:
        history = full_history[full_history["week_index"] < weeks]
        suggestions = detect_recurring_slots(history, weeks_of_history=weeks)

        matched_truth = set()
        for suggestion in suggestions:
            if _matches_ground_truth(suggestion, ground_truth):
                true_positives += 1
                for weekdays, time_minutes in ground_truth:
                    if set(suggestion.weekdays) == set(weekdays) and abs(
                        suggestion.time_minutes - time_minutes
                    ) <= 20:
                        matched_truth.add((weekdays, time_minutes))
            else:
                false_positives += 1
        false_negatives += len(ground_truth - matched_truth)

    precision = true_positives / (true_positives + false_positives) if (
        true_positives + false_positives
    ) else float("nan")
    recall = true_positives / (true_positives + false_negatives) if (
        true_positives + false_negatives
    ) else float("nan")
    return {"weeks": weeks, "precision": precision, "recall": recall}


def write_figure(results: list[dict], out_path: Path) -> None:
    weeks = [r["weeks"] for r in results]
    precision = [r["precision"] for r in results]
    recall = [r["recall"] for r in results]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(weeks, precision, marker="o", label="precision", color="#1e293b")
    ax.plot(weeks, recall, marker="o", label="recall", color="#64748b")
    ax.axhline(0.9, color="#dc2626", linestyle="--", linewidth=1, label="90% target")
    ax.set_xlabel("Weeks of history")
    ax.set_ylabel("Score")
    ax.set_title("Habit detection precision/recall vs weeks of history")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def write_report(results: list[dict], figure_path: Path) -> str:
    lines = [
        "# Habit suggestions",
        "",
        "Evaluated on simulated residents with known routines (half with a fixed",
        "weekday/time routine, half pure noise as a control), not real residents.",
        "",
        "| Weeks of history | Precision | Recall |",
        "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['weeks']} | {r['precision']:.1%} | {r['recall']:.1%} |")

    # Precision alone can hit 100% on a tiny, unreliable sample (few or no
    # suggestions fire yet); require recall above half too before calling a
    # weeks-of-history point a genuinely reached target, not a small-sample fluke
    weeks_to_90 = next(
        (r["weeks"] for r in results if r["precision"] >= 0.9 and r["recall"] >= 0.5), None
    )
    lines += [
        "",
        (
            f"Reaches 90% precision (with recall already above 50%, so it isn't a "
            f"small-sample fluke) at {weeks_to_90} weeks of history."
            if weeks_to_90
            else "Does not reach a stable 90% precision within the weeks tested."
        ),
        "",
        f"![precision and recall vs weeks]({figure_path.name})",
        "",
        "## Integration",
        "",
        "`GET /suggestions` runs the same beta-binomial detector against a",
        "resident's own request history and returns proposed schedules; the",
        "resident app shows a card offering to create each one.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    start = time.time()
    residents = _generate_residents(n_residents=60, seed=42)
    results = []
    for weeks in (2, 4, 6, 8, 12):
        print(f"Evaluating at {weeks} weeks of history")
        results.append(evaluate_at_weeks(residents, weeks))

    REPORTS_DIR.mkdir(exist_ok=True)
    figure_path = REPORTS_DIR / "habits.png"
    write_figure(results, figure_path)

    report = write_report(results, figure_path)
    report_path = REPORTS_DIR / "habits.md"
    report_path.write_text(report)
    print(f"Wrote {report_path}")
    print(f"Wrote {figure_path}")

    version = save_artifact(
        "habits",
        payload={"detector": "beta_binomial_cluster"},
        metrics={
            "precision_at_12_weeks": results[-1]["precision"],
            "recall_at_12_weeks": results[-1]["recall"],
        },
        calibrated=True,
        training_data_path=DATA_DIR / "history_demand.parquet",
    )
    print(f"Saved habits artifact version {version}")
    print(f"Done in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
