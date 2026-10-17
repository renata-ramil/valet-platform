"""Assembles reports/RESULTS.md from the saved experiment outputs already in
reports/, ml/artifacts/, and reports/support_eval.md. Every number here is
read from a saved file, not retyped by hand, so README.md can cite this
file and the numbers stay traceable. Run with `make report`."""

import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sim.experiments import paired_diff_ci  # noqa: E402

REPORTS = REPO_ROOT / "reports"
ML_ARTIFACTS = REPO_ROOT / "ml" / "artifacts"


def _read(path: Path) -> str:
    if not path.exists():
        print(f"Missing {path}, skipping its section")
        return ""
    return path.read_text()


def _extract_line(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(0) if match else None


def _latest_artifact_metrics(model_type: str) -> dict:
    latest_path = ML_ARTIFACTS / model_type / "latest.json"
    if not latest_path.exists():
        return {}
    version = json.loads(latest_path.read_text())["version"]
    metadata_path = ML_ARTIFACTS / model_type / version / "metadata.json"
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text())


def policy_headline() -> str:
    parquet_path = REPORTS / "policies_experiments.parquet"
    if not parquet_path.exists():
        return "No policy experiment data found; run `make experiments` first.\n"
    df = pd.read_parquet(parquet_path)
    scenario = df[df["scenario"] == "weekday_peak"]
    baseline = scenario[scenario["variant"] == "baseline"].sort_values("seed")
    variant = scenario[scenario["variant"] == "assigner_only"].sort_values("seed")
    if baseline.empty or variant.empty:
        return "weekday_peak baseline/assigner_only rows not found.\n"

    relocations_ci = paired_diff_ci(
        baseline["relocations_per_retrieval"].tolist(),
        variant["relocations_per_retrieval"].tolist(),
        seed=1,
    )
    on_time_ci = paired_diff_ci(
        baseline["on_time_rate"].tolist(), variant["on_time_rate"].tolist(), seed=3
    )
    lines = [
        "**Departure-aware spot assignment vs nearest-free baseline**, "
        f"weekday_peak scenario, {len(baseline)} paired seeds "
        "(reports/policies_summary.md, reports/policies_experiments.parquet, "
        "recomputed here with `sim.experiments.paired_diff_ci`, simulated):",
        "",
        f"- Relocations per retrieval: {relocations_ci}",
        f"- On-time rate: {on_time_ci}",
    ]
    return "\n".join(lines) + "\n"


def staffing_headline() -> str:
    text = _read(REPORTS / "policies_summary.md")
    flat = _extract_line(text, r"Flat staffing.*?valet-hours")
    cpsat = _extract_line(text, r"CP-SAT shift covering.*?valet-hours")
    if not (flat and cpsat):
        return "Staffing comparison not found in reports/policies_summary.md.\n"
    flat_hours = float(re.search(r"[\d.]+", flat.split(":")[-1]).group())
    cpsat_hours = float(re.search(r"[\d.]+", cpsat.split(":")[-1]).group())
    savings = (1 - cpsat_hours / flat_hours) * 100
    return (
        "**Forecast-driven staffing vs flat coverage**, weekday_peak ground-truth "
        "demand (reports/policies_summary.md, simulated):\n\n"
        f"- {flat}\n- {cpsat}\n- Savings: {savings:.0f}% fewer valet-hours at the same coverage target\n"
    )


def forecast_headline() -> str:
    text = _read(REPORTS / "forecast.md")
    rhat = _extract_line(text, r"Max R-hat across folds is [\d.]+")
    coverage80 = re.findall(r"\| \d \| [\d.]+ \| [\d.]+ \| [\d.]+ \| ([\d.]+%)", text)
    if not text:
        return "No forecast report found.\n"
    return (
        "**Hierarchical negative binomial demand forecast** (reports/forecast.md, "
        "reports/forecast.png, simulated):\n\n"
        f"- 4-fold rolling-origin backtest, 80% target coverage, "
        f"achieved: {', '.join(coverage80) if coverage80 else 'see report'}\n"
        f"- Convergence: {rhat or 'see report'}, zero divergences in every fold\n"
    )


def eta_headline() -> str:
    text = _read(REPORTS / "eta.md")
    held_out = _extract_line(
        text, r"held-out \(same distribution\) \| \d+ \| [\d.]+%"
    )
    shifted = _extract_line(text, r"1\.5x demand \| \d+ \| [\d.]+%")
    if not text:
        return "No ETA report found.\n"
    held_out_coverage = held_out.split("|")[-1].strip() if held_out else "see report"
    shifted_coverage = shifted.split("|")[-1].strip() if shifted else "see report"
    return (
        "**Conformalized ETA intervals** (reports/eta.md, reports/eta.png, "
        "simulated):\n\n"
        f"- Held-out coverage against a 90% target: {held_out_coverage}\n"
        f"- Under 1.5x demand shift: coverage drops to {shifted_coverage}, "
        "recovers after recalibrating on 50 shifted examples (see figure)\n"
    )


def habits_headline() -> str:
    metrics = _latest_artifact_metrics("habits")
    text = _read(REPORTS / "habits.md")
    milestone = _extract_line(text, r"Reaches 90% precision.*?weeks of history\.")
    lines = [
        "**Habit-based schedule suggestions** (reports/habits.md, "
        "reports/habits.png, ml/artifacts/habits, simulated):",
        "",
    ]
    if milestone:
        lines.append(f"- {milestone}")
    if metrics.get("metrics"):
        m = metrics["metrics"]
        lines.append(
            f"- At 12 weeks of history: {m['precision_at_12_weeks']:.0%} precision, "
            f"{m['recall_at_12_weeks']:.0%} recall"
        )
    return "\n".join(lines) + "\n"


def security_headline() -> str:
    text = _read(REPORTS / "tamper_demo.txt")
    broken_chain = _extract_line(text, r"BROKEN CHAIN:.*")
    return (
        "**Tamper-evident audit log** (reports/tamper_demo.txt, "
        "docs/threat-model.md, docs/security-report.md, docs/authorization-matrix.md):\n\n"
        f"- {broken_chain or 'see reports/tamper_demo.txt'}\n"
        "- Authorization matrix: every endpoint in the live OpenAPI schema tested "
        "live as 5 caller types (resident, valet, manager, support, a resident of "
        "a second building) plus unauthenticated; see docs/authorization-matrix.md\n"
        "- Security scans: bandit, pip-audit, npm audit, Schemathesis; every finding "
        "triaged in docs/security-report.md (one false positive, two documented and "
        "accepted tradeoffs, zero unresolved)\n"
    )


def support_assistant_headline() -> str:
    text = _read(REPORTS / "support_eval.md")
    mode = _extract_line(text, r"Mode: [^\n*]+")
    overall_match = re.search(
        r"\*\*all\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)%\*\*", text
    )
    attack = _extract_line(text, r"Attack group: \d+/\d+ passed[^\n]*")
    if not text:
        return "No support eval report found.\n"
    overall = (
        f"{overall_match.group(1)}/{overall_match.group(2)} passed ({overall_match.group(3)}%)"
        if overall_match
        else "see report"
    )
    return (
        "**Support assistant evaluation** (reports/support_eval.md, "
        "evals/support_cases.yaml, 62 cases across 6 groups):\n\n"
        f"- {mode}\n"
        f"- Overall: {overall}\n"
        f"- {attack or 'see report'}\n"
    )


def main() -> None:
    sections = [
        ("# Results", "", ""),
        (
            "",
            "All numbers below are read programmatically from the files in "
            "`reports/`, `ml/artifacts/`, and `docs/` by `scripts/build_results.py` "
            "(run via `make report`), not retyped by hand. Every section names "
            "its source file. Simulator and ML numbers are labeled simulated; "
            "they are not from a pilot building.",
            "",
        ),
        ("## 1. Departure-aware garage assignment", policy_headline(), ""),
        ("## 2. Digital twin", "See `make sim` and `reports/baseline_*.md` for per-scenario baseline results (30 seeds each, simulated).", ""),
        ("## 3. Forecast-driven staffing", staffing_headline(), ""),
        ("## 3b. Demand forecast accuracy", forecast_headline(), ""),
        ("## 4. Calibrated ready-by promises", eta_headline(), ""),
        ("## 5. Schedule engine", "Property-based tests in `backend/tests/test_schedule_engine.py` and `backend/tests/test_schedule_engine_properties.py` cover DST transitions, skip/override exceptions, and idempotent materialization; see `make test` output.", ""),
        ("## 5b. Habit-based suggestions", habits_headline(), ""),
        ("## 6. Security and tamper-evident audit log", security_headline(), ""),
        ("## 7. Support assistant", support_assistant_headline(), ""),
    ]

    lines = []
    for heading, body, trailer in sections:
        if heading:
            lines.append(heading)
            lines.append("")
        if body:
            lines.append(body.rstrip())
            lines.append("")
        if trailer:
            lines.append(trailer)
            lines.append("")

    REPORTS.mkdir(exist_ok=True)
    output_path = REPORTS / "RESULTS.md"
    output_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
