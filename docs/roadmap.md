# FPL Manager roadmap

> **Living document.** This is the source of truth for delivery status and priorities. Human contributors and AI agents must read it before material work and update it when priorities or milestone status changes. See [architecture.md](architecture.md) for the project's purpose and architecture.

## Delivery phases

### V0.1 — trustworthy FPL data and rules foundation

Scope:

- Download official FPL `bootstrap-static` and `fixtures` data.
- Preserve timestamped raw payloads and normalized SQLite snapshots locally.
- Represent players and validate a complete 15-player squad.
- Validate a legal 11-player starting lineup and formation.
- Generate a machine-readable snapshot summary.

Status: **V0.1 completed on 2026-09-03.**

Completed:

- Python package scaffold using Python 3.12.
- `fpl update` and `fpl report` CLI commands.
- Local SQLite snapshot store and raw-data archive.
- Deterministic squad and starting-lineup rule validation.
- Initial rule tests.
- Private, Git-ignored current-squad JSON format and committed example template.
- Deterministic transfer validation, including position, bank, club-limit, and transfer-hit checks.
- CLI command for validating proposed transfers against the latest saved FPL snapshot (supporting integer IDs and `-n` name resolution).
- SQLite persistence test coverage.
- Automatic squad import utility script (`scripts/import_squad.py` and `fpl import-squad`) to populate `config/current_squad.json` from `players.txt`.
- Real transfer-validation smoke testing against live private squad configuration.

### V0.2 — decision-support basics

Status: **V0.2 completed on 2026-09-03.**

Completed:

- Detailed Current-squad report (`fpl squad` / `fpl squad-report`), calculating individual player purchase/current/selling prices, team breakdown, bank value, remaining chips, free transfers, and hard squad rule validation (`reports/squad_report.json`).
- Fixture analysis and transparent FDR difficulty rankings (`fpl fixtures`), supporting multi-gameweek tickers, team difficulty ranking, and `--squad-only` filtering (`reports/fixtures_report.json`).
- Automated legal transfer candidate generator (`fpl suggest-transfers` / `fpl options`), evaluating 1-, 2-, and 3-transfer moves under budget, position, and club limits, ranking options by net expected points (xP) improvement and FDR (`reports/transfer_suggestions.json`). *(Note: transfers are currently capped at max 3 moves due to performance; 4-transfer search proved too slow under brute-force combination and we may revisit 4+ transfer moves tomorrow or in V0.3 with an optimized ILP/branch-and-bound solver).*
- Transparent, deterministic expected-points (xP) baseline model combining price-tier prior, sample-size weighted form blending, official availability status discounting, position-aware FDR difficulty adjustments, and home/away venue multipliers (`src/fpl_manager/expected_points.py`, documented in `docs/expected_points.md`).
- Matchday Starting-XI and captaincy options generator (`fpl lineup` / `fpl starting-xi` / `fpl captain`), evaluating all legal outfield formation distributions, selecting optimal primary Captain (2x) and Vice-Captain, ordering substitutes, independently verifying formation legality against `rules.py`, and writing `reports/lineup_report.json`.

Remaining:

- None. Ready for V0.3.

### V0.3 — projections and optimisation

Status: **V0.3 completed on 2026-09-04.**

Completed:

- **Expanded Data & Storage Architecture**: Added underlying Opta metrics (`expected_goals`, `expected_assists`, `expected_goal_involvements`, `expected_goals_conceded`, per-90 metrics, `minutes`, `starts`, `bps`, `ict_index`, `news`) and an `events` table for gameweek deadlines with zero-downtime automatic SQLite schema migrations.
- **Component-Based Projection & Uncertainty Engine**: Built minutes prediction ($xM$, $P(\text{start})$, $P(\ge 60)$), component-based $xP$ calculation (Appearance + Attacking $xGI$ + Defensive clean sheet / concession penalties + BPS), and uncertainty distributions ($xP_{\text{floor}}$ 10th percentile, $xP_{\text{ceiling}}$ 90th percentile, standard deviation $\sigma$). Introduced risk profiles: `neutral` (mean xP), `floor` (safe rank preservation), and `ceiling` (differential upside).
- **Combinatorial Mathematical Optimizer (`src/fpl_manager/optimizer.py`)**:
  - Fast recursive **branch-and-bound** multi-transfer solver supporting 1 to 5 transfers. Employs symmetry breaking ($j > i$ for identical positions) and upper-bound heap pruning, solving 4-transfer moves across the entire Premier League in ~0.3s without external solver dependencies.
  - Multi-stage **Wildcard and Free-Hit squad optimizer** (`solve_wildcard` / `fpl wildcard`) using feasible greedy initialization, 1-opt upgrading, and 2-opt cross-position local search to produce legal 15-player squads and optimal Starting XIs in ~0.05s.
- **Multi-Gameweek Planning Roadmap (`src/fpl_manager/planner.py` / `fpl plan`)**:
  - Beam search decision engine evaluating rolling transfer sequences across 3 to 6 gameweeks.
  - Explicitly models the trade-offs of rolling a transfer, banking up to 5 FTs, using 1 or 2 FTs, or taking targeted -4pt hits.
  - Supports `--no-hits` mode and risk profiles (`neutral`, `floor`, `ceiling`), generating detailed weekly timelines and alternative strategic trajectories (`reports/transfer_plan.json`).

Remaining:

- None. Ready for V0.4.

### V0.4 — evaluation, research, and strategic risk

Status: **V0.4 completed on 2026-09-04.**

Completed:

- **Pre-Deadline Decision Logging & Audit Trail (`src/fpl_manager/decision_log.py`)**:
  - Persistent, immutable record of manager choices before every deadline (`fpl log-decision`, `fpl decisions`).
  - Gameweek-linked squad state: `current_squad.json` includes an explicit `gameweek` field linking team validity to the manager's active gameweek.
  - Differentiates past gameweek logging (`gameweek < current_squad.gameweek`) from current decisions:
    - When logging decisions for a past gameweek, managers can enter players who were on the team at that time without requiring them to be in `current_squad.json` (e.g. trading Amad for Tielemans in GW2 when `current_squad.json` is at GW3).
    - Past gameweek logging records the decision in SQLite for auditing and evaluation with `fpl evaluate` while preserving `current_squad.json` untouched.
    - Explicit full 15-player squad input supported via `--squad-players`.
    - Current gameweek logging applies transfers directly and updates `current_squad.json` (player IDs, purchase prices, bank value, remaining chips, free transfers, and active gameweek).
  - Supports custom Starting XI (`--starters`), ordered bench (`--bench`), captain (`--captain` / `-c`), and vice-captain (`--vice-captain` / `--vc`) with fuzzy name resolution, or defaults to the model's optimized selection.
  - Supports recording executed transfers (`--transfer` / `-t OUT:IN`), updating squad membership dynamically and automatically calculating transfer hits.
  - Automatically captures point-in-time baseline model recommendations (`decision_recommendations` table) alongside manager choices to track human vs model divergences.
  - Pre-validates complete squad legality and formation rules before persistence.
  - Allows recording post-matchday actual points scored (`--actual-points`) to evaluate decision quality over time.
- **Official Matchday Live Scores Ingestion (`src/fpl_manager/scores.py` / `fpl update-scores`)**:
  - Retrieves official player scores and performance statistics directly from the FPL API (`event/{gw}/live/`).
  - Caches scores in local SQLite table `player_gameweek_scores` and saves raw timestamped payloads in `data/raw/`.
  - Supports offline fallbacks and graceful handling during future or incomplete gameweeks.
- **Model Backtesting & Accuracy Evaluation Engine (`src/fpl_manager/evaluation.py` / `fpl evaluate`)**:
  - Point-in-time historical backtesting comparing predicted expected points (xP) vs actual points scored.
  - Automatically retrieves actual scores from local cache / FPL API when `--scores` is omitted, and auto-finalizes decisions.
  - Statistical metrics: Mean Absolute Error (MAE), Root Mean Squared Error (RMSE), and Spearman Rank Correlation ($\rho$) with tied-rank handling.
  - Uncertainty interval calibration: evaluates the empirical coverage percentage of players falling inside predicted $[xP_{\text{floor}}, xP_{\text{ceiling}}]$ confidence bounds.
  - Manager Regret Analysis: calculates Captaincy Regret (points lost compared to optimal captain in Starting XI) and Bench Regret (points stranded on bench compared to lowest-scoring starter).
  - Human vs Model Divergence Analysis: evaluates actual lineup score delta between manager's chosen XI and the model's recommended XI.
  - Multi-Gameweek & Season Evaluation: aggregated accuracy report (`reports/evaluation_summary.json`) tracking systematic model bias (over-/under-prediction).
- **Effective Ownership (EO) & Strategic Risk Index (`src/fpl_manager/ownership.py` / `fpl ownership` / `fpl risk`)**:
  - Models competitive captaincy distribution across the player pool and computes Effective Ownership ($EO = \text{Ownership} + \text{Captaincy}$).
  - Classifies assets into strategic roles:
    - `SHIELD`: High EO ($\ge 40\%$) template preservation assets protecting rank against common hauls.
    - `SWORD`: Low EO ($< 15\%$) differential assets with high xP or ceiling potential providing massive rank acceleration.
    - `CORE`: Balanced mid-ownership assets ($15\% \le EO < 40\%$).
  - Calculates manager's Net Rank Exposure per player: $+60\%$ to $+100\%$ positive rank leverage when starting/captaining, and negative exposure (rank drag) for non-owned template threats.
  - Integrated into matchday lineup report (`fpl lineup`), displaying strategic category and EO next to every starter.
- **Chip Strategy & Blank / Double Gameweek Planner (`src/fpl_manager/chip_strategy.py` / `fpl chip-strategy`)**:
  - Automatically segments the season into Gameweeks 1-19 (First Half) and Gameweeks 20-38 (Second Half), constraining planning horizons strictly within the active segment.
  - Automatically resets all chips (`wildcard`, `freehit`, `benchboost`, `triplecaptain`) after Gameweek 19, ignoring any chips used in the first half when evaluating the second half.
  - Detects chips used in the active segment from persistent decision logs (`decisions` table in SQLite) with manual override via `--used-chips`.
  - Scans upcoming calendar events to automatically identify Blank Gameweeks (`BLANK`), Double Gameweeks (`DOUBLE`), and combined events (`BLANK_AND_DOUBLE`).
  - Quantifies squad impact: counts blanking and doubling assets in the manager's current 15-player squad.
  - Models empirical chip valuations across remaining gameweeks for Wildcard, Free Hit, Bench Boost, and Triple Captain.
  - Generates conflict-free multi-gameweek deployment schedules and writes `reports/chip_strategy.json`.

Remaining:

- None. Ready for V0.5.

### V0.5 — Graphical User Interface (GUI) & Multi-Team Management

Status: **In Progress / Current Milestone.**

Scope & Architecture:

1. **Multi-Team Management Core (`src/fpl_manager/teams.py`)**:
   - Support multiple squads/teams stored under `config/teams/<team_id>/` (or SQLite `teams` table).
   - Each team maintains:
     - Squad state (`squad.json`): player IDs, purchase prices, bank, free transfers, remaining chips, active gameweek.
     - Team metadata (`metadata.json` or DB record): team name, manager name, FPL team ID, created timestamp.
     - Scoped historical decision audit logs and post-gameweek evaluations linked to `team_id`.
   - Team Management API and CLI:
     - `create_team(name, squad_data)`: create a new team from scratch, example template, or player import.
     - `list_teams()`: list all registered teams and their active gameweek/bank.
     - `load_team(name_or_id)`: switch the global active team pointer (`config/active_team.json`).
     - Backwards compatibility: seamless fallback to `config/current_squad.json` as the default team (`"default"`).

2. **Interactive GUI Application (`src/fpl_manager/gui/` / `fpl gui`)**:
   - Provide a visual, interactive dashboard for all core FPL decision engine capabilities.
   - Built with a clean, responsive, local web interface (or lightweight desktop framework) launched effortlessly with `fpl gui`:
     - **Team Switcher & Creator Bar**:
       - Dropdown to instantly switch active teams.
       - "New Team" modal: create team, assign initial 15 players, set budget, bank, and starting gameweek.
     - **Dashboard & Football Pitch View**:
       - Visual formation pitch (e.g. 3-4-3, 3-5-2, 4-4-2, etc.) rendering starting XI cards and ordered bench substitutes.
       - Player cards display player photo/jersey, web name, position, next fixture + FDR badge, predicted xP, uncertainty bounds ($xP_{\text{floor}}$–$xP_{\text{ceiling}}$), and Effective Ownership role badge (`SHIELD`, `SWORD`, `CORE`).
       - Captain (C) and Vice-Captain (VC) visual indicators.
       - Team status HUD: Bank, Team Value, Free Transfers, Remaining Chips, Active Gameweek.
     - **Interactive Decision Logging Panel**:
       - Record pre-deadline decisions for both current and past gameweeks.
       - Drag/select starting 11, bench ordering, captain, and vice-captain.
       - Interactive transfer builder: search players with autocomplete, preview hits and budget delta, log `-t OUT:IN`.
       - Visual feedback badge: "Current squad updated" vs. "Past gameweek recorded for evaluation".
     - **Transfer Recommendations Visualizer**:
       - Ranked cards for 1- to 5-transfer moves with projected net gain ($\Delta xP - \text{Hits}$), FDR ticker, and "Apply to Squad" one-click action.
     - **Wildcard & Free-Hit Optimizer Studio**:
       - Interactive sliders for squad budget and risk profile (`neutral`, `floor`, `ceiling`).
       - Side-by-side comparison of current squad vs optimized 15-player squad.
     - **Multi-Gameweek Transfer Planning Roadmap**:
       - Visual timeline across a 3–6 gameweek horizon showing recommended moves, banked transfers, hit costs, and cumulative xP curves.
     - **Chip Strategy & Fixture Calendar**:
       - Interactive matrix of all 38 gameweeks highlighting Blanks and Doubles.
       - Visual roadmap for First Half (GW1–19) and Second Half (GW20–38) with empirical chip valuations and deployment sequence.
     - **Evaluation & Regret Performance Hub**:
       - Post-matchday actual scores, captaincy regret analysis, bench regret, model calibration curves, and human vs. model comparison.

Remaining:
- [ ] Task 1: Multi-team storage abstraction, team creation, team switching, and team-scoped decision persistence.
- [ ] Task 2: GUI server / application architecture and routing (`fpl gui` entry point).
- [ ] Task 3: Team switching, team creation modal, and squad HUD.
- [ ] Task 4: Interactive pitch lineup visualizer and formation engine.
- [ ] Task 5: Decision logger view (current + past gameweeks, trades, captaincy, notes).
- [ ] Task 6: Transfer recommendations, Wildcard/Free-Hit studio, and multi-GW planner views.
- [ ] Task 7: Chip strategy calendar and post-gameweek evaluation performance hub.
- [ ] Task 8: End-to-end integration tests and documentation.

### V0.6 — optional LLM integration & live matchday analytics

- Generate structured analytical packages from deterministic data and reports.
- Start with human + LLM review of those artifacts.
- API-based LLM analysis advisory layer evaluating narrative sentiment, injury press conferences, and tactical setups.
- Real-time live matchday points and rank simulation tracker.
- All LLM suggestions remain advisory and must be validated before presentation.

## Working conventions

- Use the Conda environment named `fbl` with Python 3.12.
- Install the project with `pip install -e ".[dev]"`.
- Keep generated data, SQLite databases, raw API payloads, and reports out of Git unless a deliberately curated example fixture is needed for tests.
- Prefer small, tested changes that preserve deterministic validity checks.
- Update this document when completing a milestone, adding a major subsystem, or changing priorities.
