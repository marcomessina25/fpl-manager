# Items Left for V1.3.5 — Optimizer Decision-Quality Study

**Milestone:** V1.3.5  
**Branch:** `v135`  
**Parent / Baseline:** `master` (V1.2.5 frozen baseline + V1.3 GBDT challenger)  
**Primary Research Question:** *Given the same quantitative projections, which optimizer mechanisms actually improve realized FPL decisions?*

---

## Work Breakdown & Status

- [x] **P0: Git Branch & Workspace Initialization**
  - [x] Fetch `origin/master` (includes PR #18 V1.3 merge).
  - [x] Branch `v135` created from `origin/master`.
  - [x] Clean workspace verification.

- [x] **P1: Optimizer Ablation Framework (`src/fpl_manager/backtest/optimizer_ablation.py`)**
  - [x] Define `OptimizerAblationConfig` specifying:
    - Horizon: $H \in \{1, 3, 5, 8\}$
    - Bench weight: $W_{\text{bench}} \in \{0.0, 0.15\}$
    - Goalkeeper hurdle: $\text{GK}_{\text{hurdle}} \in \{0.50, 3.00\}$
    - Candidate pool: $N_{\text{pool}} \in \{5, 15, 25\}$
    - Flexibility / Dead capital: $W_{\text{dead}} \in \{0.0, 3.0\}$
    - Dynamic chip awareness: $\text{Chip}_{\text{aware}} \in \{\text{False}, \text{True}\}$
  - [x] Define canonical ablation variants $B_0$ through $B_7$ + Full.
  - [x] Implement `DecisionEngineAblation` with parameterized mechanics.
  - [x] Register `b0`...`b7`, `v1.3.5` in `resolve_decision_engine`.

- [x] **P2: Decision-Regret Framework & Mathematical Decomposition**
  - [x] Define `DecisionRegretRecord`:
    - `selected_action`, `best_action_model`, `best_action_hindsight`
    - `realized_selected_points`, `realized_best_model_points`, `realized_hindsight_points`
  - [x] Implement mathematical decomposition:
    - $\text{Prediction Regret} = \text{Realized Hindsight} - \text{Realized Best Model}$
    - $\text{Optimizer Regret} = \text{Realized Best Model} - \text{Realized Selected}$
    - $\text{Total Decision Regret} = \text{Realized Hindsight} - \text{Realized Selected}$
    - Invariant: $\text{Prediction Regret} + \text{Optimizer Regret} \equiv \text{Total Decision Regret}$
  - [x] Implement `compute_gameweek_decision_regret(...)` with invariant tolerance check.

- [x] **P3: Starting-State Factorial Experiment**
  - [x] State A: V1.0 heuristic GW1 squad construction.
  - [x] State B: V1.1 strategic squad balanced construction.
  - [x] State C: Alternative strategic profile (`maximum_ev`).
  - [x] Evaluated downstream trajectory under fixed optimizer ($B_7$ / V1.2.5) at GW1, GW5, GW10, and GW38.
  - [x] Result: State C (`maximum_ev`) unlocks +93 net points over balanced initial construction on 2024-25.

- [x] **P4: Multi-Season Ablation Execution Script (`scripts/run_v135_ablation.py`)**
  - [x] Fast CLI runner supporting `--seasons`, `--variants`, `--fast`, `--output-dir`.
  - [x] Measure runtime performance budget: median ms/GW, p95 ms/GW.
  - [x] Export all required deliverables to `reports/v135/`:
    - `experiment_manifest.json`
    - `optimizer_ablation.csv` & `.md`
    - `season_matrix.csv`
    - `regret_analysis.csv` & `.md`
    - `runtime_analysis.csv`
    - `final_summary.md`

- [x] **P5: Test Suite Verification (`tests/test_optimizer_ablation.py`)**
  - [x] Test $B_0$ through $B_7$ configuration factory.
  - [x] Test horizon scaling ($H=1$ vs $H=3$ vs $H=5$).
  - [x] Test bench-aware vs XI-only objective values.
  - [x] Test goalkeeper transfer hurdle suppression.
  - [x] Test candidate pool size bounds.
  - [x] Test exact mathematical regret identity.
  - [x] 100% test pass rate (13/13 unit tests; 451/451 full regression suite).

- [x] **P6: Hardened Engine Deployment & V1.4 Handoff Finalization**
  - [x] Update `docs/v1.3.5/v135.md` with complete empirical findings and architectural decisions 1, 2, 3.
  - [x] Implement and expose `DecisionEngineV135` synthesizing:
    - Multi-GW rolling horizon ($H=3, \gamma=0.75$) with explicit bench weighting ($W_{\text{bench}}=0.15$).
    - Role-specific goalkeeper transfer hurdle ($\text{GK}_{\text{hurdle}}=3.0$).
    - Constrained candidate search pool ($N=5$) mitigating prediction regret / search breadth overfitting.
    - Default `maximum_ev` initial squad construction.
  - [x] Route `resolve_decision_engine("v1.3.5")` and alias variants.
  - [x] Verify complete test suite (15/15 unit tests passing).
  - [x] Ready for V1.4 interactive simulation platform and human-in-the-loop benchmark.

