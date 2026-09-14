# V0.9 Predictor Regression Investigation & Release Gate

## Purpose

The current `v09` branch contains the V0.9 learned participation/prediction system and associated decision-layer changes.

The latest 2025-26 full-season backtest shows that V0.9 is **not yet demonstrated to be better than V0.8 in absolute FPL points**. Do not open/merge the V0.9 PR until the investigation below is completed and documented.

This document is an implementation/investigation brief for an AI coding agent.

## 1. Current Evidence

### V0.9 prediction results — 2025-26

- Evaluated player-gameweeks: 29,338
- xP MAE: **1.174**
- xP RMSE: **1.990**
- xP Spearman: **0.6835**
- xP bias: **+0.130**
- xM MAE: **15.90 min**
- xM RMSE: **24.32 min**
- xM bias: **+3.11 min**
- Availability precision: **79.9%**
- Availability recall: **88.8%**
- False positives: **2,534**
- False negatives: **1,276**

The problematic xM buckets are:

| Predicted minutes | MAE |
|---|---:|
| 0-15 | 4.3 |
| 16-30 | **22.7** |
| 31-60 | **33.5** |
| 61-75 | 26.0 |
| 76-90 | 18.7 |

The key remaining problem is intermediate participation, especially 16-60 minutes.

### V0.8 comparison — 2025-26

Previously established V0.8 results:

- xP MAE: **1.150**
- xP RMSE: **1.984**
- xP Spearman: **0.6750**
- xM MAE: **13.92 min**
- xM RMSE: **23.62 min**
- xM bias: approximately **-0.12 min**
- Availability precision: **81.8%**
- Availability recall: **83.7%**
- False positives: **2,118**
- False negatives: **1,851**

Therefore V0.9 currently has slightly better xP ranking, but worse xP absolute error, materially worse xM error, more positive xM bias, higher recall but lower precision, and more false positives.

### V0.9 decision simulation — 2025-26

| Strategy | Net points |
|---|---:|
| Simple xP Baseline (V0.9) | **1903** |
| Production Optimizer neutral (V0.9) | **1901** |
| No-Transfer Baseline | **1340** |

Decision diagnostics:

| Strategy | 0-min starters | 0-min captains | Bench regret | Transfer gain |
|---|---:|---:|---:|---:|
| Simple xP | 53 | 5 | 279 | +68 |
| Production Optimizer | 58 | 6 | **198** | **+108** |
| No Transfer | 104 | 4 | 1 | 0 |

The V0.9 optimizer is only **2 points behind** its Simple xP strategy.

This is substantially better than the established V0.8 relationship:

- V0.8 Simple xP: **2063**
- V0.8 Production Optimizer: **1962**
- Difference: **-101 points**

Do not discard the V0.9 decision-layer changes merely because total points are lower.

## 2. Primary Objective

Determine **why V0.9 currently scores fewer points than V0.8** and identify the smallest scientifically justified changes required before the V0.9 release PR.

Do not begin by blindly tuning coefficients.

First isolate the source of the regression.

The investigation must distinguish:

1. regression caused by the new V0.9 predictor;
2. improvement/regression caused by the V0.9 decision engine;
3. interaction between predictor and decision engine;
4. differences caused by xP calibration/projection changes;
5. differences caused by backtest configuration or data.

## 3. Mandatory Four-Way Ablation

Run a controlled 2x2 experiment:

### A — V0.8 predictor + V0.8 decision engine

Historical baseline.

### B — V0.9 predictor + V0.8 decision engine

Question: **Does the new predictor itself improve or hurt FPL decision performance?**

### C — V0.8 predictor + V0.9 decision engine

Question: **Does the V0.9 decision engine improve performance independently of the new predictor?**

### D — V0.9 predictor + V0.9 decision engine

Current result:

- Simple xP: 1903
- Production Optimizer: 1901

Produce:

| Predictor | Decision engine | Simple xP | Optimizer | Difference |
|---|---|---:|---:|---:|
| V0.8 | V0.8 | | | |
| V0.9 | V0.8 | | | |
| V0.8 | V0.9 | | | |
| V0.9 | V0.9 | 1903 | 1901 | -2 |

Also report:

- 0-minute starters
- 0-minute captains
- bench regret
- transfer gain / ROI
- points per GW
- total transfers
- other existing decision diagnostics

The experiment must be reproducible from repository commands.

## 4. Predictor Ablation

Compare at minimum:

1. V0.8 participation/xM + V0.8 xP components
2. V0.9 learned participation/xM + V0.8 xP components
3. V0.8 participation/xM + V0.9 xP components
4. V0.9 learned participation/xM + V0.9 xP components

If supported cleanly, also compare:

- learned participation without regime overlay
- learned participation + regime overlay
- learned participation + calibration
- learned participation + regime + calibration

Reuse existing predictor-version switches and infrastructure wherever possible.

## 5. Expected Minutes Investigation

Focus specifically on intermediate participation.

Current V0.9 errors:

- 16-30 min: 22.7 MAE
- 31-60 min: 33.5 MAE
- 61-75 min: 26.0 MAE

Investigate:

- start probability calibration
- substitute probability calibration
- probability of playing
- conditional starter minutes
- conditional substitute minutes
- zero-minute outcomes
- recent starts/minutes
- consecutive zero-minute runs
- fixture congestion
- player role/regime
- returning-from-injury behaviour
- emerging/demoted/fringe players

Produce error breakdowns by:

- position
- price tier
- role/regime
- predicted-minute bucket
- actual-minute bucket
- start/sub/no-appearance state

Determine whether the problem is primarily bad probabilities, conditional minutes, regime classification, calibration, feature insufficiency, or interactions.

## 6. Probability Calibration Audit

Evaluate separately:

- `P(start)`
- `P(sub | not start)` if available
- `P(play)`
- `P(60+)`

For each report:

- Brier score
- log loss
- reliability buckets/curve
- ECE
- MCE
- sample count

Compare calibrated vs uncalibrated outputs where supported.

Do not assume better xM MAE implies better probability calibration.

## 7. Temporal / Leakage Audit

Verify strict chronology.

Document:

- training seasons/gameweeks
- calibration period
- validation period
- final test period
- feature availability timestamp
- whether post-deadline/current-GW information can influence predictions

The 2025-26 final evaluation must remain untouched by model/threshold selection.

Do not tune against 2025-26 and then report it as an independent validation set.

Use rolling-origin or chronological validation where infrastructure supports it.

Run existing leakage tests and add tests for any discovered gap.

## 8. Decision-Weighted Evaluation

Do not evaluate only global MAE/RMSE.

Report:

### Player selection
- 0-minute selected starters
- selected players with <15 minutes
- selected players with 16-30 minutes
- selected players with 31-60 minutes
- bench regret

### Captaincy
- 0-minute captains
- captain points
- captain regret if calculable
- decisions affected by participation uncertainty

### Transfers
- gross transfer gain
- transfer net ROI
- number of transfers
- bad transfer rate
- points lost from selecting non-participants

### Season
- total points
- points/GW
- head-to-head vs No Transfer
- Simple xP vs Optimizer gap

## 9. Interpretation Rules

Do **not** declare V0.9 a failure solely because total points are below V0.8.

Do **not** declare V0.9 a success solely because Spearman is higher.

The current evidence is already interesting:

> V0.9's optimizer is almost tied with its Simple xP strategy (-2 points), whereas V0.8's optimizer was substantially behind Simple xP (-101 points).

Determine whether this confirms that some V0.9 decision-layer changes are valuable independently of the predictor.

## 10. Do Not Optimize Directly for 2025-26

2025-26 is the final evaluation period.

If changes are required:

1. identify the failure mode;
2. select model/feature changes using training/validation periods;
3. evaluate on held-out periods;
4. report 2025-26 only as final validation.

Prefer chronological/rolling-origin evaluation.

## 11. Release Gate

V0.9 should not open its release PR until:

### Mandatory
- [ ] Four-way predictor/decision ablation completed.
- [ ] Predictor regression source identified.
- [ ] xM intermediate-minute failure investigated.
- [ ] Probability calibration audited.
- [ ] Temporal split/leakage verified.
- [ ] Full test suite passes.
- [ ] Results reproducible from repository commands.
- [ ] `docs/v09/v09_regression_investigation.md` contains final results.
- [ ] `docs/v09/v09.md` updated with final experimental results.
- [ ] `docs/roadmap.md` accurately reflects completed/deferred work.
- [ ] No benchmark definition was changed merely to improve the result.

### Strongly preferred
- [ ] V0.9 learned participation beats V0.8 on held-out predictive metrics, OR
- [ ] there is a documented scientific reason to retain it despite not beating V0.8 globally.
- [ ] V0.9 decision-layer improvements are demonstrated independently.
- [ ] A clear production participation-model recommendation is made.

## 12. Possible Outcomes

### A — V0.9 predictor is clearly worse

Keep the V0.9 architecture but improve/rework learned participation. Do not merge the current predictor.

### B — V0.9 predictor is statistically better but produces fewer FPL points

Investigate calibration/objective mismatch. Do not immediately revert it.

### C — V0.9 predictor is good, V0.9 decision engine is bad

Keep the predictor and fix/revert the decision-layer change.

### D — V0.9 decision engine is better but predictor is worse

This is a plausible hypothesis. Keep decision-layer improvements and improve/replace participation model.

### E — Backtest configuration is responsible

Fix the benchmark before changing the model.

## 13. Engineering Requirements

The agent should:

- inspect the existing V0.9 branch before modifying code;
- reuse existing predictor-version switches;
- avoid unnecessary API/interface changes;
- add deterministic/reproducible experiment commands;
- add regression tests for discovered bugs;
- avoid test-season-specific constants;
- avoid changing baseline implementations to improve comparisons;
- keep V0.8 behaviour frozen;
- document every experimental configuration;
- ensure reports identify predictor and decision-engine versions.

Do not remove V0.8.

V0.8 must remain an immutable comparison baseline.

## 14. Deliverables

### Code

Minimal code required for:

- ablation execution
- diagnostics
- calibration analysis
- reproducibility
- regression tests

### Report

Create:

`docs/v09/v09_regression_investigation.md`

with:

1. executive summary
2. V0.8 vs V0.9 comparison
3. four-way ablation
4. predictor ablation
5. xM error analysis
6. probability calibration
7. temporal/leakage audit
8. decision-weighted analysis
9. root cause
10. recommended changes
11. final release recommendation

### Optional machine-readable output

If practical:

`reports/v09_ablation_results.json`

and/or reproducible CSV output.

## 15. Final Agent Report

The final response must explicitly answer:

1. Why does V0.9 currently score fewer points than V0.8?
2. Is the regression caused by predictor, decision engine, or both?
3. Is learned V0.9 participation actually better than V0.8?
4. Which part of xM modelling is failing?
5. Are V0.9 decision-layer changes worth keeping?
6. What exact changes should be made before release?
7. Can we open the V0.9 PR now?

End with an unambiguous:

**PR READY** or **NOT PR READY**

Do not recommend opening the PR merely because the test suite passes.
