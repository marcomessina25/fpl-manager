# Items Left for V1.0

## Purpose

This document is the final pre-release checklist for the V1.0 PR.

The objective is **not** to add more research or new predictive-model features. The objective is to make the current V1.0 implementation correct, reproducible, honestly documented, and safe to merge into `master`.

The current PR is a strong V1.0 candidate, but the review identified a small number of release-blocking correctness and verification issues that should be resolved before merge.

---

# P0 — Release Blockers

## P0.1 — Add an independent exact transfer reference solver

### Problem

The current `solve_transfers_exhaustive()` implementation delegates to the production branch-and-bound solver with a very large result/candidate limit.

Therefore it does **not** independently prove that branch-and-bound reaches the global optimum.

We need an exact reference implementation, but it must be deliberately bounded so that it cannot consume excessive CPU or memory on a developer laptop.

### Required implementation

Create a small, independent brute-force reference solver used only for verification.

The reference solver should:

1. Operate on a **synthetic, explicitly bounded candidate pool**.
2. Never enumerate the real FPL player universe.
3. Enumerate all legal combinations of `k` players out and `k` players in.
4. Validate each resulting squad.
5. Calculate the objective independently.
6. Return the exact optimum.
7. Be completely independent of the production branch-and-bound implementation.

### Test sizes

Use small candidate pools whose complete enumeration is comfortably bounded.

Example:

| Test | Candidate OUT | Candidate IN | Transfers | Combinations |
|---|---:|---:|---:|---:|
| A | 4 | 4 | 1 | 16 |
| B | 6 | 6 | 2 | 225 |
| C | 7 | 7 | 3 | 1,225 |
| D | 8 | 8 | 4 | 4,900 |
| E | 9 | 9 | 5 | 15,876 |

These tests verify the behaviour of 1–5 transfer combinations without attempting to brute-force the real FPL search space.

### Required adversarial scenarios

Include cases covering:

- optimum appearing late in enumeration
- many equal-scoring solutions / ties
- budget constraints
- squad legality
- position constraints
- club/team constraints
- unavailable players
- zero-value transfers
- negative-value transfers
- pruning-sensitive cases where the optimum is only slightly better than the current incumbent

### Safety guard

The reference implementation should have an explicit evaluation budget, for example:

```python
MAX_REFERENCE_EVALUATIONS = 100_000
```

Calculate the expected number of combinations before execution and fail clearly if a test exceeds the safety budget.

### Acceptance criterion

For every bounded synthetic case:

```text
production branch-and-bound optimum
        ==
independent exact reference optimum
```

The objective value and the resulting legal transfer solution must agree.

### Naming

Do not call a production branch-and-bound wrapper `solve_transfers_exhaustive()`.

Prefer terminology such as:

```text
solve_transfers_exact_reference()
```

or:

```text
solve_transfers_bruteforce_reference()
```

The reference implementation is a **verification oracle**, not a production solver.

---

# P0.2 — Add an independent exact multi-GW reference planner

### Problem

The current `plan_multi_gw_exhaustive()` implementation delegates to the production planner with a very large beam width.

A large beam is still a beam search and does not constitute exhaustive/global-optimality verification.

### Required implementation

Create a small independent exact reference planner for synthetic multi-gameweek scenarios.

Prefer dynamic programming over explicitly enumerated states:

```text
V(state, GW)
    = max over legal next actions:
        immediate reward
        + V(next_state, GW + 1)
```

Alternatively, for very small test spaces, complete state/action enumeration is acceptable.

### Test scope

Use intentionally tiny synthetic problems, for example:

- 2–4 gameweeks
- 4–6 synthetic players
- 2–5 possible actions per gameweek
- bounded state space

The goal is verification, not realistic-scale performance.

### Required scenarios

Include:

1. immediate reward
2. transfer cost
3. future value / non-greedy optimum
4. banked transfers
5. illegal transitions
6. repeated player usage
7. ties
8. a scenario where the optimal plan is not the greedy plan

### Acceptance criterion

For every bounded synthetic scenario:

```text
production multi-GW planner
        ==
independent exact reference optimum
```

The optimal objective and resulting legal plan must agree.

### Naming

Do not call a wide-beam production implementation `plan_multi_gw_exhaustive()`.

Prefer:

```text
plan_multi_gw_exact_reference()
```

or:

```text
plan_multi_gw_dp_reference()
```

for the independent test oracle.

The production planner should be documented honestly as a heuristic/beam-search method if it is not globally exhaustive.

---

## P0.3 — Fix and regression-test the `lineup.py` objective/reporting transition

### Problem

The V1.0 changes introduce objective-specific variables such as:

```python
starters_obj
captain_obj
total_lineup_obj
```

while parts of the reporting code still appear to reference the previous variables:

```python
starters_xp
captain_bonus
```

This needs to be verified because it may produce a runtime `NameError` or incorrect reporting depending on the surrounding implementation.

### Required action

Keep the model xP and the decision objective conceptually separate.

For example:

```text
model quantities:
    starters_xp
    captain_bonus
    total_lineup_xp

decision quantities:
    starters_obj
    captain_obj
    total_lineup_obj
```

Use the objective variables for optimization and preserve xP variables for reporting/diagnostics where appropriate.

### Acceptance criterion

- No undefined-variable paths.
- Lineup selection works.
- Lineup reporting works.
- Historical replay works.
- Objective values and xP values are not accidentally conflated.
- Add regression tests covering the affected path.

---

# P1 — Important Before Merge

## P1.1 — Clarify decision-error attribution semantics

### Problem

The new evaluation layer reports:

- prediction error
- decision error
- captaincy error
- transfer error
- chip error

However, the current definitions appear to overlap.

For example, a decision regret measure comparing actual performance with a hindsight-optimal lineup can already include captaincy, transfer, or chip effects.

Therefore the current implementation should not be presented as a strictly additive five-way decomposition unless the categories are made mutually exclusive.

### Preferred solution

Make the accounting explicitly additive:

```text
total decision regret
    =
    lineup regret
  + captaincy regret
  + transfer regret
  + chip regret
  + hit cost
```

with clearly defined counterfactuals.

### Alternative

If the current diagnostics are intentionally overlapping, rename/document them as:

```text
decision-loss diagnostics
```

rather than:

```text
five-way decision attribution
```

### Acceptance criterion

Documentation must clearly state whether the categories are:

- mutually exclusive/additive, or
- overlapping diagnostic measures.

No ambiguous decomposition claims.

---

## P1.2 — Tighten model metadata and reproducibility semantics

### Problem

`ModelMetadata.from_dict()` currently appears capable of filling missing metadata fields with defaults.

For a reproducibility-oriented V1.0 system, silently converting incomplete provenance into apparently valid provenance is undesirable.

### Required action

For required provenance fields, prefer explicit validation:

```text
model_version
training_data_cutoff
feature_set_version
parameter_version
prediction_timestamp
```

Missing required fields should either:

- raise a validation error, or
- be explicitly marked as incomplete/unknown.

Do not silently fabricate valid-looking provenance.

---

## P1.3 — Distinguish live and historical prediction timestamps

### Problem

Model metadata may use the current UTC time when a prediction timestamp is not explicitly supplied.

That is reasonable for live predictions but can weaken historical reproducibility.

### Required semantics

For historical reconstruction:

```text
prediction_timestamp
    =
historical snapshot/deadline timestamp
```

For live prediction:

```text
prediction_timestamp
    =
actual current prediction time
```

The system should not silently use `now()` for a historical prediction.

### Acceptance criterion

Historical replay produces stable metadata and does not depend on the machine's current clock.

---

## P1.4 — Tighten the PIT leakage validator claims

The seven-category leakage framework is useful, but documentation should distinguish:

1. invariants that can be checked directly from the snapshot, and
2. checks that depend on an explicitly supplied pre/post-deadline reference state.

Do not claim that the validator independently proves a property that it only verifies when an external reference field is supplied.

### Acceptance criterion

Documentation accurately describes the scope and limitations of PIT validation.

---

## P1.5 — Explain or remove the branch-and-bound bound change

A change to the branch-and-bound estimated score/bound appears to modify a constant from:

```text
+0.5
```

to:

```text
+1.0
```

This is potentially important because the value participates in pruning.

### Required action

Either:

1. revert the change if it is unnecessary, or
2. document why the new bound is correct and add a regression/adversarial test demonstrating that it cannot incorrectly prune an optimal branch.

This should be addressed together with P0.1.

---

# P2 — Recommended Cleanup Before Merge

## P2.1 — Clarify the meaning of neutral risk profile

The default is correctly:

```text
neutral
lineup_penalty_weight = 0.0
```

But callers can still explicitly pass a non-zero penalty while selecting the `neutral` risk profile.

This is useful for experimentation, but the semantics should be explicit.

Recommended documentation:

> Neutral defaults to `lineup_penalty_weight = 0.0`. Explicit custom penalty weights remain available for experimentation and are not considered the canonical neutral configuration.

No hidden override is necessary unless the project decides that `neutral` must mathematically guarantee pure xP optimization.

---

## P2.2 — Be precise about the V1.0 quantitative model

The V1.0 product release uses the frozen V0.9/V0.9.1 quantitative predictor.

This is perfectly acceptable.

Documentation should consistently distinguish:

```text
V1.0 product/release
```

from:

```text
V0.9.1 frozen quantitative model
```

Avoid implying that V1.0 introduced a newly trained predictive model if it did not.

---

## P2.3 — Provide provenance for headline performance numbers

Every headline backtest number in README/release documentation should point to a reproducible report or artifact.

Examples include:

- seasonal net points
- comparison against No-Transfer
- comparison against Greedy
- aggregate multi-season points
- transfer gains
- decision-regret metrics

Prefer explicit references such as:

```text
reports/v10_canonical_model_report.md
reports/v10_decision_backtest_2021_2026.md
```

where those reports exist.

---

# P3 — Final V1.0 Release Gate

After P0/P1 items are complete:

## P3.1 — Full test suite

Run:

- unit tests
- integration tests
- optimizer tests
- exact-reference verification tests
- PIT/leakage tests
- model metadata tests
- historical replay
- decision backtests
- GUI/API tests
- LLM/provider tests
- database migration tests

No unexplained failures.

---

## P3.2 — Regression against frozen V0.9.1

Confirm that V1.0 does not unexpectedly degrade the frozen V0.9.1 baseline.

Record:

- prediction metrics
- decision metrics
- transfer metrics
- zero-minute starters
- captaincy metrics
- bench regret
- historical replay totals

Any differences should be explained by intentional V1.0 changes.

---

## P3.3 — Documentation consistency

Check:

- README
- roadmap
- V1.0 documentation
- release notes
- model registry documentation
- evaluation documentation
- optimizer documentation

No documentation should claim:

- exact optimization where only heuristic search exists
- exhaustive search where only a wide beam exists
- guaranteed logging where persistence is best-effort
- stronger PIT guarantees than the implementation provides

---

## P3.4 — Scope check

Do **not** add new research features merely to fill remaining time.

Explicitly keep out of V1.0:

- new participation model research
- new xP model components
- new external data sources
- automatic learned risk penalties
- rank-prediction research
- major new LLM personas
- major GUI redesign
- production MILP wildcard research

These belong to post-V1.0 research tracks.

---

# Final Definition of Done

V1.0 is ready for merge when:

```text
[ ] P0.1 Independent exact transfer oracle
[ ] P0.2 Independent exact multi-GW oracle
[ ] P0.3 lineup objective/reporting regression fixed
[ ] P1.1 decision-attribution semantics clarified
[ ] P1.2 model metadata validation hardened
[ ] P1.3 historical timestamps deterministic
[ ] P1.4 PIT validation claims aligned with implementation
[ ] P1.5 branch-and-bound bound change justified/tested
[ ] P2 documentation cleanups completed
[ ] P3 full test suite passes
[ ] V0.9.1 regression is explained
[ ] README/release documentation is consistent
[ ] No known release-blocking correctness issue
```

## Final principle

The goal of V1.0 is not to prove that the system is perfect.

The goal is to make the system:

> **stable, reproducible, tested, measurable, and demonstrably useful.**

Where an algorithm is heuristic, say so.

Where an oracle is exact, make it genuinely independent.

Where a metric is diagnostic rather than causal, say so.

Where a result is experimental, label it experimental.

**V1.0 should be the point where we trust the system enough to start the next generation of experiments — not the point where we pretend the research is finished.**
