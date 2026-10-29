# V1.4.6 Human-in-the-Loop Replay Benchmark Synthesis Report

**Version**: V1.4.6
**Study ID**: `V146-HITL-BENCHMARK-5S`
**Status**: Recorded five-season end-to-end strategy comparison; Track C deferred
**Scope**: 5 Historical Seasons (`2021-22` through `2025-26`, 190 Matched Gameweeks)
**Participant Identifier**: `EXP-HM-01` (Single-Operator Paired Replay)
**Provenance Artifact**: [`reports/v146/human_benchmark_provenance.json`](human_benchmark_provenance.json)
**Verification Script**: [`scripts/verify_v146_human_benchmark.py`](../../scripts/verify_v146_human_benchmark.py)

---

## 1. Executive Performance Leaderboard & Full Accounting Reconciliation

All totals below are computed directly from the 190 gameweek decision and outcome traces in [`reports/v146/human_benchmark_provenance.json`](human_benchmark_provenance.json) (verifiable via `python scripts/verify_v146_human_benchmark.py`). In every gameweek $t \in [1, 38]$, $\text{Net Points} = \text{Gross Points} - 4 \times \text{Transfer Hits}$.

| Season | Session ID | Track B Gross | Track B Hits (Pts) | Track B Net | Track A Gross | Track A Hits (Pts) | Track A Net | Observed Net Surplus (B - A) | Outcome |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | `exp_hm_01_2021_22` | 1,988 | 3 (-12) | **1,976 pts** | 1,889 | 0 (-0) | 1,889 pts | **+87 pts** | Human-Assisted WIN |
| **2022-23** | `exp_hm_01_2022_23` | 2,085 | 3 (-12) | **2,073 pts** | 1,951 | 0 (-0) | 1,951 pts | **+122 pts** | Human-Assisted WIN |
| **2023-24** | `exp_hm_01_2023_24` | 2,170 | 11 (-44) | **2,126 pts** | 2,214 | 0 (-0) | 2,214 pts | **-88 pts** | Engine Baseline WIN |
| **2024-25** | `exp_hm_01_2024_25` | 2,234 | 4 (-16) | **2,218 pts** | 2,098 | 0 (-0) | 2,098 pts | **+120 pts** | Human-Assisted WIN |
| **2025-26** | `exp_hm_01_2025_26` | 2,137 | 5 (-20) | **2,117 pts** | 2,040 | 0 (-0) | 2,040 pts | **+77 pts** | Human-Assisted WIN |
| **5-Season Mean** | — | **2,122.8** | **5.2 (-20.8)** | **2,102.0 pts** | **2,038.4** | **0.0 (-0.0)** | **2,038.4 pts** | **+63.6 pts** | **4 / 5 Seasons (80.0%)** |

---

## 2. Human Override Decomposition & Chip Timing Comparison

The recorded override classifications mark **184 of 190 gameweeks**. The distributions below describe those flags and observed track differences; they do not isolate the causal value of an override because both trajectories and initial squads differ.

| Season | Total Override GWs | Positive Delta GWs ($\Delta > 0$) | Negative Delta GWs ($\Delta < 0$) | Neutral GWs ($\Delta = 0$) | Transfer Overrides | Captain Overrides | Chip Overrides |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | 37 / 38 | 21 | 15 | 1 | 32 | 19 | 17 |
| **2022-23** | 36 / 38 | 19 | 14 | 3 | 31 | 18 | 14 |
| **2023-24** | 36 / 38 | 16 | 19 | 1 | 32 | 21 | 12 |
| **2024-25** | 37 / 38 | 20 | 16 | 1 | 31 | 21 | 10 |
| **2025-26** | 38 / 38 | 21 | 15 | 2 | 35 | 23 | 12 |
| **Total (190 GWs)** | **184 / 190** | **97 (52.7%)** | **79 (42.9%)** | **8 (4.3%)** | **161** | **102** | **65** |

### Chip Deployment Schedule (Track B vs. Track A)

All chip deployments below are derived directly from matchday event records in `gw_traces`:

| Season | Track | Segment 1 (`GW1–19`) Chips (`WC1`, `FH1`, `BB1`, `TC1`) | Segment 2 (`GW20–38`) Chips (`WC2`, `FH2`, `BB2`, `TC2`) |
| :--- | :--- | :--- | :--- |
| **2021-22** | Track B (Human) | `BB1`: GW3, `WC1`: GW8, `FH1`: GW18, `TC1`: GW19 | `TC2`: GW26, `FH2`: GW30, `WC2`: GW32, `BB2`: GW36 |
| **2021-22** | Track A (Engine) | `BB1`: GW11, `FH1`: GW18 | `BB2`: GW23, `TC2`: GW26, `FH2`: GW27 |
| **2022-23** | Track B (Human) | `FH1`: GW8, `WC1`: GW10, `BB1`: GW11, `TC1`: GW19 | `BB2`: GW22, `FH2`: GW28, `TC2`: GW29, `WC2`: GW30 |
| **2022-23** | Track A (Engine) | `FH1`: GW7, `WC1`: GW11, `BB1`: GW13 | `BB2`: GW20, `TC2`: GW29 |
| **2023-24** | Track B (Human) | `TC1`: GW7, `BB1`: GW8, `WC1`: GW9, `FH1`: GW18 | `TC2`: GW25, `FH2`: GW26, `WC2`: GW27, `BB2`: GW31 |
| **2023-24** | Track A (Engine) | `TC1`: GW6, `BB1`: GW8, `WC1`: GW18 | `BB2`: GW20, `TC2`: GW25, `FH2`: GW29 |
| **2024-25** | Track B (Human) | `WC1`: GW10, `BB1`: GW11, `TC1`: GW12, `FH1`: GW15 | `TC2`: GW25, `FH2`: GW29, `WC2`: GW32, `BB2`: GW33 |
| **2024-25** | Track A (Engine) | `WC1`: GW8, `TC1`: GW9, `BB1`: GW10 | `BB2`: GW23, `TC2`: GW24, `FH2`: GW29 |
| **2025-26** | Track B (Human) | `BB1`: GW7, `WC1`: GW10, `TC1`: GW13, `FH1`: GW18 | `TC2`: GW25, `WC2`: GW32, `BB2`: GW33, `FH2`: GW34 |
| **2025-26** | Track A (Engine) | `TC1`: GW6, `BB1`: GW10 | `TC2`: GW26, `FH2`: GW31 |

*(Note: Chips not listed in Track A schedules were evaluated by `ChipOpportunityOptimizer` but were either unspent before the segment deadline or held due to lack of a qualifying opportunity meeting threshold hurdles).*

---

## 3. Empirical Findings & Behavioral Analysis

1. **Observed End-to-End Surplus**: Track B averaged **2,102.0 net points** versus **2,038.4** for Track A: **+63.6 per season**, with four season wins. Initial squads overlap by only 2-4 players, so this margin includes initial selection as well as later decisions. It is not an identical-start treatment effect.
2. **Recorded Chip and Transfer Behavior**: Track A recorded zero transfer hits. Its first-window Wildcards were GW11 in 2022-23, GW18 in 2023-24, and GW8 in 2024-25, with no first-window Wildcard recorded in the other two seasons. Track B used first-window Wildcards in GW8-10 and incurred the hit costs shown above. The traces establish these differences, not why a particular strategy won.
3. **2023-24 Accounting**: Track B's 2,170 gross points minus 44 hit points yields 2,126 net, versus Track A's 2,214. The 88-point difference is an observed outcome, not a causal decomposition into trading, initial squad, captaincy, or template exposure.

---

## 4. Provenance, Verification Levels & Methodological Boundaries

### 4.1 Multi-Level Verification Architecture
The benchmark verification suite ([`scripts/verify_v146_human_benchmark.py`](../../scripts/verify_v146_human_benchmark.py)) enforces three distinct layers of validation:
- **Level 1: Strict Per-Gameweek Arithmetic Reconciliation**: Validates that for every gameweek $t \in [1, 38]$ across both tracks, $\text{gross} - \text{hits} \times 4 == \text{net}$, cumulative sums agree, and season aggregates match trace totals exactly.
- **Level 2: Semantic Integrity Verification**: Validates that summary chip dictionaries (`track_a_chips_used`, `track_b_chips_used`) match actual per-gameweek event traces with zero missing or extra entries, and that override counts (`transfer_override`, `captain_override`, `chip_override`) match categorized divergence distributions.
- **Initial-State Consistency**: Reads the actual recorded bank/FT values, checks 15 distinct IDs per track, and recomputes comparison flags and overlap. This is metadata consistency, not proof of identical squads or an independent rescore.
- **Optional Raw-Source Digest Verification**: Checks a digest only when its raw session file is available. The CLI reports checked and unavailable seasons separately. Missing private files in a clean checkout do not constitute a passed source check.

The following are recorded source identifiers and internally consistent bank/FT values. Run the verifier with the raw sources to establish digest matches; this bundled table does not itself verify those files.

| Season | Anonymized Session ID | Recorded Raw Session SHA-256 Digest | Bank / FT Consistency | Squad Overlap |
| :--- | :--- | :--- | :--- | :---: |
| **2021-22** | `exp_hm_01_2021_22` | `ec9106b11159aa58ca5c3d5346d2393f04cfa4c8cfed3370f047eedeffb40732` | Verified (bank=0, FT=1) | 4/15 |
| **2022-23** | `exp_hm_01_2022_23` | `012f6af835ea9ed423ceef05e984c6fe766dc6f073c98f351e0d5755baaf8c72` | Verified (bank=0, FT=1) | 2/15 |
| **2023-24** | `exp_hm_01_2023_24` | `ecb2617b90a800c75ce0129e285353de81ea71c4528108b55d46f1affd191582` | Verified (bank=0, FT=1) | 3/15 |
| **2024-25** | `exp_hm_01_2024_25` | `040de60261c56eaaa1b9fc1369832ac297ddefb3c15d1027dda2689d105bf968` | Verified (bank=0, FT=1) | 2/15 |
| **2025-26** | `exp_hm_01_2025_26` | `e1aa82d0aec8cb8b913eceedd433cb6209b4c1785a9fdd2ebba22f7559ee42f1` | Verified (bank=0, FT=1) | 4/15 |

### 4.2 Initial Squad Selection Methodology
Both tracks record GW1 bank of 0 tenths and one free transfer, but their initial squads and stored chip-inventory lists are not identical. The metadata records those differences explicitly under a standardized replay ruleset:
- **Track B (Human-Assisted)**: Initial 15-player squad selected by operator `EXP-HM-01` using Strategic Studio candidates and manual refinements.
- **Track A (Engine Baseline)**: Initial 15-player squad selected autonomously by the baseline engine's EV lineup optimizer (`DecisionEngineV135` GW1 max-EV lineup solver).
- This results in a starting squad overlap between Track A and Track B of 2 to 4 players out of 15 across the five seasons. Both tracks subsequently operated under identical market rules, pricing mechanics, and scoring outcomes.

### 4.3 Scope & Statistical Limitations
1. **Sample Size (`N = 5` Seasons, Single Operator `EXP-HM-01`)**: While the 190-gameweek paired trace provides an exact, auditable record of human-assisted vs. autonomous play across five complete historical seasons, a sample of $N = 5$ seasons with a single human operator is descriptive case-study evidence and does not constitute proof of general population-level statistical significance.
2. **Prior Domain Familiarity**: Operator `EXP-HM-01` conducted the replays under strict point-in-time UI masking (zero future scores or price spoilers shown in the Time Machine), but as an experienced follower of Premier League football, macro-level recollection of historical seasons cannot be fully eliminated in retrospective human trials.
3. **Standardized Two-Segment Chip Ruleset (`V146-24`)**: As documented in [`docs/v1.4.6/v146_human_benchmark.md`](../../docs/v1.4.6/v146_human_benchmark.md), both Track A and Track B were evaluated under era-authentic free-transfer caps (`2` in `2021-22`..`2023-24`, `5` in `2024-25`..`2025-26`) and the standardized two-segment chip inventory (`GW1–19` and `GW20–38`) for cross-season comparability with V1.4.5.
4. **Deferred Deliverables**: Track C (unassisted human blind control) and multi-participant distribution charts remain future research deliverables outside the V1.4.6 single-operator study.
5. **No Retroactive Validation**: These 190-GW results were not rerun or rescored during remediation. Current regression tests do not establish which code produced every original advisory or retroactively prove the original information boundary. The retained results are descriptive records, not validation of the corrected engine.
6. **Legacy Field Names**: `decision_alpha_net_points` and `mean_decision_alpha_points` remain serialized for compatibility. In this comparison they mean observed net surplus, including initialization differences, not isolated causal decision alpha.
