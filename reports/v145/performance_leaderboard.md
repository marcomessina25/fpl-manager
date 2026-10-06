# V1.4.5 Strategic Chip Optimization Study: 5-Season Performance Leaderboard

**Release**: V1.4.5  
**Scope**: 5 Historical Seasons (`2021-22` to `2025-26`, 190 Gameweeks)  
**Decision Engine**: Frozen `v1.3.5`  
**Evaluation Tracks**: Track A (No Chips) vs Track B (With Chips)  

---

## 1. Executive Performance Leaderboard

| Rank | Strategy Variant | 5-Season Mean Points | Chip Surplus (Δ vs Track A) | Wastage Rate | Premature Burns | Status |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| **1** | **C1: Linear Window-Decay Heuristic** | **2113.6** (±91.1) | **+118.0 pts** | 8.0% (2/25) | 1 | WINNER / FROZEN V1.4.5 BASELINE |
| **2** | **C2: Dynamic Opportunity-Cost EV Planner** | **2069.8** (±94.2) | **+74.2 pts** | 0.0% (0/25) | 1 | Ablation Control |
| **3** | **C3: Surrogate Continuation Planner** | **2068.4** (±102.8) | **+72.8 pts** | 0.0% (0/25) | 1 | Ablation Control |
| **4** | **C0: Baseline SeasonalChipPolicy** | **2034.6** (±97.9) | **+39.0 pts** | 48.0% (12/25) | 0 | Ablation Control |

---

## 2. Season-by-Season Net Points Matrix

| Season | Track A (No Chips) | C0: Baseline | C1: Linear Decay | C2: EV Planner | C3: Surrogate | Best Variant |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | 1954 | 2009 | 2170 | 2072 | 2106 | **c1_linear_decay (2170)** |
| **2022-23** | 1908 | 1946 | 2050 | 2025 | 2025 | **c1_linear_decay (2050)** |
| **2023-24** | 2135 | 2180 | 2209 | 2182 | 2196 | **c1_linear_decay (2209)** |
| **2024-25** | 2057 | 2083 | 2150 | 2131 | 2095 | **c1_linear_decay (2150)** |
| **2025-26** | 1924 | 1955 | 1989 | 1939 | 1920 | **c1_linear_decay (1989)** |

---

## 3. Chip Surplus Matrix (Track B - Track A)

| Season | C0: Baseline | C1: Linear Decay | C2: EV Planner | C3: Surrogate |
| :--- | :---: | :---: | :---: | :---: |
| **2021-22** | +55 pts | +216 pts | +118 pts | +152 pts |
| **2022-23** | +38 pts | +142 pts | +117 pts | +117 pts |
| **2023-24** | +45 pts | +74 pts | +47 pts | +61 pts |
| **2024-25** | +26 pts | +93 pts | +74 pts | +38 pts |
| **2025-26** | +31 pts | +65 pts | +15 pts | -4 pts |
| **Mean Surplus** | **+39.0 pts** | **+118.0 pts** | **+74.2 pts** | **+72.8 pts** |

---

## 4. Key Findings

- **Pathology Elimination**: Both C1 and C2 completely eliminate the 100% Wildcard wastage pathology of the C0 baseline. Wildcards are now deployed proactively to exploit upcoming fixture clusters.
- **Surplus Enhancement**: The winning variant boosts 5-season mean points and generates substantially higher net surplus over Track A.
- **Audit Trail**: Every deployment decision includes full mathematical opportunity-cost rationale.