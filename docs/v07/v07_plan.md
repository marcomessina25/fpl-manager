# V0.7 --- Detailed Development Plan

## 1. Objective

V0.7 is the next major milestone after the V0.65 stabilization release.

The purpose of V0.7 is to move the project from:

> **"We have a deterministic FPL decision engine with an xP model and
> LLM advisory layer."**

towards:

> **"We can objectively measure how good the underlying predictions and
> decisions are using historical, point-in-time FPL data."**

The central principle for V0.7 is **measurement before optimization**.

Before substantially changing the xP model, optimizer, or LLM strategy,
we should establish a reproducible historical evaluation framework and
determine where the current system actually succeeds and fails.

V0.7 should therefore prioritize:

1.  historical data acquisition;
2.  point-in-time data integrity;
3.  reproducible historical reconstruction;
4.  player/xP/xM backtesting;
5.  decision-engine backtesting;
6.  deterministic benchmark strategies;
7.  quantitative comparison and reporting;
8.  identifying the highest-value improvements for V0.8+.

------------------------------------------------------------------------

# 2. Relationship with V0.65

V0.65 is primarily a **stabilization and correctness** milestone.

Its goal is to make the existing system safe enough to use as the
foundation for historical experimentation.

V0.7 should build on that foundation rather than reopening V0.65.

### V0.65 provides

-   deterministic FPL rules;
-   squad-state management;
-   transfer-chain handling;
-   transfer accounting;
-   decision logging;
-   lineup validation;
-   automatic substitutions;
-   Gameweek handling;
-   xP calculation;
-   optimizer;
-   LLM advisory layer;
-   OpenRouter integration;
-   evaluation infrastructure;
-   regression tests.

### V0.7 adds

-   historical datasets;
-   point-in-time reconstruction;
-   historical feature snapshots;
-   historical xP/xM evaluation;
-   backtesting;
-   benchmark strategies;
-   systematic metrics;
-   reproducible experiments;
-   analysis of failure modes.

The V0.7 work should **consume the V0.65 interfaces wherever
practical**, not create a parallel implementation of the FPL rules.

------------------------------------------------------------------------

# 3. Guiding principles

## 3.1 No future information leakage

This is the most important requirement of V0.7.

When evaluating a decision for Gameweek `GW`, the system must only use
information that would have been available **before the decision was
made**.

For example, a Gameweek 10 decision must not use:

-   Gameweek 10 final points;
-   Gameweek 10 final minutes;
-   Gameweek 10 final bonus;
-   future transfers;
-   future prices;
-   future ownership;
-   future injury information;
-   future fixture information that was not available at decision time.

The backtester must enforce this structurally wherever possible.

------------------------------------------------------------------------

## 3.2 Reproducibility

A historical experiment should be reproducible.

Given:

-   the same historical dataset;
-   the same configuration;
-   the same code version;
-   the same decision timestamp;

the system should produce the same result.

Avoid experiments that depend on uncontrolled live API responses.

------------------------------------------------------------------------

## 3.3 Separate prediction quality from decision quality

These are different questions.

### Prediction quality

> How accurately does xP predict future FPL points?

### Decision quality

> Given the available information, does the optimizer choose better
> actions?

### LLM quality

> Does the LLM improve decisions compared with the deterministic system
> alone?

These should be evaluated separately.

A model can have good predictive accuracy while producing poor
decisions, and vice versa.

------------------------------------------------------------------------

## 3.4 Deterministic core remains authoritative

The LLM must remain an advisory component.

The V0.7 backtester should be able to run without an LLM.

This gives us:

``` text
Deterministic baseline
        ↓
Deterministic optimizer
        ↓
Optional LLM advisor
        ↓
Deterministic validation
        ↓
Historical result
```

This makes it possible to measure whether the LLM actually adds value.

------------------------------------------------------------------------

# 4. V0.7 workstreams

V0.7 should be developed through the following workstreams:

1.  Historical data architecture
2.  Historical data acquisition
3.  Point-in-time snapshots
4.  Historical feature reconstruction
5.  xP/xM backtesting
6.  Decision-engine backtesting
7.  Benchmark strategies
8.  LLM A/B evaluation
9.  Experiment configuration and reproducibility
10. Metrics and reporting
11. Data-quality validation
12. Documentation and research conclusions

The order matters.

Do not begin by modifying the xP formula. First build the infrastructure
capable of telling us whether a modification is better.

------------------------------------------------------------------------

# 5. Phase 1 --- Historical data architecture

## Goal

Create a clean representation of historical FPL data suitable for
backtesting.

The first task is to inspect the current data layer and determine which
existing structures can be reused.

### Inventory

Identify all currently used FPL data sources, including:

-   players;
-   teams;
-   fixtures;
-   Gameweeks;
-   player Gameweek statistics;
-   prices;
-   ownership;
-   transfers;
-   injuries/status;
-   availability;
-   minutes;
-   points;
-   bonus;
-   goals/assists;
-   clean sheets;
-   cards;
-   saves;
-   other statistics currently used by the model.

For every field, document:

  ---------------------------------------------------------------------------
  Field                 Current source    Historical        Point-in-time
                                          availability      requirement
  --------------------- ----------------- ----------------- -----------------
  Player identity       FPL API           Yes               Low

  Price                 FPL data          Historical        High
                                          reconstruction    
                                          required          

  Ownership             FPL data          Historical        High
                                          reconstruction    
                                          required          

  GW points             FPL data          Yes               Future/outcome
                                                            data

  Minutes               FPL data          Yes               Future/outcome
                                                            data

  Fixtures              FPL data          Yes               High

  Availability/status   FPL data          Historical        Very high
                                          reconstruction    
                                          required          
  ---------------------------------------------------------------------------

The exact fields should be determined from the actual implementation
rather than guessed in advance.

------------------------------------------------------------------------

# 6. Phase 2 --- Historical data acquisition

## Goal

Obtain enough historical seasons to make V0.7 useful.

Prefer official FPL-origin data or reliable public historical datasets
where possible.

The first implementation should support at least one complete historical
season end-to-end.

After that, expand to multiple seasons.

### Suggested progression

``` text
Dataset 1
    ↓
one complete season
    ↓
validate pipeline
    ↓
Dataset 2
    ↓
second season
    ↓
cross-season validation
    ↓
additional seasons
```

Do not spend significant effort acquiring many seasons before proving
that the reconstruction pipeline works correctly on one.

------------------------------------------------------------------------

# 7. Point-in-time data model

This is the core architectural requirement.

A historical record should not merely say:

``` text
player_id = X
gameweek = 10
```

It should represent what was knowable at the relevant decision point.

Conceptually:

``` text
Decision timestamp
        ↓
Available data snapshot
        ↓
Model prediction
        ↓
Decision
        ↓
Actual future outcome
```

The system should maintain a strict separation between:

### Information available before decision

Used as model input.

### Information revealed after decision

Used only as ground truth.

------------------------------------------------------------------------

# 8. Snapshot strategy

For each historical decision point, create or reconstruct a snapshot
containing the data available at that time.

For example:

``` text
season
gameweek
decision_timestamp
player_state
team_state
fixture_state
prices
ownership
availability
historical_performance
configuration
```

The snapshot should be immutable once generated.

A useful structure is:

``` text
data/
    historical/
        2024-25/
            gw01/
            gw02/
            ...
        2025-26/
            gw01/
            ...
```

The exact storage format should follow the existing repository
architecture and should be selected after inspecting current
persistence/data conventions.

------------------------------------------------------------------------

# 9. Decision timestamp is critical

The backtester needs a clearly defined decision point.

For V0.7, initially use a consistent rule such as:

> Decision is made using information available after the previous
> Gameweek and before the next Gameweek deadline.

Do not assume that "Gameweek N data" means all information available
immediately before Gameweek N.

Where possible, use timestamps from the historical data.

If exact timestamps are unavailable, document the approximation
explicitly.

------------------------------------------------------------------------

# 10. Historical feature reconstruction

Once snapshots exist, reconstruct the exact features consumed by the
current xP model.

This is where the V0.7 work should connect directly to the current
deterministic core.

The objective is:

``` text
historical snapshot
        ↓
current feature pipeline
        ↓
historical xP prediction
```

not:

``` text
historical snapshot
        ↓
special historical xP implementation
```

unless the current code genuinely cannot support historical inputs.

If a new abstraction is needed, refactor the existing feature
calculation into reusable functions rather than duplicating the model.

------------------------------------------------------------------------

# 11. xP backtesting

## Primary research question

> How well does the current xP model predict future FPL points?

For every player and Gameweek:

``` text
prediction_time
predicted_xP
actual_points
expected_minutes
actual_minutes
availability
```

should be recorded.

The evaluation layer should calculate at least:

-   MAE;
-   RMSE;
-   Spearman rank correlation;
-   calibration/error by prediction bucket;
-   error distribution;
-   performance by position;
-   performance by expected-minutes range;
-   performance by availability;
-   performance by player price range.

The existing evaluation infrastructure should be reused where possible.

------------------------------------------------------------------------

# 12. xM / minutes-model evaluation

The expected-minutes component deserves separate evaluation.

Do not only evaluate:

``` text
xP
```

because xP combines:

``` text
per-minute expected production
×
expected minutes
```

If expected minutes are wrong, the final xP can be wrong even when the
underlying per-minute model is reasonable.

Measure:

``` text
predicted minutes
actual minutes
```

and report:

-   MAE;
-   RMSE;
-   bias;
-   error distribution;
-   calibration by predicted-minutes bucket.

Example:

``` text
Predicted 0–15
Predicted 16–30
Predicted 31–60
Predicted 61–75
Predicted 76–90
```

This should become one of the primary research outputs of V0.7.

------------------------------------------------------------------------

# 13. Availability model evaluation

Evaluate availability separately from xP.

For example:

``` text
predicted availability
actual availability
```

and calculate:

-   accuracy;
-   precision/recall where appropriate;
-   calibration;
-   false-positive availability;
-   false-negative availability.

The objective is to determine whether availability uncertainty is being
represented correctly.

------------------------------------------------------------------------

# 14. Establish deterministic baselines

Before evaluating the optimizer, create simple baselines.

At minimum:

## Baseline A --- No-transfer strategy

Keep the previous squad and make no transfers unless required by the
rules.

This gives a lower-complexity reference.

## Baseline B --- Highest-xP transfer strategy

Select transfers using the existing xP ranking with minimal
sophistication.

## Baseline C --- Existing optimizer

Run the current optimizer.

## Baseline D --- Optional LLM-assisted strategy

Run the deterministic optimizer plus the LLM advisor.

The comparison should therefore look like:

``` text
No-transfer
     │
     ├── simple deterministic strategy
     │
     ├── current optimizer
     │
     └── optimizer + LLM
```

This is essential.

Without baselines, an absolute points total tells us very little.

------------------------------------------------------------------------

# 15. Backtest the actual decision engine

The historical framework should eventually reconstruct a complete
Gameweek decision.

For each historical Gameweek:

``` text
historical snapshot
        ↓
build squad state
        ↓
calculate xP
        ↓
generate candidate transfers
        ↓
optimizer
        ↓
optional LLM advice
        ↓
deterministic validation
        ↓
execute simulated decision
        ↓
simulate lineup
        ↓
calculate actual points
        ↓
store result
```

This should use the same production decision components wherever
practical.

------------------------------------------------------------------------

# 16. Do not optimize against future results

This is the biggest methodological risk.

The backtest must never do:

``` text
future points
      ↓
choose best transfer
```

and then call that an evaluation.

That would be an oracle.

The optimizer must only see:

``` text
information available at decision time
```

and the actual points are revealed only afterward for evaluation.

------------------------------------------------------------------------

# 17. Simulated FPL state

The backtester needs to maintain a simulated manager state across
Gameweeks.

At minimum:

``` text
squad
bank
free transfers
transfer history
hits
captain
vice captain
chips
bench order
starting XI
```

The simulated state should evolve sequentially:

``` text
GW1
 ↓
GW2
 ↓
GW3
 ↓
...
```

Do not independently optimize every Gameweek using a reset squad.

That would produce unrealistic results.

------------------------------------------------------------------------

# 18. Chips and special cases

V0.7 should decide explicitly which special FPL mechanisms are supported
by the backtester.

At minimum, document support status for:

-   Wildcard;
-   Free Hit;
-   Bench Boost;
-   Triple Captain;
-   transfer hits;
-   captaincy;
-   vice-captaincy;
-   double Gameweeks;
-   blank Gameweeks.

Do not necessarily implement every chip in the first V0.7 iteration.

A sensible staged approach is:

``` text
V0.7 initial
    transfers + lineup + captaincy

V0.7 later
    chips + more complex special cases
```

The important requirement is that unsupported mechanisms are explicitly
excluded rather than silently ignored.

------------------------------------------------------------------------

# 19. LLM evaluation

The LLM should be evaluated as an **incremental component**.

Run identical historical decision points through:

### Experiment 1

Deterministic optimizer only.

### Experiment 2

Deterministic optimizer + LLM.

Then compare:

-   total points;
-   Gameweek points;
-   transfer cost;
-   captain points;
-   hit frequency;
-   squad value;
-   rank-related metrics where available;
-   decision stability;
-   invalid recommendations;
-   override frequency.

The critical question is:

> Does the LLM add measurable value after deterministic optimization?

If it does not, we should not assume that adding more LLM
prompts/providers will improve the product.

------------------------------------------------------------------------

# 20. LLM experiment controls

LLM evaluation must be reproducible as far as possible.

Record:

``` text
provider
model
prompt version
temperature
input snapshot
output
parsed decision
validation result
final executed decision
```

The raw LLM response should be stored for analysis, subject to
privacy/security considerations.

This will allow us to determine whether a change in performance comes
from:

-   the model;
-   the prompt;
-   the data;
-   the deterministic optimizer;
-   the validation layer.

------------------------------------------------------------------------

# 21. Provider strategy

V0.65 already has a verified free-capable OpenRouter path.

V0.7 should therefore **not** make "find a free provider" a blocking
objective.

Instead:

``` text
OpenRouter free-capable model
        ↓
baseline LLM provider
```

Additional providers should be added only when useful for comparative
experiments.

The provider abstraction should allow:

``` text
provider/model
```

to be changed without modifying the decision engine.

Provider expansion remains a later enhancement unless required by an
experiment.

------------------------------------------------------------------------

# 22. Experiment configuration

Introduce a reproducible experiment configuration.

For example:

``` yaml
season: 2024-25
gameweeks:
  - 1
  - 2
  - 3
strategy: optimizer
llm:
  enabled: false
model:
  version: current
```

The exact format can follow repository conventions.

The goal is that a researcher can run:

``` text
same dataset
+
same configuration
=
same experiment
```

without manually changing source code.

------------------------------------------------------------------------

# 23. Results storage

Every backtest should produce structured results.

At minimum:

``` text
experiment_id
season
gameweek
strategy
squad_before
transfers
squad_after
captain
predicted_points
actual_points
transfer_cost
net_points
```

For prediction-level evaluation:

``` text
player_id
gameweek
prediction_timestamp
xP
xM
availability
actual_points
actual_minutes
```

This data should be stored in a form that can later be analyzed with
Python/pandas without scraping application logs.

------------------------------------------------------------------------

# 24. Research reports

V0.7 should generate a concise report for every experiment.

Example:

``` text
Experiment: 2024-25 baseline
Gameweeks: 1–38

Strategy                 Points    Hits    Net points
------------------------------------------------------
No transfers             ...
Simple xP                ...
Optimizer                ...
Optimizer + LLM          ...
```

Prediction metrics:

``` text
Metric                 Result
--------------------------------
xP MAE                 ...
xP RMSE                ...
Spearman correlation   ...
xM MAE                 ...
Availability accuracy  ...
```

The report should also identify statistically meaningful differences
where possible.

------------------------------------------------------------------------

# 25. Failure-mode analysis

Do not stop at aggregate metrics.

Find where the system fails.

Examples:

-   high-xP player repeatedly underperforms;
-   expected minutes consistently overestimated;
-   injured players incorrectly selected;
-   rotation risk underestimated;
-   fixtures incorrectly valued;
-   captaincy decisions systematically biased;
-   transfers made for marginal gains but incur excessive hits;
-   optimizer overreacts to one Gameweek;
-   LLM changes good deterministic decisions into worse ones.

These failure modes should become the input to V0.8+ development.

------------------------------------------------------------------------

# 26. Statistical methodology

Avoid selecting model improvements based solely on one season.

For each major experiment, report:

-   mean performance;
-   median performance;
-   variance;
-   Gameweek-level distribution;
-   confidence intervals where appropriate;
-   cross-season performance.

For strategy comparisons, use paired Gameweek-level comparisons where
appropriate because all strategies face the same underlying fixtures.

The objective is not merely:

> "Strategy A scored more points."

It is:

> "Strategy A consistently outperformed Strategy B across the same
> historical decision points."

------------------------------------------------------------------------

# 27. Train/test separation

If V0.7 eventually introduces model fitting or parameter optimization,
enforce temporal separation.

For example:

``` text
Season 2023-24
       ↓
development / calibration

Season 2024-25
       ↓
validation

Season 2025-26
       ↓
out-of-sample evaluation
```

Do not tune parameters on the same Gameweeks used to claim performance.

This becomes particularly important once we begin calibrating xP/xM.

------------------------------------------------------------------------

# 28. xP model improvement policy

Do not immediately rewrite the xP model.

First establish a baseline.

Then test modifications individually:

``` text
Baseline xP
   ↓
Change A
   ↓
Backtest
   ↓
Change B
   ↓
Backtest
```

Every modification should answer:

1.  What hypothesis are we testing?
2.  What data supports the hypothesis?
3.  What metric should improve?
4.  What regression would invalidate the change?
5.  Does the improvement generalize across seasons?

This turns model development into controlled experimentation rather than
subjective tuning.

------------------------------------------------------------------------

# 29. V0.7 milestones

## V0.7.0 --- Data foundation

Deliver:

-   historical data ingestion;
-   normalized historical dataset;
-   basic point-in-time snapshots;
-   data-quality checks;
-   one complete historical season.

Acceptance criterion:

> One historical season can be reconstructed without manual
> intervention.

------------------------------------------------------------------------

## V0.7.1 --- Prediction backtesting

Deliver:

-   historical feature reconstruction;
-   xP prediction generation;
-   xM/minutes evaluation;
-   availability evaluation;
-   prediction metrics;
-   first research report.

Acceptance criterion:

> We can calculate prediction performance for every supported
> player/Gameweek in the selected historical dataset without future-data
> leakage.

------------------------------------------------------------------------

## V0.7.2 --- Decision backtesting

Deliver:

-   sequential simulated squad state;
-   transfers;
-   transfer costs;
-   lineup;
-   captaincy;
-   actual points;
-   baseline strategies.

Acceptance criterion:

> We can replay a complete historical season as a deterministic FPL
> manager simulation.

------------------------------------------------------------------------

## V0.7.3 --- Optimizer evaluation

Deliver:

-   current optimizer integrated into backtesting;
-   exhaustive/small-space validation where feasible;
-   comparison against simple baselines;
-   transfer-efficiency metrics.

Acceptance criterion:

> We can quantify whether the optimizer improves on simple deterministic
> strategies.

------------------------------------------------------------------------

## V0.7.4 --- LLM A/B evaluation

Deliver:

-   deterministic-only experiment;
-   deterministic + LLM experiment;
-   provider/model tracking;
-   prompt-version tracking;
-   LLM decision logging;
-   invalid-output metrics.

Acceptance criterion:

> We can quantitatively determine whether the LLM improves the
> deterministic decision system.

------------------------------------------------------------------------

## V0.7.5 --- Multi-season validation

Deliver:

-   second historical season;
-   cross-season evaluation;
-   temporal train/test separation if model fitting has begun;
-   robustness analysis.

Acceptance criterion:

> Major conclusions do not depend entirely on one historical season.

------------------------------------------------------------------------

# 30. Definition of done

V0.7 should not be considered complete merely because a historical
dataset exists.

The minimum definition of done is:

### Data

-   [ ] Historical dataset acquired.
-   [ ] Data normalized.
-   [ ] Point-in-time snapshots implemented.
-   [ ] Data-quality validation implemented.
-   [ ] No known future-data leakage.

### Prediction

-   [ ] Historical xP can be generated.
-   [ ] xP vs actual points evaluated.
-   [ ] xM/expected minutes evaluated.
-   [ ] Availability evaluated.
-   [ ] Metrics stored reproducibly.

### Decision engine

-   [ ] Historical squad state can be reconstructed.
-   [ ] Transfers can be simulated sequentially.
-   [ ] Transfer costs are accounted for.
-   [ ] Lineups are simulated.
-   [ ] Captaincy is simulated.
-   [ ] Actual points are calculated.

### Baselines

-   [ ] No-transfer baseline.
-   [ ] Simple xP baseline.
-   [ ] Current optimizer.
-   [ ] Optional LLM-assisted strategy.

### LLM

-   [ ] Provider/model recorded.
-   [ ] Prompt version recorded.
-   [ ] Outputs logged.
-   [ ] Invalid recommendations measured.
-   [ ] Deterministic validation remains authoritative.

### Research

-   [ ] Results are reproducible.
-   [ ] Results are exportable.
-   [ ] At least one complete-season report exists.
-   [ ] At least one cross-season validation is performed before drawing
    strong conclusions.
-   [ ] Failure modes are documented.

------------------------------------------------------------------------

# 31. What V0.7 should NOT attempt

To keep the milestone focused, do not make these mandatory V0.7
deliverables:

-   sophisticated news sentiment;
-   press-conference ingestion;
-   social-media sentiment;
-   complex ownership modelling;
-   rank-aware optimization;
-   advanced chips strategy;
-   complete injury prediction;
-   real-time LLM agents;
-   autonomous decision execution;
-   large GUI redesign;
-   multi-provider LLM framework beyond what is needed for experiments.

These may become V0.8, V0.9, V1.0 or later depending on the evidence
produced by V0.7.

------------------------------------------------------------------------

# 32. Suggested repository structure

The exact structure should follow the existing repository, but
conceptually:

``` text
data/
    historical/

src/fpl_manager/
    historical/
        ingestion.py
        snapshots.py
        reconstruction.py
    backtest/
        engine.py
        strategies.py
        metrics.py
        reporting.py

tests/
    test_historical.py
    test_backtest.py
    test_backtest_no_leakage.py
    test_strategies.py

docs/
    v07/
        v07_plan.md
        v07_data_model.md
        v07_experiments.md
        v07_results.md
```

Do not create this structure blindly. Reuse existing modules where they
already provide an appropriate abstraction.

------------------------------------------------------------------------

# 33. Development sequence

The recommended implementation order is:

``` text
1. Audit current data interfaces
        ↓
2. Define historical data contract
        ↓
3. Acquire one historical season
        ↓
4. Build point-in-time snapshots
        ↓
5. Validate snapshots
        ↓
6. Reconstruct current xP inputs
        ↓
7. Backtest xP/xM
        ↓
8. Build sequential manager simulation
        ↓
9. Add simple baselines
        ↓
10. Integrate current optimizer
        ↓
11. Validate optimizer results
        ↓
12. Add LLM A/B testing
        ↓
13. Add second season
        ↓
14. Cross-season analysis
        ↓
15. Document failure modes
        ↓
16. Define V0.8 priorities from evidence
```

This ordering minimizes wasted work.

------------------------------------------------------------------------

# 34. The most important architectural decision

The historical backtester should become a **first-class deterministic
subsystem**, not a collection of analysis notebooks.

We want:

``` text
historical data
      ↓
reproducible snapshot
      ↓
production model
      ↓
production optimizer
      ↓
production rules
      ↓
simulated outcome
      ↓
metrics
```

This means that future changes to the production decision engine can
automatically be evaluated against historical data.

That is the foundation for all subsequent model development.

------------------------------------------------------------------------

# 35. Expected V0.7 outcome

At the end of V0.7, we should be able to answer questions such as:

### Prediction

> How accurate is our xP model?

### Minutes

> How accurate is our expected-minutes model?

### Availability

> How well do we model player availability?

### Optimization

> Does our optimizer outperform simple xP-based strategies?

### Transfers

> Are additional transfers worth their cost?

### Captaincy

> Does the optimizer select better captains than a simple baseline?

### LLM

> Does the LLM improve the deterministic recommendation?

### Robustness

> Do these conclusions hold across multiple seasons?

Those answers are much more valuable than simply adding another feature.

------------------------------------------------------------------------

# 36. V0.8 decision gate

V0.7 should finish with an evidence-based decision gate.

For each major component:

``` text
Component
    ↓
Backtest
    ↓
Metric
    ↓
Failure analysis
    ↓
Decision
```

Possible decisions:

``` text
KEEP
```

if performance is satisfactory.

``` text
CALIBRATE
```

if the concept is good but parameters need adjustment.

``` text
REDESIGN
```

if systematic failure is identified.

``` text
REMOVE
```

if the component does not provide measurable value.

The V0.8 roadmap should be derived from these findings rather than
predetermined assumptions.

------------------------------------------------------------------------

# 37. Final V0.7 philosophy

The transition should be:

``` text
V0.65
Stabilize the system
        ↓
V0.7
Measure the system
        ↓
V0.8+
Improve the system based on evidence
```

The most important deliverable of V0.7 is therefore not a new algorithm.

It is a trustworthy experimental framework that allows us to say:

> **"We know what information was available, we know what the system
> predicted, we know what decision it made, we know what actually
> happened, and we can reproduce the comparison."**

Once that exists, improvements to xP, xM, the optimizer, and the LLM
become measurable engineering/research problems rather than guesswork.
