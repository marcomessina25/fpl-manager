# Gemini Coding Guidelines & Architectural Directives

> **PERMANENT CORE MANDATE FOR GEMINI & AI AGENTS:**
> **STRICT 1:1 FUNCTIONAL AND VISUAL CORRESPONDENCE BETWEEN "LIVE MANAGER" AND "HISTORICAL TIME MACHINE" MODES.**

---

## 1. The 1:1 Parity Golden Rule

Whenever designing, extending, refactoring, or testing features across FPL Manager, **there must be a strict 1:1 correspondence between the "Live Manager" (2026/27) and "Historical Time Machine" modes**:
1. **Identical Interfaces & Controls**: Any tab, tool, dropdown, solver, or slider available in Live Manager must be available in Historical Time Machine mode with the exact same functionality, styling, and options.
2. **Never Degrade Historical Mode**: Historical Time Machine mode is not a simplified sandbox. It is a full retrospective simulation laboratory with full solver capabilities. Never replace combinatorial optimization or beam-search planning with a stripped-down manual fallback.
3. **Clean Session & Data Isolation**: Historical mode must strictly operate on the currently selected historical simulation session (`session_id`). Live 2026/27 SQLite database tables and active team files must **NEVER** leak into or be queried by historical mode.
4. **Zero Future Leakage**: In Historical mode, predictions, projections, standings, fixtures, and evaluations must strictly reflect point-in-time knowledge up to the active simulation gameweek (`current_gw`). Never reveal or use future matchday outcomes.

**Intentional live-only exceptions:** Live Matchday and AI Advisor & Briefing are hidden in Historical mode. Preserve this existing behavior. The parity requirement applies to shared workflows; it does not authorize live-data or LLM calls from Historical mode.

---

## 2. Tab-by-Tab Parity Specifications

### Transfers & Staging (`#tab-transfers`)
- **Shared Unified Architecture**: Both Live Manager and Historical Time Machine share `#live-transfers-wrapper`.
- **Combinatorial Solvers**: Must support solving 1 to 5 transfers (`#tx-num`), horizons from 1 to 10 gameweeks (`#tx-gws`), and risk profiles (`neutral`, `floor`, `ceiling`). GUI calculations use the latest registered decision engine without a version selector in either mode. Legacy engine selection remains available for explicit CLI/research use; existing frozen simulation baselines must retain their recorded version.
- **Proposition Cards**: Solvers output ranked candidates (`#1 Best Move`, etc.) with xP deltas, post-move bank amounts, reason badges (`Lineup xP`, `Pool Expansion`, `GK Suppression`, `Horizon Gain`), and an interactive **⚡ Apply Move** button.
- **Manual Transfers Prohibition**: Manual transfer dropdowns (e.g., sell player X, buy player Y) must **NEVER** live on the Transfers tab. They belong exclusively under Decision Logger.

### Decision Logger (`#tab-decisions`)
- **Section 1 (Executed Transfers & Trades)**: Manual trades are staged and executed here (`#tx-exec-out`, `#tx-exec-in`, `#available-players-datalist`, `#btn-execute-trade`). In Historical mode, the dropdowns and autocomplete datalist strictly pull from the historical simulation squad and historical player pool.
- **Section 2 (Matchday Strategic Decision & Instructions)**: Captaincy, Vice-Captaincy, Chip selection, hits, actual points, and manager rationale notes.
- **Season Decision History (`#decisions-list`)**: Must display logged decisions exclusively for the active historical simulation session (`/api/decisions?session_id=<sid>`). Never display live SQLite team logs in Historical mode.

### Multi-GW Planner (`#tab-planner`)
- **Beam Search Roadmap**: Generates rolling multi-gameweek trajectories across horizons (1 to 8 gameweeks).
- **Player Attribute Contract**: Historical squad player representations must always provide both `id` and `player_id` to ensure compatibility across planners and lineup solvers without raising `KeyError: 'id'`.
- **Apply Next Step**: Interactive **⚡ Apply GW[N] Move** applies step 0 transfers, captain, and lineup directly into the active historical simulation session.

### Chip Strategy & Calendar (`#tab-chips`)
- **Horizon-Wide Deployment Roadmap**: Historical chip deployment must evaluate Blank and Double gameweeks across the entire season segment (GW1–19 for First Segment, GW20–38 for Second Segment).
- **Conflict-Free Scheduling**: Recommends optimal deployment gameweeks for Triple Captain, Bench Boost, Free Hit, and Wildcard based on fixture topology and double gameweeks. It must **NEVER** default to `"No chips recommended in current horizon."` simply because a chip is not triggered on the exact current gameweek.

### Strategic Studio (`#tab-strategic`)
- **Pre-Season & Initial Squad Solving**: Solves full 15-player squads under budget using MIP/knapsack optimization, supporting both historical seasons (e.g., 2023-24, 2022-23) and live 2026/27 data.
- **1-Click Apply**: Applying candidates into an active historical simulation session initializes or reconfigures the historical team cleanly.

---

## 3. Implementation Checklist for Future Changes
Before finishing any task touching GUI, APIs, or solvers:
- [ ] Are both modes (`state.appMode === "live"` and `state.appMode === "historical"`) supported?
- [ ] Does switching between modes preserve state and properly populate squad / player pools?
- [ ] Are manual transfers isolated to Decision Logger?
- [ ] Does `/api/decisions?session_id=...` return only simulation-specific decisions?
- [ ] Does `/api/plan?session_id=...` run smoothly without schema errors?
- [ ] Does `/api/historical/simulations/<sid>/chips` return a full deployment schedule?
- [ ] Have regression tests in `tests/test_historical_gui_api.py` and `tests/test_historical_simulation.py` been executed and passed?
