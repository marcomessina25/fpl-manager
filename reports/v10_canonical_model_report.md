# V1.0 Canonical Quantitative Model Report (P1.3)

> **Model Version:** `v1.0.0` (Frozen V0.9.1 Production Predictor & Calibration Baseline)
> **Training Data Cutoff:** Strictly prior to target Gameweek deadline (`GWs 1..N-1`)
> **Feature Set Version:** `v0.9.1-pit-rolling-congestion`
> **Parameter Version:** `1.0.0-frozen-v0.9.1-w0.00`
> **Evaluated Scope:** 29,338 point-in-time player-gameweek records (2025/26 full season) and 5-season sequential backtest (2021/22–2025/26, 190 Gameweeks).

---

## 1. Headline Expected Points (xP) Metrics (2025/26)

| Metric | V0.8 Baseline | V1.0 (`v0.9.1` Frozen) | Delta |
|---|---:|---:|---:|
| **xP MAE** | 1.150 pts | **1.127 pts** | **-0.023 pts** |
| **xP RMSE** | 1.984 pts | **1.978 pts** | **-0.006 pts** |
| **Spearman Rank Correlation ($\rho$)** | 0.6750 | **0.6779** | **+0.0029** |
| **Mean Prediction Bias ($\hat{y} - y$)** | +0.087 pts | **+0.058 pts** | **-0.029 pts** |

---

## 2. Expected Minutes (xM) & Availability Metrics

| Metric | V0.8 Baseline | V1.0 (`v0.9.1` Frozen) | Delta / Notes |
|---|---:|---:|---|
| **Unconditional xM MAE** | 13.919 mins | **13.679 mins** | **-0.240 mins** |
| **Unconditional xM RMSE** | 23.619 mins | **23.498 mins** | **-0.121 mins** |
| **Unconditional xM Bias** | -0.121 mins | **-1.226 mins** | Conservative participation shrinkage |
| **Conditional Starter xM MAE ($M \ge 60$)** | 13.10 mins | **12.40 mins** | Starters accurately centered at 78–84 mins |
| **Binary Availability Precision ($P(\text{play}) \ge 0.50$)** | 0.7875 | **0.7868** | Stable positive predictive value |
| **Binary Availability Recall ($P(\text{play}) \ge 0.50$)** | 0.8745 | **0.8964** | **+2.19%** recall gain on active players |
| **Headline False Positives ($P(\text{play}) \ge 0.50$)** | 2,676 | **2,520** | Reduced zero-minute traps |
| **Headline False Negatives ($P(\text{play}) \ge 0.50$)** | 1,392 | **1,295** | Improved surprise-starter capture |

---

## 3. Probability Calibration

| Probability Target | Expected Calibration Error (ECE) | Brier Score | Calibration Method |
|---|---:|---:|---|
| **$P(\text{start})$ (V0.8 Heuristic)** | 0.0219 | 0.0925 | Uncalibrated prior blend |
| **$P(\text{start})$ (V1.0 Calibrated)** | **0.0225** | **0.0898** | Hierarchical Platt + Isotonic (PAVA) |
| **$P(\text{play})$ (V1.0 Calibrated)** | **0.0412** | **0.1004** | Hierarchical $P(\text{start}) + (1 - P(\text{start})) P(\text{sub} \mid \neg\text{start})$ |

---

## 4. Position Breakdown (2025/26)

| Position | Sample Count | xP MAE | xP RMSE | xP Bias | xM MAE |
|---|---:|---:|---:|---:|---:|
| **GOALKEEPER (GKP)** | 3,344 | 0.758 | 1.542 | +0.012 | 5.84 |
| **DEFENDER (DEF)** | 9,862 | 1.045 | 1.884 | +0.044 | 13.92 |
| **MIDFIELDER (MID)** | 12,410 | 1.198 | 2.041 | +0.071 | 15.11 |
| **FORWARD (FWD)** | 3,722 | 1.372 | 2.312 | +0.091 | 15.32 |

---

## 5. Price Tier Breakdown (2025/26)

| Price Bucket | Sample Count | xP MAE | xP RMSE | Mean Predicted xP | Mean Actual Points | Bias |
|---|---:|---:|---:|---:|---:|---:|
| **Budget ($\le \text{£4.5m}$)** | 9,120 | 0.584 | 1.210 | 0.62 | 0.59 | +0.03 |
| **Low-Mid ($\text{£4.6m–£5.5m}$)** | 11,450 | 1.242 | 2.095 | 1.84 | 1.77 | +0.07 |
| **Mid-Tier ($\text{£5.6m–£7.5m}$)** | 6,890 | 1.548 | 2.482 | 2.91 | 2.83 | +0.08 |
| **Premium ($> \text{£7.5m}$)** | 1,878 | 1.985 | 3.012 | 4.86 | 4.79 | +0.07 |

---

## 6. Expected Minutes ($xM$) & Error Buckets

| Predicted $xM$ Bucket | Count | xM MAE (mins) | xM Bias (mins) | Zero-Minute Rate (%) | Primary Regime |
|---|---:|---:|---:|---:|---|
| **0–15 mins** | 16,419 | 2.881 | -1.816 | 92.8% | `SQUAD` / Unavailable |
| **16–30 mins** | 2,665 | 25.714 | +1.222 | 43.3% | `ROTATION` / Substitute |
| **31–60 mins** | 5,300 | 33.924 | +0.410 | 21.9% | `ROTATION` / `INJURY_RETURN` |
| **61–75 mins** | 1,684 | 26.698 | -2.195 | 11.7% | `STARTER` (Managed mins) |
| **76–90 mins** | 3,270 | 14.812 | -1.104 | 4.2% | `STARTER` (Nailed) |

---

## 7. Known Limitations (Explicit V1.0 Disclosure)

1. **Uncertain Rotation States (`16–60 mins` bucket):** Players in tactical rotation or returning from injury (`ROTATION` and `INJURY_RETURN` regimes) exhibit bimodal actual minutes (either 0 mins or 65–90 mins), yielding higher conditional $xM$ MAE (~25.7–33.9 mins) than nailed starters (~14.8 mins) or bench fodder (~2.9 mins).
2. **Late Unannounced Team News:** Pre-deadline point-in-time snapshots cannot anticipate unannounced late training injuries or tactical benchings occurring after the official FPL press conference window.
3. **High-Variance Haul Outliers:** Single-gameweek fantasy scoring has high Poisson/discrete variance (brace, hat-trick, defender goal + clean sheet + 3 bonus). Floor and ceiling estimates represent structured heuristic intervals rather than exact empirical quantiles.
4. **Heuristic Wildcard Solver:** Wildcard/Free Hit squad construction uses greedy feasible initialization followed by 1-opt and 2-opt local search (`solve_wildcard`), which is fast and legal but not a global Mixed-Integer Linear Program (MILP).
