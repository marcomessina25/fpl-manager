# FPL Manager

A local-first Fantasy Premier League decision engine for the 2026/27 season.

![Version](https://img.shields.io/badge/Version-1.3.5-purple) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

The project deliberately separates deterministic facts and rule checks from strategic judgement:

```
FPL API -> local SQLite snapshots -> rules + validation -> reports -> human / LLM analysis
```

## Living roadmap

- [`docs/architecture.md`](docs/architecture.md) defines the purpose, architectural boundaries, and responsibilities of each layer.
- [`docs/roadmap.md`](docs/roadmap.md) tracks current delivery status and next milestones.

Both human contributors and AI agents must read the relevant living documents before making material changes and update them whenever architecture, scope, priorities, or delivery status changes.

## Data & Attribution

This project processes official FPL data from the Fantasy Premier League API.
Commercial use of FPL data must comply with FPL's terms of service.
See [FPL Data Usage](https://fantasy.premierleague.com/) for details.

## Quick start

Create the Conda environment and install the project in editable mode:

```powershell
conda create -n fpl python=3.12
conda activate fpl
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

## Current scope (V1.3.5 — Optimizer Decision-Quality Study & Hardened Architecture)

V1.3.5 freezes the quantitative predictor and systematically isolates the incremental decision-level effect of optimizer mechanisms across controlled ablations ($B_0$ through $B_7$):

- **Bench-Aware Multi-Horizon Optimization ($H=3, \gamma=0.75, W_{\text{bench}}=0.15$)**: Multi-GW planning without bench awareness is brittle (-56 pts vs control); adding explicit bench weighting ($W_{\text{bench}}=0.15$) surges performance to **2,289.0 pts (+193.0 pts over $B_1$, +137.0 pts over control $B_0$)** by buffering against multi-period prediction noise.
- **Goalkeeper Churn Suppression ($\text{GK}_{\text{hurdle}}=3.0$ pts)**: Role-specific hurdles on healthy goalkeepers eliminate zero-utility transfers, preserving free transfers for high-variance outfield picks.
- **Candidate Search Pool Regularization ($N=5$)**: Mitigates "search breadth overfitting" where unconstrained candidate pools ($N=25$) dropped **-147.0 pts** due to the optimizer aggressively selecting noisy positive prediction error tails. Constraining the candidate pool to $N=5$ top candidates serves as an essential regularizer.
- **Default `maximum_ev` Strategic Initialization**: Initial squad selection exerts compounding season-long leverage, unlocking **+93 net points** over balanced initialization under identical downstream optimization.
- **Mathematical Regret Decomposition Verified**: Empirically confirms $\text{Total Decision Regret} \equiv \text{Prediction Regret} + \text{Optimizer Regret}$. In modern variants, Optimizer Regret is 0.00 pts, proving that performance drops in wide candidate spaces are entirely driven by Prediction Regret.
- **Engine Deployment**: Implemented in [`DecisionEngineV135`](src/fpl_manager/backtest/decision_engine.py), accessible via `--decision-engine v1.3.5` / `resolve_decision_engine("v1.3.5")`.
- **Handoff to V1.4**: Freezes this validated decision engine as the reference core for interactive historical season simulation.
- Full specification & reports: [`docs/v1.3.5/v135.md`](docs/v1.3.5/v135.md) and [`reports/v135/final_summary.md`](reports/v135/final_summary.md).

---

## Previous research (V1.3 — Gradient Boosting Quantitative & Strategic Engine)

V1.3 delivers a full **Gradient Boosting Decision Tree (GBDT)** framework across participation, matchday projections, and decision evaluation:
- **GBDT Hierarchical Participation & Minutes (`src/fpl_manager/ml/`)**: `HistGradientBoostingClassifier` for $P(\text{start})$ and $P(\text{sub} \mid \text{not start})$ (Val AUC: 0.9487); `HistGradientBoostingRegressor` for conditional minutes (MAE: 7.93 mins).
- **Non-Linear Matchday Threat & Defense**: Machine-learned interaction terms between player underlying metrics, opponent defensive solidity, and venue.
- **DecisionEngineV13 Integration**: Registered under `--decision-engine v1.3` / `--predictor v1.3` with full feature pipeline support.
- **Zero-Leakage & Optional Packaging**: Optional dependency via `pip install -e ".[ml]"`; zero-breakage pure-Python fallback when `scikit-learn` is not present.
- **Audited 5-Season Multi-Version Benchmark Ledger (`reports/v13/`)**:
  - V1.3 achieved outstanding performance in recent Premier League dynamics (**2025-26: 2,144 pts Track A, 2,169 pts Track B**; highest of any version tested).
  - Across the full 5-season historical horizon (2,046.6 vs 1,988.0 Track A), V1.2.5 remains the more stable historical all-season optimizer.
  - **Promotion Rule**: In accordance with the project roadmap promotion rule, `DecisionEngineV125` remains the default live decision engine, while V1.3 is packaged as the high-tier ML predictor and engine.
- Full specification: [`docs/v1.3/v13.md`](docs/v1.3/v13.md) / [`docs/v1.3/v13_gradient_boosting.md`](docs/v1.3/v13_gradient_boosting.md).

---

## Current baseline (V1.2.5 — Lineup-Aware Transfer Evaluation Refinements & Benchmark Target Achievement)

### What's New in V1.2.5
- **Candidate Pool Expansion (`max_results=25`)**:
  - Expanded candidate pool in `solve_transfers` from 5 to 25, preventing high-value starting XI upgrades from being pruned prematurely (+17.00 pts/season).
- **Goalkeeper Churn Suppression & Role Hurdles**:
  - Imposed a 1.50 pt hurdle and playing security invariant on GK moves, cutting wasteful keeper churn by 60% and saving free transfers for outfielders (+1.40 pts/season).
- **Rolling 3-Gameweek Discounted Lineup Horizon ($H=3, \gamma=0.75$)**:
  - Evaluates candidate transfers across a 3-GW discounted lineup horizon, dampening reactive panic-selling on 1-week knocks and anticipating fixture runs (+2.40 pts/season).
- **Dynamic Chip-Aware Bench Weighting**:
  - Dynamically tunes `bench_weight`: $0.05\times$ for Free Hit (concentrating £100m into starting XI), $0.99\times$ for Bench Boost (scoring all 15 players), doubling chip return from +24.4 to +41.2 pts/season (+37.6 pts overall in Track B).
- **Live Decision Engine Wiring**:
  - Connected `DecisionEngineV125` directly into live CLI commands (`suggest-transfers`, `plan`, `lineup`), Web GUI endpoints, and LLM briefings, with optional `--engine legacy` fallback.
- **Clean Removal of Inert Unavailability Registry**:
  - Confirmed 100% inert in backtests (exact 0.00 drift across all 5 seasons); eliminated dead code and hindsight bias.

### Audited 5-Season Benchmark Results (GW 1–38)

| Version | Track A Mean Net | Track B Mean Net | Chip Delta (B - A) | Track A Std Dev | Δ vs V1.2 (Track A) | Δ vs V1.0 (Track A) |
|---|---:|---:|---:|---:|---:|---:|
| **V0.9** | 1,983.6 | 2,048.2 | +64.6 pts | ±212.8 | -42.2 pts | -64.8 pts |
| **V1.0** | 2,048.4 | 2,108.0 | +59.6 pts | ±205.2 | +22.6 pts | — (baseline) |
| **V1.1** | 1,983.0 | 2,010.0 | +27.0 pts | ±122.4 | -42.8 pts | -65.4 pts |
| **V1.1.5** | 1,980.4 | 2,007.8 | +27.4 pts | ±145.2 | -45.4 pts | -68.0 pts |
| **V1.2** | 2,025.8 | 2,050.2 | +24.4 pts | ±122.0 | — | -22.6 pts |
| **V1.2.5** | **2,046.6** | **2,087.8** | **+41.2 pts** | **±116.9** | **+20.8 pts** | **-1.8 pts** |

Full specification and execution plan: [`docs/v1.2.5/v125.md`](docs/v1.2.5/v125.md) and [`docs/v1.2.5/v125_implementation_plan.md`](docs/v1.2.5/v125_implementation_plan.md).

---

## Previous scope (V1.2 — Strategic Squad Balancing & Long-Term Unavailability)

### What's New in V1.2
- **Asymmetric Starting XI vs Bench Squad Balancing (`src/fpl_manager/strategic_squad.py`)**:
  - `solve_strategic_squad` scores candidate swaps with an asymmetric lineup objective (`1.0×` starters, `0.15×` bench) instead of a flat 15-player sum.
- **Lineup-Aware Transfer Evaluation (`DecisionEngineV12` in `src/fpl_manager/backtest/decision_engine.py`)**:
  - Transfers are scored on their net effect on **Starting XI** expected points rather than raw squad totals.
- **Audited 5-Season Multi-Version Benchmark Ledger (`reports/v12/`)**:
  - V1.2 recovered +45.4 pts vs V1.1.5 in Track A with lowest cross-season variance (±122.0). Full specification: [`docs/v1.2/v12.md`](docs/v1.2/v12.md).

---

## Previous scope (V1.1.5 — Hardening & Multi-Season Ledger Release)

### What's New in V1.1.5
- **Point-in-Time Premier League Departure Engine (`src/fpl_manager/models.py`, `src/fpl_manager/backtest/decision_engine.py`, `data/historical/departures_registry.json`)**:
  - Point-in-time detection and resolution of players departing the Premier League mid-season (overseas sales, loans, contract terminations).
  - Explicit historical departures registry covering departures across 5 historical seasons (`2021-22` through `2025-26`).
  - Active dead capital recovery: `DecisionEngineV115` detects departed assets in the squad and prioritizes liquidating dead roster slots and stranded bank budget to restore active starting depth.
  - Zero-false-positive blank gameweek immunity: avoids misclassifying blank gameweek teams (e.g. GW29 postponement / cup blank) as departed players by relying strictly on verified departure dates, FPL player status (`u`), and registry records rather than single-gameweek fixture presence.
- **Calibrated Seasonal Chip Strategy & Anti-Pathology Guardrails (`src/fpl_manager/chip_strategy.py`)**:
  - Anti-pathology fixture schedule guards: Free Hit requires `len(fixtures) >= 4` to prevent burning high-value chips in postponed/abandoned gameweeks.
  - Elimination of forced expiry panics: removed hardcoded forced Wildcard dumps in GW19 / GW37, replaced with dynamic near-expiry qualification thresholds requiring positive expected gain ($\ge 8.0$ net xP over rolling horizon).
  - Horizon clamping: multi-gameweek lookaheads are strictly clamped to remaining gameweeks in each half-season (`min(39, gw + horizon)`) preventing index out-of-bounds or cross-half-season leakage.
- **Audited 5-Season Multi-Version Benchmark Ledger (`reports/v115/`)**:
  - Full reproducible backtests comparing V1.0, V1.1.0, and V1.1.5 across all 5 historical seasons (`2021-22` to `2025-26`).
  - Comprehensive Track A (No Chips) and Track B (With Chips) ledger isolating pure strategic transfer engine dynamics from chip variance.
  - Granular comparative documentation in [`reports/v115/multi_version_benchmark/multi_version_comparison.md`](reports/v115/multi_version_benchmark/multi_version_comparison.md) and [`reports/v115/multi_season_summary/multi_season_summary.md`](reports/v115/multi_season_summary/multi_season_summary.md).

### What's New in V1.1.0
- **Multi-Team Management (`fpl teams`, `fpl team create`, `fpl team switch`, `fpl team info`, `fpl team delete`)**: Manage multiple isolated fantasy teams, switch between them, and persist distinct rosters and financials in `config/teams.json`.
- **Interactive Web GUI Dashboard (`fpl gui`)**: Local-first browser interface with interactive pitch view, team switcher, multi-gameweek transfer planner, starting lineup builder, chip strategy roadmap visualizer, and strategic LLM advisory chat.
- **DecisionEngineV11 Strategic Optimization**: Strategic multi-gameweek transfer roll vs spend evaluation, dynamic thresholding, and horizon lookahead.

### What's New in V1.0.0 & V1.0.1
- **Release V1.0.1 — Documentation & Codebase Comment Alignment**: Full audit and alignment of all living documentation (`README.md`, `docs/roadmap.md`, `docs/architecture.md`, `docs/expected_points.md`, `docs/optimizer_and_planning.md`), module docstrings across all 51 Python modules, CLI risk/predictor/decision-engine choices (`v1.0.1` / `v1.0` / `v0.9.1`), and `suggest_transfers` risk-profile validation (`validate_risk_profile`).
- **Canonical Model Registry & Historical Prediction Reconstruction (`src/fpl_manager/model_registry.py`)**: Every projection embeds canonical `ModelMetadata` (`model_version="v1.0.0"`, `quantitative_core_version="v0.9.1-frozen"`), strict provenance validation (`ModelMetadata.from_dict(..., strict=True)`), deterministic feature provenance, explicit regime tags (`single`, `dgw`, `bgw`), and `reconstruct_historical_prediction()` with snapshot-anchored historical timestamps (`resolve_historical_snapshot_timestamp()`).
- **Strict 7-Category Point-in-Time Leakage Enforcement (`src/fpl_manager/historical/validation.py`)**: `validate_no_future_leakage()` checks and rejects lookahead across all 7 leakage categories (`player_gw_history`, `player_prices`, `availability_status`, `fixture_schedule`, `finished_fixtures_in_current_or_future_gw`, `season_totals_over_rolling_total`, `post_deadline_snapshot_timestamp`), and `PIT_LEAKAGE_VERIFICATION_SCOPE` explicitly distinguishes **intrinsic snapshot invariants** (Categories 6 & 7, checked directly on any standalone snapshot) from **reference-comparative checks** (Categories 1–5, verified against an uncontaminated reference snapshot).
- **Neutral Strategy Alignment (`lineup_penalty_weight = 0.0`) & Lineup Quantity Separation (`src/fpl_manager/lineup.py`)**: `DecisionEngineV10` and `select_starting_lineup(risk_profile="neutral")` default to `lineup_penalty_weight = 0.0` (pure expected points maximization without variance penalty), while explicit custom `lineup_penalty_weight` values remain supported for experimentation and non-neutral profiles (`safe` `w = 0.15`, `conservative` `w = 0.35`, `differential` `w = -0.10`, `upside` `w = -0.15`). `select_starting_lineup` strictly separates `model_quantities` (`starters_xp`, `captain_bonus`, `total_lineup_xp`) from `decision_quantities` (`starters_obj`, `captain_obj`, `total_lineup_obj`).
- **Independent Exact Verification Oracles & Heuristic Disclosures (`src/fpl_manager/optimizer.py`, `src/fpl_manager/planner.py`)**:
  - `solve_transfers` is verified against the independent brute-force Cartesian oracle `solve_transfers_exact_reference()` (`MAX_REFERENCE_EVALUATIONS = 100_000`) across bounded 1–5 transfer instances (`A=16, B=225, C=1225, D=4900, E=15876`) and adversarial pruning-sensitive FDR-inversion bounds.
  - `generate_multi_gameweek_plan` is a forward beam-search planner (`algorithm = "beam_search_multi_gw"`, `is_exact_global_optimum = False`) verified on small synthetic horizons against the independent Bellman dynamic programming reference oracle `plan_multi_gw_exact_reference()`.
  - `solve_wildcard` explicitly discloses its heuristic local-search status (`algorithm = "heuristic_local_search_1opt_2opt"`, `is_exact_global_optimum = False`).
- **Persistent LLM Evaluation Audit Table (`llm_evaluations`)**: Every LLM advisory call logs provider, model, deterministic validation status, fallback reason, and manager follow-through in SQLite.
- **Mutually Exclusive Additive Regret Decomposition & Decision-Weighted Error (`src/fpl_manager/evaluation.py`)**: Provides both `additive_regret_decomposition` (`total_decision_regret = lineup_regret + captaincy_regret + transfer_regret + chip_regret + hit_cost`, `is_mutually_exclusive_additive = True`) and `decision_loss_diagnostics` (`is_overlapping_diagnostic = True`), weights prediction errors by decision importance (`2.0` captain, `1.5` transfer target, `1.0` starter, `0.35` bench), and explicitly separates `observed_outcome` from `hindsight_counterfactual`.

### V1.0 Methodological Disclosure (What V1.0 Does Well, Poorly, and Does Not Claim)

- **What V1.0 Does Well:**
  - Enforces 100% deterministic FPL rule legality (squad size/positions, club quotas, selling-price tax, free transfers, transfer hits, autosubs, vice-captain promotion, and chip lifecycles).
  - Guarantees point-in-time historical evaluation across 5 seasons (`2021-22` to `2025-26`) using the frozen V0.9.1 quantitative core (`quantitative_core_version = "v0.9.1-frozen"`).
  - Solves 1–5 single-gameweek transfer combinations via branch-and-bound verified against `solve_transfers_exact_reference`, and outperforms No-Transfer and Greedy single-transfer baselines by `+17` to `+59` net points per season in historical backtests (see canonical benchmark tables and provenance in [`reports/v10_canonical_model_report.md`](reports/v10_canonical_model_report.md) and [`reports/v09_frozen_baseline.json`](reports/v09_frozen_baseline.json)).
  - Subordinates LLM strategic commentary strictly to deterministic rule validation with guaranteed offline heuristic fallback.
- **What V1.0 Does Poorly (Known Limitations):**
  - **Mid-Gameweek Unexpected Rotation & Late Team News:** Unannounced tactical benchings (30–65 minute rotation players) remain the largest irreducible source of single-gameweek $xP$ variance (`xM MAE ~ 19.1 mins`; see [`reports/v10_canonical_model_report.md`](reports/v10_canonical_model_report.md)).
  - **15-Player Wildcard & Multi-GW Global Optimality:** Full 15-player Wildcard/Free-Hit construction (`solve_wildcard`) uses a 1-opt/2-opt heuristic local search (`~50ms`) and multi-GW horizon planning (`generate_multi_gameweek_plan`) uses bounded beam search; both guarantee high-quality feasible trajectories rather than theoretical global optima over the full combinatorial state space.
  - **In-Game Bonus Point Tie-Breaking:** Bonus points ($xP_{\text{bonus}}$) are approximated from expected attacking and clean-sheet contributions rather than full match-level BPS Monte Carlo simulation.
- **What V1.0 Does Not Claim:**
  - V1.0 does **not** claim to predict exact single-gameweek match outcomes or eliminate football variance; it maximizes expected value and risk-adjusted utility over multi-gameweek horizons.
  - V1.0 does **not** allow any LLM to override deterministic squad rules, budgets, or point projections.

### Previous Milestones (V0.9 & V0.9.1)
- **Learned Hierarchical Participation Model (V0.9)**: Two-stage hierarchical model predicting $P(\text{start})$ and $P(\text{sub} \mid \text{not start})$ with PAVA isotonic and Platt calibration.
- **Chip Lifecycle Hardening & Transfer Hit Elimination (V0.9.1)**: Full enforcement of zero transfer hit penalties when Wildcard or Free Hit chips are active across all CLI and GUI paths.

## Roadmap

The detailed roadmap lives in [`docs/roadmap.md`](docs/roadmap.md), the V1.3.5 optimizer study specification in [`docs/v1.3.5/v135.md`](docs/v1.3.5/v135.md), the V1.3 GBDT specification in [`docs/v1.3/v13.md`](docs/v1.3/v13.md), the planned V1.4 simulation sandbox in [`docs/v1.4/v14_historical_simulation.md`](docs/v1.4/v14_historical_simulation.md), the V1.2.5 release report in [`docs/v1.2.5/v125.md`](docs/v1.2.5/v125.md), and prior milestone documentation in [`docs/v1.2/v12.md`](docs/v1.2/v12.md).

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details. You are free to use, modify, and reproduce this software with attribution to Marco Messina.

