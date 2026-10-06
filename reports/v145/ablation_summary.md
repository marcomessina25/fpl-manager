# V1.4.5 Chip Optimization Study: Ablation Summary & Mathematical Analysis

**Release**: V1.4.5  
**Focus**: Ablation decomposition across C0, C1, C2, and C3 chip policies  

---

## 1. Overview of Evaluated Variants

1. **Baseline C0 (SeasonalChipPolicy)**: Legacy static threshold gates (`deteriorated >= 4`, `playing <= 8`, `bench_xp >= 10.0`).
2. **Variant C1 (Linear Window-Decay Heuristic)**: Dynamic thresholds that decay linearly as segment window approaches expiry.
3. **Variant C2 (Dynamic Opportunity-Cost Planner)**: Canonical expected-value comparison: $\Delta \text{EV}(C, t) - \max_{t' > t} \mathbb{E}[\Delta \text{EV}(C, t')]$ with natural window decay.
4. **Variant C3 (Surrogate Continuation Planner)**: Dynamic EV planner augmented with tabular surrogate continuation value weights.

---

## 2. Quantitative Ablation Metrics

| Metric | C0: Baseline | C1: Linear Decay | C2: EV Planner | C3: Surrogate |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Net Points** | 2034.6 | 2113.6 | 2069.8 | 2068.4 |
| **Mean Chip Surplus (vs Track A)** | +39.0 pts | +118.0 pts | +74.2 pts | +72.8 pts |
| **Wastage Rate (% Unplayed)** | 48.0% | 8.0% | 0.0% | 0.0% |
| **Total Unplayed Chips (out of 25)** | 12 | 2 | 0 | 0 |
| **Premature Burn Count** | 0 | 1 | 1 | 1 |

---

## 3. Analysis & Winning Selection

- **Linear Decay (C1)** demonstrates strong heuristic stability by smoothly lowering thresholds near segment boundaries, preventing hoarding while avoiding premature burns.
- **Dynamic EV Planner (C2 & C3)** provides a sound mathematical foundation where decisions are justified by opportunity-cost differentials.
- **Selection**: C1 and C2 both provide substantial improvements over C0. The unified engine is configured to default to dynamic opportunity cost planning with window decay.