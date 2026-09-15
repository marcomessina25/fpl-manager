# V0.9 Follow-up Tasks — Predictor & Evaluation Repair

## Purpose

This document defines the **P0–P8 tasks** required after the V0.9 ablation/regression investigation.

The current evidence shows that V0.9 is **not PR-ready**. The immediate objective is not to add more features, but to establish a scientifically valid experiment, identify the source of the regression, and produce a participation model that is demonstrably better than the frozen V0.8 baseline.

## Evidence driving this plan

The latest V0.9 investigation reported:

- V0.9 2025/26 xP MAE: **1.174** vs V0.8 **1.150**
- V0.9 xP RMSE: **1.990** vs V0.8 **1.984**
- V0.9 xP Spearman: **0.6835**, slightly better than V0.8
- V0.9 xM MAE: **15.905**, substantially worse than V0.8 **13.92**
- V0.9 xM bias: **+3.11 minutes**
- V0.9 availability precision/recall: **79.9% / 88.8%**
- Current calibrated P(start) has severe high-confidence miscalibration: the 0.9–1.0 bin predicts about **0.9935** while actual frequency is about **0.7672**
- Current calibration improves some probability metrics but **worsens xM MAE**: calibrated 15.905 vs uncalibrated 14.749
- Removing regimes worsens xM MAE to **18.715**, so the regime layer appears useful and should be retained.
- The xM 16–30 and 31–60 minute buckets reveal a strongly multimodal participation distribution: roughly **0 minutes / substitute minutes / starter minutes**, rather than a smooth continuous distribution.
- Most importantly, the four-way predictor/decision-engine ablation produced:
  - V0.8 predictor + V0.8 engine = **2063 / 1962**
  - V0.9 predictor + V0.8 engine = **1903 / 1901**
  - V0.8 predictor + V0.9 engine = **2063 / 1962**
  - V0.9 predictor + V0.9 engine = **1903 / 1901**

The exact equality between A/C and B/D means the decision-engine ablation is **not yet causally valid**. Do not conclude that V0.9's regression is caused by the predictor until this is fixed and rerun.

---

# P0 — Repair and Validate the Four-Way Ablation Harness

## Objective

Prove that the experiment actually switches between V0.8 and V0.9 decision engines while holding everything else constant.

## Required work

1. Locate the exact code path used by the ablation harness to select:
   - predictor version
   - decision-engine version
2. Trace both selections from CLI/configuration through the complete replay path.
3. Confirm that `decision_engine=v0.8` and `decision_engine=v0.9` instantiate/call genuinely different implementations.
4. Add explicit instrumentation to the experiment output:
   - predictor version
   - decision-engine version
   - optimizer implementation/class/function
   - relevant strategy configuration
5. Add a unit/integration test that fails if changing the decision-engine selector does not change the selected implementation.
6. Run a deliberately synthetic test where V0.8 and V0.9 engines are forced to produce distinguishable decisions, proving the selector works.
7. Re-run the complete 2x2 experiment.

## Acceptance criteria

- A/C are allowed to match only if the engines are genuinely different but happen to produce identical results; this must be demonstrated, not assumed.
- B/D are subject to the same requirement.
- The output must make the selected predictor and engine unambiguous.
- No causal claim about the decision engine is valid before this task passes.

---

# P1 — Audit and Document Every Ablation Component

## Objective

Ensure every reported ablation corresponds to a real, isolated code-path change.

## Required work

For each experiment variant, document exactly what changes:

- V0.8 predictor
- V0.9 predictor
- V0.8 decision engine
- V0.9 decision engine
- `v0.9_part_v0.8_comp`
- calibrated vs uncalibrated probabilities
- regimes enabled/disabled

For each variant record:

1. Input data.
2. Predictor implementation.
3. Participation implementation.
4. Calibration implementation.
5. Decision engine.
6. Optimizer.
7. Objective function.
8. Transfer policy.
9. Captain policy.
10. Any hidden defaults.

Verify that no component silently falls back to another implementation.

## Acceptance criteria

Produce a machine-readable experiment manifest for every run.

The manifest must be sufficient for another developer to reproduce the exact configuration without reading the experiment code.

---

# P2 — Freeze V0.8 as the Immutable Regression Baseline

## Objective

Make V0.8 the permanent scientific reference for V0.9 development.

## Required work

1. Identify the exact V0.8 predictor implementation used for the historical benchmark.
2. Record its configuration and data assumptions.
3. Add regression tests covering the V0.8 benchmark path.
4. Prevent V0.9 changes from silently modifying V0.8 behaviour.
5. Store baseline metrics in a versioned machine-readable artifact.

## Required baseline dimensions

At minimum:

- xP MAE
- xP RMSE
- xP Spearman
- xP bias
- xM MAE
- xM RMSE
- xM bias
- availability precision
- availability recall
- false positives
- false negatives
- decision replay points
- zero-minute starters
- zero-minute captains
- bench regret
- transfer gain

## Acceptance criteria

V0.8 results are reproducible and remain unchanged when V0.9 code is modified.

---

# P3 — Preserve and Harden the V0.9 Regime Layer

## Objective

Keep the regime component because the evidence indicates it materially improves participation prediction.

## Evidence

The regime ablation changed:

- xM MAE without regimes: **18.715**
- xM MAE with regimes: **15.905**
- bias without regimes: **+4.975**
- bias with regimes: **+3.107**

This is a meaningful improvement.

## Required work

1. Keep regimes enabled in the main V0.9 path.
2. Document each regime and its features.
3. Verify that regime features are strictly point-in-time.
4. Add tests for regime transitions.
5. Add diagnostics showing how often each regime is selected.
6. Measure performance by regime:
   - xM MAE
   - xM bias
   - zero-minute rate
   - start/sub probabilities
7. Identify whether any regime is systematically overconfident.

## Acceptance criteria

The regime layer must remain deterministic, leakage-safe, explainable, and independently measurable.

---

# P4 — Replace the Continuous Participation Middle Ground with a State-Based Model

## Objective

Investigate a participation model aligned with the observed multimodal distribution.

## Motivation

The current xM errors indicate that a continuous expected-minute prediction is hiding three fundamentally different states:

1. **No appearance**
2. **Substitute appearance**
3. **Starter appearance**

The latest diagnosis shows that in the 16–30 and 31–60 predicted-minute ranges, actual observations are heavily concentrated around these discrete outcomes.

## Proposed model

Model participation hierarchically:

### Stage 1 — Appearance probability

`P(appearance)`

### Stage 2 — Role probability

Conditional on appearance:

`P(start | appearance)`

`P(sub | appearance) = 1 - P(start | appearance)`

### Stage 3 — Conditional minutes

Estimate separate distributions:

`P(minutes | start)`

`P(minutes | sub)`

Do not immediately collapse these distributions to a single mean.

## Required work

1. Build a state-based baseline using:
   - no appearance
   - substitute
   - starter
2. Keep the current regime features available.
3. Compare:
   - current V0.9 expected-minutes model
   - V0.8
   - state-based V0.9 candidate
4. Evaluate both:
   - expected minutes
   - full state probabilities
5. Investigate whether conditional minutes should be:
   - fixed by position
   - player-specific
   - regime-specific
   - empirical distributions
   - quantile-based

## Acceptance criteria

The new model must beat or clearly justify itself against V0.8 on out-of-sample participation metrics before becoming the production V0.9 model.

---

# P5 — Redesign Calibration as a Temporal, Prediction-Preserving Layer

## Objective

Fix calibration without damaging xM or decision quality.

## Current problem

The current calibration produces strong aggregate calibration metrics in some areas but has severe high-end overconfidence.

For P(start), the highest probability bin is approximately:

- predicted: **0.9935**
- actual: **0.7672**

For P(60+):

- predicted: **0.9585**
- actual: **0.7195**

Furthermore:

- calibrated xM MAE: **15.905**
- uncalibrated xM MAE: **14.749**

Therefore the current calibration transformation is not safe as a production transformation.

## Required work

1. Separate:
   - model fitting data
   - calibration data
   - final test data
2. Use a strictly temporal calibration split.
3. Fit calibration only on information available before the evaluation period.
4. Compare:
   - no calibration
   - Platt scaling
   - isotonic regression
   - state-specific calibration
   - regime-specific calibration if sample sizes permit
5. Evaluate calibration with:
   - Brier
   - log loss
   - reliability curves
   - ECE
   - MCE
6. Evaluate downstream impact on:
   - xM MAE
   - xM bias
   - xP MAE
   - decision replay
7. Check especially the 0.8–1.0 probability region.

## Acceptance criteria

Calibration must improve probability quality **without unacceptable degradation in xM or decision replay**.

Do not select calibration solely because Brier/ECE improves.

---

# P6 — Freeze the Model and Run the Final 2025/26 Evaluation

## Objective

Once the candidate model is selected, perform a clean, untouched evaluation.

## Rules

The 2025/26 final evaluation must not be used to:

- tune coefficients
- select features
- select calibration parameters
- choose thresholds
- select regimes
- choose between competing model architectures

## Required metrics

### Participation

- xM MAE
- xM RMSE
- xM bias
- MAE by minute bucket
- zero-minute rate
- starter/sub accuracy
- P(appearance) calibration
- P(start) calibration

### Expected points

- xP MAE
- xP RMSE
- xP Spearman
- xP bias

### Availability classification

- precision
- recall
- F1
- false positives
- false negatives

### Decision impact

- total points
- points vs no-transfer baseline
- points vs simple xP baseline
- zero-minute starters
- zero-minute captains
- bench regret
- transfer gain

## Acceptance criteria

The final report must clearly state whether V0.9 is:

- better than V0.8,
- equivalent,
- or worse.

Do not use a single headline metric to declare success.

---

# P7 — Run the Full Decision Backtest and Closed-Loop Validation

## Objective

Determine whether the improved participation model actually improves manager decisions.

Prediction improvements alone are insufficient.

## Required experiments

Run the final candidate through the existing historical decision framework across the supported seasons.

Compare at minimum:

1. V0.8 baseline
2. V0.9 candidate
3. Simple xP baseline
4. No-transfer baseline

Evaluate:

- total points
- transfer decisions
- captain decisions
- bench decisions
- zero-minute exposure
- transfer regret
- bench regret
- decision confidence
- points gained/lost specifically due to participation predictions

## Required analysis

Identify whether the new model improves:

- avoiding rotation traps
- avoiding zero-minute starters
- avoiding zero-minute captains
- selecting reliable starters
- exploiting genuine rotation opportunities

## Acceptance criteria

The candidate must demonstrate a meaningful decision-level advantage or provide a compelling predictive improvement with no material decision degradation.

---

# P8 — V0.9 Release Gate / PR Readiness

## V0.9 is PR-ready only when all of the following are true

### Experimental validity

- [x] P0 complete
- [x] Four-way ablation is proven valid
- [x] Predictor and decision-engine effects are separable
- [x] P1 experiment manifests are reproducible

### Baseline integrity

- [x] V0.8 baseline is frozen
- [x] V0.8 regression tests pass
- [x] No accidental V0.8 behaviour changes

### Participation model

- [x] P4 candidate model evaluated
- [x] State-based participation approach compared against V0.8/V0.9
- [x] Regime layer retained and validated
- [x] No point-in-time leakage

### Calibration

- [x] Temporal calibration split implemented
- [x] High-confidence calibration errors investigated
- [x] Calibration does not materially damage xM
- [x] Calibration does not materially damage decision replay

### Final evaluation

- [x] P6 final 2025/26 evaluation completed
- [x] P7 multi-season decision backtest completed
- [x] Results documented
- [x] All reported numbers reproducible

### Engineering

- [x] Tests pass
- [x] No debug-only experiment code remains in production paths
- [x] Documentation matches actual implementation
- [x] Model version/configuration is explicit
- [x] No hidden fallback between V0.8 and V0.9 implementations

---

# Recommended Execution Order

Do **not** implement all tasks simultaneously.

Use this sequence:

```text
P0  →  P1  →  P2
             ↓
            P3
             ↓
            P4
             ↓
            P5
             ↓
            P6
             ↓
            P7
             ↓
            P8
```

More explicitly:

1. **P0:** Fix the experimental harness.
2. **P1:** Prove every ablation means what it claims.
3. **P2:** Freeze V0.8.
4. **P3:** Keep and validate regimes.
5. **P4:** Build the state-based participation candidate.
6. **P5:** Redesign temporal calibration.
7. **P6:** Freeze the candidate and evaluate 2025/26.
8. **P7:** Validate downstream decision impact.
9. **P8:** Decide PR readiness.

---

# Important Constraints for the AI Coding Agent

## Do not

- delete or weaken the V0.8 baseline;
- tune against the final 2025/26 test results;
- declare the decision engine responsible for the regression before P0;
- declare the predictor solely responsible before P0;
- optimize only for Spearman;
- optimize only for Brier/ECE;
- optimize only for xM MAE;
- remove regimes merely because they add complexity;
- replace the model with a generic ML library without first validating the experimental design;
- silently change historical data definitions;
- introduce point-in-time leakage.

## Do

- preserve reproducibility;
- make every model/version explicit;
- produce machine-readable experiment artifacts;
- report both prediction and decision metrics;
- inspect errors by participation state;
- keep temporal validation strict;
- prefer the simplest model that demonstrably improves V0.8;
- treat V0.8 as the immutable control condition.

---

# Definition of Done

V0.9 is complete when the project can answer, with reproducible evidence:

> **Does the V0.9 participation model predict player availability, starter/substitute state, and expected minutes better than V0.8, and does that improvement produce better FPL decisions without introducing leakage or calibration failures?**

Until that question is answered positively and reproducibly, **V0.9 should remain development work and should not be considered PR-ready.**
