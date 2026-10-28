# V1.4.6 Human-in-the-Loop Replay Benchmark Synthesis Report

**Version**: V1.4.6  
**Scope**: 5 Historical Seasons (`2021-22` through `2025-26`, 190 Gameweeks)  
**Evaluation Tracks**:
- **Track A**: Autonomous Frozen Reference Baseline (`DecisionEngineV135` + `ChipOpportunityOptimizer`)
- **Track B**: Human-Assisted (Human Manager + Point-in-Time Engine Advisory)

---

## 1. Executive Performance Leaderboard

| Season | Track B (Human + Engine) | Track A (Frozen Engine Baseline) | Decision Alpha (H − E) | Outperformed? |
| :--- | :---: | :---: | :---: | :---: |
| **2021-22** | **1,976 pts** | 1,889 pts | **+87 pts** | Human WIN |
| **2022-23** | **2,073 pts** | 1,951 pts | **+122 pts** | Human WIN |
| **2023-24** | **2,126 pts** | 2,214 pts | **-88 pts** | Engine WIN |
| **2024-25** | **2,218 pts** | 2,098 pts | **+120 pts** | Human WIN |
| **2025-26** | **2,117 pts** | 2,040 pts | **+77 pts** | Human WIN |
| **5-Season Mean** | **2,102.0 pts** | 2,038.4 pts | **+63.6 pts** | **4 / 5 Seasons (80.0%)** |

---

## 2. Decision Alpha Analysis

1. **Overall Synergy**: Across 190 simulated matchdays, the human-in-the-loop strategy delivered a **+63.6 points per season mean surplus** over the autonomous engine baseline.
2. **Win Rate**: Human managers beat the algorithm in **4 out of 5 seasons (80.0%)**.
3. **Turbulence Resilience**: The largest human gains were recorded during seasons characterized by postponement clusters, fixture rescheduling, and player rotation (2022-23: +122 pts; 2024-25: +120 pts; 2021-22: +87 pts), where human managers effectively identified qualitative rotation traps that quantitative models under-discounted.
4. **Algorithmic Dominance in Template Streaks**: In 2023-24, the engine baseline prevailed (+88 pts) due to strict algorithmic holding of high-performing template players through variance swings.
