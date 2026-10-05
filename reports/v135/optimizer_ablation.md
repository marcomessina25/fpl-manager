# V1.3.5 Optimizer Ablation Study Results

**Evaluated Seasons:** 2024-25  
**Total Execution Time:** 481.0s

## 1. Core Incremental Ablation Matrix

| Variant | Architectural Factor Isolated | Track A Mean | Track A Std | Delta vs B0 | Track B Mean | Chip Gain | Mean Hits | Mean 0-Min |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **B0** | Control: Single-GW horizon (H=1), XI-only (bench=0.0), baseline pool (5), no hurdles, no flexibility | **2324.0** | ±0.0 | +0.0 pts | **2366.0** | +42.0 pts | 0.0 | 37.0 |
| **B1** | Multi-GW Horizon: H=3 discounted (gamma=0.75), XI-only (bench=0.0), baseline pool (5), no hurdles | **2242.0** | ±0.0 | -82.0 pts | **2272.0** | +30.0 pts | 0.0 | 28.0 |
| **B2** | Extended Horizon: H=5 discounted (gamma=0.75), XI-only (bench=0.0), baseline pool (5), no hurdles | **2233.0** | ±0.0 | -91.0 pts | **2272.0** | +39.0 pts | 0.0 | 33.0 |
| **B3** | Bench-Aware: H=3, bench weight 0.15, baseline pool (5), no GK hurdle, no flexibility | **2252.0** | ±0.0 | -72.0 pts | **2294.0** | +42.0 pts | 0.0 | 26.0 |
| **B4** | GK Hurdle: H=3, bench weight 0.15, GK hurdle 3.0, baseline pool (5), no flexibility | **2208.0** | ±0.0 | -116.0 pts | **2254.0** | +46.0 pts | 0.0 | 31.0 |
| **B5** | Candidate Pool Expansion: H=3, bench weight 0.15, GK hurdle 3.0, expanded pool (25), no flexibility | **2224.0** | ±0.0 | -100.0 pts | **2266.0** | +42.0 pts | 0.0 | 29.0 |
| **B6** | Flexibility & Strategic Init: H=3, pool 25, dead capital 3.0, static chips, strategic balanced init | **2148.0** | ±0.0 | -176.0 pts | **2182.0** | +34.0 pts | 0.0 | 35.0 |
| **B7** | Full Integrated Policy: H=3, pool 25, dead capital 3.0, dynamic chip-aware weights, strategic balanced init | **2148.0** | ±0.0 | -176.0 pts | **2182.0** | +34.0 pts | 0.0 | 35.0 |

---

