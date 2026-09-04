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
  - Stores chosen Starting XI, primary captain (C), vice-captain (VC), ordered bench, chips played, transfer moves, and transfer hits.
  - Automatically captures point-in-time baseline model recommendations (`decision_recommendations` table) alongside manager choices to track human vs model divergences.
  - Pre-validates complete squad legality and formation rules before persistence.
  - Allows recording post-matchday actual points scored (`--actual-points`) to evaluate decision quality over time.
- **Model Backtesting & Accuracy Evaluation Engine (`src/fpl_manager/evaluation.py` / `fpl evaluate`)**:
  - Point-in-time historical backtesting comparing predicted expected points (xP) vs actual points scored.
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
  - Scans upcoming calendar events to automatically identify Blank Gameweeks (`BLANK`), Double Gameweeks (`DOUBLE`), and combined events (`BLANK_AND_DOUBLE`).
  - Quantifies squad impact: counts blanking and doubling assets in the manager's current 15-player squad.
  - Models empirical chip valuations across remaining gameweeks for Wildcard, Free Hit, Bench Boost, and Triple Captain.
  - Generates conflict-free multi-gameweek deployment schedules respecting manager's consumed chips (`--used-chips`) and writes `reports/chip_strategy.json`.

Remaining:

- None. Ready for V0.5.

### V0.5 — optional LLM integration & live matchday analytics

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
