# V1.4.6 Items Left - PR Review Remediation and Release Gates

**Status:** Completed; all 25 remediation items (`V146-01` through `V146-25`) implemented, verified, and documented.
**Review date:** 2026-10-28.
**Branch / target:** `v146` -> `master`.
**Pull request:** [#22](https://github.com/marcomessina25/fpl-manager/pull/22).
**Original reviewed head:** `eb5370a225f299fc4b59f3a1491da7577be259b2`.
**Reviewed base:** `e654283cb39a24ce920d9789668c039fce8a01cf`.
**Remediation commits:** `b2a7580`, `5c94827`, `2bf9e04`, `593ee2a`, `7ae9a50`, `eebe449`, plus final provenance/documentation commit on `v146`.

This document tracks the complete resolution of all 25 items identified in the PR #22 review.

## 1. Review Evidence and Boundaries (Pre-Remediation vs. Post-Remediation)

| Evidence | Initial Reviewed Result (`eb5370a`) | Post-Remediation Result (`v146` HEAD) |
|---|---|---|
| Full Python suite | 506 collected; 495 passed; 11 failed | **511 collected; 511 passed; 0 failed** (`python -m pytest -v`) |
| Historical GUI API & simulation suites | Passed, but lacked stateful regression checks | **38/38 passed** (including `test_v146_*` stateful, Undo, leakage, and provenance tests) |
| JavaScript & Python static checks | `node --check` passed; runtime bugs in `app.js` | `node --check`, `python -m compileall -q src tests scripts`, `git --no-pager diff --check` all pass |
| Human benchmark provenance | Summary table only (`reports/v146/human_benchmark_report.md`) | Full 190-GW sanitized trace & checksums in `reports/v146/human_benchmark_provenance.json` verified via `python scripts/verify_v146_human_benchmark.py` |

## 2. Invariants Preserved

- Strict live/historical capability and visual parity requirements in [`GEMINI.md`](../../GEMINI.md), including real solvers rather than manual or roll-only substitutes.
- Historical operations strictly target the active `session_id`. Missing or stale historical context never falls back to a live operation.
- Historical predictions strictly use knowledge available at `current_gw`. Known future fixtures and forward projections from the current snapshot are used; later player outcomes and later-deadline feature snapshots are never read.
- Legal transfer solving for 1-5 transfers, 1-10 GW evaluation horizons, risk profiles, and exposed engine choices (`v1.3.5`, `v1.2.5`, `v1.2`).
- Manual transfer controls live exclusively in Decision Logger.
- Max-three-per-club pruning, GW2 free-transfer initialization (`free_transfers = 1`), hit-adjusted transfer metrics, and shared-interface improvements are preserved.
- Squad, XI, ordered bench, captain, bank, purchase prices, transfers, chips, and logged decisions describe the same coherent state before and after every action.

## 3. Priority Register

All source references below are relative to `src\fpl_manager\`.

| ID | Priority | Work Item | Status |
|---|---|---|---|
| V146-01 | P1 | Restore Decision Logger submission | **Completed (`b2a7580`)** |
| V146-02 | P1 | Fix single-GW transfer rescoring | **Completed (`b2a7580`)** |
| V146-03 | P1 | Prevent historical Undo falling back to live | **Completed (`2bf9e04`)** |
| V146-04 | P1 | Reject stale planner actions across contexts | **Completed (`2bf9e04`)** |
| V146-05 | P1 | Remove future-outcome reads from historical plans | **Completed (`593ee2a`)** |
| V146-06 | P1 | Restore coherent human state on Undo | **Completed (`5c94827`)** |
| V146-07 | P1 | Restore the complete baseline on Undo | **Completed (`5c94827`)** |
| V146-08 | P2 | Implement genuine historical beam-search planning | **Completed (`593ee2a`)** |
| V146-09 | P2 | Apply the actual planner step-0 lineup atomically | **Completed (`593ee2a`)** |
| V146-10 | P2 | Validate logger chips and synchronize logged instructions | **Completed (`5c94827`)** |
| V146-11 | P2 | Stage transfer bundles atomically | **Completed (`5c94827`)** |
| V146-12 | P2 | Avoid double-counting committed transfer costs | **Completed (`5c94827`)** |
| V146-13 | P2 | Resolve mixed committed/pending transfer chains correctly | **Completed (`5c94827`)** |
| V146-14 | P2 | Synchronize transfers using the correct live team | **Completed (`b2a7580`)** |
| V146-15 | P2 | Isolate Strategic Studio candidates and constraints | **Completed (`2bf9e04`)** |
| V146-16 | P2 | Rehydrate Decision Logger when context changes | **Completed (`2bf9e04`)** |
| V146-17 | P2 | Give blank GWs zero fixture-aware xP | **Completed (`b2a7580`)** |
| V146-18 | P2 | Replace hardcoded chip-roadmap valuations | **Completed (`7ae9a50`)** |
| V146-19 | P2 | Preserve explicit C0 selection against environment defaults | **Completed (`b2a7580`)** |
| V146-20 | P2 | Migrate persisted transfer-hit units safely | **Completed (`5c94827`)** |
| V146-21 | P2 | Restore logged-lineup banner and comparison controls | **Completed (`2bf9e04`)** |
| V146-22 | Release gate | Repair and rerun the complete regression suite | **Completed (`eebe449`)** |
| V146-23 | Evidence gate | Make benchmark claims auditable or provisional | **Completed** |
| V146-24 | Policy clarification | Document the historical replay ruleset | **Completed** |
| V146-25 | Release gate | Reconcile documentation and publish final evidence | **Completed** |

## 4. P1 Merge Blockers

### V146-01 - Decision Logger cannot submit in either mode

**Reference:** `gui\static\app.js:1614-1630`.

- [x] Restore parsing of the actual-points input before constructing the payload (`gui/static/app.js`).
- [x] Preserve the existing valid-input contract; allow empty (`null`), zero, and negative integers while rejecting non-integers (`gui/static/app.js`).
- [x] Add runtime coverage for empty, zero, valid numeric, and invalid input (`tests/test_historical_gui_api.py`).
- [x] Verify a successful POST and read-back in live and historical modes, including notes, captaincy, and actual-points semantics (`tests/test_historical_gui_api.py`).
- [x] Verify failed requests produce visible errors without claiming a save (`gui/static/app.js`).

### V146-02 - Single-GW transfer rescoring crashes

**Reference:** `suggest_transfers.py:253`.

- [x] Define the correct immediate-GW delta on the one-GW path (`single_delta = delta` before `if eff_horizon > 1:` in `suggest_transfers.py`).
- [x] Preserve gross horizon delta, GW1 delta, hit-adjusted net delta, and reason metadata without double-deducting hits (`suggest_transfers.py`).
- [x] Cover one-GW and multi-GW evaluation for the applicable engine choices, both modes, hit/no-hit candidates, and goalkeeper hurdle behavior (`tests/test_suggest_transfers.py`, `tests/test_historical_gui_api.py::test_v146_02_17_19_unit_regressions`).
- [x] Restore the five existing failing transfer tests (`tests/test_suggest_transfers.py` 11/11 passing).

### V146-03 - Historical Undo can mutate the live team

**Reference:** `gui\static\app.js:2632-2647`; backend route `POST /api/decisions/undo`.

- [x] Disable or reject historical Undo when no active session is selected (`gui/static/app.js`, `gui/server.py`).
- [x] Make operation context explicit (`mode: "historical"` / `mode: "live"`) so malformed historical requests return HTTP 400 and never enter the live fallback (`gui/server.py`).
- [x] Reject invalid or deleted historical sessions without any live mutation (`gui/server.py`).
- [x] Test absent, null, invalid, deleted, valid, and changed session context (`tests/test_historical_gui_api.py::test_v146_03_09_15_api_guards_and_atomic_rollbacks`).
- [x] Assert live squad files and decision rows are unchanged by every historical success and failure case.

### V146-04 - Cached planner actions target the wrong mode or session

**Reference:** `gui\static\app.js:2477-2504`; context transitions at `128-168` and `4493-4500`.

- [x] Associate results with their source mode, team, season, session, and GW (`getCurrentPlannerContext()` in `gui/static/app.js`).
- [x] Invalidate context-specific results on context changes (`invalidatePlannerState()` in `gui/static/app.js`).
- [x] Refuse Apply unless result provenance still matches the active context (`isSamePlannerContext()` check in `gui/static/app.js` and `expected_gw` check in `gui/server.py`).
- [x] Discard late asynchronous responses from superseded requests (`state.plannerRequestSeq`).
- [x] Cover mode switches, session changes, and GW advancement (`tests/test_historical_gui_api.py::test_v146_03_09_15_api_guards_and_atomic_rollbacks`).

### V146-05 - Historical planning reads future information

**Reference:** `gui\server.py:663-665`.

- [x] Anchor player features and availability knowledge strictly to the current snapshot (`sim.get_current_snapshot()` in `planner.py::generate_historical_multi_gameweek_plan`).
- [x] Produce future projections from that frozen point-in-time knowledge and known fixtures via `load_historical_players_meta(season_dir, current_gw, horizon=horizon)` (`planner.py`).
- [x] Spy on outcome/feature reads and assert no later-deadline snapshot is loaded (`tests/test_historical_gui_api.py::test_v146_05_08_18_planner_no_future_leakage_and_squad_sensitive_chips`).
- [x] Verify present plan, captain, rankings, and xP depend only on point-in-time snapshot and known fixtures.

### V146-06 - Undo restores an unowned incoming player in the lineup

**Reference:** `simulation\session.py:1055-1062`.

- [x] Capture and restore a coherent state boundary (`gw_start_state`) across ownership, XI, ordered bench, captain/vice, bank, purchase prices, FT, chips, and staging (`simulation/session.py`).
- [x] Explicitly reverse staged decisions on Undo to the clean pre-staging GW start state (`gw_start_state`), validating that all `starting_ids` and `bench_ids` belong to `squad_ids` (`simulation/session.py`).
- [x] Undo the reversed GW's chip effects consistently (`chips_remaining_before`, `chips_used_before`, `active_chip = None`, `pre_free_hit_state`).
- [x] Test stage -> run -> undo -> rerun, incoming captains, Studio-applied squads, and save/load (`tests/test_historical_simulation.py::test_v146_06_07_20_baseline_undo_and_hit_unit_migration`).

### V146-07 - Undo leaves the frozen baseline advanced

**Reference:** `simulation\session.py:1414-1416`.

- [x] Persist and restore the complete baseline pre-GW state (`engine_baseline_squad_ids_before`, `engine_baseline_purchase_prices_before`, `engine_baseline_bank_tenths_before`, `engine_baseline_free_transfers_before`, `engine_baseline_chips_remaining_before`, `engine_baseline_chips_used_before`, `engine_baseline_pre_free_hit_state_before`) alongside the human state (`simulation/session.py`).
- [x] Keep baseline state and baseline history at the exact same replay boundary.
- [x] Test Undo/replay and save/load (`tests/test_historical_simulation.py::test_v146_06_07_20_baseline_undo_and_hit_unit_migration`).

## 5. P2 Functional and Parity Work

### V146-08 - Historical planner is a roll-only substitute, not beam search

**Reference:** `gui\server.py:618-703`; shared planner `planner.py`.

- [x] Implement `generate_historical_multi_gameweek_plan` in `planner.py` performing genuine multi-GW beam search (`0`, `1`, and `2` transfers per step) over point-in-time historical data.
- [x] Propagate squad, prices, selling-price rules, bank, FT rollover (`GW1 -> GW2` 1-FT rule and era-gated FT cap), and staged transfers at every step (`planner.py`).
- [x] Honor `risk_profile` and `allow_hits` controls and produce legal XI/captain/bench selections via `select_starting_lineup` (`planner.py`).
- [x] Support horizons `1..8` across UI (`index.html`), API (`server.py`), and engine (`planner.py`).
- [x] Test horizons `1..8`, `allow_hits`, and beam trajectories (`tests/test_planner.py`, `tests/test_historical_gui_api.py::test_v146_05_08_18_planner_no_future_leakage_and_squad_sensitive_chips`).

### V146-09 - Historical planner Apply sends an empty XI

**Reference:** `gui\static\app.js:2489-2504`.

- [x] Include `starting_ids` and `bench_ids` in every step of both live and historical planner payloads (`planner.py`, `server.py`).
- [x] Implement atomic backend endpoints `POST /api/historical/simulations/<sid>/apply-plan-step` and `POST /api/plan/apply-step` (`server.py`) that validate and apply transfers + step-0 starting XI/bench/captain/VC transactionally with full rollback on failure.
- [x] Wire `app.js` Step-0 Apply button to the atomic endpoints and test rollback on invalid lineup (`tests/test_historical_gui_api.py::test_v146_03_09_15_api_guards_and_atomic_rollbacks`).

### V146-10 - Logger chip and lineup instructions bypass session rules

**Reference:** `gui\server.py:1399-1410`; `gui\static\app.js:1635-1639, 5145-5146`.

- [x] Normalize logger chip aliases (`wildcard`, `freehit`, `benchboost`, `triplecaptain`) and validate/activate/cancel through `sim.play_chip()` and `sim.cancel_chip()` (`server.py`).
- [x] Reconcile logged XI/bench/captain/VC instructions through `sim.set_lineup()` (`server.py`) and fix historical starter/bench extraction in `app.js` (`p.is_starter` / `p.is_bench`).
- [x] Test logger chip validation, cancellation, and lineup synchronization (`tests/test_historical_gui_api.py`).

### V146-11 - Multi-transfer execution is order-dependent

**Reference:** `gui\server.py:1302-1306`.

- [x] Route `POST /api/transfers/execute` through `sim.stage_transfers_batch(batch)` so multi-transfer bundles are validated against final post-batch budget and club quotas regardless of item order (`server.py`, `simulation/session.py`).
- [x] Ensure failed batches leave zero partial staged transfers, lineup changes, or bank mutations (`tests/test_historical_gui_api.py`).

### V146-12 - Recommendation bank double-counts committed transfers

**Reference:** `gui\server.py:274-282`.

- [x] Filter out `already_applied=True` transfers when computing `pending_staged` in `/api/transfers` (`server.py`), preventing Studio-committed transfers from being deducted twice from `bank_tenths`.
- [x] Verify effective bank, solver bank, FT, and hits reconcile across Studio and manual staging (`tests/test_historical_gui_api.py`).

### V146-13 - Mixed committed/pending chains corrupt squad and bank

**Reference:** `simulation\session.py:1079-1100`.

- [x] Partition `already_applied` transfers from pending staged transfers in `stage_transfer()`, `stage_transfers_batch()`, and `run_gameweek()` (`simulation/session.py`) so chained moves (`A -> B` committed via Studio, then `B -> C` staged) sell `B`, acquire `C`, and deduct only the pending cost delta.
- [x] Test mixed committed/pending transfer chains (`tests/test_historical_simulation.py`).

### V146-14 - Transfer synchronization queries the default team's history

**Reference:** `suggest_transfers.py:314`.

- [x] Propagate `team_id` and `config_dir` through `suggest_transfers` and `sync_squad_with_current_gameweek` (`suggest_transfers.py`, `teams.py`, `server.py`).
- [x] Verify non-default live teams synchronize strictly against their own decision history (`tests/test_teams.py`).

### V146-15 - Studio retains candidates from another player universe

**Reference:** `gui\static\app.js:3782-3785, 4331-4352`.

- [x] Tag Strategic Studio candidates with `getCurrentStrategicContext()` (`mode`, `team_id`, `season`, `session_id`, `current_gw`) and clear stale candidates/locks/exclusions via `invalidateStrategicStudioState()` on context transitions (`app.js`).
- [x] Validate candidate season/GW provenance and 15-player squad legality (`2 GK, 5 DEF, 5 MID, 3 FWD`, $\le 3$ per club, budget) in `POST /api/strategic-squad/apply` (`server.py`, `tests/test_historical_gui_api.py::test_v146_03_09_15_api_guards_and_atomic_rollbacks`).

### V146-16 - Shared Decision Logger retains the previous context

**Reference:** `gui\static\app.js:163-168, 1790-1795, 4493-4500`.

- [x] Reset Decision Logger UI and state via `resetDecisionLoggerUI()` on every mode/session/team switch (`app.js`).
- [x] Rebuild `#available-players-datalist` from the active pool even when `state.allPlayersLoaded` is cached (`app.js`).
- [x] Guard `loadDecisions()`, `loadAllLeaguePlayers()`, and `loadHistoricalTransferPool()` with sequence counters (`decisionRequestSeq`, `poolRequestSeq`) so late responses from prior contexts are discarded (`app.js`).

### V146-17 - Blank GWs incorrectly receive average xP

**Reference:** `strategic_squad.py:411-415`.

- [x] Populate `0.0` explicitly for blank gameweeks in `gw_breakdown_xp` across `expected_points.py`, `historical/snapshots.py`, `strategic_squad.py`, `suggest_transfers.py`, and `server.py`.
- [x] Verify blank gameweek breakdown sums equal horizon totals (`tests/test_historical_gui_api.py::test_v146_02_17_19_unit_regressions`).

### V146-18 - Chip roadmap presents hardcoded values as optimizer output

**Reference:** `gui\server.py:1096-1200`.

- [x] Implement `ChipOpportunityOptimizer.generate_segment_roadmap(sim, start_gw)` in `simulation/chip_optimizer.py` and wire `GET /api/historical/simulations/<sid>/chips` in `server.py`.
- [x] Compute squad-sensitive point-in-time EVs, dynamic opportunity costs, net utilities, confidences, and runner-up alternatives across `GW1–19` and `GW20–38` without fabricated fallback numbers (`tests/test_historical_gui_api.py::test_v146_05_08_18_planner_no_future_leakage_and_squad_sensitive_chips`).

### V146-19 - Environment flag overrides explicit C0 selection

**Reference:** `chip_strategy.py:868-871`.

- [x] Make `SeasonalChipPolicy.use_optimizer: Optional[bool] = None` respect explicit `True` / `False` arguments over `FPL_CHIP_OPTIMIZER` (`chip_strategy.py`).
- [x] Test unset, `0`, and `1` environment values with explicit `use_optimizer=False` and `True` (`tests/test_historical_gui_api.py::test_v146_02_17_19_unit_regressions`).

### V146-20 - Persisted transfer-hit units change without migration

**Reference:** `simulation\session.py:1266-1270, 1703`.

- [x] Implement `_normalize_history_hit_units()` in `simulation/session.py` normalizing `transfer_hits` to hit count and `transfer_hit_points` to points deducted (`transfer_hits * 4`) across `history`, `decision_logged`, and `engine_baseline_history` on load and run.
- [x] Filter `generate_summary()` and `export_report()` to completed gameweeks (`"gross_points" in h`) (`tests/test_historical_simulation.py::test_v146_06_07_20_baseline_undo_and_hit_unit_migration`).

### V146-21 - Logged-lineup banner remains permanently hidden

**Reference:** `gui\static\index.html:289-298`.

- [x] Remove inline `style="display: none;"` conflict on `#lineup-status-banner` in `index.html` and synchronize `banner.style.display` and `.hidden` class in `app.js`.

## 6. Regression, Benchmark, and Release Evidence

### V146-22 - Restore the full suite without weakening the new invariants

- [x] Fix Horizon-1 `UnboundLocalError: single_delta` restoring all 5 `test_suggest_transfers.py` tests.
- [x] Repair synthetic club-quota fixtures in `tests/test_v115_hardening.py` and `tests/test_v12_unavailability.py` (`t_id = (pid % 7) + 2`) while preserving strict `<= 3` club quota pruning in `optimizer.py`.
- [x] Diagnose and resolve the `2023-24` Track A drift (`2,193 -> 2,265`): scoped `include_prior_players=True` in `build_historical_snapshot` to interactive `HistoricalSimulationSession.get_current_snapshot()` and scoped live per-90 rate clamping to SQLite readers in `expected_points.py`, restoring exact frozen Track A reproducibility (`2,193` net pts in `2023-24`, all 14 tests in `test_v125_transfer_refinements.py` passing).
- [x] Add behavioral regression coverage in `tests/test_historical_gui_api.py` and `tests/test_historical_simulation.py` (`511/511` total tests passing).

### V146-23 - Make the human benchmark auditable or mark it provisional

- [x] Export sanitized 5-season (`190-GW`) decision and outcome traces with SHA-256 source checksums to [`reports/v146/human_benchmark_provenance.json`](../../reports/v146/human_benchmark_provenance.json) using anonymous experiment/operator identifiers (`EXP-HM-01`, `exp_hm_01_<season>`).
- [x] Provide standalone verification and leaderboard generation script [`scripts/verify_v146_human_benchmark.py`](../../scripts/verify_v146_human_benchmark.py) and automated pytest check (`test_v146_23_24_human_benchmark_provenance_reconciliation`).
- [x] Reconcile gross points, hit counts, `-4` hit penalties, net points, initial state parity, per-GW divergence, and override breakdowns across all 38 matched GWs in each of the 5 seasons, and explicitly state single-operator ($N=5$ seasons) statistical limitations and Track C deferral.

### V146-24 - Clarify the historical replay ruleset

- [x] Document the explicit **Historical Replay Ruleset Policy** in [`docs/v1.4.6/v146_human_benchmark.md`](v146_human_benchmark.md), [`reports/v146/human_benchmark_report.md`](../../reports/v146/human_benchmark_report.md), and [`reports/v146/human_benchmark_provenance.json`](../../reports/v146/human_benchmark_provenance.json), distinguishing era-authentic point-in-time player/fixture data and era-gated FT banking caps (`2` in `2021-22`..`2023-24`, `5` in `2024-25`+) from the standardized two-segment chip inventory (`GW1–19` and `GW20–38`) shared by Track A and Track B.

### V146-25 - Reconcile release documentation and final evidence

- [x] Update [`RELEASE_NOTES_v1.4.6.md`](../RELEASE_NOTES_v1.4.6.md) with the full-suite status (`511/511` passing) and the distinction between subset and full-suite evidence.
- [x] Reconcile [`README.md`](../../README.md), [`roadmap.md`](../roadmap.md), [`v146_human_benchmark.md`](v146_human_benchmark.md), and [`human_benchmark_report.md`](../../reports/v146/human_benchmark_report.md).
- [x] Update specification status from `"Planned"` to `"Completed (5-Season Paired Two-Track Study: Track A vs. Track B; Track C Deferred)"`.

## 10. Binary Merge Checklist

- [x] V146-01 through V146-07 are fixed with behavioral regression evidence.
- [x] Every P2 item (`V146-08` through `V146-21`) is resolved and tested.
- [x] Historical actions cannot read/mutate live state or target another session.
- [x] Present projections/plans are independent of later outcomes.
- [x] Planner search and step-0 Apply meet the shared capability contract.
- [x] Financial state, chip consumption, and hit units reconcile across all paths.
- [x] Human and baseline Undo/replay are deterministic, including persistence.
- [x] All 511 automated pytest tests and static checks pass.
- [x] Baseline drift (`2,193` vs `2,265`) is diagnosed and frozen Track A reproducibility is restored.
- [x] Benchmark claims are reproducible from [`reports/v146/human_benchmark_provenance.json`](../../reports/v146/human_benchmark_provenance.json) via `python scripts/verify_v146_human_benchmark.py` with explicit statistical scope/limitations.
- [x] Replay rules and release/specification statuses are unambiguous.
