# V1.4 — Interactive Historical Season Simulation & Human-in-the-Loop Benchmark Platform

**Status:** Planned (Follows V1.3 Gradient Boosting Milestone)  
**Specification:** [`docs/v1.4/v14_historical_simulation.md`](v14_historical_simulation.md)  
**Corpus / Repo:** `marcomessina25/fpl-manager`  

---

## 1. Executive Summary & Vision

Throughout versions V0.9 through V1.3, **FPL Manager** evaluated decision logic primarily via automated, non-interactive batch backtests (`run_version_comparison_backtest`, `scripts/run_v125_benchmark.py`). In those runs, fixed algorithmic policies made every transfer, starting lineup, and chip deployment deterministically across historical seasons (`2021-22` through `2025-26`).

While automated backtests establish a rigorous algorithmic baseline (e.g. V1.2.5 Track A achieving **2,046.6 net points/season** and Track B **2,087.8 net points/season**, with V1.3 exploring gradient boosting enhancements), they miss the central reality of Fantasy Premier League: **the partnership between the software and the human manager**.

**V1.4** transforms the project by introducing the **Interactive Historical Season Simulation Platform** (the *"FPL Time Machine"* / *Historical Sandbox Mode*). 

With V1.4, a manager can:
1. **Choose Any Past Season:** Select from fully archived seasons (`2021-22`, `2022-23`, `2023-24`, `2024-25`, or `2025-26`).
2. **Interactive Squad Creation (GW1):** Receive algorithmic starting squad recommendations (balanced, maximum EV, floor, ceiling), review strategic LLM critiques, accept the optimal squad, or customize players, substitutes, formation, and captaincy.
3. **Step-by-Step Gameweek Execution:** Review readiness, confirm the gameweek team, and click **"Run GW"**.
4. **Real-World Historical Scoring:** The engine computes exact official matchday scores using point-in-time historical data, executing automatic substitutions, captaincy doubling, and transfer hit penalties according to official FPL rules.
5. **Interactive Inter-Gameweek Loop:** Immediately view updated standings, injuries/suspensions, transfer suggestions with lineup deltas, chip options (Wildcard, Free Hit, Bench Boost, Triple Captain), and an LLM tactical briefing for the upcoming gameweek before deciding on the next moves.
6. **Season Finale & Local Reporting:** At the end of Gameweek 38, generate, view, and export comprehensive analytical performance reports locally.
7. **Empirical Human-in-the-Loop Validation:** Conduct blind trials with participants unaware of past Premier League outcomes, establishing a formal empirical lower-bound benchmark for human + software + LLM co-management.

> **Optimizer Selection Policy:** The default decision engine for the historical simulation will be chosen based on the empirical results of V1.3. If V1.3 Gradient Boosting demonstrates superior performance over V1.2.5 on historical data, the simulation sandbox will adopt V1.3 GBDT as its default recommendation engine (with optional user toggle to run V1.2.5).

---

## 2. The Empirical Lower-Bound Hypothesis & Blind Study Protocol

### 2.1 The Scientific Rationale
A standard critique of decision-support systems in sports analytics is hindsight bias or algorithmic overfitting to past trends. In V1.4, we address this directly through an empirical human trial:

$$\text{Live Human Expectation} \ge \mathbb{E}[\text{Points} \mid \text{Software} + \text{LLM} + \text{Naive Human (Historical Blind Replay)}]$$

1. **The Naive Human Condition:** We recruit one or more human participants who are **completely unaware of historical Premier League outcomes** (e.g., participants who did not follow English football during the `2022-23` or `2023-24` seasons).
2. **Zero Lookahead Guarantees:** At each gameweek deadline, participants are presented *only* with the point-in-time statistics, engine suggestions, and LLM advice available at that historical moment.
3. **The Lower Bound Claim:** 
   - If an unaware human, guided strictly by FPL Manager's projections, transfer suggestions, and LLM briefing, achieves **$\ge 2,200$ points** in an unpredictable season (such as the 2022-23 mid-season World Cup or 2023-24 double gameweek blitz), then:
   - This score establishes a **conservative empirical lower bound** for the software.
   - An active manager with domain knowledge, following real-life press conferences and tactical nuances in the live season, can expect to achieve an even higher performance ceiling.
4. **Reporting in V1.4 PR:**
   - The verified scores, transfer histories, chip timings, and feedback from these trial runs will be aggregated into a formal summary document included directly within the V1.4 pull request.

---

## 3. Architectural Pillars of V1.4

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                          V1.4                                          │
├────────────────────┬────────────────────┬────────────────────┬────────────┬────────────┤
│      PILLAR 1      │      PILLAR 2      │      PILLAR 3      │  PILLAR 4  │  PILLAR 5  │
│ Historical Session │ Interactive Squad  │ Deterministic Match│ Inter-GW   │ Season End │
│ State Management   │ Builder & GW1 Init │ Resolution Engine  │ Management │ Analytics  │
├────────────────────┼────────────────────┼────────────────────┼────────────┼────────────┤
│ • Multi-season sel │ • Engine templates │ • Historical stats │ • Tx engine│ • GW chart │
│ • Isolated sandbox │ • LLM evaluation   │ • Auto-subs & cap  │ • Chips    │ • Chip eval│
│ • State save/load  │ • Manual customize │ • Hit penalties    │ • LLM brief│ • Markdown │
│ • No live conflict │ • Lineup & Captain │ • Net gameweek pts │ • Zero leak│   export   │
└────────────────────┴────────────────────┴────────────────────┴────────────┴────────────┘
```

### Pillar 1: Historical Session State Management (`HistoricalSessionState`)
- **Isolation Invariant:** A historical simulation must **never** modify the user's active live squad (`config/current_squad.json`), live database (`data/fpl.sqlite3`), or existing multi-team configuration (`config/teams.json`).
- **Session Persistence:** Simulations are stored in `config/simulations/<session_id>.json`. Each session tracks:
  - `session_id`: Unique identifier (e.g. `sim_2022_23_trial_01`).
  - `season`: Target historical season (`2021-22`, `2022-23`, `2023-24`, `2024-25`, `2025-26`).
  - `current_gw`: Current simulation progress (1 to 38).
  - `squad`: 15-player list with `player_id`, `purchase_price`, `selling_price`.
  - `bank`: Remaining budget (tenths of £1m).
  - `free_transfers`: Available free transfers (1 to 5, according to FPL roll rules).
  - `chips`: Availability and status of Wildcard (H1/H2), Free Hit (H1/H2), Bench Boost (H1/H2), Triple Captain (H1/H2).
  - `history`: List of resolved gameweek summaries (transfers made, hits taken, chips played, points scored, autosubs executed).

### Pillar 2: Interactive Squad Builder & GW1 Initialization
- **Engine Templates:** Generates multiple starting squad recommendations using point-in-time GW1 snapshots.
- **LLM Starting Briefing:** Qualitative analysis explaining structure, fixture runs, and risks.
- **Manual Customization:** Interactive pitch interface for adding, removing, or locking players with live budget and formation validation.

### Pillar 3: Deterministic Historical Matchday Resolution Engine
- **Historical Data Sourcing:** Real fixture results and player scores loaded from `data/historical/<season>/gws/gw<N>.json`.
- **Official FPL Rules Implementation:**
  - Auto-substitutions: Starters with 0 minutes are substituted by bench outfielders in bench order, preserving minimum valid formation constraints ($\ge 1$ GKP, $\ge 3$ DEF, $\ge 2$ MID, $\ge 1$ FWD). Backup goalkeeper replaces starting goalkeeper if starter played 0 minutes.
  - Dynamic Captaincy: Captain receives $2\times$ points ($3\times$ if Triple Captain is active). If the captain plays 0 minutes, multiplier shifts to the vice-captain.
  - Transfer Hits: $-4$ points per extra transfer exceeding available free transfers.
  - Chip Scoring: Bench Boost includes points from all 4 bench players; Free Hit restores pre-chip squad at gameweek completion.

### Pillar 4: Inter-Gameweek Progression, Transfers & Chip Orchestrator
- Step-by-step gameweek advance with full point-in-time isolation (no future data leakage).
- Recommendation engine provides optimal transfer recommendations for the upcoming deadline.
- LLM strategic briefings contextualized for upcoming gameweek schedule and chip opportunities.

### Pillar 5: Season Finale Analytics & Local Report Export
- At GW38 completion, generates detailed performance summaries: total points, net points, rank estimate, captaincy success rate, transfer hit impact, and chip returns.
- Export options: JSON, Markdown, and CSV saved locally under `reports/simulations/`.

---

## 4. CLI & GUI Integration

### CLI Commands (`fpl sim`)
- `fpl sim create --season 2023-24 --id my-trial-01`
- `fpl sim list`
- `fpl sim status [--id <id>]`
- `fpl sim transfers [--id <id>]`
- `fpl sim make-transfer <out_id>:<in_id> [--id <id>]`
- `fpl sim lineup --starters "..." --captain "..." --vc "..." [--id <id>]`
- `fpl sim play-chip <chip_name> [--id <id>]`
- `fpl sim run-gw [--id <id>]`
- `fpl sim report [--id <id>] --export-markdown`

### Web Studio GUI
- Dedicated **"Time Machine / Historical Sim"** tab in Web GUI.
- Interactive pitch view, matchday run controller, transfer recommendations drawer, and chip activation panel.
