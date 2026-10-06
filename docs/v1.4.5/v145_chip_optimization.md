# V1.4.5 — Multi-Season Strategic Chip Optimization Study & Engine Unification

**Status:** Planned (Next release following V1.4)  
**Predecessor:** V1.4 — Interactive Historical Season Simulation & Time Machine Sandbox Platform  
**Successor:** V1.4.6 — Empirical Human-in-the-Loop Replay Benchmark  
**Corpus / Repo:** `marcomessina25/fpl-manager`

---

## 1. Executive Summary & Problem Formulation

In FPL, chips represent the highest-leverage discrete interventions available to a manager over a 38-gameweek season:
- **Wildcard (x2)**: Complete 15-player squad restructuring without transfer hits (one available in GW1–19, one in GW20–38).
- **Free Hit**: One-gameweek squad transformation, reverting to the original squad post-deadline.
- **Triple Captain**: Multiplies captain score by 3 instead of 2.
- **Bench Boost**: Scores all 15 squad members (including 4 bench players).

### Structural Failures in Existing Implementations
1. **The Fixed Threshold & Static Gate Pathology**:
   - Both the live advisory heuristics (`chip_strategy.py`) and the historical backtest policy (`SeasonalChipPolicy`) relied on fixed point-delta hurdles (e.g. `squad_deficit >= 12.0` or `gw_xp_gain >= 8.0`).
   - *Premature Burns*: Superficial short-term fixture bumps can cause a Free Hit to be triggered right after a Wildcard restructuring or immediately after GW1, wasting massive future value despite the squad already being freshly optimal.
   - *Chip Wastage / Inaction*: If hard thresholds are missed narrowly in every individual gameweek, the engine hoards chips indefinitely across entire half-seasons (Segment 1 expires at GW19, Segment 2 at GW38), yielding 0 points from unplayed chips.
2. **Disconnected Pipeline Divergence**:
   - The GUI Chip Strategy visualizer and the simulation benchmark engine use different heuristics, causing user-facing roadmaps to contradict reproducible simulation replays.
3. **Disregard for Future Blank & Double Gameweek Topography**:
   - Particularly in Segment 2 (GW20–38), FA Cup postponements create extreme Blank Gameweeks (BGWs) and massive Double Gameweeks (DGWs). A static threshold model fails to compute the option value of preserving chips for known or projected schedule dislocations.

---

## 2. Core Scientific & Optimization Architecture

V1.4.5 completely eliminates arbitrary, hard-coded thresholds in favor of a **rigorous expected-value (EV) and opportunity-cost optimization framework** (exploring ML / surrogate-value policies):

### 2.1 Dynamic Opportunity Cost & Segment Window Horizons
Every candidate matchday $t$ for chip $C$ is evaluated by balancing its immediate point surplus against the residual opportunity cost:

$$\text{Net Utility}(C, t) = \Delta \text{EV}(C, t) - \max_{t' \in [t+1, T_{\text{window}}]} \mathbb{E}[\Delta \text{EV}(C, t')]$$

- **Natural Terminal Window Decay**: As $t \to T_{\text{window}}$ (GW19 for Segment 1 chips, GW38 for Segment 2 chips), the opportunity cost of holding the chip naturally decays to zero:
  $$\lim_{t \to T_{\text{window}}} \max_{t' > t} \mathbb{E}[\Delta \text{EV}(C, t')] = 0$$
  This mathematically guarantees that chips are deployed on the **global maximum of the remaining fixtures** rather than hoarded until expiration.

### 2.2 Free Hit Valuation Model
- Compares the EV of the current squad under upcoming fixtures against the optimal temporary 15-player lineup.
- If the current squad was recently optimized via Wildcard or at season launch (GW1), $\Delta \text{EV}(\text{FH}, t)$ is naturally minimal, while future opportunity cost during BGWs is substantial. Thus, $\text{Net Utility}(\text{FH}, t) \ll 0$ without needing artificial blacklists.

### 2.3 Blank & Double Gameweek Awareness (GW20–38)
- Segment 2 trajectory evaluation ingests fixture congestion and rescheduled match schedules.
- Computes expected utility distributions for Triple Captain (targeting elite doubled assets with high expected minutes) and Bench Boost (targeting 15 active doubled or premium fixtures).

### 2.4 Machine Learning / Surrogate Valuation Exploration
- Investigate training a lightweight predictive model or tabular value function estimating the downstream expected points of retaining a given chip state $(s_{\text{squad}}, \text{chips\_remaining}, t)$ to provide fast, exact Bellman-style lookahead valuations.

---

## 3. Scope of Multi-Season Empirical Study

The V1.4.5 milestone will conduct a comprehensive empirical ablation across all 5 historical seasons (`2021-22` to `2025-26`):

1. **Ablation Matrix**:
   - Baseline Control: Current heuristic `SeasonalChipPolicy` (with known wastage/premature burn pathologies).
   - Variant C1: Linear window-decay heuristic model.
   - Variant C2: Full dynamic-programming EV opportunity-cost planner.
   - Variant C3: ML / surrogate-value chip policy.
2. **Evaluation Metrics**:
   - 5-season mean total points across Track B (With Chips).
   - Chip return surplus ($\text{Track B} - \text{Track A}$).
   - Wastage rate (% of simulations finishing with unplayed chips).
   - Premature burn rate (% of Free Hits deployed within $\le 2$ GWs of Wildcard or GW1).
   - Reproducibility & parity: Zero deviation between GUI Chip Strategy recommendation and simulation execution.

---

## 4. Deliverables

- `src/fpl_manager/simulation/chip_optimizer.py`: New unified chip optimization engine.
- Reconciled `/api/chips` and `/api/historical/simulations/<id>/chips` endpoints.
- Full 5-season ablation benchmark report in `reports/v145/`.
- Audited final chip engine deployed to both live and historical modes.
