# V1.4.6 — Empirical Human-in-the-Loop Replay Benchmark Study

**Status:** Recorded five-season end-to-end strategy comparison; Track C deferred
**Predecessor:** V1.4.5 — Multi-Season Strategic Chip Optimization Study & Engine Unification
**Platform:** V1.4 — Interactive Historical Season Simulation & Time Machine Sandbox
**Corpus / Repo:** `marcomessina25/fpl-manager`
**Tracked Provenance Artifact:** [`reports/v146/human_benchmark_provenance.json`](../../reports/v146/human_benchmark_provenance.json)
**Verification Script:** [`scripts/verify_v146_human_benchmark.py`](../../scripts/verify_v146_human_benchmark.py)

---

## 1. Executive Summary & Scientific Purpose

Building on the V1.4 Historical Simulation platform (point-in-time snapshots, zero-spoiler standings/fixtures, isolated session state) and the V1.4.5 Strategic Chip Optimizer (`ChipOpportunityOptimizer`, `c1_linear_decay`), **V1.4.6 executes and audits the 5-season Human-in-the-Loop Replay Benchmark** (`2021-22` through `2025-26`, 190 simulated gameweeks).

The study empirically evaluates an **end-to-end strategy comparison**: a human operator equipped with point-in-time algorithmic projections, combinatorial transfer solving, and opportunity-cost chip valuations (Track B) against the autonomous frozen reference engine (Track A) across all decisions from season initiation through season conclusion. Both tracks begin with identical bank (£0.0m, fully invested) and 1 free transfer, but employ different squad-selection strategies, resulting in distinct 15-player starting lineups (2–4/15 overlap):

1. How does an end-to-end human-in-the-loop strategy (Track B: Strategic Studio initial selection + human-assisted decisions) perform relative to an end-to-end autonomous strategy (Track A: autonomous EV solver initial selection + frozen engine decisions)?
2. What is the observed net surplus when tracking both initial squad composition and subsequent human-assisted interventions across the full season?
3. How does human-in-the-loop intervention behave across turbulent rescheduling/postponement seasons (`2021-22`, `2022-23`, `2024-25`) versus sustained template-scoring streaks (`2023-24`)?

---

## 2. Experimental Design, Scope & Replay Tracks

### 2.1 Evaluated & Deferred Tracks
The V1.4.6 benchmark evaluates two paired tracks operating under identical information and regulatory constraints but employing distinct strategic approaches:

- **Track A — Engine-Only Deterministic Baseline (Executed)**:
  - Initial 15-player squad: Autonomously selected via the frozen reference engine's EV optimizer.
  - Gameweek decisions: The frozen reference pipeline (`DecisionEngineV135` with $H=3, \gamma=0.75, W_{\text{bench}}=0.15, \text{GK}_{\text{hurdle}}=3.0$, quantitative predictor `v0.9.1-frozen`, and `ChipOpportunityOptimizer` `c1_linear_decay`) executes autonomously from GW1 to GW38 inside the same simulation session (`engine_baseline_*`).
- **Track B — Human-Assisted End-to-End Strategy (Executed, Operator `EXP-HM-01`)**:
  - Initial 15-player squad: Manually selected by operator `EXP-HM-01` using Strategic Studio candidate generation and refinement.
  - Gameweek decisions: At each gameweek deadline $t \in [1, 38]$, the human operator inspects point-in-time software recommendations (ranked transfer candidates, optimal starting XI/captaincy, and segment-wide chip opportunity valuations) and commits the final pre-deadline decision.
- **Track C — Human Blind Control (Deferred)**:
  - Originally conceived as an unassisted information-only control track. Track C was **not executed in V1.4.6** and is explicitly deferred to future multi-participant trials to avoid confounding single-operator memory effects across repeated plays of the same historical season.

### 2.2 Recorded Initial Conditions & Information Boundary
- **Bank and FT Consistency**: Both recorded starting states have bank 0 and one FT. Their stored chip-inventory lists are reported explicitly, not assumed identical.
- **Distinct Initial Squads**: Track A and Track B generate independent 15-player squads through different selection methods, resulting in 2–4/15 overlap across the five seasons.
- **Point-in-Time Engineering Requirement**: Current historical projections, plans, chip advice, standings and fixture cards must use knowledge available at `current_gw`. Regression tests exercise this boundary, but do not retroactively prove that every retained original trial used the corrected pipeline.

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
The committed artifact contains 190 gameweek records, both starting states, and declared source digests. The command checks arithmetic, semantic totals, and initial metadata consistency. It checks raw-source digests only for files actually present and explicitly lists unavailable checks:

```powershell
python scripts/verify_v146_human_benchmark.py
```

Full statistical tables, per-season override breakdowns, and methodological limitations are published in [`reports/v146/human_benchmark_report.md`](../../reports/v146/human_benchmark_report.md).

### Legacy Serialized Keys Compatibility Note
The summary metrics in the provenance artifact retain historical key names `mean_decision_alpha_points` and `decision_alpha_net_points` for backward compatibility with earlier analysis pipelines. These keys describe the **observed net surplus** across end-to-end strategies (initial selection + later decisions), not an isolated identical-start post-decisional alpha treatment. When interpreting these fields, distinguish between the observed gross difference and causal attribution: the recorded value is the measured outcome difference, not proof that post-start decisions alone produced that margin.

### Scope & Retroactive Validation Limitations (Important)
The recorded 190-gameweek traces constitute **descriptive case-study evidence** under the code and execution environment at the time of original replay. This followup fix task has corrected contradictions in *documentation and framing* but has **not rescored or rerun the 190-GW benchmark**. Consequently:
- The net totals (gross points, transfer hits, net points per season) remain unchanged from original execution.
- Current regression tests validate the corrected code pipeline but do not retroactively establish which code produced every original advisory.
- The recorded traces are retained as authentic historical replay records under their original execution context, not independent verification of the corrected engine.
- Future independent rescores with the corrected pipeline may produce different results and would require separate publication as new trials.
- No claim is made that all human advice recorded in the original traces was generated by the current fixed advisory pipeline or that the traces validate the corrected system.
Source verification distinguishes whether recorded metadata is *internally consistent* from whether those results would be independently reproduced by rescoring with corrected code. See [`reports/v146/human_benchmark_report.md`](../../reports/v146/human_benchmark_report.md) Section 4.3 for scope boundaries and single-operator/five-season limitations.
