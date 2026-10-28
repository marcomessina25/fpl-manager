# V1.4.6 — Empirical Human-in-the-Loop Replay Benchmark Study

**Status:** Completed (5-Season Paired Two-Track Study: Track A vs. Track B; Track C Deferred)
**Predecessor:** V1.4.5 — Multi-Season Strategic Chip Optimization Study & Engine Unification
**Platform:** V1.4 — Interactive Historical Season Simulation & Time Machine Sandbox
**Corpus / Repo:** `marcomessina25/fpl-manager`
**Tracked Provenance Artifact:** [`reports/v146/human_benchmark_provenance.json`](../../reports/v146/human_benchmark_provenance.json)
**Verification Script:** [`scripts/verify_v146_human_benchmark.py`](../../scripts/verify_v146_human_benchmark.py)

---

## 1. Executive Summary & Scientific Purpose

Building on the V1.4 Historical Simulation platform (point-in-time snapshots, zero-spoiler standings/fixtures, isolated session state) and the V1.4.5 Strategic Chip Optimizer (`ChipOpportunityOptimizer`, `c1_linear_decay`), **V1.4.6 executes and audits the 5-season Human-in-the-Loop Replay Benchmark** (`2021-22` through `2025-26`, 190 simulated gameweeks).

The study empirically evaluates paired human + software decision-making against the autonomous frozen reference engine under identical initial conditions and strict point-in-time information boundaries:

1. How does a human manager equipped with point-in-time algorithmic projections, combinatorial transfer solving, and opportunity-cost chip valuations (Track B) perform relative to the autonomous reference engine (Track A)?
2. When the human operator overrides algorithmic transfer, captaincy, or chip recommendations, what is the realized gameweek and season-level decision alpha?
3. How does human-in-the-loop intervention behave across turbulent rescheduling/postponement seasons (`2021-22`, `2022-23`, `2024-25`) versus sustained template-scoring streaks (`2023-24`)?

---

## 2. Experimental Design, Scope & Replay Tracks

### 2.1 Evaluated & Deferred Tracks
To isolate human intervention on top of the advisory engine, the V1.4.6 benchmark evaluates two paired tracks from identical GW1 starting states across all 5 historical seasons:

- **Track A — Engine-Only Deterministic Baseline (Executed)**:
  - The frozen reference pipeline (`DecisionEngineV135` with $H=3, \gamma=0.75, W_{\text{bench}}=0.15, \text{GK}_{\text{hurdle}}=3.0$, quantitative predictor `v0.9.1-frozen`, and `ChipOpportunityOptimizer` `c1_linear_decay`) executes autonomously from GW1 to GW38 inside the same simulation session (`engine_baseline_*`).
- **Track B — Human-Assisted Replay (Executed, Operator `EXP-HM-01`)**:
  - At each gameweek deadline $t \in [1, 38]$, the human operator (`EXP-HM-01`) inspects point-in-time software recommendations (ranked transfer candidates, optimal starting XI/captaincy, and segment-wide chip opportunity valuations) and commits the final pre-deadline decision.
- **Track C — Human Blind Control (Deferred)**:
  - Originally conceived as an unassisted information-only control track. Track C was **not executed in V1.4.6** and is explicitly deferred to future multi-participant trials to avoid confounding single-operator memory effects across repeated plays of the same historical season.

### 2.2 Initial State Parity & Information Boundary Guarantees
- **Identical Starting State**: In every season, Track A and Track B initialize at GW1 from the exact same 15-player `maximum_ev` Strategic Studio squad, identical purchase prices, identical bank balance, `free_transfers = 1`, and identical chip inventory.
- **Zero-Spoiler Point-in-Time Enforcement**: All projections, multi-GW planner trajectories, chip opportunity-cost roadmaps, league standings, and fixture cards strictly consume data available prior to the simulated gameweek deadline (`current_gw`). Future match scores, realized points, and post-deadline price changes are masked.

---

## 3. Historical Replay Ruleset Policy (`V146-24`)

To ensure readers and reviewers can cleanly distinguish **era-authentic historical data** from the **standardized simulation ruleset** applied during replay, the V1.4.6 benchmark operates under the following explicit ruleset specification:

| Rule Dimension | Policy Applied in V1.4 / V1.4.5 / V1.4.6 Replays | Era-Authentic vs. Standardized Status |
| :--- | :--- | :--- |
| **Player Pool, Prices & Fixtures** | Loaded strictly from `data/historical/<season>` point-in-time snapshots (`GW1..GW38`), including mid-season Premier League departures (`departures_registry.json`) and double/blank gameweeks. | **Era-Authentic Data** |
| **Matchday Scoring & Autosubs** | Official FPL matchday points, goalkeeper/outfield formation constraints ($\ge 1$ GK, $\ge 3$ DEF, $\ge 2$ MID, $\ge 1$ FWD), captain/vice-captain fallback, and `-4 pt` per excess transfer hit penalty. | **Era-Authentic Rules** |
| **GW1 $\to$ GW2 Free Transfer Rollover** | Unlimited pre-GW1 squad construction never banks an extra transfer into GW2; entering GW2 always starts with `free_transfers = 1`. | **Era-Authentic Rules** |
| **Free Transfer Banking Cap (`max_free_transfers`)** | Season-gated in `HistoricalSimulationSession`: `max_free_transfers = 2` for `2021-22`, `2022-23`, and `2023-24`; `max_free_transfers = 5` for `2024-25` and `2025-26`. | **Era-Authentic Rules** |
| **Seasonal Chip Windows** | Standardized two-segment chip inventory across all 5 replayed seasons: **Segment 1 (`GW1–19`)** (`wildcard_1`, `free_hit`, `bench_boost`, `triple_captain`) and **Segment 2 (`GW20–38`)** (`wildcard_2`, `free_hit_2`, `bench_boost_2`, `triple_captain_2`), with unplayed Segment 1 chips expiring and resetting entering GW20. | **Standardized Two-Segment Simulation Ruleset** (shared by both Track A and Track B for cross-season chip optimizer comparability) |

> **Note on Ruleset Scope**: Both Track A (autonomous engine baseline) and Track B (human-assisted operator) execute under the exact same ruleset within each paired session. Preserving the standardized two-segment chip window across all 5 seasons maintains consistency with the V1.4.5 `ChipOpportunityOptimizer` ablation benchmark.

---

## 4. Logged Metrics, Provenance & Verification (`V146-23`)

For every gameweek $t \in [1, 38]$ across all 5 seasons (`190` matched gameweeks):
1. **Point-in-Time Advisory Capture**:
   - `recommended_transfers`, `recommended_captain_id`, `recommended_chip`, and `predicted_lineup_xp`.
2. **Track B (Human-Assisted) & Track A (Engine Baseline) Resolution**:
   - `gross_points`, `transfer_hits` (normalized hit count), `transfer_hit_points` (`transfer_hits * 4`), `net_points` (`gross_points - transfer_hit_points`), `cumulative_net_points`, `chip_used`, and `transfers_executed`.
3. **Divergence & Override Classification**:
   - Per-GW realized net points delta: $\Delta \text{Net}_t = \text{Net}_{\text{Track B}, t} - \text{Net}_{\text{Track A}, t}$.
   - Explicit override flags (`is_human_override`, `transfer_override`, `captain_override`, `chip_override`).

### Reproducible Verification Command
All 190 gameweek traces, initial state parity records, and SHA-256 source checksums are committed in [`reports/v146/human_benchmark_provenance.json`](../../reports/v146/human_benchmark_provenance.json) and can be independently verified and aggregated via:

```powershell
python scripts/verify_v146_human_benchmark.py
```

Full statistical tables, per-season override breakdowns, and methodological limitations are published in [`reports/v146/human_benchmark_report.md`](../../reports/v146/human_benchmark_report.md).
