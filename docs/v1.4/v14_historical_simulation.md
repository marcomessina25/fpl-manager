# V1.4 — Interactive Historical Season Simulation & Time Machine Sandbox Platform

**Status:** Completed (Simulation & Time Machine Sandbox Platform Delivered; Experimental Benchmark Sequence decoupled to V1.4.5 & V1.4.6)  
**Predecessor:** V1.3.5 — Optimizer Decision-Quality Study  
**Corpus / Repo:** `marcomessina25/fpl-manager`

---

## 1. Executive Summary & Vision

V1.4 transforms FPL Manager from a batch backtesting system into an **interactive historical FPL Time Machine**.

The user can enter any past Premier League season (`2021-22` through `2025-26`), receive strictly verified point-in-time information available at each historical deadline (standings, past results with actual scores, masked upcoming fixtures), make transfers and lineup adjustments, deploy chips, resolve authentic historical gameweek results with deterministic scoring and autosubs, and step through the season.

The purpose of V1.4 is to:
1. Provide a rigorous, fully isolated interactive historical simulation environment across both CLI (`fpl sim`) and Web Studio GUI (`⏳ Historical Time Machine`);
2. Deliver the software instrumentation, session state engine, and zero-spoiler data boundaries necessary for reproducible research.

> **Methodological Sequence Alignment (V1.4 → V1.4.5 → V1.4.6):**
> Following rigorous review of seasonal chip behavior in multi-season simulations, human-in-the-loop benchmark studies cannot produce trustworthy comparative metrics if the underlying chip policy relies on heuristic fixed thresholds that cause unspent chip wastage or premature burns. 
> Therefore, the empirical human benchmark originally envisioned for V1.4 is decoupled:
> - **V1.4 (Current)**: Delivers the complete simulation platform, GUI Time Machine, and zero-leakage standings/fixture engines.
> - **V1.4.5 (Next)**: Deep multi-season study designing an ML / EV-driven strategic chip optimization model without fixed thresholds.
> - **V1.4.6 (Follow-up)**: Execution of the controlled Human-in-the-Loop Replay Benchmark on top of the finalized, audited V1.4.5 optimization engine.

---

# 2. V1.4 Scientific Boundary

The historical simulator must never expose information from after the simulated deadline.

At historical Gameweek `N`, the system may use:

- snapshots available before the GW deadline;
- historical fixtures known at that time;
- historical player/team information already published;
- the frozen predictor and optimizer configuration;
- information explicitly supplied by the simulated manager.

It must not use:

- future player points;
- future injuries/suspensions;
- future lineups;
- future fixture outcomes;
- future transfer activity;
- future prices or ownership unless they were already available at the simulated timestamp.

The simulator must preserve the same point-in-time discipline established by the repository's historical research framework.

---

# 3. Baseline Engine Policy

The V1.4 simulator must use a **frozen engine selected from V1.3/V1.3.5 research**.

The selection is evidence-based rather than predetermined.

Possible configurations include:

```text
validated V1.2.5 baseline
validated V1.3 predictor + frozen optimizer
validated V1.3.5 optimizer configuration
```

The simulator must record the exact:

- predictor version;
- decision engine version;
- optimizer configuration;
- objective;
- horizon;
- solver version;
- dataset version;
- snapshot ID;
- experiment ID.

Do not change the quantitative core halfway through a human benchmark.

---

# 4. Empirical Human-in-the-Loop Study

The goal is not to predict what a human *should* score.

The goal is to measure what happens when a human manager operates the system under controlled historical information constraints.

A trial participant may be given:

- the FPL Manager quantitative projections;
- legal transfer candidates;
- optimizer recommendations;
- lineup/captain recommendations;
- chip analysis;
- structured LLM briefings if the study condition includes them;
- the historical information that was genuinely available at the simulated deadline.

The participant then makes the final decision.

Record both:

```text
software recommendation
human decision
actual historical outcome
```

This allows human-vs-engine divergence to be studied without replacing the human decision with an assumed algorithmic choice.

---

# 5. Blind Replay Protocol

A historical replay participant should not be given future outcomes for the season being replayed.

The platform should enforce:

- season isolation;
- deadline isolation;
- no future-data APIs;
- no future reports in the UI;
- no accidental display of future player points;
- immutable historical snapshot selection.

The participant should see only the state that the application intentionally exposes at that historical point.

### Important methodological constraint

Do not describe a human replay as a guaranteed lower bound for live-season performance.

A historical blind replay can establish an **observed benchmark under the defined experimental conditions**. It cannot by itself prove that live managers will perform above or below that score.

---

# 6. Historical Session State Management

Create a dedicated `HistoricalSessionState`.

### Isolation invariant

A historical simulation must never modify:

- `config/current_squad.json`;
- the live database;
- existing multi-team configuration;
- live decision logs.

Simulation state should live under:

```text
config/simulations/<session_id>.json
```

Each session tracks:

- `session_id`;
- season;
- current GW;
- squad;
- purchase price;
- selling price;
- bank;
- free transfers;
- chips;
- transfers;
- lineup;
- captain/vice-captain;
- resolved GW history;
- experiment metadata.

---

# 7. Historical Squad Creation

At GW1 the user can choose among validated starting-state policies.

Examples:

- baseline engine squad;
- maximum expected value;
- balanced;
- high floor;
- high ceiling;
- future flexibility;
- manually constructed squad.

The UI must clearly identify whether a squad was:

```text
engine-generated
human-modified
fully human-created
```

If the user modifies an engine-generated squad, the exact final squad becomes the simulation's authoritative starting state.

The starting-state predictor and the evaluation predictor must remain separate in provenance.

---

# 8. Deterministic Historical Matchday Resolution

Use archived historical data from:

```text
data/historical/<season>/gws/gw<N>.json
```

Implement official FPL scoring rules already supported by the repository.

### Auto-substitutions

- a starter with zero minutes can be replaced by a bench player;
- bench order is respected;
- formation legality is preserved;
- goalkeeper replacement follows the goalkeeper rule.

### Captaincy

- captain receives `2x` points;
- Triple Captain receives `3x` points;
- if captain plays zero minutes, the vice-captain receives the multiplier.

### Transfer hits

- extra transfers beyond available free transfers incur the official hit amount;
- hit accounting is explicit in the session ledger.

### Chips

- Bench Boost includes eligible bench points;
- Free Hit restores the pre-chip squad state after the GW;
- Wildcard and other chips follow the archived rules applicable to the simulated season.

Season-specific rule differences must be represented explicitly rather than assuming current rules apply retroactively.

---

# 9. Inter-Gameweek Loop

At the end of each GW:

```text
Resolve historical matches
        ↓
Apply scoring / autosubs / captaincy
        ↓
Update squad state
        ↓
Update bank / free transfers / chips
        ↓
Persist immutable GW result
        ↓
Advance to next historical deadline
        ↓
Generate recommendations using only information available then
```

The next GW must not be initialized using information from the future.

---

# 10. CLI

Target commands:

```bash
fpl sim create --season 2023-24 --id my-trial-01
fpl sim list
fpl sim status --id my-trial-01
fpl sim transfers --id my-trial-01
fpl sim make-transfer <out_id>:<in_id> --id my-trial-01
fpl sim lineup --starters "..." --captain "..." --vc "..." --id my-trial-01
fpl sim play-chip <chip_name> --id my-trial-01
fpl sim run-gw --id my-trial-01
fpl sim report --id my-trial-01 --export-markdown
```

Command names may change during implementation, but all state transitions must remain explicit and auditable.

---

# 11. Web Studio GUI

Provide a dedicated **Historical Simulation / Time Machine** workspace.

Core components:

- season selector;
- simulation-session selector;
- historical deadline/state header;
- squad/pitch view;
- bank and free-transfer display;
- transfer recommendation panel;
- lineup/captain panel;
- chip panel;
- manager decision confirmation;
- Run GW control;
- GW result summary;
- season-progress chart;
- engine-vs-human comparison.

The UI must make the historical timestamp visible enough that a participant understands which information state they are operating in.

---

# 12. Season Finale Analytics

At GW38 generate:

- total points;
- net points after hits;
- transfer count;
- transfer-hit cost;
- captain points;
- captain regret;
- bench points left behind;
- autosub events;
- chip timing;
- chip returns;
- bank trajectory;
- squad-value trajectory;
- engine-vs-human decision divergence;
- cumulative points curve.

Export:

```text
JSON
Markdown
CSV
```

under:

```text
reports/simulations/
```

---

# 13. Human-vs-Engine Benchmark

Each simulation should retain both:

```text
Engine recommendation
Human final decision
Historical realized outcome
```

This allows analysis of:

- when humans override the engine;
- when overrides help;
- when overrides hurt;
- whether the human adds value in particular decision classes;
- whether the engine systematically fails in particular states.

The study should report observations without assuming that one participant or one replay represents all FPL managers.

---

# 14. V1.4 Research Tracks

### Track A — Engine-only replay

The frozen engine makes all decisions.

Purpose:

- validate the simulator;
- verify parity with batch backtests;
- detect simulation-state bugs.

### Track B — Human + engine replay

The engine recommends; the human decides.

Purpose:

- measure human/engine divergence;
- study override value;
- evaluate the complete decision-support workflow.

### Track C — Human-only replay (optional)

The human receives the historical information state but not engine recommendations.

Purpose:

- provide a direct human baseline where feasible.

Any comparison between tracks must preserve the same season, information boundary, and starting-state policy.

---

# 15. Simulator Validation Before Human Trials

Before any human benchmark, the simulator must pass an automated parity suite.

For historical seasons/GWs where batch backtests already exist:

```text
batch engine result
        ==
historical simulator engine-only result
```

within explicitly documented numerical tolerances.

Validate at minimum:

- squad state transitions;
- transfer legality;
- bank accounting;
- free-transfer rollover;
- hits;
- captaincy;
- vice-captain fallback;
- autosubs;
- formation legality;
- chip state transitions;
- Free Hit restoration;
- Wildcard persistence;
- historical price/selling-price rules.

No human study should start before this parity gate passes.

---

# 16. Deliverables

Expected V1.4 artifacts:

```text
docs/v1.4/v14_historical_simulation.md
reports/simulations/<session>/...
scripts / CLI commands for simulation management
historical simulation test suite
human-study protocol
final benchmark report
```

The PR should include the experimental protocol and the exact configuration used for any reported human benchmark.

---

# 17. Definition of Done for V1.4
 
 V1.4 is complete when:
 
 - [x] historical sessions are isolated from live state;
 - [x] all supported seasons (`2021-22` to `2025-26`) can be loaded;
 - [x] historical GW state is point-in-time isolated;
 - [x] squad creation is deterministic and/or explicitly human-controlled;
 - [x] transfer legality is enforced with club quotas and financial accounting;
 - [x] lineup/captain/bench state is persisted;
 - [x] official scoring and autosubs are resolved correctly;
 - [x] chip state transitions are correctly maintained (Wildcard windows, Free Hit squad reversion);
 - [x] batch/simulator parity passes;
 - [x] CLI workflow works end-to-end (`fpl sim create/list/status/overview/transfer/chip/run-gw/report`);
 - [x] GUI workflow works end-to-end (Time Machine workspace with Standings, Past Results, Upcoming Fixtures with zero spoilers);
 - [x] engine-only historical replay reproduces the frozen baseline;
 - [x] human decisions are stored separately from engine recommendations;
 - [x] no future information leaks into the simulation (strict zero-spoiler discipline);
 - [x] human benchmark protocol is documented and scheduled for execution in V1.4.6 (following V1.4.5 strategic chip optimization).

---

# 18. Milestone Sequencing

The updated release architecture is:

```text
V1.3 / V1.3.5
Predictor & optimizer research baseline
        ↓
V1.4 (Current Release)
Historical Season Simulation & Time Machine Sandbox Platform
        ↓
V1.4.5
Multi-Season Strategic Chip Optimization Study (ML / EV Optimization)
        ↓
V1.4.6
Empirical Human-in-the-Loop Replay Benchmark Execution
        ↓
V1.5
Multi-provider / combinatorial advisory research
```

This ensures that human benchmark participants are evaluated against a rigorously optimized baseline engine rather than heuristic threshold artifacts.
