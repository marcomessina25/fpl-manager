# V1.2.5 — Detailed Implementation Plan

**Status:** Ready for execution
**Target Branch:** `v125` (branch from `v12` after the V1.2 PR merges; if V1.2 is still open, branch from `v12` and target the PR at `v12`, not `master`)
**Predecessor:** V1.2 (Strategic Squad Balancing & Long-Term Unavailability)
**Architectural Specification:** [`v125.md`](v125.md) — *this document is the execution plan for that spec*
**Primary Objective:** Track A $\ge 2{,}060.0$ and Track B $\ge 2{,}110.0$ mean net pts across the 5-season audited benchmark, surpassing V1.0 (2,048.4 / 2,108.0).

---

## 0. Ground Truth — Verified Starting State

Every number below was measured on branch `v12`, not estimated. Re-verify before starting if the branch has moved.

### 0.1 Benchmark baseline (5 seasons, GW 1–38)

| Version | Track A Mean | Track B Mean |
|---|---:|---:|
| V0.9 | 1,983.6 (±212.8) | 2,048.2 (±169.4) |
| V1.0 | **2,048.4** (±205.2) | **2,108.0** (±178.9) |
| V1.1 | 1,983.0 (±122.4) | 2,010.0 (±177.0) |
| V1.1.5 | 1,980.4 (±145.2) | 2,007.8 (±170.7) |
| V1.2 | 2,025.8 (±122.0) | 2,050.2 (±151.7) |

V1.2 per-season Track A: 2021-22 **1983**, 2022-23 **1867**, 2023-24 **2174**, 2024-25 **2120**, 2025-26 **1985**.

### 0.2 Measured pillar decomposition of V1.2's +45.4 over V1.1.5

| Pillar | Mechanism | Contribution |
|---|---|---:|
| Pillar 1 | `bench_weight` 0.15 vs 1.0 | **+24.2** |
| Pillar 2 | Unavailability registry | **+0.0** |
| Pillar 3 + dead capital | Lineup-aware transfer eval | **+21.2** |

Per-season Pillar 1 delta: +56 / −21 / +21 / +64 / +1. **Note the −21 in 2022-23** — asymmetric weighting is not a uniform win, and any V1.2.5 change that amplifies it can make that season worse. Track this cell explicitly.

### 0.3 Critical finding V1.2.5 inherits

**Pillar 2 is inert.** Running V1.2 with an empty registry reproduces all five seasons *exactly*. The signal is live (15–17 players flagged per GW in 2023-24) but cannot affect outcomes: long-term unavailable players are excluded from the purchase pool, so they never enter a squad, so the `dead_capital_penalty` — which only applies to players already held — never has a subject. Two correct mechanisms that mutually pre-empt each other. Owned here as **Pillar 6**.

### 0.4 Runtime facts (supersede the V1.2 handoff's estimate)

- One season × one track × one version ≈ **4–6 s**.
- Full 50-cell benchmark ≈ **6.1 minutes**, not "well over an hour". Run it freely; it is not a scarce resource.
- Full test suite: **401 tests, ~112–150 s**.

### 0.5 Environment

```powershell
# PowerShell. && || ?? ?. do NOT work. Use ; and if ($?) { ... }
conda run -n fpl --no-capture-output python -m pytest tests/ -q > $env:TEMP\pt.txt 2>&1; Write-Output "exit=$LASTEXITCODE"; Get-Content $env:TEMP\pt.txt | Select-Object -Last 6
```

`conda run` swallows pytest's summary line — always redirect and read back. Interpreter `C:\Users\mom\.conda\envs\fpl\python.exe`, Python 3.12.14, pytest 8.4.2. `v11.patch` in the repo root is untracked, pre-existing and unrelated — never `git add -A`; stage explicit paths.

---

## 1. Code Under Change — Exact Locations

| File | Symbol | Line (on `v12`) | Role |
|---|---|---:|---|
| `backtest/decision_engine.py` | `_evaluate_squad_lineup_xp` | 1171 | Lineup objective; `bench_w` default 0.15 |
| `backtest/decision_engine.py` | `DecisionEngineV12` | 1204 | Engine class |
| `backtest/decision_engine.py` | `.decide_transfers` | ~1330–1455 | Transfer loop; `max_results=5` at ~1424 |
| `backtest/decision_engine.py` | `._is_dead_capital` | 1233 | Pillar 2 consumer |
| `backtest/decision_engine.py` | `resolve_decision_engine` | 1463 | Version alias dispatch |
| `optimizer.py` | `solve_transfers` | 127 | Branch-and-bound; `max_results=15`, `cand_limit` 60/45/30/25 |
| `backtest/engine.py` | `run_sequential_simulation` | ~380–500 | `apply_dep` / `apply_unavail` gating at 404–405 |
| `backtest/strategic_analysis.py` | `run_version_comparison_backtest` | 1660 | Benchmark harness |
| `strategic_squad.py` | `solve_strategic_squad` | — | Squad solver; legacy mode when `bench_weight >= 1.0` |

### 1.1 Two pre-existing defects to resolve while here

**(a) Captain weight diverges from spec.** `v12.md` Pillar 1 specifies $0.8 \times \text{Value}(\text{Captain})$, but `_evaluate_squad_lineup_xp:1188` applies a full `1.0 × cap_val`:

```python
score = st_val + cap_val + bench_w * bench_val   # cap_val at 1.0, spec says 0.8
```

Decide deliberately in Task 1: either change the code to 0.8 and re-benchmark, or amend the spec to 1.0. Do not leave them contradictory. Treat any resulting benchmark movement as a *measured* change, not drift.

**(b) 2-opt candidate cap differs by mode.** `strategic_squad.py` uses top-30 in legacy mode and top-25 in asymmetric mode, narrowing V1.2's search relative to `master`. Undocumented deviation from the spec. Make uniform (preferred) or document.

---

## 2. Non-Negotiable Invariants

These hold at **every commit**, not merely at the end. Any violation is a stop-and-investigate, never a new baseline.

1. **Predecessor parity.** V0.9 / V1.0 / V1.1 / V1.1.5 reproduce their `master` ledgers with 0.0 drift, all 5 seasons, both tracks. V1.1 Track A 1,983.0 (±122.4); V1.1.5 Track A 1,980.4 (±145.2).
2. **V1.2 immutability.** `DecisionEngineV12` behaviour is frozen. V1.2.5 lands as `DecisionEngineV125`. If a V1.2 number moves, a shared code path was edited without gating — revert and re-gate.
3. **Safe defaults preserved.** `StrategicConstraints.bench_weight` defaults `1.0`; `build_historical_snapshot(..., apply_unavailability=False)` and `load_historical_strategic_players(..., apply_unavailability=False)` default `False`. New parameters follow the same rule: **default to existing behaviour, opt in explicitly.** This is precisely how V1.2's Issue 2 and Issue 6 arose.
4. **No lookahead.** No `datetime.now()` in decision paths; point-in-time snapshots only.
5. **Tests must discriminate.** Every new test must fail when its feature is disabled. V1.2 shipped three non-discriminating tests (Issue 5) — see §6.
6. **Benchmark before/after every pillar.** Cheap (6 min). Never batch two pillars into one measurement.

---

## 3. Pillar → Task Map

| Pillar (spec §3) | Task | Expected Track A |
|---|---|---:|
| Scaffold `DecisionEngineV125` | Task 1 | +0.0 (exact V1.2 parity) |
| Pillar 1: Candidate pool expansion | Task 2 | +10 to +25 |
| Pillar 2: GK churn suppression | Task 3 | +15 to +30 |
| Pillar 3: Multi-GW horizon (H=3, γ=0.75) | Task 4 | +15 to +35 |
| Pillar 4: DGW/BGW awareness | Task 5 | +5 to +15 (Track B mainly) |
| Pillar 5: Dynamic chip bench weights | Task 6 | Track B +25 to +35 |
| **Pillar 6: Resolve inert unavailability** | Task 7 | +0 to +10 (correctness) |
| Benchmark, ledger, docs | Tasks 8–10 | — |

Targets are hypotheses to be tested, **not** quotas. If a pillar measures negative, report it and keep it gated off rather than tuning until it looks good. V1.2 was damaged by exactly that pressure.

---

## 4. Task-by-Task Execution (TDD)

Each task: failing test → implementation → passing test → targeted benchmark → commit + push.

---

### Task 1 — Scaffold `DecisionEngineV125` with verified V1.2 parity

**Goal:** A new engine that is byte-identical to V1.2 in behaviour. Nothing else. This is the safety harness for every later task.

**Steps**
1. Add `DecisionEngineV125(DecisionEngineV12)` in `backtest/decision_engine.py`. Override only `version` → `"v1.2.5"` and `describe()`. No behavioural change.
2. Register aliases `"v1.2.5"`, `"v125"`, `"balanced_v125"` in `resolve_decision_engine`.
3. Extend the `apply_dep` / `apply_unavail` gates in `backtest/engine.py:404-405` to include `"v1.2.5"`:
   ```python
   apply_dep = (dec_engine.version in ("v1.1.5", "v1.2", "v1.2.5"))
   apply_unavail = (dec_engine.version in ("v1.2", "v1.2.5"))
   ```
   Audit for other `== "v1.2"` / `in (...)` comparisons and update each deliberately. Missing one silently reverts V1.2.5 to V1.1 behaviour.
4. Resolve defect §1.1(a) (captain weight) and §1.1(b) (candidate cap) — decide, implement, record the decision in the commit message.

**Test contract** (`tests/test_v125_engine.py`)
- `test_v125_resolves_from_all_aliases`
- `test_v125_matches_v12_decisions_on_fixed_snapshot` — same snapshot, same seed: identical transfer list and identical initial squad.

**Validation**
```powershell
cd c:\Projects\fpl-manager; conda run -n fpl --no-capture-output python scripts/run_v12_benchmark.py
```
Add `"v1.2.5"` to the `versions` tuple. **Gate: V1.2.5 Track A == 2,025.8 exactly and per-season 1983/1867/2174/2120/1985.** If §1.1(a) changed the captain weight, V1.2 *and* V1.2.5 both move together — record both new values as the new reference before continuing.

**Commit:** `feat(v1.2.5): scaffold DecisionEngineV125 with verified V1.2 behavioural parity`

---

### Task 2 — Pillar 1: Candidate pool expansion & direct lineup ranking

**Root cause (spec §2.1):** `solve_transfers` ranks by *unweighted 15-player squad delta* and returns only `max_results=5`. `DecisionEngineV12` then re-scores those 5 with the asymmetric lineup objective. A starting-XI upgrade ranked 6th–20th on flat squad sum is discarded before lineup scoring ever runs.

**Steps**
1. Add `max_results: int = 5` as a `DecisionEngineV125.__init__` parameter (default preserves V1.2); set the V1.2.5 default to `50`.
2. Replace the hardcoded `max_results=5` at ~line 1424 with `self.max_results`.
3. Sweep `max_results` ∈ {5, 25, 50, 100} on 2023-24 and 2024-25 Track A. Record all four; pick on measured evidence, not the spec's guess.
4. If wall-clock per cell exceeds ~15 s at 50, raise `cand_limit` instead (it already defaults 60/45/30/25 by K) — it prunes earlier and more cheaply than widening `max_results`.
5. *Optional, only if step 3 underdelivers:* add native lineup-aware ranking inside `solve_transfers` behind a default-off `objective="lineup"` flag. Higher risk — `solve_transfers` is shared with V1.0/V1.1/V1.1.5, so the flag **must** default to existing behaviour.

**Test contract** (`tests/test_v125_transfer_refinements.py`)
- `test_expanded_candidate_pool_surfaces_starter_upgrade_ranked_outside_top5` — construct a squad where the best lineup-xP move ranks ~8th by flat squad delta. Assert V1.2 (`max_results=5`) **misses** it and V1.2.5 (`max_results=50`) **takes** it. This two-sided assertion is what makes the test discriminate.

**Gate:** predecessors unmoved; V1.2 unmoved; V1.2.5 Track A strictly > 2,025.8.

**Commit:** `feat(v1.2.5): expand transfer candidate pool before lineup re-scoring (Pillar 1)`

---

### Task 3 — Pillar 2: Goalkeeper churn suppression

**Root cause (spec §2.2):** 2023-24 burned 5 free transfers on goalkeeper swaps (GW09/11/17/32/38). Cheap GKs plus ±1.0–1.5 xP clean-sheet swings make GK moves look efficient to a 1-GW evaluator, while starving explosive outfield rotations.

**Steps**
1. Add to `DecisionEngineV125`:
   ```python
   gk_min_net_gain: float = 1.50
   outfield_min_net_gain: float = 0.50
   gk_play_probability_floor: float = 0.50
   ```
2. In `decide_transfers`, after computing `net_gain`, derive the hurdle from the positions of the outgoing players and require `net_gain > hurdle` rather than the flat `min_net_gain`.
3. Playing-security invariant: reject a GK transfer unless the outgoing GK has `play_probability < 0.50`, **or** the move clears a 3-GW net gain ≥ 3.0 (this half depends on Task 4; land the `play_probability` half here and wire the 3-GW clause in Task 4).
4. **Instrument GK transfers per season** — you cannot verify the ≤2/season target without counting. Add a counter to the ledger record in `run_version_comparison_backtest` alongside `departure_tx_count`.

**Test contract**
- `test_gk_swap_below_hurdle_rejected_outfield_swap_above_hurdle_accepted` — identical net gain of 1.0 for both; assert GK rejected, outfield accepted.
- `test_gk_transfer_allowed_when_incumbent_injured` — `play_probability=0.1` ⇒ permitted despite small gain.
- Each must fail with the hurdles reverted to flat `0.50`.

**Gate:** 2023-24 GK transfers drop 5 → ≤2. Watch 2022-23 (already −21 on Pillar 1) for compounding damage.

**Commit:** `feat(v1.2.5): add position-specific transfer hurdles and GK playing-security invariant (Pillar 2)`

---

### Task 4 — Pillar 3: Multi-gameweek discounted lineup horizon

**Highest-value and highest-risk task.** Root cause (spec §2.3): `_evaluate_squad_lineup_xp` sees only GW+1, causing panic sales on 1–2 week knocks. The 2023-24 GW20–23 Haaland → Watkins → Salah → Richarlison churn is the worked example.

$$\Delta xP_{\text{rolling}} = \sum_{t=0}^{H-1} \gamma^t \left( \text{LineupXP}_{GW+t}(S_{\text{new}}) - \text{LineupXP}_{GW+t}(S_{\text{old}}) \right) - \text{HitCost}, \quad H=3,\ \gamma=0.75$$

**Steps**
1. Implement alongside the existing function — **do not modify `_evaluate_squad_lineup_xp`**, which V1.2 depends on:
   ```python
   def _evaluate_squad_multi_horizon_lineup_xp(
       squad, projections_by_gw, horizon=3, gamma=0.75, bench_w=0.15
   ) -> float:
   ```
   Reuse the single-GW function per gameweek and discount; do not duplicate the formation search.
2. Source forward projections **point-in-time**. This is the leakage-critical step of the whole release: projections for GW+1 and GW+2 must be produced from data available at the GW deadline. Reuse the existing multi-GW projection path that `solve_strategic_squad` already uses for its `horizon` parameter rather than inventing a second one.
3. Degrade gracefully at season end (GW 37–38): shrink the horizon instead of erroring or zero-filling.
4. Sweep $H \in \{1,2,3,4\}$ and $\gamma \in \{0.6, 0.75, 0.9\}$ on 2023-24 + 2024-25. Report the grid; pick on evidence.
5. Wire the 3-GW clause of the GK invariant from Task 3.

**Test contract**
- `test_multi_horizon_prefers_sustained_fixtures_over_single_week_spike` — player A spikes at GW+1 then collapses; player B is steady across 3. H=1 picks A, H=3 picks B.
- `test_multi_horizon_holds_premium_through_short_absence` — replicate the GW20 Haaland knock; assert V1.2.5 holds.
- `test_multi_horizon_truncates_at_season_end` — at GW 37 with H=3, no error.
- `test_multi_horizon_uses_no_future_information` — assert projections are drawn from the snapshot, not outcomes. **Non-negotiable.**

**Gate:** 2023-24 ≥ 2,240 and 2024-25 ≥ 2,220 (spec §5). Full benchmark; confirm no predecessor drift, since this task touches shared projection plumbing.

**Commit:** `feat(v1.2.5): add rolling 3-GW discounted lineup horizon (Pillar 3)`

---

### Task 5 — Pillar 4: Double/blank gameweek awareness

Largely emergent from Task 4 — a DGW player accrues two fixtures of xP inside the H=3 window automatically. This task **verifies** that rather than adding heuristics.

**Steps**
1. Confirm the projection path multiplies per-fixture xP for multi-fixture gameweeks. If it silently takes only the first fixture, fix that — it is a latent bug affecting V1.1+ as well (flag separately; do not silently alter predecessor behaviour).
2. Only if measurement shows a real gap, add explicit `FixtureDensity(p, t)` weighting.

**Test contract**
- `test_double_gameweek_player_projects_two_fixtures`
- `test_blank_gameweek_player_projects_zero`

**Gate:** inspect GW34/GW37 2023-24 decisions for DGW loading.

**Commit:** `feat(v1.2.5): verify and enforce DGW/BGW fixture-density handling (Pillar 4)`

---

### Task 6 — Pillar 5: Dynamic chip-aware bench weighting

**Root cause (spec §2.4):** V1.2 realizes only +24.4 pts from chips vs V1.0's +59.6. A squad built assuming bench = 0.15× is structurally wrong for Bench Boost, where all 15 players score.

| Context | `bench_weight` |
|---|---:|
| Standard GW | 0.15 |
| Free Hit | 0.05 |
| 1–2 GWs before Bench Boost | 0.60 |
| Bench Boost GW | 1.00 |

**Steps**
1. Thread active/planned chip context into `initialize_squad` and `decide_transfers`. **Caution:** `bench_weight >= 1.0` selects the *legacy symmetric* path in `solve_strategic_squad`. The Bench Boost value of exactly `1.00` will therefore trip legacy mode. Either use `0.99`, or add an explicit mode flag independent of the weight's magnitude. **This is the single most likely silent failure in the release.**
2. Pre-BB window requires knowing the chip plan in advance — reuse the existing V1.1.5 seasonal chip planner. Do not peek at future gameweek outcomes to decide.
3. Track A must be **completely unaffected** (no chips) — a Track A movement here proves the chip context leaked into non-chip paths.

**Test contract**
- `test_free_hit_concentrates_budget_in_starting_xi` — starting XI cost ≥ £83.5m.
- `test_bench_boost_squad_has_fifteen_playing_assets`
- `test_bench_boost_weight_does_not_trigger_legacy_symmetric_mode` — guards step 1's trap.
- `test_track_a_unaffected_by_chip_bench_weighting`

**Gate:** Track B chip delta ≥ +50.0; **Track A byte-identical to Task 5's result.**

**Commit:** `feat(v1.2.5): dynamic chip-aware bench weighting (Pillar 5)`

---

### Task 7 — Pillar 6: Resolve the inert unavailability mechanism

**This task exists because of §0.3 and has no counterpart in the original spec.**

V1.2 ships a registry that provably changes nothing. Three honest options — **decide explicitly, do not leave it ambiguous**:

- **Option A — Make it bite (preferred).** The mechanism fails because exclusion pre-empts the penalty. The penalty is only reachable for a player who becomes unavailable *while held*. Verify whether `_is_dead_capital` is ever consulted for a held player whose flag flips mid-season; if the engine already sells them on pure xP collapse before the penalty applies, the penalty is genuinely redundant and Option B follows. If it does *not*, make the penalty fire and measure.
- **Option B — Remove it.** Delete the registry, the flag propagation, and the purchase exclusion. Defensible: zero measured value, 9 hand-curated entries, hindsight selection bias (6 of 9 in 2023-24). Reduces surface area.
- **Option C — Keep, documented as inert.** Only if a live-API (non-backtest) path demonstrably benefits. If so, **prove it with a test on the live path**, since backtest evidence says +0.0.

**Steps**
1. Instrument: count how many times per season a *held* player's unavailability flag is true at decision time. If that count is 0 across all 5 seasons, Option A is impossible and the choice is B or C.
2. Execute the chosen option.
3. If keeping: address the registry selection bias — document the inclusion criterion or derive entries programmatically from season-long minutes plus a news scan.
4. If removing: confirm the benchmark is unchanged (it must be, by §0.3) — a *perfect* regression test, since any movement means the ablation was wrong.

**Test contract**
- `test_held_player_becoming_unavailable_is_prioritized_for_sale` (Option A), or
- `test_registry_removal_does_not_change_benchmark` (Option B).

**Commit:** `fix(v1.2.5): resolve inert long-term unavailability mechanism (Pillar 6)`

---

### Task 8 — Full 5-season benchmark & ledger

1. Create `scripts/run_v125_benchmark.py` mirroring `run_v12_benchmark.py` with `versions=("v0.9","v1.0","v1.1","v1.1.5","v1.2","v1.2.5")`.
2. Confirm `decision_engine_version=",".join(versions)` in `strategic_analysis.py:1795` still derives provenance from the actual version list (fixed during the V1.2 review — do not let it regress to a hardcoded string).
3. Consider promoting the progress `print()` calls added at `strategic_analysis.py:1706/1721` to a `verbose: bool = False` parameter — library functions should not print unconditionally.
4. Write `reports/v125/` ledgers.
5. **Publish a pillar ablation table**, as in `v12.md` §4.1. V1.2 shipped claiming four working pillars when one contributed nothing; ablation is now a release requirement, not a nicety.

**Commit:** `feat(v1.2.5): add 5-season benchmark ledger with per-pillar ablation`

---

### Task 9 — Documentation

1. Update `v125.md` §4/§5 with measured results; replace every target with an outcome.
2. Update `docs/roadmap.md` §21 and the header baseline line.
3. If the Track A ≥ 2,060 target is missed, **state that plainly and either defer with justification or revise the criterion with reasoning.** Do not quietly drop it — V1.2 handled this correctly and that precedent holds.
4. Record the §1.1(a) captain-weight decision in `v12.md`/`v125.md` so spec and code agree.

**Commit:** `docs(v1.2.5): record measured benchmark outcomes and pillar ablation`

---

### Task 10 — PR preparation

Remote is **GitHub** (`marcomessina25/fpl-manager`), so `gh` / the GitHub compare URL apply — not Azure DevOps tooling.

1. Title, < 70 chars.
2. Body: `## Summary` + `## Test plan`. GitHub allows a large body, but keep it scannable — lead with the measured benchmark table and the pillar ablation.
3. **Stacked-branch check** — if V1.2 has not merged, target `v12`, not `master`, or the diff swallows V1.2's 17 commits:
   ```powershell
   git rev-list --count v12..v125; git rev-list --count master..v125
   ```
   Differing counts ⇒ target `v12`.
4. Create with `gh pr create --base <target> --head v125 --title "..." --body-file pr_text.txt`, or open the compare URL:
   ```
   https://github.com/marcomessina25/fpl-manager/compare/<target>...v125
   ```
   `pr_text.txt` is already gitignored — keep using it as the scratch body file.
5. Carry forward the §7 risks below, and state plainly whether the Track A / Track B targets were met.


---

## 5. Benchmark Protocol

After each pillar task:

```powershell
cd c:\Projects\fpl-manager; conda run -n fpl --no-capture-output python scripts/run_v125_benchmark.py > $env:TEMP\v125bench.txt 2>&1; Write-Output "exit=$LASTEXITCODE"; Get-Content $env:TEMP\v125bench.txt -Tail 20
```

Record in a running table committed with each task:

| Task | V1.2.5 Track A | Δ | V1.2 | V1.1.5 | V1.1 | V1.0 | V0.9 | GK tx (23-24) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Task 1 | 2025.8 | — | 2025.8 | 1980.4 | 1983.0 | 2048.4 | 1983.6 | 5 |

The five predecessor columns must never change. They are the drift alarm.

---

## 6. Testing Standards

1. **Discriminating by construction.** Verify each new test *fails* with its feature disabled — flip the flag, watch it go red, flip back. V1.2 shipped three tests that passed identically on `master`'s algorithm.
2. **No monkeypatching the predicate under test.** V1.2's `test_planner.py:188` monkeypatched `is_long_term_unavailable`, proving only that the filter was wired, not that it could fire. Drive behaviour through real domain objects.
3. **Beware xP tie-breaks.** A test can pass because two candidates tie on xP rather than because the feature fired. Make the intended winner unambiguous.
4. **Explicit opt-in in tests.** Asymmetric behaviour requires `bench_weight=0.15`; registry behaviour requires `apply_unavailability=True`. Defaults are deliberately legacy.
5. Full suite green (baseline **401 passed**) before every commit.

---

## 7. Risk Register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | `bench_weight=1.00` for Bench Boost trips legacy symmetric mode in `solve_strategic_squad` | **High** | Use 0.99 or a mode flag independent of magnitude; Task 6 test guards it |
| 2 | Multi-GW projections (Task 4) introduce lookahead | **High** | Reuse existing point-in-time horizon path; dedicated no-future-information test |
| 3 | Shared-path edits silently move predecessor baselines | **High** | New params default to existing behaviour; benchmark after every task |
| 4 | Widened `max_results` degrades runtime superlinearly | Medium | Sweep and measure; prefer `cand_limit` tuning |
| 5 | Parameter sweeps overfit 5 seasons | Medium | Prefer round defaults; report full sweep grids; treat 5 seasons as a small sample |
| 6 | GK hurdle blocks a *legitimate* GK change | Medium | `play_probability < 0.50` escape hatch |
| 7 | 2022-23 regresses further (already −21 on Pillar 1) | Medium | Track per-season, not just the mean |
| 8 | Target missed and pressure to tune to hit it | Medium | Report honestly and defer, per V1.2's precedent |
| 9 | Registry selection bias if Pillar 6 keeps the registry | Low | Document criterion or derive programmatically |
| 10 | `end_gw` availability cliff is sharper than reality | Low | Known simplification; name it |
| 11 | `load_departures_registry` swallows corrupt-file exceptions | Low | Pre-existing `master` behaviour; fix only if touched |

---

## 8. Definition of Done

- [ ] Task 1: `DecisionEngineV125` reproduces V1.2 exactly; captain-weight and candidate-cap divergences resolved.
- [ ] Tasks 2–6: each pillar implemented, discriminating tests, benchmarked independently.
- [ ] Task 7: inert unavailability mechanism explicitly resolved (make it bite / remove / justify).
- [ ] Predecessor parity: V0.9–V1.2 reproduce their ledgers with 0.0 drift at the final commit.
- [ ] Track A ≥ 2,060.0 **or** an explicit, justified deferral.
- [ ] Track B ≥ 2,110.0 **or** an explicit, justified deferral.
- [ ] Chip realization ≥ +50.0; GK transfers ≤ 2.0/season.
- [ ] Per-pillar ablation table published in `reports/v125/` and `v125.md`.
- [ ] Full suite green (≥ 401 passing).
- [ ] `v125.md` and `roadmap.md` reflect measured outcomes, not targets.
- [ ] PR body leads with the measured benchmark and ablation tables; correct target branch (`v12` if V1.2 is unmerged); risks carried forward.
- [ ] Each task committed and pushed separately.
