# FPL Manager Roadmap

> Living document. This is the source of truth for delivery status, engineering priorities, release criteria, known risks, and long-term direction. Human contributors and AI agents must read it before material work and update it when priorities or milestone status changes.

**Current baseline:** V1.0.0 is the current release target, with V1.0 release hardening completed on `version_10` / PR #12 work. V1.1 is the next major milestone and is deliberately centered on **strategic squad construction, full GUI integration, and end-to-end ML analysis**. The previously planned multi-provider / extended-LLM work moves to V1.2.

---

# 0. Executive Roadmap

FPL Manager is evolving from a deterministic FPL calculation engine into a complete **decision-support, strategic squad-construction, and experimentation platform**.

The long-term system should answer:

- What should I do this Gameweek?
- What are the best legal alternatives?
- How much expected value does each action provide?
- What is the risk of each action?
- How does ownership / Effective Ownership affect rank exposure?
- What is the best multi-Gameweek strategy?
- What squad should I start the season with?
- What squad should I construct when using a Wildcard?
- How do my own preferences and constraints change the optimal strategic candidates?
- What happens if I lock a player the optimizer did not initially select?
- Which strategic starting states produce better downstream decisions?
- How did the recommendation perform?
- Was the model better than the human decision?
- Which parts of the model are systematically wrong?
- Does a better starting squad improve the entire downstream decision process?
- Can historical evidence be used to improve the next version?

The core design principle remains:

```text
Official FPL data
        ↓
Local point-in-time snapshots
        ↓
Deterministic rules / state
        ↓
Quantitative projections
        ↓
Strategic squad construction
        ↓
Optimizers / planners
        ↓
Strategic risk & ownership analysis
        ↓
Structured manager dossier
        ↓
Optional LLM qualitative analysis
        ↓
Deterministic validation
        ↓
Human decision
        ↓
Decision log
        ↓
Actual outcome
        ↓
Evaluation / backtesting
        ↓
Model / strategy improvement
```

---

# 1. Release Sequence

```text
V0.1
Trustworthy FPL data and rules
        ↓
V0.2
Decision-support basics
        ↓
V0.3
Projections and optimization
        ↓
V0.4
Evaluation, research and strategic risk
        ↓
V0.5
GUI and multi-team management
        ↓
V0.6
Analytical briefing, live matchday, optional LLM
        ↓
V0.65
Stabilization and release hardening
        ↓
V0.7
Historical backtesting and predictive validation
        ↓
V0.8
Participation, rank-aware decisions and football context
        ↓
V0.9
Learned participation model, closed-loop evaluation and hardening
        ↓
V1.0
Stable, reproducible decision-support platform
        ↓
V1.1
Strategic squad construction
+ Full GUI integration
+ Full ML / end-to-end evaluation
        ↓
V1.2
Multi-provider expansion
+ Extended LLM model research
+ Human-in-the-loop AI experimentation
        ↓
Future
Automated learning loops
+ richer scenario planning
+ deeper strategic modelling
```

---

# 2. Release Status

| Version | Scope | Status |
|---|---|---|
| V0.1 | Data/rules foundation | Released |
| V0.2 | Decision-support basics | Released |
| V0.3 | Projections and optimization | Released |
| V0.4 | Evaluation/research/risk | Released |
| V0.5 | GUI/multi-team | Released |
| V0.6 | Briefing/live/LLM | Released through subsequent stabilization |
| V0.65 | Stabilization | Completed through later hardening |
| V0.7 | Historical prediction/backtesting | Completed |
| V0.8 | Participation/rank/context | Completed |
| V0.9 | Learned participation/closed-loop/hardening | Completed |
| V1.0 | Stable production platform | Release candidate / PR-ready |
| **V1.1** | **Strategic squad + GUI + full ML analysis** | **Next major milestone** |
| V1.2 | Multi-provider + extended LLM research | Planned |
| Future | Automated learning / advanced strategy | Research |

---

# 3. V0.1–V0.9 Historical Record

The V0.x roadmap established the foundations for V1.0.

## V0.1 — Trustworthy FPL data and rules foundation

**Status: completed.**

Delivered:

- official FPL `bootstrap-static` and `fixtures` ingestion;
- timestamped raw payloads;
- local SQLite snapshots;
- player representation;
- 15-player squad validation;
- legal starting-XI validation;
- formation validation;
- deterministic transfer validation;
- machine-readable reports;
- private squad configuration;
- SQLite persistence tests;
- squad import.

---

## V0.2 — Decision-support basics

**Status: completed.**

Delivered:

- detailed squad reporting;
- prices;
- team breakdown;
- bank/team value;
- free transfers;
- chips;
- fixture analysis;
- FDR;
- fixture ticker;
- legal transfer candidate generation;
- 1–3 transfer recommendations;
- xP baseline;
- availability adjustment;
- starting-XI optimizer;
- captain/vice-captain;
- bench ordering;
- JSON reports.

---

## V0.3 — Projections and optimization

**Status: completed.**

Delivered:

- expanded player metrics;
- expected minutes;
- probability of starting;
- 60+ probability;
- substitute probability;
- component-based xP;
- floor/ceiling/variance;
- risk profiles;
- recursive branch-and-bound transfer search;
- heuristic Wildcard / Free Hit optimizer;
- multi-GW beam-search planner.

Important permanent terminology:

> The production Wildcard / Free Hit optimizer is heuristic/local-search unless a future implementation explicitly proves global optimality.

---

## V0.4 — Evaluation, research and strategic risk

**Status: completed.**

Delivered:

- persistent decision logging;
- point-in-time recommendations;
- human-vs-model divergence;
- actual-points recording;
- live-score ingestion;
- MAE/RMSE/rank correlation;
- captain regret;
- bench regret;
- multi-GW/season aggregation;
- ownership;
- Effective Ownership;
- Shield/Sword/Core concepts;
- chip valuation and scheduling.

---

## V0.5 — GUI and multi-team management

**Status: completed.**

Delivered:

- isolated team workspaces;
- team creation/cloning/switching;
- browser GUI;
- visual pitch;
- player cards;
- FDR/xP/ownership;
- captaincy;
- financial HUD;
- transfer builder;
- transfer recommendations;
- Wildcard/Free Hit studio;
- multi-GW planner;
- chip strategy;
- evaluation hub.

---

## V0.6 — Analytical briefing, live matchday and optional LLM

**Status: completed through subsequent stabilization.**

Delivered:

- manager dossier;
- squad health;
- starting XI;
- captaincy;
- injury/news context;
- ownership risk;
- transfer recommendations;
- live matchday;
- autosub simulation;
- live statistics;
- Effective Ownership leverage;
- LLM advisor;
- multiple personas;
- structured responses;
- deterministic legality guardrails;
- GUI advisor workflow.

Provider integrations remain optional and must never be a prerequisite for core operation.

---

## V0.65 — Stabilization and hardening

**Status: completed through subsequent hardening work.**

The stabilization work established:

- state-transition correctness;
- quantitative xP/xM validation;
- optimizer legality;
- GUI/API safety;
- provider failure handling;
- deterministic guardrails;
- regression tests;
- integration tests;
- secure secret handling.

---

## V0.7 — Historical backtesting and predictive validation

**Status: completed.**

The first serious research release established:

- point-in-time historical snapshots;
- strict no-future-leakage semantics;
- baseline comparisons;
- prediction calibration;
- xP/xM evaluation;
- minutes modelling;
- probabilistic event modelling;
- uncertainty analysis;
- versioned model metadata;
- decision-level backtesting.

---

## V0.8 — Participation, rank-aware decisions and football context

**Status: completed.**

Delivered:

- probabilistic participation engine;
- rotation/congestion features;
- rank-aware risk profiles;
- structured football context;
- provenance/confidence/expiry for external observations;
- LLM strategy critique;
- A/B predictive backtesting.

---

## V0.9 — Learned participation, closed-loop evaluation and hardening

**Status: completed.**

The V0.9 work introduced:

- learned/calibrated temporal participation modelling;
- participation regimes;
- calibration;
- decision-weighted error attribution;
- production hardening;
- security;
- multi-season analysis;
- predictor/decision-engine factorial analysis.

A key finding was that the learned V0.9 predictor improved results materially, while an additional lineup participation penalty interacted negatively with already participation-aware xP.

Subsequent V0.9.1 hardening established a neutral default lineup penalty of zero and validated the choice over multiple seasons.

---

# 4. V1.0 — Stable FPL Decision-Support Platform

**Status: release candidate / PR-ready.**

V1.0 is not intended to contain every future feature.

It establishes a trustworthy quantitative and software foundation for the strategic work in V1.1.

## V1.0 goals

- stable production architecture;
- reproducible historical evaluation;
- frozen quantitative core;
- independent exact reference algorithms for bounded synthetic validation;
- explicit heuristic/exact characterization;
- strict point-in-time semantics;
- model provenance;
- decision provenance;
- regression suite;
- secure provider handling;
- auditable LLM evaluations.

## V1.0 optimizer discipline

Production components must explicitly state:

- algorithm;
- exact/heuristic status;
- optimality guarantee;
- search bounds;
- objective;
- provenance.

Independent exact reference solvers are validation oracles on bounded synthetic problems, not a requirement to brute-force the real FPL search space.

## V1.0 completion standard

V1.0 is successful when the existing platform is:

> stable, reproducible, tested, measurable, and honestly characterized.

---

# 5. V1.1 — Strategic Squad Construction, Full GUI Integration & Full ML Analysis

**Status: planned.**

This is the next major milestone.

V1.1 has exactly three major pillars:

```text
Pillar 1 — ENGINE
Strategic squad construction

Pillar 2 — GUI
Full interactive integration

Pillar 3 — ML
Full end-to-end historical analysis
```

The central product question becomes:

> **Can FPL Manager construct a strategically strong starting state, let the human refine that state through explicit constraints and preferences, and demonstrate through leakage-free historical replay what effect that starting state has on downstream decisions?**

---

## 5.1 Why V1.1 is different from V1.0

The existing engine primarily answers:

> Given my current squad, what should I do next?

V1.1 adds:

> What squad should I start from?

This creates three distinct optimization problems.

### Initial squad

Starting from the season-start budget:

> Construct a squad that is strategically strong over an initial horizon and preserves future flexibility.

### Wildcard

Starting from the current squad:

> Construct a strategically strong new squad over a future horizon.

### Free Hit

Starting from the current squad but with a temporary reset:

> Construct the best one-GW squad under the Free Hit rules.

These should share infrastructure but have different objectives and state semantics.

---

# 6. V1.1 Pillar 1 — Engine

## 6.1 Generalized squad-construction framework

Create a reusable strategic squad optimizer supporting:

- Initial;
- Wildcard;
- Free Hit;
- future strategic squad modes.

Inputs:

- current squad/state;
- budget;
- available players;
- point-in-time projections;
- fixtures;
- horizon;
- strategy;
- constraints;
- preferences.

Outputs:

- multiple candidate squads;
- objective values;
- strategic metrics;
- provenance;
- exact/heuristic status.

---

## 6.2 Hard constraints

Support:

- budget;
- squad size;
- position quotas;
- club limits;
- locked players;
- excluded players;
- chip-specific legality.

Hard constraints must never be silently violated.

---

## 6.3 Soft preferences

Support:

- preferred players;
- preferred clubs;
- preferred positions;
- desired budget reserve;
- fixture preferences;
- future-flexibility preferences;
- differential preference;
- risk preference.

Soft preferences must be represented separately from hard constraints.

---

## 6.4 Multiple strategic candidates

Do not model the result as a single universal `optimal_team`.

Support candidates such as:

- Maximum EV;
- Balanced;
- High Floor;
- High Ceiling;
- Future Flexibility;
- Defend;
- Chase.

Also support multiple near-optimal solutions where the objective is close enough that structural diversity is meaningful.

---

## 6.5 Strategic objective

The strategic objective may include:

```text
expected_points_over_horizon
+ future_transfer_flexibility
+ fixture_value
+ captaincy_option_value
+ bench_value
+ strategy_adjustments
- expected_transfer_cost
- structural_risk
```

The exact formulation must be empirical.

Every component must be:

- measurable;
- backtestable;
- ablatable;
- removable if it does not improve decision quality.

---

## 6.6 Initial squad optimizer

Support configurable horizons such as:

- 1 GW;
- 3 GW;
- 5 GW;
- 6 GW;
- 8 GW.

The important distinction is that the strategic optimizer must not merely maximize GW1 xP.

It should evaluate the value of the state created for future decisions.

---

## 6.7 Wildcard optimizer

The Wildcard optimizer should consider:

- future fixture runs;
- expected points;
- expected minutes;
- future transfers;
- squad structure;
- bench;
- captaincy;
- flexibility;
- strategy/risk;
- current squad state.

It must be genuinely multi-GW rather than a one-GW Free Hit with a different label.

---

## 6.8 Free Hit generalization

Generalize the existing Free Hit optimizer into the shared squad-construction framework.

Example semantics:

```text
Free Hit:
    horizon = 1 GW
    temporary squad

Wildcard:
    horizon = N GWs
    persistent squad

Initial:
    horizon = N GWs
    no prior squad
```

---

## 6.9 Constraint-driven re-optimization

The following must be possible:

```text
Optimizer proposes squad
        ↓
Human locks Haaland
        ↓
Re-optimize
        ↓
Human also locks Donnarumma
        ↓
Re-optimize
        ↓
Human excludes Player X
        ↓
Re-optimize
```

The constraints become part of the optimization problem rather than manual post-processing.

---

## 6.10 Constraint impact analysis

Show:

- previous objective;
- new objective;
- objective delta;
- changed players;
- strategic opportunity cost;
- changes to future flexibility.

Example:

```text
LOCK Haaland

Previous objective: 412.3
New objective:      409.8
Opportunity cost:    -2.5

Changed:
Player A → Player B
Player C → Player D
```

---

# 7. V1.1 Pillar 2 — Full GUI Integration

## 7.1 Strategic Squad Studio

Add first-class GUI workflows:

- Initial Squad;
- Wildcard;
- Free Hit.

They should use the generalized engine.

---

## 7.2 Strategic objective selector

Expose:

- Balanced;
- Maximum EV;
- High Floor;
- High Ceiling;
- Defend;
- Chase;
- Future Flexibility.

The UI must explain what each objective means.

---

## 7.3 Horizon selector

Support:

- 1;
- 3;
- 5;
- 6;
- 8;
- custom Gameweeks.

---

## 7.4 Constraint controls

Support:

### Must Have

Hard lock.

### Must Avoid

Hard exclusion.

### Prefer

Soft preference.

### Structural constraints

Examples:

- club exposure;
- budget reserve;
- premium count;
- bench strength.

---

## 7.5 Candidate comparison

Show multiple candidates side-by-side.

Possible metrics:

| Metric | Candidate A | Candidate B | Candidate C |
|---|---:|---:|---:|
| Horizon xP | | | |
| GW1 xP | | | |
| Future flexibility | | | |
| Bench value | | | |
| Captaincy options | | | |
| Risk | | | |
| Objective | | | |

Do not imply that different strategies have a universal winner.

---

## 7.6 Interactive player controls

Every candidate player should support:

- Lock;
- Unlock;
- Exclude;
- Prefer;
- Remove preference.

Constraint state must be visually obvious.

---

## 7.7 Optimizer ↔ human loop

The intended workflow:

```text
Optimizer proposes
        ↓
Human inspects
        ↓
Human constrains
        ↓
Optimizer re-solves
        ↓
System explains changes
        ↓
Human accepts / iterates
```

This is a core V1.1 product feature.

---

## 7.8 Human-first workflow

The user must also be able to begin with constraints:

```text
Wildcard
Horizon: 6 GWs

Must Have:
    Haaland
    Donnarumma

Strategy:
    Balanced
```

Then request the strategic squad.

---

## 7.9 GUI provenance

Every generated strategic squad should expose:

- historical/current snapshot;
- Gameweek;
- model version;
- optimizer version;
- strategy;
- horizon;
- constraints;
- objective;
- algorithm;
- search configuration;
- exact/heuristic status;
- generation timestamp.

---

## 7.10 Integration with existing GUI

Strategic squad construction must connect to:

- transfer builder;
- `suggest-transfers`;
- Wildcard;
- Free Hit;
- multi-GW planner;
- lineup;
- captaincy;
- decision history;
- evaluation;
- backtesting.

The strategic squad must become a valid downstream starting state, not a disconnected report.

---

# 8. V1.1 Pillar 3 — Full ML Analysis

The ML/research work is intentionally a major pillar, not a small validation step.

The V0.7–V0.9 methodology must be extended to evaluate **starting-state quality**.

---

## 8.1 Historical initial-squad backtest

For every historical season:

1. reconstruct pre-GW1 information;
2. generate predictions using only available information;
3. construct strategic candidate squads;
4. record strategy/objective/constraints;
5. replay forward;
6. run weekly decision-making;
7. record actual outcomes;
8. attribute errors.

---

## 8.2 Historical Wildcard backtest

For historical Wildcard opportunities:

1. reconstruct the squad;
2. reconstruct the point-in-time information state;
3. run the strategic Wildcard optimizer;
4. generate multiple candidates;
5. record objective values;
6. replay future Gameweeks;
7. run the weekly decision engine;
8. compare realized outcomes.

Repeat across multiple seasons and Wildcard contexts.

---

## 8.3 Starting-state baselines

At minimum compare:

### A — Historical/actual squad

Where data is available.

### B — Short-horizon optimizer

Existing one-GW style construction.

### C — V1.1 strategic optimizer

Multi-GW strategic construction.

### D — Alternative strategic profiles

Compare different objectives.

The purpose is characterization and causal decomposition, not declaring one strategy universally best.

---

## 8.4 Extend the V0.7–V0.9 analytical chain

Existing:

```text
features
→ prediction
→ participation state
→ xP / xM
→ optimizer score
→ decision
→ actual outcome
```

V1.1:

```text
historical state
→ strategic squad construction
→ starting state
→ prediction
→ weekly decision
→ actual outcome
```

---

## 8.5 Starting-state quality metrics

Measure:

- horizon xP;
- realized horizon points;
- expected-vs-realized delta;
- squad value;
- bench value;
- captaincy opportunity;
- fixture coverage;
- future transfer flexibility;
- corrective transfers required;
- structural weaknesses.

---

## 8.6 End-to-end decision metrics

### Prediction

- xP MAE;
- xM MAE;
- RMSE;
- rank correlation;
- calibration;
- participation classification.

### Squad construction

- objective;
- realized points;
- regret;
- constraint cost;
- flexibility.

### Weekly decisions

- transfer gain;
- transfer hits;
- lineup regret;
- bench regret;
- captain regret;
- zero-minute starters;
- chip outcomes.

### End-to-end

- cumulative points;
- net points;
- transfer count;
- transfer hits;
- rank trajectory where available;
- strategic regret.

---

## 8.7 Multi-season walk-forward

Do not rely on one season.

For each historical experiment:

```text
historical information
        ↓
point-in-time prediction
        ↓
strategic construction
        ↓
future evaluation
        ↓
advance time
```

Report:

- per-season results;
- aggregate results;
- variance;
- failure cases;
- strategy sensitivity;
- horizon sensitivity.

---

## 8.8 Starting State × Predictor × Decision Engine

Extend the V0.9 factorial methodology.

Potential factors:

- baseline vs strategic starting squad;
- baseline vs V1.0 predictor;
- baseline vs current decision engine;
- strategic profile;
- horizon.

The experiment should decompose:

```text
starting-state main effect
prediction main effect
decision-engine main effect
interaction effects
```

The question is:

> Does strategic squad construction produce a downstream benefit independently of weekly prediction quality?

---

## 8.9 Starting-state error attribution

Add explicit categories:

```text
STARTING_STATE_ERROR
PREDICTION_ERROR
DECISION_ERROR
INTERACTION
HARMLESS
```

Examples:

- structural weakness created by the initial squad;
- player omitted because of incorrect strategic valuation;
- correct player available but predicted incorrectly;
- prediction correct but decision engine selected incorrectly.

---

## 8.10 Strategic regret

Use hindsight only as an evaluation reference.

Conceptually:

```text
Strategic regret =
    hindsight reference outcome
    -
    selected candidate outcome
```

Reports must distinguish:

- decision-time information;
- production candidate;
- hindsight oracle.

The production optimizer must never receive hindsight information.

---

## 8.11 Solution multiplicity

Measure:

- number of optimal solutions where exact;
- near-optimal candidate count;
- objective spread;
- structural diversity;
- common players;
- strategy-specific differences.

This prevents a different but nearly equivalent squad from being incorrectly classified as an optimizer failure.

---

## 8.12 Constraint sensitivity

Run controlled experiments:

```text
baseline
+ lock Haaland
+ lock Donnarumma
+ exclude player X
+ prefer player Y
+ reserve £0.5m
+ change horizon
+ change strategy
```

Measure:

- objective change;
- squad composition change;
- flexibility;
- historical outcome.

---

## 8.13 Horizon sensitivity

Evaluate:

```text
1 GW
3 GW
5 GW
6 GW
8 GW
```

Determine:

- composition changes;
- realized outcome changes;
- future transfer pressure;
- possible overfitting;
- point at which longer-horizon planning becomes useful.

Longer horizon must not be assumed to be better.

---

## 8.14 Strategy sensitivity

Evaluate:

- neutral;
- floor;
- ceiling;
- defend;
- chase;
- flexibility.

Report:

- objective;
- composition;
- downstream outcomes;
- variance;
- robustness.

No universal strategy ranking is required.

---

## 8.15 Full predictive error analysis

Reuse:

- confusion matrices;
- false positives;
- false negatives;
- high-value cohorts;
- error concentration;
- decision-weighted error ledger;
- root-cause analysis.

Add:

- starting-state errors;
- structural errors;
- strategic horizon errors;
- constraint opportunity costs.

---

# 9. V1.1 ML Research Track

V1.1 may test new models in:

## Participation

- NO_PLAY / SUB / START;
- state-specific minutes;
- position-specific distributions;
- manager-specific rotation;
- congestion.

## Expected points

- calibration;
- residual analysis;
- fixture interaction;
- role changes.

## Strategic modelling

- future transfer probability;
- future squad flexibility;
- transfer-cost expectation;
- fixture-swing anticipation;
- captaincy option value.

An experimental model must not replace the production model merely because it improves one predictive metric.

Promotion requires decision-level and walk-forward evidence.

---

# 10. V1.1 Model Promotion Gate

Every production ML change must pass:

1. unit tests;
2. leakage tests;
3. point-in-time validation;
4. out-of-sample prediction evaluation;
5. decision-level backtest;
6. multi-season validation;
7. comparison with V1.0;
8. reproducibility.

A model that improves MAE but does not improve downstream decisions may remain experimental.

---

# 11. V1.1 Required Reports

Generate reproducible reports under:

```text
reports/
    v11/
        initial_squad_backtest/
        wildcard_backtest/
        strategic_profiles/
        horizon_sensitivity/
        constraint_sensitivity/
        starting_state_ablation/
        prediction_decision_ablation/
        error_attribution/
        multi_season_summary/
```

Each report must include:

- dataset;
- snapshot semantics;
- historical window;
- model version;
- optimizer version;
- strategy;
- horizon;
- constraints;
- metrics;
- uncertainty where applicable;
- limitations.

---

# 12. V1.1 Engine Acceptance Criteria

- [ ] Generalized squad-construction interface supports Initial / Wildcard / Free Hit.
- [ ] Strategic horizon is configurable.
- [ ] Multiple strategic candidates can be returned.
- [ ] Hard constraints are deterministic.
- [ ] Locked players are enforced.
- [ ] Excluded players are enforced.
- [ ] Soft preferences are separate from hard constraints.
- [ ] Existing Free Hit behavior remains regression-safe.
- [ ] Wildcard uses a multi-GW strategic objective.
- [ ] Initial selection uses a multi-GW strategic objective.
- [ ] Optimizer metadata exposes algorithm and optimality status.
- [ ] Small synthetic cases have independent exact-reference tests.
- [ ] Constraint changes trigger deterministic re-optimization.
- [ ] Outputs preserve provenance.

---

# 13. V1.1 GUI Acceptance Criteria

- [ ] Initial Squad workflow.
- [ ] Wildcard workflow.
- [ ] Free Hit workflow using generalized engine.
- [ ] Multiple candidate display.
- [ ] Lock player.
- [ ] Unlock player.
- [ ] Exclude player.
- [ ] Prefer player.
- [ ] Horizon selection.
- [ ] Strategy selection.
- [ ] Interactive re-optimization.
- [ ] Changed-player explanation.
- [ ] Objective/opportunity-cost display.
- [ ] Provenance display.
- [ ] Commit candidate into normal decision workflow.
- [ ] Decision history records constraints and optimizer state.

---

# 14. V1.1 ML Acceptance Criteria

- [ ] Historical initial squads reconstructed without future leakage.
- [ ] Historical Wildcards reconstructed without future leakage.
- [ ] Multiple strategic profiles backtested.
- [ ] Multiple horizons evaluated.
- [ ] V0.7–V0.9 predictive metrics retained.
- [ ] Starting-state metrics implemented.
- [ ] Weekly decision metrics implemented.
- [ ] End-to-end season metrics implemented.
- [ ] Multi-season walk-forward evaluation implemented.
- [ ] Starting-state × predictor × decision-engine ablation implemented.
- [ ] Starting-state error attribution implemented.
- [ ] Constraint sensitivity implemented.
- [ ] Strategy sensitivity implemented.
- [ ] Hindsight/oracle results separated from production information.
- [ ] Reproducible reports generated.
- [ ] Production-time candidate generation remains leakage-free.

---

# 15. V1.1 Testing Strategy

Maintain the V1.0 testing standard.

## Unit

Test:

- constraints;
- objectives;
- strategic scoring;
- candidate generation;
- horizon handling;
- state transitions.

## Property/invariant

Examples:

- budget never exceeded;
- position quotas always legal;
- club limits always legal;
- locked players always retained;
- excluded players never selected.

## Integration

Test:

- optimizer → GUI;
- GUI → optimizer;
- optimizer → planner;
- historical snapshot → optimizer;
- optimizer → backtest;
- strategic squad → weekly decision engine.

## Exact-reference

Use small synthetic problems only.

## Leakage

Test that future information cannot enter:

- features;
- predictions;
- strategic scoring;
- squad construction;
- candidate generation.

## Regression

Existing V1.0 workflows must remain stable unless intentionally changed.

---

# 16. V1.1 Performance Requirements

Strategic optimization may be substantially more expensive than one-GW optimization.

Use:

- bounded search;
- caching;
- reusable prediction calculations;
- fixture/horizon caching;
- candidate limits;
- explicit search configuration.

The GUI must remain responsive enough for interactive constraint changes.

Do not attempt unrestricted brute force over the real FPL universe simply to claim exactness.

---

# 17. V1.1 Definition of Done

A complete initial-squad workflow:

```text
START OF SEASON
      ↓
Strategic Initial Squad Optimizer
      ↓
Multiple strategic candidates
      ↓
Human locks / excludes / prefers
      ↓
Re-optimization
      ↓
Final starting squad
      ↓
Weekly decision engine
      ↓
GW-by-GW decisions
      ↓
Evaluation
```

A complete Wildcard workflow:

```text
CURRENT SQUAD
      ↓
Strategic Wildcard Optimizer
      ↓
Multiple strategic candidates
      ↓
Human constraints
      ↓
Re-optimization
      ↓
Final Wildcard Squad
      ↓
Multi-GW planner
      ↓
Evaluation
```

A complete research workflow:

```text
Historical snapshot
      ↓
Strategic squad construction
      ↓
Candidate starting states
      ↓
V1.0 prediction engine
      ↓
Weekly decision engine
      ↓
Actual outcomes
      ↓
V0.7–V0.9 analytical framework
      ↓
Starting-state × prediction × decision analysis
      ↓
Multi-season conclusions
```

---

# 18. V1.1 Success Questions

### Engine

> Can FPL Manager construct strategically meaningful initial and Wildcard squads rather than merely maximizing one Gameweek?

### Product

> Can a human guide that optimization through explicit constraints and preferences without leaving the GUI?

### Science

> Does starting from a strategically constructed squad measurably improve downstream decision quality under strict point-in-time historical evaluation?

The third question is the most important.

V1.1 should not be considered successful merely because the generated squads look more sophisticated.

It succeeds if the end-to-end experiment establishes **where strategic squad construction helps, where it does not, and under which horizons, strategies and constraints the differences matter**.

---

# 19. V1.2 — Multi-Provider Expansion & Extended LLM Model Research

**Status: planned after V1.1.**

V1.2 is the previously planned V1.1 scope, deliberately moved one release later so that the strategic quantitative engine and its evaluation framework exist first.

The central question becomes:

> **Can multiple AI models/providers improve human decision-making when placed around a trustworthy deterministic strategic engine?**

---

## 19.1 Multi-provider infrastructure

Investigate and support, where justified:

- OpenAI;
- Gemini;
- OpenRouter;
- Groq;
- other viable providers;
- local/open models where practical.

Provider support must remain optional.

The core application must work without an external LLM.

---

## 19.2 Provider benchmark

Measure:

- quality;
- consistency;
- latency;
- cost;
- rate limits;
- context handling;
- structured-output reliability;
- failure behavior.

Do not evaluate providers only by subjective response quality.

---

## 19.3 Extended model research

Test multiple model families and sizes.

Questions:

- Which models understand FPL context?
- Which models are best at qualitative tactical analysis?
- Which are best at challenging optimizer assumptions?
- Which are best at explaining trade-offs?
- Which are best at human-facing synthesis?
- Does a larger model materially improve decisions?

---

## 19.4 Human-in-the-loop experimentation

V1.2 should support structured experiments where:

```text
AI agent executes task
        ↓
Human is asked a targeted question
        ↓
Human answers
        ↓
AI continues
        ↓
Result is recorded
```

Human interactions must become part of the experiment record.

The system should distinguish:

- AI-generated decision;
- human constraint;
- human correction;
- final decision;
- outcome.

---

## 19.5 LLM role architecture

Potential roles:

- Strategic Analyst;
- Devil's Advocate;
- Tactical Analyst;
- News Synthesizer;
- Decision Reviewer;
- Post-GW Analyst;
- Research Agent.

The LLM remains subordinate to deterministic rules and quantitative validation.

---

## 19.6 Closed-loop LLM evaluation

Compare:

```text
quantitative only
quantitative + human
quantitative + LLM
quantitative + LLM + human
```

Evaluate actual downstream decision quality.

The goal is not to prove that an LLM is useful.

The goal is to measure whether it is useful.

---

# 20. Long-Term Research Tracks

These remain available after V1.2 and should be promoted into releases only when there is sufficient evidence.

## Track A — Better player modelling

Potential features:

- rolling xG/xA;
- non-penalty xG;
- set-piece xG;
- penalty probability;
- shot volume;
- touches in box;
- big chances;
- progressive actions;
- key passes;
- team attacking strength;
- opponent defensive strength;
- player share of team xG/xA;
- role changes.

Only add a feature if historical testing demonstrates incremental value.

---

## Track B — Better minutes modelling

Potential sources:

- historical lineups;
- substitutions;
- fixture congestion;
- manager rotation;
- injuries;
- suspensions;
- European schedules;
- tactical role;
- recent starts.

Minutes modelling remains a high-value research area.

---

## Track C — Better fixture modelling

Move beyond coarse FDR toward:

```text
team_attack_strength
team_defense_strength
opponent_attack_strength
opponent_defense_strength
home_advantage
```

Derive:

- expected team goals;
- expected goals conceded;
- clean-sheet probability.

---

## Track D — Better rank strategy

Build a benchmark model:

```text
template ownership
benchmark captain
benchmark transfers
```

Then calculate:

- defensive exposure;
- offensive exposure;
- expected rank gain;
- expected rank loss.

---

## Track E — Squad construction

Track E is now promoted into V1.1.

The long-term research direction includes:

- strategic initial squads;
- strategic Wildcards;
- exact mixed-integer optimization if worthwhile;
- future transfer flexibility;
- team structure;
- price-change risk;
- fixture runs;
- bench strength;
- future chip strategy;
- multiple strategic objectives;
- constrained candidate generation.

The objective should be more than one-GW xP.

---

## Track F — Multi-GW planning

Future improvements:

- dynamic re-projection;
- price-change uncertainty;
- injuries;
- future transfer opportunities;
- fixture swings;
- blank/double events;
- chip interactions;
- multiple objectives;
- scenario trees.

---

## Track G — LLM strategy layer

Promoted into V1.2.

Potential roles:

- Devil's Advocate;
- Tactical Analyst;
- Strategic Planner;
- News Synthesizer;
- Decision Reviewer;
- Post-GW Analyst.

The LLM remains subordinate to deterministic facts and legality.

---

## Track H — Automated learning loop

Long-term architecture:

```text
prediction
    ↓
decision
    ↓
outcome
    ↓
error
    ↓
feature/model diagnosis
    ↓
new model candidate
    ↓
backtest
    ↓
accept/reject
```

Never automatically deploy a model merely because it performed better over the latest few Gameweeks.

---

# 21. Engineering Principles

## 1. Deterministic truth first

The application owns:

- rules;
- prices;
- squad state;
- budget;
- transfer legality;
- lineup legality;
- chips;
- recorded decisions.

LLMs never override these.

## 2. No future leakage

Historical predictions and strategic optimizers use only information available at the historical decision point.

## 3. Every important number should be explainable

xP, strategic value and optimizer objectives should be decomposable.

## 4. Every decision should be reproducible

A decision record should identify:

- snapshot;
- model version;
- optimizer version;
- input state;
- strategy;
- constraints;
- recommendation;
- human choice;
- eventual outcome.

## 5. Prefer measured improvements

Do not add complexity without demonstrating benefit.

## 6. Keep the offline path functional

The quantitative core must work without an LLM API.

## 7. Provider integrations are optional

No provider should be a single point of failure.

## 8. External information must have provenance

News and contextual observations should carry source, timestamp and confidence.

## 9. UI must never be the source of truth

The GUI calls domain functions; it does not duplicate business rules.

## 10. Separate optimization from evaluation

Production-time optimizers must not receive hindsight information.

## 11. Exact reference ≠ production brute force

Use bounded exact references to validate heuristic/optimized production components.

## 12. Release small, research deeply

A smaller validated release is preferable to a feature-heavy branch with uncertain correctness.

---

# 22. Testing Strategy

Testing operates at four primary levels.

## Unit

Pure functions:

- rules;
- selling price;
- availability;
- xM;
- xP;
- ownership;
- fixtures;
- strategic objectives;
- constraints;
- hit calculation.

## Property/invariant

Examples:

- squad always has 15 unique players;
- squad never exceeds club limits;
- lineup always has 11 players;
- lineup formation is legal;
- bank never becomes negative after validated transfer;
- locked players remain present;
- excluded players never appear;
- undo restores prior state.

## Integration

Full workflows:

- update;
- squad;
- transfers;
- lineup;
- strategic squad;
- logging;
- scoring;
- evaluation;
- backtesting.

## Historical regression

A fixed historical Gameweek set should remain a permanent regression dataset.

---

# 23. Release Discipline

Every release should have:

1. feature list;
2. known bugs;
3. fixed bugs;
4. tests added;
5. tests passed;
6. schema/migration notes;
7. compatibility notes;
8. model changes;
9. optimizer changes;
10. provider changes;
11. known limitations;
12. reproducibility instructions.

A branch should not be described as complete merely because feature code exists.

Use distinct states:

- `implemented`;
- `tested`;
- `validated`;
- `PR-ready`;
- `released`.

---

# 24. Immediate Work Queue

## Now — V1.0 release

- [ ] Complete final V1.0 review.
- [ ] Confirm PR #12 release-hardening changes.
- [ ] Run full regression suite.
- [ ] Confirm exact-reference transfer oracle.
- [ ] Confirm exact-reference multi-GW oracle.
- [ ] Confirm lineup quantity separation.
- [ ] Confirm model metadata validation.
- [ ] Confirm historical timestamp determinism.
- [ ] Confirm PIT wording.
- [ ] Confirm optimizer exact/heuristic documentation.
- [ ] Confirm release reports and known limitations.
- [ ] Merge/release V1.0.

## Next — V1.1

### Engine

- [ ] Generalize squad-construction framework.
- [ ] Define strategic objective interface.
- [ ] Add Initial Squad mode.
- [ ] Add strategic Wildcard mode.
- [ ] Generalize Free Hit.
- [ ] Add hard constraints.
- [ ] Add soft preferences.
- [ ] Add lock/exclude/prefer model.
- [ ] Add multiple candidate solutions.
- [ ] Add configurable horizons.
- [ ] Add constraint impact analysis.
- [ ] Integrate with multi-GW planner.

### GUI

- [ ] Build Strategic Squad Studio.
- [ ] Add Initial Squad workflow.
- [ ] Add Wildcard workflow.
- [ ] Generalize Free Hit workflow.
- [ ] Add candidate comparison.
- [ ] Add player lock/unlock.
- [ ] Add exclude/prefer.
- [ ] Add strategy selection.
- [ ] Add horizon selection.
- [ ] Add re-optimization.
- [ ] Add opportunity-cost explanation.
- [ ] Add provenance.
- [ ] Connect output to normal decision workflow.

### ML

- [ ] Historical initial-squad reconstruction.
- [ ] Historical Wildcard reconstruction.
- [ ] Multi-strategy backtest.
- [ ] Multi-horizon backtest.
- [ ] Starting-state metrics.
- [ ] End-to-end season replay.
- [ ] Starting-state × predictor × decision-engine ablation.
- [ ] Strategic regret.
- [ ] Solution multiplicity.
- [ ] Constraint sensitivity.
- [ ] Horizon sensitivity.
- [ ] Strategy sensitivity.
- [ ] Starting-state error attribution.
- [ ] Multi-season walk-forward reports.

## After V1.1 — V1.2

- [ ] Multi-provider benchmark.
- [ ] Extended model benchmark.
- [ ] Human-in-the-loop framework.
- [ ] LLM role experiments.
- [ ] Closed-loop AI evaluation.
- [ ] AI-assisted strategic reasoning.

---

# 25. Definition of "Good Enough"

The project should optimize for **decision quality**, not technical sophistication.

The key question for every future feature is:

> Does this help us make better FPL decisions, or does it merely make the application more complicated?

Priority remains:

```text
Correctness
    >
Data quality
    >
Prediction quality
    >
Decision quality
    >
Strategic starting-state quality
    >
Evaluation
    >
UX
    >
Feature count
```

The strategic optimizer should therefore not be considered successful merely because it produces a higher projected score.

The important evidence is whether its decisions survive:

- point-in-time validation;
- out-of-sample evaluation;
- multi-season replay;
- downstream decision analysis;
- human constraint interaction.

---

# 26. Final Strategic Direction

The project has now passed through three major phases:

```text
V0.x
Build the engine
        ↓
V0.7–V0.9
Make the engine measurable
        ↓
V1.0
Make the engine trustworthy
        ↓
V1.1
Make squad construction strategic
and prove its downstream value
        ↓
V1.2
Determine whether AI/LLMs improve
the human + quantitative system
```

The long-term product is therefore not simply:

> "An FPL optimizer."

It is:

> **A reproducible decision-support system that constructs strategic options, lets a human express preferences and constraints, explains the consequences, records decisions, and continuously evaluates whether the system actually improves FPL decision quality.**
