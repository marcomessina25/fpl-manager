# PyQt6 Migration Plan and Effort Estimate

**Status:** Design proposal only; no PyQt6 port or dependency installation performed.
**Assessment date:** 2026-10-29.
**Baseline:** merged V1.4.6, `38595a7fd6946fe64a9c8047761728cb6e348722`.
**Related documents:** [Repository assessment](repository_analysis.md), [V1.4.7 delivery plan](v147_plan.md).

## 1. Recommendation

Use native **PyQt6 Widgets** for a future desktop client, but extract a
framework-independent application layer before connecting widgets to the engine.
Do not translate the existing JavaScript controller line by line into a large
`MainWindow` class. Do not treat embedding the current site in `QWebEngineView`
as the requested native port.

The migration can reuse the quantitative and optimization implementation. It
cannot safely reuse the present UI orchestration unchanged: context ownership,
staging, persistence, asynchronous results, and errors need explicit contracts.
Qt supplies useful widgets and lifecycle mechanisms, not automatic correctness.

The current web interface remains the supported client until the native client
passes the complete shared-workflow acceptance matrix. An incomplete Qt spike is
development evidence, not a production replacement.

## 2. Scope and Product Rules

The existing navigation has ten workspaces: **eight shared** and **two live-only**.
Historical mode already correctly hides Live Matchday and AI Advisor & Briefing.
Preserve that behavior; it is not a defect to repair.

For the shared workspaces, Historical should use the same shell, navigation,
spacing, interaction patterns, controls, terminology, and result presentation as
Live. Differences must represent the selected dataset/rules and simulation time,
not reduced capabilities or a separate-looking application.

| Workspace | Native implementation | Required behavior |
|---|---|---|
| Overview & Standings | Tables, fixture/result delegates, date/GW navigation | Historical as-of knowledge; no future scores |
| Pitch & Lineup | `QGraphicsView` scene plus an accessible table alternative | XI/bench ordering, swaps, captain/vice, logged/model views |
| Transfers & Staging | Form controls and ranked move cards/delegates | 1-5 transfers, 1-10 GW evaluation, risk controls, atomic Apply |
| Strategic Studio | Searchable player table, constraint controls, candidate comparison | Budget, modes/profiles, locks/excludes/preferences, Apply |
| Decision Logger | Executed-trade model and decision editor | Manual trades only here; audit, chip and lineup consistency |
| Multi-GW Planner | Roadmap table/cards and step details | Genuine 1-8 GW planning and atomic step-0 Apply |
| Chip Strategy & Calendar | Calendar/table and opportunity details | Complete active segment, feasible valuations, conflict checks |
| Evaluation & History | History tables, score summaries, optional trend views | Actual/net/hit units consistent; session-specific history |
| Live Matchday | Live score/fixture views | **Live only**, never invoked from Historical |
| AI Advisor & Briefing | Provider/model controls, structured briefing, advisory text | **Live only**; retain provider/model choice |

Decision-engine version selection is not part of the future GUI. New GUI
calculations use the centrally registered current engine. Existing frozen
research baselines retain their recorded settings and provenance. Hiding a menu
must not silently rewrite old experiments.

Preserve team/session creation, import, renaming/deletion, player details,
confirmation dialogs, error recovery, and completed-season behavior; these are
part of the port, not incidental polish.

## 3. Proposed Architecture

This is a target design, not an existing package layout:

```text
                  Web / CLI adapters         PyQt6 views
                          |                        |
                          |              presenters/controllers
                          +------------+-----------+
                                       |
                      application queries and commands
                 typed context, revision, errors, receipts
                                       |
                      domain services and repositories
                      /              |               \
              projections       rules/solvers     persistence
                                       |
                     immutable snapshots / recorded results
```

### Application boundary

Introduce explicit context types rather than interpreting a missing
`session_id` as permission to use a live team:

- Live: team identifier, season, gameweek, state revision.
- Historical: session identifier, season, simulation gameweek, state revision.
- Research/reference configuration: explicitly versioned; not an end-user GUI
  engine preference.

Queries return immutable read models with context and provenance. Commands
return a mutation receipt and the resulting authoritative state. Views must not
reconstruct bank, purchase basis, hits, chip inventory, or transfer history.

Candidate results retain the revision against which they were computed. Apply
must reject a stale revision or recalculate deliberately; it must not silently
apply a different transaction.

### Repositories and transactions

Choose a durable-write strategy before native write workflows are implemented:

1. Prefer one transactional authoritative store for mutable state, with versioned
   JSON import/export and immutable research records.
2. If JSON remains authoritative during transition, use atomic file replacement,
   per-context serialization, and a durable recovery protocol for file/SQL
   operations. Compensating rollback with suppressed errors is not sufficient.

The choice needs a migration proof against real *sanitized* legacy shapes,
including unrecoverable purchase basis. Preserve originals before migration;
never invent acquisition prices merely to make a load succeed.

Qt models consume repositories through services. Neither table delegates nor
pitch item handlers should execute SQL or modify session JSON directly.

## 4. Native UI Structure

- One application shell and shared navigation, not separate Live/Historical
  window implementations.
- A common context header: mode, team/session, season, active deadline/GW,
  observation cutoff, and clear pending-operation state.
- `QAbstractTableModel` / `QAbstractListModel` for players, squad, moves, decisions,
  plans, and fixtures; proxy models for filtering and sorting.
- Stable row keys include the player universe and context. Numeric player IDs
  alone are not identities across seasons.
- Presenters own screen state; reusable display formatters own money/xP/hit units.
- Central palette, typography, spacing and semantic colors. Do not transplant
  hundreds of inline style strings into Python.
- Keyboard access, predictable focus restoration, accessible labels, scalable
  layouts and Windows high-DPI behavior are acceptance requirements.
- A pitch is useful, but an accessible squad table must offer the same actions.
- Do not add a new experimental menu, technical engine dropdown, or manual
  transfer editor outside Decision Logger.

Use Qt Designer selectively for stable form layouts if the team prefers it.
Generated UI files should remain generated; keep state and business logic
outside them. Do not make a Designer-versus-handwritten choice a prerequisite to
all service work.

## 5. Jobs, Threads, Cancellation and Stale Results

Qt Widgets must be used on the GUI thread. Worker results should enter through
queued signals into GUI-thread receivers; workers must not update widget/model
state directly. QObject ownership and disposal must follow thread affinity [S2].

Recommended task contract:

1. Capture immutable context, revision, inputs and a job identifier.
2. Show loading state and disable only conflicting mutations.
3. Execute a read/compute operation outside the GUI event loop.
4. On completion, verify job, context and revision before publishing results.
5. On navigation, invalidate the old job's authority immediately.
6. Cancellation is cooperative; a running task may finish and be discarded.
7. Serialize mutations and acknowledge whether an operation actually committed.

Use worker threads for blocking I/O and suitable short tasks. Evaluate process
workers for substantial Python CPU-bound searches: `QThread` is not a promise of
CPU parallelism under the Python GIL. This process choice is an engineering
recommendation to validate in the spike, not a Qt guarantee.

For Windows process workers, use explicit spawn-safe entry points, serializable
DTOs and immutable inputs. Do not send QObjects or live SQLite connections to a
process. Do not forcibly terminate a worker that owns a state mutation.

Shutdown must reject new jobs, invalidate late results, complete or recover
committed writes, and dispose workers correctly. Do not destroy a running thread
and hope queued callbacks are harmless.

Proposed performance gates, **not measured current performance**:

- Simple local interactions should visibly acknowledge input within 100 ms.
- Long work should show progress/loading feedback rather than freeze the UI.
- Cancellation should acknowledge the user's request promptly while explaining
  any safe completion boundary.
- Establish measured median/p95 solve times on representative datasets and a
  specified machine before setting solver time budgets.

## 6. Persistence, Resources and Distribution

The current source-tree `PROJECT_ROOT` assumptions are not a desktop deployment
strategy. Introduce injectable paths and resource access:

- Packaged immutable resources/models through a resource locator.
- Writable application data and caches in appropriate per-user locations.
- Explicit legacy repository import; no silent copying or overwriting of teams.
- Historical datasets managed separately from the executable where appropriate.
- `QSettings` for geometry/preferences, not authoritative FPL state or API secrets.
- Preserve existing CLI database/config overrides and headless workflows.
- No Qt import requirement for domain tests or non-GUI CLI use.

Plan an optional desktop dependency group only when implementation is approved.
No PyQt6 dependency or native GUI module is added by this planning task.

Start packaging with a directory-based Windows build for easier diagnosis.
Validate frozen model/resource discovery on a clean machine without a repository
checkout. Consider one-file packaging only after correctness and startup behavior
are understood.

PyInstaller bundles are specific to their build OS/interpreter; it is not a
cross-compiler [S5]. macOS signing/notarization and additional native installers
must be estimated separately rather than assumed free.

## 7. Licensing Gate

The repository is MIT-licensed (`LICENSE:1`). **PyQt6 is GPLv3 or commercially
licensed, not LGPL**; Qt's own licensing is a separate consideration [S1].

Before distribution, approve one of:

- GPL-compatible distribution with the applicable notices and obligations; or
- a suitable commercial PyQt license and correctly licensed Qt distribution.

Do not silently change the repository license, assume MIT settles the combined
application's obligations, or substitute another binding without approval.
PySide6 can be evaluated as an alternative if licensing requirements demand it,
but that is a decision gate, not a change to the requested PyQt6 plan.

This is a technical planning constraint, not legal advice. License review and
procurement lead time are external calendar risks.

## 8. Migration Phases and Acceptance Gates

| Phase | Deliverable | Exit gate |
|---|---|---|
| Q0 | Licensing decision and disposable technical spike | A responsive window, real model/view table and delayed-worker test; no user-state mutation |
| Q1 | Application services, contexts and repository contracts | Headless tests prove legality, revisions, isolation, atomicity and recovery |
| Q2 | Shared shell, navigation, task broker and read models | Mode switches discard stale jobs; correct eight/shared plus two/live-only navigation |
| Q3 | Overview, players and squad/pitch | Search, filtering, XI/bench/captain controls and accessible alternative pass |
| Q4 | Transfers and Strategic Studio | All supported controls, genuine solvers and safe candidate Apply |
| Q5 | Logger, planner and chip calendar | Exact accounting, complete planning and chip transitions |
| Q6 | Live/advisory and evaluation/report workflows | Existing live-only boundaries and LLM choices preserved |
| Q7 | Packaging, parity and cutover validation | Clean-machine build and full two-mode workflow matrix pass |

Keep the web client available during implementation. A proposed future
`--ui qt` development option is only an option to design later; it does not exist
as a result of this document. Do not switch the default until Q7 is complete.

## 9. Testing Strategy

- Keep calculation/rules/solver tests independent of Qt.
- Reuse service-level contract fixtures across CLI, HTTP and native adapters.
- Add `pytest-qt` only for the implementation phase; explicitly select the PyQt6
  binding when multiple bindings are installed [S4].
- Exercise real widgets, model notifications, queued signals, focus and shutdown.
- Use controlled deferred workers to reproduce A -> B, Live -> Historical,
  GW5 -> GW6 -> GW5, cancellation, and late-error scenarios deterministically.
- Verify identical shared capabilities, not identical results from different
  seasons or different rule contexts.
- Test file/SQL failure points, save/load, old schema migration, unknown price
  basis, repeated Apply, Undo/replay, and Free Hit lifecycle through services.
- Retain the current Node controller regressions until the web client is retired.
- Add Windows CI and clean-machine packaging checks; Linux offscreen widget
  tests alone are not evidence of a good Windows desktop experience.
- Manual visual/high-DPI/accessibility acceptance remains distinct from unit
  counts and screenshots generated by a test runner.

## 10. Work Estimate

### Assumptions

One senior Python engineer comfortable with Qt, stable feature scope, ten
workspaces, eight of them shared between modes, and reuse of the current
calculation core. Include tests and Windows packaging; exclude new predictive
models, a new optimization algorithm, rewritten historical datasets, auto-update
infrastructure, and a multi-participant benchmark.

This is an engineering estimate before a Qt spike, not a fixed-price quote.
Person-days mean focused implementation/review effort, not elapsed calendar time.

| Package | Person-days |
|---|---:|
| Q0: licensing/technical decisions and spike | 2-3 |
| Q1: service extraction, revisioned writes and migration hardening | 10-16 |
| Q2: shared shell, task lifecycle and model infrastructure | 3-5 |
| Q3a: overview, player search and read-model views | 5-7 |
| Q3b: pitch, lineup, bench and captain interactions | 5-8 |
| Q4: transfer results, constraints and Strategic Studio | 5-8 |
| Q5: logger, planner and chip calendar | 5-7 |
| Q6: live/advisory, evaluation and reports | 3-5 |
| Q7: cross-workflow tests, Windows packaging and cutover | 6-9 |
| **Base total** | **44-68** |
| **With approximately 30% uncertainty allowance** | **58-89** |

**Planning envelope:** roughly **12-18 working weeks for one engineer**.
Two experienced engineers may bring the calendar envelope to approximately
**8-12 weeks**, but service design, data migration and final parity remain on the
critical path; effort does not simply halve.

The base includes the Q1 prerequisite work. If V1.4.7 completes that work first,
subtract it once from the remaining migration estimate; do not charge it twice.
An unexpectedly broad move of all mutable JSON state into a new SQL schema, a
large redesign of the underlying rules, or incomplete data provenance requires
re-estimation rather than absorption into an optimistic UI-only budget.

The repository assessment also identifies calculation, scoring and research
measurement repairs beyond the GUI/application-boundary migration itself.
Bundling the complete audit remediation into the same programme adds roughly
**8-15 person-days outside overlapping foundations**: approximately **52-83 base
days**, or **68-108 with uncertainty** (**14-22 working weeks** for one engineer).
This is a broader programme estimate, not a second bill for Q1. Prioritize the
high-risk outcome/money/predictor defects before production native cutover.

Optional scope changes:

- Additional polished/signed native OS distributions: allow roughly 4-8 extra
  person-days per platform, plus external signing/notarization lead time.
- A fully polished interaction/visual redesign beyond parity can add design and
  usability rounds; specify those before committing a date.
- A web-view wrapper is much smaller but does not deliver the proposed native
  architecture and does not eliminate the current lifecycle debt.

Confidence is **medium-low before Q0/Q1**. Re-estimate after the first real
end-to-end vertical slice and measured packaging result.

## 11. Decisions Required Before Implementation

- PyQt licensing/distribution route.
- Windows-first versus additional native distribution targets.
- Authoritative state/recovery design and legacy import policy.
- Approval of common screen wireframes and historical capability exceptions.
- Which CPU jobs need process isolation, based on measurements.
- Whether the native client is a later V1.4.7 milestone or a subsequent release;
  do not merge an incomplete port merely to meet the version label.

## 12. Sources

External documentation checked 2026-10-29; floating Qt URLs can reference a
different minor release from the eventual pinned PyQt build. Confirm compatibility
when selecting dependencies, rather than treating a documentation heading as a
tested package version.

- **[S1]** [Riverbank: PyQt and licensing](https://www.riverbankcomputing.com/software/pyqt/).
- **[S2]** [Qt: Threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html).
- **[S3]** [Qt: Model/View Programming](https://doc.qt.io/qt-6/model-view-programming.html).
- **[S4]** [pytest-qt: supported bindings and widget/signal testing](https://pytest-qt.readthedocs.io/en/latest/intro.html).
- **[S5]** [PyInstaller: operating modes and platform-specific builds](https://pyinstaller.org/en/stable/operating-mode.html).
- [Riverbank: signals and slots](https://www.riverbankcomputing.com/static/Docs/PyQt6/signals_slots.html).
