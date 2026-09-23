# V0.9 Focused Error Attribution & Decision-Impact Investigation

## Purpose

This investigation is the next step for V0.9 after the 2025/26 prediction and decision backtests.

The objective is **not to redesign V0.9 yet**. The objective is to determine precisely where the remaining V0.9 errors come from, how costly those errors are for FPL decisions, and which component should be changed next.

We must separate four questions:

1. Is the remaining weakness primarily **participation-state prediction**?
2. Is it primarily **conditional minutes estimation**?
3. Is it primarily **probability calibration / thresholding**?
4. Is the prediction reasonable but the **decision engine/optimizer converts it poorly into decisions**?

Only after these questions are answered should the next V0.9 implementation be selected.

---

# Current Evidence

The current 2025/26 V0.9 prediction report shows:

| Metric | V0.8 | V0.9 |
|---|---:|---:|
| xP MAE | 1.150 | **1.127** |
| xP RMSE | 1.984 | **1.978** |
| xP Spearman | 0.6750 | **0.6779** |
| xP Bias | +0.087 | **+0.058** |
| xM MAE | 13.92 | **13.68** |
| xM RMSE | 23.62 | **23.50** |
| xM Bias | -0.12 | **-1.23** |
| Availability Precision | 81.8% | **80.0%** |
| Availability Recall | 83.7% | **88.6%** |
| False Positives | 2,118 | **2,520** |
| False Negatives | 1,851 | **1,295** |

The V0.9 report also shows xM MAE of 2.9, 25.6, 33.9, 27.3 and 17.7 minutes for the 0–15, 16–30, 31–60, 61–75 and 76–90 predicted-minute buckets respectively.

The current decision replay reports:

- Production Optimizer: **2015 points**
- Simple xP: **1919 points**
- No Transfer: **1602 points**
- Optimizer vs Simple: **+96 points**
- Optimizer vs No Transfer: **+413 points**
- 42 zero-minute starters
- 4 zero-minute captains
- 246 points bench regret
- +154 gross transfer gain

These are context, not targets to optimize against directly.

---

# Investigation Principles

## 1. Do not change the production model during the investigation

Do not tune V0.9 coefficients, alter calibration parameters, change production thresholds, change optimizer weights, introduce new production features, or retrain against the final 2025/26 test set.

Exploratory models must remain isolated from production.

## 2. Keep V0.8 as the immutable control

Every major analysis must support direct V0.8 vs V0.9 comparison.

## 3. Preserve point-in-time semantics

Every prediction must use only information available immediately before the relevant gameweek.

## 4. Separate prediction error from decision error

A bad FPL decision does not automatically imply a bad prediction, and a prediction error does not necessarily affect a decision.

---

# P0 — Establish a Reproducible Analysis Dataset

## Objective

Create one canonical player-gameweek analysis table from the same 2025/26 backtest data used by the existing reports.

Each row represents:

`player × gameweek`

## Required fields

### Identity
- season
- gameweek
- player_id
- player_name
- team
- position

### Pre-GW context
- price
- ownership if available
- prior minutes
- minutes last 3
- minutes last 5
- starts last 3
- starts last 5
- consecutive zero appearances
- rest days
- congestion / dense-7-day indicator
- current regime
- relevant V0.9 features

### Prediction
- predicted xP
- predicted xM
- P(no appearance)
- P(sub)
- P(start)
- P(play)
- P(60+)
- predicted participation state
- predicted conditional minutes if available

### Ground truth
- actual points
- actual minutes
- actual state: NO_PLAY / SUB / START

### Decision context
Where available:
- simulated squad ownership
- selected XI
- bench position
- captain
- transfer in/out
- transfer candidate ranking
- optimizer score
- simple xP ranking
- realized points

## Acceptance criteria

A single player-gameweek must be traceable end-to-end:

`features → prediction → participation state → xP → optimizer score → decision → actual outcome`

---

# P1 — Build the Participation-State Confusion Matrix

## Objective

Determine whether V0.9's remaining error is fundamentally a classification problem.

Use three states:

`NO_PLAY / SUB / START`

Create the full confusion matrix:

| Predicted \ Actual | NO_PLAY | SUB | START |
|---|---:|---:|---:|
| NO_PLAY | | | |
| SUB | | | |
| START | | | |

Report counts, row/column percentages, precision, recall, F1 and macro-F1.

Run this for both V0.8 and V0.9.

## Required breakdowns

Repeat by:

- position
- price tier
- regime
- predicted xM bucket
- team
- xP percentile
- congestion state

## Acceptance criteria

Identify the dominant transitions, such as:

- START → NO_PLAY
- START → SUB
- SUB → NO_PLAY
- SUB → START
- NO_PLAY → SUB
- NO_PLAY → START

Do not collapse SUB and START into a single available class for this analysis.

---

# P2 — Quantify the Cost of Participation-State Errors

## Objective

Translate classification errors into FPL-relevant consequences.

For every state-transition error calculate:

- count
- mean actual points
- mean predicted xP
- mean predicted xM
- actual minutes
- predicted minutes
- estimated point loss
- total realized point exposure

Example:

`Pred START → Actual NO_PLAY`

Report count, xP, xM, actual minutes, actual points and decision relevance.

## Prioritize high-value errors

Break errors into:

- top 10% xP players
- premium players
- midfielders/forwards
- captain candidates
- likely starters
- bench candidates

The key question is:

> Are the errors mostly harmless low-value players, or are they affecting players the optimizer actually wants?

## Acceptance criteria

Produce a ranked table of state errors by **decision relevance**, not frequency alone.

---

# P3 — False Positive / False Negative Attribution

## Objective

Explain the V0.9 availability trade-off.

V0.8:
- FP = 2,118
- FN = 1,851
- precision = 81.8%
- recall = 83.7%

V0.9:
- FP = 2,520
- FN = 1,295
- precision = 80.0%
- recall = 88.6%

## False positives

For every V0.9 FP capture:

- actual minutes
- predicted xM
- P(play)
- P(start)
- predicted state
- actual state
- price
- xP
- position
- regime
- congestion
- recent starts
- recent minutes

Aggregate by probability bucket, xM bucket, position, price tier, regime, team and player.

## False negatives

Perform the same analysis.

## Required output

Create:

`error type → frequency → average xP exposure → total xP exposure → realized points`

## Acceptance criterion

Determine whether V0.9's extra recall is valuable or mainly creates additional false confidence.

---

# P4 — Conditional Minutes Investigation

## Objective

Determine whether remaining xM error is primarily caused by incorrect participation state or incorrect minutes conditional on the correct state.

For correctly classified observations calculate:

`residual = actual_minutes - predicted_minutes`

separately for:

- NO_PLAY
- SUB
- START

## Required statistics

For each state:

- MAE
- RMSE
- bias
- median absolute error
- mean predicted minutes
- mean actual minutes
- sample count

Repeat by position, regime, price tier and predicted-minute bucket.

## Counterfactual decomposition

Where possible calculate:

### Oracle-state estimate

Use the actual participation state but retain the model's conditional-minute prediction.

### Oracle-minutes estimate

Use actual minutes conditional on the predicted state.

Use these to estimate how much xM error is attributable to:

1. wrong state;
2. wrong conditional minutes.

## Acceptance criteria

Produce a quantitative decomposition of total xM error into state-classification and conditional-minute components.

---

# P5 — Investigate the 16–60 Minute Region

## Objective

Focus on the known difficult region.

The current V0.9 report shows:

- 16–30 MAE = **25.6**
- 31–60 MAE = **33.9**

## Required analysis

For predictions in 16–60 minutes produce:

- actual-minute histogram
- predicted-minute histogram
- actual state distribution
- predicted state distribution
- confusion matrix
- mean actual minutes by predicted state
- residual distribution

Explicitly test whether actual minutes cluster around:

- 0
- substitute minutes
- starter minutes

rather than forming a smooth continuous distribution.

## Required conclusion

Determine from evidence whether continuous expected-minute prediction is adequate or whether a discrete state model plus conditional minutes distribution is justified.

Do not assume the state-model hypothesis before measuring it.

---

# P6 — Calibration and Threshold Sensitivity

## Objective

Determine whether the FP/FN trade-off is primarily a calibration problem or an operating-point problem.

Use the existing frozen V0.9 predictions. Do not retrain.

For P(play), P(start) and P(60+) report:

- reliability curves
- Brier
- log loss
- ECE
- MCE

Then sweep analysis-only thresholds, e.g.:

`0.50, 0.55, 0.60, ... 0.95`

For each threshold report:

- precision
- recall
- F1
- FP
- FN
- zero-minute starters
- zero-minute captains
- decision-weighted cost

Do not change the production threshold during this task.

## Acceptance criteria

Identify the operating region that best trades off missed playable players against false playable players, and determine whether the current production operating point is defensible.

---

# P7 — Decision-Impact Attribution

## Objective

Determine exactly how V0.9 participation predictions affect the 2015-point result.

For every important decision capture:

## Transfer
- player transferred out
- player transferred in
- xP before transfer
- xM before transfer
- participation probabilities
- optimizer score
- realized points
- counterfactual realized points

## Lineup
For each selected player:
- predicted state
- predicted xM
- predicted xP
- actual state
- actual minutes
- actual points

## Bench
For each relevant benched player:
- predicted xM
- actual minutes
- actual points
- hindsight selection opportunity

## Captain
For each captain:
- predicted xP
- predicted xM
- actual minutes
- actual points
- best alternative actual points
- participation error

---

# P8 — Counterfactual Decision Experiments

## Objective

Separate prediction quality from optimizer quality.

Run the same historical gameweeks with:

### A — V0.8 predictor + V0.8 engine

### B — V0.9 predictor + V0.8 engine

### C — V0.8 predictor + V0.9 engine

### D — V0.9 predictor + V0.9 engine

These runs must use the repaired and validated ablation harness.

For each report:

- total points
- points vs no-transfer
- points vs simple xP
- zero-minute starters
- zero-minute captains
- bench regret
- transfer gain
- transfer count

Estimate:

`predictor contribution + engine contribution + predictor×engine interaction`

Do not interpret identical A/C or B/D results as evidence of equivalence until the harness proves the engines are actually different.

---

# P9 — Decision-Weighted Error Ledger

## Objective

Create a single ledger connecting prediction errors to actual FPL consequences.

Classify each material error as:

- PREDICTION_ERROR
- DECISION_ERROR
- BOTH
- HARMLESS

Example:

A player predicted START but actually did not play.

If selected and a safer alternative existed, classify as decision-relevant.

If not selected and the prediction had no effect, classify as harmless.

This distinction is critical: statistical errors are not automatically FPL errors.

---

# P10 — Produce the Error Attribution Dashboard

## Objective

Create:

`reports/v09_error_attribution_2025_26.md`

and:

`reports/v09_error_attribution_2025_26.json`

Optional:

- `reports/v09_state_confusion_2025_26.csv`
- `reports/v09_error_ledger_2025_26.csv`
- `reports/v09_decision_impact_2025_26.csv`

## Markdown report sections

1. Dataset
2. V0.8 vs V0.9 prediction comparison
3. Participation confusion matrix
4. FP/FN attribution
5. Conditional minutes attribution
6. 16–60 minute investigation
7. Calibration/threshold analysis
8. Decision error ledger
9. Counterfactual optimizer experiments
10. Decision-weighted impact
11. Root-cause conclusion
12. Recommended next implementation

---

# P11 — Root-Cause Decision Tree

The final report must choose the evidence-supported path.

## Case A — State classification dominates

If most xM error and decision regret comes from:

`START ↔ SUB / START ↔ NO_PLAY / SUB ↔ NO_PLAY`

then focus next on a discrete state participation model.

## Case B — Conditional minutes dominate

If state classification is good but minutes inside each state remain poor, focus on:

- conditional minutes distributions
- player-specific minutes
- regime-specific minutes
- quantile prediction
- uncertainty modelling

Do not redesign classification unnecessarily.

## Case C — Calibration dominates

If raw predictions are useful but calibration/threshold errors cause most decision losses, focus on:

- temporal calibration
- state-specific calibration
- decision-aware thresholding

Do not retrain the core predictor prematurely.

## Case D — Prediction is adequate but decisions are poor

If counterfactuals show useful V0.9 predictions but poor decisions, focus on:

- optimizer objective
- lineup risk penalty
- bench construction
- captain selection
- transfer risk
- participation-aware constraints

## Case E — Predictor/optimizer interaction dominates

Investigate:

- objective coupling
- xP/xM interaction
- probability calibration
- risk penalties
- nonlinear decision effects

---

# P12 — Final Investigation Checklist

## Experimental validity
- [ ] Same data and point-in-time rules for all comparisons
- [ ] V0.8 immutable
- [ ] V0.9 immutable during investigation
- [ ] Four-way harness validated
- [ ] Predictor and engine selections explicitly recorded

## Prediction
- [ ] State confusion matrix
- [ ] FP/FN attribution
- [ ] Conditional-minute decomposition
- [ ] 16–60 minute analysis
- [ ] Position/regime/price breakdowns

## Calibration
- [ ] Reliability curves
- [ ] Brier/log loss/ECE/MCE
- [ ] Threshold sweep
- [ ] Decision-weighted calibration impact

## Decision impact
- [ ] Transfer attribution
- [ ] Lineup attribution
- [ ] Bench attribution
- [ ] Captain attribution
- [ ] Counterfactual 2×2
- [ ] Error ledger

## Final decision
- [ ] Root cause identified
- [ ] One highest-value intervention selected
- [ ] Evidence supporting it documented
- [ ] No production changes made before attribution

---

# Final Question

The investigation must end by answering:

> **If we were allowed to change only ONE part of V0.9 next, what should we change, and what evidence proves that this is the highest-value intervention?**

Do not answer this before completing P0–P10.

The purpose of this investigation is not to maximize another aggregate metric. It is to understand **why V0.9 still makes wrong FPL decisions and which specific component is responsible**.
