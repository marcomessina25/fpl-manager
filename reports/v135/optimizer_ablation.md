# V1.3.5 Optimizer Ablation Study Results

**Evaluated Seasons:** 2024-25  
**Total Execution Time:** 163.7s

## 1. Core Incremental Ablation Matrix

| Variant | Architectural Factor Isolated | Track A Mean | Track A Std | Delta vs B0 | Track B Mean | Chip Gain | Mean Hits | Mean 0-Min |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **B0** | Control: Single-GW horizon (H=1), XI-only (bench=0.0), baseline pool (5), no hurdles, no flexibility | **2152.0** | ±0.0 | +0.0 pts | **2177.0** | +25.0 pts | 0.0 | 32.0 |
| **B1** | Multi-GW Horizon: H=3 discounted (gamma=0.75), XI-only (bench=0.0), baseline pool (5), no hurdles | **2096.0** | ±0.0 | -56.0 pts | **2120.0** | +24.0 pts | 0.0 | 42.0 |
| **B2** | Extended Horizon: H=5 discounted (gamma=0.75), XI-only (bench=0.0), baseline pool (5), no hurdles | **2218.0** | ±0.0 | +66.0 pts | **2241.0** | +23.0 pts | 0.0 | 27.0 |
| **B3** | Bench-Aware: H=3, bench weight 0.15, baseline pool (5), no GK hurdle, no flexibility | **2289.0** | ±0.0 | +137.0 pts | **2318.0** | +29.0 pts | 0.0 | 36.0 |
| **B4** | GK Hurdle: H=3, bench weight 0.15, GK hurdle 3.0, baseline pool (5), no flexibility | **2289.0** | ±0.0 | +137.0 pts | **2318.0** | +29.0 pts | 0.0 | 36.0 |
| **B5** | Candidate Pool Expansion: H=3, bench weight 0.15, GK hurdle 3.0, expanded pool (25), no flexibility | **2142.0** | ±0.0 | -10.0 pts | **2176.0** | +34.0 pts | 0.0 | 24.0 |
| **B6** | Flexibility & Strategic Init: H=3, pool 25, dead capital 3.0, static chips, strategic balanced init | **2142.0** | ±0.0 | -10.0 pts | **2176.0** | +34.0 pts | 0.0 | 24.0 |
| **B7** | Full Integrated Policy: H=3, pool 25, dead capital 3.0, dynamic chip-aware weights, strategic balanced init | **2142.0** | ±0.0 | -10.0 pts | **2176.0** | +34.0 pts | 0.0 | 24.0 |

---

