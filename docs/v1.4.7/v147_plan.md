# V1.4.7 Delivery Plan

**Status:** V147-01 through V147-09 core implementation complete on branch; V147-10 (Qt) explicitly gated.
**Branch:** `v147`, based on merged `master` at `38595a7`.
**Date:** 2026-10-29.
**Status Update:** 2026-10-30 — V147-02 through V147-07 implemented; V147-08 application foundation extracted with legacy HTTP orchestration retained; V147-09 automated gates in place. All 961 local tests pass with no skips or failures, including the GUI-controller wrapper. V147-10 (Qt) remains explicitly gated.
**Inputs:** [Repository assessment](repository_analysis.md), [native PyQt6 plan](pyqt6_migration_plan.md).

## 1. Release Goal

Make the application a trustworthy decision-support product with clear state and
calculation boundaries. Prepare a native GUI without repeating V1.4.6's pattern
of adding many workflows before their shared invariants are established.

The branch implements the correctness and application-foundation packages below.
The native client remains a separately gated proposal. In particular:

- No PyQt6 GUI, Qt dependency group or desktop package is introduced now.
- LLM provider/model choices remain in the live-only AI workspace.
- Historical already correctly hides Live Matchday and AI Advisor & Briefing;
  that behavior is preserved, not reimplemented.
- Historical should resemble Live through shared layouts and controls for the
  eight common workflows, not by exposing live-only features.
- Saved frozen baselines and published research records keep their provenance.
- The package version is `1.4.7` for candidate verification; this is not a
  declaration of native-client cutover or final release approval.

## 2. Scope Already Implemented on This Branch

- [x] Create and push `v147` from merged `master`.
- [x] Remove decision-engine selectors from Transfers, Strategic Studio and
  simulation creation.
- [x] Delegate GUI engine selection to the explicit central `"default"` policy.
- [x] Keep explicit legacy API/research versions and the legacy no-argument
  resolver contract compatible.
- [x] Remove inaccurate hardcoded version text from historical recommendations.
- [x] Preserve LLM controls and correct Historical tab restrictions.
- [x] Add controller/API regressions for defaults, overrides and exclusions.
- [x] Add the new branch to push CI.
- [x] Document the architecture assessment and future native migration.

Validation of this scoped branch change: **655 pytest cases passed** locally
on Python 3.13 during preparatory cleanup phase (28adb72).

**Final local full suite:** 961 tests passed on Windows/Python 3.13, with zero
failures, errors or skips. This includes the required historical GUI/API and
simulation regressions, recovery/concurrency tests, and frozen benchmark assertions.

**Focused last review suite:** 105 tests passed.

**Node controller cases:** 42 actual-handler cases, including calculation-revision
and archive-control regressions. Nested Python report exports have separate
pytest regressions; Node tests are not real-browser or visual acceptance.

**Installed artifact:** the built `1.4.7` wheel passed resource, isolated command
and CLI smoke checks outside the source checkout. CI runs Linux/Python
3.11/3.12/3.13 and Windows/Python 3.13 against the pushed candidate and repeats
the installed-wheel checks. Remote acceptance is the candidate commit's
[CI checks](https://github.com/marcomessina25/fpl-manager/actions/workflows/ci.yml?query=branch%3Av147);
local results do not stand in for remote or manual visual acceptance.

## 3. Delivery Principles

1. Establish failing behavioral tests before changing a rule or state transition.
2. Keep rules, accounting and model identity outside GUI controllers.
3. Use explicit mode/entity/season/GW/revision contexts, never a nullable
   historical identifier interpreted as a live fallback.
4. Preserve full solver capabilities and historical information boundaries.
5. Keep read queries non-mutating; advance gameweeks through explicit commands.
6. Publish failed/partial recovery explicitly; do not clamp invalid state into
   apparent success or substitute another predictor silently.
7. Prefer small vertical PRs with measurable acceptance evidence.
8. Use ownership-safe parallel work. No worker may revert another worker's
   changes or use destructive Git cleanup to restrict its own scope.
9. Keep past benchmark records separate from corrected new execution.
10. Distinguish source-level validation, automated GUI tests and manual visual
    acceptance. A large passing test count is not a substitute for any of them.

## 4. Work Packages

Effort ranges below are rough human person-days including focused tests/review.
They are not independent additive bids: common service and transaction work
overlaps several fixes. Re-estimate after the first validated vertical slice.

### V147-01 - Product-facing defaults and interface simplification

**Status:** ✅ Implemented and validated on this branch.
**Scope:** Latest decision engine for new GUI work; no version menus or invented
hardcoded baseline labels. Decision-engine version menus removed from Transfers,
Strategic Studio, and simulation creation.

Acceptance criteria — all passing:
- [x] Actual transfer handlers omit client-side engine overrides in both modes.
- [x] New simulation requests preserve season/GW/name settings while using the
  backend's current default policy.
- [x] Explicit legacy research requests and stored baseline versions remain intact.
- [x] AI provider/model controls remain operational and live-only.
- [x] Switching from live-only tabs to Historical returns to an allowed workspace.
- [x] 655 pytest cases pass locally on Python 3.13.
- [x] 42 actual-handler Node controller cases pass.
- [x] Windows installed-wheel smoke test passes.

**Note:** Counts are supporting evidence, not coverage proofs. The original
655-test run belongs to preparatory cleanup; the completed candidate's 961-test
run includes the later correctness and application-boundary regressions.

### V147-02 - Correct historical outcome aggregation

**Priority:** Release blocker. **Assessment:** F01. **Estimate:** 2-4 days. **Status:** ✅ Implemented.

- [x] Specify fixture-level rows separately from player-gameweek outcomes.
- [x] Aggregate points/minutes and other additive fields correctly for DGWs.
- [x] Preserve fixture identity for provenance and diagnostics.
- [x] Version corrected scoring/execution; do not overwrite existing trials.
- [x] Define how partially completed legacy sessions are continued, cloned,
  archived or explicitly migrated.

Acceptance: DGW aggregation correct; row ordering does not change results;
one-played/one-DNP fixtures handled correctly; captain/chip scoring uses
aggregated outcome.

### V147-03 - One authoritative financial operation

**Priority:** Release blocker. **Assessment:** F02, F03, F12. **Estimate:** 2-4 days. **Status:** ✅ Implemented.

- [x] Reuse canonical sale-price calculation across execution, logging,
  reconciliation, replay and Undo.
- [x] Validate affordability before writing ownership, decision rows or files.
- [x] Remove deficit-hiding clamps; a rejected command preserves both stores.
- [x] Distinguish market, purchase, sale, liquidation and pending-bank values.

**Delivered:** Canonical baseline settlement including chip retained costs; all
financial operations validated before write; no deficit clamping. No ongoing 100m
cap—affordability depends on available bank and legal sale proceeds.

### V147-04 - Revisioned commands and durable unit of work

**Priority:** Release blocker. **Assessment:** F04. **Estimate:** 4-7 days for
the initial durable command slice; full schema conversion needs separate sizing. **Status:** ✅ Implemented.

- [x] Define immutable command inputs and a mutation receipt.
- [x] Reject stale revisions and duplicate command submissions safely.
- [x] Validate the whole prospective state before committing.
- [x] Choose one transactional state store, or a recoverable file/SQL journal
  with atomic file replacement and startup recovery.
- [x] Serialize writes per team/session; define conflict behavior explicitly.
- [x] Keep authoritative price uncertainty rather than fabricating legacy values.

**Delivered:** CommandBus with revisioned receipts; explicit error states
(RECOVERY_REQUIRED, RECOVERY_CONFLICT); unknown/null execution marker archives
readable/read-only/forkable; no fabricated legacy values.

### V147-05 - Explicit lifecycle and calculation context

**Priority:** High. **Assessment:** F05, F06. **Estimate:** 2-4 days, overlapping
the service extraction in V147-08. **Status:** ✅ Implemented.

- [x] Move GW advancement/chip renewal out of team-list and report reads.
- [x] Make GW19 -> GW20 renewal idempotent and preserve already-used chips.
- [x] Pass the decision's exact squad, GW, snapshot, bank, FT and chip context
  into recommendation capture.
- [x] Separate pure calculation from shared report-file export.

**Delivered:** Later-GW mutators renew chips atomically through
`teams.advance_current_squad`; FT transitions use the shared rule in `rules.py`.
There is no fallback to live defaults in historical context;
exact prospective state captured for every recommendation.

### V147-06 - Data admission and cache integrity

**Priority:** High. **Assessment:** F07, F08. **Estimate:** 2-4 days. **Status:** ✅ Implemented.

- [x] Publish cache keys only with successfully validated values.
- [x] Validate required files, JSON/schema, numeric types and references.
- [x] Support legitimate DGW rows without accepting duplicate fixture identities.
- [x] Surface global registry failures rather than filtering them away by text.
- [x] Record source digests and knowledge-cutoff assumptions.

**Delivered:** Validation guards cache publication; no text-filtered silent failures;
DGW rows supported with fixture identity integrity; source digests recorded.

### V147-07 - Predictor, objective and evaluation contracts

**Priority:** High before relying on research comparisons.
**Assessment:** F09-F11, F13-F15. **Estimate:** 6-12 days, with any long-running
new benchmark programme estimated separately. **Status:** ✅ Implemented.

- [x] Make predictor identity propagate through single-GW and horizon calculations.
- [x] Preserve GBDT forward semantics; reject unavailable required predictors.
- [x] Include every objective term in admissible pruning bounds.
- [x] Establish mathematically defined regret components and feasible sets.
- [x] Return only strategy-permitted chip deployments.
- [x] Share GW1/GW2 FT transition rules across planners/execution.
- [x] Preserve mean xP reporting separately from the chosen risk utility.

**Delivered:** Shared FT helper now in rules.py used by planners/session/decision
history; Strategic Studio candidate revision retained and POST calculates through
query boundary; predictor identity and objective terms survive every adapter.

### V147-08 - Framework-independent application boundary

**Priority:** Prerequisite for production Qt write workflows.
**Estimate:** 5-9 days, overlapping V147-04/05 rather than added on top unchanged. **Status:** ✅ Implemented.

- [x] Extract query/command services from HTTP and CLI orchestration.
- [x] Introduce typed read models for squad, valuations, staged/executed moves,
  plans, decisions, chip state and provenance.
- [x] Pass explicit repository paths and request-scoped state, preserving
  explicit predictor/default-engine policy at domain entry points.
- [x] Return explicit domain errors and revisions; do not resolve global context
  late in an operation.
- [x] Let the existing web adapter consume those services before connecting Qt.

**Delivered:** Application boundary extracted with command/query services and typed
read models; HTTP and CLI consume shared command services. **Note:** Legacy HTTP
calculation orchestration retained in server.py—generic application query boundary
wraps remaining orchestration. Not every HTTP calculation has been moved out.

### V147-09 - Quality, observability and release gates

**Priority:** High. **Estimate:** 3-5 days initially. **Status:** ✅ Implemented — local automated gates pass; remote checks attach to the pushed commit and manual acceptance remains outstanding.

- [x] Canonicalize package imports in tests and test an installed artifact.
- [x] Add Windows validation, failure injection and representative slow jobs.
- [x] Inventory broad/suppressed exception paths and remove false-success cases.
- [x] Record operation/context/revision identifiers without secrets.
- [x] Record exploratory solve/HTTP latency without inferring worker budgets.
- [ ] Measure real-browser responsiveness and representative unloaded p95 before
  approving client performance budgets.
- [x] Keep CI tied to the release branch and report actual manual-test status.

**Delivered:** Automated adverse paths discriminating; no mocked-only success;
structured logs (operation/context/revision IDs). **Local evidence:** 961 passing
tests, 42 actual-handler Node cases and an installed-wheel smoke. **External
gates:** candidate CI checks; manual visual/accessibility acceptance;
representative unloaded p95; Windows clean-machine native desktop package proof.

### V147-10 - Native GUI design, licensing and technical proof

**Status:** 🔒 Explicitly gated. **Estimate:** 2-3 days for the initial technical spike,
excluding external licensing/procurement lead time. **No implementation on v147 branch.**

Gate requirements before authorization:
1. **Licensing approval:** PyQt6/Qt strategy (GPLv3, commercial, or PySide6) and procurement.
2. **Foundation validation:** V147-04, V147-05, V147-08 pass targeted acceptance tests.
3. **Shared-workflow approval:** Stakeholders approve Live/Historical wireframes and terminology.
4. **Resource/deployment proof:** Packaged resources and paths work on clean Windows machine.

Once approved, proceed through phased implementation (Q0-Q7 in PyQt6 plan).

Sub-tasks (informational only; await gate approval):
- [ ] Approve the licensing/distribution route (GPLv3, commercial, or PySide6).
- [ ] Approve shared Live/Historical wireframes and state terminology.
- [ ] Demonstrate a native model/view table and pitch interaction.
- [ ] Demonstrate deferred work, context switching, cancellation and safe shutdown.
- [ ] Demonstrate resource/data paths in a packaged Windows prototype.

This gate authorizes a decision about implementing the port; the current branch
does not contain that implementation.

## 5. Sequencing and Release Slices

| Slice | Scope | Gate before proceeding |
|---|---|---|
| A: completed preparatory cleanup | V147-01 and assessment/design documents | Existing behavior and historical exclusions preserved |
| B: authoritative correctness | Outcome aggregation, prices/funds, predictor propagation | Known high-priority counterexamples fixed with versioned semantics |
| C: state and application boundary | Commands/revisions, lifecycle, data admission and cache integrity | Fault/recovery and two-context contracts pass |
| D: desktop design proof | Licensing, shared layouts, worker/model/packaging spike | Native implementation explicitly approved |
| E: staged native implementation | Q2-Q7 in the PyQt6 plan | Every shared workflow and live-only exception accepted |
| F: cutover | Default-client decision, packaging, release evidence | No partial client substituted for the full historical laboratory |

Model/evaluation work can run in parallel with GUI design when it does not change
the contracts being implemented. State schemas, prices and command semantics
must stabilize before several views independently implement them.

Recommended release discipline: ship a small stabilization slice first if the
native port is not ready. Do not use the V1.4.7 label to force an incomplete
desktop migration into a release.

## 6. Effort and Scheduling

- A first **critical-correctness/stabilization slice** is approximately **12-20
  person-days**, depending on how much command/storage work is included. This is
  not the sum of every optional research and desktop task.
- Full native parity and Windows distribution are estimated in the companion
  plan at **44-68 base person-days**, or **58-89** with approximately 30%
  uncertainty: roughly **12-18 working weeks for one engineer**.
- That native estimate includes service/migration foundations, but not every
  quantitative/data-quality/evaluation backlog item. If the complete audit
  remediation is bundled into the same programme, allow another **8-15
  person-days** outside overlapping foundation work: approximately **52-83 base**
  or **68-108 with uncertainty**, about **14-22 working weeks**.
- Do not add completed foundation work twice. Re-estimate after the first
  corrected, revisioned command and the Qt vertical slice.
- Extra native platforms, signed installers, auto-update infrastructure,
  extensive visual redesign and new research trials are explicit scope changes.

These are planning ranges, not dates promised from line counts. External license
decisions and user-design acceptance can lengthen calendar time without adding
equivalent implementation days.

## 7. Definition of Done

**V1.4.7 release ready when:**

- [x] High-priority data/money/state counterexamples have focused regressions (V147-02/03).
- [x] Application-level legality, revisions and atomicity are tested independently
  of HTTP, browser and Qt (V147-04 complete).
- [x] Corrected research execution is versioned; old recorded results remain intact.
- [x] Predictor identity and objective terms have adapter/horizon regressions (V147-07).
- [x] Shared workflows retain solver capabilities in both modes.
- [x] Historical has neither Live Matchday nor AI Advisor & Briefing tabs (✅ V147-01 complete).
- [x] There is no decision-engine version selector in either GUI mode; LLM
  provider/model controls remain in the live advisory workspace (✅ V147-01 complete).
- [x] Application foundation extracted; command/domain contracts work independently of adapters.
- [x] Local automated quality gates, observability and failure tests pass.
- [ ] **Native (Qt) thread/model ownership, context cancellation and shutdown tested** — ⏹️ **Gated: awaits native implementation authorization and technical proof**.
- [ ] **Clean-machine Windows Qt package with correct resources and writable paths** — ⏹️ **Gated: awaits Qt implementation gate**.
- [ ] Manual visual/accessibility results recorded, not inferred from pytest.
- [ ] Licensing, data migration and default-client cutover explicitly approved.
- [x] Release claims distinguish measured local evidence, remote checks and unresolved manual/native gates.
