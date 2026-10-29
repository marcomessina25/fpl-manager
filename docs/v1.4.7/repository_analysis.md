# Repository Assessment for V1.4.7

**Assessment date:** 2026-10-29.
**Evidence baseline:** merged V1.4.6, `38595a7fd6946fe64a9c8047761728cb6e348722`.
**Working branch:** `v147`, created from that `master` and pushed to `origin`.
**Companion documents:** [Delivery plan](v147_plan.md), [PyQt6 migration and estimate](pyqt6_migration_plan.md).

## 1. Executive Assessment

This is a valuable domain application with substantial reusable Python code,
not software that should be discarded. However, the evidence does **not** justify
the simpler conclusion that the GUI is bad and the engine is already sound.

The weakest boundary is between user actions, mutable state, persistence,
calculation and presentation. The browser exposes this weakness through stale
responses, duplicated controls and accounting inconsistencies. Related problems
also exist in execution, historical outcomes, predictor selection and evaluation.

**Recommendation:** make V1.4.7 a correctness-and-boundaries milestone, with a
designed native PyQt6 client as a gated follow-on workstream. Preserve the useful
calculation core, but do not build a second GUI directly over today's HTTP
handler and JSON/SQL mutation routines.

PyQt6 can improve native interaction, model/view structure and distribution.
It will not automatically fix an incorrect sale price, lost double-GW points,
or a result emitted after the user changed sessions.

## 2. Scope, Evidence and Limitations

The assessment covers source structure, domain and optimizer paths, data and
persistence, browser orchestration, tests, CI, packaging assumptions, and
research claims. Source references below identify the baseline commit, not
necessarily line numbers after the small V1.4.7 cleanup.

Evidence includes source inspection, targeted in-memory checks, public historical
records, existing regression history, and static measurements of tracked files.
Private team databases, credentials and raw human replay sessions were not used
as audit input.

Important boundaries:

- The merged release has a 647-case pytest suite and Node controller regressions.
  Test count is **not** line/branch coverage or proof of FPL correctness.
- This is not a dedicated penetration test, an accessibility certification,
  a live user study, or a full independent rescore of the benchmark seasons.
- No complete real-browser visual review or native Qt spike was performed.
  Visual/UX recommendations are based on interaction structure and source, not
  claimed screenshot or usability measurements.
- New findings below are **analysis and planned remediation**, not fixes silently
  included with the decision-engine menu removal.
- Current Historical hiding of Live Matchday and AI Advisor & Briefing is
  correct and explicitly preserved.

### Immediate V1.4.7 branch changes

The narrowly scoped implementation removes decision-engine version menus from
Transfers, Strategic Studio and simulation creation. New GUI calculations and
new simulations resolve the central latest-engine policy. LLM provider/model
choices and explicit research versions remain available in their proper places;
saved frozen baselines are not upgraded.

The no-argument legacy resolver contract is retained. GUI callers use an explicit
`"default"` policy rather than changing implicit research behavior.

## 3. Measured Baseline

These are physical line/function-span measurements, not logical SLOC,
cyclomatic complexity, test coverage, or automatic defect counts.

| Measure | Observed baseline |
|---|---:|
| Python source modules under `src` | 63 |
| Physical Python source lines | 36,613 |
| Python test modules | 59 |
| Physical Python test lines | 20,892 |
| Python scripts | 23 |
| Named top-level browser functions | 117 |
| Named asynchronous browser functions | 39 |
| Browser `await` occurrences | 175 |
| Top-level workspaces | 10: eight shared, two live-only |
| Inline `style=` occurrences in HTML / JavaScript | 171 / 284 |
| CSS custom-property definitions | 16 |
| Broad exception handlers in Python source | 127 |
| Of those, pass-only handlers | 46 |
| Source function spans longer than 100 lines | 98 |

Large functions can be justified, and broad handlers are not all bugs. Here the
signals matter because they coincide with repeated lifecycle, rollback,
validation and orchestration failures.

| Hotspot | Physical lines / span | Evidence |
|---|---:|---|
| Browser controller | 6,954 | `gui\static\app.js` |
| HTTP adapter | 2,452 | `gui\server.py` |
| Simulation aggregate | 2,357 | `simulation\session.py` |
| Decision-engine catalogue | 2,289 | `backtest\decision_engine.py` |
| Browser CSS / HTML | 1,843 / 1,186 | `gui\static\app.css`, `index.html` |
| HTTP `do_POST` | 1,263 | `gui\server.py:1022-2284` |
| HTTP `do_GET` | 855 | `gui\server.py:166-1020` |
| CLI `main` | 1,042 | `cli.py:835-1876` |
| Historical planner | 480 | `planner.py:520-999` |
| Strategic squad solve | 455 | `strategic_squad.py:729-1183` |
| GW resolution | 439 | `simulation\session.py:1425-1863` |

All paths in the hotspot table are relative to `src\fpl_manager`.

## 4. What Is Good and Should Be Preserved

| Strength | Why it matters | Representative evidence |
|---|---|---|
| Real domain implementation | Lineups, captain fallback, autosubs, transfers, chips and budgets are not delegated to an LLM | `rules.py`, `lineup.py`, `transfers.py`, `backtest\engine.py` |
| Mostly reusable Python calculation core | A native client need not reimplement projection and search algorithms | `expected_points.py`, `optimizer.py`, `strategic_squad.py` |
| Integer-tenths pricing | Correct basis for exact money conservation and sale-price rounding | `transfers.py:26-30`, `squad_state.py` |
| Explicit player and projection structures | Existing enums/dataclasses can seed stronger application contracts | `models.py`, `expected_points.py`, `simulation\models.py` |
| Actual search capabilities | Transfer search, legal formation selection, strategic heuristics and beam trajectories provide useful functionality | `optimizer.py`, `strategic_squad.py`, `planner.py` |
| Reference/experimental machinery | Exact small-instance references, model registry and ablations are useful validation assets | `strategic_squad.py`, `model_registry.py`, `backtest\optimizer_ablation.py` |
| Historical reconstruction intent | There are dedicated snapshot, standings and reconstruction paths rather than simply querying live state | `historical\`, `simulation\` |
| Growing stateful regression base | Recent tests address real asynchronous and accounting failures, not only page availability | `tests\test_gui_context.js`, `tests\test_historical_session_integrity.py` |
| Optional advisory role | The architecture describes the LLM as an analyst over facts, not an authority for legality | `docs\architecture.md:5-62`, `llm_advisor.py` |
| Local-first baseline | Default loopback hosting, local data and explicit optional remote advisory are appropriate for the product | `gui\server.py:2381-2414`, `providers.py` |
| Research records now disclose limits | Preserving recorded results while identifying different starting squads is preferable to silently rewriting history | `reports\v146\human_benchmark_report.md`, provenance verifier |

These strengths justify **refactoring around the engine**, not replacing every
algorithm or deleting legacy research versions.

Production strategic squad construction explicitly describes feasible seeding,
1-opt and 2-opt heuristics (`strategic_squad.py:729` onward). It should not be
marketed as a proven global MIP optimum. A useful heuristic, a pruned search and
an exact bounded reference are different guarantees; preserve and label each.

## 5. Confirmed or Source-Supported Correctness Findings

Priority is for V1.4.7 planning. A source-level defect does not imply a measured
season-total impact; no such impact is invented here.

### 5.1 Data, money and state

| ID | Priority | Finding and evidence | Required outcome |
|---|---|---|---|
| F01 | High | DGW rows overwrite rather than aggregate in `historical\snapshots.py:483-500`. Public 2023-24 GW34 Mateta rows contain **16 + 13 = 29 points**, **67 + 90 = 157 minutes**; the loader retains the latter fixture only. | Fixture-row and player-GW contracts; additive aggregation, correct minutes/participation, row-order invariance |
| F02 | High | Decision Logger can accept unaffordable transfers, write a negative computed bank, then persist `max(0, new_bank)` instead of rejecting: `decision_log.py:808-919`. | One authoritative affordability/accounting command; no mutation on insufficient funds |
| F03 | High | Logger/reconciliation sale formulas ignore price falls: `decision_log.py:513-517,775-784,848-857`; purchase 65/current 60 yields 65 instead of canonical 60. | Use `selling_price()` consistently; exact conservation across entry points |
| F04 | High | State may be written or a decision deleted before later validation/completion: `decision_log.py:1005-1016,1234-1268`. Separate files and SQL can diverge. | Validate a full transition before commit; durable rollback/recovery and revision checks |
| F05 | Medium | A team-list read can advance GW19 to GW20 without renewing chips; later renewal depends on the old GW still being <=19: `teams.py:242-253,284-290`, `decision_log.py:862-866,1204-1207`. | Explicit, idempotent advance-GW command; queries do not perform hidden lifecycle transitions |
| F06 | Medium | Recommendation capture omits the decision's squad path and sometimes GW, allowing default-team recommendations in another team's audit: `decision_log.py:134-146`. | Calculate from an explicit immutable decision context, without report-export side effects |
| F07 | Medium | Registry cache publishes the new path before parsing succeeds, potentially returning A's old registry for invalid B on retry: `historical\snapshots.py:89-103`. | Publish validated key/value together; valid-A -> invalid-B -> retry-B remains a failure |
| F08 | Medium | Dataset validation checks GW file existence but not usable JSON/schema or required teams/fixtures, and can discard generic registry errors: `historical\validation.py:176-207`. | Distinguish availability, schema validity, referential integrity and as-of provenance |

F01 is particularly important: a self-consistent gross-minus-hits report can
still be wrong if the underlying outcome loader lost a fixture. It can affect
captain multipliers, autosubs and baseline comparisons, not only displayed points.

### 5.2 Search, prediction and evaluation

| ID | Priority | Finding and evidence | Required outcome |
|---|---|---|---|
| F09 | High | Transfer pruning's optimistic bound omits the dead-capital bonus: `optimizer.py:254-256,290-299,373-382`. A candidate can be pruned using a bound lower than its achievable final score. | Bound dominates the actual objective; small exhaustive-oracle tests including bonuses |
| F10 | High | Multi-GW projection dispatch does not consistently preserve predictor semantics; component calculation and participation branches can fall back to another version: `expected_points.py:1013-1082`. | One explicit predictor contract across single-GW and horizon projections |
| F11 | High | Forward GBDT reconstruction reads `predictor_version` metadata while the registry emits `model_version`, allowing canonical fallback: `backtest\decision_engine.py:1347-1351`. Metadata-based reconstruction can also fall back and relabel another predictor: `model_registry.py:266-283`. | Preserve the executable predictor identity; reject unsupported or inconsistent metadata |
| F12 | High | Replay sale-price formulas also ignore falls: `backtest\engine.py:561-568,623-628`, `backtest\decision_engine.py:1901-1906`. | Canonical selling-price behavior or an explicitly versioned legacy execution record |
| F13 | High | Regret decomposition clamps components and replaces the total, obscuring the stated identity: `backtest\optimizer_ablation.py:549-558`. Its action universe is also a truncated one-transfer shortlist. | Keep the measured total immutable, preserve signed algebra, and distinguish a shortlist from an independent exhaustive oracle |
| F14 | Medium | Live chip scheduling can select candidates marked blocked: `chip_strategy.py:663-694`. | The returned schedule satisfies its own guardrails; explain when no permissible date exists |
| F15 | Medium | Live and historical planner GW1 FT advancement differ: `planner.py:254,662-665`. | Shared execution-rule transition tests; preseason never grants an extra GW2 FT |

These findings qualify the idea that the engine is already finished. Much of its
structure is worth retaining, but objective consistency, predictor identity and
truthful evaluation need stronger contracts.

Bounded verification examples:

- The transfer solver returned score **22** while its independent exact
  reference returned **37** on the same legal small instance. This is
  inadmissible pruning inside the retained pool, not only a critique of
  deliberately limited candidate breadth.
- Identical inputs produced **2.99** single-GW V0.9 xP versus **3.07** for a
  one-GW multi-GW V0.9 profile. Multi-GW V1.3 followed the V0.8 path in the probe.
- A `model_version=v1.3.0` identity dispatched V1.0.1 for forward forecasting
  and V1.0 for metadata-only reconstruction. These probes captured dispatch;
  they did not deserialize model artifacts.
- Tracked regret examples B3/GW20 and B3/GW30 have hindsight-minus-selected
  differences **2** and **26**, but reported total regret **40** and **53**:
  `reports\v135\regret_analysis.csv:12,18`. An identity repaired by overwriting
  its measured total is not an independent quality assessment.
- A guarded early-Wildcard opportunity with immediate EV 2 and utility -16 was
  still scheduled live. Eligibility must be explicit; negative utility and
  ineligibility are not interchangeable concepts.

These are controlled mechanics and recorded inconsistencies, **not estimates of
season uplift after a fix**. Corrections can change trajectories and require
separately identified research runs.

### Research compatibility

Correcting outcome aggregation, execution rules or sale proceeds may change
historical totals. Preserve published trials as recorded artifacts; do not
silently rewrite them or present corrected reruns as the same experiment.

Future runs should record code/data digests, predictor and feature versions,
strategy configuration, execution/scoring rules, initial states, and any fallback.
The GUI's latest-engine policy must not redefine a saved frozen trial.

## 6. GUI and UX Assessment

### What works

The application has a useful task inventory, a common top-level navigation, a
recognizable pitch metaphor, ranked recommendations, user-controlled risk and
horizons, and explicit separation of manual trading into Decision Logger.
The CSS already has reusable classes and custom properties.

Historical's two live-only tab exclusions are correct. More similar presentation
should come from shared components and read models, not exposing inappropriate
live-data or LLM workflows.

### Why the GUI has been fragile

1. **Several responsibilities share one file.** Data loading, navigation,
   formatting, HTML construction, state transitions and action handlers live
   together in almost 7,000 JavaScript lines.
2. **Context is a protocol each handler must remember.** The new context epochs,
   request sequences and mutation guards are useful fixes, but their correctness
   depends on applying the same discipline at every asynchronous boundary.
3. **UI state can outlive its data.** Selected IDs, candidate objects, sessions,
   player pools and old callbacks can have different lifetimes.
4. **Lifecycle and styling are intertwined.** Hundreds of inline style fragments
   make consistent redesign, accessibility and state presentation harder.
5. **The adapter contains domain rules.** The HTTP handler performs budget,
   lineup, provenance and persistence orchestration rather than simply adapting
   typed application commands.
6. **Important conceptual states are easy to confuse.** Pending versus committed
   transfers, market versus sale value, base versus remaining FT, and forecast
   versus realized points need explicit read models and labels.
7. **Some controls overstate actual choice.** Baseline
   `index.html:526-533` exposes a Strategic Studio engine selector without a
   corresponding engine-selection binding in the client request path. The
   V1.4.7 cleanup removes this misleading control rather than pretending it
   selected a different algorithm.

Representative source evidence:

- Global state and context helpers: `gui\static\app.js:3-42`.
- Separate live/historical wrappers and lifecycle orchestration:
  `gui\static\app.js:105-230`.
- Large rendering functions and inline card templates:
  `gui\static\app.js:982` onward.
- File/SQL snapshot and compensating rollback logic:
  `gui\server.py:2110-2284`.

This is not evidence that a browser interface is inherently unsuitable. A
well-layered web client could also work. PyQt6 is a product/platform choice whose
benefits depend on fixing the same boundaries.

### UX priorities

- One shared shell and visual language for the eight common workflows.
- A persistent, unmistakable team/session/season/deadline/as-of context header.
- Distinct pending/executed/committed states and authoritative money/FT readouts.
- Clear empty, loading, cancelled, stale and failed states.
- Latest decision engine managed internally; research identifiers are provenance,
  not everyday form controls.
- Preserve LLM provider/model choice in the live-only advisory workspace.
- Keyboard navigation, focus recovery, scalable layouts and high-DPI testing.
- Validate the proposed layouts with actual users; code inspection cannot prove
  a design is pleasant or efficient.

## 7. Engineering and Operational Debt

### Application and persistence boundaries

Use explicit Live/Historical contexts, immutable query results, revisioned
commands and a shared unit of work. Separate calculation from report export.
Do not move today's handler methods unchanged into Qt button callbacks.

### Error visibility and observability

The 127 broad source handlers and 46 pass-only examples are audit targets, not
46 automatically confirmed failures. Prioritize persistence, migration,
prediction fallback and registry paths. A failed operation must not look like
success or silently substitute another model/dataset.

Introduce structured operation/context identifiers, actionable domain errors,
and diagnostic logs without secrets or private notes. Qt should display the
same errors that CLI and HTTP adapters receive.

### Test architecture

- Keep the successful stateful regressions and grow an invariant matrix.
- Add exhaustive small-instance comparisons for pruning/search correctness.
- Test repeated reads, schema upgrades, concurrent commands and injected
  failures, not only successful requests and counts.
- Canonicalize package imports: four test modules use `src.fpl_manager` while
  production uses `fpl_manager`. Different module identities can make mocks or
  class/singleton assumptions unreliable.
- Add installed-package and clean-machine tests; editable checkout tests are
  not desktop packaging tests.
- Preserve deterministic delayed-response/controller tests. They are useful,
  but not a real browser or real Qt widget test.

### CI and release process

The baseline matrix covers Python 3.11-3.13 on Ubuntu. It does not establish
Windows packaging, native widget behavior, or a complete visual/accessibility
acceptance result. The branch allow-list also needs release hygiene: `v147` is
added now so this branch receives push CI, rather than relying on a later PR.

Version assertions should test actual compatibility/provenance contracts rather
than continually appending release numbers to unrelated frozen-model tests.
Keep design goals, completed code, measured checks and manual acceptance distinct.

### Distribution and trust boundaries

- `gui\server.py:84-86` assumes a repository-relative writable database/config.
  A frozen desktop app needs explicit resource and per-user data locations.
- The default loopback host is positive; wildcard CORS is visible at
  `gui\server.py:107,131`. Before broader distribution, review whether the HTTP
  service remains necessary and how its access boundary is constrained.
- Treat credentials separately from preferences; do not put API keys into plain
  `QSettings` merely because the UI is native.
- Dataset/model provenance, backups, retention and clean-machine recovery need
  release acceptance criteria.
- A dedicated security review remains a separate pre-distribution gate; this
  assessment is not a security certification.

## 8. Recommended V1.4.7 Priorities

1. **Correct money and historical outcomes first:** F01-F04 and F12.
2. **Make model and objective selection explicit:** F09-F11 and F13-F15.
3. **Extract application services and context/revision contracts:** cover all
   mutation paths, not just whichever button last failed.
4. **Harden data admission and lifecycle transitions:** F05-F08.
5. **Characterize the shared GUI workflows and error states.**
6. **Approve a native design, licensing route and worker/packaging spike.**
7. **Only then implement the staged Qt port**, retaining the web client until
   parity and clean-machine acceptance pass.

Do not combine all of these into another giant feature PR with a final test-count
claim. Use small vertical slices, independent validators, ownership-safe parallel
work, and explicit acceptance evidence.

## 9. Overall Conclusion

The strongest asset is the accumulated FPL domain knowledge and reusable Python
calculation machinery. The largest liability is inconsistent authority over
state, rules and context at integration boundaries.

A GUI rewrite alone would be a cosmetic success with the same failure modes.
A boundary-first V1.4.7 followed by a gated native client can improve both
reliability and presentation without abandoning the engine investment.
