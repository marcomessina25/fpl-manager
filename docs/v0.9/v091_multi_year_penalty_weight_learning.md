# V0.9.1 — Multi-Year Participation Risk Penalty Calibration

## Objective

Determine whether the V0.9 participation-aware lineup risk adjustment is too strong, well calibrated, too weak, or unnecessary when paired with the V0.9 learned/calibrated participation model.

The goal is **not** to decide penalty vs. no penalty from 2025/26 alone. We will learn/select a penalty strength using historical seasons and evaluate it out-of-sample.

The experiment must evaluate both:
- fantasy decision quality, and
- participation-risk outcomes such as zero-minute starters and captain failures.

## Background

The V0.9 error-attribution analysis found a valid predictor/engine interaction:

| Predictor | Engine | Points | Zero-min starters | Zero-min caps | Bench regret |
|---|---|---:|---:|---:|---:|
| V0.8 | V0.8 Unconstrained | 1948 | 50 | 3 | 273 |
| V0.9 | V0.8 Unconstrained | 2033 | 44 | 4 | 235 |
| V0.8 | V0.9 Participation-Aware | 1953 | 48 | 3 | 268 |
| V0.9 | V0.9 Participation-Aware | 2015 | 42 | 4 | 246 |

This shows that V0.9 prediction adds substantial decision value, while the current V0.9 engine extracts less value from it. It does **not** prove that the participation penalty should be removed: an explicit penalty can represent risk aversion beyond expected points.

Therefore the primary question is:

> **What penalty strength, if any, generalizes across seasons and improves the decision objective?**

---

# 1. Research Questions

### RQ1 — Does the risk penalty improve decision quality?

For each weight measure:
- total fantasy points,
- points vs. no-transfer baseline,
- points vs. current V0.9 configuration,
- transfer gain,
- bench regret,
- starting-XI regret.

### RQ2 — What does risk control cost?

Measure:
- zero-minute starters,
- zero-minute captains,
- starters who became substitutes,
- high-xP players incorrectly benched,
- expected points lost because of the penalty.

### RQ3 — Does the optimal weight generalize?

Select weights using prior seasons and evaluate them on a held-out future season. Never tune on 2025/26 and then call 2025/26 validation.

### RQ4 — Is one global weight sufficient?

Start with one scalar weight. Only investigate position-specific weights if the global result is demonstrably inadequate or systematically biased.

### RQ5 — Is the penalty redundant?

Treat redundancy as a hypothesis. Test whether V0.9 xP already captures enough participation uncertainty that an additional risk adjustment adds little or negative decision value.

---

# 2. Exact Experiment Definition

## 2.1 Verify the production formula first

Identify the exact lineup scoring formula in `decision_engine.py`.

Document:
- base xP input,
- participation adjustment,
- exact formula,
- constants,
- where the penalty is applied,
- whether lineup, bench and captain selection use it,
- whether transfer scoring uses it.

Do not rewrite the production formula from memory.

Create a parameterized pure function, conceptually:

```python
def lineup_score(xp: float, p_start: float, penalty_weight: float, ...) -> float:
    ...
```

The experimental function must reproduce current production behavior exactly at the current production weight.

---

# 3. Penalty Weight Grid

Initial sweep:

```text
w ∈ {0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30}
```

where the experimental form is conceptually:

```text
score = xP × [1 − w × (1 − P(start))]
```

If the actual production formula differs, preserve its exact mathematical structure and parameterize only the strength.

Always include:
- `w=0.00`,
- current V0.9 production weight,
- the grid values.

If the best result is at a boundary, extend the sweep in that direction rather than declaring the boundary optimal.

---

# 4. Seasons

Minimum:
- 2023/24
- 2024/25
- 2025/26

Preferred, if the existing historical infrastructure supports them reproducibly:
- 2021/22
- 2022/23

For every run:
1. use only point-in-time information,
2. preserve existing FPL/backtest rules,
3. use the same V0.9 predictor,
4. vary only penalty strength,
5. keep randomness deterministic.

---

# 5. Train / Validation / Test Protocol

Use walk-forward / leave-one-season-out selection.

Example:

```text
Target 2023/24:
  train: 2021/22, 2022/23
  test:  2023/24

Target 2024/25:
  train: 2021/22, 2022/23, 2023/24
  test:  2024/25

Target 2025/26:
  train: 2021/22, 2022/23, 2023/24, 2024/25
  test:  2025/26
```

If the repository cannot reproduce this exact protocol, document the closest valid alternative instead of silently changing methodology.

The selected weight must be frozen before running the target season.

---

# 6. Objective for Learning the Weight

Primary objective:

```text
season_total_points
```

Select the weight using aggregate normalized performance across training seasons, not one season's raw total.

If the repository already has an established normalization method, use it and document it. Otherwise a possible normalization is:

```text
normalized_points =
    (strategy_points - no_transfer_points)
    / (best_available_strategy_points - no_transfer_points)
```

Secondary diagnostics:
- zero-minute starter rate,
- zero-minute captain rate,
- bench regret,
- transfer count,
- transfer gain,
- starting-XI hit rate,
- high-xP zero-minute errors.

Do not hide these behind one aggregate score.

---

# 7. Risk / Reward Frontier

For every weight report:

```text
points
vs no-transfer
zero-minute starters
zero-minute captains
bench regret
transfers
```

Identify Pareto-dominated weights.

A weight is dominated if another weight has:
- at least as many points,
- no more zero-minute starters,
- no more bench regret,
- and is strictly better on at least one metric.

This prevents a high-point configuration from being judged without understanding its risk trade-off.

---

# 8. Required Counterfactuals

For every season compare:

### A. No penalty
`w=0`

### B. Current production penalty
Exact current V0.9 configuration.

### C. Walk-forward selected weight
The weight learned only from prior seasons.

### D. Oracle participation risk term — optional
Use actual historical participation state only for analysis.

This is **not deployable**. It measures the theoretical value remaining if participation prediction were perfect.

---

# 9. Separate Lineup and Captain Effects

Analyze independently:

## Starting XI
- zero-minute starters,
- points lost from zero-minute starters,
- high-xP players benched,
- starting-XI regret.

## Captain
- zero-minute captains,
- captain points lost,
- captain decisions changed by penalty,
- P(start) of selected captain.

If captain selection uses different logic, do not assume the lineup penalty fixes captain failures.

---

# 10. Player-Level Changed-Decision Ledger

For every decision changed by penalty weight, record:

```text
season
gameweek
player
position
price
xP
P(start)
actual_state
actual_minutes
selected_at_w=0
selected_at_current
selected_at_candidate
actual_points
decision_delta
```

Classify each changed decision:

```text
PENALTY_HELPED
PENALTY_HURT
NEUTRAL
```

`PENALTY_HELPED` means the penalty avoided a player who ultimately delivered zero or materially fewer minutes/points than the alternative.

`PENALTY_HURT` means the penalty benched a player who ultimately delivered more value than the selected alternative.

Define and document the threshold for `NEUTRAL`.

---

# 11. Weight Sensitivity

For each season generate:

```text
weight → total points
weight → zero-minute starters
weight → bench regret
```

Calculate neighboring-weight differences.

Determine:
- smoothness,
- plateau vs sharp optimum,
- season-to-season movement,
- location of current production weight,
- whether the optimum is robust or fragile.

A broad stable plateau is preferable to a single-point historical optimum.

---

# 12. Generalization Tests

After walk-forward selection evaluate:

### Season generalization
Does the learned weight outperform `w=0` and the current production weight on held-out seasons?

### Position generalization
Break down:
- GK
- DEF
- MID
- FWD

Do not create separate position weights unless evidence justifies the added complexity.

### Price-tier generalization
Use existing project tiers, at minimum:
- budget,
- mid,
- premium.

### Participation-regime generalization
Use the existing V0.9 regime definitions where available, such as:
- stable starter,
- rotation,
- fringe,
- substitute/cameo-oriented.

---

# 13. Stability Statistics

For each tested/selected weight calculate:
- mean points,
- median points,
- standard deviation,
- minimum season result,
- maximum season result,
- mean zero-minute starter rate,
- standard deviation of zero-minute starter rate.

Where practical, add bootstrap confidence intervals over gameweeks or decision events.

Do not claim statistical significance unless the analysis actually supports it.

---

# 14. Leakage Controls

The following are prohibited:
- selecting the final weight using the target season,
- fitting the penalty with future minutes,
- using future player/team fingerprints,
- using actual future participation to tune production weights,
- changing the V0.9 predictor between penalty configurations,
- changing transfer rules,
- changing backtest horizons,
- using oracle information in deployable configurations.

Every production result must remain point-in-time valid.

---

# 15. Reproducibility

Create a deterministic repository-native experiment entry point, for example:

```bash
python -m src.experiments.penalty_weight_sweep
```

Use the project's existing conventions if different.

The experiment must:
1. enumerate penalty weights,
2. enumerate target seasons,
3. run identical backtests,
4. save raw per-season results,
5. save aggregate results,
6. save changed-decision attribution,
7. save walk-forward selected weights,
8. generate a Markdown report.

Recommended outputs:

```text
reports/
  v091_penalty_weight_sweep/
    summary.md
    weight_results.csv
    walk_forward_results.csv
    decision_attribution.csv
    season_results/
      2023_24.csv
      2024_25.csv
      2025_26.csv
```

Follow repository conventions where an existing structure already exists.

---

# 16. Acceptance Criteria

## P0 — Formula verification
- [ ] Exact production penalty formula identified.
- [ ] Current production weight identified.
- [ ] Parameterized implementation reproduces production behavior.
- [ ] Unit tests cover `w=0`, current weight and intermediate values.

## P1 — Sweep
- [ ] At least 0.00–0.30 in 0.05 increments.
- [ ] Current production weight included explicitly.
- [ ] Boundary extended when necessary.

## P2 — Multi-season
- [ ] At least 2023/24, 2024/25, 2025/26.
- [ ] Earlier seasons included if reproducible.
- [ ] Identical decision/backtest rules.

## P3 — Walk-forward
- [ ] Target season never used for weight selection.
- [ ] Selected weights frozen before test.
- [ ] Training and test results reported separately.
- [ ] No leakage.

## P4 — Decision impact
- [ ] Total points.
- [ ] Transfer gain.
- [ ] Zero-minute starters.
- [ ] Zero-minute captains.
- [ ] Bench regret.
- [ ] High-xP decision errors.
- [ ] Player-level changed-decision ledger.

## P5 — Robustness
- [ ] Per-season results.
- [ ] Mean/median/std.
- [ ] Sensitivity curves.
- [ ] Position breakdown.
- [ ] Price-tier breakdown.
- [ ] Participation-regime breakdown.

## P6 — Release gate

The final report must classify the evidence as exactly one of:

1. **Remove penalty** — `w=0` consistently wins without unacceptable risk increase.
2. **Reduce penalty** — a smaller non-zero weight consistently beats the current value.
3. **Keep current penalty** — current weight remains competitive and stable.
4. **Increase penalty** — larger weights consistently improve decisions.
5. **No stable global weight** — results vary materially and require a more sophisticated approach.

Do not select an outcome from one season.

---

# 17. Final Report

Required sections:

## Executive Summary
- selected weights by target season,
- out-of-sample point impact,
- risk impact,
- current-weight comparison,
- stability assessment.

## Weight Sweep

| Weight | Mean points | Median | Std | Zero-min starters | Zero-min caps | Bench regret |
|---:|---:|---:|---:|---:|---:|---:|

## Walk-Forward Results

| Target season | Training seasons | Selected weight | Test points | w=0 points | Current-weight points |
|---|---|---:|---:|---:|---:|

## Risk / Reward Frontier

Points versus zero-minute starters, with Pareto-dominated weights identified.

## Decision Attribution

How often the penalty:
- helped,
- hurt,
- had negligible impact.

## Segment Analysis
- position,
- price tier,
- participation regime.

## Conclusion

Answer:

> **What penalty strength should V0.9.1 use, based on multi-season out-of-sample evidence?**

Clearly distinguish demonstrated results, interpretation, and remaining uncertainty.

---

# 18. Implementation Order

### Phase 1 — Instrumentation
1. Locate exact production penalty.
2. Extract/parameterize it.
3. Add equivalence tests.
4. Add configuration/CLI weight.

### Phase 2 — Reproduction
5. Reproduce the existing 2025/26 V0.8/V0.9 counterfactual.
6. Verify `w=0` matches the unconstrained V0.9-predictor result.
7. Verify current weight matches the existing V0.9 result.
8. Stop if reproduction fails; fix methodology before sweeping.

### Phase 3 — Sweep
9. Run initial grid.
10. Extend boundary when required.
11. Generate season-level curves.

### Phase 4 — Walk-forward
12. Implement forward weight selection.
13. Freeze selected weights.
14. Run complete held-out backtests.

### Phase 5 — Attribution
15. Build changed-decision ledger.
16. Classify helped/hurt/neutral.
17. Separate lineup and captain effects.
18. Analyze high-xP/high-P(start) decisions.

### Phase 6 — Robustness
19. Position analysis.
20. Price-tier analysis.
21. Participation-regime analysis.
22. Stability analysis.

### Phase 7 — Release decision
23. Compare learned, current and zero-penalty configurations.
24. Apply acceptance criteria.
25. Generate final report.
26. Only then modify the production penalty.

---

## Non-Goals

This experiment does **not**:
- redesign the V0.9 participation predictor,
- retrain xP,
- redesign transfer logic,
- redesign captain logic unless separately justified,
- introduce a neural model,
- optimize many hyperparameters simultaneously.

The scope is deliberately narrow:

> **Learn whether and how strongly lineup selection should penalize participation uncertainty when using the V0.9 predictor.**
