# Release Notes — V1.4.6: Historical Parity, Solver Hardening & Human Benchmark Study

## Overview
- **Version**: 1.4.6
- **Branch**: `v146`
- **Pull Request**: [#22](https://github.com/marcomessina25/fpl-manager/pull/22)
- **Scope**: 5-Season Paired Human-in-the-Loop Replay Benchmark (`V146-HITL-BENCHMARK-5S`), Full 1:1 Live vs. Historical Functional & Behavioral Parity, Solver & Undo Hardening (`V146-01` through `V146-25`), and Comprehensive Rule Integrity.

---

## 1. Multi-Season Performance Summary: Human-Assisted vs. Frozen Engine Baseline

Across all 5 audited historical seasons (`2021-22` through `2025-26`, 190 simulated gameweeks), paired human-assisted decision-making operating with point-in-time algorithmic assistance (Track B: Single Operator `EXP-HM-01` + Engine Advisory) was evaluated against the autonomous reference engine (Track A: Frozen `DecisionEngineV135` + `ChipOpportunityOptimizer` `c1_linear_decay`) from identical GW1 `maximum_ev` starting squads. Track C (unassisted blind human control) was deferred outside this single-operator study.

| Season | Session ID | Track B Gross | Track B Hits (Pts) | Track B Net | Track A Gross | Track A Hits (Pts) | Track A Net | Decision Alpha (B − A) | Outcome |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | `exp_hm_01_2021_22` | 1,988 | 3 (-12) | **1,976 pts** | 1,889 | 0 (-0) | 1,889 pts | **+87 pts** | Human-Assisted WIN |
| **2022-23** | `exp_hm_01_2022_23` | 2,085 | 3 (-12) | **2,073 pts** | 1,951 | 0 (-0) | 1,951 pts | **+122 pts** | Human-Assisted WIN |
| **2023-24** | `exp_hm_01_2023_24` | 2,170 | 11 (-44) | **2,126 pts** | 2,214 | 0 (-0) | 2,214 pts | **-88 pts** | Engine Baseline WIN |
| **2024-25** | `exp_hm_01_2024_25` | 2,234 | 4 (-16) | **2,218 pts** | 2,098 | 0 (-0) | 2,098 pts | **+120 pts** | Human-Assisted WIN |
| **2025-26** | `exp_hm_01_2025_26` | 2,137 | 5 (-20) | **2,117 pts** | 2,040 | 0 (-0) | 2,040 pts | **+77 pts** | Human-Assisted WIN |
| **5-Season Mean** | — | **2,122.8** | **5.2 (-20.8)** | **2,102.0 pts** | **2,038.4** | **0.0 (-0.0)** | **2,038.4 pts** | **+63.6 pts** | **4 / 5 Seasons (80.0%)** |

### Key Empirical Findings & Methodological Framing:
1. **Observed Paired Surplus (+63.6 pts Mean for Operator `EXP-HM-01`)**: Across 190 matched gameweeks, the human-assisted track outperformed the autonomous frozen baseline in 4 of 5 seasons (`2021-22`, `2022-23`, `2024-25`, `2025-26`). Because $N = 5$ seasons with a single operator (`EXP-HM-01`) is a paired case study rather than a multi-participant population sample, results are presented as audited empirical replay evidence rather than proof of universal statistical superiority.
2. **Proactive Structural Wildcarding vs. Template Persistence**: Operator `EXP-HM-01` achieved positive alpha during postponement- and rescheduling-heavy seasons (+122 pts in `2022-23`, +120 pts in `2024-25`, +87 pts in `2021-22`) through earlier structural Wildcards (`GW8–10`) and selective hit-taking (`3–5 hits/season`), whereas the zero-hit autonomous baseline prevailed in `2023-24` (-88 pts) when human over-trading (`11 hits`, `-44 pts`) underperformed patient holding of template streaks.
3. **Auditable Provenance & Ruleset Policy (`V146-23`, `V146-24`)**: Sanitized 190-GW decision traces, SHA-256 source checksums, and hit/net point reconciliations are committed in [`reports/v146/human_benchmark_provenance.json`](../reports/v146/human_benchmark_provenance.json) and verified via `python scripts/verify_v146_human_benchmark.py`. Replays combine era-authentic point-in-time player/fixture archives and era-gated free-transfer caps (`max_free_transfers = 2` for `2021-22`..`2023-24`, `5` for `2024-25`+) with universal `GW1 -> GW2` 1-FT rollover and the standardized two-segment chip inventory (`GW1–19` and `GW20–38`).

---

## 2. Comprehensive Bug Fix & Remediation Dossier (Fixed in V1.4.6)

### Bug 1: Live Manager Expected Points Rate Anomaly & Per-90 Clamping Scope
- **Pathology**: Small-sample baseline registry rates in live `ExpectedPointsProjection` caused low-minute players to produce distorted projections ($+30.0$ xP). Applying that clamp unconditionally to historical CSV readers also shifted frozen 2023-24 Track A backtest totals (`2,193 -> 2,265`).
- **Fix**: Scoped per-90 rate clamping (`expected_goals_per_90 <= 1.20`, `expected_assists_per_90 <= 1.00`) strictly to live SQLite database projections in `src/fpl_manager/expected_points.py`, preserving exact frozen historical backtest reproducibility (`2,193` net points in `2023-24`).

### Bug 2: Live Team Synchronization & Multi-Team FT Isolation (`V146-14`)
- **Pathology**: Live Manager skipped Gameweek 6 due to premature database records, and `suggest_transfers` called `sync_squad_with_current_gameweek` without propagating `team_id` / `config_dir`, leaking the `default` team's FT history into non-default teams.
- **Fix**: Restored valid GW6 pre-deadline state and propagated `team_id` and `config_dir` through `suggest_transfers.py`, `teams.py`, and `server.py`.

### Bug 3: Unified Live & Historical Transfers Tab & Horizon-1 Rescoring (`V146-02`)
- **Pathology**: Historical Time Machine lacked combinatorial multi-transfer solving, and `rescore_transfer_candidates` raised `UnboundLocalError: single_delta` whenever `eff_horizon == 1` (affecting `v1.2` and `horizon=1` queries).
- **Fix**: Unified Live and Historical modes onto `#live-transfers-wrapper` (1–5 transfers, 1–10 GW horizons, risk profiles, `v1.3.5` / `v1.2.5` engines), isolated manual trades to Decision Logger, and initialized `single_delta = delta` prior to the `eff_horizon > 1` branch in `src/fpl_manager/suggest_transfers.py`.

### Bug 4: Decision Logger Submission, Chip Validation & Context Rehydration (`V146-01`, `V146-10`, `V146-16`)
- **Pathology**: `handleDecisionSubmit` referenced undeclared `actual_points`, bypassed session chip validation via direct `sim.active_chip` assignment, extracted historical lineups via nonexistent `p.role` flags, and retained stale decision/picker state across mode switches.
- **Fix**: Restored validated `actual_points` / `transfer_hits` parsing, routed historical logger chips and lineups through `sim.play_chip()`, `sim.cancel_chip()`, and `sim.set_lineup()`, and added `resetDecisionLoggerUI()` with request-sequence guards and datalist rebuilding on context switches.

### Bug 5: Zero-Leakage Historical Multi-GW Beam Search & Atomic Step-0 Apply (`V146-04`, `V146-05`, `V146-08`, `V146-09`)
- **Pathology**: Historical `/api/plan` read future gameweek snapshots (`current_gw + offset`), used a 1-step + hardcoded `ROLL` substitute instead of beam search, only exposed horizons `1..5`, lacked stale-context guards, and submitted empty starter arrays on Step-0 Apply.
- **Fix**: Implemented `generate_historical_multi_gameweek_plan` in `src/fpl_manager/planner.py` using strictly point-in-time projections from `sim.get_current_snapshot()` across horizons `1..8` (evaluating `0`, `1`, and `2` transfers per step with legal formation optimization), added `starting_ids` and `bench_ids` to each step, added atomic backend endpoints (`POST /api/historical/simulations/<sid>/apply-plan-step` and `POST /api/plan/apply-step`), and enforced frontend provenance guards (`state.plannerRequestSeq`, `getCurrentPlannerContext()`).

### Bug 6: Squad-Sensitive Segment Chip Roadmap & Explicit Policy Selection (`V146-18`, `V146-19`)
- **Pathology**: Historical `/api/historical/simulations/<sid>/chips` fell back to hardcoded EVs (`14.5`, `12.0`, `9.5`, `8.5`) and `0.88` confidence when no immediate chip was triggered, and `FPL_CHIP_OPTIMIZER=1` overrode explicit `SeasonalChipPolicy(use_optimizer=False)` (`C0`) calls.
- **Fix**: Implemented `ChipOpportunityOptimizer.generate_segment_roadmap(sim, start_gw)` in `src/fpl_manager/simulation/chip_optimizer.py` computing squad-sensitive point-in-time EVs, dynamic opportunity costs, net utilities, confidences, and runner-up alternatives across `GW1–19` and `GW20–38`, and preserved explicit `use_optimizer` arguments over environment defaults in `src/fpl_manager/chip_strategy.py`.

### Bug 7: GW1/GW2 Free Transfer Rollover & Deterministic Human + Baseline Undo (`V146-03`, `V146-06`, `V146-07`)
- **Pathology**: Entering GW2 erroneously banked a rollover FT, historical Undo with `session_id: null` fell back to mutating the live team, Undo after staging left unowned incoming players in `starting_ids`, and Undo failed to restore `engine_baseline_*` state.
- **Fix**: Enforced `free_transfers = 1` entering GW2, blocked historical Undo without a valid `session_id` (HTTP 400), tracked `gw_start_state` to restore coherent pre-staging human ownership/lineup state, and restored all `engine_baseline_*` fields in `undo_last_gameweek()`.

### Bug 8: Atomic Batch Transfers, Committed Cost Deduplication & Mixed Chains (`V146-11`, `V146-12`, `V146-13`)
- **Pathology**: Sequential `stage_transfer()` calls rejected net-affordable multi-transfer bundles when an upgrade preceded a downgrade, `/api/transfers` double-subtracted `already_applied=True` Studio transfers from `bank_tenths`, and mixed committed/pending chains (`A -> B` applied, then `B -> C` staged) corrupted squad ownership and bank.
- **Fix**: Wired `POST /api/transfers/execute` to `sim.stage_transfers_batch(batch)`, excluded `already_applied` transfers from pending bank deductions, and partitioned committed vs. pending transfers in `run_gameweek()`.

### Bug 9: Blank-GW Zero Projections, Hit-Unit Migration & Banner Visibility (`V146-15`, `V146-17`, `V146-20`, `V146-21`)
- **Pathology**: Missing keys in `gw_breakdown_xp` during blank gameweeks fell back to average xP in `strategic_squad.py`, Strategic Studio retained candidates across player universes, legacy `transfer_hits` entries storing points (`4`, `8`) mixed with hit counts (`1`, `2`), and inline `style="display: none;"` hid `#lineup-status-banner`.
- **Fix**: Explicitly populated `0.0` for blank gameweeks in `gw_breakdown_xp`, scoped and validated Strategic Studio candidates by context (`mode`, `team_id`, `season`, `session_id`, `current_gw`), normalized hit units via `_normalize_history_hit_units()` on session load, and synchronized `#lineup-status-banner` visibility.

### Bug 10: Mid-Season Real-Life Transfers Team Quota Pruning (January Window)
- **Pathology**: Real-world mid-season transfers creating $>3$ players from a single club were not pruned if outgoing combinations failed to sell enough excess club players.
- **Fix**: Added strict outgoing club-quota pruning in `solve_transfers` (`src/fpl_manager/optimizer.py`), populated availability keys (`status`, `is_departed`, `is_unavailable`) on incoming optimizer dicts, and added the **⚠️ Team Quota Alert** banner.

---

## 3. Second PR Review Remediation Dossier (V146-R2-01 through V146-R2-23)

### Workstream A: Live Mutation Safety & Authoritative Finances (`V146-R2-01`, `V146-R2-04`)
- **Live Planner Step-0 Apply Atomicity (`gui/server.py`)**: Fixed `POST /api/plan/apply-step` signature call contracts (`captain_id=`, `vice_captain_id=`, `transfers=None`) and added atomic pre-mutation backups of both the squad file and SQLite database records (`decisions`, `decision_recommendations`), with automatic rollback if either transfer execution or lineup validation fails.
- **Strategic Studio Bank Preservation (`strategic_squad.py`, `suggest_transfers.py`)**: Added `effective_prices_tenths` to `StrategicConstraints`, pricing retained locked players at their selling price (`selling_price()`) rather than full repurchase price, and computed authoritative resulting bank directly from actual ownership changes, preserving unspent bank when appreciated players are retained.

### Workstream B: Planner Objectives & Risk Bounds (`V146-R2-05`, `V146-R2-06`, `V146-R2-07`, `V146-R2-08`, `V146-R2-09`)
- **Net Floor/Ceiling Beam Ranking (`planner.py`)**: Deducted `step_hits * 4` points from cumulative floor and ceiling metrics, preventing beam search from selecting hit-heavy dominated transfers under floor/ceiling profiles.
- **Free Hit Reversion Entering Step 1 (`planner.py`)**: Restored permanent squad ownership, purchase basis, and bank entering step 1 whenever Free Hit is active at step 0.
- **Active Scoring Chips in Plan Evaluations (`planner.py`)**: Incorporated Triple Captain (3x captain points) and Bench Boost (all bench player points) into step 0 evaluations without carrying bonuses past their 1-GW duration.
- **GW1 Preseason Hit-Free Actions (`planner.py`)**: Waived transfer hits and limits during GW1 planning, matching session execution rules.
- **Blank GW Non-Zero Future Bounds (`planner.py`)**: Derived future floor/ceiling bounds from non-blank fixture variance and positional volatility baselines rather than collapsing future weeks to zero.

### Workstream C: Chip Strategy Guardrails & Feasible Replacements (`V146-R2-10`, `V146-R2-11`, `V146-R2-16`)
- **Symmetrical Cooldowns & Guardrail Integrity (`simulation/chip_optimizer.py`)**: Enforced symmetrical cooldowns between Free Hit and Wildcard, eliminating fallbacks to `GUARDRAIL_BLOCKED` candidates and leaving genuinely unusable chips unscheduled with explicit reasons.
- **Achievable Budget-Feasible Replacements (`simulation/chip_optimizer.py`)**: Replaced unconstrained top-eleven player sums with `_calc_achievable_pool_xi_xp`, evaluating legal starting XIs strictly affordable under total capital.
- **Frozen Baseline Configuration Persistence (`simulation/session.py`)**: Pinned `baseline_chip_use_optimizer` and `baseline_chip_optimizer_variant` in `experiment_metadata` upon session creation, ensuring baseline reproducibility across reloads and environment settings.

### Workstream D: GUI Context Epoch & Lifecycle Safety (`V146-R2-02`, `V146-R2-03`, `V146-R2-18`, `V146-R2-19`, `V146-R2-20`)
- **Transfer Provenance Guards (`gui/static/app.js`)**: Tracked `transferRequestSeq` and `reqProvenance` across solve and apply cycles, discarding stale responses and rejecting applies against mismatched contexts.
- **Context Epoch Boundaries (`gui/static/app.js`)**: Incremented `state.contextEpoch` on mode, team, or simulation switches, rechecking captured context after each asynchronous boundary to prevent clobbering shared UI controls.
- **Historical Decision Logger Session Guard (`gui/static/app.js`)**: Guarded target-GW listeners against missing simulation sessions, preventing unintended live database queries.
- **Logger Chip Parity & Dynamic Enablement (`gui/static/app.js`)**: Standardized `toLoggerChipOptionValue()` across tab transitions and rebuilt chip enabled/disabled states dynamically from destination context.
- **Strategic Studio Constraint Isolation (`gui/static/app.js`)**: Emptied player pools and datalists upon context switch and disabled lock/exclude and solve controls until destination configurations are installed.

### Workstream E: Provenance Replay Audit & Semantic Verification (`V146-R2-21`, `V146-R2-22`, `V146-R2-23`)
- **Trace-Derived Provenance Export (`scripts/verify_v146_human_benchmark.py`)**: Derived summary chip usage directly from canonical gameweek trace events, eliminating stale dictionary artifacts.
- **Initial State Parity & Overlap Audit (`reports/v146/human_benchmark_report.md`)**: Reconciled initial starting state documentation: both tracks strictly started GW1 with £0.0m bank (full £100.0m team value) and 1 FT, with starting squads reflecting their respective generation policies (Strategic Studio for Track B vs. autonomous EV solver for Track A, resulting in 2..4/15 squad overlap).
- **Multi-Level Verification Architecture**: Added Level 1 arithmetic reconciliation, Level 2 semantic chip/override validation, and Level 3 raw trace SHA-256 integrity audits, backed by corruption rejection unit tests in `tests/test_benchmark_provenance.py`.

---

## 4. Verification & Test Suite Health (`V146-22`, `V146-25`, `V146-R2-22`)

- **Full Automated Pytest Suite**: **530 / 530 passing tests** (`python -m pytest -v`) across the entire repository with zero failures and zero warnings, including:
  - Historical GUI and simulation suites (`test_historical_gui_api.py`, `test_historical_simulation.py`)
  - Live GUI and planner apply tests (`test_gui.py`, `test_planner.py`, `test_decision_log.py`)
  - Strategic Studio and combinatorial solver suites (`test_strategic_squad_gui.py`, `test_strategic_squad_engine.py`, `test_suggest_transfers.py`)
  - Chip optimizer and guardrail parity suites (`test_chip_optimizer.py`, `test_chip_parity_and_regression.py`, `test_chip_strategy.py`)
  - Benchmark provenance verification and corruption suites (`test_benchmark_provenance.py`)
- **Static & Provenance Checks**:
  - `python -m compileall -q src tests scripts`: Passed (`0` errors).
  - `node --check .\src\fpl_manager\gui\static\app.js`: Passed (`0` syntax errors).
  - `python scripts/verify_v146_human_benchmark.py`: Passed (Level 1, 2, and 3 validation across 5 seasons, 190 gameweeks).
  - `git --no-pager diff --check origin/master...HEAD`: Passed (`0` whitespace/formatting issues).
