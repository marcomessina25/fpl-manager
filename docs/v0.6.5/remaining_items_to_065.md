# Remaining Items to V0.65

## Purpose

This document captures the remaining items identified during the review
of PR #7 (`v065` → `master`) after the latest fixes.

The intent is **not** to reopen the V0.65 scope or redesign the system.
These are the final correctness, verification, and documentation items
that should be checked before considering V0.65 fully ready.

The observations below are deliberately separated into:

-   **must verify / potentially blocking** items;
-   **strongly recommended release-hardening** items;
-   items that can safely remain for later versions.

------------------------------------------------------------------------

# 1. Verify A→B→A transfer cancellation semantics

### Status

**Needs verification against actual FPL transfer/accounting semantics.**

The current transfer-chain implementation supports collapsing chains
such as:

``` text
A → B
B → C
```

into:

``` text
A → C
```

It also currently treats:

``` text
A → B
B → A
```

as a cancellation.

The important question is whether cancellation of the **net squad
state** should also mean cancellation of the **transfer activity** for
the purposes of:

-   transfer count;
-   free-transfer consumption;
-   transfer hits;
-   decision logging.

These concepts should not automatically be treated as identical.

### Why this matters

A transfer sequence can have:

1.  a final squad state;
2.  a logical/net transfer representation;
3.  actual transfer actions;
4.  FPL accounting consequences.

The implementation must use the correct semantics for the application's
intended representation.

### Required verification

Check the authoritative FPL rules/data semantics for:

``` text
A → B
B → A
```

and determine whether this should produce:

``` text
net squad change = 0
```

and independently:

``` text
transfer count = 0 or 2
```

depending on the actual accounting semantics.

Also verify:

``` text
A → B
B → C
```

and, if supported:

``` text
A → B
B → C
C → A
```

### Regression coverage

Keep/add tests for:

-   single transfer chain;
-   multiple independent chains;
-   A→B→C;
-   A→B→A;
-   sequential transfers across the same Gameweek;
-   transfer count and hit calculation after chain resolution.

### Recommendation

Do not change the current implementation merely because the behavior is
surprising. First establish the intended FPL accounting semantics, then
make the smallest required correction.

------------------------------------------------------------------------

# 2. Evaluation must not silently hide matchday-calculation failures

### Status

**Strongly recommended before merge.**

The evaluation pipeline currently contains fallback behavior around
matchday-performance calculation.

The concern is the distinction between:

``` text
user-facing runtime resilience
```

and:

``` text
scientific evaluation correctness
```

For a GUI/runtime operation, graceful fallback can be useful.

For historical evaluation/backtesting, silently replacing the
authoritative calculation with an older/simple calculation can produce a
plausible-looking but incorrect result.

### Risk scenario

``` text
new matchday calculation fails
        ↓
exception caught
        ↓
old/simple calculation used
        ↓
evaluation succeeds
        ↓
incorrect result is treated as valid
```

This is particularly undesirable because evaluation will become the
foundation for V0.7 model development.

### Recommended behavior

For authoritative evaluation:

``` text
matchday calculation succeeds
        ↓
use authoritative result
```

If it fails:

``` text
matchday calculation fails
        ↓
evaluation explicitly fails or is marked unavailable
```

If a fallback must remain for compatibility, it should be explicitly
marked, e.g.:

``` text
evaluation_status = fallback
evaluation_warning = ...
```

rather than being indistinguishable from normal evaluation.

### Regression coverage

Verify:

1.  Normal matchday evaluation works.
2.  A matchday-calculation failure is surfaced explicitly.
3.  A UI fallback, if retained, cannot silently contaminate scientific
    evaluation.
4.  The fallback behavior is clearly distinguishable from authoritative
    evaluation.

### Recommendation

**P1 release-hardening item.**

It is not necessary to redesign the evaluation system in V0.65, but
silent fallback should not become a source of misleading measurements.

------------------------------------------------------------------------

# 3. Verify Gameweek finalization semantics

### Status

**Needs one final correctness verification.**

V0.65 introduced automatic Gameweek/matchday handling and automatic
evaluation of unfinalized decisions when matchday data is available.

The key distinction is:

``` text
match data exists
```

versus:

``` text
the relevant Gameweek is fully completed/finalizable
```

These are not necessarily equivalent.

### Risk scenarios

Particular attention should be paid to:

-   postponed fixtures;
-   double Gameweeks;
-   fixtures played at different times;
-   partially completed Gameweeks;
-   late/remaining fixtures.

A system should not finalize a Gameweek simply because some score data
is available.

### Required behavior

For a fully completed Gameweek:

``` text
all relevant fixtures finished
        ↓
Gameweek may be finalized
```

For an incomplete Gameweek:

``` text
some relevant fixtures pending
        ↓
do not finalize
```

For a double Gameweek:

``` text
all relevant fixtures for the Gameweek
        ↓
must be accounted for before finalization
```

### Regression coverage

Add deterministic tests using mocked/synthetic FPL data for:

-   fully completed Gameweek;
-   partially completed Gameweek;
-   double Gameweek;
-   postponed/late fixture.

The tests should not require a live FPL API.

### Recommendation

**P1 release-hardening item.**

------------------------------------------------------------------------

# 4. Synchronize `docs/v065_potential_bugs.md` with the final implementation

### Status

**Documentation update required.**

`docs/v065_potential_bugs.md` is intended to be the audit/disposition
document for V0.65. It therefore needs to describe the final state of
the branch, not an earlier intermediate state.

Review all entries against the latest implementation and tests.

### Areas that should be checked

At minimum:

-   transfer atomicity;
-   transfer-chain resolution;
-   xP availability;
-   OpenRouter;
-   evaluation;
-   LLM robustness;
-   team isolation;
-   security/persistence.

### Transfer atomicity

The final implementation now uses compensating rollback involving the
relevant persistence layers.

The bug matrix should not describe the fix merely as:

> squad file rollback on decision-log failure

if the implementation now also restores/removes the corresponding
decision state.

The matrix should accurately distinguish:

``` text
decision write failure
```

from:

``` text
final squad write failure after decision write
```

and reflect the regression tests that cover both directions.

### OpenRouter

The current state should reflect that:

-   OpenRouter integration is present;
-   verified OpenRouter free-capable models work with an API key having
    a zero-dollar balance;
-   those models are usable within their applicable free-token limits;
-   not every OpenRouter model is necessarily free;
-   paid models should remain clearly identified.

Do not leave the OpenRouter item marked as simply deferred if the
current implementation has been verified.

### Status vocabulary

Prefer explicit dispositions such as:

-   `FIXED`
-   `VERIFIED`
-   `DEFERRED`
-   `NOT REPRODUCED`
-   `ACCEPTED RISK`

A `FIXED` status should correspond to regression coverage or a clearly
documented verification.

------------------------------------------------------------------------

# 5. Remove test-count and release-status inconsistencies

### Status

**Documentation cleanup required.**

Different repository documents have referred to different V0.65 test
counts, including:

``` text
159
161
163
```

The exact count will naturally change as tests are added, so the roadmap
should not depend on a stale hard-coded number.

### Recommended wording

Use something like:

> The complete automated test suite passes in CI.

If an exact count is retained in PR/release notes, it should be
generated from the actual final test run.

### Release-state terminology

Keep these states distinct:

``` text
implemented
tested
validated
PR-ready
merged
released
```

Before PR #7 is merged, the roadmap should not describe V0.65 as fully
released.

A precise interim status is:

> V0.65 implemented and validated on the `v065` branch; pending merge.

Only after merge/release should it become:

> V0.65 released.

------------------------------------------------------------------------

# 6. OpenRouter / free-provider objective

### Status

**No longer a V0.65 blocker.**

The current OpenRouter setup has been manually verified with an API key
carrying a **\$0 balance**, and the configured free-capable models work
subject to their applicable token limits.

Therefore, the original requirement:

> provide a usable LLM option without requiring paid OpenAI/Gemini
> credits

is satisfied for the current V0.65 provider setup, subject to free-tier
limits and provider availability.

### Important distinction

Do not claim:

> OpenRouter is entirely free.

Instead state:

> V0.65 supports verified OpenRouter free-capable models that operate
> under the provider's free usage limits.

Paid models may still be available and should remain clearly marked.

### Future improvement

Provider/model availability should eventually be made more dynamic
instead of relying on a manually maintained model list.

This is a future enhancement, not a V0.65 blocker.

------------------------------------------------------------------------

# 7. Optimizer: additional exhaustive-equivalence coverage

### Status

**Deferred / strongly recommended future hardening.**

The current regression strategy comparing branch-and-bound against
exhaustive enumeration on small synthetic datasets is excellent.

For additional confidence, extend the same principle to:

``` text
1 transfer
2 transfers
3 transfers
4 transfers
5 transfers
```

where computationally feasible.

### Required invariant

For a sufficiently small synthetic search space:

``` text
branch-and-bound optimum
==
exhaustive-search optimum
```

This should remain a permanent regression principle.

### V0.65 disposition

The existing coverage is sufficient to demonstrate the approach.

Additional 2--5 transfer exhaustive verification can remain outside the
critical V0.65 merge path if time/scope is constrained.

------------------------------------------------------------------------

# 8. xP availability: numerical regression coverage

### Status

**Deferred scientific validation; current V0.65 correctness work is
sufficient if existing tests pass.**

The V0.65 changes correctly address the concern about availability being
applied more than once in the relevant xP/xGC calculation.

The current boundary tests are useful, especially around:

``` text
0% availability
```

and expected-minute bounds.

### Future stronger test

A future numerical regression should evaluate the same player/fixture
under:

``` text
100% availability
75% availability
50% availability
25% availability
0% availability
```

and inspect the final:

-   expected minutes;
-   component xP;
-   final xP.

The important invariant is that availability affects the final expected
score exactly once according to the intended model.

### Important distinction

V0.65 can establish:

> implementation correctness and boundary behavior.

V0.7+ should establish:

> statistical calibration using historical data.

Do not conflate those two goals.

------------------------------------------------------------------------

# 9. Security wording around browser localStorage

### Status

**Documentation/design wording improvement; not a V0.65 blocker.**

Browser `localStorage` is convenient local persistence, but it should
not be described simply as a "secure" secret store.

These concepts are different:

``` text
sanitized
≠
encrypted
≠
secure secret storage
```

For the current local-first application this may be an acceptable
usability trade-off, but the documentation should be precise.

### Recommended wording

Something along the lines of:

> API keys can optionally be persisted in browser storage for
> convenience. Users should treat the local browser profile as trusted.

Environment variables or non-persistent entry should remain preferable
where appropriate.

This does not require a full secret-management redesign in V0.65.

------------------------------------------------------------------------

# 10. Freeze V0.65 scope

### Status

**Recommendation: freeze.**

The current PR already covers substantial work:

-   state integrity;
-   transfer-chain handling;
-   autosubs;
-   matchday handling;
-   automatic Gameweek synchronization;
-   evaluation integration;
-   LLM robustness;
-   OpenRouter;
-   regression testing;
-   documentation.

Do not add unrelated features to PR #7.

Once the remaining correctness/documentation items are addressed:

``` text
V0.65
    ↓
final test
    ↓
merge PR #7
    ↓
V0.7
```

### Explicitly defer

Do not pull the following into V0.65:

-   historical point-in-time datasets;
-   xP statistical calibration;
-   minutes model;
-   rank-aware optimization;
-   effective ownership strategy;
-   news/press-conference ingestion;
-   major LLM architecture redesign;
-   broad provider expansion;
-   large GUI redesign.

These belong to later roadmap stages.

------------------------------------------------------------------------

# Final V0.65 checklist

Before merge, the preferred final sequence is:

-   [ ] Verify A→B→A semantics against FPL accounting.
-   [ ] Decide whether evaluation fallback should be removed or
    explicitly surfaced.
-   [ ] Verify partial/double/postponed Gameweek finalization behavior.
-   [ ] Update `docs/v065_potential_bugs.md` to match the latest
    code/tests.
-   [ ] Remove stale/inconsistent test counts.
-   [ ] Ensure roadmap says V0.65 is pending merge rather than released.
-   [ ] Confirm OpenRouter free-capable models remain verified and
    correctly documented.
-   [ ] Run the complete automated test suite.
-   [ ] Confirm no secrets/API keys are committed.
-   [ ] Freeze the V0.65 scope.
-   [ ] Merge PR #7 once the remaining checks pass.

------------------------------------------------------------------------

# Recommended disposition

The overall V0.65 implementation is now **close to merge-ready**.

The most important previously identified blocker --- cross-persistence
transfer rollback --- has been addressed with compensating rollback and
corresponding regression tests.

The remaining items are primarily about:

1.  ensuring transfer-chain semantics exactly match the intended FPL
    accounting;
2.  preventing scientific evaluation from silently hiding failures;
3.  verifying Gameweek finalization in edge cases;
4.  keeping the audit documentation synchronized;
5.  cleaning up release-status/test-count inconsistencies.

After these are resolved, V0.65 should be frozen and merged rather than
expanded further.
