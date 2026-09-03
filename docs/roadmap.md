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

- Expected-minutes and fixture-adjusted projection models.
- Squad, transfer, starting-XI, and captain optimisation under all hard rules.
- Multiple-gameweek planning and strategic flexibility.
- Uncertainty-aware outputs, rather than single point estimates only.

### V0.4 — evaluation and research

- Historical snapshots and backtesting that use only information available at each historical point.
- Decision logging and model evaluation.
- Analysis of quantitative, LLM, and human overrides.
- Chip strategy, blank/double gameweek planning, and ownership/rank-aware risk.

### V0.5 — optional LLM integration

- Generate structured analytical packages from deterministic data and reports.
- Start with human + ChatGPT/Codex review of those artifacts.
- Consider API-based LLM analysis only after the underlying data, validation, and model outputs are trusted.
- All LLM suggestions remain advisory and must be validated before presentation.

## Working conventions

- Use the Conda environment named `fbl` with Python 3.12.
- Install the project with `pip install -e ".[dev]"`.
- Keep generated data, SQLite databases, raw API payloads, and reports out of Git unless a deliberately curated example fixture is needed for tests.
- Prefer small, tested changes that preserve deterministic validity checks.
- Update this document when completing a milestone, adding a major subsystem, or changing priorities.
