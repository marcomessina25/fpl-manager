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

Status: **in progress — core implementation completed and live data successfully downloaded on 2026-09-03.**

Completed:

- Python package scaffold using Python 3.12.
- `fpl update` and `fpl report` CLI commands.
- Local SQLite snapshot store and raw-data archive.
- Deterministic squad and starting-lineup rule validation.
- Initial rule tests.

Remaining before V0.1 is complete:

- Represent the user's actual current squad and state (bank, free transfers, purchase/selling prices, chips).
- Transfer validator based on that state.
- Expand automated test coverage for edge cases and API storage.
- Commit the initial repository state.

### V0.2 — decision-support basics

- Current-squad report.
- Fixture analysis and transparent player rankings.
- Basic, documented expected-points assumptions.
- Legal one- and two-transfer option generation.
- Starting-XI and captaincy options.

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
