# V1.4.5 Baseline Pathology Report: Legacy `SeasonalChipPolicy` (C0)

**Scope**: 5 historical seasons (`2021-22` to `2025-26`), frozen `v1.3.5` decision engine.
**Source**: `scripts/run_v145_ablation.py` (C0 rows) and `reports/v145/seasonal_results/*.json`. All figures below are taken from that output.

## 1. Per-season results (C0 baseline)

| Season | Track A (no chips) | Track B (C0 chips) | Surplus | Chips played | Unplayed chip slots |
| :--- | :---: | :---: | :---: | :--- | :--- |
| 2021-22 | 1954 | 2009 | +55 | BB x2, FH, TC | WC1, WC2 |
| 2022-23 | 1908 | 1946 | +38 | BB, FH, TC | WC1, WC2 |
| 2023-24 | 2135 | 2180 | +45 | TC x2, BB, FH | WC1, WC2 |
| 2024-25 | 2057 | 2083 | +26 | BB x2, TC x2 | WC1, WC2, FH |
| 2025-26 | 1924 | 1955 | +31 | BB x2, TC | WC1, WC2, FH |
| **Mean** | **1995.6** | **2034.6** | **+39.0** | | **12 / 25 slots (48%)** |

## 2. Observed pathologies

1. **Wildcard never deployed**: 0 of 10 Wildcard slots used across 5 seasons. The gate (`>= 4` deteriorated squad players) is never reached when the engine manages the squad with weekly transfers.
2. **Free Hit under-used**: unplayed in 2 of 5 seasons (gate requires `<= 8` active players).
3. **Overall wastage**: 12 of 25 chip slots (48%) expired unused.

## 3. Not measured here

Premature-burn counts, near-expiry "panic" share and live-vs-simulation divergence were **not** quantified by the baseline run. See `v145_pipeline_divergence_audit.md` for the (qualitative) code-level divergence analysis.
