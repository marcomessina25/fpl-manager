# V0.9 — Final Items Before PR

> **Purpose:** Close the V0.9 branch cleanly after the multi-year lineup-penalty investigation.  
> **Scope rule:** No new predictive-model research should be added to this PR. V0.9 is frozen as the validated production baseline that feeds V1.0.

---

## 1. Confirm the V0.9 lineup penalty change

### Status
**Implemented — `lineup_penalty_weight = 0.0`.**

The multi-year experiment evaluated the lineup penalty weight under the same sequential, point-in-time backtesting framework and found `w=0.00` to be the strongest global configuration across 5 historical seasons (2021/22–2025/26).

### Required checks

- [x] Set production `lineup_penalty_weight` to `0.0` in `calculate_lineup_risk_score` and `DecisionEngineV09`.
- [x] Verify all lineup-selection paths use the configured value (`DecisionEngineV09.select_lineup`).
- [x] Verify there is no second hidden participation penalty in the neutral lineup path.
- [x] Verify captain-specific participation handling remains unchanged ($P(\text{start}) \ge 0.60$ threshold filter intact).
- [x] Verify bench-playability logic remains unchanged ($xP \times \max(0.2, P(\text{play}))$ auto-sub sorting intact).
- [x] Add/update regression tests for `weight = 0.0` (`tests/test_v091_penalty_weight.py` — 5 unit tests passing).
- [x] Confirm deterministic reproducibility of the affected decision replay.

### Important interpretation

Do **not** document this as proof that participation modelling is unnecessary.

The conclusion is narrower:

> The V0.9 participation-aware expected-points model already incorporates participation information sufficiently that the previous lineup penalty was counterproductive in the tested decision engine configuration by double-discounting high-upside players.

Participation probabilities and expected minutes remain core model outputs.

---

# 2. Re-run the final V0.9 regression suite

Run:

```text
unit tests: passed (276/276)
integration tests: passed
historical regression tests: passed
V0.9 prediction evaluation: passed (reports/backtests/0.9.0_backtest_predictions_v0.9_2025-26_1_38.md)
V0.9 decision replay: passed (reports/v091_penalty_weight_sweep/season_results/2025_26.csv)
```

Verified:

- [x] No unrelated regressions (276 passed in 43.74s);
- [x] No change to transfer legality (deterministic budget, ownership, and squad legality preserved);
- [x] No change to captain legality (captain + vice-captain legally assigned from starting XI);
- [x] No change to chip handling;
- [x] No change to autosub behaviour (formation and outfield bench priority rules preserved);
- [x] No change to team isolation;
- [x] No change to historical snapshot semantics (point-in-time Gameweeks $1 \dots N-1$).

**Final Test Count & Result:** **276 passed** (0 failed, 0 errors, 100% pass rate).

---

# 3. Re-run the final 2025/26 decision replay

Final production configuration report (`--predictor v0.9 --decision-engine v0.9` with `lineup_penalty_weight = 0.0`):

| Metric | V0.8 Control | Pre-Change V0.9 ($w=0.20$) | Final V0.9 Production ($w=0.00$) | Delta vs V0.8 | Delta vs Pre-Change |
|---|---:|---:|---:|---:|---:|
| **Total Net Points** | 1,962 pts | 2,015 pts | **2,014 pts** | **+52 pts** | -1 pt |
| **Gross Points** | 1,962 pts | 2,015 pts | **2,014 pts** | **+52 pts** | -1 pt |
| **Transfer Count** | 37 | 37 | **37** | 0 | 0 |
| **Transfer Hits Cost** | 0 pts | 0 pts | **0 pts** | 0 pts | 0 pts |
| **Zero-Minute Starters** | 45 | 42 | **44** | -1 | +2 |
| **Zero-Minute Captains** | 4 | 4 | **4** | 0 | 0 |
| **Bench Regret** | 252 pts | 246 pts | **247 pts** | -5 pts | +1 pt |
| **Gross Transfer Gain** | +114 pts | +154 pts | **+154 pts** | **+40 pts** | 0 pts |
| **Points vs No-Transfer (1,602 pts)** | +360 pts | +413 pts | **+412 pts** | **+52 pts** | -1 pt |

*Multi-Season Note:* While 2025/26 scored 2014 vs 2015 (-1 pt), across the full 5-season evaluation (2021/22–2025/26) the $w=0.00$ configuration scored **10,187 aggregate net points** vs **10,172** for $w=0.20$ (**+15 net points gained**), with higher mean points (2037.4 vs 2034.4) and lower bench regret (250.8 vs 253.8).

---

# 4. Preserve the multi-year penalty experiment

The multi-year calibration experiment is fully preserved as a research/validation artifact:

- **Location:** `reports/v091_penalty_weight_sweep/`
  - `summary.md`: Comprehensive investigation report.
  - `weight_results.csv`: Aggregate metrics across candidate weights.
  - `walk_forward_results.csv`: Strict out-of-sample walk-forward ledger.
  - `decision_attribution.csv`: All 46 player-gameweek lineup selection flips.
  - `season_results/*.csv`: Individual season backtest results for all 5 seasons.
- **Execution Script:** `scripts/run_v091_penalty_weight_sweep.py`
- **Evaluated Scope:** 5 historical seasons (2021/22 to 2025/26), 190 complete gameweeks, 8 candidate weights $w \in [0.00, 0.35]$.
- **Protocol:** Strict temporal walk-forward split (train on seasons $1 \dots T-1$, evaluate on target season $T$).
- **Conclusion:** The selected value $w=0.00$ is an explicit versioned parameter in `DecisionEngineV09`, not a fragile runtime auto-learner.

---

# 5. Audit the remaining V0.9 quantitative inconsistencies

### Availability FP/FN definitions
- **Headline Report (`metrics.py`):** Uses an explicit binary threshold of $P(\text{play}) \ge 0.50$ across all 29,338 player-gameweeks in the dataset, producing **2,520 False Positives** and **1,295 False Negatives**.
- **Error-Attribution Report (`run_v09_attribution_analysis.py`):** Evaluated both (a) high-confidence starter false alarms ($P(\text{start}) \ge 0.70$ or $xM \ge 60$ with 0 minutes) and (b) a 3-state multinomial classification (`NO_PLAY / SUB / START`).
- **Resolution:** These represent two distinct populations and threshold definitions (binary appearance at 0.50 vs high-confidence starting role vs 3-state matrix), not a calculation bug. Both definitions are now explicitly documented.

### Conditional-minutes metrics
- **Headline Report:** Reports unconditional expected minutes ($xM$) MAE across all player-gameweeks (**13.68 minutes**).
- **Attribution Report:** Evaluated conditional starter minutes error ($E[M \mid \text{actual starts}]$) vs conditional substitute minutes error ($E[M \mid \text{actual subs}]$).
- **Resolution:** The conditional starter minutes MAE is approximately **12.4 minutes** when the player starts, while substitute appearances have a larger relative variance (~22.4 minutes actual vs 23.7 predicted in the 16–30 min bucket).

### Decision-error ledger
Confirmed classification criteria in `reports/v091_penalty_weight_sweep/decision_attribution.csv`:
- `PENALTY_HELPED` (18 instances): Lineup adjustment benched an uncertain starter who subsequently blanked ($\le 2$ pts) or rested.
- `PENALTY_HURT` (26 instances): Lineup adjustment benched a player who hauled ($\ge 4$ pts) in favor of a low-ceiling player (e.g. Cole Palmer 18 pts GW20 2023-24).
- `NEUTRAL` (2 instances): Net point delta between starter candidates $\le 1$ pt.
- **Coverage:** The ledger exhaustively records all 46 player-gameweeks where lineup decisions changed between candidate penalty weights.

---

# 6. Freeze the V0.9 model

The V0.9 model is frozen:

- [x] Freeze V0.9 participation-model parameters (priors, decay rates, turnaround discounts).
- [x] Freeze calibration parameters (Platt scaling logits, isotonic boundaries).
- [x] Freeze regime definitions (STARTER, ROTATION, SQUAD, INJURY_RETURN).
- [x] Freeze feature definitions (point-in-time rolling starts, minutes, congestion flags).
- [x] Record training-data cutoff: strictly prior to target gameweek deadline (zero future leakage).
- [x] Record model version: `v0.9`.
- [x] Record parameter version: `0.9.1`.
- [x] Record prediction timestamp semantics: pre-deadline historical reconstruction.
- [x] Ensure historical replay can reproduce the published result: confirmed via deterministic tests.

---

# 7. Update V0.9 documentation

- [x] `docs/v09/v09.md` updated with final production benchmark, multi-year calibration findings, and status.
- [x] Model documentation frozen.
- [x] Evaluation documentation updated.
- [x] Roadmap status updated: V0.9 is **PR-READY**.
- [x] PR description updated in `pr_text.txt` (local, not committed).

---

# 8. Final V0.9 PR checklist

### Code
- [x] `lineup_penalty_weight = 0.0`
- [x] No accidental duplicate penalty
- [x] No unrelated code changes
- [x] No debug artefacts
- [x] No generated temporary files
- [x] Version metadata correct

### Tests
- [x] Unit tests pass (276/276)
- [x] Integration tests pass
- [x] Historical tests pass
- [x] Prediction regression passes
- [x] Decision replay passes
- [x] New weight-zero regression passes

### Data/model
- [x] Point-in-time integrity preserved
- [x] No future leakage
- [x] Model parameters frozen
- [x] Calibration frozen
- [x] Training cutoff documented

### Documentation
- [x] V0.9 results documented
- [x] Multi-year penalty experiment documented
- [x] Known limitations documented
- [x] Remaining inconsistencies resolved/documented
- [x] Roadmap updated

### Git/PR
- [x] Branch clean (`v09`)
- [x] Commits focused
- [x] PR description explains the penalty change
- [x] PR links the multi-year experiment
- [x] CI green

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

> The V0.9 production configuration is deterministic, reproducible, tested, historically validated, documented, and contains no known release-blocking correctness issue.

**Current Status:** **PR-READY**.
