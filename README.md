# FPL Manager

A local-first Fantasy Premier League decision engine for the 2026/27 season.

![Version](https://img.shields.io/badge/Version-0.9.1-purple) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```
FPL API -> local SQLite snapshots -> rules + validation -> reports -> human / LLM analysis
```

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

Launch the interactive local web dashboard:

```powershell
fpl gui
```

Or run headless without automatically opening the default browser:

```powershell
fpl gui --port 8080 --no-browser
```

### Multi-Team Management

Manage multiple isolated fantasy teams, switch between them, or create a new team:

```powershell
# List all configured teams and active squad
fpl teams

# Create a new team (cloned from active squad or template)
fpl team create "Differential Kings" --manager "Marco" --activate

# Inspect active or specific team metadata and financials
fpl team info
fpl team info differential-kings

# Switch active team
fpl team switch default
fpl team switch differential-kings

# Delete a team
fpl team delete differential-kings
```

All CLI commands (`squad`, `lineup`, `suggest-transfers`, `wildcard`, `plan`, `chip-strategy`, `log-decision`, `decisions`, `evaluate`) automatically operate on the currently active team, or accept an explicit `--team <id>` argument.

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

Generate legal 1- to 5-transfer move recommendations (ranked by net projected expected points gain $\Delta xP - \text{Hits}$, powered by pure Python branch-and-bound optimization with rank-aware risk profiles: `neutral`, `floor`, `ceiling`, `defend_lead`, `chase`):

```powershell
fpl suggest-transfers --transfers 1
fpl suggest-transfers --transfers 2 --risk chase
fpl suggest-transfers --transfers 4 --risk defend_lead
```

Generate optimal 15-player squad (Wildcard / Free-Hit) under budget and club constraints:

```powershell
fpl wildcard
fpl wildcard --budget 100.0 --risk ceiling
fpl free-hit --risk chase
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

### Historical Dataset Acquisition & Backtesting

Download and normalize historical season archives from public FPL repositories into `data/historical/<season>` for prediction and strategy backtesting:

```powershell
fpl download-historical --season 2023-24
```

Run empirical participation error diagnostics and root-cause decomposition (V0.8.1):

```powershell
fpl backtest-participation --season 2023-24 --start-gw 1 --end-gw 38 --report
fpl backtest-participation --season 2023-24 --save-report
```

Run out-of-sample prediction accuracy backtesting with comparative predictor versioning:

```powershell
fpl backtest-predictions --season 2023-24 --start-gw 1 --end-gw 38 --predictor v0.9 --report
fpl backtest-predictions --season 2023-24 --start-gw 1 --end-gw 38 --predictor v0.8 --report
fpl backtest-predictions --season 2023-24 --start-gw 1 --end-gw 38 --predictor v0.7 --report
```

Run sequential multi-gameweek decision simulations comparing the production optimizer against baselines:

```powershell
fpl backtest-decisions --season 2023-24 --strategy optimizer --start-gw 1 --end-gw 10 --predictor v0.9
fpl backtest-decisions --season 2023-24 --strategy notransfer --start-gw 1 --end-gw 10 --predictor v0.9
```

### Strategic LLM Advisory & Candidate Strategy Critique

Generate qualitative strategic critiques of candidate moves while enforcing deterministic legality checks:

```powershell
fpl advise --persona tactical_analyst
fpl advise --persona devil_advocate --provider gemini
```

## Current scope (V0.9 & V0.9.1 Completed)

### What's New in V0.9 & V0.9.1
- **Learned Hierarchical Participation Model (V0.9)**: Replaced transitional heuristic rules with a two-stage hierarchical model trained on multi-year point-in-time features without future data leakage:
  - *Stage 1*: Calibrated logistic regression predicting starting probability $P(\text{start})$.
  - *Stage 2*: Conditional classifier predicting substitute probability $P(\text{sub} \mid \text{not start})$.
  - *Expected Minutes ($xM$)*: $xM = P(\text{start}) \cdot \mathbb{E}[M \mid \text{start}] + P(\text{sub} \mid \text{not start}) \cdot (1 - P(\text{start})) \cdot \mathbb{E}[M \mid \text{sub}]$.
- **Dynamic Rotation Regimes & Turnaround Fingerprints (V0.9)**: Player-specific turnaround congestion models capturing fast vs. slow recovery profiles, 7-day and 14-day match congestion, and exponential role-loss decay.
- **Probability Calibration via Isotonic Regression & Platt Scaling (V0.9)**: Calibrated with Pool Adjacent Violators Algorithm (PAVA) and Platt scaling, directly aligning predicted participation probabilities with empirical base rates.
- **Granular xP Component Calibration (V0.9)**: Empirical conversion shrinkage for Opta underlying metrics (xG/xA), defensive clean sheet Poisson shrinkage, goalkeeper save curves, and bonus point modeling.
- **Decision A/B Backtesting Framework (`fpl backtest-decisions`) (V0.9)**: Multi-season sequential decision replay framework with realistic transfer bank constraints, transfer ROI tracking, and counterfactual regret analysis against `notransfer` and baseline policies.
- **Closed-Loop Evaluation & Hindsight Counterfactuals (V0.9)**: Direct post-deadline comparison between actual human choices, model-recommended starting lineups, and hindsight-optimal legal maximums.
- **Multi-Year Participation Risk Penalty Calibration (V0.9.1)**: Empirical multi-season calibration (2022/23 to 2025/26) determining the optimal participation risk weight ($w=0.0$), maximizing net fantasy points (+2033 in 2025/26) while eliminating unwarranted bench regret.
- **Chip Lifecycle Hardening & Transfer Hit Elimination (V0.9.1)**: Full enforcement of zero transfer hit penalties (`-4` points dropped) when Wildcard or Free Hit chips are active across decision logging, transfer execution, live matchday scoring, finalized scoring, and evaluation. Comprehensive chip alias normalization (`wildcard`, `wildcard_1`, `wildcard_2`, `wc`, `freehit`, `free_hit`, `fh`).
- **GUI Pitch & Trade Synchronization (V0.9.1)**: Auto-populates active chips in the Pitch view to prevent accidental chip clearing on lineup saves, passes active chips from trade execution modals, and displays dynamic `0 (Free with Chip)` placeholders.

### Core Platform Capabilities
- **Predictive Participation Engine**: Probabilistic participation and minutes estimation outperforming baseline minutes models.
- **Rank-Aware Decision Optimization**: Risk profiles (`neutral`, `floor`, `ceiling`, `defend_lead`, `chase`) across transfer suggestions, Wildcard, Free-Hit, and multi-gameweek planning.
- **Structured Qualitative Football Context Layer**: Traceable observations categorized into `FACT`, `INFERENCE`, `RUMOUR`, and `MODEL_ASSUMPTION` with confidence weights and gameweek expiration.
- **LLM Qualitative Strategy Critique**: Pre-deadline strategy dossiers critiquing optimizer candidates against qualitative context under deterministic rules.
- **Interactive Local Graphical Dashboard (`fpl gui`)**: Zero-dependency local web app with visual football pitch lineup, team switcher, decision logger, transfers visualizer, Wildcard studio, and evaluation hub.
- **Multi-Team Management Core (`fpl teams`, `fpl team`)**: Full multi-squad support with team isolation, active team switching, team cloning, and team-scoped decision persistence.
- **Official FPL API Ingestion**: Normalized SQLite snapshots with automated schema migration and raw payload preservation.
- **Combinatorial Optimizer**: Pure Python branch-and-bound optimizer for 1 to 5 transfers (`fpl suggest-transfers`) and rolling multi-gameweek transfer planning (`fpl plan`).
- **Effective Ownership & Strategic Risk Index**: Template Shield vs Differential Sword categorization (`fpl ownership` / `fpl risk`).
- **Chip Strategy Planner**: Multi-gameweek Blank and Double Gameweek calendar analyzer (`fpl chip-strategy`).
- **Audit Trail & Regret Engine**: Gameweek decision logging and post-matchday evaluation (`fpl log-decision`, `fpl decisions`, `fpl evaluate`).

## Roadmap

The detailed roadmap lives in [`docs/roadmap.md`](docs/roadmap.md).

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.
