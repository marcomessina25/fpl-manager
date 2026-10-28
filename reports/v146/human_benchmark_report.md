# V1.4.6 Human-in-the-Loop Replay Benchmark Synthesis Report

**Version**: V1.4.6
**Study ID**: `V146-HITL-BENCHMARK-5S`
**Status**: Completed (5-Season Paired Two-Track Study; Track C Blind Control Deferred)
**Scope**: 5 Historical Seasons (`2021-22` through `2025-26`, 190 Matched Gameweeks)
**Participant Identifier**: `EXP-HM-01` (Single-Operator Paired Replay)
**Provenance Artifact**: [`reports/v146/human_benchmark_provenance.json`](human_benchmark_provenance.json)
**Verification Script**: [`scripts/verify_v146_human_benchmark.py`](../../scripts/verify_v146_human_benchmark.py)

---

## 1. Executive Performance Leaderboard & Full Accounting Reconciliation

All totals below are computed directly from the 190 gameweek decision and outcome traces in [`reports/v146/human_benchmark_provenance.json`](human_benchmark_provenance.json) (verifiable via `python scripts/verify_v146_human_benchmark.py`). In every gameweek $t \in [1, 38]$, $\text{Net Points} = \text{Gross Points} - 4 \times \text{Transfer Hits}$.

| Season | Session ID | Track B Gross | Track B Hits (Pts) | Track B Net | Track A Gross | Track A Hits (Pts) | Track A Net | Decision Alpha (B − A) | Outcome |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | `exp_hm_01_2021_22` | 1,988 | 3 (-12) | **1,976 pts** | 1,889 | 0 (-0) | 1,889 pts | **+87 pts** | Human-Assisted WIN |
| **2022-23** | `exp_hm_01_2022_23` | 2,085 | 3 (-12) | **2,073 pts** | 1,951 | 0 (-0) | 1,951 pts | **+122 pts** | Human-Assisted WIN |
| **2023-24** | `exp_hm_01_2023_24` | 2,170 | 11 (-44) | **2,126 pts** | 2,214 | 0 (-0) | 2,214 pts | **-88 pts** | Engine Baseline WIN |
| **2024-25** | `exp_hm_01_2024_25` | 2,234 | 4 (-16) | **2,218 pts** | 2,098 | 0 (-0) | 2,098 pts | **+120 pts** | Human-Assisted WIN |
| **2025-26** | `exp_hm_01_2025_26` | 2,137 | 5 (-20) | **2,117 pts** | 2,040 | 0 (-0) | 2,040 pts | **+77 pts** | Human-Assisted WIN |
| **5-Season Mean** | — | **2,122.8** | **5.2 (-20.8)** | **2,102.0 pts** | **2,038.4** | **0.0 (-0.0)** | **2,038.4 pts** | **+63.6 pts** | **4 / 5 Seasons (80.0%)** |

---

## 2. Human Override Decomposition & Chip Timing Comparison

Across the 190 simulated matchdays, operator `EXP-HM-01` modified at least one component of the engine's point-in-time recommendation (transfer pair, captaincy, or chip activation) in **182 of 190 gameweeks**:

| Season | Total Override GWs | Positive Alpha GWs ($\Delta > 0$) | Negative Alpha GWs ($\Delta < 0$) | Neutral GWs ($\Delta = 0$) | Transfer Overrides | Captain Overrides | Chip Overrides |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | 36 / 38 | 20 | 15 | 1 | 32 | 19 | 12 |
| **2022-23** | 35 / 38 | 19 | 14 | 2 | 31 | 18 | 13 |
| **2023-24** | 36 / 38 | 16 | 19 | 1 | 32 | 21 | 12 |
| **2024-25** | 37 / 38 | 20 | 16 | 1 | 31 | 21 | 10 |
| **2025-26** | 38 / 38 | 21 | 15 | 2 | 35 | 23 | 12 |
| **Total (190 GWs)** | **182 / 190** | **96 (52.7%)** | **79 (43.4%)** | **7 (3.8%)** | **161** | **102** | **59** |

### Chip Deployment Schedule (Track B vs. Track A)

| Season | Track | Segment 1 (`GW1–19`) Chips (`WC1`, `FH1`, `BB1`, `TC1`) | Segment 2 (`GW20–38`) Chips (`WC2`, `FH2`, `BB2`, `TC2`) |
| :--- | :--- | :--- | :--- |
| **2021-22** | Track B (Human) | `WC1`: GW8, `FH1`: GW18, `BB1`: GW3, `TC1`: GW19 | `WC2`: GW32, `FH2`: GW30, `BB2`: GW36, `TC2`: GW26 |
| **2021-22** | Track A (Engine) | `WC1`: GW17, `FH1`: GW18, `BB1`: GW19, `TC1`: GW7 | `WC2`: GW28, `FH2`: GW30, `BB2`: GW36, `TC2`: GW26 |
| **2022-23** | Track B (Human) | `WC1`: GW10, `FH1`: GW8, `BB1`: GW11, `TC1`: GW19 | `WC2`: GW30, `FH2`: GW28, `BB2`: GW22, `TC2`: GW29 |
| **2022-23** | Track A (Engine) | `WC1`: GW17, `FH1`: GW12, `BB1`: GW19, `TC1`: GW9 | `WC2`: GW33, `FH2`: GW28, `BB2`: GW29, `TC2`: GW25 |
| **2023-24** | Track B (Human) | `WC1`: GW9, `FH1`: GW18, `BB1`: GW8, `TC1`: GW7 | `WC2`: GW27, `FH2`: GW26, `BB2`: GW31, `TC2`: GW25 |
| **2023-24** | Track A (Engine) | `WC1`: GW19, `FH1`: GW18, `BB1`: GW8, `TC1`: GW7 | `WC2`: GW31, `FH2`: GW29, `BB2`: GW37, `TC2`: GW25 |
| **2024-25** | Track B (Human) | `WC1`: GW10, `FH1`: GW15, `BB1`: GW11, `TC1`: GW12 | `WC2`: GW32, `FH2`: GW29, `BB2`: GW33, `TC2`: GW25 |
| **2024-25** | Track A (Engine) | `WC1`: GW19, `FH1`: GW18, `BB1`: GW3, `TC1`: GW2 | `WC2`: GW30, `FH2`: GW29, `BB2`: GW36, `TC2`: GW25 |
| **2025-26** | Track B (Human) | `WC1`: GW10, `FH1`: GW18, `BB1`: GW7, `TC1`: GW13 | `WC2`: GW32, `FH2`: GW34, `BB2`: GW33, `TC2`: GW25 |
| **2025-26** | Track A (Engine) | `WC1`: GW19, `FH1`: GW18, `BB1`: GW2, `TC1`: GW6 | `WC2`: GW31, `FH2`: GW29, `BB2`: GW36, `TC2`: GW32 |

---

## 3. Empirical Findings & Behavioral Analysis

1. **Observed Paired Surplus (+63.6 pts/season for Operator `EXP-HM-01`)**: Across the 5 audited seasons (190 gameweeks), the human-assisted track averaged **2,102.0 net points** vs. **2,038.4 net points** for the autonomous baseline (+63.6 pts/season mean delta), outperforming the autonomous engine in 4 of 5 seasons (`2021-22`, `2022-23`, `2024-25`, `2025-26`).
2. **Proactive Structural Wildcarding & Selective Hit Taking**: Notice that Track A (`DecisionEngineV135` with `hit_cost = 4.0` and `gk_transfer_hurdle = 3.0`) took **0 transfer hits** across all 5 seasons and frequently held `WC1` until the Segment 1 terminal decay window (`GW17–19`). By contrast, operator `EXP-HM-01` deployed `WC1` earlier (`GW8–10`) to catch fixture-swing inflection points and took selective transfer hits (`3 to 5 hits/season` in winning seasons, `-12 to -20 pts`) to restructure around blank/double gameweeks.
3. **Over-Trading Penalty in Template Seasons (`2023-24`)**: In `2023-24`, operator `EXP-HM-01` took **11 transfer hits (`-44 pts`)** and posted a negative override balance (`16+ / 19-`), trailing the zero-hit autonomous baseline by **-88 net points** (`2,126` vs. `2,214`). Even on gross points (`2,170` vs. `2,214`), aggressive human rotation chasing underperformed the engine's patient holding of high-ownership template assets (`B3/B4` horizon damping).

---

## 4. Provenance, Ruleset & Methodological Limitations

### 4.1 Reproducibility & Source Checksums
Every number in this report is deterministically verified by [`scripts/verify_v146_human_benchmark.py`](../../scripts/verify_v146_human_benchmark.py) against [`reports/v146/human_benchmark_provenance.json`](human_benchmark_provenance.json):

| Season | Anonymized Session ID | Raw Session Trace SHA-256 Digest | Initial Squad Parity (`15 IDs`, Bank, FT) |
| :--- | :--- | :--- | :---: |
| **2021-22** | `exp_hm_01_2021_22` | `ef76ce422894db7fd220780747597bb8eb07c8653839ba399f756a813d8f0ab3` | Verified (`bank=10`, `FT=1`) |
| **2022-23** | `exp_hm_01_2022_23` | `df2699c62fb8fcdf2199b4f1584f96a4a33dc39142c574fd198a4a6a06678915` | Verified (`bank=5`, `FT=1`) |
| **2023-24** | `exp_hm_01_2023_24` | `3da0fc9c6cc24212a3b08e8170dfea9e2c15d827ab5be21df4120c7f57f1f895` | Verified (`bank=0`, `FT=1`) |
| **2024-25** | `exp_hm_01_2024_25` | `c85258bb9d03d85bf03460498df20c3b648f2ef3065aa7e34a627786716a6462` | Verified (`bank=5`, `FT=1`) |
| **2025-26** | `exp_hm_01_2025_26` | `c44890505b4621094c79ec6ec8fa3ca793efbc7b08e079d669963653226c0c79` | Verified (`bank=5`, `FT=1`) |

### 4.2 Scope & Statistical Limitations
1. **Sample Size (`N = 5` Seasons, Single Operator `EXP-HM-01`)**: While the 190-gameweek paired trace provides an exact, auditable record of human-assisted vs. autonomous play across five complete historical seasons, a sample of $N = 5$ seasons with a single human operator is descriptive case-study evidence and does not constitute proof of general population-level statistical significance.
2. **Prior Domain Familiarity**: Operator `EXP-HM-01` conducted the replays under strict point-in-time UI masking (zero future scores or price spoilers shown in the Time Machine), but as an experienced follower of Premier League football, macro-level recollection of historical seasons cannot be fully eliminated in retrospective human trials.
3. **Standardized Two-Segment Chip Ruleset (`V146-24`)**: As documented in [`docs/v1.4.6/v146_human_benchmark.md`](../../docs/v1.4.6/v146_human_benchmark.md), both Track A and Track B were evaluated under era-authentic free-transfer caps (`2` in `2021-22`..`2023-24`, `5` in `2024-25`..`2025-26`) and the standardized two-segment chip inventory (`GW1–19` and `GW20–38`) for cross-season comparability with V1.4.5.
4. **Deferred Deliverables**: Track C (unassisted human blind control) and multi-participant distribution charts remain future work outside the V1.4.6 single-operator study.
