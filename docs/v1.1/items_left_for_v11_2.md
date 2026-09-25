# Items Left for V1.1.2

## Purpose

V1.1 has now reached a strong implementation state across the three intended pillars:

1. Strategic squad engine
2. Full GUI integration
3. End-to-end ML / decision-system analysis

This document defines the **final hardening pass between the current V1.1 PR state and a clean V1.1 release**.

The goal of V1.1.2 is deliberately narrow:

> **Do not expand the product scope. Make the current V1.1 implementation internally consistent, experimentally defensible, reproducible, and honest about what its results demonstrate.**

V1.1.2 should not introduce a new prediction model, new LLM provider, new strategic optimization paradigm, or major GUI feature.

It should fix the remaining issues in the current PR, regenerate the analytical artifacts from the final code, and establish the quantitative baseline that V1.2 can safely build upon.

---

# Executive Summary

The remaining work is concentrated in six areas:

| Priority | Area | Objective |
|---|---|---|
| P0.1 | Baseline legality | Ensure every experimental baseline is a legal FPL squad |
| P0.2 | Factorial design | Remove predictor contamination from the starting-state factor |
| P0.3 | Report regeneration | Ensure committed reports correspond exactly to final code |
| P0.4 | Scientific claims | Remove conclusions stronger than the data supports |
| P0.5 | Horizon-value invariant | Explain and test suspicious strategic horizon xP values |
| P0.6 | Provenance/fallback | Make every experiment and fallback fully traceable |

After these, perform the P1 validation and release gate.

---

# P0 — Merge / Release Blockers

## P0.1 — Make all baseline starting squads strictly legal

### Problem

The baseline initial-squad construction can produce a candidate without explicitly enforcing the full FPL budget constraint.

This is unacceptable because baseline squads are used as comparison arms in the V1.1 evaluation.

A baseline must be a valid FPL squad before it can be compared with a strategic squad.

### Required validity

Every baseline must satisfy:

```text
15 players
2 goalkeepers
5 defenders
5 midfielders
3 forwards

≤ 3 players per club

total cost ≤ available budget

all required player eligibility constraints
```

### Tasks

- [x] Audit `generate_baseline_initial_squad()`.
- [x] Ensure the budget is a hard constraint, not merely reported afterward.
- [x] Ensure the baseline is passed through the same squad legality validator used elsewhere.
- [x] Fail explicitly if a baseline cannot be constructed.
- [x] Never silently clip negative bank to zero.
- [x] Add a test with an intentionally over-budget candidate.
- [x] Add a test at exactly the budget boundary.
- [x] Add a test where the naïve uniform positional template is impossible under the budget.
- [x] Add a test for club-limit violations.
- [x] Add a test for position-count violations.

### Acceptance criteria

Every baseline used by:

- factorial analysis
- starting-state backtests
- multi-season summaries
- strategic profile comparisons

passes the canonical squad validator.

No report contains results from an illegal baseline.

---

# P0.2 — Make the factorial starting-state factor independent of the predictor factor

## Problem

The current 2×2×2 experiment is conceptually:

```text
Starting State
×
Predictor
×
Decision Engine
```

but the strategic starting state is generated using the V1.0.1 / current predictor.

This means the starting-state factor already contains information from the predictor factor.

Therefore the experiment does not cleanly represent three independent interventions.

### Preferred solution

Construct the starting-state policies independently of the downstream predictor being evaluated.

For example:

```text
Starting-state factor A:

A0 = baseline starting squad
A1 = strategic starting squad
```

where both A0 and A1 are generated from a frozen, explicitly declared information set.

Then evaluate:

```text
A0 / A1
×
Predictor P0 / P1
×
Decision Engine D0 / D1
```

### Tasks

- [x] Define the information set used to construct A0/A1.
- [x] Freeze the starting-state construction predictor/version.
- [x] Ensure the downstream predictor factor can differ from the construction predictor.
- [x] Record construction predictor separately from evaluation predictor.
- [x] Add provenance:
  - `starting_state_policy`
  - `starting_state_predictor_version`
  - `evaluation_predictor_version`
  - `decision_engine_version`
- [x] Add a synthetic test proving the factors can vary independently.
- [x] Update the factorial report methodology.

### Acceptance criteria

The report can explicitly distinguish:

```text
predictor used to construct the starting state
```

from:

```text
predictor used to evaluate downstream decisions
```

and does not describe them as independent when they are not.

---

# P0.3 — Regenerate every V1.1 report from the final implementation

## Problem

The latest code contains analytical improvements that are not necessarily reflected in committed reports.

Examples include:

- full factorial interactions
- improved failure handling
- revised horizon semantics
- heuristic error diagnostics
- exact-reference comparisons

A repository release must not contain reports generated by an older analytical implementation.

### Tasks

- [x] Delete or archive stale V1.1 analytical outputs where appropriate.
- [x] Run the final report-generation pipeline from scratch.
- [x] Regenerate:
  - starting-state ablation
  - strategic profile analysis
  - initial-squad backtests
  - Wildcard backtests
  - multi-season summary
  - error diagnostics
  - horizon sensitivity
  - constraint sensitivity
  - heuristic-vs-exact analysis
- [x] Verify every report's generation metadata.
- [x] Verify every report identifies the current code/model version.
- [x] Verify no report contains conclusions from the previous implementation.
- [x] Run a clean-environment report generation if practical.

### Acceptance criteria

For every committed V1.1 report:

```text
report inputs
=
final V1.1 implementation
=
documented methodology
```

No stale report survives the release.

---

# P0.4 — Rewrite analytical conclusions to match the observed data

## Problem

The current multi-season results contain substantial cross-season variation.

For example, the observed strategic-minus-baseline differences include both negative and positive seasons, with one recent season contributing a particularly large positive difference.

Therefore wording such as:

```text
"decisively demonstrates"
"consistently improves"
"independent positive effect"
```

is too strong unless supported by the regenerated analysis.

### Required principle

Reports must distinguish:

```text
observed result
```

from:

```text
interpretation
```

and from:

```text conclusion supported by the experiment
```

### Tasks

- [x] Search all V1.1 reports for unsupported certainty.
- [x] Remove "consistently" unless every relevant season supports it.
- [x] Remove "decisively demonstrates" unless the statistical/evidentiary design supports it.
- [x] Remove "independent effect" unless factorial interactions support that interpretation.
- [x] Report sample size for each comparison.
- [x] Report per-season results before aggregate means.
- [x] Report variation across seasons.
- [x] Report failed/missing experiments.
- [x] Distinguish exploratory findings from validated conclusions.

### Preferred style

Instead of:

```text
Strategic squad construction decisively improves downstream outcomes.
```

prefer:

```text
Across the evaluated seasons, strategic starting-state construction produced
a mean difference of X points versus the baseline, with substantial
cross-season variation. The result provides evidence of a starting-state
effect under the evaluated methodology, but does not establish consistent
improvement across all seasons.
```

Use the actual regenerated values.

---

# P0.5 — Resolve and test the suspicious horizon-xP values

## Problem

Some strategic reports show very large differences in `horizon_xp` between candidates generated from the same player pool and horizon.

For example, values around:

```text
~345
```

and others around:

```text
~92
```

appear in the existing artifacts.

This may be legitimate if the objectives intentionally define fundamentally different value quantities, but it is suspicious enough that it must be explained.

### Required investigation

For every strategic candidate:

```text
stored horizon_xp
```

must equal an independent recomputation:

```text
Σ selected-player GW-level xP
```

using the exact same horizon.

### Tasks

- [x] Identify the origin of every reported `horizon_xp`.
- [x] Independently recompute horizon xP from selected players.
- [x] Compare stored vs recomputed values.
- [x] Determine whether profile-specific scaling is intentional.
- [x] If intentional, rename the metric so it is not confused with raw horizon xP.
- [x] If accidental, fix the calculation.
- [x] Add a regression test.
- [x] Add a candidate-level invariant check.

### Acceptance criteria

For every candidate:

```text
stored_horizon_xp == independently_recomputed_horizon_xp
```

within an explicitly documented floating-point tolerance.

A strategic objective may differ between profiles, but raw horizon xP must have a single unambiguous definition.

---

# P0.6 — Complete provenance and fallback transparency

## Problem

V1.1 needs to be a reproducible research platform.

The final result must make it possible to determine exactly:

```text
what was run
with what data
using what model
using what configuration
```

### Required provenance

At minimum record:

```text
experiment_id
season
gameweek
decision_deadline
starting_state_policy
starting_state_predictor_version
evaluation_predictor_version
decision_engine_version
strategic_solver_version
objective
horizon
constraints
random_seed
configuration_hash
dataset/version identifier
```

### Fallback

If interactive V1.1 retains fallback behavior, record:

```text
fallback_used
fallback_reason
requested_engine
actual_engine
```

### Tasks

- [x] Add missing provenance fields.
- [x] Add configuration hash.
- [x] Add deterministic experiment identifier.
- [x] Add dataset/version identifier.
- [x] Record fallback metadata.
- [x] Ensure backtests never silently fallback.
- [x] Add serialization/replay test.

### Acceptance criteria

A stored experiment result can be traced to:

```text
code version
data version
configuration
solver
predictor
starting-state policy
decision engine
```

without inference or guesswork.

---

# P1 — Strongly Recommended Hardening

## P1.1 — Validate factorial decomposition against synthetic ground truth

Construct a synthetic 2×2×2 dataset where the true effects are known.

Example:

```text
main effect A = 10
main effect B = 5
main effect C = 2

AB = 3
AC = -1
BC = 4

ABC = 7
```

Verify that the implementation recovers the known values exactly.

### Acceptance criteria

Residual:

```text
max reconstruction error < 1e-6
```

and all synthetic effects match expected values.

---

## P1.2 — Add construction/evaluation predictor provenance to factorial reports

Every factorial cell should explicitly show:

```text
starting-state construction predictor
evaluation predictor
decision engine
```

This prevents future confusion when multiple model versions exist.

---

## P1.3 — Strengthen baseline comparisons

For every baseline type report:

- legality
- total cost
- remaining bank
- squad value
- player count
- position counts
- club counts
- objective value.

Do not compare a strategic squad with an invalid or differently constrained baseline.

---

## P1.4 — Add candidate horizon-xP invariant tests

For every generated strategic candidate:

```text
independent_xp_sum(candidate)
==
candidate.horizon_xp
```

Test:

- horizon 1
- horizon 2
- horizon 3
- horizon 5
- horizon 8

and multiple strategic profiles.

---

## P1.5 — Clarify "walk-forward" terminology

Only use:

```text
walk-forward
```

if model/profile selection genuinely uses only earlier historical data before each evaluated period.

Otherwise use:

```text
multi-season historical evaluation
```

or:

```text
multi-season out-of-sample evaluation
```

as appropriate.

### Tasks

- [ ] Audit actual temporal training/selection behavior.
- [ ] Rename reports if necessary.
- [ ] Document temporal boundaries.
- [ ] Avoid implying a methodology that the experiment does not implement.

---

## P1.6 — Expand heuristic-vs-exact evaluation

For bounded synthetic candidate pools:

```text
exact optimum
vs
1-opt
vs
2-opt
```

Report:

- mean gap
- median gap
- max gap
- 95th percentile gap
- exact-match rate
- runtime.

Separate:

```text
correctness validation
```

from:

```text
heuristic quality measurement
```

---

## P1.7 — Add repeated randomized synthetic trials

A single synthetic example is insufficient to characterize heuristic quality.

Generate many bounded random problem instances.

For each:

```text
exact
1-opt
2-opt
gap
runtime
```

### Acceptance criteria

The report provides empirical evidence about heuristic behavior without claiming a global guarantee.

---

# P2 — GUI Finalization

## P2.1 — Make fallback state visible

If V1.1 falls back to V1.0 in interactive mode, show:

```text
V1.1 strategic solver failed
Fallback used: V1.0
Reason: ...
```

Do not make fallback indistinguishable from normal V1.1 output.

---

## P2.2 — Show construction and evaluation provenance where relevant

For strategic candidates, display:

- strategic profile
- objective
- horizon
- solver
- exact/heuristic status
- construction predictor
- evaluation predictor where relevant
- constraints.

---

## P2.3 — Verify final applied squad identity

After:

```text
Generate
→ modify
→ re-optimize
→ Apply
```

the squad sent to the planner must exactly match the squad displayed as selected.

Add a regression test based on player IDs.

---

# P3 — Research Quality

## P3.1 — Starting-state regret

For each historical decision point:

```text
chosen starting state
vs
best feasible starting state under information available at deadline
```

Measure:

```text
regret
```

without using future information in construction.

Future information may only be used when evaluating realized outcomes.

---

## P3.2 — Multiple optimum / near-optimum analysis

For each exact-reference problem where feasible, measure:

```text
number of exact optima
solutions within 0.1%
solutions within 0.5%
solutions within 1%
```

Compare their:

- future flexibility
- ownership
- fixture exposure
- transfer burden
- risk characteristics.

---

## P3.3 — Constraint sensitivity

Measure the marginal effect of:

- budget
- club limits
- position structure
- locks
- exclusions
- must-have
- must-avoid
- structural preferences
- horizon
- risk profile.

Distinguish:

```text
objective impact
```

from:

```text
squad composition impact
```

---

## P3.4 — Horizon sensitivity

Run:

```text
1 GW
2 GW
3 GW
5 GW
8 GW
```

and report:

- squad overlap
- objective
- realized points
- regret
- transfer burden
- stability.

---

## P3.5 — Strategy-profile sensitivity

Compare strategic profiles descriptively.

Do not produce an overall winner/ranking.

Report:

- squad composition differences
- objective differences
- realized outcomes
- risk metrics
- flexibility
- ownership
- future transfer requirements.

---

# P4 — Final Validation

## P4.1 — Full clean test suite

Run:

```text
unit tests
integration tests
regression tests
exact-reference tests
factorial tests
GUI tests
```

No unexpected failures.

---

## P4.2 — Clean report regeneration

Use a clean environment where practical.

Verify:

```text
code
→ data
→ analysis
→ report
```

works without relying on stale generated artifacts.

---

## P4.3 — Repository consistency audit

Verify consistency across:

- package version
- GUI version
- model registry
- roadmap
- changelog
- V1.1 documentation
- report metadata
- PR description
- release notes.

---

## P4.4 — Search for stale V1.0/V1.1 claims

Search documentation and reports for:

```text
decisively
consistently
independent
walk-forward
optimal
globally optimal
causal
proves
demonstrates
```

Review each occurrence manually.

The objective is not to remove strong language mechanically; it is to ensure every claim is supported by the actual methodology.

---

# V1.1.2 Release Gate

V1.1.2 is ready when all of the following are true.

## Engine

- [x] Every baseline is legal.
- [x] Horizon xP has one unambiguous definition.
- [x] Candidate horizon xP has an independent invariant test.
- [x] Exact and heuristic solvers use the same feasible space.
- [x] Exact reference remains independently implemented.
- [x] Heuristic quality is empirically measured.

## Factorial analysis

- [x] Starting-state construction information set is explicit.
- [x] Construction predictor is separated from evaluation predictor.
- [x] All main effects are calculated.
- [x] All pairwise interactions are calculated.
- [x] Three-way interaction is calculated.
- [x] Synthetic decomposition test passes.
- [x] Missing cells are explicit.

## Historical evaluation

- [x] Baselines are legal.
- [x] PIT inputs are audited.
- [x] Temporal terminology is accurate.
- [x] Multi-season results are reported per season.
- [x] Aggregate conclusions reflect cross-season variation.

## Reporting

- [x] All reports regenerated.
- [x] No stale reports remain.
- [x] Report metadata matches current code.
- [x] Unsupported claims removed.
- [x] Diagnostic attribution is clearly labelled heuristic.
- [x] No causal language without counterfactual methodology.

## Reproducibility

- [x] Experiment ID recorded.
- [x] Code/version recorded.
- [x] Dataset version recorded.
- [x] Configuration hash recorded.
- [x] Predictor versions recorded.
- [x] Starting-state construction predictor recorded.
- [x] Decision-engine version recorded.
- [x] Solver version recorded.
- [x] Random seed recorded where relevant.
- [x] Fallbacks recorded.

## GUI

- [x] Solver status visible.
- [x] Fallback status visible.
- [x] Candidate provenance visible.
- [x] Applied squad exactly matches selected squad.

---

# Final Definition of Done

V1.1.2 is complete when the repository can honestly make the following statement:

> **V1.1 provides a strategic starting-squad engine, an integrated GUI workflow, and an end-to-end historical evaluation framework. V1.1.2 hardens that implementation so that baseline comparisons are legal, experimental factors are explicitly defined, historical analyses are reproducible, reports are generated from the final implementation, and conclusions are limited to what the evidence supports.**

The release should leave the project with a clean quantitative foundation:

```text
V1.0
Trustworthy decision engine
        ↓
V1.1
Strategic starting-state engine
        ↓
V1.1.2
Validated + reproducible quantitative baseline
        ↓
V1.2
LLM / AI provider experimentation
```

The purpose of V1.1.2 is therefore **not to add another major feature**.

Its purpose is to make sure that when V1.2 asks:

```text
"Does AI/LLM assistance improve the system?"
```

we have a trustworthy answer to:

```text
"What is the performance of the quantitative system
we are comparing it against?"
```
