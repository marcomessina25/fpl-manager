# V1.4.6 — Empirical Human-in-the-Loop Replay Benchmark Study

**Status:** Planned (Follows V1.4.5)  
**Predecessor:** V1.4.5 — Multi-Season Strategic Chip Optimization Study & Engine Unification  
**Platform:** V1.4 — Interactive Historical Season Simulation & Time Machine Sandbox  
**Corpus / Repo:** `marcomessina25/fpl-manager`

---

## 1. Executive Summary & Scientific Purpose

With the completion of the V1.4 Historical Simulation platform (infrastructure, zero-spoiler standings/fixtures, state persistence) and the V1.4.5 Strategic Chip Optimizer (eliminating heuristic chip wastage and unifying simulation/GUI engines), **V1.4.6 executes the formal Human-in-the-Loop Replay Benchmark**.

The study empirically measures human decision-making and human + software synergy when operating under strictly enforced historical point-in-time information constraints:

1. How do human managers perform when equipped with state-of-the-art deterministic optimization, machine-learned expected points, and calibrated chip policies?
2. When human managers override algorithmic recommendations (transfers, captaincy, chips), does human intuition generate positive or negative decision alpha?
3. What is the observed empirical distribution of manager divergence across diverse season contexts (normal seasons, COVID/postponement disruptions, fixture-dense double gameweeks)?

---

## 2. Experimental Design & Replay Tracks

### Track Structure
To isolate software recommendations from human agency, three parallel tracks are evaluated under identical point-in-time snapshots and initial squad conditions:

- **Track A — Engine-Only Deterministic Baseline**:
  - The frozen reference pipeline (`DecisionEngineV135` transfers + V1.4.5 Strategic Chip Optimizer) executes autonomously from GW1 to GW38.
- **Track B — Human-Assisted (Human + Engine Advisory)**:
  - Human participants receive full software recommendations (candidate transfers ranked by net EV, optimal starting XI/captaincy, and chip advisory valuations) at each deadline.
  - The participant makes the final decision, with the option to accept, modify, or completely override recommendations.
- **Track C — Human Blind Control (Information Only)**:
  - Participants receive authentic historical fixtures, past match results, and official league standings, but no algorithmic projections or transfer recommendations.

### Information Boundary & Zero-Spoiler Guarantees
- Replays operate strictly through the V1.4 Time Machine Sandbox.
- Future fixture scores, finished statuses, player points, and post-deadline price movements are completely masked.
- Participants operate under the identical decision deadlines of the simulated historical season.

---

## 3. Logged Metrics & Statistical Evaluation

For every gameweek $t \in [1, 38]$ across each participant session:
1. **Decision Capture**:
   - `engine_recommended_transfers` vs `human_transfers`
   - `engine_captain` vs `human_captain`
   - `engine_chip_action` vs `human_chip_action`
2. **Outcome Resolution**:
   - Realized gameweek net points (points minus hits).
   - Realized points divergence: $\Delta \text{Pts}_t = \text{Score}_{\text{human}, t} - \text{Score}_{\text{engine}, t}$.
3. **Regret Decomposition**:
   - Human Override Regret: points lost/gained specifically attributable to overriding algorithmic recommendations.
   - Prediction Regret vs Decision Regret breakdown.

---

## 4. Deliverables & Benchmark Report

- Standardized benchmark replay protocol and trial participant instructions.
- Participant session logs stored in `config/simulations/<session_id>.json`.
- Full statistical synthesis report in `reports/v146/human_benchmark_report.md`.
- Publication-ready visualizations: cumulative score trajectory comparisons, override alpha distribution, and chip timing divergence charts.
