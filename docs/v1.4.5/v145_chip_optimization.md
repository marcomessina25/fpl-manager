# V1.4.5 — Multi-Season Strategic Chip Optimization Study & Engine Unification

**Status:** Planned (next release after V1.4)  
**Predecessor:** V1.4 — Interactive Historical Season Simulation & Time Machine Sandbox Platform  
**Successor:** V1.4.6 — Empirical Human-in-the-Loop Replay Benchmark  
**Corpus / Repo:** `marcomessina25/fpl-manager`  
**Operating mode:** This document is the working implementation plan for the AI agent assigned to V1.4.5.

---

## 1. Executive Summary & Problem Formulation

In FPL, chips are the highest-leverage discrete interventions available across a 38-gameweek season:
- **Wildcard (x2)**: complete 15-player squad restructuring without transfer hits, with one use in GW1–19 and one use in GW20–38.
- **Free Hit**: a temporary one-gameweek squad reset, restoring the original squad after the deadline.
- **Triple Captain**: triples captain points rather than doubling them.
- **Bench Boost**: scores all 15 players, including the 4 bench players.

The current system has a structural issue: chip decisions are driven by brittle fixed thresholds and policy fragments that are not unified across the live advisor and historical simulation pipelines. The result is a mix of premature burns, chip hoarding, and schedule-blind decision paths. V1.4.5 solves this by replacing hard-coded gates with a single opportunity-cost and expected-value framework, validated through a rigorous 5-season empirical study.

### Structural Failures in Existing Implementations

1. **Fixed Threshold & Static Gate Pathology**
   - The live advisory heuristics in `src/fpl_manager/chip_strategy.py` and the historical policy in `SeasonalChipPolicy` currently rely on static thresholds such as `squad_deficit >= 12.0` or early-gameweek xP heuristics.
   - These thresholds are not aligned with the true value of preserving future optionality. They cause:
     - **Premature burns**: a superficial short-term fixture bump can trigger a Free Hit immediately after a Wildcard or right after GW1, wasting large future potential.
     - **Chip hoarding**: if a threshold is narrowly missed each week, the engine can hold chips across multiple gameweeks even when the remaining window has clear high-value opportunities.
     - **Half-season expiry blindness**: due to segment boundaries, a chip is treated as a local threshold problem rather than a global best-use-of-window problem.

2. **Disconnected Pipeline Divergence**
   - The GUI chip strategy visualizer does not operate from the same valuation logic as the historical simulation engine, producing contradictory roadmaps for the same underlying season state.
   - This undermines trust and makes reproducing chip recommendations impossible across sessions.

3. **Ignoring Fixture Topography**
   - The system does not consistently reason about blank and double topography in the second half of the season.
   - In GW20–38, FA Cup postponements and fixture congestion can radically reshape chip value, but static thresholds are too blunt to incorporate this option value correctly.

4. **No Single Optimizer Contract**
   - There is no canonical engine that both live recommendations and historical backtests call into.
   - The absence of a common chip optimizer prevents reproducibility, porting across APIs, and controlled benchmarks.

---

## 2. Implementation Goal

V1.4.5 replaces ad hoc chip gating with a formal expected-value and opportunity-cost optimizer that is:
- unified across GUI and historical simulator paths,
- aware of the remaining gameweek window and segment boundaries,
- sensitive to blank and double gameweek structure,
- benchmarked over all five historical seasons,
- designed to be auditable and reproducible.

The final delivery is not just a better heuristic. It is a single versioned chip engine which is frozen and used as the official baseline for the follow-up V1.4.6 human benchmark.

---

## 3. Scientific Architecture

### 3.1 Dynamic Opportunity Cost Model

For each chip candidate `C` at gameweek `t`, the optimizer computes the tradeoff between immediate value and future optionality.

The base decision function is:

$$
\text{Net Utility}(C, t) = \Delta \text{EV}(C, t) - \max_{t' \in [t+1, T_{\text{window}}]} \mathbb{E}[\Delta \text{EV}(C, t')]
$$

Where:
- `ΔEV(C, t)` is the immediate expected-value benefit of using chip `C` in the current gameweek.
- `max_{t' > t}` estimates the best remaining value of holding the chip for a later opportunity in the same segment.
- `T_window` is the segment boundary: GW19 for the first half of the season and GW38 for the second half.

This formalizes the correct rule: do not deploy a chip only because the immediate local delta looks strong; deploy it only when the immediate gain outweighs the value of holding that chip for the best remaining opportunity.

### 3.2 Natural Terminal Window Decay

The optimizer will explicitly encode the fact that the value of preserving a chip decays as the segment window approaches its end.

$$
\lim_{t \to T_{\text{window}}} \max_{t' > t} \mathbb{E}[\Delta \text{EV}(C, t')] = 0
$$

This ensures the decision engine naturally prefers deployment on the highest-value remaining fixture cluster rather than hoarding until expiry.

Important consequence:
- The optimizer does not require hard-coded threshold values to decide when to use a chip.
- Instead, threshold behavior emerges from the opportunity-cost comparison itself.

### 3.3 Free Hit Valuation Model

The optimizer will compare:
- the expected points of the current squad under the upcoming fixture run,
- versus the expected points of the best temporary 15-player lineup under the same fixture run,
- while respecting the fact that the current squad may have been recently optimized by Wildcard or may be relatively stable at season start.

This means Free Hit value is not a simple "low active-player count" trigger. It is an expected-value comparison between current squad state and the best short-term temporary optimization.

### 3.4 Blank & Double Gameweek Awareness

In GW20–38, fixture congestion is a dominant factor. The optimizer will treat BGW/DGW topology as a first-class input:
- detect not just the existence of multiple fixtures but their concentration in the same gameweek,
- identify which players are likely to benefit from DGW exposure,
- evaluate whether a Triple Captain or Bench Boost is more valuable than preserving the chip for a later double or blank.

This also allows the engine to reason about the edge case where a blank gameweek emerges after a recent wildcard or fixture spike, which the current threshold model mishandles.

### 3.5 Surrogate-Value / ML Exploration

The optimizer can explore a ML-assisted policy in parallel with a full dynamic-programming planner:
- a compact tabular surrogate that estimates the downstream value of keeping a chip in reserve,
- or a small model that predicts near-term chip ROI using player xP, expected minutes, fixture congestion, and chip inventory state.

This is explicitly a second-stage exploration path, not the sole source of truth. The first successful implementation should be the deterministic dynamic planner; ML is optional and only promoted if it is robust and reproducible.

---

## 4. Engineering Scope

### 4.1 Unified Chip Optimizer Engine

New file:
- `src/fpl_manager/simulation/chip_optimizer.py`

Responsible for:
- evaluating all available chip choices,
- calculating immediate EV, future opportunity cost, and net utility,
- selecting the optimal chip according to the current state,
- exposing a common API for GUI and historical engine integration.

### 4.2 Live & Historical API Reconciliation

The live advisory endpoint and historical simulation endpoint should share the same optimizer logic.

Files and endpoints involved:
- `src/fpl_manager/chip_strategy.py` — current live heuristic implementation
- `src/fpl_manager/simulation/` — historical simulation engine
- `/api/chips`
- `/api/historical/simulations/<id>/chips`

The goal is parity:
- same optimizer version,
- same valuation logic,
- same set of guardrails,
- same chip recommendation semantics for matched input states.

### 4.3 Fixture Topography Enhancements

The optimizer requires richer schedule context than a simple fixture count. Planned improvements include:
- canonical BGW/DGW season map,
- asset multiplicity by gameweek,
- double-gameweek exposure scoring,
- blank-gameweek player vulnerability checks,
- schedule-aware utility curves for Triple Captain and Bench Boost.

Planned location:
- `src/fpl_manager/fixtures.py`
- helper logic in the chip optimizer module

---

## 5. Detailed Implementation Plan

This section is the working task breakdown for the AI agent.

### Phase 1 — Diagnosis and Baseline Characterization

Objective: record the exact failure modes of the current policy before replacing it.

Tasks:
1. Run the existing `SeasonalChipPolicy` across all five historical seasons (`2021-22` to `2025-26`).
2. Quantify:
   - chip wastage rate,
   - premature burn rate,
   - unplayed chip rate,
   - missed opportunity rate,
   - policy divergence between live and simulation pipelines.
3. Output a baseline report under `reports/v145/`.
4. Capture baseline chip schedules and compare them against known fixture topography.

Deliverables:
- `reports/v145/v145_baseline_pathology_report.md`
- `reports/v145/v145_pipeline_divergence_audit.md`
- raw CSV/JSON ledger of per-gameweek policy decisions

Acceptance criteria:
- each chip decision is traceable to a specific gameweek, state, and expected value estimate,
- the report identifies the historical failure modes without ambiguity.

### Phase 2 — Unified State and Data Model Design

Objective: define the single chip optimization contract.

Tasks:
1. Formalize a state object containing:
   - squad IDs,
   - active chips remaining,
   - current gameweek,
   - remaining segment window,
   - recent chip history,
   - fixture topology for upcoming gameweeks,
   - budget and player projections.
2. Create a `ChipOpportunityValue` dataclass with:
   - chip name,
   - gameweek,
   - immediate EV,
   - future maximum EV,
   - net utility,
   - confidence,
   - rationale.
3. Define the common optimizer interface used by all system entry points.

Files to touch:
- `src/fpl_manager/simulation/chip_optimizer.py`
- `src/fpl_manager/chip_strategy.py`
- any relevant simulation session model or result schema

Acceptance criteria:
- GUI and historical simulation share the same public optimizer interface,
- all recommendation output includes metadata usable for audit and reporting.

### Phase 3 — Core Optimizer Implementation

Objective: replace the threshold-based policy with a deterministic planning engine.

Implementation workstreams:

1. **Immediate EV Computation**
   - Evaluate `wildcard`, `free_hit`, `bench_boost`, `triple_captain` for the current gameweek.
   - Compute the immediate value of deployment using projected xP and the best available lineup state.

2. **Future Opportunity Computation**
   - For each chip, scan the remaining gameweeks in the segment.
   - Estimate the best future value of holding the chip instead of deploying it now.

3. **Net Utility Calculation**
   - Subtract the future opportunity from the immediate benefit.
   - Then apply the segment-window decay and decision confidence weighting.

4. **Selection Policy**
   - If net utility is positive and the chip is still available,
     deploy it;
   - otherwise keep it in reserve.

5. **Guardrails**
   - preserve anti-pathology constraints such as:
     - no immediate Free Hit after a recent Wildcard or season start unless the case is genuinely strong,
     - no chip deployed in a totally invalid fixture state,
     - no cross-half-season leakage of chip timing or window logic,
     - no deployment in impossible gameweeks or invalid chip inventory states.

Implementation target:
- `src/fpl_manager/simulation/chip_optimizer.py`

Acceptance criteria:
- the optimizer is deterministic for the same gameweek and state,
- no chip can be recommended in an invalid inventory state,
- the optimizer exposes enough structured metadata for reproducible reasoning.

### Phase 4 — Ablation Study and Model Comparison

Objective: compare the unified optimizer against control variants and select the winning policy.

The study should cover these variants:

- **Baseline C0**: current heuristic `SeasonalChipPolicy`
- **Variant C1**: linear window-decay heuristic
- **Variant C2**: full dynamic-programming EV opportunity-cost planner
- **Variant C3**: surrogate-value / ML-assisted chip policy

Evaluation dimensions:
- 5-season mean Track B total points,
- chip return surplus (`Track B - Track A`),
- premature burn rate,
- wastage rate,
- variance across seasons,
- API parity and simulation parity,
- holdout or cross-season robustness for ML-based variants.

Tasks:
1. Build a parameterized benchmark harness that runs each variant for every season.
2. Log every chip deployment with its immediate EV and future opportunity estimate.
3. Store the benchmark results in `reports/v145/`.
4. Produce an ablation summary that clearly identifies the best-performing variant.

Deliverables:
- `reports/v145/ablation_summary.md`
- `reports/v145/seasonal_results/<season>.json`
- `reports/v145/performance_leaderboard.md`

Acceptance criteria:
- every variant is run on the same input data,
- the benchmark report is reproducible from source,
- the optimal variant is objectively selected by the metrics rather than by narrative preference.

### Phase 5 — API Unification and GUI Parity

Objective: ensure the user-facing strategy engine matches the simulation engine.

Tasks:
1. Replace or wrap the live chip recommendation logic so it calls the same optimizer engine as historical mode.
2. Ensure the recommendation payload includes metadata for:
   - chip name,
   - immediate EV,
   - future opportunity,
   - current segment,
   - confidence,
   - explanation text.
3. Ensure consistent output shape on:
   - `/api/chips`
   - `/api/historical/simulations/<id>/chips`
4. Run parity checks where identical states produce identical recommendation metadata and ranking order.

Files likely involved:
- `src/fpl_manager/chip_strategy.py`
- API route definitions
- GUI rendering / strategy presentation layer

Acceptance criteria:
- no divergence between GUI recommendation and simulation replay for the same input state,
- API output is versioned and auditable.

### Phase 6 — Validation, Regression Coverage, and Hardening

Objective: lock the optimizer down with deterministic tests and anti-pathology safeguards.

Tasks:
1. Add unit tests for immediate EV calculations and decision selection.
2. Add tests covering:
   - invalid chip inventory states,
   - segment boundaries,
   - no premature burns after Wildcard or GW1,
   - no invalid campaign-level decisions near expiry,
   - deterministic ordering of recommended chips,
   - near-identical states produce near-identical outputs.
3. Add integration tests for simulation sessions and historical snapshots.
4. Validate all pathologies discovered in baseline diagnostics are eliminated or reduced materially.

Files to touch:
- `tests/test_chip_strategy.py`
- `tests/test_chip_optimizer.py` (new)
- existing historical simulation tests if necessary

Acceptance criteria:
- unit and integration tests pass,
- optimizer behavior is deterministic,
- known pathologies are explicitly covered and prevented.

### Phase 7 — Documentation and Final Freeze for V1.4.6

Objective: prepare a frozen baseline for the next milestone.

Tasks:
1. Update this document with the final architecture, decisions, and benchmark findings.
2. Freeze the chip optimizer version used in V1.4.5.
3. Document limitations and any known assumptions.
4. Prepare the V1.4.6 benchmark specification against the V1.4.5 engine as a fixed baseline.

Files to touch:
- `docs/v1.4.5/v145_chip_optimization.md`
- any roadmap or milestone docs referencing V1.4.5 / V1.4.6

Acceptance criteria:
- the next human benchmark is run against a clearly defined and stable chip baseline,
- the final plan and findings are sufficiently audit-friendly for future comparison.

---

## 6. Detailed Workstreams by File

### `src/fpl_manager/chip_strategy.py`
- replace/adapt static thresholds with optimizer call path,
- preserve the public CLI-facing strategy output,
- surface the opportunity-cost explanation text for users,
- maintain compatibility with existing `fpl chip-strategy` behavior during migration.

### `src/fpl_manager/simulation/chip_optimizer.py`
- core engine,
- per-chip immediate EV,
- future opportunity scan,
- segment-aware decision logic,
- metadata serialization for audit logs.

### `src/fpl_manager/fixtures.py`
- BGW/DGW detection and fixture topology scoring,
- fixture concentration analysis,
- mapping of players to profitable DGW opportunities.

### `reports/v145/`
- all empirical study outputs,
- baseline audit,
- final benchmark report,
- summary charts and interpretation.

### `tests/`
- deterministic verification of optimizer behavior,
- regression coverage for edge cases and anti-pathology rules.

---

## 7. Evaluation Metrics

The V1.4.5 study should explicitly track the following metrics:

- 5-season mean total points with chips active (Track B)
- chip return surplus (`Track B - Track A`)
- wasted chip rate (% of simulations finishing with unplayed chips)
- premature burn rate (% of Free Hits used within two gameweeks of Wildcard or GW1)
- opportunity-cost regret (% of decisions where the chip was used too early relative to best remaining opportunity)
- parity of recommendations between GUI and simulation engine
- robustness of the engine across seasons and schedule shocks

The KPI target is not simply “more points.” The real target is:
- fewer wasted chips,
- fewer deterministic policy errors,
- better dynamic use of future fixture structure,
- consistent recommendations between interfaces.

---

## 8. Deliverables

Planned final outputs for V1.4.5:

- `src/fpl_manager/simulation/chip_optimizer.py`: unified chip optimization engine
- reconciled chip recommendation logic across live and historical paths
- fixture-aware BGW/DGW valuation support
- 5-season benchmark results in `reports/v145/`
- full baseline comparison against the legacy `SeasonalChipPolicy`
- final freeze of the winning chip policy for the V1.4.6 human benchmark

---

## 9. AI Agent Execution Notes

This document is intended to be used as the operational brief for the coding agent implementing V1.4.5.

The agent should favor the following principles:
- optimize for correctness and reproducibility, not local heuristic tweaks,
- keep the optimizer deterministic and explainable,
- prefer a single versioned engine over parallel fragmented policies,
- measure success with benchmark metrics, not just subjective “better-looking” recommendations,
- treat GUI parity as a core requirement, not an afterthought.

The implementation should be incremental and auditable:
1. diagnose current pathologies,
2. implement the engine,
3. validate it over all seasons,
4. unify live and historical entry points,
5. freeze the result for V1.4.6.

---

## 10. Success Criteria for V1.4.5

V1.4.5 is complete when all of the following are true:
- the system no longer relies on hard-coded threshold gates as the primary decision mechanism,
- a single optimizer is used by both GUI and simulation paths,
- the engine is mathematically coherent under segment window decay,
- multi-season empirical benchmarking shows a clear reduction in chip waste and premature burns,
- the resulting engine is accepted as the fixed baseline for V1.4.6 human-in-the-loop replay studies.

This milestone should be judged not by the presence of a clever heuristic, but by the elimination of chip pathologies and the delivery of a reproducible, unified strategic baseline.
