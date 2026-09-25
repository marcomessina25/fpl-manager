# Items Left for V1.1

## Purpose

This document is the remaining hardening and validation work identified from the review of PR #14.

V1.1 already contains the intended three major pillars:

1. **Strategic squad engine**
2. **Full GUI integration**
3. **End-to-end ML / decision-system analysis**

The goal of this checklist is **not** to redesign V1.1. The architecture is already in place. The remaining work is to make the implementation scientifically trustworthy, deterministic, transparent, and safe to use as the foundation for V1.2.

---

# P0 — Must Fix Before V1.1 Merge

These items should block merging PR #14.

---

## P0.1 — Fix strategic horizon / xP aggregation semantics

### Problem

The historical strategic-player loader aggregates expected points across the selected horizon, while downstream strategic-value logic also applies the horizon length.

This risks effectively multiplying an already horizon-aggregated value by the horizon again.

The internal representation must have one unambiguous meaning.

### Required outcome

Choose and document one convention.

Preferred convention:

```text
player expected_points = expected points for one specific GW
```

Strategic evaluation then explicitly aggregates:

```text
strategic_xp(player, horizon)
    = Σ expected_points(player, GW)
```

Do not multiply an already horizon-aggregated value by `horizon` again.

### Tasks

- [x] Audit `load_historical_strategic_players()`.
- [x] Audit `compute_player_strategic_value()`.
- [x] Audit strategic objective aggregation.
- [x] Audit multi-GW candidate evaluation.
- [x] Introduce explicit naming where necessary:
  - `gw_xp`
  - `horizon_xp`
  - `strategic_value`
- [x] Add tests for horizon 1, 2, 5, and 8.
- [x] Verify that doubling the horizon does not accidentally multiply an already aggregated value.
- [x] Add a regression test with manually known player projections.
- [x] Document the aggregation convention in the strategic-engine documentation.

### Acceptance criteria

For a player with:

```text
GW1 = 5
GW2 = 6
GW3 = 7
GW4 = 8
GW5 = 9
```

the five-GW expected-point contribution must be:

```text
35
```

not:

```text
175
```

unless a clearly documented alternative objective intentionally defines that quantity.

---

## P0.2 — Remove silent V1.1 → V1.0 fallback in strategic initialization

### Problem

The V1.1 strategic initialization path can catch an exception and silently return the V1.0 initialization result.

This can cause a backtest to appear to evaluate V1.1 while actually evaluating V1.0 for some historical cases.

That is unacceptable for scientific evaluation.

### Required outcome

Strategic initialization failures must be observable.

Preferred behavior for research/backtesting:

```text
V1.1 strategic initialization fails
        ↓
explicit failure
        ↓
recorded reason
        ↓
test/backtest can fail or exclude the run explicitly
```

If production fallback is retained, it must be explicitly recorded.

### Tasks

- [x] Remove unconditional silent fallback.
- [x] Introduce an explicit strategic-initialization exception/result state.
- [x] If fallback is retained for interactive GUI use, expose:
  - `fallback_used`
  - `fallback_reason`
  - requested version
  - actual solver/version used.
- [x] Ensure backtesting never silently falls back.
- [x] Add tests for solver failure.
- [x] Add a backtest assertion that requested V1.1 and executed V1.1 are identical.

### Acceptance criteria

No V1.1 backtest may silently contain V1.0 initialization.

Every fallback must be explicitly represented in the result/provenance.

---

## P0.3 — Make the 2×2×2 factorial analysis a real factorial analysis

### Problem

The V1.1 analysis evaluates:

```text
Starting State
× Predictor
× Decision Engine
```

but currently emphasizes main effects.

A three-factor experiment also contains pairwise and three-way interactions.

Therefore a main-effect difference alone cannot establish that the starting-state effect is independent of the predictor or decision engine.

### Required outcome

Report:

```text
Starting-state main effect
Predictor main effect
Decision-engine main effect

Starting-state × Predictor
Starting-state × Decision-engine
Predictor × Decision-engine

Starting-state × Predictor × Decision-engine
```

### Tasks

- [x] Implement complete factorial cell extraction.
- [x] Calculate all main effects.
- [x] Calculate all pairwise interactions.
- [x] Calculate the three-way interaction.
- [x] Verify the decomposition mathematically.
- [x] Add tests using a synthetic 2×2×2 dataset with known effects.
- [x] Remove or rewrite language claiming that an effect is "independent" unless supported by the interaction analysis.
- [x] Report sample counts for every cell.
- [x] Report missing/failed cells explicitly.

### Acceptance criteria

The report can distinguish:

```text
main effect
```

from:

```text
interaction effect
```

and never describes a main effect as independent without supporting interaction analysis.

---

## P0.4 — Correctly characterize error attribution

### Problem

The current `run_error_attribution_analysis()` contains useful diagnostics, but some classifications are heuristic rather than genuine counterfactual attribution.

Examples include fixed point assignments and assigning some transfer/bench losses to a single causal category.

These are useful diagnostics but should not be presented as mathematically identified causal contributions.

### Required outcome

Either:

**A. Implement genuine counterfactual attribution**

or:

**B. Rename and document the current system as heuristic error diagnostics.**

For V1.1, option B is acceptable if implemented honestly.

### Recommended terminology

```text
heuristic_error_diagnostics
```

or:

```text
decision_error_diagnostics
```

rather than:

```text
counterfactual_error_attribution
```

unless the underlying counterfactual framework is actually implemented.

### Tasks

- [x] Audit all error-attribution categories.
- [x] Identify hard-coded point allocations.
- [x] Identify overlapping categories.
- [x] Rename current diagnostics if they are heuristic.
- [x] Document category definitions.
- [x] Ensure categories are not described as causal attribution.
- [x] Add tests for category assignment.
- [x] Add explicit "heuristic" metadata to the analysis result.
- [x] If genuine counterfactual attribution is implemented, document the counterfactual baseline for every category.

### Acceptance criteria

The report must clearly distinguish:

```text
observed loss
heuristic diagnostic
counterfactual estimate
```

These must never be presented as interchangeable concepts.

---

## P0.5 — Align exact-reference solver feasibility with production solver

### Problem

The exact strategic reference solver must evaluate the same feasible solution space as the production strategic solver.

Any discrepancy in:

- availability
- locked players
- exclusions
- budget
- position limits
- club limits
- squad size
- other hard constraints

can make the exact solver an invalid oracle.

### Tasks

- [x] Compare production and exact-reference eligibility filtering.
- [x] Compare all hard constraints.
- [x] Ensure unavailable players are handled consistently.
- [x] Ensure locked players are handled consistently.
- [x] Ensure exclusions are handled consistently.
- [x] Ensure objective terms are equivalent.
- [x] Keep search algorithms independent.
- [x] Add adversarial exact-reference tests.

### Acceptance criteria

For every bounded synthetic test case:

```text
production solver feasible space
==
exact reference feasible space
```

while the search algorithms remain independently implemented.

---

# P1 — Strongly Recommended Before Merge

These items should ideally be completed in the same V1.1 hardening cycle.

---

## P1.1 — Measure heuristic optimality gap against exact oracle

### Goal

The exact strategic solver should be used not only to verify correctness but to quantify the quality of the production heuristic.

For bounded synthetic problems:

```text
exact optimum = X
heuristic result = Y

optimality gap = X - Y
relative gap = (X - Y) / |X|
```

### Tasks

- [x] Generate bounded synthetic strategic pools.
- [x] Run exact reference.
- [x] Run production heuristic.
- [x] Calculate absolute optimality gap.
- [x] Calculate relative optimality gap.
- [x] Report mean gap.
- [x] Report median gap.
- [x] Report maximum gap.
- [x] Report 95th percentile gap.
- [x] Include adversarial local-search cases.
- [x] Test 1-opt and 2-opt separately.

### Acceptance criteria

V1.1 reports empirical heuristic quality without claiming a global optimality guarantee.

---

## P1.2 — Do not silently drop failed strategic profiles

### Problem

`generate_strategic_candidates()` can skip a failed strategic profile.

That makes an incomplete experiment look like a complete one.

### Tasks

- [x] Record every requested profile.
- [x] Record success/failure.
- [x] Record failure reason.
- [x] Preserve successful candidates.
- [x] Surface failed profiles in GUI.
- [x] Include failures in backtest reports.
- [x] Add regression test.

### Example result

```json
{
  "requested_profiles": [
    "balanced",
    "safe",
    "ceiling",
    "differential"
  ],
  "successful_profiles": [
    "balanced",
    "safe",
    "differential"
  ],
  "failed_profiles": {
    "ceiling": "No feasible squad under supplied constraints"
  }
}
```

---

## P1.3 — Complete the point-in-time historical audit

### Goal

Ensure V1.1 historical strategic construction uses only information available at the historical decision deadline.

### Audit areas

- [x] Player projections.
- [x] Player prices.
- [x] Player availability.
- [x] Fixtures.
- [x] Team strength.
- [x] Ownership.
- [x] Form.
- [x] News/injury signals.
- [x] Historical squad state.
- [x] Chip state.
- [x] Transfer state.
- [x] Any feature introduced by V1.1.

### Special attention

Audit historical Wildcard reconstruction around the actual decision deadline.

### Acceptance criteria

Every historical input has an explicit point-in-time definition.

No future information is used to construct the starting state.

---

## P1.4 — Add explicit missing-cell handling to factorial experiments

### Problem

Backtesting experiments can fail for individual combinations.

A missing cell must not silently change the experimental population.

### Tasks

- [x] Record requested experiment cells.
- [x] Record completed cells.
- [x] Record failed cells.
- [x] Record sample size per cell.
- [x] Refuse aggregate comparison when required cells are missing.
- [x] Allow exploratory partial results only when clearly marked.

---

## P1.5 — Add deterministic replay identifiers

### Goal

Every V1.1 experiment should be reproducible.

### Tasks

Record:

```text
season
GW
decision deadline
starting state
candidate pool identifier
objective
constraints
solver
solver version
predictor version
decision-engine version
random seed
configuration hash
dataset/version identifier
```

### Acceptance criteria

A historical experiment can be replayed from its recorded provenance.

---

## P1.6 — Validate the strategic objective independently

Create hand-constructed scenarios where the expected optimum is obvious.

Examples:

1. Higher xP player should beat lower xP player.
2. Fixture advantage should matter only when enabled.
3. Locked player should remain in squad.
4. Excluded player must never appear.
5. Budget constraint must be respected.
6. Club constraint must be respected.
7. Position constraint must be respected.
8. Horizon extension must change value only through additional GWs.
9. Preference bonus must be measurable.
10. A structural preference must not override a hard constraint.

---

# P2 — GUI / Product Hardening

The GUI architecture is already in place. These tasks are integration and transparency improvements.

---

## P2.1 — Show solver failures explicitly

The GUI must distinguish:

```text
No feasible squad
```

from:

```text
Solver failed
```

from:

```text
Profile unavailable
```

from:

```text
Historical data unavailable
```

Do not display a generic empty candidate list.

---

## P2.2 — Show exact vs heuristic status everywhere

Whenever a candidate is displayed, expose:

```text
Algorithm
Exact/global optimum status
Objective
Horizon
Constraints
Projection version
```

This should be consistent between:

- Strategic Studio
- candidate comparison
- squad detail
- planner
- history
- saved decisions.

---

## P2.3 — Show fallback status if fallback remains

If any fallback remains in interactive mode, the GUI should display it.

Example:

```text
Strategic solver failed.
Fallback: V1.0 initialization.
Reason: <reason>
```

The user must never mistake fallback output for V1.1 output.

---

## P2.4 — Verify optimizer → human → optimizer workflow

Test:

```text
Generate
→ Lock player
→ Exclude player
→ Add preference
→ Re-optimize
→ Compare delta
→ Apply
→ Send to planner
```

Acceptance criteria:

- locks persist
- exclusions persist
- objective persists
- horizon persists
- provenance persists
- final applied squad exactly matches displayed squad.

---

## P2.5 — Verify human → optimizer workflow

Test starting from a manually constructed squad:

```text
Manual squad
→ seed optimizer
→ optimize remaining positions
→ compare
→ apply
```

No hidden changes to manually selected players should occur.

---

# P3 — ML / Research Hardening

These tasks can continue after the P0 merge gate if needed, but should be completed before declaring V1.1 research complete.

---

## P3.1 — Separate "ML analysis" from "ML model development"

Documentation should distinguish:

```text
ML / decision-system evaluation
```

from:

```text
new predictive-model training
```

V1.1 primarily evaluates the interaction between:

```text
starting state
+
predictor
+
decision engine
```

The existing V0.9.1-frozen quantitative predictor remains the baseline unless a new model is explicitly introduced.

---

## P3.2 — Add starting-state quality metrics

For every historical starting squad, calculate:

- projected points
- realized points
- regret
- opportunity cost
- bench points
- captain contribution
- availability loss
- transfer requirements
- future flexibility
- chip compatibility
- budget remaining
- squad value
- fixture exposure
- concentration / team exposure.

---

## P3.3 — Add strategic regret analysis

For each historical starting state:

```text
chosen starting state
vs
best feasible starting state under information available at deadline
```

Report:

```text
starting-state regret
```

without using future information to construct the decision.

Future information may only be used to evaluate realized outcomes after the decision.

---

## P3.4 — Analyze multiple optimal and near-optimal squads

Do not assume one unique optimum.

Report:

```text
number of exact optima
number within 0.1% of optimum
number within 0.5%
number within 1%
```

Study whether different near-optimal squads have materially different:

- flexibility
- risk
- ownership
- fixture exposure
- future transfer requirements.

---

## P3.5 — Constraint sensitivity analysis

For each constraint:

```text
baseline
constraint enabled
objective delta
squad delta
```

Examples:

- budget
- club limit
- position structure
- must-have
- must-avoid
- structural preference
- horizon
- risk profile.

This should distinguish:

```text
objective loss
```

from:

```text
squad composition change
```

---

## P3.6 — Horizon sensitivity analysis

Run:

```text
1 GW
2 GW
3 GW
5 GW
8 GW
```

and compare:

- squad overlap
- objective
- realized points
- regret
- future transfer burden
- stability.

The report should make clear when increasing the horizon materially changes the squad.

---

## P3.7 — Strategy-profile sensitivity

Compare:

```text
balanced
safe
conservative
differential/chase
upside/ceiling
```

without ranking them globally.

Report:

- squad differences
- objective differences
- realized outcomes
- risk metrics
- future flexibility
- ownership differences.

---

## P3.8 — Walk-forward validation

Run strategic starting-state analysis across multiple seasons using only information available at each historical decision point.

At minimum preserve the existing multi-season methodology used by V0.7–V0.9.

Report:

```text
training / calibration period
validation period
test period
```

where applicable.

Avoid selecting a strategic profile using the same test period used to evaluate it.

---

# P4 — Testing

---

## P4.1 — Unit tests

Cover:

- constraints
- locks
- exclusions
- budget
- club limits
- position limits
- objective
- horizon
- candidate generation
- exact reference
- heuristic solver
- GUI state
- provenance
- failure handling.

---

## P4.2 — Integration tests

Cover:

```text
Strategic Engine
→ Decision Engine
→ Planner
→ Lineup
→ Captain
→ History
```

and:

```text
GUI
→ Strategic Engine
→ GUI
→ Planner
```

---

## P4.3 — Regression tests

Ensure V1.0 workflows remain functional.

V1.1 must not silently change existing V1.0 behavior when the strategic-squad functionality is not requested.

---

## P4.4 — Exact-reference adversarial tests

Required cases:

- hidden optimum
- greedy trap
- local-search trap
- tied optimum
- unavailable player
- locked unavailable player
- exclusion
- budget boundary
- club boundary
- position boundary
- preference conflict
- impossible constraints
- zero-value players
- negative-value players
- duplicate-equivalent candidates.

---

## P4.5 — Reproducibility tests

Same:

```text
data
configuration
seed
version
```

must produce the same strategic result.

If stochasticity is intentionally used, it must be explicit and seeded.

---

# P5 — Performance

---

## P5.1 — Benchmark production strategic solver

Measure on realistic candidate pools:

- runtime
- number of evaluations
- memory
- iterations
- 1-opt iterations
- 2-opt iterations
- candidate count
- constraints.

---

## P5.2 — Keep exact reference bounded

The exact solver remains an oracle, not the production algorithm.

It must never accidentally be invoked on the full real FPL universe.

Maintain a hard evaluation/state budget.

---

## P5.3 — GUI responsiveness

Strategic Studio should remain usable while optimization runs.

If necessary:

- progress indicator
- cancellation
- bounded search
- asynchronous execution.

---

# P6 — Documentation

---

## P6.1 — Update V1.1 documentation after hardening

Document:

- exact vs heuristic algorithms
- objective semantics
- horizon semantics
- constraints
- solver limitations
- provenance
- historical backtesting methodology
- factorial analysis
- error-diagnostic definitions
- reproducibility
- performance boundaries.

---

## P6.2 — Avoid unsupported claims

Do not use:

```text
globally optimal
```

for heuristic strategic squads.

Do not use:

```text
causal error attribution
```

for heuristic diagnostics.

Do not use:

```text
independent effect
```

when only main effects have been calculated.

Do not use:

```text
leakage-free
```

unless the specific validation scope supports the claim.

Prefer precise wording such as:

```text
validated against an independent bounded exact reference
```

or:

```text
empirically evaluated under point-in-time historical reconstruction
```

---

## P6.3 — Version consistency

Before release, verify:

- package version
- GUI version
- model registry
- quantitative core version
- documentation
- roadmap
- changelog
- PR description
- experiment reports

all consistently identify V1.1.

---

# P7 — Final V1.1 Release Gate

V1.1 is ready to merge/release when all of the following are true.

### Engine

- [x] Strategic Initial/Wildcard/Free Hit construction works.
- [x] Hard constraints are enforced.
- [x] Soft preferences are explicit.
- [x] Horizon semantics are correct.
- [x] Exact reference is independent.
- [x] Exact reference uses the same feasible space.
- [x] Heuristic nature is explicit.
- [x] Heuristic optimality gap is measured.

### GUI

- [x] Strategic Squad Studio works end-to-end.
- [x] Initial/Wildcard/Free Hit modes work.
- [x] Candidate comparison works.
- [x] Locks/exclusions/preferences work.
- [x] Optimizer → human → optimizer works.
- [x] Human → optimizer works.
- [x] Solver provenance is visible.
- [x] Failures/fallbacks are visible.

### ML / research

- [x] Historical initial-squad backtests work.
- [x] Historical Wildcard backtests work.
- [x] Point-in-time reconstruction is audited.
- [x] Walk-forward evaluation works.
- [x] 2×2×2 factorial analysis includes interactions.
- [x] Error diagnostics are honestly characterized.
- [x] Starting-state regret is measured.
- [x] Horizon sensitivity is measured.
- [x] Constraint sensitivity is measured.
- [x] Strategy-profile sensitivity is measured.
- [x] Near-optimal solution analysis exists.

### Reproducibility

- [x] Experiment provenance is complete.
- [x] Seeds/configuration are recorded.
- [x] Historical decision timestamps are deterministic.
- [x] Results can be replayed.
- [x] No silent fallback exists in research/backtesting.

### Quality

- [x] Unit tests pass.
- [x] Integration tests pass.
- [x] Regression tests pass.
- [x] Exact-reference adversarial tests pass.
- [x] Performance benchmarks are acceptable.
- [x] Documentation matches implementation.

---

# Recommended execution order

Do not implement all items indiscriminately.

Use this order:

```text
P0.1  Horizon / xP semantics
   ↓
P0.2  Remove silent fallback
   ↓
P0.5  Exact-reference feasibility alignment
   ↓
P0.3  Full factorial interactions
   ↓
P0.4  Error-attribution semantics
   ↓
P1.1  Heuristic optimality gap
   ↓
P1.2  Profile failure reporting
   ↓
P1.3  PIT audit
   ↓
P1.4–P1.6  Experiment/reproducibility hardening
   ↓
P2    GUI hardening
   ↓
P3    Research expansion
   ↓
P4    Full test/release gate
```

The first five items are the **V1.1 merge blockers**.

---

# V1.1 Definition of Done

V1.1 is complete when the system can honestly make the following statement:

> **The platform can construct strategic starting squads for Initial, Wildcard, and Free Hit decisions; expose those decisions through an integrated GUI; allow the user to inspect and modify the optimization constraints; feed the resulting squad into the existing decision/planning system; and evaluate the complete starting-state → prediction → decision pipeline using reproducible, point-in-time historical experiments.**

And the system must explicitly distinguish:

```text
exact reference
vs
production heuristic
```

```text
observed outcome
vs
diagnostic attribution
```

```text
main effect
vs
interaction
```

```text
V1.1 execution
vs
fallback execution
```

```text
historical information
vs
future evaluation information
```

That distinction is the central quality requirement for the remainder of V1.1.

---

# After V1.1

Once this checklist is complete, V1.2 can proceed with the next research question:

```text
Does adding LLMs / additional AI providers
actually improve the human + quantitative decision system?
```

V1.1 should therefore establish the trustworthy quantitative baseline against which V1.2 AI/LLM experiments can be evaluated.
