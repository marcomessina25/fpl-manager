# V1.4.6 Items Left - PR Review Remediation and Release Gates

**Status:** Open; request changes before merge.
**Review date:** 2026-10-28.
**Branch / target:** `v146` -> `master`.
**Pull request:** [#22](https://github.com/marcomessina25/fpl-manager/pull/22).
**Reviewed head:** `eb5370a225f299fc4b59f3a1491da7577be259b2`.
**Reviewed base:** `e654283cb39a24ce920d9789668c039fce8a01cf`.
**Scope:** 33 changed files, 5,481 additions, 897 deletions.

This is the remediation backlog from the PR review, not a record of completed
fixes. All work below remains pending. References identify the reviewed head;
reconfirm line numbers after implementation changes.

## 1. Review Evidence and Boundaries

| Evidence | Observed result |
|---|---|
| Full Python suite, local Python 3.13 | 506 collected; 495 passed; 11 failed |
| PR CI, Python 3.13 | Same 11 failures and 495 passes |
| PR CI, Python 3.11 and 3.12 | Cancelled by matrix fail-fast, not passed |
| Historical GUI API and simulation suites | Passed, but did not detect the stateful defects below |
| JavaScript syntax check | Passed; syntax validity did not catch runtime and DOM defects |
| Targeted reproductions | In-memory Python and Node executions with mocked boundaries |
| Real-browser end-to-end coverage | Not executed during this review |
| Human benchmark provenance | Not verifiable from the tracked summary alone |

CI evidence: [workflow run 40714639452](https://github.com/marcomessina25/fpl-manager/actions/runs/40714639452).

The published "full automated test suite 39/39" statement describes a selected
subset, not the actual full-suite result. Passing endpoint/schema assertions do
not prove correct optimization, isolation, financial accounting, or replay.

The findings are functional correctness and release-evidence issues, not a
dedicated security audit. Synthetic reproduction scores illustrate defects;
they are not historical benchmark results. Proposed regression cases below are
requirements for future tests, not claims that those tests already exist.

## 2. Invariants to Preserve

- Keep the strict live/historical capability and visual parity requirements in
  [`GEMINI.md`](../../GEMINI.md), including real solvers rather than manual or
  roll-only substitutes.
- Historical operations must target the active `session_id`. Missing or stale
  historical context must never become an implicit live operation.
- Historical predictions must use knowledge available at `current_gw`. Known
  future fixtures and genuine forward projections are allowed; later player
  outcomes and later-deadline feature snapshots are not.
- Retain legal transfer solving for 1-5 transfers, 1-10 GW evaluation horizons,
  risk profiles, and the exposed engine choices.
- Keep manual transfer controls exclusively in Decision Logger.
- Preserve max-three-per-club pruning, correct GW2 free-transfer initialization,
  hit-adjusted transfer metrics, and useful shared-interface improvements.
- Squad, XI, ordered bench, captain, bank, purchase prices, transfers, chips, and
  logged decisions must describe the same state before and after every action.
- Shared state-management fixes must preserve supported live behavior rather
  than repairing historical mode by breaking the live path.

## 3. Priority Register

All source references below are relative to `src\fpl_manager\`.

| ID | Priority | Outstanding work |
|---|---|---|
| V146-01 | P1 | Restore Decision Logger submission |
| V146-02 | P1 | Fix single-GW transfer rescoring |
| V146-03 | P1 | Prevent historical Undo falling back to live |
| V146-04 | P1 | Reject stale planner actions across contexts |
| V146-05 | P1 | Remove future-outcome reads from historical plans |
| V146-06 | P1 | Restore coherent human state on Undo |
| V146-07 | P1 | Restore the complete baseline on Undo |
| V146-08 | P2 | Implement genuine historical beam-search planning |
| V146-09 | P2 | Apply the actual planner step-0 lineup atomically |
| V146-10 | P2 | Validate logger chips and synchronize logged instructions |
| V146-11 | P2 | Stage transfer bundles atomically |
| V146-12 | P2 | Avoid double-counting committed transfer costs |
| V146-13 | P2 | Resolve mixed committed/pending transfer chains correctly |
| V146-14 | P2 | Synchronize transfers using the correct live team |
| V146-15 | P2 | Isolate Strategic Studio candidates and constraints |
| V146-16 | P2 | Rehydrate Decision Logger when context changes |
| V146-17 | P2 | Give blank GWs zero fixture-aware xP |
| V146-18 | P2 | Replace hardcoded chip-roadmap valuations |
| V146-19 | P2 | Preserve explicit C0 selection against environment defaults |
| V146-20 | P2 | Migrate persisted transfer-hit units safely |
| V146-21 | P2 | Restore logged-lineup banner and comparison controls |
| V146-22 | Release gate | Repair and rerun the complete regression suite |
| V146-23 | Evidence gate | Make benchmark claims auditable or provisional |
| V146-24 | Policy clarification | Document the historical replay ruleset |
| V146-25 | Release gate | Reconcile documentation and publish final evidence |

P1 findings block merge. P2 findings are also unresolved release work; they are
not automatically accepted merely because the P1 items are fixed.

## 4. P1 Merge Blockers

### V146-01 - Decision Logger cannot submit in either mode

**Reference:** `gui\static\app.js:1614-1630`.

The save handler references undeclared `actual_points` after its declaration was
removed in this PR. Every submission raises `ReferenceError` before the POST.

- [ ] Restore parsing of the actual-points input before constructing the payload.
- [ ] Preserve the existing valid-input contract; do not introduce arbitrary
  score caps, prohibit legitimate negative scores, or silently coerce invalid input.
- [ ] Add runtime coverage for empty, zero, valid numeric, and invalid input.
- [ ] Verify a successful POST and read-back in live and historical modes,
  including notes, captaincy, and the intended actual-points semantics.
- [ ] Verify failed requests produce visible errors without claiming a save.

**Acceptance:** Both save paths send valid payloads and persist the intended
decision. A syntax-only check is not sufficient.

### V146-02 - Single-GW transfer rescoring crashes

**Reference:** `suggest_transfers.py:253`.

`single_delta` is assigned only when `eff_horizon > 1` but read for every
complete 15-player squad. A one-GW effective horizon crashes; `v1.2` always takes
that path. `v1.2.5` and `v1.3.5` are affected when their effective horizon is one.
Five existing `test_suggest_transfers.py` tests reproduce the failure.

- [ ] Define the correct immediate-GW delta on the one-GW path.
- [ ] Preserve gross horizon delta, GW1 delta, hit-adjusted net delta, and reason
  metadata without double-deducting hits.
- [ ] Cover one-GW and multi-GW evaluation for the applicable engine choices,
  both modes, hit/no-hit candidates, and goalkeeper hurdle behavior.
- [ ] Restore the five existing failing transfer tests.

**Acceptance:** Horizon-one candidates return correct values without exceptions,
and multi-GW behavior remains unchanged except for deliberate, documented fixes.

### V146-03 - Historical Undo can mutate the live team

**Reference:** `gui\static\app.js:2632-2647`;
backend route `POST /api/decisions/undo`.

With historical mode selected but no simulation, Undo sends `session_id: null`.
The backend's live fallback targets the active live team.

- [ ] Disable or reject historical Undo when no active session is selected.
- [ ] Make operation context explicit enough that malformed historical requests
  cannot enter the live fallback, while preserving valid live requests.
- [ ] Reject invalid or deleted historical sessions without any live mutation.
- [ ] Test absent, null, invalid, deleted, valid, and changed session context.
- [ ] Assert live squad files and decision rows are unchanged by every
  historical success and failure case.

**Acceptance:** No historical Undo path can operate on a live team.

### V146-04 - Cached planner actions target the wrong mode or session

**Reference:** `gui\static\app.js:2477-2504`;
context transitions at `128-168` and `4493-4500`.

A live-generated plan retains a captured live-mode branch after switching to
historical mode, so Apply still executes live transfers. A historical plan uses
the current global session ID, so a plan generated for A can be sent to B.

- [ ] Associate results with their source mode, team, season, session, and GW.
- [ ] Invalidate or restore context-specific results on context changes.
- [ ] Refuse Apply unless result provenance still matches the active context.
- [ ] Discard late asynchronous responses from superseded requests.
- [ ] Cover both mode-switch directions, live team changes, historical session
  changes, GW advancement, and context changes while requests are in flight.

**Acceptance:** Applying a stale result is rejected with a visible explanation
and no mutation to either its old context or the newly selected context.

### V146-05 - Historical planning reads future information

**Reference:** `gui\server.py:663-665`.

A GW5 plan builds historical snapshots for GW6/GW7 and reconstructs projections
from them, thereby using outcomes unavailable at GW5.

- [ ] Anchor player features and availability knowledge to the current snapshot.
- [ ] Produce future projections from that frozen knowledge and known fixtures,
  not later historical feature snapshots.
- [ ] Spy on outcome/feature reads and assert no later-deadline data is loaded.
- [ ] Change later outcomes while holding currently known fixtures fixed; the
  present plan, captain, rankings, and xP must remain unchanged.
- [ ] Retain legitimate sensitivity to changes in the known fixture schedule.

**Acceptance:** Present recommendations are independent of future outcomes.
Do not implement this by suppressing valid forward-looking fixture analysis.

### V146-06 - Undo restores an unowned incoming player in the lineup

**Reference:** `simulation\session.py:1055-1062`.

Staging substitutes incoming lineup/captain IDs before resolution, but the
pre-resolution ownership snapshot still contains outgoing players. Undo clears
staging and restores this inconsistent combination. Rerunning can score the
incoming player without owning them or paying for their transfer.

- [ ] Capture and restore a coherent state boundary across ownership, XI,
  ordered bench, captain/vice, bank, purchase prices, FT, chips, and staging.
- [ ] Explicitly document whether Undo preserves staged decisions or reverses
  them. Either behavior must leave ownership and accounting consistent.
- [ ] Undo the reversed GW's chip effects consistently; do not retain consumption
  from a GW that has been undone.
- [ ] Test stage -> run -> undo -> rerun, including incoming captains, bench
  changes, Studio-applied squads, save/load, and repeated use.
- [ ] Assert all starters/bench players are owned and all costs/hits occur once.

**Acceptance:** Undo never enables an unowned player to score; replaying the
same valid decisions produces the same financial and scoring outcome.

### V146-07 - Undo leaves the frozen baseline advanced

**Reference:** `simulation\session.py:1414-1416`.

Undo removes the baseline history entry without restoring its squad, prices,
bank, FT, or chips. A deterministic GW5 reproduction changed baseline scoring
from 68 to 60 points after Undo and replay; these are scores, not GW numbers.

- [ ] Persist and restore the complete baseline pre-GW state alongside the human
  state, including chip effects and all transfer accounting.
- [ ] Keep baseline state and baseline history at the same replay boundary.
- [ ] Test transfers and Bench Boost, Undo/replay, repeated cycles, and save/load.
- [ ] Define safe handling for legacy saves lacking a complete baseline snapshot;
  do not silently claim reproducible comparison when reconstruction is impossible.

**Acceptance:** Identical inputs and outcomes produce identical baseline results
before and after Undo, with correct bank, squad, FT, and chip inventories.

## 5. P2 Functional and Parity Work

### V146-08 - Historical planner is a roll-only substitute, not beam search

**Reference:** `gui\server.py:618-703`; shared planner `planner.py`.

The branch uses one immediate recommendation followed by hardcoded `ROLL`
steps. Risk/no-hit controls are not passed into planning, future scores use the
top 11 without formation constraints, and bank/FT trajectories are not properly
derived from the planned state.

- [ ] Adapt the real shared beam-search engine to historical point-in-time data.
- [ ] Propagate squad, prices, bank, FT, staging, and chip effects at every step.
- [ ] Honor risk and no-hit controls and produce legal XI/captain selections.
- [ ] Resolve the mandate's 1-8 GW range across UI/API/engine. The existing live
  planner validates 1-6; do not claim eight-GW support without implementing it.
- [ ] Test a multi-step opportunity that beats forced rolling, no-hit restrictions,
  risk behavior, horizons 1-8, and season-end truncation.

**Acceptance:** Both modes perform genuine trajectory optimization with the same
capabilities, preserving the response contract and V146-05's information boundary.

### V146-09 - Historical planner Apply sends an empty XI

**Reference:** `gui\static\app.js:2489-2504`.

The handler filters on nonexistent `p.role` fields instead of historical
`is_starter`/`is_bench` flags, submitting zero starters and 15 bench players.
Transfers can be staged before lineup validation fails.

- [ ] Apply the recommended step-0 XI, ordered bench, captain, and vice-captain,
  rather than merely copying the current lineup.
- [ ] Use the correct historical contract and validate the resulting owned squad.
- [ ] Validate the whole operation before mutation or roll back all changes.
- [ ] Test roll-only and multi-transfer steps, exact 11/4 membership, captaincy,
  and a forced lineup failure leaving no partial staging.

**Acceptance:** Successful Apply matches step 0 exactly; failed Apply is atomic.

### V146-10 - Logger chip and lineup instructions bypass session rules

**Reference:** `gui\server.py:1399-1410`;
`gui\static\app.js:1635-1639, 5145-5146`.

Direct `sim.active_chip` assignment bypasses normalization and availability
checks. Logger alias `freehit` can waive hits without the canonical Free Hit
snapshot/reversion, and `benchboost` can score without consuming `bench_boost`.
Consumed chips can be reused through direct assignment. Canonical chip names
also fail to match logger select options and may be cleared on save.

The frontend additionally builds malformed lineup arrays from `p.role`, while
the backend does not apply posted XI/bench instructions to actual session state.
The save crash currently blocks the UI path, but direct API requests are reachable.

- [ ] Normalize aliases through shared chip helpers and validated session methods.
- [ ] Distinguish omitted chip instructions, explicit cancellation, and activation.
- [ ] Reconcile logged XI/bench/captain instructions through session validation.
- [ ] Test all exposed aliases, consumed chips, cancellation, omission, Free Hit
  restoration, Bench Boost consumption, and audit/execution lineup agreement.

**Acceptance:** Logger decisions obey the same chip and lineup rules as other
controls, and persisted audit data matches the state that is actually resolved.

### V146-11 - Multi-transfer execution is order-dependent

**Reference:** `gui\server.py:1302-1306`.

The execution route calls `stage_transfer()` per item. With zero bank, an upgrade
costing 10 tenths followed by a downgrade releasing 10 tenths is rejected even
though the final bundle is affordable.

- [ ] Reuse `stage_transfers_batch()` and final-state budget/quota validation.
- [ ] Preserve existing staging semantics and idempotency deliberately.
- [ ] Test both bundle orders, quota-repair moves, and an invalid later item.
- [ ] Assert failures leave no partial staged transfer, lineup, or bank changes.

**Acceptance:** Legal final bundles succeed regardless of item order; illegal
bundles fail atomically with a visible validation error.

### V146-12 - Recommendation bank double-counts committed transfers

**Reference:** `gui\server.py:274-282`.

Studio-applied transfers already change ownership/bank and carry
`already_applied=True`. The recommendation branch subtracts their costs again.
A bank of 20 tenths becomes -10 when a committed 30-tenths cost is counted twice.

- [ ] Distinguish pending from committed transfers when deriving effective state.
- [ ] Verify ownership is not duplicated and purchase prices remain correct.
- [ ] Test Studio apply -> recommendations, pending-only staging, and mixed state.
- [ ] Assert displayed bank, solver bank, FT, hits, and eventual execution agree.

**Acceptance:** Every transfer cost affects effective finances exactly once.

### V146-13 - Mixed committed/pending chains corrupt squad and bank

**Reference:** `simulation\session.py:1079-1100`.

Reachable flow: Studio applies A(50) -> B(60), reducing bank from 50 to 40;
manual staging then requests B -> C(80). Collapse reconstructs an unapplied
A -> C costing 30 although A is no longer owned. Reproduction leaves B owned,
scores C, and ends with bank 10 instead of 20.

- [ ] Resolve applied and pending accounting without reconstructing a financial
  transaction whose outgoing player has already been sold.
- [ ] Keep final ownership, lineup, purchase prices, and transfer audit consistent.
- [ ] Reproduce using actual `stage_transfer()` and `run_gameweek()` behavior.
- [ ] Assert C is owned, B is removed, and bank is 20 for the stated example.
- [ ] Document existing chained-transfer FT/hit semantics separately; do not
  silently introduce an unrelated charging-policy change.

**Acceptance:** Mixed chains cannot overcharge or score an unowned player.

### V146-14 - Transfer synchronization queries the default team's history

**Reference:** `suggest_transfers.py:314`.

The new synchronization call omits `team_id`, so a stale non-default squad can
read the default team's FT history and persist the wrong transfer balance.

- [ ] Derive/pass the actual team and configuration context using existing helpers.
- [ ] Test two teams with deliberately different decision histories and FT.
- [ ] Cover direct API and CLI/service callers, not only GUI startup.
- [ ] Assert only the selected team's state changes and hit costs use its own FT.

**Acceptance:** No team's synchronization depends on another team's decisions.

### V146-15 - Studio retains candidates from another player universe

**Reference:** `gui\static\app.js:3782-3785, 4331-4352`.

Reloading configuration replaces the player pool but retains candidates, previous
candidate, locks, and exclusions. Apply combines old-universe IDs with the current
destination. A wrong-context payload was reproduced; this does not establish
that every malformed roster is accepted.

- [ ] Scope or invalidate candidate/constraint state by full source context.
- [ ] Reject stale asynchronous results and stale Apply actions.
- [ ] Validate candidate provenance and legality against the destination session,
  season, current GW, and budget at the backend boundary.
- [ ] Test mode, live team, season, historical session, and GW transitions.

**Acceptance:** No candidate or constraint silently changes meaning when its
player universe changes.

### V146-16 - Shared Decision Logger retains the previous context

**Reference:** `gui\static\app.js:163-168, 1790-1795, 4493-4500`.

Mode/session changes leave old decision history visible. Returning live can leave
historical options in the manual-transfer datalist because a populated live cache
causes an early return without rebuilding the DOM.

- [ ] Immediately clear or reload decision history and executed-transfer displays.
- [ ] Rebuild the picker from the active pool even when no network fetch is needed.
- [ ] Scope caches and reject late responses from previous contexts.
- [ ] Test both mode directions, two historical sessions, no selected session,
  and correct resolution of the displayed incoming-player options.

**Acceptance:** Displayed decisions, executed trades, and picker options always
belong to the active context; historical loading does not query live decision data.

### V146-17 - Blank GWs incorrectly receive average xP

**Reference:** `strategic_squad.py:411-415`.

Missing GW keys fall back to average xP. For players with fixtures only in GW1
and GW3, reproduction gives 60 lineup xP in blank GW2: breakdown sum 180 versus
the stated horizon total 120.

- [ ] Represent explicit blanks as zero, distinguishing them from unavailable data.
- [ ] Check shared projection producers and consumers, including historical
  transfer rescoring, for the same missing-key interpretation.
- [ ] Cover blank, double, normal, mixed, and genuinely missing projections.
- [ ] Assert GW breakdowns reconcile with aggregate xP within rounding tolerance.

**Acceptance:** Blank fixtures cannot create invented points or inconsistent totals.

### V146-18 - Chip roadmap presents hardcoded values as optimizer output

**Reference:** `gui\server.py:1096-1200`.

Future entries use fixed EVs, confidence `0.88`, and preferred wildcard windows
GW8/GW29 instead of computed opportunity-cost valuations. Two different squads
with no immediate chip recommendation produced identical schedules.

- [ ] Generate the full segment roadmap through the canonical optimizer using
  current point-in-time state and known future fixtures.
- [ ] Derive EV, future opportunity, utility, and confidence from actual supported
  calculations; do not fabricate optimizer-shaped metadata.
- [ ] Cover GW1-19/GW20-38, available/used chips, end-of-window pressure,
  meaningful squad changes, and conflict-free scheduling.
- [ ] Compare live/historical outputs for equivalent inputs, not merely key names.
- [ ] Test actual optimizer guardrails. Do not incorrectly prohibit Bench Boost
  immediately after Wildcard; the cited cooldown concerns Free Hit/Wildcard.

**Acceptance:** Recommendations and valuation metadata have genuine optimizer
provenance; a legitimate lack of a recommendation is explained rather than faked.

### V146-19 - Environment flag overrides explicit C0 selection

**Reference:** `chip_strategy.py:868-871`.

`FPL_CHIP_OPTIMIZER=1` overrides explicit `use_optimizer=False`, allowing a C0
ablation to delegate silently to C1.

- [ ] Preserve explicit policy/variant selection over environment defaults.
- [ ] Test unset, `0`, and `1` environment values with explicit C0/C1 selection.
- [ ] Record the actual policy in benchmark configuration/manifests.

**Acceptance:** Explicit C0 remains C0 regardless of a process-wide default.

### V146-20 - Persisted transfer-hit units change without migration

**Reference:** `simulation\session.py:1266-1270, 1703`.

Old `transfer_hits` values represent penalty points; new values represent the
number of charged transfers. Mixing one old entry of 4 and one new entry of 1
produces an exported penalty of 20 rather than the correct 8 points.

- [ ] Version/migrate old history or expose unambiguous count and penalty fields.
- [ ] Reconcile JSON, API, GUI, summaries, and exported reports consistently.
- [ ] Cover old-only, new-only, mixed, zero-hit, save/load, and Undo histories.
- [ ] Assert gross minus net equals the actual point penalty, including the
  two-entry example's 8-point total.

**Acceptance:** Existing saved sessions retain correct totals after upgrade.

### V146-21 - Logged-lineup banner remains permanently hidden

**Reference:** `gui\static\index.html:289-298`.

New inline `display: none` is not reversed when the renderer removes `hidden`,
concealing the logged-state summary and model/actual-lineup comparison controls.

- [ ] Use a consistent visibility mechanism across logged and model branches.
- [ ] Verify both toggle directions and expected lineup/captain/points state.
- [ ] Check actual computed visibility in a browser, not class changes alone.

**Acceptance:** Logged-state information and comparison controls are visible and usable.

## 6. Regression, Benchmark, and Release Evidence

### V146-22 - Restore the full suite without weakening the new invariants

The 11 observed failures fall into three groups:

| Group | Existing failing coverage | Required treatment |
|---|---|---|
| 5 one-GW crashes | `test_suggest_transfers.py`: 1/2/3/4 moves and risk profiles | Fix V146-02; retain behavioral assertions |
| 4 invalid-quota fixtures | One departed-player test in `test_v115_hardening.py`; three optimizer integration tests in `test_v12_unavailability.py` | Make fixtures club-legal while retaining their intended offload/filtering discrimination |
| 2 baseline drift assertions | `test_v125_transfer_refinements.py`: `test_track_a_unaffected_by_chip_bench_weighting`, `test_registry_removal_does_not_change_benchmark` | Investigate why 2023-24 Track A changed from 2,193 to 2,265 |

- [ ] Repair fixtures rather than weakening max-three-per-club validation.
- [ ] Attribute baseline drift to specific code/rules/configuration changes.
- [ ] Do not simply replace golden values with current outputs. Establish and
  document an intentional baseline version if a rebaseline is justified.
- [ ] Add behavioral regression coverage for all confirmed findings, especially
  context changes and Apply -> resolve -> Undo -> replay.
- [ ] Rerun the complete suite on Python 3.11, 3.12, and 3.13.
- [ ] Record actual pass/failure/skip counts and code SHA; newly added tests mean
  the eventual suite need not contain exactly 506 tests.
- [ ] Capture browser evidence for the shared controls and state transitions.

**Acceptance:** All supported-version jobs pass without new failures, unexpected
skips, hidden fallbacks, or cancelled jobs being counted as successes.

### V146-23 - Make the human benchmark auditable or mark it provisional

The tracked V1.4.6 report is a summary table. The reviewed diff does not supply
the replay traces, manifests, or aggregation command needed to verify the
claimed +63.6 points per season and 4/5 season win rate. This is an evidence gap,
not an allegation that the numbers were fabricated.

- [ ] First resolve future leakage, scoring/accounting errors, baseline Undo,
  migration, explicit policy selection, and relevant baseline drift.
- [ ] Supply sanitized decision traces or an accessible, versioned artifact
  archive with checksums. Do not commit private user sessions or credentials.
- [ ] Provide the exact runner/aggregation command and code/data/configuration
  versions, predictor and chip-policy identifiers, ruleset, and seeds if used.
- [ ] Record identical initial squads, bank, prices, FT, chips, and information
  boundaries for the compared tracks.
- [ ] Reconcile gross points, hit penalties, net points, and per-GW divergence for
  38 matched GWs in each of the five seasons.
- [ ] Explain participant/trial selection and how overrides were recorded; use
  anonymous experiment identifiers rather than personal session details.
- [ ] Generate the leaderboard from source traces, not manually copied totals.
- [ ] Supply the planned decision/override analysis and visuals, or explicitly
  identify unimplemented deliverables and any Track C exclusion.
- [ ] State the limitations of five season-level comparisons; avoid describing
  the reported mean/win rate as proof of general statistical synergy.
- [ ] If evidence is unavailable, clearly mark results provisional or remove
  unsupported release claims across the report, PR, and release notes.

**Acceptance:** A reviewer can independently regenerate the reported numbers,
or all published material accurately identifies the evidence as provisional.

### V146-24 - Clarify the historical replay ruleset

**Classification:** Open policy/documentation question, not a confirmed
introduced defect.

Base specifications and chip policies already describe two chip windows, and
new tests intentionally apply the GW20 reset to a 2023-24 replay. Consequently,
the blanket reset was not retained as an accidental PR-regression finding.

- [ ] Explicitly state whether older seasons replay under current competition
  rules or their era-authentic chip/FT/scoring rules.
- [ ] Preserve existing intended behavior until an explicit policy decision.
- [ ] Document the chosen ruleset in replay/benchmark metadata and specifications.
- [ ] If era-authentic behavior is approved, scope and test it separately;
  recompute affected benchmarks rather than silently mixing rulesets.

**Acceptance:** Readers can distinguish historical data from the rules applied
to that data. Live/historical interface parity does not itself settle this policy.

### V146-25 - Reconcile release documentation and final evidence

- [ ] Update [`RELEASE_NOTES_v1.4.6.md`](../RELEASE_NOTES_v1.4.6.md) with the actual
  full-suite status and the distinction between subset and full-suite evidence.
- [ ] Reconcile [`README.md`](../../README.md), [`roadmap.md`](../roadmap.md),
  [`v146_human_benchmark.md`](v146_human_benchmark.md), the PR description, and
  [`human_benchmark_report.md`](../../reports/v146/human_benchmark_report.md).
- [ ] Resolve the specification's "Planned" status against what actually ships.
- [ ] Remove unconditional parity/verification claims until behavioral evidence
  supports them; preserve explicit limitations where work is deferred.
- [ ] Attach the final reviewed SHA, CI run, reproduction/test references,
  browser results, and benchmark provenance to the release handoff.
- [ ] Mark an item complete only after its implementation and acceptance evidence
  are linked; documentation of a defect is not its resolution.

## 7. Execution Order and Dependencies

Independent fixes need not wait for unrelated items. In particular, stale
planner context does not depend on logger parsing, and bank accounting does not
depend on removing future reads.

| Workstream | Suggested order / actual integration prerequisites |
|---|---|
| Immediate runtime fixes | V146-01 and V146-02 can proceed independently |
| Context isolation | V146-03/04/15/16 share a context-lifecycle design; each mutation still needs its own guard |
| Historical planning | V146-05 and V146-08 must be integrated before accepting the optimized roadmap; V146-09 verifies the real step-0 payload |
| Financial correctness | V146-11/12/13 can be investigated independently, then tested together through Studio/manual/solver flows |
| Undo/replay | V146-06/07/20 need a compatible persistence/migration design and combined replay tests |
| Logger instructions | V146-10 API fixes are independent; its UI acceptance requires V146-01 |
| Projection/chip correctness | V146-17/18/19 can proceed independently; V146-18 must preserve point-in-time boundaries |
| Release proof | V146-22 uses all fixes; audited V146-23 results require the relevant state/scoring/information fixes and an identified ruleset |
| Final handoff | V146-25 incorporates final tests, policy clarification, and benchmark evidence or explicit provisional status |

Any Undo preserve-vs-revert behavior or historical ruleset change requires an
explicit decision. Do not substitute arbitrary time-to-live limits, score caps,
silent fallbacks, or unreviewed rule changes for the underlying fixes.

## 8. Cross-Mode Verification Matrix

These are required coverage targets, not already executed tests.

| Surface | Live coverage | Historical coverage | Stateful / failure cases |
|---|---|---|---|
| Decision Logger | Save/read-back, actual scores, manual trades | Session-only decisions, correct pool, chip/lineup instructions | Both mode directions, no session, stale response, failed POST |
| Transfers | Correct selected team FT; 1-5 moves; 1-10 GW controls | Same engines/controls, effective staged state | Net-affordable bundles, quota repair, failed later item, committed/pending mix |
| Planner | Real shared search and supported horizon range | Real point-in-time search and exact step-0 Apply | Context switches, legal formations, no-hit/risk behavior, atomic failures |
| Undo | Existing live behavior preserved | Human and baseline state restored | Staged incoming captain, chips, repeat replay, legacy save/load |
| Strategic Studio | Candidate/constraint state tied to live team | Historical season/session-bound candidates | Pool changes, stale candidates, apply then manual trade |
| Chip roadmap | Canonical optimizer and explicit policy | Same capabilities, whole active segment | Used chips, aliases, cancellation, end-window, real EV metadata |
| Projections | Blank/double GW and horizon consistency | Same contracts without future outcomes | Future-outcome perturbation, explicit blank vs missing data |
| Pitch / visibility | Logged/model banner and toggles | Matching usable controls | Actual computed display, lineup and captain synchronization |
| Reports / benchmark | Consistent units and selected configuration | Reproducible human/baseline comparisons | Old/new/mixed hit histories, repeat Undo, trace-derived totals |

Include GW1/GW2, GW19/GW20, GW38/completed seasons, insufficient bank, excess club
quota, and no selected simulation where relevant. Check isolation by asserting
unrelated session files and live database/team state remain unchanged.

## 9. Validation Commands

Run from the repository root with an activated, supported Python environment
and the existing project test dependencies. Do not assume the review's temporary
environment still exists. Do not install new test tools merely to run this list.

Existing focused suites:

```powershell
python -m pytest -v tests\test_historical_gui_api.py tests\test_historical_simulation.py tests\test_chip_parity_and_regression.py
python -m pytest -v tests\test_suggest_transfers.py tests\test_optimizer.py tests\test_v125_live_wiring.py tests\test_rules.py
python -m pytest -v tests\test_decision_log.py tests\test_teams.py tests\test_planner.py
python -m pytest -v tests\test_strategic_squad_gui.py tests\test_strategic_squad_engine.py tests\test_expected_points.py
python -m pytest -v tests\test_v115_hardening.py tests\test_v12_unavailability.py tests\test_v125_transfer_refinements.py
```

Final full-suite and static checks:

```powershell
python -m pytest -v
python -m compileall -q src tests
node --check .\src\fpl_manager\gui\static\app.js
git --no-pager diff --check
```

Use the existing test modules and add focused behavioral coverage as needed.
The command list deliberately does not reference hypothetical test files or
assert that Node syntax checking replaces UI runtime/browser coverage.

## 10. Binary Merge Checklist

- [ ] V146-01 through V146-07 are fixed with behavioral regression evidence.
- [ ] Every P2 item is resolved, or an explicit reviewed disposition describes
  its remaining impact; no known issue is silently treated as completed.
- [ ] Historical actions cannot read/mutate live state or target another session.
- [ ] Present projections/plans are independent of later outcomes.
- [ ] Planner search and step-0 Apply meet the shared capability contract.
- [ ] Financial state, chip consumption, and hit units reconcile across all paths.
- [ ] Human and baseline Undo/replay are deterministic, including persistence.
- [ ] All supported Python CI jobs pass; cancelled jobs do not count as passes.
- [ ] Browser validation confirms visible, usable controls and context isolation.
- [ ] Baseline drift is explained and any approved rebaseline is versioned.
- [ ] Benchmark claims are reproducible, or clearly provisional everywhere.
- [ ] Replay rules and release/specification statuses are unambiguous.
- [ ] Final evidence references the actual merge candidate, not an earlier SHA.

**Completion rule:** Check off work only when its required outcome has been
verified and persists correctly. This backlog alone does not establish merge readiness.
