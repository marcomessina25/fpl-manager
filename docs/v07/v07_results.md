# V0.7 Empirical Research Results & Cross-Season Evaluation

## 1. Executive Summary

Version 0.7 establishes the historical measurement framework for `fpl-manager`. For the first time, prediction accuracy and decision engine performance have been objectively evaluated against complete historical Premier League datasets (2022-23 and 2023-24) using strict point-in-time reconstruction with **zero future-data leakage**.

### Key Quantitative Findings:
1. **Predictive Accuracy:**
   - The production $xP$ model achieves a consistent Spearman rank correlation of **$\rho \approx 0.52 - 0.60$** across seasons (MAE: $1.26 - 1.35$ pts).
   - Among active players (starters/subs with $>0$ mins), rank correlation remains moderate ($\rho \approx 0.33$).
2. **Minutes ($xM$) Accuracy:**
   - Expected minutes prediction has an overall MAE of $\approx 19.1$ minutes.
   - For regular starters ($>75$ expected mins), calibration is tight (mean predicted 81.5 vs actual 78.3 mins, MAE: 15.9 mins).
   - Mid-tier rotation assets ($16-60$ predicted mins) suffer the highest variance.
3. **Availability Model:**
   - 100% recall on active players; however, a 38.4% precision reveals high false-positive rates due to unflagged rotational benching and tactical non-appearances.
4. **Decision Engine & Baselines:**
   - **Production Combinatorial Optimizer** decisively outperforms both the No-Transfer baseline and the greedy Simple $xP$ baseline across both test seasons.
   - In 2023-24 (GW 1-10): **Optimizer (532 pts)** vs Simple xP (494 pts, $+38$) vs No-Transfer (473 pts, $+59$).
   - In 2022-23 (GW 1-10): **Optimizer (438 pts)** vs Simple xP (418 pts, $+20$) vs No-Transfer (421 pts, $+17$).
5. **LLM Qualitative Advisor:**
   - The deterministic validation layer prevented 100% of illegal LLM transfer proposals.
   - When restricted to legal moves, qualitative LLM overrides provided negligible or negative net expected value compared to direct mathematical branch-and-bound optimization.

---

## 2. Cross-Season Prediction Metrics

| Metric | 2022-23 Season (GW 1-10) | 2023-24 Season (GW 1-38) | Interpretation |
| :--- | :---: | :---: | :--- |
| **Total Player-GW Samples** | 7,120 | 28,742 | Comprehensive out-of-sample coverage |
| **xP MAE** | 1.353 pts | 1.262 pts | Stable low absolute prediction error |
| **xP RMSE** | 2.340 pts | 2.041 pts | Expected variance under Poisson scoring events |
| **Spearman Rank Correlation** | 0.5148 | 0.5956 | Strong rank ordering of assets |
| **Prediction Bias** | +0.284 pts | +0.319 pts | Slight optimistic bias toward appearance points |
| **Minutes MAE** | 21.45 mins | 19.11 mins | Rotation uncertainty is the main error driver |

---

## 3. Cross-Season Strategy Comparison

Replaying simulated managers starting with identical £100.0m squads at GW1:

### Season 2023-24 (Gameweeks 1–10)
| Strategy | Net Points | Gross Points | Hits Taken | Transfers Made | Delta vs No-Transfer |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Baseline A: No-Transfer** | 473 | 473 | 0 (-0 pts) | 0 | - |
| **Baseline B: Simple xP** | 494 | 494 | 0 (-0 pts) | 9 | +21 pts |
| **Baseline C: Production Optimizer** | **532** | **532** | 0 (-0 pts) | 9 | **+59 pts** |

### Season 2022-23 (Gameweeks 1–10)
| Strategy | Net Points | Gross Points | Hits Taken | Transfers Made | Delta vs No-Transfer |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Baseline A: No-Transfer** | 421 | 421 | 0 (-0 pts) | 0 | - |
| **Baseline B: Simple xP** | 418 | 418 | 0 (-0 pts) | 9 | -3 pts |
| **Baseline C: Production Optimizer** | **438** | **438** | 0 (-0 pts) | 9 | **+17 pts** |

### Conclusion on Optimization:
The combinatorial branch-and-bound optimizer consistently finds synergistic team improvements that simple greedy 1-for-1 swaps miss. Greedy selection without portfolio awareness can actually hurt performance (as observed in 2022-23 where Simple xP lost 3 points to No-Transfer).

---

## 4. Failure-Mode Analysis

Detailed investigation of decision losses and prediction errors revealed four primary failure modes:

1. **Failure Mode 1: Mid-Tier Rotation Blindness**
   - *Observation:* Players in the 30–60 expected minutes bucket had an MAE of 36.7 minutes.
   - *Root Cause:* Linear minutes scaling from past starts fails during fixture congestion (European matches) and early cup rotations.
   - *Remedy for V0.8:* Implement manager rotation patterns and fixture turnaround features.
2. **Failure Mode 2: Unflagged Injury / Non-Squad Risk**
   - *Observation:* High false-positive availability rate (38.4% precision). Over 17,000 player-gameweek instances where available players registered 0 minutes.
   - *Root Cause:* FPL API status often remains "Available" ('a') for fringe players or newly injured players if press conferences happen after deadline or managers omit them from the squad sheet.
3. **Failure Mode 3: Defensive Clean Sheet Double Counting**
   - *Observation:* Defenders against FDR 2 opponents were systematically over-projected by $\approx 0.6$ pts.
   - *Root Cause:* Clean sheet expectations did not adequately factor in late concession probabilities (90+ minute goals).
4. **Failure Mode 4: LLM Hallucination of Legality**
   - *Observation:* Unconstrained LLM suggestions repeatedly proposed transfers violating bank budgets or club quotas.
   - *Root Cause:* LLMs struggle with exact arithmetic constraints over 15-variable combinatorial spaces.
   - *Remedy:* LLMs must strictly operate in an advisory or explanatory capacity over deterministic candidate menus, never generating unvalidated transfers.

---

## 5. V0.8 Evidence-Based Decision Gate

Following Section 36 of `docs/v07/v07_plan.md`, the experimental findings dictate the following architectural decisions:

| Component | Status | Empirical Rationale | V0.8 Action Plan |
| :--- | :---: | :--- | :--- |
| **Branch-and-Bound Optimizer** | **KEEP** | Consistently generated $+17$ to $+59$ pts over baselines without transfer hit penalties. | Retain as authoritative core solver. Expand to multi-gameweek beam planning. |
| **Formation-Legal Autosub Engine** | **KEEP** | Flawlessly simulated matchday realities and vice-captain promotions. | Maintain in production evaluation. |
| **Component xP Model** | **CALIBRATE** | Good rank correlation ($\rho \approx 0.60$), but positive bias ($+0.32$ pts) and FDR defensive sensitivity need recalibration. | Tune Clean Sheet and FDR coefficients based on 2022-24 empirical regressions. |
| **Expected Minutes Model** | **REDESIGN** | Highest error contribution (MAE 19.1 mins). Fails on mid-tier rotation assets. | Introduce dedicated probabilistic minutes model with fixture turnaround features. |
| **Autonomous LLM Decision Execution** | **REMOVE** | LLM overrides degraded net points and produced invalid recommendations. | Keep LLM strictly in qualitative explanation and manager briefing roles. |
