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

## Private current-squad file

Copy `config/current_squad.example.json` to `config/current_squad.json`, then replace the placeholder player IDs and purchase prices with your own 15-player squad. The private file is ignored by Git; do not commit it. Prices and bank are stored in tenths of a million (£5.0m is `50`).

Use the latest official snapshot to find each player ID, for example:

```powershell
fpl update
fpl players --search "Salah"
```

Enter the returned `id` for each member of your squad. Use the current price as the purchase price only when you bought the player at that price; otherwise enter the price you actually paid.

After running `fpl update`, validate a proposed transfer using FPL player IDs:

```powershell
fpl validate-transfers --transfer 123:456
```

Repeat `--transfer` for a multi-transfer move. The command checks your squad, position, bank, club limit, and transfer-hit impact without changing your saved state.

The database is saved at `data/fpl.sqlite3`; downloaded source payloads are timestamped under `data/raw/`. Both are intentionally ignored by Git.

## Current scope

- Official FPL API ingestion (`bootstrap-static` and `fixtures`)
- Timestamped raw API snapshots and normalized SQLite tables
- Pure, testable validators for a 15-player squad and an 11-player starting lineup
- A small CLI for updating data and producing a machine-readable current-state report

## Roadmap

The detailed roadmap lives in [`docs/roadmap.md`](docs/roadmap.md).
