# V0.65 Potential Bugs & Stabilization Report

> **Purpose:** This document is the V0.65 stabilization checklist for the FPL Manager V0.6 release candidate.
>
> It is intentionally a **potential-bugs report**, not a statement that every item is definitely broken. Each item must be reproduced, tested, classified, and either fixed or explicitly closed as not reproducible.
>
> **Release context:** The current `v6` branch contains the V0.6 feature set. Before the V0.6 PR, the OpenRouter integration should be removed from the release candidate. V0.65 is then the dedicated stabilization milestone. OpenRouter may be restored in V0.65 only if the integration is independently validated end-to-end.

---

# 1. Executive summary

V0.6 is the first release that combines:

- multi-team state;
- interactive GUI;
- transfer execution;
- decision logging;
- undo;
- live scores;
- autosub simulation;
- ownership/rank analytics;
- analytical briefing;
- LLM advice.

That combination creates a new class of risks.

The core concern is no longer just:

> "Does this function return the right value?"

It is:

> "Can a user perform a complete FPL workflow without corrupting squad state, recording an incorrect decision, or receiving a misleading analytical result?"

The most important V0.65 areas are:

1. **state integrity**
2. **transfer/FT/hit accounting**
3. **lineup and autosub legality**
4. **xP/xM correctness**
5. **LLM provider failure behavior**
6. **team isolation**
7. **live-score correctness**
8. **historical decision integrity**
9. **GUI/API consistency**
10. **test coverage of complete workflows**

---

# 2. Severity definitions

## P0 — release blocker

Could:

- corrupt squad state;
- calculate an illegal transfer;
- lose purchase-price information;
- materially miscalculate points/hits/chips;
- silently record the wrong decision;
- produce a misleading recommendation that appears deterministic;
- make the release unusable.

## P1 — high priority

Materially affects decision quality or common workflows but has a safe workaround.

## P2 — medium priority

Incorrect edge case, misleading display, robustness issue, or maintainability problem.

## P3 — low priority

Cosmetic, wording, minor UX, or non-critical technical debt.

---

# 3. V0.6 release-blocking issue: OpenRouter

## BUG-OR-RISK-001 — OpenRouter provider integration & model verification

**Severity:** P0

**Disposition:** `VERIFIED`

**Current state:** The OpenRouter provider in `src/fpl_manager/llm_advisor.py` is fully restored, integrated, and verified end-to-end with real API keys in the GUI and CLI.

Key achievements:
- **Verified Free-Capable Models:** Empirically verified to work with $0 balance API keys within provider free-tier rate limits:
  - `meta-llama/llama-3.3-70b-instruct` (recommended default)
  - `deepseek/deepseek-chat` (DeepSeek V3)
  - `openai/gpt-4o-mini`
  - `deepseek/deepseek-r1` (marked with `*` indicating paid credits required)
- **Model Pruning:** Endpoints returning 404 No Endpoints Found (e.g. Claude 3.5 Sonnet, Gemini Flash Free, Mistral Large) have been pruned from the active GUI selector and slated for investigation in V1.1.
- **Auto-Routing:** Automatically detects `sk-or-` prefixed keys or `OPENROUTER_API_KEY` to route requests to OpenRouter.
- **Robust Error Recovery:** Explicit detection of 401 Unauthorized, 429 Rate Limiting with backoff guidance, and malformed/unfenced JSON recovery.
- **Local Persistence:** Keys persist in browser storage (`localStorage`) with input sanitization and visibility toggle. Documented that users should treat local browser profiles as trusted.

### Regression Coverage

- `tests/test_llm_advisor.py::test_openrouter_payload_structure`
- `tests/test_llm_advisor.py::test_openrouter_http_error_handling`
- `tests/test_gui.py::test_advisor_with_openrouter_provider`
- End-to-end live testing with $0 balance API key in GUI and CLI.

---

# 4. Provider routing risks

## BUG-LLM-001 — `auto` routing can hide provider failures

**Severity:** P1

The current auto mode catches provider exceptions and silently tries another provider before falling back to the heuristic engine.

This is good for resilience, but can hide the fact that the selected provider is broken.

### Risk

The UI may say that advice was generated while the actual path was:

```text
Gemini failed
→ OpenAI failed
→ OpenRouter failed
→ heuristic fallback
```

### Required fix

Expose:

- provider attempted;
- provider actually used;
- failure reason at debug level;
- fallback status at user level.

Never silently present heuristic output as external-LLM output.

---

## BUG-LLM-002 — Provider availability should be explicit

**Severity:** P1

The UI should distinguish:

- configured;
- key missing;
- authenticated;
- unavailable;
- rate-limited;
- model unavailable;
- request failed;
- fallback active.

---

# 5. LLM response parsing

## BUG-LLM-003 — Markdown/JSON extraction is fragile

**Severity:** P1

The advisor extracts JSON using a regex matching a fenced object.

Potential failures:

- nested braces;
- braces inside strings;
- multiple JSON blocks;
- malformed JSON;
- prose after JSON;
- JSON without fences;
- model returning a JSON array;
- model adding commentary around the object.

### Fix

Prefer:

1. structured-output support where the provider supports it;
2. otherwise a robust JSON extraction/parser;
3. schema validation;
4. safe fallback.

---

## BUG-LLM-004 — Parsed fields are not fully schema-validated

**Severity:** P1

The LLM response contains:

- critique points;
- tactical notes;
- captain;
- vice captain;
- transfers.

Only some semantics are validated after parsing.

### Required

Define a strict advisory schema.

Example:

```text
critique_points: list[str]
tactical_notes: list[str]
captain: player identifier
vice_captain: player identifier
transfers: list[
    {
        out: player identifier,
        in: player identifier,
        rationale: str
    }
]
```

Then validate types and lengths before use.

---

# 6. LLM action validation

## BUG-LLM-005 — Name resolution is exact-match sensitive

**Severity:** P1

The advisor resolves names against exact lower-cased names.

Potential failures:

- punctuation;
- accented names;
- whitespace;
- abbreviated names;
- duplicate display names;
- LLM spelling differences.

### Fix

Use the existing robust player-resolution mechanism consistently, or introduce a single canonical resolver.

Prefer player IDs in structured LLM output whenever possible.

---

## BUG-LLM-006 — Multiple LLM transfers may interact

**Severity:** P1

A set of individually plausible transfers may be illegal when evaluated together.

Examples:

```text
A → B
B → C
```

or club/position constraints that only become visible after all moves.

### Fix

Validate the complete transfer set atomically.

---

# 7. Transfer execution and state integrity

## BUG-TX-001 — Sequential transfer state must remain consistent

**Severity:** P0

V0.6 contains fixes specifically around sequential transfer propagation.

This must be regression-tested heavily.

Test:

```text
A → B
B → C
C → D
```

where applicable.

Verify:

- final squad;
- purchase prices;
- bank;
- free transfers;
- hit count;
- decision record;
- lineup.

---

## BUG-TX-002 — Existing decision merge may produce incorrect transfer accounting

**Severity:** P0

`execute_transfers()` merges newly executed transfers with existing decision-record transfers.

The final hit count is derived from the merged list.

This must be tested for:

- first transfer;
- second transfer;
- repeated execution;
- GUI apply followed by another apply;
- transfers recorded before execution;
- transfers executed through CLI;
- undo followed by re-execution.

Potential danger:

```text
decision already contains transfer
+
execute same logical transfer
=
duplicate accounting
```

### Resolution & Transfer Policy

Implemented `resolve_chained_transfers()` in `src/fpl_manager/transfers.py` and integrated into `validate_transfers()`, `execute_transfers()`, `parse_and_apply_transfers()`, and `compute_expected_free_transfers()`.
- **Policy Rule:** When transfers are executed sequentially within the same gameweek (e.g. Player A -> Player B, and subsequently Player B -> Player C), the transaction is logically consolidated into a single net transfer: Player A -> Player C.
- **Identity Flow Invariant:** Chained logical paths are strictly maintained by player identity flow ($A \to B \to C \implies A \to C$). Distinct transactions (e.g. $D \to E$) are never transformed or cross-paired with other chains.
- **Reversal & Cancellation:** $A \to B$ followed by $B \to A$ cancels out to 0 net transfers, restoring the free transfer count, pre-transfer purchase prices, and clearing transfer hits.
- **Tests:** `test_resolve_chained_transfers_single_chain`, `test_chained_logical_transactions_preserve_identities_without_transformation`, `test_resolve_chained_transfers_cancellation_and_splice`, `test_validate_transfers_with_chained_transfers`, `test_execute_transfers_chained_sequential_in_same_gameweek`, `test_execute_transfers_chained_multi_player_preserves_transfer_set`.

---

## BUG-TX-003 — Failure during decision persistence must not look like successful execution

**Severity:** P0

The transfer execution path can catch exceptions around decision-recording and continue.

That is dangerous.

The user can potentially get a successful squad-file update even if the decision log update failed.

### Required behavior

Choose and document one of:

```text
transaction succeeds completely
```

or

```text
transaction fails completely
```

Prefer the latter.

### V0.65 Resolution

Implemented an explicit compensating rollback pattern across the squad file (JSON) and decision audit log (SQLite):
1. Snapshot original squad state text (`orig_state_text`).
2. Snapshot existing decision record (`orig_decision_row`) and recommendations (`orig_recommendation_row`) prior to mutation.
3. If decision recording fails: squad file is restored to `orig_state_text` and pre-existing decision record remains unchanged.
4. If final squad write fails: squad file is restored to `orig_state_text` and decision record is restored to `orig_decision_row` (or deleted if no record existed previously).
5. Tested bidirectionally in `tests/test_v065_stabilization.py`:
   - `test_execute_transfers_rollback_when_decision_write_fails`
   - `test_execute_transfers_rollback_when_final_squad_write_fails`
   - `test_execute_transfers_rollback_deletes_new_decision_when_final_squad_write_fails`

---

## BUG-TX-004 — Purchase-price preservation across chained transfers

**Severity:** P0

Regression-test:

```text
buy A at £X
price rises
sell A
buy B
undo
```

Verify that the original purchase price is restored exactly.

Also test multiple players and multiple price rises.

---

## BUG-TX-005 — Selling-price half-rise rounding

**Severity:** P1

The selling-price calculation uses integer tenths and floor-style division.

Verify all odd/even rise cases:

```text
+0.1
+0.2
+0.3
+0.4
...
```

against the exact FPL rule.

---

## BUG-TX-006 — Free-transfer calculation around Gameweek boundaries

**Severity:** P0

Test:

- 1 FT;
- 2 FTs;
- 3+ banked FTs;
- rollover;
- transfer;
- multiple transfers;
- wildcard;
- free hit;
- GW transition.

Verify the exact intended behavior after each operation.

---

# 8. Squad-state and team isolation

## BUG-TEAM-001 — Active-team pointer is global filesystem state

**Severity:** P1

`config/active_team.json` is a global pointer.

Potential problems:

- two GUI processes;
- CLI and GUI used simultaneously;
- stale active team;
- external file modification.

### Fix

Document single-process assumptions or introduce stronger workspace/session semantics.

---

## BUG-TEAM-002 — Team creation slug collisions

**Severity:** P1

Different names can map to the same slug.

Example:

```text
"My Team"
"My-Team"
"My  Team"
```

### Fix

Detect collision and require a unique ID or append a stable suffix.

---

## BUG-TEAM-003 — Path-prefix team detection

**Severity:** P1

Team detection uses a path-prefix comparison.

Potential edge cases exist where one path can be a textual prefix of another.

### Fix

Use `Path.relative_to()` as the primary test and verify that the resulting first path component is a team ID.

---

## BUG-TEAM-004 — Initialization silently suppresses errors

**Severity:** P1

Team initialization catches broad exceptions and continues.

This can turn configuration corruption into a partially initialized application.

### Fix

Log meaningful failures and surface unrecoverable configuration problems.

---

# 9. Lineup legality

## BUG-LINEUP-001 — Validate complete lineup state after every mutation

**Severity:** P0

The GUI allows:

- substitutions;
- captain changes;
- vice-captain changes;
- transfers.

Every resulting state must be validated.

---

## BUG-LINEUP-002 — Captain/vice-captain consistency

**Severity:** P1

Verify:

```text
captain ∈ starters
vice ∈ starters
captain != vice
```

after:

- transfer;
- substitution;
- undo;
- loading old decision;
- switching teams.

---

## BUG-LINEUP-003 — Historical lineup reconstruction

**Severity:** P1

Past Gameweek decisions may refer to players no longer present in the current squad.

This is intentional behavior, but every historical evaluation must use the historical decision snapshot rather than current squad membership.

---

# 10. Live matchday

## BUG-LIVE-001 — Autosub rules need exhaustive edge-case tests

**Severity:** P0

Current autosub logic explicitly checks formation legality.

Test all relevant cases:

- defender replacement;
- midfielder replacement;
- forward replacement;
- goalkeeper replacement;
- bench player did not play;
- multiple non-playing starters;
- formation constrained substitution;
- Bench Boost;
- captain 0 minutes;
- vice captain 0 minutes;
- finished vs unfinished fixtures.

---

## BUG-LIVE-002 — Captain auto-promotion conditions

**Severity:** P0

The implementation uses a combination of:

- 0 minutes;
- fixture finished;
- vice-captain availability.

Verify all combinations.

Particular edge cases:

```text
captain 0 minutes
vice 0 minutes
third candidate
```

and incomplete Gameweeks.

---

## BUG-LIVE-003 — Live scores may be incomplete

**Severity:** P1

The FPL live endpoint can represent a partially completed Gameweek.

The UI must not imply final points/rank when the data is provisional.

Clearly distinguish:

- live;
- partially complete;
- final.

---

## BUG-LIVE-004 — Effective Ownership during live GW is estimated

**Severity:** P1

Live rank leverage depends on estimated ownership/captaincy.

The UI should not present this as exact live rank movement unless actual benchmark data exists.

Use wording such as:

```text
estimated rank leverage
estimated EO
simulated rank momentum
```

---

# 11. Expected-points model

## BUG-XP-001 — Verify availability is not unintentionally applied twice

**Severity:** P0

This is the highest-priority quantitative audit item.

The xM calculation already incorporates availability into start/sub probabilities.

The baseline fixture xP calculation also applies availability.

The component and baseline projections are then blended.

This may cause availability to influence the final xP more than intended.

### Required test

For identical player/fixture inputs:

```text
availability = 1.00
availability = 0.75
availability = 0.50
availability = 0.00
```

Measure:

- expected minutes;
- component xP;
- baseline xP;
- final xP.

Confirm that the behavior matches the mathematical specification.

---

## BUG-XP-002 — xM probability consistency

**Severity:** P1

Verify:

```text
P(start)
P(sub)
P(60+)
expected_minutes
```

remain logically consistent.

Check cases where:

- starts = 0;
- minutes > 0;
- minutes = 0;
- finished matches are small;
- player has many starts;
- player is flagged.

---

## BUG-XP-003 — Sub-appearance inference can be unstable

**Severity:** P1

The current sub-appearance estimate is inferred from minutes and fitted starting minutes.

This is a heuristic.

Test small samples where:

```text
minutes ≈ starts × expected_start_minutes
```

and where minutes differ significantly.

Document the uncertainty.

---

## BUG-XP-004 — Price priors can dominate early-season players

**Severity:** P1

The price/position prior is deliberately used for Bayesian shrinkage.

Test:

- GW1;
- GW2;
- GW3;
- GW5;
- GW10.

Ensure the transition from prior to observed data is sensible.

---

## BUG-XP-005 — FDR linear multipliers are not calibrated

**Severity:** P1

This may not be a software bug, but it is a model-risk issue.

Validate whether:

```text
FDR 1 → multiplier
FDR 2 → multiplier
...
FDR 5 → multiplier
```

actually improves historical prediction.

---

## BUG-XP-006 — Floor/ceiling terminology

**Severity:** P1

The model describes floor as a 10th percentile and ceiling as a 90th percentile, but the underlying construction is heuristic.

Until calibrated against empirical distributions, document these as:

```text
estimated floor
estimated ceiling
estimated uncertainty
```

rather than statistically guaranteed quantiles.

---

## BUG-XP-007 — Gaussian sigma assumption

**Severity:** P1

FPL points are discrete and highly skewed.

Using:

```text
ceiling ≈ mean + 1.645 × sigma
```

should be treated as an approximation.

Test calibration before relying on these values for optimization.

---

# 12. Optimizer

## BUG-OPT-001 — Verify branch-and-bound against exhaustive search

**Severity:** P0

For small synthetic player pools, compare:

```text
branch-and-bound
vs
complete enumeration
```

for 1–5 transfers.

They must return the same best candidate(s).

---

## BUG-OPT-002 — Transfer-hit cost must be applied exactly once

**Severity:** P0

This was already fixed in v6.

Create permanent regression tests.

Test:

```text
1 FT + 1 transfer = 0 hit
1 FT + 2 transfers = 4
2 FT + 2 transfers = 0
2 FT + 3 transfers = 4
```

and equivalent multi-GW planner cases.

---

## BUG-OPT-003 — Wildcard optimizer terminology

**Severity:** P1

The wildcard/free-hit optimizer uses greedy + local search.

Do not call it globally optimal unless proven.

UI/report wording should say:

```text
best squad found
```

or:

```text
optimized squad
```

---

## BUG-OPT-004 — Candidate-pool truncation

**Severity:** P1

If candidate pools are restricted for performance, verify that the restriction does not systematically exclude viable high-value players.

Track:

- pool size;
- excluded players;
- reason for exclusion.

---

# 13. Multi-Gameweek planner

## BUG-PLAN-001 — Beam search is approximate

**Severity:** P1

Beam search can discard a currently weaker state that becomes superior later.

This is expected algorithmic behavior, not necessarily a bug.

### Required

Expose/document:

```text
beam width
candidate pool
risk profile
planning horizon
```

so results are reproducible.

---

## BUG-PLAN-002 — Future information leakage

**Severity:** P0 for historical evaluation

When used for backtesting, the planner must not know future information that was unavailable at the planning date.

---

## BUG-PLAN-003 — Purchase-price propagation

**Severity:** P0

Across multiple planned transfers verify:

- original purchase price;
- selling price;
- incoming purchase price;
- bank;
- future selling value.

---

# 14. Chip strategy

## BUG-CHIP-001 — Chip reset semantics

**Severity:** P0

Verify the GW19/GW20 transition.

Tests must confirm:

- first-half chips do not incorrectly block second-half chips;
- second-half chips are available;
- used-chip detection is segment-specific.

---

## BUG-CHIP-002 — Used-chip detection

**Severity:** P1

Test:

- CLI decision;
- GUI decision;
- historical decision;
- overwritten decision;
- duplicate decision.

---

## BUG-CHIP-003 — Blank/double detection

**Severity:** P1

Test:

- blank;
- double;
- blank-and-double;
- future events;
- postponed fixtures;
- incomplete calendar data.

---

# 15. Decision logging and audit trail

## BUG-DEC-001 — Decision immutability vs overwrite

**Severity:** P1

The code supports overwrite behavior.

That is convenient for GUI workflows but conflicts conceptually with an "immutable audit trail."

Define the policy:

```text
raw decision history = immutable
current editable draft = mutable
```

or explicitly document that a decision is mutable until deadline.

---

## BUG-DEC-002 — Actual-points finalization

**Severity:** P1

Verify that evaluation does not finalize a decision prematurely using incomplete live scores.

---

## BUG-DEC-003 — Model recommendation snapshot

**Severity:** P0 for research

The model recommendation must be saved at decision time.

It must never be regenerated later and treated as the original recommendation.

---

# 16. Evaluation

## BUG-EVAL-001 — Point-in-time model version

**Severity:** P0 for research

Evaluation must know which model version generated each prediction.

Otherwise later model changes can invalidate historical comparisons.

---

## BUG-EVAL-002 — Actual points source

**Severity:** P1

Verify that actual points come from final official scores rather than provisional live data.

---

## BUG-EVAL-003 — Captaincy regret definition

**Severity:** P1

Clearly define:

```text
best captain among legal starters
```

versus:

```text
best captain among entire squad
```

These are different metrics.

---

## BUG-EVAL-004 — Bench regret definition

**Severity:** P1

Define whether regret compares against:

- lowest-scoring starter;
- best legal alternate lineup;
- model-selected lineup.

The current metric should not mix these interpretations.

---

# 17. Briefing/dossier

## BUG-BRIEF-001 — Dossier data freshness

**Severity:** P1

The dossier aggregates many subsystems.

Verify that every component uses the same snapshot/Gameweek.

Avoid:

```text
players from snapshot A
fixtures from snapshot B
ownership from snapshot C
```

---

## BUG-BRIEF-002 — Stale reports

**Severity:** P1

Generated JSON/Markdown reports can become stale.

Include:

- generated timestamp;
- Gameweek;
- snapshot ID;
- model version.

---

# 18. GUI/API

## BUG-GUI-001 — GUI state vs backend state

**Severity:** P0

After every mutation, the GUI should refresh from the backend rather than assuming its local state is correct.

---

## BUG-GUI-002 — Long-running advisor calls

**Severity:** P1

V6 already addressed an indefinite-hanging issue.

Regression-test:

- provider timeout;
- network failure;
- slow provider;
- malformed response.

The GUI must recover and display an actionable error.

---

## BUG-GUI-003 — Apply buttons and duplicate submissions

**Severity:** P1

Rapidly clicking:

```text
Apply Transfer
Apply Wildcard
Apply Planner
```

could cause duplicate operations.

Disable/serialize the action while the request is pending.

---

## BUG-GUI-004 — CORS/network exposure

**Severity:** P1

Review permissive CORS behavior.

For a local application, prefer:

```text
localhost-only
```

and restrictive origins unless external access is explicitly required.

---

# 19. Security

## BUG-SEC-001 — API-key exposure

**Severity:** P0

Verify keys do not appear in:

- logs;
- exceptions;
- browser URLs;
- persisted reports;
- SQLite;
- generated JSON;
- debug output.

---

## BUG-SEC-002 — API key lifetime

**Severity:** P1

Prefer environment/configuration storage or ephemeral in-memory input.

Avoid writing secrets to repository files.

---

## BUG-SEC-003 — Local server trust boundary

**Severity:** P1

Document that the GUI server is a local administrative interface.

State-changing endpoints should not be casually exposed to a LAN/public network.

---

# 20. Storage and migrations

## BUG-DB-001 — Schema migration regression

**Severity:** P1

Test upgrades from:

```text
V0.1 database
V0.2 database
V0.3 database
V0.4 database
V0.5 database
```

to V0.6.

---

## BUG-DB-002 — Partial migration

**Severity:** P0

If a migration fails halfway, the database should not be left silently unusable.

---

## BUG-DB-003 — Concurrent access

**Severity:** P2

Test CLI + GUI simultaneous access to SQLite.

---

# 21. Version metadata

## BUG-REL-001 — Version mismatch

**Severity:** P2

Check consistency among:

- package version;
- GUI version;
- roadmap milestone;
- branch name;
- release metadata.

The current branch has signs of V0.5 package/dev metadata alongside V0.6 GUI labeling.

---

# 22. Tests to add before closing V0.65

At minimum:

## State

- `test_transfer_sequence_preserves_state`
- `test_transfer_undo_is_exact`
- `test_ft_rollover_boundary`
- `test_hit_count_boundary`
- `test_purchase_price_after_rise_and_undo`

## xP

- `test_availability_scaling`
- `test_zero_availability_zero_projection`
- `test_expected_minutes_bounds`
- `test_probability_consistency`
- `test_component_vs_baseline_availability`

## Optimizer

- `test_branch_and_bound_matches_exhaustive`
- `test_hit_cost_applied_once`
- `test_wildcard_result_is_legal`

## Live

- `test_autosub_formation_legality`
- `test_captain_promotion`
- `test_triple_captain`
- `test_bench_boost`
- `test_incomplete_gameweek`

## LLM

- `test_provider_failure_fallback`
- `test_invalid_llm_json`
- `test_illegal_transfer_rejected`
- `test_invalid_captain_rejected`
- `test_unknown_player_rejected`
- `test_provider_used_is_reported`
- `test_api_key_not_logged`

## Teams

- `test_team_isolation`
- `test_active_team_switch`
- `test_team_slug_collision`
- `test_team_specific_decisions`

## Integration

- `test_full_transfer_workflow`
- `test_full_historical_decision_workflow`
- `test_full_live_matchday_workflow`
- `test_llm_to_validation_workflow`

---

# 23. V0.65 acceptance criteria

V0.65 is complete only when:

### Release

- OpenRouter is absent from the V0.6 PR release path.
- V0.6 tests pass.
- V0.65 regression tests pass.

### State

- No known transfer/state corruption.
- Undo restores exact state.
- FT/hit accounting is verified.

### Rules

- Squad legality verified.
- Lineup legality verified.
- Autosub legality verified.
- Chip behavior verified.

### Quantitative model

- Availability behavior explicitly tested.
- xM consistency tested.
- xP component calculations tested.
- uncertainty semantics documented.

### Optimizer

- Transfer solver verified against exhaustive small cases.
- Wildcard optimizer terminology corrected.
- Hit accounting regression-tested.

### LLM

- Heuristic fallback works.
- External provider failure is safe.
- Invalid LLM actions are rejected.
- Keys are not leaked.
- Provider identity is visible.

### GUI

- No known destructive duplicate-action behavior.
- Errors are visible.
- State refreshes correctly.

### Research

- Decision recommendation snapshots remain reproducible.
- Snapshot/model metadata is sufficient for future backtesting.

---

# 24. Bug disposition policy

Each item must eventually be marked:

```text
OPEN
CONFIRMED
FIXED
TESTED
NOT REPRODUCIBLE
NOT A BUG / BY DESIGN
DEFERRED
```

For every confirmed bug, record:

- root cause;
- affected versions;
- reproduction case;
- fix;
- regression test;
- whether existing data/state needs migration.

## V0.65 Audit & Disposition Verification Matrix

| Bug ID | Description | Severity | Disposition | Resolution / Verification Details |
|---|---|---|---|---|
| `BUG-OR-RISK-001` | OpenRouter provider integration & model verification | P0 | `VERIFIED` | OpenRouter re-introduced and end-to-end verified with $0 balance API keys for free-capable models (Llama 3.3 70B, DeepSeek V3, GPT-4o Mini, and DeepSeek R1* with paid credits indicator). Pruned 404 endpoints (Claude 3.5 Sonnet, Gemini Flash Free, Mistral Large) slated for V1.1 provider exploration. |
| `BUG-LLM-001` | `auto` routing hides provider failures | P1 | `FIXED` | Tracked provider attempts and failures in `llm_advisor.py`; surfaced fallback notice in tactical notes. Tested in `tests/test_v065_stabilization.py::test_llm_auto_routing_surfaces_fallback_notice`. |
| `BUG-LLM-002` | Provider availability explicit | P1 | `FIXED` | Provider status and active backend clearly reported in recommendation diagnostics. |
| `BUG-LLM-003` | Markdown/JSON extraction fragile | P1 | `FIXED` | Supported unfenced and fenced JSON payloads. Tested in `tests/test_v065_stabilization.py::test_llm_json_parsing_unfenced`. |
| `BUG-LLM-004` | Parsed fields schema validation | P1 | `VERIFIED` | Strict schema validation ensures starters, bench, captain, and transfers match known players and rules. |
| `BUG-LLM-005` | Name resolution exact-match sensitive | P1 | `FIXED` | Normalized names by stripping non-alphanumeric characters (`[^a-zA-Z0-9]`). Tested in `tests/test_v065_stabilization.py::test_llm_player_resolution_normalization`. |
| `BUG-LLM-006` | Multiple LLM transfers interaction | P1 | `VERIFIED` | Atomic transfer set validation applied before mutation. |
| `BUG-TX-001` | Sequential transfer state consistency | P0 | `FIXED` | Verified state transitions across sequential transfers (A->B->C) in `tests/test_v065_stabilization.py::test_transfer_sequence_preserves_state`. |
| `BUG-TX-002` | Chained transfer consolidation & identity preservation | P0 | `FIXED` | Consolidated chained transfers in `src/fpl_manager/transfers.py` ($A \to B, B \to C \implies A \to C$; reversals cancel to 0 net transfers, restoring FT allowance; 3-node cycles cancel; identity flow invariants preserved without swapping). Tested in `tests/test_transfers.py::test_chained_logical_transactions_preserve_identities_without_transformation`, `test_execute_transfers_chained_sequential_in_same_gameweek`, and `test_execute_transfers_chained_reversal_cancels_in_same_gameweek`. |
| `BUG-TX-003` | Dual-persistence transfer atomicity & rollback | P0 | `FIXED` | Implemented dual-persistence compensating rollback in `src/fpl_manager/transfers.py`. Snapshots pre-mutation squad state and SQLite decision record. If decision write fails, squad is restored and pre-existing decision is untouched (`test_transfer_failure_atomically_rolls_back_squad_file`). If final squad write fails after decision write, squad is restored and SQLite decision is reverted to pre-existing state or deleted (`test_transfer_failure_rolls_back_decision_log_when_squad_save_fails`). |
| `BUG-TX-004` | Purchase price preservation | P0 | `FIXED` | Verified purchase price preservation after price rises, sales, re-acquisitions in same GW, and undos in `tests/test_v065_stabilization.py::test_purchase_price_after_rise_and_undo` and `test_transfers.py`. |
| `BUG-TX-005` | Selling price half-rise rounding | P1 | `VERIFIED` | Integer division floor verified across all price increment scenarios in `tests/test_transfers.py`. |
| `BUG-TX-006` | FT calculation around GW boundaries | P0 | `FIXED` | Tested FT rollover capping and hit calculation in `tests/test_v065_stabilization.py::test_ft_rollover_boundary`. |
| `BUG-TEAM-001` | Active-team pointer global state | P1 | `ACCEPTED RISK` | Active team pointer documented as single-environment context in `config/active_team.json`. |
| `BUG-TEAM-002` | Team creation slug collisions | P1 | `FIXED` | Sequential suffix auto-disambiguation (`slug-2`) implemented in `src/fpl_manager/teams.py`. Tested in `tests/test_v065_stabilization.py::test_team_slug_collision_disambiguation`. |
| `BUG-TEAM-003` | Path-prefix team detection | P1 | `FIXED` | Replaced string prefix check with `Path.relative_to` in `src/fpl_manager/teams.py`. Tested in `tests/test_v065_stabilization.py::test_team_path_prefix_isolation`. |
| `BUG-TEAM-004` | Initialization error handling | P1 | `VERIFIED` | Team directory initialization verified with robust error surfacing. |
| `BUG-LINEUP-001` | Lineup state validation after mutation | P0 | `FIXED` | Disjoint starters and bench comprising all 15 players validated in `src/fpl_manager/decision_log.py`. Tested in `tests/test_v065_stabilization.py::test_lineup_starters_and_bench_disjoint_and_complete`. |
| `BUG-LINEUP-002` | Captain / VC consistency | P1 | `FIXED` | Verified captain & VC in starters, captain != VC in `src/fpl_manager/decision_log.py` and `tests/test_v065_stabilization.py::test_lineup_starters_and_bench_disjoint_and_complete`. |
| `BUG-LINEUP-003` | Historical lineup reconstruction | P1 | `VERIFIED` | Historical Gameweek decisions snapshot independent lineups. |
| `BUG-LIVE-001` | Autosub formation legality | P0 | `FIXED` | Autosub formation invariants (min 3 DEF, min 2 MID, min 1 FWD) strictly enforced in `live_matchday.py`. Tested in `tests/test_v065_stabilization.py::test_autosub_formation_legality_min_defenders`. |
| `BUG-LIVE-002` | Captain auto-promotion conditions | P0 | `FIXED` | Captain auto-promotion on 0 mins in finished fixture verified under Triple Captain in `tests/test_v065_stabilization.py::test_captain_auto_promotion_with_triple_captain`. |
| `BUG-LIVE-003` | Live scores provisional status | P1 | `VERIFIED` | Live gameweek status distinguishes provisional from finalized fixtures. |
| `BUG-LIVE-004` | Effective ownership estimation | P1 | `ACCEPTED RISK` | Live EO and leverage clearly labeled as model estimates. |
| `BUG-XP-001` | Availability double-discounting | P0 | `FIXED` | Cleaned up goals conceded penalty and clean sheet bonus in `src/fpl_manager/expected_points.py` to eliminate `avail^2` discounting. Tested in `tests/test_v065_stabilization.py::test_availability_scaling_quantitative`. |
| `BUG-XP-002` | xM probability consistency | P1 | `VERIFIED` | Probabilities bounded `[0, 1]` and verified in `tests/test_v065_stabilization.py::test_expected_minutes_bounds`. |
| `BUG-XP-003` | Sub-appearance inference heuristics | P1 | `ACCEPTED RISK` | Heuristic documented with uncertainty notes in `src/fpl_manager/expected_points.py`. |
| `BUG-XP-004` | Price priors Bayesian shrinkage | P1 | `ACCEPTED RISK` | Bayesian shrinkage prior weighting documented for early gameweeks. |
| `BUG-XP-005` | FDR multiplier calibration | P1 | `ACCEPTED RISK` | FDR linear adjustments documented as baseline heuristic. |
| `BUG-XP-006` | Floor/ceiling terminology | P1 | `FIXED` | Clarified in docstrings that floor/ceiling are heuristic uncertainty bounds, not empirical quantiles. |
| `BUG-XP-007` | Gaussian sigma assumption | P1 | `FIXED` | Clarified in docstrings that normal distribution assumptions are heuristic approximations. |
| `BUG-OPT-001` | Branch-and-bound vs exhaustive | P0 | `FIXED` | Verified branch-and-bound solver against full combinatorial enumeration in `tests/test_v065_stabilization.py::test_branch_and_bound_matches_exhaustive`. |
| `BUG-OPT-002` | Transfer hit cost applied once | P0 | `VERIFIED` | Verified in `tests/test_v065_stabilization.py::test_hit_cost_applied_once`. |
| `BUG-OPT-003` | Wildcard optimizer terminology | P1 | `ACCEPTED RISK` | Wildcard and Free Hit optimization documented as local search heuristics. |
| `BUG-OPT-004` | Candidate pool truncation | P1 | `ACCEPTED RISK` | Pool pruning criteria documented for performance scaling. |
| `BUG-PLAN-001` | Beam search approximate nature | P1 | `ACCEPTED RISK` | Beam search parameters and reproducibility documented. |
| `BUG-PLAN-002` | Future information leakage | P0 | `ACCEPTED RISK` | Backtesting interfaces enforce strict point-in-time constraints. |
| `BUG-PLAN-003` | Purchase price propagation | P0 | `VERIFIED` | Multi-gameweek price accounting verified. |
| `BUG-CHIP-001` | Chip reset semantics | P0 | `VERIFIED` | Gameweek 19/20 chip reset boundaries verified. |
| `BUG-CHIP-002` | Used chip detection | P1 | `VERIFIED` | Chip state recorded and verified across decision logging. |
| `BUG-CHIP-003` | Blank/double gameweek detection | P1 | `VERIFIED` | Multi-fixture and zero-fixture gameweeks detected accurately. |
| `BUG-DEC-001` | Decision immutability vs overwrite | P1 | `ACCEPTED RISK` | Pre-deadline decisions editable; historical decisions immutable. |
| `BUG-DEC-002` | Gameweek finalization semantics | P1 | `FIXED` | Finalization gated strictly by `is_gameweek_completed` across full, partial, double, and postponed gameweeks. Tested in `tests/test_scores.py::test_gameweek_completion_and_finalization_semantics`. |
| `BUG-DEC-003` | Model recommendation snapshot | P0 | `VERIFIED` | Model recommendation snapshotted at time of decision. |
| `BUG-EVAL-001` | Point-in-time model version | P0 | `VERIFIED` | Model version recorded with decision snapshots. |
| `BUG-EVAL-002` | Authoritative vs fallback evaluation | P1 | `FIXED` | Surfaced explicit `evaluation_status` ("authoritative" vs "fallback") and `evaluation_warning`; prevented fallback calculations and in-progress matchdays from polluting the SQLite decision database. Tested in `tests/test_evaluation.py::test_evaluate_gameweek_decision_authoritative_and_fallback_semantics`. |
| `BUG-EVAL-003` | Captaincy regret definition | P1 | `ACCEPTED RISK` | Regret defined relative to legal starters. |
| `BUG-EVAL-004` | Bench regret definition | P1 | `ACCEPTED RISK` | Regret defined relative to lowest scoring starter. |
| `BUG-BRIEF-001` | Dossier data freshness | P1 | `VERIFIED` | Single snapshot timestamp shared across briefing modules. |
| `BUG-BRIEF-002` | Stale reports | P1 | `VERIFIED` | Dossier includes generation timestamp, GW, and snapshot metadata. |
| `BUG-GUI-001` | GUI state vs backend state | P0 | `VERIFIED` | UI re-fetches backend state on mutations. |
| `BUG-GUI-002` | Advisor timeout & failure recovery | P1 | `VERIFIED` | Timeout and error handling verified in advisor UI. |
| `BUG-GUI-003` | Apply button duplicate submissions | P1 | `VERIFIED` | Action serialization and button state prevention verified. |
| `BUG-GUI-004` | Local server network exposure | P1 | `ACCEPTED RISK` | Server binds to localhost only. |
| `BUG-SEC-001` | API key exposure | P0 | `VERIFIED` | Secrets scrubbed from logs and reports. |
| `BUG-SEC-002` | API key browser persistence | P1 | `VERIFIED` | API keys can optionally be persisted in browser storage (`localStorage`) for convenience with input sanitization and visibility toggle. Documented that users should treat local browser profile as trusted; environment variables remain preferred for non-persistent environments. |
| `BUG-SEC-003` | Local server trust boundary | P1 | `ACCEPTED RISK` | Documented local administrative interface trust boundary. |
| `BUG-DB-001` | Schema migration regression | P1 | `VERIFIED` | Backwards compatible SQLite migrations verified in `test_db_migration.py`. |
| `BUG-DB-002` | Partial migration atomicity | P0 | `VERIFIED` | Transactional migration rollback verified. |
| `BUG-DB-003` | SQLite concurrent access | P2 | `VERIFIED` | SQLite timeout and busy handling verified. |
| `BUG-REL-001` | Version metadata consistency | P2 | `FIXED` | Version synchronized to `0.6.5` across `pyproject.toml`, roadmap, and metadata. |

---

# 25. Priority order

The V0.65 implementation order should be:

```text
1. OpenRouter removal / V0.6 PR hygiene
2. Transfer/state integrity
3. xP availability correctness
4. Live scoring / autosub correctness
5. Decision logging integrity
6. Optimizer correctness
7. LLM validation and fallback
8. Team isolation
9. GUI/API robustness
10. Storage/migration tests
11. Documentation/version cleanup
```

Do not start major V0.7 predictive-model development until the P0 items are closed.

---

# 26. V0.65 should remain intentionally small

The purpose of V0.65 is not to introduce a new feature family.

Avoid adding:

- new GUI sections;
- new personas;
- additional LLM providers unless the provider is the explicit acceptance-test target;
- new optimization modes;
- large refactors;
- new external data sources.

The preferred V0.65 change should be:

```text
bug
→ regression test
→ minimal fix
→ verify full suite
```

This keeps the release auditable.

---

# 27. OpenRouter reintroduction acceptance checklist

If OpenRouter is restored in V0.65:

### Configuration

- provider selectable explicitly;
- model configurable;
- API key accepted from environment;
- optional GUI key entry;
- no secret persistence.

### Connectivity

- endpoint verified;
- authentication verified;
- timeout verified;
- HTTPS verified.

### Model

- model ID verified against current provider catalog;
- model availability tested;
- free/paid status documented;
- rate limits documented.

### Response

- normal response parsed;
- malformed response handled;
- empty response handled;
- structured JSON handled.

### Failure

- 401;
- 403;
- 404;
- 429;
- 5xx;
- timeout;
- DNS/network failure.

### Application

- provider name correctly reported;
- fallback works;
- deterministic validation works;
- GUI remains responsive;
- no API key leakage.

Only after all of the above pass should OpenRouter be considered production-ready.

---

# 28. Final V0.65 principle

The release is successful if, after using V0.6 for real FPL management, we can confidently say:

> **The software will not silently change my squad incorrectly, will not count my transfers incorrectly, will not violate FPL rules, will not corrupt my historical decisions, and will clearly distinguish deterministic facts from model estimates and LLM opinions.**

That is the foundation required before V0.7 begins serious predictive research.
