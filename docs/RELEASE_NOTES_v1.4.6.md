# Release Notes — V1.4.6: Historical Parity & Live Manager Integrity Hardening

## Overview
**Version**: 1.4.6  
**Branch**: `v146`  
**Purpose**: Eliminate model rate anomalies in Live Manager, restore state integrity for Team Marco, deliver strict 1:1 functional & visual parity between Live Manager and Historical Time Machine, and refine Strategic Squad Studio constraint management and gameweek horizon breakdowns.

---

## 1. Live Manager Integrity & Carvalho Anomaly Fix
- **Rate Clamping in Expected Points Engine (`src/fpl_manager/expected_points.py`)**:
  - Implemented upper bound sanity guards on baseline per-90 rates (`expected_goals_per_90 <= 1.20`, `expected_assists_per_90 <= 1.00`).
  - Resolved the pathology where players with micro sample sizes or skewed registry rates (e.g., Carvalho) exploded with nonsensical $+30.0$ xP projections dominating transfer suggestions.
- **Team Marco (`default`) State Restoration**:
  - Cleaned premature / corrupted GW6+ decision records in `data/fpl.sqlite3` that caused Live Manager to falsely skip GW6 and display GW7 as current.
  - Restored squad state in `config/teams/default/squad.json` to the pre-deadline state for GW6 with £1.3m in bank and 1 available free transfer.

---

## 2. 1:1 Parity: Live Manager ⟷ Historical Time Machine
- **Transfers & Staging**:
  - Historical mode now supports full combinatorial transfer exploration (1–5 transfers, horizon selection, risk profiles, engine selection, and "Apply Move" staging into simulation session).
  - Wired `/api/transfers` with `session_id` support using `load_historical_players_meta` and zero-leakage `analyze_historical_fixtures`.
- **Decision Logger in Historical Mode**:
  - Decision Logger tab is fully active in both Live Manager and Historical modes.
  - Automatically logs matchday decisions upon matchday resolution (`run_gameweek()`).
  - Automatically logs the initial squad selection as GW1 decision (`initial_decision`).
  - Automatically collapses chained intra-gameweek transfers ($A \to B \to C \implies A \to C$).
  - `/api/decisions` and `/api/evaluate` endpoints fully support `session_id`.
- **Multi-GW Planner & Chip Strategy**:
  - Planner tab enabled in Historical mode with `session_id` routing, allowing multi-step roadmaps to be generated and applied directly to historical simulation sessions.
  - Chip strategy calendar fully wired to historical simulation sessions.
- **Pitch & Lineup Parity**:
  - Historical pitch displays point-in-time projected expected points (`xP`) before matchdays (instead of `0p`).
  - Substitutions on the pitch swap starters and bench players rather than triggering transfers.
  - Displays actual scores for completed gameweeks and projected xP for upcoming gameweeks.
- **Undo / Revert Gameweek**:
  - Added deterministic matchday undo (`/api/decisions/undo` with `session_id`), cleanly reverting simulation squad, bank, free transfers, and chips to the prior gameweek.

---

## 3. Strategic Squad Studio Fixes
- **Constraint Management & Visual Feedback**:
  - Fixed issue where clearing or updating constraints retained obsolete lock indicators on cards.
  - Applied locks and constraints globally across all generated candidate profiles (Maximum EV, Balanced, Premium Heavy, Differential, etc.).
- **Gameweek-by-Gameweek Horizon Breakdown**:
  - Fixed flat duplicate xP display across future gameweeks.
  - Populated point-in-time fixture difficulties and projections across target gameweeks (`gw_breakdown_xp`), reflecting fixture swings and blank/double gameweeks accurately.

---

## 4. Verification & Testing
- Validated with 50 passing unit and integration tests across:
  - `tests/test_historical_simulation.py`
  - `tests/test_expected_points.py`
  - `tests/test_strategic_squad_engine.py`
  - `tests/test_transfers.py`
- Validated with 31 passing GUI API tests across:
  - `tests/test_historical_gui_api.py`
  - `tests/test_gui.py`
  - `tests/test_strategic_squad_gui.py`
