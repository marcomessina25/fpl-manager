# V1.4.7 Delivery Plan

**Status:** Proposed work programme; only the scoped GUI cleanup is implemented.
**Branch:** `v147`, based on merged `master` at `38595a7`.
**Date:** 2026-10-29.
**Inputs:** [Repository assessment](repository_analysis.md), [native PyQt6 plan](pyqt6_migration_plan.md).

## 1. Release Goal

Make the application a trustworthy decision-support product with clear state and
calculation boundaries. Prepare a native GUI without repeating V1.4.6's pattern
of adding many workflows before their shared invariants are established.

The immediate branch change removes decision-engine version menus. The rest of
this document is **planned**, not already implemented. In particular:

- No PyQt6 GUI, Qt dependency group or desktop package is introduced now.
- LLM provider/model choices remain in the live-only AI workspace.
- Historical already correctly hides Live Matchday and AI Advisor & Briefing;
  that behavior is preserved, not reimplemented.
- Historical should resemble Live through shared layouts and controls for the
  eight common workflows, not by exposing live-only features.
- Saved frozen baselines and published research records keep their provenance.
- The package version remains the current release until release preparation;
  a branch name alone does not declare a completed V1.4.7 release.

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
on Python 3.13, and **35 Node controller cases passed**. The Node cases are also
invoked by a pytest wrapper, so these numbers must not be added as independent
coverage. None of these results establishes that F01-F15 are repaired.

These are not a claim that the core findings F01-F15 have been repaired.

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

**Status:** Implemented on this branch.
**Scope:** Latest decision engine for new GUI work; no version menus or invented
hardcoded baseline labels.

Acceptance:
- [x] Actual transfer handlers omit client-side engine overrides in both modes.
- [x] New simulation requests preserve season/GW/name settings while using the
  backend's current default.
- [x] Explicit legacy research requests and stored baseline versions remain intact.
- [x] AI provider/model controls remain operational.
- [x] Switching from live-only tabs to Historical returns to an allowed workspace.

### V147-02 - Correct historical outcome aggregation

**Priority:** Release blocker. **Assessment:** F01. **Estimate:** 2-4 days.

- [ ] Specify fixture-level rows separately from player-gameweek outcomes.
- [ ] Aggregate points/minutes and other additive fields correctly for DGWs.
- [ ] Preserve fixture identity for provenance and diagnostics.
- [ ] Version corrected scoring/execution; do not overwrite existing trials.
- [ ] Define how partially completed legacy sessions are continued, cloned,
  archived or explicitly migrated.

Acceptance: Mateta GW34 returns 29 points/157 minutes; row ordering does not
change results; one-played/one-DNP fixtures do not trigger false autosubs or
vice-captain promotion; captain/chip scoring uses the aggregated outcome.

### V147-03 - One authoritative financial operation

**Priority:** Release blocker. **Assessment:** F02, F03, F12. **Estimate:** 2-4 days.

- [ ] Reuse canonical sale-price calculation across execution, logging,
  reconciliation, replay and Undo.
- [ ] Validate affordability before writing ownership, decision rows or files.
- [ ] Remove deficit-hiding clamps; a rejected command preserves both stores.
- [ ] Distinguish market, purchase, sale, liquidation and pending-bank values.

Do not restore a blanket 100m cap on an ongoing squad's appreciated market
value. Affordability depends on actual available bank and legal sale proceeds,
not whether current market value exceeds the initial squad-construction budget.

Acceptance: price falls/flat/odd-even rises; zero-bank unaffordable purchase;
multiple and chained trades; repeat lineup save; historical/past-decision
logging; exact integer-tenths conservation through every entry point.

### V147-04 - Revisioned commands and durable unit of work

**Priority:** Release blocker. **Assessment:** F04. **Estimate:** 4-7 days for
the initial durable command slice; full schema conversion needs separate sizing.

- [ ] Define immutable command inputs and a mutation receipt.
- [ ] Reject stale revisions and duplicate command submissions safely.
- [ ] Validate the whole prospective state before committing.
- [ ] Choose one transactional state store, or a recoverable file/SQL journal
  with atomic file replacement and startup recovery.
- [ ] Serialize writes per team/session; define conflict behavior explicitly.
- [ ] Keep authoritative price uncertainty rather than fabricating legacy values.

Acceptance: inject failure before/after each write and recovery step; reject
same captain/vice without consuming a chip; reject stale concurrent commands;
restore ownership, prices, bank, chips, XI and history exactly after Undo.

### V147-05 - Explicit lifecycle and calculation context

**Priority:** High. **Assessment:** F05, F06. **Estimate:** 2-4 days, overlapping
the service extraction in V147-08.

- [ ] Move GW advancement/chip renewal out of team-list and report reads.
- [ ] Make GW19 -> GW20 renewal idempotent and preserve already-used chips.
- [ ] Pass the decision's exact squad, GW, snapshot, bank, FT and chip context
  into recommendation capture.
- [ ] Separate pure calculation from shared report-file export.

Acceptance: two teams with different portfolios never capture each other's
advice; past/historical queries never fall back to live defaults; repeated reads
do not change authoritative state; every advancement path renews chips once.

### V147-06 - Data admission and cache integrity

**Priority:** High. **Assessment:** F07, F08. **Estimate:** 2-4 days.

- [ ] Publish cache keys only with successfully validated values.
- [ ] Validate required files, JSON/schema, numeric types and references.
- [ ] Support legitimate DGW rows without accepting duplicate fixture identities.
- [ ] Surface global registry failures rather than filtering them away by text.
- [ ] Record source digests and knowledge-cutoff assumptions.

Acceptance: valid A -> malformed B -> retry B never returns A; empty/corrupt GW
files and missing teams/fixtures fail with actionable errors; score masking and
announcement-time fixture provenance are reported as distinct guarantees.

### V147-07 - Predictor, objective and evaluation contracts

**Priority:** High before relying on research comparisons.
**Assessment:** F09-F11, F13-F15. **Estimate:** 6-12 days, with any long-running
new benchmark programme estimated separately.

- [ ] Make predictor identity propagate through single-GW and horizon calculations.
- [ ] Preserve GBDT forward semantics; reject unavailable required predictors.
- [ ] Include every objective term in admissible pruning bounds.
- [ ] Establish mathematically defined regret components and feasible sets.
- [ ] Return only strategy-permitted chip deployments.
- [ ] Share GW1/GW2 FT transition rules across planners/execution.
- [ ] Preserve mean xP reporting separately from the chosen risk utility.

Acceptance: tiny exhaustive search oracles, bonus-dominant moves, predictor spies
and aliases, no silent fallback, signed/decomposed regret reconciliation,
guardrail-exhausted windows, and equivalent live/historical input contracts.

### V147-08 - Framework-independent application boundary

**Priority:** Prerequisite for production Qt write workflows.
**Estimate:** 5-9 days, overlapping V147-04/05 rather than added on top unchanged.

- [ ] Extract query/command services from HTTP and CLI orchestration.
- [ ] Introduce typed read models for squad, valuations, staged/executed moves,
  plans, decisions, chip state and provenance.
- [ ] Inject repositories, paths and predictor/default policy.
- [ ] Return explicit domain errors and revisions; do not resolve global context
  late in an operation.
- [ ] Let the existing web adapter consume those services before connecting Qt.

Acceptance: no GUI import in domain/application services; the same command has
the same validated result through supported adapters; calculation-only queries
do not write state or reports; context changes invalidate all stale results.

### V147-09 - Quality, observability and release gates

**Priority:** High. **Estimate:** 3-5 days initially.

- [ ] Canonicalize package imports in tests and test an installed artifact.
- [ ] Add Windows validation, failure injection and representative slow jobs.
- [ ] Inventory broad/suppressed exception paths and remove false-success cases.
- [ ] Record operation/context/revision identifiers without secrets.
- [ ] Measure solve latency and UI responsiveness before choosing worker budgets.
- [ ] Keep CI tied to the release branch and report actual manual-test status.

Acceptance: automated adverse paths are discriminating, not only mocked success;
no unsupported real-browser claims; migration and cold-start failure are tested;
CI builds the candidate being shipped, not only editable-checkout source.

### V147-10 - Native GUI design, licensing and technical proof

**Status:** Planned only. **Estimate:** 2-3 days for the initial technical spike,
excluding external licensing/procurement lead time.

- [ ] Approve the licensing/distribution route.
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

- [ ] High-priority data/money/state counterexamples no longer reproduce.
- [ ] Application-level legality, revisions and atomicity are tested independently
  of HTTP, browser and Qt.
- [ ] Corrected research execution is versioned; old recorded results remain intact.
- [ ] Predictor identity and objective terms survive every adapter/horizon.
- [ ] Shared workflows remain full-capability in both modes.
- [ ] Historical has neither Live Matchday nor AI Advisor & Briefing tabs.
- [ ] There is no decision-engine version selector in either GUI mode; LLM
  provider/model controls remain in the live advisory workspace.
- [ ] Native thread/model ownership, context cancellation and shutdown are tested.
- [ ] A clean-machine Windows package has correct resources and writable paths.
- [ ] Manual visual/accessibility results are recorded, not inferred from pytest.
- [ ] Licensing, data migration and default-client cutover are explicitly approved.
- [ ] Release claims name measured evidence and unresolved limitations honestly.
