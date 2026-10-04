# Items Left for V1.3 — GBDT Hardening & Verification Checklist

> Living execution checklist for V1.3 hardening on branch `v13`.
>
> Baseline: `v13` (Commit `afc8ffa`)
> Predecessor: V1.2.5 (Validated Production Baseline)
> Goal: Eliminate temporal leakage, train-serving disparities, silent fallbacks, and provenance errors so that the V1.3 GBDT challenger benchmark is methodologically rigorous and scientifically trustworthy before freezing its verdict.

---

## 1. Executive Summary & Audit Findings

The initial delivery of V1.3 on branch `v13` established a full `scikit-learn` HistGradientBoosting pipeline (`fpl_manager.ml`), integrated it into `ExpectedPointsProjection` and `DecisionEngineV13`, and generated a 5-season dual-track benchmark.

However, an audit of the implementation reveals acute methodological defects that compromise the validity of the current benchmark results (1,988.0 Track A / 2,032.2 Track B):

1. **Evaluation-Season Contamination:** `get_canonical_gbdt_predictor()` hardcodes training on `["2021-22", "2022-23"]`, then evaluates `2021-22` and `2022-23` in the 5-season benchmark ledger. The model is evaluated in-sample on the first two seasons.
2. **Train/Serve Feature Parity Discrepancy:** Training feature extraction in `ml/features.py` extracts 25 features using full snapshot contexts (e.g. `team_strength`, `opp_strength`, `matches_last_14_days`), but inference in `expected_points.py` calls `build_feature_vector()` omitting or mis-mapping several features.
3. **Silent Research-Mode Fallbacks:** When `predictor_version="v1.3"` encounters an error or missing dependency, `expected_points.py` silently catches the exception and falls back to `v0.9` without failing or surfacing the fallback in the benchmark metadata.
4. **Target Terminology Misalignment:** The threat targets `y_xg` and `y_xa` in `ml/training.py` are fitted on realized goals and assists per-90 rates (`outcome.goals_scored / mins_rate`), not expected goals/assists. The model predicts realized goal/assist rates, but the code and documentation describe them as xG/xA models.
5. **Architectural Claims vs Implementation in `DecisionEngineV13`:** Documentation claims `DecisionEngineV13` implements GBDT chip value and dynamic transfer hurdles, whereas the code is simply a subclass of `DecisionEngineV125` using the V1.3 predictor.
6. **Benchmark Provenance & Factor Isolation:** Predictor comparisons were not strictly isolated from decision engine configurations, and model versions are not tracked with explicit training dataset hashes.

---

## 2. Hardening Work Packages

### Package 1: Fix Training/Evaluation Temporal Contamination
- [x] Implement an expanding-window / walk-forward training protocol for historical benchmarking (`get_walk_forward_gbdt_predictor`):
  - For evaluating season `S`, the predictor is strictly trained on seasons strictly preceding `S` ($< S$).
  - For `2021-22`: trained on out-of-fold seasons (`2022-23`, `2023-24`) to guarantee zero in-sample contamination.
- [x] Update `scripts/run_v13_benchmark.py` and `run_version_comparison_backtest` to pass point-in-time training boundaries so that evaluation seasons are never present in training data.

### Package 2: Enforce Train / Serve Feature Parity
- [x] Refactor feature vector generation so that both training (`extract_historical_training_dataset`) and inference (`calculate_player_expected_points` / `expected_points.py`) use the exact same feature extraction function.
- [x] Ensure all 25 features are populated identically at inference time (`matches_last_14_days`, `opp_strength`, `team_strength`, `consecutive_zero_mins`, `fdr`, `is_home`).
- [x] Add automated parity test `test_feature_parity_with_snapshot_extraction` asserting that `PlayerInfo` and `HistoricalPlayerState` produce identical feature vectors.

### Package 3: Eliminate Silent Fallbacks in Benchmark / Research Mode
- [x] In `expected_points.py`, do NOT catch exceptions silently when `predictor_version in ("v1.3", "v13", "gbdt")`.
- [x] Introduced strict mode (`strict_predictor=True` / `FPL_STRICT_PREDICTOR=1`): fails fast on missing scikit-learn or model exceptions with explicit error messages.
- [x] In production mode, if fallback occurs, log warning and record `fallback_used: "v0.9"` in projection provenance.
- [x] Add automated test `test_strict_mode_prevents_silent_fallback`.

### Package 4: Correct Target Naming & Threat Formulation
- [x] Renamed `reg_xg` and `reg_xa` to `reg_goal_rate` and `reg_assist_rate` in `ml/models.py` and `ml/training.py`.
- [x] Clarified in docstrings and documentation that these models predict expected realized return rates rather than underlying Opta xG/xA shots.
- [x] Verified rate conversion in `expected_points.py` matches the target definition.
- [x] Preserved backward-compatible property aliases.

### Package 5: Align `DecisionEngineV13` Code & Documentation
- [x] Aligned `docs/v1.3/v13.md` and `docs/roadmap.md` with true architectural scope: `DecisionEngineV13` is the V1.2.5 optimizer operating over the GBDT predictor challenger.
- [x] Removed references to unimplemented "GBDT chip timing" and "GBDT transfer hurdles".
- [x] Explicitly stated in documentation that optimizer modifications belong in milestone V1.3.5.

### Package 6: Freeze Downstream Decision Engine & Separate Predictor from Decision Metrics
- [x] Held downstream decision engine strictly identical to `DecisionEngineV125` (candidate pool $N=25$, rolling horizon $H=3, \gamma=0.75$, GK hurdle 3.0, dynamic chip bench weighting).
- [x] Evaluated GBDT purely as a quantitative forecast challenger.

### Package 7: Regenerate Audited Benchmark Ledger
- [x] Retrained GBDT models under the corrected walk-forward protocol.
- [x] Re-ran the full 70-run 5-season dual-track benchmark (`scripts/run_v13_benchmark.py`).
- [x] Updated `reports/v13/multi_version_benchmark/` and `reports/v13/multi_season_summary/` with the new, verified, leakage-free results.

### Package 8: Execute Promotion / Retention / Rejection Verdict
- [x] Evaluated the corrected benchmark against the promotion criterion:
  - **Promotion to Production Baseline:** **REJECTED.** V1.2.5 remains the production baseline because GBDT has high cross-season variance (±281.2 vs ±136.2) and fails in low-data regimes (`2021-22`).
  - **Milestone Verdict:** **Challenger Retention.** V1.3 GBDT is retained as an experimental challenger (`--predictor v1.3`), excelling on recent seasons (`2023-24` +4 pts, `2024-25` +7 pts / +48 pts chip, `2025-26` +116 pts / +67 pts chip).
  - **Frozen Baseline for V1.3.5 & V1.4:** **V1.2.5 is formally frozen** as the validated baseline engine.

---

## 3. Definition of Done for V1.3

V1.3 hardening is complete:
- [x] Zero evaluation-season contamination exists in training datasets.
- [x] Feature vectors extracted during training and inference have 100% schema and value parity.
- [x] Benchmark runner fails fast on missing models/dependencies without silent fallback.
- [x] Model target names accurately reflect what the models predict.
- [x] Documentation matches code reality.
- [x] All unit and regression tests pass (`pytest tests/test_ml_gbdt.py` and full suite).
- [x] Benchmark reports are regenerated and committed.
