# V0.9 — Final Items Before PR

> **Purpose:** Close the V0.9 branch cleanly after the multi-year lineup-penalty investigation.  
> **Scope rule:** No new predictive-model research should be added to this PR. V0.9 should be frozen as the validated production baseline that feeds V1.0.

---

## 1. Confirm the V0.9 lineup penalty change

### Status
**Implemented — `lineup_penalty_weight = 0.0`.**

The multi-year experiment evaluated the lineup penalty weight under the same sequential, point-in-time backtesting framework and found `w=0.00` to be the strongest global configuration.

### Required checks

- [x] Set production `lineup_penalty_weight` to `0.0`.
- [ ] Verify all lineup-selection paths use the configured value.
- [ ] Verify there is no second hidden participation penalty in the neutral lineup path.
- [ ] Verify captain-specific participation handling remains unchanged unless separately justified.
- [ ] Verify bench-playability logic remains unchanged.
- [ ] Add/update regression tests for `weight = 0.0`.
- [ ] Confirm deterministic reproducibility of the affected decision replay.

### Important interpretation

Do **not** document this as proof that participation modelling is unnecessary.

The conclusion is narrower:

> The V0.9 participation-aware expected-points model already incorporates participation information sufficiently that the previous lineup penalty was counterproductive in the tested decision engine configuration.

Participation probabilities and expected minutes remain core model outputs.

---

# 2. Re-run the final V0.9 regression suite

Run:

```text
unit tests
integration tests
historical regression tests
V0.9 prediction evaluation
V0.9 decision replay
```

Verify:

- no unrelated regressions;
- no change to transfer legality;
- no change to captain legality;
- no change to chip handling;
- no change to autosub behaviour;
- no change to team isolation;
- no change to historical snapshot semantics.

Record the final test count and result.

---

# 3. Re-run the final 2025/26 decision replay

Produce the final production configuration report.

At minimum record:

- total points;
- transfer count;
- zero-minute starters;
- zero-minute captains;
- bench regret;
- transfer gain;
- captaincy regret;
- comparison with V0.8;
- comparison with the pre-change V0.9 configuration.

The purpose is to establish a permanent V0.9 regression result.

---

# 4. Preserve the multi-year penalty experiment

Keep the experiment and results as a research/validation artifact.

Document:

- tested weights;
- seasons;
- Gameweeks;
- simulation protocol;
- mean points;
- zero-minute starters;
- zero-minute captains;
- sensitivity of the result;
- selected production weight.

Do not turn the experiment into a runtime auto-learning mechanism.

The selected value should remain an explicit versioned model/decision-engine parameter.

---

# 5. Audit the remaining V0.9 quantitative inconsistencies

Before calling V0.9 PR-ready, resolve or explicitly document any inconsistencies found during the error-attribution work.

In particular verify:

### Availability FP/FN definitions

The headline report and error-attribution report used slightly different FP/FN totals.

Determine whether this is:

- different thresholds;
- different populations;
- different definitions;
- or a reporting bug.

### Conditional-minutes metrics

The error-attribution report contains conflicting starter-minute error figures.

Verify the underlying calculation and retain only the correctly defined metric.

### Decision-error ledger

Confirm exactly what qualifies as:

```text
PREDICTION_ERROR
DECISION_ERROR
BOTH
HARMLESS
```

and document whether the ledger is exhaustive or only covers a restricted subset of decision failures.

These should not necessarily trigger new model work, but they must not remain ambiguous in the release documentation.

---

# 6. Freeze the V0.9 model

After the final regression:

- [ ] Freeze V0.9 participation-model parameters.
- [ ] Freeze calibration parameters.
- [ ] Freeze regime definitions.
- [ ] Freeze feature definitions.
- [ ] Record training-data cutoff.
- [ ] Record model version.
- [ ] Record parameter version.
- [ ] Record prediction timestamp semantics.
- [ ] Ensure historical replay can reproduce the published result.

No new V0.9 feature should be introduced after this point unless it fixes a correctness bug.

---

# 7. Update V0.9 documentation

Update:

- `docs/v09/v09.md`
- model documentation
- evaluation documentation
- roadmap status
- release notes/changelog if present

The documentation should clearly distinguish:

```text
implemented
tested
validated
PR-ready
released
```

Do not call the branch released until the merge/release has actually happened.

---

# 8. Final V0.9 PR checklist

### Code

- [ ] `lineup_penalty_weight = 0.0`
- [ ] No accidental duplicate penalty
- [ ] No unrelated code changes
- [ ] No debug artefacts
- [ ] No generated temporary files
- [ ] Version metadata correct

### Tests

- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Historical tests pass
- [ ] Prediction regression passes
- [ ] Decision replay passes
- [ ] New weight-zero regression passes

### Data/model

- [ ] Point-in-time integrity preserved
- [ ] No future leakage
- [ ] Model parameters frozen
- [ ] Calibration frozen
- [ ] Training cutoff documented

### Documentation

- [ ] V0.9 results documented
- [ ] Multi-year penalty experiment documented
- [ ] Known limitations documented
- [ ] Remaining inconsistencies resolved/documented
- [ ] Roadmap updated

### Git/PR

- [ ] Branch clean
- [ ] Commits focused
- [ ] PR description explains the penalty change
- [ ] PR links the multi-year experiment
- [ ] CI green

---

# 9. Explicitly out of scope for the V0.9 PR

Do **not** add:

- a new minutes model;
- a new participation classifier;
- new xP components;
- new external-data sources;
- a new rank objective;
- automatic penalty-weight learning;
- new LLM personas;
- major GUI features;
- large optimizer redesigns.

Those belong in V1.0 or later research tracks.

---

# V0.9 exit criterion

V0.9 is PR-ready when:

> The V0.9 production configuration is deterministic, reproducible, tested, historically validated, documented, and contains no known release-blocking correctness issue.

At that point, the branch should move to PR rather than continuing to accumulate research changes.
