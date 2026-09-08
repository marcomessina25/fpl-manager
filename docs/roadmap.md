# FPL Manager roadmap

> **Living document.** This is the source of truth for delivery status, engineering priorities, release criteria, known risks, and long-term direction. Human contributors and AI agents must read it before material work and update it when priorities or milestone status changes.
>
> **Current planning baseline:** V0.6 has been implemented on the `v6` branch, but it is **not yet considered PR-ready**. The current v0.6 OpenRouter integration must be removed from the release candidate before merging. V0.65 is the stabilization/bug-fix milestone following that removal. A future free LLM provider should be integrated only after a real end-to-end API test proves that it works with the application.

See `docs/architecture.md` and `docs/expected_points.md` for the deeper architecture and projection-model design.

---

## 0. Executive roadmap

The project is evolving from a deterministic FPL calculation engine into a complete **FPL decision-support and experimentation platform**.

The long-term objective is not simply to produce player rankings. The system should answer:

- What should I do this Gameweek?
- What are the best legal alternatives?
- How much expected value does each action provide?
- What is the risk of each action?
- How does ownership/Effective Ownership affect rank exposure?
- What is the best 3–6 GW strategy rather than the best isolated GW?
- When should chips be deployed?
- How did the recommendation perform?
- Was the model actually better than the human decision?
- Which parts of the model are systematically wrong?
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
Model improvement
```

### Immediate release path

```text
v0.6 current v6 branch
        │
        ├── remove OpenRouter from release candidate
        ├── run stabilization / regression tests
        ↓
v0.6 PR
        │
        ↓
v0.65
        ├── bug audit
        ├── state-transition hardening
        ├── integration tests
        ├── xP correctness audit
        └── optional validated OpenRouter restoration
        │
        ↓
v0.7
        ├── historical backtesting
        ├── calibration
        ├── minutes model
        └── first serious predictive-model iteration
        │
        ↓
v0.8
        ├── football information layer
        ├── rank-aware optimization
        ├── improved uncertainty
        └── stronger chip / multi-GW planning
        │
        ↓
v0.9
        ├── closed-loop evaluation
        ├── model-vs-human experiments
        ├── provider abstraction
        └── production hardening
        │
        ↓
v1.0
        └── stable FPL decision-support platform
```

---

# Delivery phases

## V0.1 — Trustworthy FPL data and rules foundation

**Status: completed on 2026-09-03.**

### Scope

- Download official FPL `bootstrap-static` and `fixtures` data.
- Preserve timestamped raw payloads.
- Normalize data into local SQLite snapshots.
- Represent players and validate a complete 15-player squad.
- Validate a legal 11-player starting lineup and formation.
- Generate machine-readable snapshot summaries.
- Establish deterministic transfer validation.
- Keep private squad configuration out of Git.

### Completed

- Python package scaffold using Python 3.12.
- `fpl update` and `fpl report`.
- Local SQLite snapshot store.
- Raw-data archive.
- Deterministic squad and starting-lineup validation.
- Initial rule tests.
- Private Git-ignored current-squad JSON format and example template.
- Deterministic transfer validation covering position, bank, club-limit, and transfer-hit checks.
- CLI transfer validation with integer IDs and name resolution.
- SQLite persistence tests.
- Squad import utility and `fpl import-squad`.
- Live/private squad transfer-validation smoke testing.

### Exit criteria

- No known correctness issue in basic squad/lineup/transfer rules.
- Snapshot data can be reproduced locally.
- Tests cover the fundamental invariants.

---

## V0.2 — Decision-support basics

**Status: completed on 2026-09-03.**

### Delivered

- Detailed current-squad reporting.
- Player purchase/current/selling prices.
- Team breakdown.
- Bank and team value.
- Free transfers.
- Remaining chips.
- Hard squad-rule validation.
- Fixture analysis.
- Transparent FDR difficulty rankings.
- Multi-gameweek fixture ticker.
- `--squad-only` filtering.
- Automated legal transfer candidate generation.
- 1-, 2-, and 3-transfer recommendations.
- xP baseline model.
- Availability discounting.
- Position-aware FDR adjustments.
- Home/away multiplier.
- Starting-XI optimizer.
- Captain and vice-captain selection.
- Bench ordering.
- Independent lineup legality verification.
- JSON reports.

### Historical note

Four-transfer brute-force search was initially too slow; this limitation was subsequently addressed in V0.3 through a faster branch-and-bound transfer solver.

---

## V0.3 — Projections and optimisation

**Status: completed on 2026-09-04.**

### Delivered

#### Expanded data and storage

Added:

- expected goals
- expected assists
- expected goal involvements
- expected goals conceded
- per-90 metrics
- minutes
- starts
- BPS
- ICT index
- news
- Gameweek event/deadline information

SQLite schema migrations were introduced so the application can evolve without destroying existing local data.

#### Component-based xP / xM

Introduced:

- expected minutes (`xM`)
- probability of starting
- probability of 60+ minutes
- substitute-appearance probability
- appearance points
- attacking contribution
- defensive contribution
- clean-sheet expectation
- goals-conceded penalties
- bonus expectation
- disciplinary deductions
- floor
- ceiling
- variance / standard deviation

Risk profiles:

- `neutral`
- `floor`
- `ceiling`

#### Transfer optimizer

Introduced recursive branch-and-bound search for 1–5 transfers with:

- symmetry breaking
- budget pruning
- upper-bound pruning
- club-limit constraints
- transfer-hit accounting

#### Wildcard / Free Hit optimizer

Introduced:

- feasible greedy initialization
- 1-opt local improvement
- 2-opt cross-position improvement
- legal squad construction
- starting-XI optimization

**Important terminology:** this is a heuristic/local-search optimizer, not a proof of global optimality. Future documentation and UI wording should preserve that distinction unless an exact solver is introduced.

#### Multi-Gameweek planner

Introduced beam search over 3–6 Gameweeks with:

- roll decisions
- free-transfer banking
- 1-transfer actions
- 2-transfer actions
- optional hits
- risk profiles
- weekly timelines
- cumulative projected net xP

---

## V0.4 — Evaluation, research, and strategic risk

**Status: completed on 2026-09-04.**

### Delivered

#### Decision logging and audit trail

- Persistent pre-deadline decisions.
- Gameweek-linked squad state.
- Historical Gameweek logging.
- Explicit 15-player squad input.
- Starting XI.
- Bench order.
- Captain / vice-captain.
- Executed transfers.
- Transfer-hit calculation.
- Point-in-time model recommendations.
- Human-vs-model divergence tracking.
- Actual-points recording.
- Deterministic legality checks before persistence.

#### Live score ingestion

- Official FPL live scores.
- Local SQLite score cache.
- Raw timestamped score payloads.
- Granular minutes/goals/assists/clean-sheet/bonus/BPS data.
- Offline/future/incomplete-GW handling.

#### Evaluation

- Point-in-time xP vs actual-point backtesting.
- MAE.
- RMSE.
- Spearman rank correlation.
- Tied-rank handling.
- Uncertainty interval coverage.
- Captaincy regret.
- Bench regret.
- Human-vs-model lineup comparison.
- Multi-GW/season aggregation.
- Systematic over-/under-prediction tracking.

#### Ownership and strategic risk

- Estimated ownership.
- Estimated captaincy share.
- Effective Ownership.
- `SHIELD`.
- `SWORD`.
- `CORE`.
- Net rank exposure.

#### Chip strategy

- GW1–19 and GW20–38 segmentation.
- Chip reset between halves.
- Used-chip detection from decision logs.
- Blank detection.
- Double detection.
- Blank-and-double detection.
- Squad impact analysis.
- Empirical chip valuation.
- Conflict-free deployment schedules.

---

## V0.5 — GUI and multi-team management

**Status: completed on 2026-09-04.**

### Delivered

#### Multi-team management

- Multiple isolated team workspaces.
- Per-team `squad.json`.
- Per-team metadata.
- Team names.
- Manager names.
- Optional FPL team IDs.
- Active-team pointer.
- Backwards compatibility with the legacy default squad.
- Team creation.
- Team cloning.
- Team switching.
- Team-specific historical decision/evaluation data.

#### GUI

Delivered a local browser-based dashboard containing:

- team switcher
- team creator
- dashboard
- visual football pitch
- formation display
- player cards
- FDR
- xP
- ownership role
- captain/vice-captain
- financial HUD
- interactive decision logging
- transfer builder
- transfer recommendations
- wildcard/free-hit studio
- multi-GW planner
- chip strategy
- evaluation hub

---

# V0.6 — Analytical briefing, live matchday, and optional LLM

**Status: functionally implemented on `v6`, but NOT PR-ready.**

The current v6 branch contains the V0.6 feature set, but release status must remain **candidate / stabilization required** until the OpenRouter issue is resolved by removal from the release candidate and the remaining regression audit is completed.

### Delivered

#### Analytical briefing

- Structured manager dossier.
- Human-readable manager briefing.
- Squad health.
- Starting XI.
- Captaincy.
- Injury/status information.
- News.
- Ownership risks.
- Transfer recommendations.
- Chip schedules.

#### Live matchday tracker

- Live gross points.
- Net points.
- Transfer hits.
- Captain multiplier.
- Triple Captain.
- Bench Boost.
- Dynamic autosub simulation.
- Formation legality during autosubs.
- Live player statistics.
- Effective-ownership leverage.
- Rank-acceleration indicators.

#### LLM advisor

- Gemini provider.
- OpenAI provider.
- OpenRouter provider in the current branch.
- Offline heuristic fallback.
- Devil's Advocate persona.
- Tactical Analyst persona.
- Strategic Planner persona.
- Structured response parsing.
- Deterministic captaincy validation.
- Deterministic transfer validation.
- Explicit legality errors.

#### GUI

- Live Matchday panel.
- AI Advisor panel.
- Briefing/dossier display.
- Provider selection.
- Persona selection.
- Key visibility controls.
- Apply actions workflow.

### V0.6 release policy

**Do not merge the current OpenRouter implementation into the V0.6 PR.**

The V0.6 PR should contain the feature set with OpenRouter removed or disabled from the public release path.

Gemini, OpenAI, and the offline heuristic engine may remain according to the release design, but the project must not require a paid provider for basic operation.

The offline heuristic advisor remains the guaranteed zero-cost fallback.

### OpenRouter follow-up

OpenRouter should not be treated as permanently rejected.

The current implementation can be reintroduced only after:

1. confirming the API endpoint and authentication behavior against current OpenRouter documentation;
2. selecting a currently available model explicitly;
3. testing a real key against the exact request made by the application;
4. testing invalid-key behavior;
5. testing rate-limit behavior;
6. testing model-unavailable behavior;
7. testing response parsing;
8. testing GUI-to-server key handling;
9. confirming that no key is logged or persisted accidentally;
10. adding provider-specific automated tests.

OpenRouter currently exposes an OpenAI-compatible `/api/v1/chat/completions` API and free model variants/router, but free-model availability and rate limits can change. Therefore the application should not hard-code an assumption that a particular model remains free or available indefinitely.

---

# V0.65 — Stabilization, bug audit, and release hardening

**Status: planned immediately after the V0.6 PR.**

See `docs/v065_potential_bugs.md`.

V0.65 is intentionally smaller than a feature release.

The goal is:

> **Make V0.6 trustworthy before adding major new intelligence.**

### Priority A — release-blocking correctness

- Remove OpenRouter from the V0.6 PR candidate.
- Verify all remaining LLM providers.
- Verify heuristic fallback.
- Verify `auto` routing when providers are unavailable.
- Verify malformed LLM JSON.
- Verify illegal LLM transfers.
- Verify illegal captain/vice-captain recommendations.
- Verify API failures never corrupt squad state.
- Verify transfer execution is atomic from the user's perspective.
- Verify undo restores the exact previous state.
- Verify purchase prices survive transfer/undo sequences.
- Verify free-transfer counts across sequential operations.
- Verify transfer-hit calculations.
- Verify chip interactions.
- Verify current-GW vs historical-GW decision logging.
- Verify team isolation.
- Verify active-team switching.
- Verify lineup legality after transfer execution.
- Verify autosub formation legality.
- Verify captain auto-promotion.
- Verify Triple Captain and Bench Boost.
- Verify live-score ingestion and stale/incomplete data handling.

### Priority B — quantitative correctness audit

- Verify availability is applied exactly once where intended.
- Add explicit tests for 100%, 75%, 50%, and 0% availability.
- Verify expected minutes never exceed legal bounds.
- Verify start/sub probabilities remain internally consistent.
- Verify appearance probabilities sum logically.
- Verify component xP and baseline xP do not unintentionally apply the same adjustment twice.
- Verify clean-sheet probabilities are bounded.
- Verify negative point components behave correctly.
- Verify FDR multipliers.
- Verify venue multipliers.
- Verify position-specific scoring.
- Verify goalkeeper treatment.
- Verify bonus estimates.
- Verify floor/ceiling/sigma semantics.
- Document that current uncertainty outputs are heuristic estimates, not empirically calibrated percentiles.

### Priority C — optimizer correctness

- Compare branch-and-bound transfer results against exhaustive enumeration on small synthetic pools.
- Verify 1–5 transfer search.
- Verify cross-position multi-transfer alignment.
- Verify club limits after every transfer.
- Verify bank/selling-price handling.
- Verify hit counts are applied exactly once.
- Verify wildcard/free-hit solutions are legal.
- Verify wildcard/free-hit optimizer does not claim global optimality.
- Add deterministic regression fixtures.

### Priority D — integration tests

Create complete end-to-end scenarios:

1. update → squad → lineup → decision log;
2. decision → transfer → lineup → decision;
3. multiple transfers → bank/FT/hit verification;
4. transfer → undo → exact state restoration;
5. team switch → independent state;
6. historical GW logging without changing current squad;
7. live scores → autosubs → captain → net score;
8. LLM recommendation → deterministic validation;
9. provider failure → heuristic fallback;
10. chip usage → chip availability and strategy state.

### Priority E — GUI/API hardening

- State-changing endpoints must fail safely.
- Avoid exposing secrets through logs/errors.
- Confirm API keys are never persisted.
- Review CORS behavior.
- Review localhost/network exposure.
- Ensure long-running advisor calls do not hang the GUI.
- Add request timeout behavior.
- Add clear provider error messages.
- Ensure partial failures do not leave stale UI state.
- Verify all "Apply" buttons have deterministic success/failure feedback.

### V0.65 optional OpenRouter track

OpenRouter may be restored in V0.65 **only if it passes a real provider acceptance test**.

If it does not, defer it to V0.7 or later.

Do not allow the provider to block the stabilization release.

---

# V0.7 — Historical backtesting and predictive-engine validation

**Priority: highest after V0.65.**

This is the first major research milestone.

The project must transition from:

> "The model looks sensible."

to:

> "The model demonstrably predicts better than simple baselines."

### 0.7.1 Point-in-time dataset

Build a historical dataset containing, for each Gameweek:

- players available before deadline;
- prices at the decision point;
- ownership;
- FPL status;
- chance of playing;
- minutes;
- starts;
- xG/xA and related metrics available at that point;
- fixtures;
- FDR;
- team strength;
- actual GW outcomes;
- manager decisions where available.

### Critical rule: no future leakage

For a GW N prediction, the model may only use information that would have been available before the GW N deadline.

Do not use:

- final GW statistics;
- future injury information;
- future price changes;
- future ownership;
- post-deadline team news;
- future fixtures/results;
- later versions of the same statistic.

Point-in-time integrity is more important than model complexity.

### 0.7.2 Baselines

Compare the full model against simple baselines:

- previous PPG;
- season PPG;
- form;
- price;
- xG90;
- xA90;
- xGI90;
- simple FDR-adjusted xP;
- simple minutes-adjusted xP.

The complicated model must beat meaningful baselines before complexity is justified.

### 0.7.3 Calibration

Measure:

- xP MAE;
- xP RMSE;
- rank correlation;
- prediction bias;
- calibration by xP bucket;
- calibration by position;
- calibration by price;
- calibration by minutes;
- calibration by availability;
- calibration by FDR;
- calibration by Gameweek horizon.

### 0.7.4 Minutes model

Prioritize minutes prediction.

Estimate:

- probability of starting;
- probability of 1–59 minutes;
- probability of 60+ minutes;
- expected minutes.

Candidate features:

- recent starts;
- recent minutes;
- starts/minutes ratio;
- manager selection patterns;
- price;
- position;
- injury status;
- suspension;
- fixture congestion;
- European matches;
- recent rotation;
- team strength;
- historical role.

### 0.7.5 Match-event model

Move from coarse multipliers toward probabilistic components:

- probability of appearance;
- expected goals;
- expected assists;
- probability of clean sheet;
- expected goals conceded;
- probability of bonus;
- card probability.

The objective is not necessarily maximum model sophistication; it is improved out-of-sample accuracy.

### 0.7.6 Uncertainty

Replace the current Gaussian-style heuristic interpretation with empirically evaluated distributions.

Potential outputs:

- P10;
- P25;
- median;
- P75;
- P90;
- expected value;
- variance.

If a normal approximation remains useful, it must be treated as an approximation and validated empirically.

### 0.7.7 Model registry

Introduce versioned model metadata:

```text
model_version
training_data_cutoff
feature_set_version
parameter_version
prediction_timestamp
```

Every decision should be traceable to the exact model configuration that generated it.

---

# V0.8 — Rank-aware decision optimisation and football context

Once the predictive engine is reasonably calibrated, improve the decision objective.

## 0.8.1 Rank-aware optimisation

Move beyond pure expected points.

Candidate objectives:

```text
Expected points
Expected rank gain
Expected rank loss
Probability of beating benchmark
Probability of top-k finish
Downside percentile
Risk-adjusted utility
```

Possible generic utility:

```text
U =
    expected_points
  + α × rank_leverage
  - β × downside_risk
  - γ × transfer_cost
```

The coefficients should be configurable by strategy.

### Risk profiles

#### Neutral

Maximize expected outcome.

#### Floor

Protect rank and minimize downside.

#### Ceiling

Accept variance for upside.

#### Defend lead

Prioritize minimizing catastrophic rank loss.

#### Chase

Prioritize probability of large rank gain.

## 0.8.2 Effective Ownership

Improve the ownership model from broad estimates toward:

- actual available EO data where obtainable;
- benchmark population definition;
- captaincy distribution;
- ownership uncertainty;
- rank-sensitive leverage.

Avoid presenting inferred EO as exact league data.

## 0.8.3 Football information layer

Add structured external information:

- press conferences;
- injury reports;
- expected lineups;
- suspension news;
- manager comments;
- tactical changes;
- set-piece responsibilities;
- penalty responsibilities;
- rotation risk;
- fixture congestion.

The information pipeline should distinguish:

```text
FACT
INFERENCE
RUMOUR
MODEL ASSUMPTION
```

Every external observation should carry:

- source;
- timestamp;
- confidence;
- affected player/team;
- expiry/relevance window.

## 0.8.4 LLM as qualitative analyst

The LLM should not become the numerical optimizer.

Preferred flow:

```text
Deterministic engine
       ↓
5–20 viable strategies
       ↓
structured comparison
       ↓
LLM critique
       ↓
qualitative evidence
       ↓
deterministic validation
       ↓
human decision
```

The LLM should explain:

- tactical context;
- injury uncertainty;
- rotation risk;
- set pieces;
- fixture-specific factors;
- hidden assumptions;
- potential traps.

---

# V0.9 — Closed-loop experimentation and production hardening

## 0.9.1 Model-vs-human experiments

For every decision, record:

- model recommendation;
- human recommendation;
- final decision;
- alternatives considered;
- projected xP;
- actual points;
- rank impact.

Measure over time:

- human score;
- model score;
- hybrid score;
- difference;
- regret;
- decision confidence.

## 0.9.2 Counterfactual analysis

For each GW:

- what the model recommended;
- what the human chose;
- what would have happened under each;
- what the best legal decision was after the fact.

Important:

Counterfactual analysis must clearly label hindsight results as hindsight.

## 0.9.3 Transfer ROI

Track:

```text
gross gain
hit cost
net gain
one-GW ROI
three-GW ROI
five-GW ROI
```

Also distinguish:

- transfer itself;
- captaincy;
- lineup;
- chip.

## 0.9.4 Chip ROI

Evaluate actual chip usage against:

- rolling;
- alternative GW;
- best hindsight GW;
- model recommendation.

## 0.9.5 Software hardening

- configuration abstraction;
- provider interface;
- typed API models;
- improved logging;
- structured errors;
- transaction-like state updates;
- better concurrency handling;
- migration tests;
- reproducible environment;
- CI;
- linting/type checks;
- regression fixtures.

## 0.9.6 Security

- local-only default;
- explicit bind address;
- safe CORS defaults;
- secret redaction;
- no API-key persistence;
- no API-key logging;
- provider-specific secret handling;
- clear trust boundary documentation.

---

# V1.0 — Stable FPL decision-support platform

V1.0 should not mean "every possible feature exists."

It should mean:

> **The existing feature set is stable, reproducible, tested, measurable, and demonstrably useful.**

### V1.0 acceptance criteria

#### Data

- Reliable FPL ingestion.
- Point-in-time snapshots.
- Historical reproducibility.
- Safe migrations.

#### Rules

- Complete squad legality.
- Starting XI legality.
- Transfer legality.
- Hit accounting.
- Chip accounting.
- Autosub rules.

#### Quantitative model

- Backtested.
- Baseline-comparison results documented.
- Calibration measured.
- Model versioning implemented.
- Known limitations documented.

#### Optimisation

- Transfer optimizer verified.
- Wildcard optimizer correctly described.
- Multi-GW planner tested.
- Risk profiles tested.
- Rank-aware objectives documented if implemented.

#### LLM

- Provider abstraction.
- At least one reliable external provider.
- Guaranteed heuristic fallback.
- Deterministic guardrails.
- No direct uncontrolled squad mutation.
- Clear source/context boundary.

#### GUI

- No known state corruption.
- Complete manager workflow.
- Clear errors.
- Responsive long-running operations.
- Team isolation.

#### Evaluation

- Every decision can be evaluated.
- Human/model comparison works.
- Historical backtesting works.
- Season-level reports work.

---

# Long-term research tracks

These are intentionally not tied to a specific version.

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
- role/position changes.

Only add a feature if historical testing demonstrates incremental value.

## Track B — Better minutes modelling

Potential sources:

- historical lineups;
- substitution patterns;
- fixture congestion;
- manager rotation;
- injuries;
- suspensions;
- European schedules;
- tactical role;
- recent starts.

This should probably receive more research time than adding dozens of attacking metrics.

## Track C — Better fixture modelling

Replace coarse FDR with:

```text
team_attack_strength
team_defense_strength
opponent_attack_strength
opponent_defense_strength
home_advantage
```

and derive:

- expected team goals;
- expected goals conceded;
- clean-sheet probability.

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

## Track E — Squad construction

For Wildcard:

- exact mixed-integer optimisation if worthwhile;
- future transfer flexibility;
- team structure;
- price-change risk;
- fixture runs;
- bench strength;
- future chip strategy.

The objective should eventually be more than one-GW xP.

## Track F — Multi-GW planning

Potential improvements:

- dynamic re-projection;
- price-change uncertainty;
- injuries;
- future transfer opportunities;
- fixture swings;
- blank/double events;
- chip interactions;
- multiple objective functions;
- scenario trees.

## Track G — LLM strategy layer

Potential roles:

- Devil's Advocate;
- Tactical Analyst;
- Strategic Planner;
- News Synthesizer;
- Decision Reviewer;
- Post-GW Analyst.

The LLM should remain subordinate to deterministic facts and legality.

## Track H — Automated learning loop

Eventually:

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

Never automatically deploy a new model merely because it performed better on the latest few Gameweeks.

---

# Engineering principles

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

The LLM never overrides these.

## 2. No future leakage

Historical predictions must use only information available at the prediction timestamp.

## 3. Every important number should be explainable

A player xP should be decomposable into components.

## 4. Every decision should be reproducible

A decision record should identify:

- snapshot;
- model version;
- input state;
- recommendation;
- human choice;
- eventual outcome.

## 5. Prefer measured improvements

Do not add complexity without demonstrating benefit.

## 6. Keep the offline path functional

The core engine must work without an LLM API.

## 7. Provider integrations are optional

No provider should be a single point of failure.

## 8. External information must have provenance

News should carry source/time/confidence.

## 9. UI must never be the source of truth

The GUI calls domain functions; it does not duplicate business rules.

## 10. Release small, research deeply

A small V0.65 bug-fix release is preferable to another feature-heavy branch if correctness is uncertain.

---

# Testing strategy

Testing should operate at four levels.

## Unit

Pure functions:

- rules;
- selling price;
- availability;
- xM;
- xP;
- ownership;
- fixture calculations;
- hit calculation.

## Property/invariant tests

Examples:

- squad always has 15 unique players;
- squad never exceeds three players from one club;
- lineup always has 11 players;
- lineup always has at least 1 GKP / 3 DEF / 2 MID / 1 FWD;
- bank never becomes negative after a validated transfer;
- transfer hits equal `max(0, transfers - free_transfers)`;
- undo restores the prior state.

## Integration

Full workflows:

- update;
- squad;
- transfers;
- lineup;
- logging;
- scoring;
- evaluation.

## Historical regression

A fixed set of historical Gameweeks should be used as a permanent regression dataset.

---

# Release discipline

Every release should have:

1. feature list;
2. known bugs;
3. fixed bugs;
4. tests added;
5. tests passed;
6. data/schema migration notes;
7. compatibility notes;
8. model changes;
9. provider changes;
10. known limitations.

A branch should not be described as "complete" merely because its feature code exists.

Use:

- `implemented`
- `tested`
- `validated`
- `PR-ready`
- `released`

as distinct states.

---

# Immediate work queue

## Now

### 1. Prepare V0.6 PR

- remove OpenRouter;
- keep deterministic/heuristic fallback;
- keep remaining validated providers;
- update provider documentation;
- update tests;
- run complete test suite;
- review GUI advisor configuration;
- verify no OpenRouter references remain in the release path.

### 2. Create V0.65 branch

Base it on the V0.6 PR result.

### 3. Execute `docs/v065_potential_bugs.md`

Treat it as an audit checklist, not as proof that every listed issue exists.

### 4. Fix confirmed bugs

Do not change behavior speculatively without tests.

### 5. Freeze architecture

Avoid major new GUI features until V0.65 is stable.

---

# Free LLM provider strategy

The project needs at least one **actually usable zero-cost API option** for development and personal use.

The provider-selection strategy should be:

### Candidate 1 — OpenRouter free models

Keep as a candidate because OpenRouter currently exposes free models and a free-model router, but availability and rate limits are dynamic.

### Candidate 2 — Google Gemini free tier

Useful as a provider candidate, but it should not be treated as universally free forever or for every model.

### Candidate 3 — Groq free tier

Strong candidate for experimentation because its API is OpenAI-compatible and has explicit free-plan rate limits.

### Candidate 4 — other providers

Periodically investigate:

- Hugging Face inference;
- Cerebras;
- other free/open-model inference APIs.

The acceptance criterion is not "the website says free."

It is:

```text
Can create key
      ↓
Can authenticate
      ↓
Can send our exact prompt
      ↓
Can receive valid response
      ↓
Can parse response
      ↓
Can survive errors/rate limits
      ↓
Can run through GUI
      ↓
Can validate suggested actions
```

The provider must pass that complete test.

---

# Definition of "good enough"

The project should eventually optimize for **decision quality**, not technical sophistication.

The key question for every future feature is:

> Does this help us make better FPL decisions, or does it merely make the application more complicated?

Priority should therefore generally be:

```text
Correctness
    >
Data quality
    >
Prediction quality
    >
Decision quality
    >
Evaluation
    >
UX
    >
Feature count
```

---

# Current strategic priority

**The next breakthrough should come from the predictive engine and the closed-loop evaluation system, not from adding more UI or more LLM features.**

The repository already has enough infrastructure to support serious experimentation.

The goal for the next stages is therefore:

> **Make the system scientifically measurable, improve the predictive model using historical point-in-time data, and then use that improved model to drive rank-aware optimisation and LLM-assisted strategic reasoning.**
