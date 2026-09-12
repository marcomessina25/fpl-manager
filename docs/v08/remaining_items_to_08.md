# V0.8 — Remaining Items Before PR (Completed & Verified)

## Purpose

V0.8 is functionally complete and fully verified. The remaining work was limited to **release hygiene, reproducibility, and documentation consistency**.

The predictor itself was **not** expanded further before the PR. Its remaining weaknesses are known, explicitly documented, and intentionally promoted to V0.9.

---

## Priority 1 — Reconcile benchmark documentation
**Status: [x] Completed**

The repository contains multiple benchmark contexts, which are now explicitly separated, reconciled, and documented across `README.md`, `docs/v08/v08.md`, and `pr_text.txt`:

### Controlled V0.8 milestone benchmark (2023-24 Season)
Out-of-sample A/B comparison evaluated side-by-side against the frozen V0.7 control on identical historical snapshots:
- **xM MAE:** 23.88 → 19.88 minutes (-16.8% error reduction)
- **xP MAE:** 1.403 → 1.335 points
- **Spearman Rank Correlation ($\rho$):** 0.5771 → 0.6075
- **Production Optimizer Net Points (GW 1–5 Replay):** 235 → 244 net points (+9 net points directly gained)

### Latest 2025-26 validation run
Full-season evaluation on the 2025-26 dataset:
- **xM MAE:** 13.92 minutes
- **xP MAE:** 1.150 points
- **Spearman Rank Correlation ($\rho$):** 0.6750
- **xM Bias:** approximately -0.12 minutes
- **Availability Precision:** 81.8%
- **Availability Recall:** 83.7%

*Separation Guarantee:* These results derive from different experiments/runs and are explicitly documented as separate verification baselines to prevent cross-run conflation.

---

## Priority 2 — Make the predictor limitation explicit
**Status: [x] Completed**

The predictor architecture and its known limitations are explicitly documented across `README.md`, `docs/v08/v08.md`, and `pr_text.txt`:

- **Heuristic Probabilistic Model:** The current V0.8 participation engine (`src/fpl_manager/participation.py`) is a **heuristic probabilistic model** (Bayesian recency blending over last 3/5 matches, consecutive-zero role-loss decay, turnaround congestion penalties), **not yet a learned ML classifier**.
- **Stepping Stone:** The implementation is deliberately a V0.8 transitional stepping stone to validate the participation hypothesis and establish clean feature pipelines before introducing machine learning complexity.
- **Intermediate Rotation Cohort Bottleneck:** The principal unresolved weakness is the intermediate rotation cohort, especially in the approximately 30–70 predicted minutes range (where MAE peaks around ~33.9 minutes due to ambiguity between substitute cameos, rotation benchings, and early substitutions).
- **Promotion to V0.9:** Addressing this cohort with learned statistical/ML classifiers ($P(\text{start})$, $P(\text{sub})$), probability calibration (Platt/isotonic), conditional minutes distribution models, and multi-season temporal evaluation is explicitly scheduled for V0.9.

---

## Priority 3 — Preserve the frozen baselines
**Status: [x] Completed**

- [x] **V0.7 predictor remains selectable:** Verified via `--predictor v0.7` across `fpl backtest-predictions` and `fpl backtest-decisions` (e.g. producing 68 net points on GW1-2 no-transfer baseline).
- [x] **V0.8 predictor is selectable:** Verified via `--predictor v0.8` (default, producing 94 net points on GW1-2 no-transfer baseline).
- [x] **Benchmark configurations are reproducible:** Deterministic execution with identical point-in-time snapshot reconstruction.
- [x] **Reports identify provenance:** All generated backtest reports in `reports/backtests/` explicitly identify season, Gameweek range, predictor version, and strategy type in their headers, summaries, and filenames.

---

## Priority 4 — Final PR checks
**Status: [x] Completed**

Before opening/merging:
- [x] **Complete test suite passed:** 213 passed, 0 failures, 0 errors in 86.35s (100% pass rate).
- [x] **Backtest CLI smoke tests passed:**
  - `fpl backtest-predictions --season 2023-24 --start-gw 1 --end-gw 2 --predictor v0.8 --report` verified.
  - `fpl backtest-predictions --season 2023-24 --start-gw 1 --end-gw 2 --predictor v0.7 --report` verified.
  - `fpl backtest-participation --season 2023-24 --start-gw 1 --end-gw 2 --report` verified.
  - `fpl backtest-decisions --season 2023-24 --strategy notransfer --start-gw 1 --end-gw 2 --predictor v0.8` verified.
  - `fpl backtest-decisions --season 2023-24 --strategy notransfer --start-gw 1 --end-gw 2 --predictor v0.7` verified.
- [x] **Generated reports reproducible & isolated:** Reports directory clean; ignored runtime artifacts protected by `.gitignore`.
- [x] **No credentials or private squad data committed:** `.gitignore` covers `config/current_squad.json`, `config/teams/*`, `players.txt`, and SQLite/raw caches. Verified `git status`.
- [x] **Inspected final diff:** Clean, intentional changes limited to documentation, benchmarks reconciliation, and V0.9 planning roadmap.
- [x] **PR description matches branch state:** `pr_text.txt` updated to include reconciled benchmark suites and explicit model limitations.

---

## Explicitly deferred to V0.9

The following items are intentionally **not** in V0.8 and will not block this PR:
- Learned participation model ($P(\text{start})$, $P(\text{sub})$ via logistic regression / gradient boosting / trees);
- Formal probability calibration (Platt scaling, isotonic regression, reliability curves);
- Continuous / categorical conditional minutes distributions;
- Extended rotation features (manager/team rotation patterns, role-transition detection);
- Broader xP component calibration (xG/xA conversion ratios, defensive clean sheets);
- Rank-aware strategy refinements and multi-season decision simulation expansions;
- Multi-provider LLM expansion.

---

## Release decision

**PR APPROVED:** All documentation, reproducibility, verification, and hygiene items are completed.

The current predictor successfully establishes the new V0.8 baseline (-16.8% xM MAE, +9 net optimizer points). Its remaining performance gap in the 30–70 minute range is valuable research information that forms the exact foundation of the V0.9 plan in `docs/v09/v09.md`.
