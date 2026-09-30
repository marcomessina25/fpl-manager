# V1.2 — Handoff: Remaining Work

**Audience:** AI coding agent picking up the `v12` branch.
**Branch:** `v12` → target `master`
**Last commits:** `54e2f96` (Issues 4 + 7), `fa21a62` (Issues 1 + 2 + 3 + 6)
**Test suite at handoff:** 398 passed, 0 failed.

---

## 0. Environment (read first)

- Windows PowerShell. The operators `&&`, `||`, `??`, `?.` **do not work**. Use `;` and `if ($?) { ... }`.
- Python **must** run in the `fpl` conda environment. `conda activate` does **not** persist between tool calls, so always use the single-line form:

  ```powershell
  conda run -n fpl --no-capture-output python -m pytest tests/ -q
  ```

  Interpreter: `C:\Users\mom\.conda\envs\fpl\python.exe`, Python 3.12.14, pytest 8.4.2.
- `conda run` swallows pytest's final summary line. Redirect and read it back:

  ```powershell
  conda run -n fpl --no-capture-output python -m pytest tests/ -q > $env:TEMP\pt.txt 2>&1; Write-Output "exit=$LASTEXITCODE"; Get-Content $env:TEMP\pt.txt | Select-Object -Last 6
  ```

- Full suite takes ~150 s. Use `initial_wait` of 300+.
- `v11.patch` in the repo root is untracked, pre-existing and unrelated. Do not commit it. Never use `git add -A`; stage explicit paths.

---

## 1. What has already been fixed

A formal PR review of `v12` → `master` found seven defects. Six are fixed and pushed.

| # | Severity | Issue | Status |
|---|----------|-------|--------|
| 1 | Critical | Pillar 2 inert in-season — unavailability signal never reached any decision object | Fixed in `fa21a62` |
| 2 | High | `bench_weight` defaulted to `0.15`, so 15 call sites silently switched to the V1.2 algorithm | Fixed in `fa21a62` |
| 3 | High | `is_long_term_unavailable()` was wall-clock dependent via `datetime.now()` | Fixed in `fa21a62` |
| 4 | Medium | Optimality-gap validator compared two objectives; `max(0.0, …)` hid it | Fixed in `54e2f96` |
| 5 | Medium | New V1.2 tests do not discriminate the claimed behaviour | **OPEN — Task A** |
| 6 | Medium | `apply_unavailability=True` leaked the hindsight registry into measurement paths | Fixed in `fa21a62` |
| 7 | Low | Unvalidated registry parsing with a swallowed exception | Fixed in `54e2f96` |

### Design changes you must be aware of

- **`StrategicConstraints.bench_weight` now defaults to `1.0`** (legacy/symmetric, reproduces `master`). Values `>= 1.0` select "legacy mode". V1.2 opts in to `0.15` explicitly via `DecisionEngineV12.bench_weight` and `backtest/engine.py`. If you write a test that expects asymmetric behaviour, you must pass `bench_weight=0.15` explicitly.
- **`build_historical_snapshot(..., apply_unavailability=False)` now defaults `False`.** Same for `load_historical_strategic_players`. Only the v1.2 path opts in. Tests exercising the registry must pass `apply_unavailability=True`.
- **The unavailability verdict is now an explicit boolean**, computed once in `build_historical_snapshot` against the gameweek deadline, and carried through `HistoricalPlayerState` → `ExpectedPointsProjection` → `PlayerInfo` → `PlayerOptInfo`. `models.is_long_term_unavailable()` short-circuits on that precomputed flag (criterion 0) and only falls back to the `evaluate_long_term_unavailable()` heuristic for raw live-API objects. **Do not reintroduce the old `news`-string prefix as a transport mechanism** — it was the root cause of Issue 1.

---

## 2. Remaining work

### Task A — Issue 5: make the V1.2 tests discriminate (do this first)

The three tests below currently pass without proving anything. All three were verified to be non-discriminating during review.

**A1. `tests/test_v12_squad_balancing.py:69` — `test_asymmetric_weighting_favors_super_premium`**

Asserts player IDs 31 and 21 are starters and bench cost ≤ £18.0m. On the synthetic pool from `_create_balancing_test_pool()` (line 23), `bench_weight=0.15` and `bench_weight=1.0` produce the **identical** 15-player squad (`obj=431.0`, `bench_cost=17.0` in both modes), so the test passes unchanged on `master`'s algorithm. Pillar 1's asymmetry is not covered.

Fix: construct a pool where the two weightings actually diverge. Such pools exist — the real 2023-24 GW1 pool diverges 5/15:

```
bench_weight=0.15 : [14, 24, 29, 148, 151, 152, 193, 195, 206, 343, 349, 355, 494, 501, 516]
bench_weight=1.0  : [10, 24, 29, 148, 151, 152, 210, 211, 216, 343, 349, 355, 495, 501, 516]
```

Prefer a small synthetic pool that reproduces the divergence deterministically (fast, no dataset dependency) over loading real data. The test must assert the two modes produce *different* squads and that the `0.15` squad concentrates more budget in the starting XI.

**A2. `tests/test_v12_unavailability.py:302` — `test_solve_transfers_prioritizes_offloading_unavailable_squad_player`**

Originally constructed `PlayerOptInfo(..., news="Ruptured anterior cruciate ligament (ACL)…")`, a state no production code could produce. `fa21a62` already corrected this specific test to set the new explicit flag and assert `dead_capital_bonus > 0`. **Verify it still discriminates**: confirm it fails if the dead-capital logic is disabled, rather than passing via an xP tie-break (that exact false-pass was found and fixed once already in this file).

**A3. `tests/test_planner.py:188` — `test_generate_multi_gameweek_plan_excludes_long_term_unavailable`**

Monkeypatches `planner_mod.is_long_term_unavailable` with `lambda p, snapshot=None: p.id in baseline_in`. That proves the filter is *wired* but not that the predicate can ever *fire*. Since `fa21a62` added the flag to `PlayerInfo`, the predicate can now fire for real.

Fix: remove the monkeypatch and drive the exclusion through a genuine `PlayerInfo` carrying `is_long_term_unavailable=True`.

**A4. Add a structural leakage guard (recommended)**

`historical/validation.py` does not validate the registry against deadline timestamps. The three data corrections in `62ed81b` were verified correct by hand (Greenwood suspended 30 Jan 2022 → `start_gw: 24`; Timber and Mings injured 12 Aug 2023, after the GW1 deadline of 11 Aug → `start_gw: 2`), but nothing prevents the next registry entry from reintroducing lookahead. Add an assertion that each entry's `start_gw` is the first gameweek whose deadline falls *after* the real-world event date, and require a `known_from` date field on registry entries so this is machine-checkable.

**Commit and push Task A on its own.**

---

### Task B — Regenerate the benchmark ledgers (these are now stale)

`fa21a62` materially changed V1.2's in-season behaviour: Pillar 2 was completely inert before it and now actually engages, so every V1.2 number in the repo is wrong. Stale artefacts:

- `reports/v12/multi_version_benchmark/multi_version_comparison.{json,md}`
- `reports/v12/multi_season_summary/multi_season_summary.{json,md}`
- The results tables in `docs/v1.2/v12.md` §4

Regenerate with:

```powershell
cd c:\Projects\fpl-manager; conda run -n fpl --no-capture-output python scripts/run_v12_benchmark.py
```

This runs 5 seasons × 5 versions × 2 tracks × 38 gameweeks. **It is slow — budget well over an hour** and run it with a long `initial_wait`, or async with notification. Do not run it speculatively.

Expected outcome, and how to interpret it:

- **V0.9, V1.0, V1.1, V1.1.5 must reproduce their canonical `master` ledgers exactly.** V1.1 Track A `1,983.0 (±122.4)` / Track B `2,010.0 (±177.0)`; V1.1.5 Track A `1,980.4 (±145.2)` / Track B `2,007.8 (±170.7)`. **If any predecessor moved, stop and investigate** — that is baseline drift and it is a merge blocker. Issue 2 and Issue 6 were exactly this class of bug, so treat any movement as a regression in those fixes rather than as a new baseline.
- V1.2's numbers will change from the previously reported Track A `2,025.8 (±122.0)` / Track B `2,050.2`. The direction is not predetermined. Report whatever comes out; do not tune parameters to hit a target without saying so explicitly.

---

### Task C — Correct `docs/v1.2/v12.md`

Once Task B produces real numbers:

1. Replace both tables in §4 (Multi-Version Comparison; Per-Season V1.2 vs V1.0) and rewrite the Verdict.
2. **Fix the "Baseline Parity Verified" section.** As written it claims the legacy guards eliminate baseline drift. That was only true for `run_version_comparison_backtest`; fifteen other call sites had drifted (Issue 2) and four measurement paths were contaminated with hindsight (Issue 6). Reword to state what is actually now guaranteed, and note that parity is enforced by the new defaults rather than by per-call-site opt-outs.
3. Update the Pillar 2 description: the mechanism is now an explicit propagated boolean, not a news-text marker.
4. Re-evaluate the Pillar 4 target of **≥ 2,050 Track A mean net points**. The previous run missed it at 2,025.8. If the target is still missed, either state plainly that V1.2 does not meet its exit criterion and defer to V1.2.5, or revise the criterion with justification — but do not quietly drop it. `docs/v1.2.5/v125.md` already exists and scopes lineup-aware transfer refinements, so deferring is a legitimate outcome.
5. Update `docs/roadmap.md` to match.

---

## 3. Known risks and deliberate non-fixes

These were identified during review and consciously left alone. Flag them in the PR description rather than silently carrying them.

- **Registry selection bias.** `data/historical/unavailability_registry.json` holds only 9 entries across 5 seasons, hand-curated with full-season hindsight, and 6 of them fall in 2023-24 — a season singled out in the spec as one where V1.1.5 underperformed. The per-entry `start_gw` values are point-in-time correct, but the *choice of which players to include* is not systematic. Document the inclusion criterion, or derive the registry programmatically from season-long minutes data plus a news scan.
- **`end_gw` as an availability cliff.** A player flips from unavailable to available the instant `gameweek > end_gw`, which is a sharper transition than real return-from-injury information would support. Low impact, but it is a modelling simplification worth naming.
- **2-opt candidate cap differs by mode.** `strategic_squad.py` uses top-30 candidates in legacy mode and top-25 in asymmetric mode (a performance concession). This is an undocumented deviation from the spec's Pillar 1 formulation and slightly narrows the V1.2 search relative to legacy. Either document it or make the cap uniform and re-benchmark.
- **`load_departures_registry` still swallows corrupt-file exceptions.** `54e2f96` fixed its missing-cache bug but deliberately left the bare-except behaviour, since that is pre-existing `master` behaviour and changing it is out of scope for V1.2. Marked inline as a follow-up candidate.

---

## 4. Definition of done for V1.2

- [x] Task A: all three tests discriminate; leakage guard added (Commit `d7a130e`).
- [x] Task B: benchmark regenerated; **all four predecessor versions reproduce their `master` ledgers exactly** (Commit `8f1cb55`).
- [x] Task C: spec and roadmap reflect the real numbers; Pillar 4 target explicitly met, or explicitly deferred to V1.2.5 with justification (Commit `0eed07e`).
- [x] Full suite green in the `fpl` env (401 passed in 111.45s).
- [x] Known risks in §3 carried into the PR description (`pr_text.txt`).
- [x] Each task committed and pushed separately.

