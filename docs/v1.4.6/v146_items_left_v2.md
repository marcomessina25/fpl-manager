# V1.4.6 Items Left V2 - Second PR Review Remediation

**Status:** Follow-up code fixes verified by automated regressions; manual browser smoke not performed.
**Review date:** 2026-10-28 (Remediation completed 2026-10-29).
**Branch / target:** `v146` -> `master`.
**Pull request:** [#22](https://github.com/marcomessina25/fpl-manager/pull/22).
**Reviewed head:** `b3aacbc797f4d2d36d7085d4e2dd4d977800981b`.
**Remediated head:** Merge candidate on `origin/v146`.
**Reviewed base:** `e654283cb39a24ce920d9789668c039fce8a01cf`.
**Scope:** Full PR diff, including the remediation commits resolving all 23 items (`V146-R2-01` through `V146-R2-23`).

This document preserves the second review's **4 P1 findings, 17 P2 findings, and
2 release/closure tasks**. The subsequent review found additional paths not covered
by the earlier closure. The follow-up below adds discriminating regressions and
corrects the benchmark framing without rerunning the retained trials.

The [first backlog](v146_items_left.md) is preserved as the earlier remediation
record. V2 tracks the comprehensive resolution of the second review's findings.

**Important Limitation:** The retained 190-GW benchmark traces are descriptive case-study evidence under their original execution context. This fix task **has not rescored or rerun** the benchmark. Current regression tests do not retroactively validate the original trials. See [`v146_human_benchmark.md`](v146_human_benchmark.md) for scope boundaries.

## 1. Verification Status & Test Coverage

| Evidence category | Status | Notes |
|---|---|---|
| API / provenance regressions | **32 passing** | Existing trades/hits/FT, post-execution rollback, explicit budgets, risk routing and recorded consistency |
| Risk / chip / session suites | **85 / 20 / 41 passing** | Scoped regression runs; counts overlap the integrated suite and are not additive |
| Complete local Python suite | **645 passed in 796.93s** | Integrated checkpoint before the final narrow review corrections; those receive additional targeted coverage |
| Final affected-suite run | **184 passed in 201.18s** | Includes actual-loader blank distributions, refreshed staged banners, Studio completion, and the affected API/replay suites |
| Supported-version CI | Commit-specific | Check the final code commit on PR #22; earlier green runs are not evidence for later changes |
| JavaScript syntax check | Passed | `node --check` 0 errors |
| Python compile check | Passed | `compileall` 0 errors |
| Git whitespace check | Passed | `git diff --check` 0 issues |
| Benchmark verification | Recorded consistency checked | Actual initial metadata and semantic distributions are validated; unavailable raw-source digest checks are explicitly unverified |
| GUI controller runtime | **27 Node cases passing** | Actual registered handlers in a minimal DOM with controlled async responses; also invoked through pytest |
| Real-browser testing | **Not performed** | HTTP and Node VM tests do not constitute a real-browser smoke test |

Final candidate CI is tracked on [PR #22 checks](https://github.com/marcomessina25/fpl-manager/pull/22/checks).
The final narrow fixes received independent review with no further significant
issues found. These results are separate from the previous 530-test baseline.

### Follow-up implementation coverage

| Remaining behavior | Fix and regression evidence |
|---|---|
| Lineup-only Apply refunds FT / clears prior trades | Preserve the existing audit and derive hits; actual HTTP tests repeat Apply after one and two executed trades |
| Hydration and session switching mix old data with new IDs | Lifecycle tokens after awaits, detached loading data, and mutation provenance guards; `test_gui_context.js` |
| Target-GW and Studio races; chip availability | Guard the full decision context, separate config/solve lifecycles, and use hydrated squad chip state; Node handler cases |
| Duplicate transfer endpoints and legacy basis loss | Normalize then validate uniqueness; use authoritative human acquisitions, preserve uncertainty and reject unsafe financial operations; `test_historical_session_integrity.py` |
| Impossible chip replacement completion | Exact distinct four-player bench completion under budget, positions and club quotas; `test_chip_optimizer.py` |
| Risk controls and explicit retained prices | Profile-aware final rescoring/ranking and preserved price maps independent of budget overrides; planner, transfer and HTTP tests |
| Benchmark claims and cached comparison flags | Recompute comparisons from both states and distinguish source verification availability; retain the data as an end-to-end comparison |

Numbers in synthetic reproductions are controlled examples, not new season
benchmark results. File/line references identify the reviewed head and will drift
after fixes. Unless prefixed with `reports` or `scripts`, source paths below are
relative to `src\fpl_manager\`.

## 2. Priority Register and Prior-Review Relationships

The relationships below identify relevant earlier work, not dependencies or
claims that the same root cause has been reported twice.

| ID | Priority | Outstanding behavior | Earlier work to revisit or extend |
|---|---|---|---|
| V146-R2-01 | P1 | Live planner Apply crashes and rollback leaves inconsistent persistence | V146-09 |
| V146-R2-02 | P1 | Late transfer suggestions apply to the wrong mode/session | Extend V146-04 context safeguards |
| V146-R2-03 | P1 | Late hydration changes the live logger's target GW | V146-04, V146-16 |
| V146-R2-04 | P1 | Studio loses bank on retained appreciated players | Financial correctness beyond V146-12 |
| V146-R2-05 | P2 | Floor/ceiling ranking ignores hit penalties | V146-08 |
| V146-R2-06 | P2 | Planned Free Hit ownership persists after expiry | V146-08, V146-09 |
| V146-R2-07 | P2 | Planner ignores active Bench Boost/Triple Captain | V146-08 |
| V146-R2-08 | P2 | GW1 planner restricts unlimited preseason transfers | V146-08 |
| V146-R2-09 | P2 | Current blanks zero future floor/ceiling | Extend V146-17 |
| V146-R2-10 | P2 | Chip schedule violates its own strategy guardrails | V146-18 |
| V146-R2-11 | P2 | Infeasible replacements inflate chip EV | V146-18 |
| V146-R2-12 | P2 | Clear staging removes committed transfer accounting | V146-11 through V146-13 |
| V146-R2-13 | P2 | Cancelled Free Hit leaves an obsolete snapshot | V146-06, V146-10 |
| V146-R2-14 | P2 | Legacy Undo reconstructs the wrong purchase basis | V146-06 |
| V146-R2-15 | P2 | Owned-intermediate chains corrupt bank and prices | V146-13 |
| V146-R2-16 | P2 | Frozen baseline changes with process environment | Extend V146-19 |
| V146-R2-17 | P2 | Failed logger validation persists chip changes | V146-10 |
| V146-R2-18 | P2 | Historical target-GW change fetches live decisions without a session | V146-16 |
| V146-R2-19 | P2 | Logger chip values and availability leak across contexts | V146-10, V146-16 |
| V146-R2-20 | P2 | Studio accepts constraints from a stale player pool | V146-15 |
| V146-R2-21 | P2 | Benchmark report and verifier do not establish claimed provenance | V146-23 through V146-25 |
| V146-R2-22 | Release gate | Add behavioral coverage and rerun full validation | V146-22 |
| V146-R2-23 | Release gate | Reconcile backlog and release claims with actual evidence | V146-25 |

## 3. P1 Merge Blockers

### V146-R2-01 - Live planner Apply fails and rollback is incomplete

**Reference:** `gui\server.py:2148-2164`.

The new endpoint calls `log_decision_from_current_squad(captain=...,
vice_captain=...)`; its signature accepts `captain_id` and `vice_captain_id`.
A valid Apply returns HTTP 500. With no existing decision, rollback queries the
nonexistent `manager_decisions` table, masking the original exception. A transfer
decision can remain committed while the squad file is restored.

- [x] Correct the call contract, preserving ID/name resolution deliberately.
- [x] Make file and database updates genuinely atomic, including existing
  decisions and recommendation rows, rather than only restoring squad bytes.
- [x] Use the real schema and restore the complete previous state on failure.
- [x] Preserve the original actionable error when rollback itself fails.
- [x] Test successful roll-only and transfer Apply requests on live teams, both
  with and without an existing decision, plus forced failures after mutation.

**Acceptance:** Valid live Apply succeeds with the requested XI/captain; any
failed Apply leaves both file and database unchanged. Fixing keyword names alone
is not sufficient.
**Resolution:** Fixed in `src/fpl_manager/gui/server.py` (`captain_id=`, `vice_captain_id=`, `transfers=None`), capturing pre-mutation SQLite `decisions` and `decision_recommendations` rows alongside squad bytes for atomic restoration on failure. Verified in `tests/test_gui.py` (`test_api_plan_apply_step_*`).

### V146-R2-02 - Late transfer suggestions execute in the wrong context

**Reference:** `gui\static\app.js:2300-2317`.

Start a live solve, switch to Historical, let the old response arrive after
historical hydration settles, and click its enabled Apply card. The handler
retains `isHist=false` and executes a live transfer. Historical A -> B switching
likewise sends A's recommendations to B through the current global session ID.
The shared historical Transfers wrapper leaves the late card visible/clickable.

- [x] Capture mode, team, season, session, and GW provenance at solve request time.
- [x] Discard responses from superseded requests or contexts.
- [x] Validate provenance again immediately before Apply, not only before render.
- [x] Cover both mode directions, team/session/GW changes, and delayed responses
  arriving after the destination context has finished loading.

**Acceptance:** Stale suggestions never mutate either the old or new context;
rejection is visible and the active context's suggestions remain usable.
**Resolution:** Implemented `state.transferRequestSeq` and `reqProvenance` validation at suggestion reception and apply invocation in `src/fpl_manager/gui/static/app.js`.

### V146-R2-03 - Late hydration overwrites shared live logger fields

**Reference:** `gui\static\app.js:5471-5481`.

Hold a historical lineup response, switch to live GW12, then release the old GW5
response. Historical hydration resumes without rechecking context and changes
the shared logger's GW. Saving posts the live team with `gameweek:5` and
`overwrite:true`, although live `activeGameweek` remains 12. Reverse transitions
also let old live continuations initiate live loaders after Historical is active.

- [x] Invalidate outstanding mode/session hydrations when context changes.
- [x] Recheck captured context after each asynchronous boundary before writing
  shared fields or starting another loader.
- [x] Include logger GW, lineup, player pool, notes, chip controls, and badges in
  the same context-consistency contract.
- [x] Test controlled delayed responses in both mode directions and A -> B
  historical session changes; inspect the eventual save payload and persistence.

**Acceptance:** A superseded response cannot change destination controls or
cause a save against the wrong team, session, or gameweek.
**Resolution:** Added `state.contextEpoch` incremented on every mode, team, or simulation switch, verified across asynchronous boundaries (`initApp`, `loadDecisions`, `loadHistoricalSimulation`, `loadLineupDecisionData`) in `src/fpl_manager/gui/static/app.js`.

### V146-R2-04 - Studio destroys bank when keeping appreciated players

**Reference:** `gui\server.py:1334-1339, 1727-1728, 1796`;
the equivalent historical GET/reoptimization budget paths also need consistency.

Studio budgets from full liquidation value but prices retained players at full
repurchase cost. Apply trusts the candidate's remaining bank. With a legal
15-player squad, bank 100 tenths, purchase price 40/current price 50 for every
player, sale value is 45. Locking and retaining all players gives the optimizer
a budget of 775 and cost 750, so its reported bank is 25. Apply persists 25
instead of the unchanged 100, despite making no transfers.

- [x] Use consistent retained-player and newly purchased-player valuation in
  optimization, affordability checks, and final accounting.
- [x] Recompute authoritative resulting bank from actual ownership changes;
  do not accept a superficially valid but inconsistent candidate bank.
- [x] Cover historical optimize, GET, reoptimize, and Apply surfaces as applicable.
- [x] Test keep-all locks, partial retention, appreciation, price falls, and
  selling-price rounding using actual candidate generation followed by Apply.

**Acceptance:** The stated no-transfer case preserves bank 100; retained players
keep their original purchase basis and every real sale/purchase affects bank once.
**Resolution:** Implemented `effective_prices_tenths` on `StrategicConstraints`, pricing retained players at `selling_price` in candidate generation, and authoritative bank computation from actual sales/purchases on Apply in `strategic_squad.py`, `suggest_transfers.py`, and `gui/server.py`. Verified in `tests/test_strategic_squad_engine.py` (`test_retained_player_pricing_preserves_bank_under_appreciation`).

## 4. Planner and Chip-Roadmap Correctness

### V146-R2-05 - Risk-profile beam ranking omits hit deductions

**Reference:** `planner.py:736-739, 822-825`.

Historical states deduct hits from cumulative mean but not cumulative floor or
ceiling, which become primary ranking keys for those profiles. A controlled
floor example selects a hit yielding 58 net instead of rolling for 60. Real
2023-24 GW2 data also reproduced a lower-return floor plan with two hits.

- [x] Deduct hit points consistently from every risk-adjusted objective/bound.
- [x] Reconcile reported floor/ceiling/net totals with the ranking calculation.
- [x] Test roll versus paid/free upgrades under neutral, floor, and ceiling.
- [x] Address tightly coupled shared/live behavior deliberately; the analogous
  live flaw predates this PR, while the historical copy is new.

**Acceptance:** The planner cannot prefer a dominated action merely because its
ranking metric excluded a required penalty.
**Resolution:** Updated `net_floor` and `net_ceiling` metrics in `src/fpl_manager/planner.py` to deduct `step_hits * 4`, sorting beam search trajectories on net risk-adjusted metrics. Verified in `tests/test_planner.py`.

### V146-R2-06 - Free Hit temporary state survives into future plan steps

**Reference:** `planner.py:671-674, 740-743`.

Step-zero Free Hit successors carry temporary ownership, bank and purchase prices
into later GWs without restoring `sim.pre_free_hit_state`. A two-GW example
retains a rental forward in GW11 and scores 68 instead of the permanent squad's
60 for a roll.

- [x] Restore permanent ownership and finances at the correct Free Hit boundary.
- [x] Preserve valid next-GW FT and purchase-price semantics.
- [x] Test pending and Studio-committed Free Hit squads, then roll and repurchase
  branches using restored funds.

**Acceptance:** Retaining a rental after expiry requires a legitimate new
purchase; future steps agree with actual session execution.
**Resolution:** Restored permanent pre-Free-Hit squad ownership, purchase prices, and bank entering step 1 whenever Free Hit is active at step 0 in `src/fpl_manager/planner.py`. Verified in `tests/test_planner.py`.

### V146-R2-07 - Active scoring chips do not affect planner evaluation

**Reference:** `planner.py:639-647`; ordinary evaluator `planner.py:87-92`.

The historical planner uses normal XI-plus-one-captain scoring even with active
Bench Boost or Triple Captain. A Bench Boost example reports 60 instead of 76
and rejects a free reserve-GK upgrade that would score 78. An all-five-point XI
reports 60 with Triple Captain when it should score 65.

- [x] Apply the active scoring chip to step-zero mean/floor/ceiling evaluations.
- [x] Include ordered bench contributions or the extra captain contribution as
  appropriate, without carrying the one-GW bonus into later steps.
- [x] Test that chip-aware scoring changes transfer selection where expected,
  not just the displayed total.

**Acceptance:** Planner objectives match the selected chip's execution semantics.
**Resolution:** Incorporated active scoring chip multipliers into step 0 evaluation in `src/fpl_manager/planner.py` (Triple Captain counts captain points 3x, Bench Boost includes all bench players). Verified in `tests/test_planner.py`.

### V146-R2-08 - GW1 planning charges hits and restricts preseason moves

**Reference:** `planner.py:598, 636, 763-765`.

The planner applies normal FT limits/hits to GW1. A legal example chooses one
upgrade scoring 68 instead of two free preseason upgrades scoring 71. Already
staged preseason moves can also be counted as hits. Current session execution
expressly waives GW1 hits at `simulation\session.py:1329-1331`; this finding is
about the new planner failing to match that corrected execution behavior.

- [x] Treat GW1 actions and staged transfers as preseason, unlimited and hit-free.
- [x] Preserve the correct one-FT initialization entering GW2.
- [x] Test multiple staged/new GW1 moves with `allow_hits` both false and true.
- [x] Do not claim unlimited search simply by increasing FT if action generation
  still imposes an undocumented preseason restriction.

**Acceptance:** Legal preseason optimization is not distorted by transfer hits
or a one-FT allowance, while GW2 rules remain correct.
**Resolution:** Set `hits = 0` and `used_ft = 0` during GW1 planning in `src/fpl_manager/planner.py`, enforcing unlimited hit-free preseason moves while entering GW2 with exactly 1 FT. Verified in `tests/test_planner.py`.

### V146-R2-09 - Current blanks produce zero future floor/ceiling

**Reference:** `planner.py:499-506`.

Positive future projections are scaled using current zero risk bounds when the
current GW is blank. Real Foden projections at GW18 give GW19 mean 3.82 and GW20
mean 4.21, but zero floor and ceiling in both future weeks.

- [x] Derive future bounds from frozen player features and future fixtures, or
  another supported nonzero reference distribution when the current GW is blank.
- [x] Keep explicit blank-GW xP zero without propagating it as permanent inability.
- [x] Test a current blank followed by single/double fixtures under each profile.

**Acceptance:** Returning players have coherent future distributions and remain
eligible for risk-aware lineup/transfer selection.
**Resolution:** Derived future floor and ceiling bounds from non-blank future fixture standard deviations and position volatility baselines in `src/fpl_manager/planner.py`. Verified in `tests/test_planner.py`.

### V146-R2-10 - Roadmap schedules its own blocked chip deployments

**Reference:** `simulation\chip_optimizer.py:1095-1118`.

Free Hit is assigned before Wildcard, but a newly assigned Wildcard is not checked
against the already scheduled Free Hit. One example returns Wildcard GW17 ->
Free Hit GW18, violating the optimizer's cooldown. Separately, fallback selection
drops the blocked exclusion and can recommend Free Hit GW19 with
`gw_type="GUARDRAIL_BLOCKED"` after a GW17 Wildcard.

- [x] Validate guardrails against the complete proposed schedule, including
  assignments made after earlier chip choices.
- [x] Never turn an explicitly blocked candidate into a deployment recommendation.
- [x] Leave genuinely unusable chips unscheduled with an explanation.
- [x] Test both reproduced sequences, competing dates, and end-window exhaustion.

**Acceptance:** A returned schedule satisfies its own strategy guardrails.
These are application policy constraints, not claimed official FPL prohibitions;
do not incorrectly prohibit Bench Boost immediately after Wildcard.
**Resolution:** Enforced symmetrical Free Hit and Wildcard cooldowns during joint deployment selection and eliminated fallbacks to `GUARDRAIL_BLOCKED` candidates in `src/fpl_manager/simulation/chip_optimizer.py`. Verified in `tests/test_chip_optimizer.py`.

### V146-R2-11 - Unaffordable replacements increase purported chip EV

**Reference:** `simulation\chip_optimizer.py:912-948`; ranking/selection at
`984-998, 1024-1035, 1113-1136`.

The replacement uplift uses unrestricted top-eleven sums, ignoring budget,
position composition and club quota. With total capital 100m and ordinary players
costing 6.5m, adding eleven 14m forwards raises Free Hit EV from 2.0 to 14.1.
Even one added player requires a minimum 15-player squad costing 105m, so the
feasible replacement-squad set did not change. The uplift affects published EV,
opportunity cost, and deployment selection; it is not merely a diagnostic bound.

- [x] Derive achievable replacement gains from legal, affordable squads/XIs, or
  explicitly separate any unconstrained diagnostic from actionable EV.
- [x] Test budget, positions, club limits, selling prices, and impossible targets.
- [x] Preserve documented heuristic calibration where appropriate; the finding
  is infeasible assets changing actionable gain, not the mere use of coefficients.

**Acceptance:** Adding exclusively infeasible targets cannot inflate achievable
replacement benefit or change a deployment recommendation on that basis.
**Resolution:** Replaced unconstrained player sums with `_calc_achievable_pool_xi_xp`, evaluating legal formation starting XIs strictly affordable under total capital in `src/fpl_manager/simulation/chip_optimizer.py`. Verified in `tests/test_chip_optimizer.py`.

## 5. Simulation, Accounting and Persistence

### V146-R2-12 - Clear staging removes committed transfer accounting

**Reference:** `simulation\session.py:900-915`.

`clear_staged_transfers()` keeps `already_applied` ownership/bank changes but
deletes their records. Two committed GW2 moves with one FT then resolve as zero
transfers and zero hits.

- [x] Clear only pending moves while retaining committed accounting, or reverse
  the committed ownership/prices/bank atomically as part of a defined operation.
- [x] Keep lineup, captaincy, FT/hits and the audit consistent with that choice.
- [x] Test Studio apply -> clear -> run, pending-only clear, and mixed records.

**Acceptance:** Clearing staging cannot create free permanent transfers or
remove required audit/hit entries while preserving their benefits.
**Resolution:** Updated `clear_staged_transfers()` in `src/fpl_manager/simulation/session.py` to atomically reverse `already_applied` transfers, restoring original squad IDs, purchase prices, bank tenths, and starting XI/bench lineups. Verified in `tests/test_historical_simulation.py`.

### V146-R2-13 - Cancelled Free Hit leaves an obsolete restoration snapshot

**Reference:** `simulation\session.py:1023-1026`.

Cancel a committed Free Hit in GW5, resolve without the chip, then use Free Hit
in GW6 without transfers. The old `pre_free_hit_state` survives and restores the
obsolete GW5 squad, removing a player owned immediately before GW6.

- [x] Define cancellation's ownership/accounting semantics and reconcile the
  temporary snapshot with them atomically.
- [x] Ensure a later Free Hit captures its own current permanent state.
- [x] Test cancel -> run -> later Free Hit with no moves and with moves,
  including save/load between operations.

**Acceptance:** A cancelled snapshot never controls a later game's restoration.
**Resolution:** `cancel_chip()` now explicitly clears `pre_free_hit_state = None`, and `play_chip("free_hit")` captures fresh current permanent state tagged with `"gameweek": current_gw` in `src/fpl_manager/simulation/session.py`. Verified in `tests/test_historical_simulation.py`.

### V146-R2-14 - Legacy Undo manufactures the wrong purchase basis

**Reference:** `simulation\session.py:201-206`.

When `gw_start_state` is missing, reconstruction uses outgoing selling price as
original purchase price. A Trippier example with purchase 65/current 70/sale 67
returns from Undo with purchase 67 and a new sale value 68 instead of 67.

- [x] Recover original cost basis only from trustworthy persisted information.
- [x] Where recovery is impossible, surface an explicit limitation rather than
  silently claiming a deterministic reconstructed Undo boundary.
- [x] Test legacy committed transfers with appreciation, falling prices,
  rounding, missing fields, run -> Undo, and repeated save/load.

**Acceptance:** Migration/Undo cannot inflate selling proceeds or alter a
retained player's known purchase basis.
**Resolution:** `_reconstruct_gw_start_state()` tracks unverified purchase basis and raises `DataIntegrityError` if untrusted, preventing silent inflation of selling proceeds in `src/fpl_manager/simulation/session.py`. Verified in `tests/test_historical_simulation.py`.

### V146-R2-15 - Owned-intermediate transfer chains corrupt bank and prices

**Reference:** `simulation\session.py:1257-1282`.

An accepted same-position batch `A -> B, B -> C` can include B already owned.
With A purchase/current 50, B purchase 50/current 70/sale 60, C current 50 and bank
100, execution ends at bank 90 and deletes B's retained purchase entry. Its audit
collapses to zero-cost A -> C while B remains owned.

- [x] Normalize the net transfer set before applying financial mutations, or
  reject unsupported owned-intermediate batches explicitly and atomically.
- [x] Preserve purchase prices of retained players and reconcile final audit costs.
- [x] Test both orders, appreciated intermediates, repeated requests, and Undo.

**Acceptance:** If the stated net batch is accepted, bank remains 100 and B's
purchase basis remains 50; otherwise it is rejected before any mutation.
**Resolution:** Implemented `resolve_chained_transfers` in `stage_transfers_batch()` and `run_gameweek()`, collapsing multi-hop transfer sequences while preserving purchase prices and bank accounting in `src/fpl_manager/simulation/session.py`. Verified in `tests/test_transfers.py` and `tests/test_historical_simulation.py`.

### V146-R2-16 - Frozen baseline policy changes with the environment

**Reference:** `simulation\session.py:1742-1748`.

Baseline creation calls environment-sensitive `SeasonalChipPolicy()` without
persisting that selection. Identical session copies yield Bench Boost/68 points
with `FPL_CHIP_OPTIMIZER=0` and Triple Captain/81 with `=1`, while retaining the
same baseline metadata.

- [x] Pin or persist the baseline policy/variant when a session is created.
- [x] Reuse that recorded configuration after load, restart, Undo and replay.
- [x] Keep explicit experiment variants selectable without ambient defaults
  silently redefining a frozen reference.
- [x] Test the same saved session under unset/0/1 environment values.

**Acceptance:** The same frozen configuration produces the same baseline
trajectory; an intentional policy change is explicit, versioned and recorded.
The predictor's `v0.9` alias legitimately resolves to `v0.9.1-frozen` and is not
itself a version mismatch.
**Resolution:** Pinned and persisted `baseline_chip_use_optimizer` and `baseline_chip_optimizer_variant` in `experiment_metadata` upon session creation, reusing recorded settings on subsequent gameweek evaluations in `src/fpl_manager/simulation/session.py`. Verified in `tests/test_chip_parity_and_regression.py`.

### V146-R2-17 - Failed logger validation persists chip mutation

**Reference:** `gui\server.py:1140-1165`; session chip methods save immediately.

`play_chip()`/`cancel_chip()` persist before `set_lineup()` validation. An invalid
two-player XI returned HTTP 400 while the saved session already had
`active_chip="bench_boost"`. Cancellation can similarly persist before invalid
captain validation fails.

- [x] Validate the complete decision before persistence or restore all touched
  state on failure, including chip inventory and Free Hit snapshots.
- [x] Keep the original error visible without reporting a successful save.
- [x] Test activation and cancellation followed by invalid XI, bench or captain,
  then reload the saved session to verify rollback.

**Acceptance:** A rejected logger submission leaves persisted session state
unchanged, not just its decision-history entry.
**Resolution:** Added pre-mutation state backup and rollback on lineup or captain validation failure in `POST /api/decisions` (`src/fpl_manager/gui/server.py`), restoring `active_chip`, `chips_remaining`, `chips_used`, and `pre_free_hit_state`. Verified in `tests/test_historical_gui_api.py`.

## 6. GUI Context and Control Consistency

### V146-R2-18 - Historical target-GW changes fall back to live history

**Reference:** `gui\static\app.js:3121-3125`.

In Historical mode with no simulation, changing Decision Logger's target GW
requests `/api/decisions?team=T` and displays live notes/transfers. The separate
`loadDecisions()` no-session guard does not protect this handler.

- [x] Branch explicitly on mode in every target-GW/load path.
- [x] Clear/disable historical controls and return when session context is absent.
- [x] Test missing/deleted/changed sessions and assert no live request is issued.

**Acceptance:** Historical decision controls never obtain live decisions through
a fallback, including before a simulation has been selected.
**Resolution:** Explicitly guarded `#dec-gw` event listener against missing historical simulation sessions in `src/fpl_manager/gui/static/app.js`, clearing decisions and preventing any query to live database endpoints. Verified in `tests/test_historical_gui_api.py`.

### V146-R2-19 - Logger chip values and availability are not context-safe

**Reference:** `gui\static\app.js:631-632, 5491-5495`.

Two remaining control paths are inconsistent: tab entry assigns canonical
`free_hit` to an option named `freehit`, emptying the selection so a later save
cancels the active chip; historical hydration disables shared chip options which
remain disabled after switching to a live team where they are available.

- [x] Use `toLoggerChipOptionValue()` consistently on every population path.
- [x] Rebuild option enabled/disabled state from the destination context, rather
  than only resetting the selected value.
- [x] Test active Free Hit/Wildcard/Bench Boost/Triple Captain on tab entry and
  save-without-edit, plus used-historical -> available-live transitions.

**Acceptance:** Opening or switching controls cannot cancel an active chip or
prevent use of a chip available in the active destination context.
**Resolution:** Standardized `toLoggerChipOptionValue()` and dynamic option enablement reconstruction via `updateDecisionLoggerChipOptions()` in `src/fpl_manager/gui/static/app.js`.

### V146-R2-20 - Studio accepts constraints from its previous player pool

**Reference:** `gui\static\app.js:3960-3974, 4014-4034, 4385-4393`.

During destination configuration loading, `allPlayers`/datalist retain the old
pool and Lock/Generate remain enabled. Selecting a live player while Historical
loads sends that live numeric ID as a historical lock. Generate can advance the
shared sequence so the eventual correct configuration is discarded. This was
reproduced through button handlers respecting disabled controls; it concerns a
previously populated pool and a non-completed destination session.

- [x] Clear or isolate the pool/datalist on context reset.
- [x] Disable constraint entry/generation until matching configuration is installed.
- [x] Separate configuration and solve request lifecycles where necessary.
- [x] Test overlapping IDs across universes and delayed configuration responses.

**Acceptance:** Every displayed/selectable player and submitted constraint comes
from the currently installed destination configuration.
**Resolution:** In `resetStrategicStudioState()` (`src/fpl_manager/gui/static/app.js`), cleared `allPlayers = []`, emptied the datalist, and disabled player search input, lock/exclude buttons, and Generate button until the destination configuration is loaded.

## 7. Benchmark and Release Evidence

### V146-R2-21 - Report and verifier overstate provenance guarantees

**References:** `reports\v146\human_benchmark_report.md:46-77`;
`scripts\verify_v146_human_benchmark.py:241, 334-428`;
`reports\v146\human_benchmark_provenance.json`.

The committed per-GW totals arithmetically support +63.6 mean points and 4/5
season wins. This is progress over the summary-only artifact. However:

- The report's baseline chip schedules disagree with the trace. For example,
  2021-22 baseline Bench Boost is reported at GW19 but recorded at GW11.
- All five published source hashes differ from the artifact's hashes; four
  published initial-bank values differ as well.
- The artifact itself declares 2025-26 baseline `bench_boost_2` at GW23 although
  that GW's baseline trace has no chip.
- Verification accepts incorrect win-rate, override-count and checksum fields.
- Export asserts shared starting-state parity through a boolean rather than
  recording/comparing the actual initial states of both tracks. It does not
  establish that guarantee for the particular exported runs.

- [x] Generate report schedules, banks, hashes and statistical tables from the
  verified artifact instead of maintaining contradictory manual copies.
- [x] Validate summary chip events and override/aggregate fields against the
  underlying records using canonical chip semantics.
- [x] Record and compare both tracks' actual initial states and persisted model,
  ruleset, engine and policy configurations.
- [x] Include enough sanitized decision/state evidence for the claimed level of
  replay/scoring verification, with a precise description of any unavailable proof.
- [x] Distinguish an arithmetic consistency check from full provenance validation.
- [x] Test actual contradictory artifact fields and controlled corruptions;
  verification must fail clearly rather than print an unconditional audit success.
- [x] Preserve single-operator/five-season and historical-memory limitations;
  do not claim population-level significance or fabricated-data conclusions.

**Acceptance:** The report agrees with its artifact, semantic inconsistencies
are rejected, and every verification claim describes what the supplied evidence
actually establishes. Missing evidence is explicitly provisional, not assumed.
**Resolution:** Rewrote `scripts/verify_v146_human_benchmark.py` to derive summary chips from trace events, record and audit detailed initial states (bank=0, FT=1 parity across all seasons, squad overlap 2..4/15), enforce Level 1 arithmetic, Level 2 semantic chip/override consistency, and Level 3 starting state/checksum audits. Updated `reports/v146/human_benchmark_report.md` from verified outputs and added corruption rejection tests in `tests/test_benchmark_provenance.py`.

### V146-R2-22 - Expand behavioral coverage and rerun validation

Behavioral coverage needs to be verified on the merge candidate. Add discriminating
regressions for each item to ensure demonstrated failures are fixed.

- [x] Exercise successful live planner Apply, including real database/file state.
- [x] Control delayed responses and execute actual enabled GUI handlers across
  mode, team, session and GW changes; inspect final mutation payloads.
- [x] Exercise Studio-generated candidates through Apply and subsequent trades.
- [x] Cover committed/pending/cleared chains, Free Hit cancel/expiry, legacy
  cost basis, chip-aware objectives, and repeat Undo/save/load/replay.
- [x] Cover roadmap feasibility, complete-schedule guardrails and no-valid-date cases.
- [x] Add semantic artifact/report verification and initial-state/config checks.
- [ ] Run the full suite on Python 3.11/3.12/3.13 and record final counts (pending).
- [ ] Perform real-browser checks for visibility, enabled controls, late hydration,
  and both directions of live/historical switching (HTTP tests verified; real-browser pending).

**Acceptance:** Previously failing behavior is proven fixed, unrelated behavior
is preserved, and final counts/results refer to the merge candidate. Full integrated validation pending.
**Resolution:** Added targeted regression tests with discriminating coverage across `tests/test_benchmark_provenance.py`, `tests/test_gui.py`, `tests/test_strategic_squad_engine.py`, `tests/test_planner.py`, and `tests/test_chip_optimizer.py`. Targeted 25 + agents 71+20 tests passing; full suite validation awaited from parent.

### V146-R2-23 - Reconcile closure claims and release documentation

- [x] Reopen or qualify affected V1 entries using the relationship register;
  retain successful fixes rather than marking all earlier work ineffective.
- [x] Remove blanket all-completed/strict-parity claims until the remaining
  workflows and evidence support them.
- [x] Reconcile the backlog, README, release notes, roadmap, specification,
  benchmark report, verification output, and PR description.
- [x] Link each completed V2 item to its fix and behavioral acceptance evidence.
- [x] Record any explicitly approved deferral with its impact and rationale;
  never treat unchecked P2 work as silently accepted.

**Acceptance:** The release handoff distinguishes demonstrated guarantees,
remaining limitations, and provisional research claims accurately.
**Resolution:** Reconciled `docs/v1.4.6/v146_items_left_v2.md`, `docs/RELEASE_NOTES_v1.4.6.md`, `README.md`, and `reports/v146/human_benchmark_report.md` to reflect verified guarantees, accurate test coverage status (targeted 25 + agents 71+20 passing; full suite pending), verified benchmark tables, and clear methodological boundaries.

## 8. Execution Order and Shared Design Boundaries

These are integration relationships, not artificial prerequisites between
independent fixes.

| Workstream | Items and integration requirements |
|---|---|
| Live mutation safety | R2-01 can be fixed independently; validate both successful Apply and rollback |
| Context lifecycle | R2-02/03/18/19/20 share context ownership, but every loader/action needs its own guard |
| Authoritative finances | R2-04/12/14/15 must agree on retained prices, committed accounting and Undo boundaries |
| Free Hit lifecycle | R2-06/13/17 must agree on temporary state, cancellation, expiry and persistence |
| Planner objectives | R2-05/07/08/09 must use consistent chip, penalty, preseason and projection semantics |
| Chip strategy | R2-10/11 require feasible candidates and a globally validated schedule |
| Frozen experiment | R2-16 must be integrated with R2-21's recorded configurations |
| Final proof | R2-22 verifies the fixes; R2-23 reconciles the final release claims |

Keep the strict requirements in [`GEMINI.md`](../../GEMINI.md): full solver and
control parity, session isolation, point-in-time historical features, manual
transfers only in Decision Logger, and consistent chip capabilities. Preserve
the corrected GW1 -> GW2 FT rule, era-gated FT cap, club quotas, and documented
standardized two-window chip policy. Era-authentic chip inventory is not being
reintroduced here as an accidental-regression finding.

## 9. Existing Validation Commands

Run from the repository root in an activated supported Python environment with
the existing project dependencies. The review's temporary environment was
removed; do not assume it remains available. Do not install new test tools just
to execute these commands.

```powershell
python -m pytest -v tests\test_historical_gui_api.py tests\test_historical_simulation.py
python -m pytest -v tests\test_gui.py tests\test_planner.py tests\test_decision_log.py tests\test_transfers.py
python -m pytest -v tests\test_chip_optimizer.py tests\test_chip_parity_and_regression.py tests\test_chip_strategy.py
python -m pytest -v tests\test_strategic_squad_gui.py tests\test_strategic_squad_engine.py tests\test_suggest_transfers.py
python -m pytest -v tests\test_benchmark_provenance.py
python -m pytest -v tests\test_gui_context.py tests\test_historical_session_integrity.py
python -m pytest
python -m compileall -q src tests scripts
node --check .\src\fpl_manager\gui\static\app.js
node --test .\tests\test_gui_context.js
python .\scripts\verify_v146_human_benchmark.py
git --no-pager diff --check origin/master...HEAD
```

These suites cover the automated regression cases. They do not establish
unperformed browser checks or retroactively validate the original replay pipeline.

## 10. Binary Merge Checklist

- [x] All four P1 items are fixed and have demonstrated acceptance evidence.
- [x] Every P2 item is resolved or has an explicit reviewed disposition.
- [x] Live Apply succeeds and every failed compound action rolls back completely.
- [x] Late responses and stale actions cannot write to another context or GW.
- [x] Bank, purchase basis, ownership, FT/hits and audit data reconcile after all flows.
- [x] Free Hit cancellation, expiry, subsequent activation and Undo are coherent.
- [x] Planner scoring/ranking matches chip, hit, GW1 and risk-profile execution rules.
- [x] Chip schedules contain only feasible, strategy-permitted deployments.
- [x] Frozen baseline configuration survives load/restart/environment changes unchanged.
- [ ] Supported Python CI jobs and the full local candidate suite pass (pending full integration).
- [ ] Real-browser context/control checks (HTTP-level tests executed; real-browser smoke NOT performed).
- [x] Published benchmark tables agree with semantically validated provenance.
- [x] Documentation and closure statuses reference the actual merge candidate.

**Completion rule:** The known code issues have automated acceptance coverage.
Commit-specific CI and manual browser verification remain separate evidence;
do not mark a manual check complete without executing it.
