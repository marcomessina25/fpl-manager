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

Inspect your detailed current-squad report (financials, player selling prices, team breakdown):

```powershell
fpl squad
```

Analyze upcoming team fixtures and difficulty ratings (FDR):

```powershell
fpl fixtures --gameweeks 5
```

Or analyze upcoming fixtures specifically for your current squad:

```powershell
fpl fixtures --gameweeks 5 --squad-only
```

Generate legal 1-, 2-, or 3-transfer move recommendations (ranked by net projected expected points gain $\Delta xP - \text{Hits}$):

```powershell
fpl suggest-transfers --transfers 1
fpl suggest-transfers --transfers 2
fpl suggest-transfers --transfers 3
```

> **Note on transfer depth:** Transfer suggestions are currently limited to a maximum of 3 transfers for performance reasons (4-transfer search was found to be too slow due to combinatorial explosion). We may revisit 4+ transfer evaluations in the future with an optimized solver (e.g. integer linear programming or branch-and-bound).

Optimize your matchday starting lineup, captaincy, and bench based on expected points (xP):

```powershell
fpl lineup
```

Or target a specific upcoming gameweek:

```powershell
fpl lineup --gameweek 3
```

Aliases `fpl starting-xi` and `fpl captain` can also be used. See [`docs/expected_points.md`](docs/expected_points.md) for full documentation of the underlying expected points baseline model.

## Private current-squad file

Copy `config/current_squad.example.json` to `config/current_squad.json`, then replace the placeholder player IDs and purchase prices with your own 15-player squad. The private file is ignored by Git; do not commit it. Prices and bank are stored in tenths of a million (£5.0m is `50`).

### Automatic Squad Import Utility

Instead of manually searching player IDs and editing JSON, you can list your squad's player names in `players.txt` (one per line) and run the automatic import script:

```powershell
python scripts/import_squad.py
```

Or via CLI:

```powershell
fpl import-squad
```

The script queries the FPL database for each line, outputs status declarations (`importing id xx player xxx team xx price xx` or `failed importing player xxx`), and automatically writes the IDs and prices into `config/current_squad.json`. See [`docs/squad_import.md`](docs/squad_import.md) for complete details.

### Manual Player Search

You can also search individual player IDs using the latest snapshot:

```powershell
fpl update
fpl players --search "Salah"
```

Enter the returned `id` for each member of your squad. Use the current price as the purchase price only when you bought the player at that price; otherwise enter the price you actually paid.

After running `fpl update`, validate proposed transfers using player names (with `-n` / `--by-name`) or integer IDs:

```powershell
fpl validate-transfers -n --transfer "Donnarumma:Haaland"
```

Or using player IDs:

```powershell
fpl validate-transfers --transfer 123:456
```

Repeat `--transfer` for a multi-transfer move. The command checks your squad, position, bank, club limit, and transfer-hit impact without changing your saved state. When `-n` is used, player names are resolved automatically against the snapshot database provided each query resolves to a unique match.

The database is saved at `data/fpl.sqlite3`; downloaded source payloads are timestamped under `data/raw/`. Both are intentionally ignored by Git.

## Current scope (V0.2 Completed)

- Official FPL API ingestion (`bootstrap-static` and `fixtures`)
- Timestamped raw API snapshots and normalized SQLite tables
- Pure, testable validators for a 15-player squad and an 11-player starting lineup
- Squad financial, selling price, and legality reporting (`fpl squad`)
- Multi-gameweek fixture difficulty rating (FDR) analysis and squad tickers (`fpl fixtures`)
- Transparent, deterministic expected-points (xP) baseline projections
- Matchday Starting-XI, captaincy, and bench optimization (`fpl lineup`)
- Legal 1-, 2-, and 3-transfer move recommendations scored by net expected points gain (`fpl suggest-transfers`)
- Transfer set validation by player ID or fuzzy name resolution (`fpl validate-transfers`)

## Roadmap

The detailed roadmap lives in [`docs/roadmap.md`](docs/roadmap.md).
