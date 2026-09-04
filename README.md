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

Generate legal 1- to 5-transfer move recommendations (ranked by net projected expected points gain $\Delta xP - \text{Hits}$, powered by pure Python branch-and-bound optimization):

```powershell
fpl suggest-transfers --transfers 1
fpl suggest-transfers --transfers 2
fpl suggest-transfers --transfers 4 --risk floor
```

Generate optimal 15-player squad (Wildcard / Free-Hit) under budget and club constraints:

```powershell
fpl wildcard
fpl wildcard --budget 100.0 --risk ceiling
fpl free-hit
```

Generate multi-gameweek transfer planning roadmap (evaluating rolled transfers vs hits over a rolling horizon):

```powershell
fpl plan --horizon 3
fpl plan --horizon 5 --no-hits
fpl plan --horizon 3 --risk floor
```

Optimize your matchday starting lineup, captaincy, and bench based on expected points (xP) and uncertainty distributions:

```powershell
fpl lineup
```

Or target a specific upcoming gameweek:

```powershell
fpl lineup --gameweek 3
```

Aliases `fpl starting-xi` and `fpl captain` can also be used. See [`docs/expected_points.md`](docs/expected_points.md) for full documentation of the underlying expected points baseline model.

Log and lock in your pre-deadline decision in the persistent audit trail:

```powershell
# Log a decision for the current gameweek (automatically updates current_squad.json: players, purchase prices, bank, and free transfers):
fpl log-decision --gameweek 3 -t "Amad:Tielemans" -c "Haaland" --vc "Salah"

# Log a decision for a past gameweek (e.g. GW2 when current squad is GW3) for audit and evaluation:
# Allows specifying players who were on the team at that time without requiring them in current_squad.json; leaves current_squad.json untouched:
fpl log-decision --gameweek 2 -t "Gabriel:Saliba" -c "Haaland" --vc "Salah" --starters "Raya,Saliba,Alexander-Arnold,Konsa,Palmer,Saka,Mbeumo,Rogers,Haaland,Wood,Watkins"
fpl log-decision --gameweek 1 --squad-players "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"
```

Review past gameweek decisions and audit trail:

```powershell
fpl decisions
fpl decisions --gameweek 2
```

Fetch and cache official live matchday player scores from the FPL API:

```powershell
fpl update-scores --gameweek 2
```

Evaluate model prediction accuracy and manager decision quality (MAE, RMSE, Spearman rank correlation, confidence interval calibration, captaincy/bench regret, human vs model divergence). If `--scores` is omitted, official scores are fetched automatically:

```powershell
fpl evaluate
fpl evaluate --gameweek 2
fpl evaluate --gameweek 2 --scores "1:6,4:2,13:14"
```

Analyze Effective Ownership (EO), Template Shields vs Differential Swords, and squad net rank exposure:

```powershell
fpl ownership
fpl risk
fpl ownership --league --top 15
```

Plan Blank and Double Gameweek chip deployment roadmap (Wildcard, Free Hit, Bench Boost, Triple Captain). Automatically segments the season into Gameweeks 1-19 (First Half) and 20-38 (Second Half); all chips reset after Gameweek 19:

```powershell
fpl chip-strategy
fpl chip-strategy --start-gw 20
fpl chip-strategy --used-chips "wildcard,freehit"
```

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

## Current scope (V0.4 Completed)

- Official FPL API ingestion (`bootstrap-static` and `fixtures`)
- Timestamped raw API snapshots and normalized SQLite tables with automated schema migration
- Pure, testable validators for a 15-player squad and an 11-player starting lineup
- Squad financial, selling price, and legality reporting (`fpl squad`)
- Multi-gameweek fixture difficulty rating (FDR) analysis and squad tickers (`fpl fixtures`)
- Component-based expected points ($xP$) model with Opta per-90 metrics and expected minutes ($xM$)
- Uncertainty distributions ($xP_{\text{floor}}$, $xP_{\text{ceiling}}$, $\sigma$) and risk profiles (`neutral`, `floor`, `ceiling`)
- Matchday Starting-XI, captaincy, and bench optimization with strategic asset tags (`fpl lineup`)
- Fast branch-and-bound combinatorial optimizer for 1 to 5 transfers (`fpl suggest-transfers`)
- Multi-stage 15-player Wildcard and Free-Hit squad optimization (`fpl wildcard` / `fpl free-hit`)
- Rolling multi-gameweek transfer planning roadmap over 3 to 6 gameweeks (`fpl plan`)
- Pre-deadline decision audit trail logging and human vs model recommendation snapshot (`fpl log-decision`, `fpl decisions`)
- Backtesting and prediction accuracy evaluation engine with MAE, RMSE, Spearman rank $\rho$, calibration, and regret metrics (`fpl evaluate`)
- Effective Ownership (EO) and Strategic Risk Index with Template Shield vs Differential Sword categorization (`fpl ownership` / `fpl risk`)
- Blank and Double Gameweek calendar analyzer and multi-gameweek chip deployment planner (`fpl chip-strategy`)
- Transfer set validation by player ID or fuzzy name resolution (`fpl validate-transfers`)

## Roadmap

The detailed roadmap lives in [`docs/roadmap.md`](docs/roadmap.md).

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.
