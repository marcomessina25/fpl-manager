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
