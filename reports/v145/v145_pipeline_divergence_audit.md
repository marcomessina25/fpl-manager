# V1.4.5 Pipeline Divergence Audit: Live Advisor vs Historical Simulator

**Release**: V1.4.5  
**Topic**: Disconnected Valuation Engines & Architectural Divergence Audit  
**Date**: October 2026  

---

## 1. Executive Summary

Prior to V1.4.5, the live decision advisor (`src/fpl_manager/chip_strategy.py`) and historical simulation engine (`src/fpl_manager/simulation/session.py` / `src/fpl_manager/backtest/engine.py`) executed conflicting valuation logic for identical squad states and fixture schedules. This divergence destroyed reproducibility between GUI recommendations and simulation replays.

---

## 2. Divergence Matrix

| Dimension | Live Advisory Engine (`chip_strategy.py`) | Historical Simulator (`SeasonalChipPolicy`) | Divergence Impact |
| :--- | :--- | :--- | :--- |
| **Primary Valuation Model** | Heuristic fixture rating peaks (`evaluate_chip_candidates`) | Instantaneous threshold gates (`evaluate_gameweek_chip`) | **Conflicting Decisions**: Live planner suggests deploying a chip in GW X, while simulator rejects it at runtime. |
| **Wildcard Trigger** | Top fixture rating delta over multi-GW window | Requires $\ge 4$ simultaneous deteriorated squad assets | **100% Hoarding in Sim**: Simulator never triggers Wildcard while Live UI repeatedly suggests it. |
| **Free Hit Evaluation** | Multi-gameweek fixture concentration rating | Requires $\le 8$ active playing players | **Schedule-blind**: Sim ignores fixture swings; Live planner ignores squad transfer flexibility. |
| **Window Boundary Logic** | Hardcoded Segments (1-19, 20-38) with greedy allocation | Hardcoded Segments with threshold relaxation at GW 18/19/37/38 | **Uncoordinated Timing**: Roadmap displays chips in mid-season; execution dumps them at deadline. |
| **API Endpoints** | `/api/chips` | `/api/historical/simulations/<id>/chips` | **UI Inconsistency**: Users viewing live vs historical tabs receive contradictory strategies. |

---

## 3. Scope note

This audit is a **code-level** comparison of the two decision paths (`recommend_chip_strategy` rating-based roadmap vs. `SeasonalChipPolicy` threshold gates). No per-state numeric divergence was measured; earlier illustrative case studies were removed because they were not derived from data.

---

## 4. Unification Mandate for V1.4.5

To eliminate this divergence, V1.4.5 unifies all chip evaluations behind a single canonical engine:
- `src/fpl_manager/simulation/chip_optimizer.py` provides `ChipOpportunityOptimizer`.
- Both `/api/chips` and `/api/historical/simulations/<id>/chips` query this optimizer.
- `SeasonalChipPolicy` in historical simulations is updated to wrap or delegate to `ChipOpportunityOptimizer`.
- Recommendations output full mathematical audit metadata (`immediate_ev`, `future_max_ev`, `net_utility`, `confidence`, `reasoning`).
