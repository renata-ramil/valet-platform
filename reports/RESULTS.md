# Results

All numbers below are read programmatically from the files in `reports/`, `ml/artifacts/`, and `docs/` by `scripts/build_results.py` (run via `make report`), not retyped by hand. Every section names its source file. Simulator and ML numbers are labeled simulated; they are not from a pilot building.

## 1. Departure-aware garage assignment

**Departure-aware spot assignment vs nearest-free baseline**, weekday_peak scenario, 30 paired seeds (reports/policies_summary.md, reports/policies_experiments.parquet, recomputed here with `sim.experiments.paired_diff_ci`, simulated):

- Relocations per retrieval: -0.0719 (95% CI -0.104 to -0.0398)
- On-time rate: 0.0573 (95% CI 0.0237 to 0.0913)

## 2. Digital twin

See `make sim` and `reports/baseline_*.md` for per-scenario baseline results (30 seeds each, simulated).

## 3. Forecast-driven staffing

**Forecast-driven staffing vs flat coverage**, weekday_peak ground-truth demand (reports/policies_summary.md, simulated):

- Flat staffing (all valets on all day): 144.0 valet-hours
- CP-SAT shift covering: 48.0 valet-hours
- Savings: 67% fewer valet-hours at the same coverage target

## 3b. Demand forecast accuracy

**Hierarchical negative binomial demand forecast** (reports/forecast.md, reports/forecast.png, simulated):

- 4-fold rolling-origin backtest, 80% target coverage, achieved: 95.5%, 94.2%, 95.5%, 92.4%
- Convergence: Max R-hat across folds is 1.070, zero divergences in every fold

## 4. Calibrated ready-by promises

**Conformalized ETA intervals** (reports/eta.md, reports/eta.png, simulated):

- Held-out coverage against a 90% target: 91.1%
- Under 1.5x demand shift: coverage drops to 84.1%, recovers after recalibrating on 50 shifted examples (see figure)

## 5. Schedule engine

Property-based tests in `backend/tests/test_schedule_engine.py` and `backend/tests/test_schedule_engine_properties.py` cover DST transitions, skip/override exceptions, and idempotent materialization; see `make test` output.

## 5b. Habit-based suggestions

**Habit-based schedule suggestions** (reports/habits.md, reports/habits.png, ml/artifacts/habits, simulated):

- Reaches 90% precision (with recall already above 50%, so it isn't a small-sample fluke) at 8 weeks of history.
- At 12 weeks of history: 100% precision, 97% recall

## 6. Security and tamper-evident audit log

**Tamper-evident audit log** (reports/tamper_demo.txt, docs/threat-model.md, docs/security-report.md, docs/authorization-matrix.md):

- BROKEN CHAIN: Hash chain broken for request 90fbe998-b5a6-45fc-81b8-4ad07940c90c at event 074e9e12-dea1-47ef-abd4-fabb30b5cf47 (position 1): stored hash does not match its type, payload and prev_hash (tampered content)
- Authorization matrix: every endpoint in the live OpenAPI schema tested live as 5 caller types (resident, valet, manager, support, a resident of a second building) plus unauthenticated; see docs/authorization-matrix.md
- Security scans: bandit, pip-audit, npm audit, Schemathesis; every finding triaged in docs/security-report.md (one false positive, two documented and accepted tradeoffs, zero unresolved)

## 7. Support assistant

**Support assistant evaluation** (reports/support_eval.md, evals/support_cases.yaml, 62 cases across 6 groups):

- Mode: rule-based fallback (no ANTHROPIC_API_KEY set)
- Overall: 62/62 passed (100%)
- Attack group: 12/12 passed, zero data leaks.

