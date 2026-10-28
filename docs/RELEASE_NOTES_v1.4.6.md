# Release Notes — V1.4.6: Historical Parity, Solver Hardening & Human Benchmark Study

## Overview
- **Version**: 1.4.6
- **Branch**: `v146`
- **Scope**: Multi-Season Human-in-the-Loop Replay Benchmark, Full 1:1 Live vs. Historical Parity, Solver Hardening, and Comprehensive Rule Integrity.

---

## 1. Multi-Season Performance Summary: Human-Assisted vs. Frozen Engine Baseline

Across all 5 audited historical seasons (`2021-22` through `2025-26`, 190 simulated gameweeks), human decision-making operating with full point-in-time algorithmic assistance (Track B: Human + Engine Advisory) was evaluated directly against the autonomous reference engine (Track A: Frozen `v1.3.5` + `ChipOpportunityOptimizer`):

| Season | Track B (Human + Engine) | Track A (Frozen Engine Baseline) | Decision Alpha (H − E) | Outcome |
| :--- | :---: | :---: | :---: | :---: |
| **2021-22** | **1,976 pts** | 1,889 pts | **+87 pts** | Human WIN |
| **2022-23** | **2,073 pts** | 1,951 pts | **+122 pts** | Human WIN |
| **2023-24** | **2,126 pts** | 2,214 pts | **-88 pts** | Engine WIN |
| **2024-25** | **2,218 pts** | 2,098 pts | **+120 pts** | Human WIN |
| **2025-26** | **2,117 pts** | 2,040 pts | **+77 pts** | Human WIN |
| **5-Season Mean** | **2,102.0 pts** | 2,038.4 pts | **+63.6 pts** | **4 / 5 Seasons (80.0%)** |

### Key Empirical Findings:
1. **Positive Decision Alpha (+63.6 pts Mean)**: Human managers paired with algorithmic decision support outperformed the autonomous frozen baseline in 4 out of 5 seasons (80.0%), proving strong synergy between quantitative models and human tactical intuition.
2. **Context-Sensitive Overrides**: Human managers achieved their highest alpha during turbulent, high-absence, and rescheduling-heavy seasons (+122 pts in 2022-23, +120 pts in 2024-25, +87 pts in 2021-22), successfully avoiding low-minute rotation risks.
3. **Template Outlier Protection**: The autonomous engine edged human managers only in 2023-24 (-88 pts), where algorithmic greedy holding of template assets during sustained scoring streaks proved optimal.

---

## 2. Comprehensive Bug Fix Dossier (Fixed in V1.4.6)

### Bug 1: Live Manager Expected Points Rate Anomaly & Carvalho Explosion
- **Pathology**: Small-sample or skewed baseline registry rates in `ExpectedPointsProjection` caused players with minimal minutes (e.g., Carvalho) to produce nonsensical projections ($+30.0$ xP), completely distorting transfer suggestions.
- **Root Cause**: Unbounded per-90 rate scaling without baseline sanity bounds.
- **Fix**: Implemented strict per-90 rate clamping in `src/fpl_manager/expected_points.py` (`expected_goals_per_90 <= 1.20`, `expected_assists_per_90 <= 1.00`).

### Bug 2: Premature GW6+ Desynchronization for Live Team Marco (`default`)
- **Pathology**: The Live Manager interface skipped Gameweek 6 and falsely displayed Gameweek 7 as current, preventing pre-deadline actions for GW6.
- **Root Cause**: Premature decision records logged in `data/fpl.sqlite3`.
- **Fix**: Purged premature database records and restored `config/teams/default/squad.json` to the valid GW6 pre-deadline state with £1.3m bank and 1 available free transfer.

### Bug 3: Historical Time Machine Transfers Tab Divergence (Parity Violation)
- **Pathology**: Historical Time Machine had a stripped-down `#hist-transfers-wrapper` with manual transfer dropdowns and lacked combinatorial multi-transfer solving.
- **Root Cause**: Fragmented frontend architecture violating the 1:1 Parity Golden Rule.
- **Fix**: Unified both Live Manager and Historical Time Machine onto `#live-transfers-wrapper`. Added full support for 1 to 5 transfers, 1 to 10 GW horizons, risk profiles (`neutral`, `floor`, `ceiling`), and solver engines (`v1.3.5`, `v1.2.5`) with ranked proposition cards and 1-click **⚡ Apply Move**. Manual transfers were moved strictly to Decision Logger.

### Bug 4: Decision Logger Data Leakage & Manual Trade Routing
- **Pathology**: In Historical mode, Decision Logger displayed decision history from the live 2026/27 team. Manual trades could not be cleanly staged.
- **Root Cause**: `/api/decisions` defaulted to querying the active live team database without scoping by `session_id`.
- **Fix**: Scoped `/api/decisions?session_id=<sid>` strictly to the active historical simulation session. Unified manual transfer execution under Decision Logger Section 1, auto-populating from the active historical squad and historical player pool.

### Bug 5: Multi-GW Planner Schema Crash (`KeyError: 'id'`)
- **Pathology**: Generating a multi-gameweek plan in Historical mode crashed with `KeyError: 'id'`.
- **Root Cause**: Squad player representations in historical snapshots used `player_id` while the beam-search planner expected `id`.
- **Fix**: Normalized squad player dictionaries across planners and solvers to guarantee both `id` and `player_id`.

### Bug 6: Chip Strategy Horizon-Wide Deployment Roadmap
- **Pathology**: Historical Time Machine always displayed `"No chips recommended in current horizon."` when no chip was scheduled for the immediate gameweek.
- **Root Cause**: Chip evaluation was restricted to the narrow transfer horizon (3–5 GWs).
- **Fix**: Integrated `ChipOpportunityOptimizer` to evaluate fixture topology across entire season segments (GW1–19, GW20–38) for optimal placement of Triple Captain, Bench Boost, Free Hit, and Wildcard based on fixture swings and Blank/Double gameweeks.

### Bug 7: Gameweek 1 & 2 Free Transfer Rollover Rule Violation
- **Pathology**: Reaching Gameweek 3, sessions showed 3 free transfers available (`free_transfers: 3`), violating official FPL rules.
- **Root Cause**: Pre-season squad setup in FPL allows unlimited transfers; the GW1 deadline never banks a rollover into GW2. Entering GW2 must always start with exactly 1 FT. In `HistoricalSimulationSession.run_gameweek()`, post-GW1 logic applied rollover banking ($\min(5, 1 - 0 + 1) = 2$), and GW2 rolled over again ($2 - 0 + 1 = 3$).
- **Fix**: Enforced in `run_gameweek()`, `_step_baseline_engine()`, `undo_last_gameweek()`, and `load()` that entering GW2 strictly starts with `free_transfers = 1`. Any loaded session at `current_gw <= 2` with $>1$ FT is defensively clamped to 1.

### Bug 8: Staged Free Transfer & Pitch Badge Desynchronization
- **Pathology**: Staging transfers in the Historical GUI did not decrement the free transfer badge in the top HUD or pitch header before matchday execution.
- **Root Cause**: API endpoints returned static baseline free transfers rather than effective available transfers.
- **Fix**: Updated `GET /api/historical/simulations/:id`, `POST /api/historical/simulations/:id/transfers`, and `POST /api/transfers/execute` to return `free_transfers = max(0, sim.free_transfers - len(sim.transfers_staged))` and synchronized HUD/pitch elements dynamically.

### Bug 9: Misleading Gross vs. Net xP Display and Multi-GW Horizon Ambiguity
- **Pathology**: Transfer recommendation cards headlined gross horizon xP before deducting hits (e.g. displaying `+5.5 xP | Hit: -4 pts`), misleading managers into thinking 2 transfers with a hit beat 1 transfer (+1.7 xP), when after the 4-point penalty the net return was only `+1.47 Net xP`. Managers also confused the 3-GW discounted sum with a single-week projection.
- **Root Cause**: The card title rendered `scoreDisplay = opt.lineup_xp_delta` (unadjusted gross horizon sum).
- **Fix**:
  - `rescore_transfer_candidates`: Added `net_lineup_xp_delta` and `gw1_lineup_xp_delta` fields to candidate outputs.
  - `app.js`: Prominently displays **Net xP** as the primary score whenever hits are involved (e.g. `+1.5 Net xP (-4 pt hit)`), with separate badges for the 3-GW horizon lineup score and the immediate single-gameweek delta.
  - Fixed an iterable boundary bug in legacy fallback search (`cand_search_max = max(max_results)` -> `cand_search_max = max_results`).

### Bug 10: Mid-Season Real-Life Transfers Team Quota Violation (January Window)
- **Pathology**: In seasons with real-world mid-season transfers (e.g. 2025-26 January window where Marc Guéhi and Antoine Semenyo moved to Man City), squads already containing 3 City players suddenly had 5 City players. The solver proposed transfers that did not sell enough City players, leaving 4 or 5 City players in the squad (rejected as illegal by the session validator).
- **Root Cause**: `solve_transfers` only checked that incoming candidates were not from a club with $\ge 3$ players, but never checked that the remaining squad satisfied $\le 3$ players per club across all clubs.
- **Fix**:
  - `optimizer.py`: Added strict team quota pruning in `solve_transfers`. Any outgoing combination that does not reduce all club counts to $\le 3$ is immediately pruned before DFS candidate generation.
  - Added an assert safeguard at the end of DFS to prevent any illegal combination from entering the result heap.
  - `server.py` & `app.js`: Added an informative **⚠️ Team Quota Alert** banner that identifies the over-represented club, lists the excess players, and informs the manager that at least $N$ transfers selling players from that club are required to restore FPL compliance.

---

## 3. Permanent Architectural Mandate (`GEMINI.md`)

Codified `GEMINI.md` at repository root establishing the permanent architectural directive:
- **Strict 1:1 Functional & Visual Correspondence**: Every tab, control, solver, and slider in Live Manager must exist identically in Historical Time Machine mode.
- **Zero Future Leakage**: Projections, standings, and evaluations must strictly reflect point-in-time knowledge.
- **Data Isolation**: Live SQLite database tables must never leak into historical simulation sessions.

---

## 4. Verification & Test Suite Health

Full automated test suite passing with **39/39 passing tests**:
- `tests/test_historical_gui_api.py`: 10/10 passed (transfers, plan, decisions, chips, status endpoints).
- `tests/test_historical_simulation.py`: 14/14 passed (GW1/GW2 rollover rules, session state isolation, undo safety).
- `tests/test_v125_live_wiring.py`: 7/7 passed (v1.2.5/v1.3.5 baseline scoring, legacy fallback, GK hurdle invariants).
- `tests/test_rules.py`: 8/8 passed (squad legality, formation quotas, mid-season excess team quota pruning).
