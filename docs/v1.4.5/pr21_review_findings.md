# PR #21 Code Review Findings & Recommendations
**V1.4.5 — Strategic Chip Opportunity-Cost Optimizer Engine & 5-Season Ablation Study**

**Date:** October 8, 2026  
**Reviewer:** @copilot  
**PR Status:** ⚠️ **Not Ready to Merge** (Medium-High Risk)  
**Assessment:** Ambitious and theoretically sound, but operational proof of parity and behavioral guarantees must be established before shipping.

---

## Executive Summary

This PR introduces a unified `ChipOpportunityOptimizer` engine to replace legacy static threshold gates in chip deployment decisions. The mathematical framework is solid (opportunity-cost planning with window decay), and the 5-season ablation study demonstrates measurable performance gains (+118.0 pts mean surplus vs +39.0 baseline, 8.0% vs 48.0% wastage).

**However, three blocking gaps prevent safe merge:**

1. **Default behavior changed silently** — `SeasonalChipPolicy()` now delegates to the optimizer without explicit user control.
2. **Parity claim unproven** — PR docs claim "100% parity" between live and historical paths, but the code and audit docs still document remaining divergence.
3. **No CI or regression evidence** — No test results, no parity validation, no before/after comparison of actual chip decisions on realistic game states.

---

## 1. Core Changes & Intent

### What Changed
- **New file:** `src/fpl_manager/simulation/chip_optimizer.py` (721 lines)
  - Four strategy variants: C0 (legacy), C1 (linear decay heuristic), C2 (dynamic EV planner), C3 (surrogate continuation)
  - Canonical decision function: `Net Utility(C, t) = ΔEV(C, t) - max_{t' ∈ [t+1, T_window]} E[ΔEV(C, t')]`
  - Four hard guardrails: GW1 protection, post-Wildcard cooldown, postponed GW block, terminal window decay

- **Modified files:**
  - `src/fpl_manager/chip_strategy.py`: `SeasonalChipPolicy` now wraps the optimizer (default `use_optimizer=True`)
  - `src/fpl_manager/chip_strategy.py`: New `optimizer_chip_candidates()` function feeds optimizer output into live roadmap generation
  - `src/fpl_manager/simulation/session.py`: Historical recommendations now include `recommended_chip_opportunity` metadata
  - Version bumps: `pyproject.toml`, `src/fpl_manager/__init__.py`

- **New artifacts:**
  - `reports/v145/performance_leaderboard.md` — 5-season leaderboard (C1 wins with +118.0 pts)
  - `reports/v145/ablation_summary.md` — Variant ablation metrics
  - `reports/v145/seasonal_results/*.json` — Per-season detailed results (2021–2026)
  - `reports/v145/v145_baseline_decisions_ledger.csv/json` — Full decision audit trail

### Rationale
The legacy `SeasonalChipPolicy` suffered from a **100% Wildcard hoarding pathology**: Wildcards were never deployed across 5 historical seasons because the threshold (`deteriorated >= 4`) was almost never reached with active squad management. This led to 48% aggregate chip wastage.

The optimizer replaces rigid thresholds with dynamic opportunity-cost planning: a chip is deployed when its immediate EV exceeds the maximum future opportunity within the segment window. Terminal window decay naturally forces deployment near segment boundaries (GW 18–19, 36–38).

**Result:** C1 (linear-decay variant) generates +118.0 pts mean surplus, eliminates hoarding pathology, and achieves 8.0% wastage vs 48.0% baseline.

---

## 2. Critical Issues & Blocking Gaps

### 2.1 Default Behavior Change (High Risk)

**Issue:** `SeasonalChipPolicy` default behavior is now optimizer-driven globally.

```python
# src/fpl_manager/chip_strategy.py, line 860+
class SeasonalChipPolicy:
    use_optimizer: bool = True                        # ← NEW DEFAULT
    optimizer_variant: str = "c1_linear_decay"
    
    def evaluate_gameweek_chip(self, ...):
        if self.use_optimizer:                        # ← SILENT DELEGATION
            from .simulation.chip_optimizer import ChipOpportunityOptimizer
            opt = ChipOpportunityOptimizer(variant=self.optimizer_variant)
            return opt.evaluate_gameweek_chip(...)
        # ... legacy gates fallback
```

**Impact:**
- Any code instantiating `SeasonalChipPolicy()` without keyword args now runs the optimizer, not the legacy policy.
- The GUI server (`src/fpl_manager/gui/server.py` line 533) now recommends chip decisions from `ChipOpportunityOptimizer`, not legacy heuristics.
- Historical simulations now use the optimizer by default.
- **This is a silent, global behavior change affecting all chip decisions in the live system and all historical replays.**

**Recommendation:**
- Add a top-level deprecation warning in `SeasonalChipPolicy.__init__()` if `use_optimizer=True` is explicitly set or left at default.
- Require explicit opt-in: `use_optimizer=True` should only happen if a consumer explicitly sets it or passes a feature flag.
- Alternatively: ship V1.4.5 with `use_optimizer=False` by default, require live code to opt-in explicitly, then deprecate the legacy path in a follow-up release.

---

### 2.2 Parity Claim Is Unproven (High Risk)

**Issue:** PR docs repeatedly claim "100% architectural and decision parity", but the implementation and audit documents contradict this.

From the PR description:
> "Furthermore, the live `/api/chips` endpoint and the historical simulation engine now share 100% architectural and decision parity."

From `reports/v145/v145_pipeline_divergence_audit.md` (in this PR):
> "**Known gap**: the live `/api/chips` roadmap (`recommend_chip_strategy`) still builds its schedule from the legacy rating-based candidates; its new EV fields are placeholders derived from `rating`, not optimizer output. Full live/historical parity is NOT yet achieved."

**Contradiction:**
- The PR claims parity is achieved.
- The audit document (also in this PR) says parity is "NOT yet achieved" and flags the live roadmap as still using legacy rating-based candidates.
- The GUI server (`server.py` line 540) adds `immediate_ev`, `future_opportunity`, `net_utility`, `confidence` fields but many are derived from cached ratings, not live optimizer state.

**Risk:**
- Live recommendations and historical replays may diverge in subtle ways (e.g., edge cases around postponed GWs, cooldown boundaries).
- Users replaying historical decisions will not get identical recommendations as the live system.
- The "unified engine" claim is partially true (both paths *can* call the optimizer), but they do so via different entry points with different data freshness.

**Recommendation:**
1. Add a deterministic parity test:
   ```python
   def test_parity_live_vs_historical():
       """Verify identical chip decisions from live and historical paths."""
       live_recs = recommend_chip_strategy(...)  # Live path
       sim = HistoricalSimulationSession.create(...)
       hist_recs = sim.get_recommendations()      # Historical path
       assert live_recs['recommended_chip'] == hist_recs['recommended_chip']
       assert live_recs['immediate_ev'] ≈ hist_recs['immediate_ev']
   ```
2. Document known divergence points (if any remain) explicitly in a "Known Limitations" section.
3. Remove the "100% parity" claim from the PR description unless the test passes.

---

### 2.3 No CI or Regression Evidence (Medium-High Risk)

**Issue:** No test results, check-run status, or before/after behavioral comparison provided.

What's missing:
- ✗ CI status (green checks on GitHub Actions, unit tests passing)
- ✗ Regression test comparing optimizer output vs legacy policy output on known game states
- ✗ Before/after comparison of actual chip decisions for a fixed set of historical snapshots
- ✗ Performance benchmarks (runtime, memory usage of the optimizer vs legacy gates)
- ✗ Edge case validation (postponed GWs, extreme squad deterioration, late-season cooldowns)

**Risk:**
- The optimizer may have subtle bugs or unintended behavior on edge cases.
- Performance regression (e.g., optimizer runs slower than legacy gates) is undetected.
- New tests (`tests/test_chip_optimizer.py`) exist but CI results are not visible in the PR.
- A reviewer cannot assess merge readiness without seeing CI green.

**Recommendation:**
1. Ensure all CI checks pass before requesting merge. Link the CI run status here.
2. Add a focused regression suite:
   ```python
   @pytest.mark.parametrize("season,gw,expected_chip", [
       ("2023-24", 8, "wildcard"),      # Known chip deployment point
       ("2024-25", 15, "triple_captain"),
       ("2025-26", 30, None),            # No chip expected
   ])
   def test_regression_known_decisions(season, gw, expected_chip):
       """Verify optimizer produces expected decisions on historical snapshots."""
   ```
3. Run before/after comparison:
   - Load a frozen squad state from each historical season at GW 8, 15, 30.
   - Compare `SeasonalChipPolicy(use_optimizer=False).evaluate_gameweek_chip(...)` (legacy)
   - vs `SeasonalChipPolicy(use_optimizer=True).evaluate_gameweek_chip(...)` (optimizer)
   - Document which decisions changed, why, and whether the change is desirable.

---

## 3. Secondary Issues

### 3.1 Heuristic-Heavy Optimizer (Medium Risk)

The optimizer frames itself as "mathematically grounded", but the implementation is heavily heuristic-tuned:

**Immediate EV computation** (`_compute_immediate_ev`, lines 410–480):
- Triple Captain: `base_xp * start_p` (no DGW premium calibration)
- Bench Boost: `bench_xp + 3.0` (hardcoded DGW boost)
- Free Hit: `squad_blanks * 4.8 + dgw_gain * 3.5 + 2.0` (magic numbers)
- Wildcard: `hit_savings + persistence + expiry_urgency` where persistence is `min(10.0, remaining_gws * 0.6)` (tuned constant)

**Future opportunity scan** (`_compute_future_opportunity`, lines 495–540):
- Discount factor: `0.96` per gameweek (tuned)
- TC in DGW: `14.0 * discount` vs non-DGW: `8.0 * discount` (calibrated thresholds)
- Surrogate correction (`_apply_c3_surrogate_correction`): tabular weights calibrated on historical data (opaque)

**Linear decay (C1)** (`_evaluate_c1_linear_decay`, lines 577–619):
- Free Hit threshold decays from 8 to 11 active players as segment ends
- Triple Captain xp threshold decays as `11.0 * rem_fraction`
- These decay curves have no documented justification

**Impact:**
- The optimizer is not a pure opportunity-cost planner; it's a heuristic wrapper around calibrated thresholds.
- Changing a magic number (e.g., `3.5` to `3.2` for FH DGW gain) could silently change chip decisions across all seasons.
- No sensitivity analysis or robustness check for these constants.

**Recommendation:**
1. Document all magic numbers and their calibration sources in a comment block.
2. Consider extracting constants to a config dataclass:
   ```python
   @dataclass
   class OptimizerCalibration:
       free_hit_squad_blank_value: float = 4.8
       free_hit_dgw_gain: float = 3.5
       # ... etc
   ```
3. Add a note in docstrings: "This optimizer blends opportunity-cost planning with empirically calibrated heuristics. Magic numbers were tuned on 5-season FPL data (2021–2026)."

---

### 3.2 Incomplete Live/Historical Unification (Medium Risk)

The PR claims to unify the engines, but the code shows partial unification:

**Live path** (`recommend_chip_strategy`, line 395+):
```python
candidates = optimizer_chip_candidates(...)  # NEW: calls optimizer
# But then still applies legacy guards:
if chip == "freehit":
    is_bgw_or_dgw = cand.get("gw_type") in (...)
    has_squad_blanks = cand.get("squad_blanks", 0) >= 2
    if not is_bgw_or_dgw and not has_squad_blanks and cand.get("rating") < 10.0:
        continue  # ← Legacy guard still here
```

**Historical path** (`HistoricalSimulationSession.get_recommendations`, line 615+):
```python
opt = ChipOpportunityOptimizer(variant="c1_linear_decay")
opps = opt.evaluate_all_opportunities(...)
rec_opportunity = opps[rec_chip].to_dict()
```

**Divergence:**
- Live path runs the optimizer, then applies legacy guards on top.
- Historical path runs the optimizer without additional guards.
- If the legacy guard catches a case the optimizer would recommend, live and historical diverge.

**Recommendation:**
- Remove the legacy guards from `recommend_chip_strategy` if the optimizer has already applied guardrails.
- Or: document explicitly that the live path applies an additional layer of caution (legacy guards) to the optimizer output, and justify why.

---

### 3.3 Lack of Documentation Clarity (Low-Medium Risk)

**Issue:** PR docs mix analysis artifacts with implementation docs.

From the PR description:
> "A comprehensive **5-Season Ablation Study (2021–22 to 2025–26, 190 Gameweeks)** across 4 algorithmic candidates demonstrates that the winning variant (**C1: Linear Window-Decay Heuristic**) generates a **+118.0 pts mean surplus**..."

This is great, but it's presented as evidence of the PR's correctness in the PR body. In reality, the ablation study is a design validation tool—it justified picking C1 over C0/C2/C3. The PR should be judged on implementation quality, test coverage, and merge safety, not on the ablation study alone.

**Recommendation:**
- Move detailed ablation discussion to a separate design doc or RFC.
- Keep the PR description focused on: what changed, why it changed, and what risks remain.
- In the PR body, link to the ablation report in `reports/v145/` for reference, but don't use it as primary justification.

---

## 4. Positive Findings

### What's Done Well

1. **Solid mathematical framework**
   - Opportunity-cost planning with explicit future scanning is a principled approach.
   - Terminal window decay naturally prevents chip hoarding at segment boundaries.
   - Hard guardrails (GW1 protection, post-Wildcard cooldown) prevent obvious pathologies.

2. **Comprehensive test coverage**
   - `tests/test_chip_optimizer.py` includes 13 test cases covering guardrails, parity, edge cases, and determinism.
   - Tests for segment resolution, chip normalization, postponed GWs, cooldowns, and exhausted inventory.

3. **Thorough reporting**
   - 5-season ablation study with season-by-season breakdowns.
   - Performance leaderboard clearly shows C1 > C0 (+118 vs +39 pts mean surplus).
   - Pathology audit documents the Wildcard hoarding problem and its resolution.

4. **Backward compatibility fallback**
   - Legacy policy still accessible via `SeasonalChipPolicy(use_optimizer=False)`.
   - C0 baseline variant provided for comparison.

---

## 5. Merge Readiness Assessment

| Dimension | Status | Evidence |
| :--- | :---: | :--- |
| **Code Quality** | ✅ Good | Well-structured, type-hinted, modular design |
| **Test Coverage** | ✅ Good | 13 new tests for optimizer, existing tests in place |
| **CI Status** | ❌ **Unknown** | No CI run results visible in PR metadata |
| **Parity Proof** | ❌ **Missing** | Claim exists but test does not; audit doc contradicts claim |
| **Default Behavior** | ⚠️ **Unsafe** | Silent global change without opt-in guard |
| **Documentation** | ⚠️ **Partial** | Good ablation docs, but parity/limitations unclear |
| **Regression Tests** | ❌ **Missing** | No before/after comparison of actual decisions |
| **Review Approval** | ❌ **None** | No reviewer sign-off visible |

**Overall:** ❌ **Not Ready to Merge**

**Risk Level:** 🔴 **Medium-High**

---

## 6. Recommended Actions Before Merge

### Phase 1: Blocking Fixes (Must Have)

1. **CI Evidence**
   - Run full test suite and link green CI run here.
   - Ensure `tests/test_chip_optimizer.py` passes.
   - Ensure existing test suite still passes (no regressions in other modules).

2. **Parity Validation Test**
   ```python
   def test_parity_live_vs_historical_gw8_2023_24():
       """Verify live and historical paths produce identical recommendations for a known state."""
       live_recs = recommend_chip_strategy(start_gw=8, season="2023-24", ...)
       sim = HistoricalSimulationSession.create(season="2023-24")
       sim.advance_to(8)
       hist_recs = sim.get_recommendations()
       
       assert live_recs['recommended_chip'] == hist_recs['recommended_chip']
       assert abs(live_recs.get('immediate_ev', 0) - hist_recs.get('immediate_ev', 0)) < 0.1
   ```
   - Run on 5+ historical snapshots from different seasons/gameweeks.
   - Document any divergence points.

3. **Default Behavior Safeguard**
   - Either:
     - *Option A:* Change `use_optimizer` default to `False`, require explicit `use_optimizer=True` to opt-in.
     - *Option B:* Add a deprecation warning in `SeasonalChipPolicy.__init__()` when `use_optimizer=True`.
   - Add a feature flag or environment variable to control the default globally.

4. **Parity Claims Correction**
   - Remove "100% parity" from PR description or replace with "Achieved in historical path; live path still uses legacy guards."
   - Link to `v145_pipeline_divergence_audit.md` as the authoritative reference.

### Phase 2: Strong-to-Have (Should Have)

5. **Regression Comparison**
   - Create a small test comparing C0 (legacy) vs C1 (optimizer) decisions on 10–15 known historical snapshots.
   - Document which decisions changed and why.
   - Example:
     ```
     Snapshot: 2023-24, GW 8
     Legacy policy: no chip
     Optimizer C1:  wildcard
     Reason:       Squad deterioration threshold now triggered by dynamic scoring, not static gate
     Risk:         None (change is intentional and desired)
     ```

6. **Magic Number Documentation**
   - Add a `# CALIBRATION` comment block above each hardcoded constant in `_compute_immediate_ev` and discount logic.
   - Reference the ablation study or historical tuning process.

7. **Guardian Test for Edge Cases**
   - Postponed GW with 2 fixtures (should block BB, TC)
   - Squad with 10+ injured players at GW 2 (should not burn Wildcard)
   - Final gameweek of segment (GW 19 / 38) with all chips available (should deploy highest-utility chip)

### Phase 3: Nice-to-Have

8. **Performance Benchmarking**
   - Measure runtime: legacy gates vs optimizer evaluation
   - Measure memory: optimizer state tracking
   - Document if optimizer is faster/slower/similar.

9. **Split Report and Code**
   - Consider moving `reports/v145/` artifacts to a separate commit or PR.
   - Makes code review cleaner (code PR vs analysis PR).

---

## 7. Suggested Merge Plan

**Assuming all Phase 1 and Phase 2 fixes are in place:**

1. **Merge to `v145` branch first** (development branch).
   - Keep `v145` as the experimental optimizer branch.
   - Allow time for integration testing, user feedback.

2. **Run extended validation** (2–4 weeks):
   - Deploy to staging environment if available.
   - Compare live recommendations vs historical replays on current live squad state.
   - Gather performance metrics.

3. **Merge to `main` only after**:
   - Phase 1 & 2 items are complete and tested.
   - Extended validation shows no regressions or surprises.
   - A release note is prepared explaining the chip decision behavior change.

4. **Release notes should include**:
   - "Chip deployment logic migrated from static thresholds (V1.3.5) to dynamic opportunity-cost planning (V1.4.5)."
   - "Wildcard hoarding pathology eliminated (0% wastage vs 48% baseline)."
   - "Known limitation: live and historical chip recommendations may differ in edge cases due to data freshness divergence."
   - "To revert to legacy behavior: `SeasonalChipPolicy(use_optimizer=False)`."

---

## 8. Conclusion

**This is strong work on a difficult problem.** The opportunity-cost framework is mathematically sound, the ablation study is thorough, and the code is well-structured. The 5-season analysis clearly shows the optimizer solves the Wildcard hoarding pathology.

**However, shipping this as V1.4.5 requires closing three operational gaps:**
1. Prove parity between live and historical paths with a deterministic test.
2. Make the default behavior change explicit and controllable.
3. Provide CI evidence and regression validation.

**Recommendation: Request Phase 1 & 2 fixes before approving merge.** Once those are in, this PR is solid and safe to merge.

---

## Appendix A: Quick Fix Checklist

```markdown
- [ ] CI run passes (link here: _________________)
- [ ] Parity test written and green
- [ ] Default behavior safeguard added (opt-in or deprecation warning)
- [ ] PR description updated to remove "100% parity" claim (or replace with accurate statement)
- [ ] Regression comparison completed (10+ historical snapshots)
- [ ] Magic numbers documented with calibration sources
- [ ] Edge case tests added (postponed GW, extreme deterioration, late-season)
- [ ] Release notes draft prepared
- [ ] Author/reviewer sign-off on merge plan
```

---

**Questions for the Author:**

1. Can you run the full CI suite and link the results here?
2. Do you have a specific reason for making `use_optimizer=True` the default? Would an opt-in approach be feasible?
3. Have you validated the parity claim by comparing live vs historical recommendations on a fixed set of game states?
4. Are there any known edge cases where the optimizer behavior differs from legacy policy, and why is that change desirable?

---

**Prepared by:** GitHub Copilot (@copilot)  
**Date:** October 8, 2026
