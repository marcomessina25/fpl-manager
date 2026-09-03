# FPL Manager

A local-first Fantasy Premier League decision engine for the 2026/27 season.

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```
FPL API -> local SQLite snapshots -> rules + validation -> reports -> human / LLM analysis
```

V0.1 does not make transfers or call an LLM. It provides a reliable data and rules foundation first.

## Living roadmap

- [`docs/architecture.md`](docs/architecture.md) defines the purpose, architectural boundaries, and responsibilities of each layer.
- [`docs/roadmap.md`](docs/roadmap.md) tracks current delivery status and next milestones.

Both human contributors and AI agents must read the relevant living documents before making material changes and update them whenever architecture, scope, priorities, or delivery status changes.

## Quick start

Create the Conda environment and install the project in editable mode:

```powershell
conda create -n fbl python=3.12
conda activate fbl
pip install -e ".[dev]"
```

Download and store an official FPL snapshot:

```powershell
fpl update
```

Inspect the most recently saved snapshot:

```powershell
fpl report
```

The database is saved at `data/fpl.sqlite3`; downloaded source payloads are timestamped under `data/raw/`. Both are intentionally ignored by Git.

## Current scope

- Official FPL API ingestion (`bootstrap-static` and `fixtures`)
- Timestamped raw API snapshots and normalized SQLite tables
- Pure, testable validators for a 15-player squad and an 11-player starting lineup
- A small CLI for updating data and producing a machine-readable current-state report

## Roadmap

The detailed roadmap lives in [`docs/roadmap.md`](docs/roadmap.md).
