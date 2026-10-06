# FPL Manager Roadmap

> Living document. This is the source of truth for delivery status, engineering priorities, release criteria, known risks, and long-term direction. Human contributors and AI agents must read it before material work and update it when priorities or milestone status changes.

**Current baseline:** V1.3 was completed, validated, and merged into master (#18) as a GBDT quantitative predictor challenger. V1.3.5 is the completed optimizer decision-quality study on branch `v135`, freezing the quantitative predictor, isolating optimizer mechanics across $B_0 \to B_7$, and deploying `DecisionEngineV135` ($H=3, \gamma=0.75, W_{\text{bench}}=0.15, \text{GK}_{\text{hurdle}}=3.0, N=5$, default `initial_strategy="maximum_ev"`). V1.4 is implemented and validated on branch `v14`, establishing the **Interactive Historical Season Simulation & Time Machine Sandbox** with point-in-time standings, past scores, upcoming fixtures with strict zero future spoilers, and full stateful simulation session management.

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
V1.1.5
Premier League departure handling
+ Historically calibrated seasonal chip strategy
+ Multi-version benchmark (v0.9 vs v1.0 vs v1.1 vs v1.1.5)
        ↓
V1.2
Strategic squad balancing (starting XI vs bench weighting)
+ Long-term unavailability handling (multi-month bans & injuries)
        ↓
V1.2.5
Lineup-aware transfer evaluation refinements
+ Candidate pool widening & direct lineup search
+ Goalkeeper churn suppression & role transfer hurdles
+ Multi-gameweek discounted lineup horizon (H=3, γ=0.75)
+ Dynamic chip-aware bench weighting
+ Live decision engine wiring with legacy fallback
        ↓
V1.3
GBDT Quantitative Predictor Challenger
+ HistGradientBoosting participation/minutes models
+ Non-linear quantitative prediction experiments
+ Strict temporal training/evaluation discipline
+ Predictor-vs-decision evaluation through the frozen V1.2.5 engine
+ No promotion unless corrected out-of-sample evidence supports it
        ↓
V1.3.5
Optimizer Decision-Quality Study & Hardened Architecture
+ Freeze the quantitative predictor
+ Optimizer component ablations (B0 through B7)
+ Bench-aware multi-horizon optimization (B3: 2,252 pts, buffering prediction noise)
+ Goalkeeper churn suppression (3.0 pt hurdle preserving outfield transfers)
+ Candidate pool expansion & search limits (B5: 2,224 pts vs B4: 2,208 pts)
+ Starting-state primacy (maximum_ev init +87 pts over balanced)
+ Formal regret decomposition (Prediction Regret dominates, Optimizer Regret <= 1.0 pt)
+ DecisionEngineV135 deployed as hardened reference baseline
        ↓
V1.4
Interactive Historical Season Simulation & Time Machine Sandbox
+ Step-by-step gameweek management across past seasons (2021-22 to 2025-26)
+ Point-in-time squad creation and historical score resolution
+ Frozen validated predictor/optimizer baseline
+ Human-vs-engine blind replay benchmark under strict information boundaries
        ↓
V1.4.5
Seasonal Chip Optimization & Multi-Team Isolation Hardening
+ Dynamic chip deployment optimization (eliminating wasted or unspent chips across segments)
+ Unified chip recommendation logic reconciling simulation policies and GUI calendar
+ Non-zero Free Hit targeting ensuring optimal deployment on blanks/doubles/deficits
+ Complete multi-team workspace isolation (preventing cross-team state leakage in live & historical modes)
        ↓
V1.5
Multi-provider expansion & combinatorial strategic advisory
+ Extended LLM model research (Claude, OpenAI, DeepSeek, Local Ollama)
+ Multi-transfer combinatorial planning (K=2 joint restructuring)
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
| V1.1 | Strategic squad + GUI + full ML analysis | Completed / Validated |
| **V1.1.5** | **PL departure lifecycle + seasonal chip calibration + multi-version benchmark** | **Completed / Merged** |
| **V1.2** | **Strategic squad balancing (XI vs bench weighting) + long-term unavailability (bans/ACLs)** | **Completed, validated, and merged into master (#16)** |
| **V1.2.5** | **Lineup-aware transfer refinements + multi-GW horizon + GK churn suppression + Live wiring** | **Completed, validated, and merged into master (#17)** |
| **V1.3** | **GBDT quantitative predictor challenger + experimental integration** | **Completed, validated, and merged into master (#18)** |
| **V1.4** | **Interactive historical season simulation & Time Machine sandbox platform** | **Completed and validated on branch `v14`** |
| V1.5 | Multi-provider expansion & combinatorial strategic advisory | Planned |

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

# 19. V1.1.5 — Premier League Departure Handling, Historically Calibrated Chip Strategy & Multi-Version Benchmark

**Status: completed & validated on branch `v115`.**  
**Specification:** `docs/v1.1.5/v115.md`  

### Purpose
Eliminate dead capital from players transferred out of the Premier League, prevent phantom buy recommendations, calibrate the 8 seasonal FPL chips (GW 1–19 and GW 20–38 quotas) against historical evidence with anti-pathology guardrails, and deliver an audited multi-season benchmark across V0.9, V1.0, V1.1, and V1.1.5.

### Core Architectural Pillars Delivered
1. **Departure Lifecycle & Dead Capital Offloading:**
   - Detect departures via status `'u'`, 0% availability with transfer/loan news, zero remaining fixtures, or the historical departures registry (`data/historical/departures_registry.json`).
   - Assign priority offload weight so recovering tied-up budget from departed players takes precedence over active underperformers.
   - Enforce strict buy-side candidate exclusion in transfers, Wildcards, Free Hits, and initial squad optimization.
2. **Historically Calibrated Seasonal Chip Engine:**
   - Track independent chip quotas: $1\times$ Wildcard, Free Hit, Triple Captain, Bench Boost in GW 1–19, and $1\times$ each in GW 20–38.
   - Anti-pathology constraints: fixture density guards (preventing Free Hit on postponed gameweeks like 2022-23 GW7), removal of blind expiry Wildcards (preventing negative EV resets in GW19/37), season-boundary clamping at GW38, and squad deterioration criteria ($\ge 4$ genuine injuries/suspensions/departures).
   - Near-expiry thresholds: disciplined dynamic thresholds (8.0 xP) for Triple Captain and Bench Boost to avoid burning chips on low-ceiling gameweeks.
3. **Multi-Version Benchmark Ledger:**
   - 5-season historical audit comparing `v0.9` vs `v1.0` vs `v1.1` vs `v1.1.5`.
   - Dual-track reporting: points scored *without chips* (Track A: pure transfer engine) vs *with chips* (Track B: seasonal chip orchestration).

---

# 20. V1.2 — Strategic Squad Balancing & Long-Term Unavailability

**Status:** Completed, validated, and merged into master (#16). Dual-track audited 5-season ledger: Track A 2,025.8 pts (lowest variance $\pm 122.0$; $+45.4$ pts vs V1.1.5); Track B 2,050.2 pts ($+42.4$ pts vs V1.1.5). Full baseline parity verified across V0.9–V1.1.5 (0.0 drift). **Ablation shows the gain comes from Pillar 1 (+24.2) and Pillar 3 (+21.2); the long-term unavailability registry (Pillar 2) contributes +0.0 pts/season and is verified inert.** Full specification and results: [`docs/v1.2/v12.md`](v1.2/v12.md).

V1.2 focuses on closing the performance gap between V1.0 (canonical single-gameweek decision engine) and V1.1 (strategic squad construction), while integrating first-class support for long-term player unavailability.

### Core Deliverables:
1. **Strategic Squad Balancing (Starting XI vs Bench Weighting):**
   - Implemented asymmetric starting XI vs bench weighting in the multi-week objective ($1.0\times$ for starters, $0.15\times$ for bench substitutes), concentrating budget into active starting firepower while preserving playing security.
2. **Long-Term Unavailability Modeling (implemented; verified inert):**
   - Precomputed boolean unavailability signal evaluated point-in-time at snapshot creation and propagated immutably through `ExpectedPointsProjection` $\to$ `PlayerInfo` $\to$ `PlayerOptInfo`, eliminating wall-clock dependencies and fragile news-string transport mechanisms.
   - Machine-checkable `known_from` dates on all historical registry entries asserted against gameweek deadlines to guarantee zero structural lookahead leakage.
   - Purchase exclusion in candidate pools and dead-capital liquidation prioritization (`dead_capital_weight=3.0`).
   - **Measured contribution: +0.0 pts/season across all 5 seasons.** Purchase exclusion pre-empts the dead-capital penalty (an excluded player never enters the squad, so the penalty never has a subject), leaving the two mechanisms unable to interact. Cleanly resolved via Option B removal in V1.2.5.
3. **Lineup-Aware Transfer Evaluation:**
   - Candidate moves evaluated on Starting XI lineup delta rather than raw unweighted 15-player squad totals.
4. **Verified Predecessor Baseline Parity:**
   - Safe architectural defaults (`bench_weight=1.0`, `apply_unavailability=False`) ensure that V0.9, V1.0, V1.1, and V1.1.5 reproduce their exact canonical master branch ledgers with 0.0 pt drift across all call sites.
   - Formally deferred the $\ge 2,050$ Track A exit criterion to V1.2.5 (`docs/v1.2.5/v125.md`).

---

# 21. V1.2.5 — Lineup-Aware Transfer Evaluation Refinements & Benchmark Target Achievement

**Status:** Implemented, verified, and PR-ready on branch `v125`. Specification: [`docs/v1.2.5/v125.md`](v1.2.5/v125.md). Execution plan: [`docs/v1.2.5/v125_implementation_plan.md`](v1.2.5/v125_implementation_plan.md). Dual-track audited 5-season ledger: Track A **2,046.6 pts** (lowest cross-season variance of any engine: $\pm 116.9$; $+20.8$ pts vs V1.2, closing 92% of the deficit against V1.0); Track B **2,087.8 pts** (chip return doubled to $+41.2$ pts/season; $+37.6$ pts vs V1.2). Full baseline parity verified across V0.9–V1.2 (exact 0.0 drift).

### Core Deliverables & Pillars:
1. **Candidate Pool Expansion (`max_results=25`):**
   - Expanded candidate pool in `solve_transfers` from 5 to 25 based on empirical sweeps across $\{5, 15, 25, 50\}$, removing the bottleneck where high-value starting XI upgrades were pruned before lineup evaluation. Measured contribution: **+17.00 pts/season**.
2. **Goalkeeper Churn Suppression & Role Transfer Hurdles:**
   - Position-specific net gain hurdles (1.50 pts for GKP vs 0.50 pts for outfield) and playing security invariant ($P(\text{play}) \ge 0.50$, or 3-GW net gain $\ge 3.0$ pts), cutting GK churn by 60% (2–3 transfers/season vs 5–10). Measured contribution: **+1.40 pts/season**.
3. **Multi-Gameweek Discounted Lineup Horizon ($H=3, \gamma=0.75$):**
   - Sourced point-in-time forward projections from deadline snapshots and pre-season schedules to evaluate rolling 3-GW discounted lineup returns, eliminating reactive panic-selling during short knocks and capturing multi-week fixture runs. Measured contribution: **+2.40 pts/season**.
4. **Double Gameweek (DGW) & Blank Gameweek Awareness:**
   - Multi-fixture gameweeks accrue cumulative xP within the 3-GW horizon, naturally prioritizing DGW assets (e.g. Eze GW34, Isak GW37) without ad-hoc rules.
5. **Dynamic Chip-Aware Bench Weighting:**
   - Dynamically scales `bench_weight`: $0.05\times$ for Free Hit (concentrates £100m into starting XI), $0.99\times$ for Bench Boost (avoids legacy symmetric mode trap), and $0.60\times$ in pre-BB accumulation windows. Track A strictly unaffected (0.0 drift); Track B chip gain increased from +24.4 to **+41.2 pts/season** (+37.60 pts overall).
6. **Resolution of Inert Unavailability Mechanism (Option B):**
   - Cleanly removed purchase exclusion for V1.2.5; confirmed 100% inert in backtests (exact 0.00 drift across all 5 seasons: 1968 / 1917 / 2193 / 2142 / 2013), eliminating dead code and hindsight bias.

### 5-Season Audited Benchmark Results (GW 1–38)

| Version | Track A Mean Net | Track B Mean Net | Chip Delta (B - A) | Track A Std Dev | Δ vs V1.2 (Track A) | Δ vs V1.0 (Track A) |
|---|---:|---:|---:|---:|---:|---:|
| **V0.9** | 1,983.6 | 2,048.2 | +64.6 pts | ±212.8 | -42.2 pts | -64.8 pts |
| **V1.0** | 2,048.4 | 2,108.0 | +59.6 pts | ±205.2 | +22.6 pts | — (baseline) |
| **V1.1** | 1,983.0 | 2,010.0 | +27.0 pts | ±122.4 | -42.8 pts | -65.4 pts |
| **V1.1.5** | 1,980.4 | 2,007.8 | +27.4 pts | ±145.2 | -45.4 pts | -68.0 pts |
| **V1.2** | 2,025.8 | 2,050.2 | +24.4 pts | ±122.0 | — | -22.6 pts |
| **V1.2.5** | **2,046.6** | **2,087.8** | **+41.2 pts** | **±116.9** | **+20.8 pts** | **-1.8 pts** |

### Per-Pillar Ablation Summary (Track A Mean Net)

| Step | Mechanism | Track A Mean | Track A Δ | Primary Empirical Impact |
|---|---|---:|---:|---|
| **V1.2 Baseline** | Asymmetric Balancing + Inert Registry | 2,025.80 | — | Lowest cross-season variance (±122.0), -22.6 pts vs V1.0 |
| **Pillar 1** | Candidate Pool Expansion (`max_results=25`) | 2,042.80 | **+17.00 pts** | Unlocks starting XI upgrades formerly pruned (+41 in 23-24, +60 in 24-25) |
| **Pillar 2** | Goalkeeper Churn Suppression (Hurdle 1.5 + Security) | 2,044.20 | **+1.40 pts** | Reduces GK moves from 5 to 2 in 23-24; saves free transfers for outfielders |
| **Pillar 3 & 4** | Rolling 3-GW Horizon ($H=3, \gamma=0.75$) & DGW | 2,046.60 | **+2.40 pts** | Multi-match fixture stability (+64 in 22-23, +23 in 25-26); anti-zigzag |
| **Pillar 5** | Dynamic Chip Bench Weighting (FH 0.05, BB 0.99) | 2,046.60 | **+0.00 pts** | Track A unaffected (zero-leakage); Track B improves +37.6 pts |
| **Pillar 6** | Resolve Inert Unavailability (Option B: Removal) | 2,046.60 | **+0.00 pts** | Verified 100% inert across 5 seasons; eliminates dead code |
| **V1.2.5 Final** | All 6 Pillars Integrated | **2,046.60** | **+20.80 pts** | **Lowest variance across all versions (±116.9)**; closes 92% of deficit |

### Target Decision & Deferral Rationale
V1.2.5 closes 92% of the Track A performance deficit against V1.0 (2,046.6 vs 2,048.4, delta -1.8 pts) while achieving the lowest cross-season standard deviation of any engine in project history ($\pm 116.9$, 43% lower variance than V1.0's $\pm 205.2$). The stretch target of $\ge 2,060.0$ Track A net points is actively tested in V1.3 via the Gradient Boosting engine.

---

# 22. V1.3 — GBDT Quantitative Predictor Challenger

**Status: Hardened, Audited & Retained as Challenger (`v13`)**  
**Specification:** [`docs/v1.3/v13.md`](v1.3/v13.md) / [`docs/v1.3/v13_gradient_boosting.md`](v1.3/v13_gradient_boosting.md)  
**Verification Checklist:** [`docs/v1.3/v13_items_left.md`](v1.3/v13_items_left.md)

### Purpose & Vision

V1.3 is a controlled quantitative-model experiment. It introduces Gradient Boosting Decision Trees as a challenger to the established quantitative core and evaluates the resulting decisions through the frozen V1.2.5 optimizer.

The scientific question was:

> **Does a more flexible quantitative predictor convert into better downstream FPL decisions under strict point-in-time historical evaluation?**

### Final Audited Evidence & Findings

Under the audited walk-forward protocol with zero evaluation-season contamination:
- **Track A Aggregate:** V1.2.5 = **2,026.6 pts** (±136.2) vs V1.3 = **1,941.6 pts** (±281.2).
- **Track B Aggregate:** V1.2.5 = **2,075.2 pts** (±139.8) vs V1.3 = **1,985.8 pts** (±287.9).
- **Season-by-Season Trajectory:**
  - In low-data regimes (`2021-22` out-of-fold and `2022-23` single-season), GBDT suffered significant distribution shift (-391 pts and -161 pts Track A).
  - In mature training regimes ($N \ge 2$ prior seasons), GBDT matched or outperformed V1.2.5: `2023-24` (+4 pts Track A), `2024-25` (+7 pts Track A, +48 pts Track B), and `2025-26` (+116 pts Track A, +67 pts Track B).

### Promotion Gate Verdict

- **Production Replacement:** **REJECTED.** V1.2.5 remains the production default due to aggregate stability and lower variance.
- **Challenger Retention:** **ACCEPTED.** V1.3 is retained as an official experimental challenger (`--predictor v1.3`), valuable for modern multi-season analysis and future hybrid ensembling.
- **Experimental Baseline Frozen:** **`DecisionEngineV125` is formally frozen** as the validated baseline engine for V1.3.5 and V1.4.

---

# 23. V1.3.5 — Optimizer Decision-Quality Study

**Status: Completed and validated on branch `v135`.**  
**Specification:** [`docs/v1.3.5/v135.md`](v1.3.5/v135.md)  
**Deliverables Ledger:** [`reports/v135/`](../reports/v135/) (`final_summary.md`, `optimizer_ablation.md`, `regret_analysis.md`, `runtime_analysis.csv`)

### Purpose & Research Verdict

V1.3.5 froze the quantitative predictor and systematically isolated the downstream decision-quality impact of each optimizer mechanism:

> **Given the same projections, which optimizer mechanisms actually improve realized FPL decisions?**

### Key Empirical Findings

1. **Bench-Aware Multi-Horizon Optimization ($B_0 \to B_1 \to B_3$):** Multi-GW planning without bench awareness was brittle (-56 pts vs control); adding explicit bench weighting ($W_{\text{bench}}=0.15$) surged performance to **2,289.0 pts (+193.0 pts over $B_1$, +137.0 pts over control $B_0$)** by buffering against multi-period prediction noise.
2. **Goalkeeper Churn Suppression ($B_3 \to B_4$):** Enforcing role-specific hurdles ($3.0$ pts) on healthy goalkeepers eliminates zero-utility transfers, preserving free transfers for outfield assets.
3. **Candidate Search Pool Regularization ($B_4 \to B_5$):** Expanding candidate search breadth from 5 to 25 caused a sharp collapse of **-147.0 pts** (2,289 to 2,142) due to "search breadth overfitting", where the optimizer aggressively selected noisy positive prediction error tails. Constraining the pool to $N=5$ acts as an essential regularizer.
4. **Mathematical Regret Decomposition Verified:** Empirically verified $\text{Total Decision Regret} \equiv \text{Prediction Regret} + \text{Optimizer Regret}$ ($\epsilon < 0.05$). Optimizer Regret is 0.00 pts in modern variants, proving that candidate pool degradation is purely driven by Prediction Regret surging from 6.50 to 21.83 pts.
5. **Starting-State Compounding Effect:** Initial squad selection exerts compounding leverage, unlocking **+93 net points** with `maximum_ev` over balanced initialization.

### Hardened Production Architecture Deployed

The following three core decisions are codified into `DecisionEngineV135`:
- **Decision 1:** Rolling $H=3, \gamma=0.75$, bench weighting $W_{\text{bench}}=0.15$, and goalkeeper transfer hurdle $\text{GK}_{\text{hurdle}}=3.0$.
- **Decision 2:** Constrained candidate search pool size `max_results = 5`.
- **Decision 3:** Default initial squad construction profile `initial_strategy = "maximum_ev"`.

Integrated into `fpl_manager.backtest.decision_engine:DecisionEngineV135` and registered under `--decision-engine v1.3.5`. This engine is formally frozen as the reference decision engine for V1.4 historical simulation.

---

# 24. V1.4 — Interactive Historical Season Simulation & Human-in-the-Loop Benchmark Platform

**Status: completed and validated on branch `v14`.**  
**Specification:** [`docs/v1.4/v14_historical_simulation.md`](v1.4/v14_historical_simulation.md)

### Delivery Summary & Implemented Architecture

V1.4 delivers the full **Interactive Historical Season Simulation & Time Machine Sandbox** across CLI, Web Studio GUI, and programmatic APIs:
- **Historical Standings & Match Results (`src/fpl_manager/historical/standings.py`)**: Computes authentic point-in-time league tables (Pos, P, W, D, L, GF, GA, GD, Pts, Form), displays completed match scores, and generates upcoming fixtures with strict zero-leakage masking of future outcomes.
- **Enriched Historical Fixture Datasets**: Enriched `data/historical/<season>/fixtures.json` across all 5 historical seasons (`2021-22` through `2025-26`) with historical match scores while updating ingestion parsers.
- **Isolated Simulation Sessions (`src/fpl_manager/simulation/`)**: Stateful sessions stored under `config/simulations/<session_id>.json` with complete legality validation, transfer staging, multi-chip rules (Wildcard windows, Free Hit squad reversion, Bench Boost, Triple Captain), deterministic matchday resolution with autosubs, transfer hit accounting, and parallel baseline tracking (`DecisionEngineV125` / `DecisionEngineV135`).
- **Interactive Web Studio GUI Time Machine**: Dedicated `⏳ Historical Time Machine` tab featuring interactive Premier League table, recent match results panel, upcoming fixture cards with FDR, interactive pitch squad view with captaincy toggles, transfer staging modal, and matchday step execution.
- **Comprehensive CLI Interface (`fpl sim`)**: Full suite of subcommands (`create`, `list`, `status`, `overview`, `transfer`, `clear-transfers`, `chip`, `recommendations`, `run-gw`, `report`).

### Purpose & Vision

V1.4 transforms FPL Manager into an interactive **Historical Season Simulation / FPL Time Machine** built on the frozen quantitative and optimizer baseline established by V1.3/V1.3.5.

Users can select a past season (`2021-22` through `2025-26`), construct or modify a starting squad, step through the season gameweek by gameweek, make transfers, set lineups, activate chips, and resolve authentic historical match outcomes.

### Human-in-the-Loop Benchmark

The platform supports controlled replay conditions in which:

- the participant sees only information available at the simulated deadline;
- the engine provides recommendations;
- the participant makes the final decision;
- engine recommendation, human decision, and realized outcome are all stored.

The benchmark reports **observed performance under the defined study conditions**. It is not presented as a universal lower bound or a prediction of live-manager performance.

### Mandatory Pre-Trial Gate

Before human trials:

```text
batch backtest
      ==
historical simulator engine-only replay
```

within documented tolerances for the frozen engine.

### Core Deliverables

- isolated historical session state;
- strict point-in-time information boundaries;
- deterministic scoring/autosub resolution;
- transfer and chip state management;
- CLI and GUI Time Machine workflow;
- engine-only parity validation;
- human-vs-engine benchmark protocol;
- reproducible season-end analytics.

---

# 24.5. V1.4.5 — Seasonal Chip Optimization & Multi-Team Isolation Hardening

**Status: planned for next release (following V1.4).**

### Core Problems Addressed
1. **Unspent Chip Wastage in Historical Simulations**: In past season simulations, heuristic chip models occasionally completed an entire half-season window without ever deploying a high-value chip (e.g. Free Hit, Triple Captain, or Bench Boost) because static hurdle thresholds were not met. Under FPL rules, chips expire at GW19 and GW38, making "holding forever" strictly suboptimal compared to deploying on the best available local peak.
2. **Reconciliation of Simulation Engine vs GUI Chip Strategy**: The historical backtest engine (`SeasonalChipPolicy`) and the GUI Chip Strategy (`recommend_chip_strategy`) historically relied on different heuristic evaluation pipelines, creating discrepancies where the GUI suggested a roadmap that differed from what simulation benchmarks executed.
3. **Multi-Team State Isolation**: Ensuring all decision logging, chip availability, bank budgets, staged transfers, and gameweek contexts remain strictly isolated across multiple live teams and historical simulation sessions without cross-contamination.

### Key Deliverables
- **Dynamic End-of-Window Chip Forcing**: When approaching deadline expiration (GW17-19 in Segment 1, GW36-38 in Segment 2), relax static hurdle gates dynamically to guarantee full chip utilization on the best candidate matchday.
- **Unified Chip Policy Model**: Share a single deterministic chip policy between historical simulation step functions, benchmark backtests, and the GUI Chip Strategy calendar.
- **Strict Multi-Team Workspace Scoping**: Explicit `team_id` / `session_id` database partitioning ensuring zero shared state between different live teams or between live and historical modes.

---

# 25. V1.5 — Multi-Provider Expansion & Combinatorial Strategic Advisory

**Status: planned after V1.4.**

V1.5 expands LLM integration across multiple providers and introduces combinatorial multi-transfer optimization ($K=2$ joint moves) alongside qualitative strategic advisory.

### 25.1 Multi-provider infrastructure
Investigate and support: OpenAI, Gemini, OpenRouter, Groq, and local/open models (Ollama, vLLM). Provider support remains strictly optional.

### 25.2 Provider benchmark
Benchmark quality, consistency, latency, cost, and structured-output reliability.

### 25.3 Multi-transfer combinatorial planning ($K=2$)
Introduce joint 2-transfer optimization to solve structural squad imbalances.

### 25.4 Closed-loop LLM evaluation
Empirically compare quantitative-only vs quantitative + human vs quantitative + LLM + human.

# 26. Long-Term Research Tracks

These remain available after V1.3 and should be promoted into releases only when there is sufficient evidence.

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

# 27. Engineering Principles

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

# 28. Testing Strategy

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

# 29. Release Discipline

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

# 30. Immediate Work Queue

## Completed — V1.3 Hardening & Audit

- [x] Fix training/evaluation temporal contamination (`get_walk_forward_gbdt_predictor`).
- [x] Enforce train/serve feature parity (`test_feature_parity_with_snapshot_extraction`).
- [x] Remove silent predictor fallback from research/benchmark mode (`strict_predictor=True`).
- [x] Correct benchmark provenance and predictor version metadata.
- [x] Freeze the downstream decision engine during predictor comparison (`DecisionEngineV125` baseline).
- [x] Correct xG/xA target terminology to normalized realized return rates.
- [x] Align V1.3 documentation with the actual implementation.
- [x] Regenerate the V1.3 benchmark under clean walk-forward rules.
- [x] Run the dedicated V1.3 test suite (12/12 passing).
- [x] Run the relevant full regression suite (435/435 passing).
- [x] Decide whether GBDT is promoted, retained as a challenger, or rejected (Verdict: **Challenger Retained**; V1.2.5 frozen as production baseline).

## V1.3.5 optimizer study (Completed)

- [x] Freeze the predictor selected by the corrected V1.3 experiment.
- [x] Build the optimizer ablation harness (`DecisionEngineAblation` & `OptimizerAblationConfig`).
- [x] Establish a minimal legal optimizer control ($B_0$).
- [x] Test horizon effects ($H=1$ vs $H=3$ vs $H=5$).
- [x] Test bench-aware effects ($B_1 \to B_3$, +193 pts gain).
- [x] Test goalkeeper transfer hurdles ($B_3 \to B_4$, 3.0 pt hurdle).
- [x] Test candidate-pool expansion ($B_4 \to B_5$, discovered search breadth overfitting).
- [x] Test future-transfer flexibility ($B_6$).
- [x] Test chip-aware sequential optimization ($B_7$).
- [x] Separate starting-state effects from downstream optimizer effects (+93 pts for `maximum_ev`).
- [x] Implement prediction-regret vs optimizer-regret decomposition ($\text{Total Regret} \equiv \text{Prediction Regret} + \text{Optimizer Regret}$).
- [x] Measure runtime/search complexity (median < 180ms/GW across all variants).
- [x] Produce multi-season decision-level reports (`reports/v135/`).
- [x] Deploy and freeze `DecisionEngineV135` before V1.4.

## Completed — V1.4 Historical Simulation Platform

- [x] Implement isolated historical simulation state (`config/simulations/<id>.json`).
- [x] Implement historical deadline/time isolation and zero future spoilers.
- [x] Implement deterministic GW scoring and autosubs.
- [x] Implement transfer/chip state progression.
- [x] Validate simulator-vs-batch parity and parallel baseline tracking.
- [x] Build CLI Time Machine workflow (`fpl sim`).
- [x] Build GUI Time Machine workflow (`/api/historical/*` + Web Studio tab).
- [x] Implement human-vs-engine benchmark protocol and divergence logging.
- [x] Generate reproducible season-end analytics and Markdown/JSON reporting.

## Later — V1.5

- [ ] Multi-provider LLM benchmark.
- [ ] Extended model/provider evaluation.
- [ ] Combinatorial multi-transfer planning.
- [ ] Closed-loop quantitative + LLM + human evaluation.

# 31. Definition of "Good Enough"

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

# 32. Final Strategic Direction

The project has now passed through four major phases:

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
V1.1–V1.2.5
Make squad construction and transfer decisions strategic
and measure their downstream value
        ↓
V1.3
Test whether a more sophisticated predictor improves decisions
        ↓
V1.3.5
Identify which optimizer mechanisms actually convert forecasts into value
        ↓
V1.4
Validate the complete decision-support loop with historical human replay
```

The long-term product is therefore not simply:

> "An FPL optimizer."

It is:

> **A reproducible decision-support system that constructs strategic options, lets a human express preferences and constraints, explains the consequences, records decisions, and continuously evaluates whether the system actually improves FPL decision quality.**

