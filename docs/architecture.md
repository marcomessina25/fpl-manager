# FPL Manager architecture

> **Living document.** This defines the project's purpose, architectural boundaries, and non-negotiable responsibilities. Human contributors and AI agents must read it before material design or implementation work and update it when these decisions change.

## Purpose

FPL Manager is a local-first decision-support system for Fantasy Premier League (FPL), beginning with the 2026/27 season. Its aim is to support a serious human + quantitative model + LLM workflow while preventing the rule, budget, price, and squad-state mistakes that a general-purpose LLM can make.

It is **not** an autonomous team manager. A human remains responsible for final FPL decisions and for executing transfers.

## V1.4.7 assessment and proposed evolution

The current implementation and its remaining correctness/integration debt are
assessed in [the repository analysis](v1.4.7/repository_analysis.md).
[The V1.4.7 plan](v1.4.7/v147_plan.md) prioritizes authoritative accounting,
historical outcome correctness, explicit contexts and durable commands.
[The PyQt6 design](v1.4.7/pyqt6_migration_plan.md) is a proposal only: extract
framework-independent services before connecting a native client; do not move
HTTP/DOM orchestration directly into widget callbacks.

Shared Live/Historical workflows retain matching capabilities. Live Matchday
and AI Advisor & Briefing are intentionally live-only and already hidden in
Historical mode. New GUI calculations use the central latest decision-engine
policy without a version menu; frozen research provenance remains explicit.

### Version and execution policy (V1.4.7)

**Current version:** 1.4.7 candidate; GUI uses latest decision engine only.
LLM provider/model choices retained in live advisory workspace. Historical mode
continues to hide Live Matchday and AI Advisor & Briefing tabs.

**Execution policy:**
- **New sessions:** record corrected execution identity `v147`, separately from the decision-engine version.
- **Missing, null, unknown or legacy-marked sessions:** readable, read-only archives. Unknown raw identities are retained in fork provenance rather than admitted as corrected execution.
- **Corrected fork:** explicit GUI 'Create corrected fork' or CLI `fpl sim fork --id OLD --new-id NEW` starts at a recoverable clean boundary. Preserves source bytes, outcome records, bank/purchase basis/provenance. Resets comparative history and seeds both squads equally. Completed archives need a new replay.
- **DGW correction:** per-fixture sum and provenance; canonical sale arithmetic and pre-write affordability validation.
- **No ongoing 100m cap:** affordability depends on available bank and legal sale proceeds, not initial squad construction budget.
- **Version-preserved research:** `run_sequential_simulation`/`run_decision_backtest` library defaults to execution `v146` for recorded compatibility; CLI `backtest-decisions` defaults to `v147` with `--execution-version v146` opt-in.
- **Original frozen benchmarks:** retained and not relabelled; corrected runs are new execution records.

**Command architecture:**
- Application contexts, CommandBus, receipts, read models and services.
- SQL and journal same live SQLite transaction; historical journal separate (`config/simulations/command_journal.sqlite3`).
- JSON staged, durable commit then atomic publication.
- Explicit roll-forward after crash; external conflicts not overwritten.
- Duplicate IDs and stale revisions protected.
- Errors `RECOVERY_REQUIRED`/`RECOVERY_CONFLICT` mean committed state needs recovery—not rolled back.
- Startup GUI calls explicit recover; CLI `fpl recover` or `fpl recover --historical`; do not retry committed work as fresh action.
- Root CLI options `--expected-revision` and `--command-id` appear BEFORE subcommand and apply to sim mutations, team advance, log-decision; other commands reject these.
- Live lifecycle no longer advances in reads; GUI Advance Deadline button or CLI `fpl team advance [TEAM_ID]` is explicit and idempotent.
- Commands explicitly targeting a later GW invoke `teams.advance_current_squad` in the same transaction before applying the mutation. Planner/session FT transitions share `rules.free_transfer_transition`.
- Query calculations do not write report files; CLI exports keep defaults.
- Evaluation no longer auto-finalizes scores from GET; explicit Scores/update-scores workflow.
- Exact team prospective state, GW, snapshot, finance and chips captured for recommendations; no default squad fallback.
- Typed revision-tagged squad, valuation, staged move, lineup, plan, decision and chip read models.
- HTTP and CLI consume shared command services; not every legacy HTTP calculation has moved from server.py—generic application query boundary wraps remaining orchestration.

**Validation and cache:**
- Data validation and cache; predictor identity with no GBDT fallback.
- Admissible search bonus; signed regret with honest bounded shortlist.
- Blocked chip scheduling and shared early FT planner transitions fixed.
- Tests use canonical `fpl_manager` imports.

**CI and distribution:**
- Linux Python 3.11/12/13 + Windows 3.13; builds and installs wheel.
- `scripts/smoke_installed.py` verifies packaged resources, isolated command smoke and CLI outside checkout.
- Structured logs contain operation/context/revision IDs, not payload/notes/secrets.

The V1.1.5 diagram below describes the foundational responsibilities, not proof
that every current module already satisfies those boundaries.

## Core principles

- Deterministic software is the source of truth for FPL facts, rules, budget, squad state, and legality.
- Every recommendation must pass an independent validator before it is shown as actionable.
- Quantitative projections estimate expected value and uncertainty; they do not invent facts.
- LLMs are strategic analysts over structured, generated data. They are not the optimizer or source of truth.
- Decisions, alternatives, and outcomes should be recorded so the system can be evaluated and improved.
- The system runs locally except for public data downloads and optional, deterministically validated LLM API calls.

## System architecture (V1.1.5)

```text
Official FPL API                 Human observations / news
prices, fixtures, players                    |
            |                                |
            +----------> local SQLite data <--+
                              |
                 +------------+------------+
                 |                         |
          Quantitative model          FPL optimizer
       projections, minutes,       legal squads, transfers,
       uncertainty, fixtures       starting XI, captaincy
                 |                         |
                 +------------+------------+
                              |
                    Generated reports / facts
                              |
                       LLM analysis layer
                  challenge assumptions, identify
                  uncertainty and strategic trade-offs
                              |
                         Human decision
                              |
                    Decision and outcome log
```

## Responsibilities by layer

| Layer | Responsibility | Must not do |
| --- | --- | --- |
| FPL ingestion + database | Fetch and persist official snapshots, current prices, fixtures, players, and gameweek facts | Make recommendations |
| Rules + validator | Enforce budget, squad quotas, club limits, formations, transfers, chips, and selling prices | Trust LLM output without validation |
| Quant model | Estimate points, minutes, fixture effects, and uncertainty | Override hard FPL facts |
| Optimizer | Search legal squads, transfers, starting XIs, and captain options | Reason from unstructured news alone |
| LLM analyst | Interpret generated facts, expose assumptions, and suggest strategic deviations | Invent data or bypass validation |
| Human | Make final choices and execute transfers | Treat a model recommendation as guaranteed |
