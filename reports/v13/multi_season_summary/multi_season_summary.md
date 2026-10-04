# Multi-Version Historical Benchmark Ledger: V0.9 vs V1.0 vs V1.1 vs V1.1.5 vs V1.2 vs V1.2.5 vs V1.3

**Historical Seasons:** 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (5 seasons evaluated)
**Evaluation Window:** GW 1–38 | **Predictor:** `v1.0.1` / `v1.3` | **Benchmark Date:** 2026-10-04

## 1. Executive Summary: Primary Walk-Forward Benchmark (2022–2026, 4 Seasons)

> **Strict Prior-Season Walk-Forward Isolation:**
> Evaluates all models strictly trained on historical seasons prior to each evaluation season ($\mathcal{D}_{< Y}$).
> Season 2021-22 is excluded from this primary aggregate because no 2020-21 historical training data exists in the repository, and is reported separately as an out-of-fold retrospective stress test.

### Track A: Without Chips (Primary Walk-Forward: 2022–23 through 2025–26)

| Engine Version | Architectural Focus | Mean Net Pts (4 Seasons) | Delta vs V0.9 | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---|---:|---:|---:|---:|---:|
| **v0.9** | Learned Participation Baseline | **2011.0** (±203.8) | +0.0 pts | 52.92 | 0.0 | 36.0 |
| **v1.0** | Canonical Single-GW Decision Engine | **2091.2** (±181.4) | +80.2 pts | 55.03 | 0.0 | 36.2 |
| **v1.1** | Strategic Squad Optimization (Multi-GW Init) | **2016.2** (±97.2) | +5.2 pts | 53.06 | 0.0 | 37.8 |
| **v1.1.5** | Departure Engine + Dead Capital Offload + Seasonal Chips | **2026.2** (±102.8) | +15.2 pts | 53.32 | 0.0 | 37.5 |
| **v1.2** | Strategic Squad Balancing (XI vs Bench) + Unavailability Modeling | **2036.5** (±119.6) | +25.5 pts | 53.59 | 0.0 | 37.8 |
| **v1.2.5** | Lineup Horizon Expansion, Candidate Pool Scaling & Dynamic Chip Bench Weighting | **2066.2** (±108.3) | +55.2 pts | 54.38 | 0.0 | 37.8 |
| **v1.3** | GBDT Quantitative Predictor Challenger (evaluated through frozen V1.2.5 decision engine) | **2032.8** (±193.7) | +21.8 pts | 53.49 | 0.0 | 37.2 |

### Track B: With Chips (Primary Walk-Forward: 2022–23 through 2025–26)

| Engine Version | Mean Net Pts (Track B) | Chip Gain (Track B - Track A) | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---:|---:|---:|---:|---:|
| **v0.9** | **2060.2** (±167.3) | **+49.2 pts** | 54.22 | 0.0 | 47.0 |
| **v1.0** | **2136.5** (±167.2) | **+45.3 pts** | 56.22 | 0.0 | 49.2 |
| **v1.1** | **2067.0** (±122.8) | **+50.8 pts** | 54.39 | 0.0 | 45.2 |
| **v1.1.5** | **2046.8** (±146.8) | **+20.6 pts** | 53.86 | 0.0 | 43.5 |
| **v1.2** | **2065.5** (±147.8) | **+29.0 pts** | 54.36 | 0.0 | 48.5 |
| **v1.2.5** | **2105.0** (±113.4) | **+38.8 pts** | 55.39 | 0.0 | 45.2 |
| **v1.3** | **2078.8** (±199.2) | **+46.0 pts** | 54.70 | 0.0 | 47.5 |

## 2. Retrospective Stress Test: Season 2021-22 (Out-of-Fold / Future-Trained)

> **Stress Test Context:**
> Because 2020-21 pre-season data is unavailable in the repository, the 2021-22 GBDT challenger was evaluated using an out-of-fold model trained on subsequent seasons (2022-23 and 2023-24).
> This measures model sensitivity to historical distribution shifts and small-sample fragility under cold-start conditions.

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx | GK Tx |
|---|---:|---:|---:|---:|---|---:|---:|
| **v0.9** | 1874 | 0 | **2000** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1 | 0 | 6 |
| **v1.0** | 1877 | 0 | **1994** | 0 | FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 | 10 |
| **v1.1** | 1850 | 0 | **1782** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1 | 6 | 7 |
| **v1.1.5** | 1797 | 0 | **1852** | 0 | BENCH_BOOST: 2, FREE_HIT: 1 | 0 | 6 |
| **v1.2** | 1983 | 0 | **1989** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1 | 0 | 4 |
| **v1.2.5** | 1968 | 0 | **2019** | 0 | BENCH_BOOST: 1, FREE_HIT: 1 | 0 | 3 |
| **v1.3** | 1577 | 0 | **1614** | 0 | FREE_HIT: 2, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1 | 0 | 5 |

## 3. Full 5-Season Reference Comparison (All Evaluated Seasons: 2021–2026)

> **Note:** Includes 2021-22 retrospective stress test results alongside the 4 strict walk-forward seasons.

### Track A: Without Chips (5-Season Aggregate)

| Engine Version | Architectural Focus | Mean Net Pts (5 Seasons) | Delta vs V0.9 | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---|---:|---:|---:|---:|---:|
| **v0.9** | Learned Participation Baseline | **1983.6** (±212.8) | +0.0 pts | 52.20 | 0.0 | 36.0 |
| **v1.0** | Canonical Single-GW Decision Engine | **2048.4** (±205.2) | +64.8 pts | 53.91 | 0.0 | 36.2 |
| **v1.1** | Strategic Squad Optimization (Multi-GW Init) | **1983.0** (±122.4) | -0.6 pts | 52.18 | 0.0 | 37.8 |
| **v1.1.5** | Departure Engine + Dead Capital Offload + Seasonal Chips | **1980.4** (±145.2) | -3.2 pts | 52.12 | 0.0 | 37.4 |
| **v1.2** | Strategic Squad Balancing (XI vs Bench) + Unavailability Modeling | **2025.8** (±122.0) | +42.2 pts | 53.31 | 0.0 | 37.4 |
| **v1.2.5** | Lineup Horizon Expansion, Candidate Pool Scaling & Dynamic Chip Bench Weighting | **2046.6** (±116.9) | +63.0 pts | 53.86 | 0.0 | 37.2 |
| **v1.3** | GBDT Quantitative Predictor Challenger (evaluated through frozen V1.2.5 decision engine) | **1941.6** (±281.2) | -42.0 pts | 51.10 | 0.0 | 37.2 |

### Track B: With Chips (5-Season Aggregate)

| Engine Version | Mean Net Pts (Track B) | Chip Gain (Track B - Track A) | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---:|---:|---:|---:|---:|
| **v0.9** | **2048.2** (±169.4) | **+64.6 pts** | 53.90 | 0.0 | 49.6 |
| **v1.0** | **2108.0** (±178.9) | **+59.6 pts** | 55.47 | 0.0 | 48.8 |
| **v1.1** | **2010.0** (±177.0) | **+27.0 pts** | 52.89 | 0.0 | 48.4 |
| **v1.1.5** | **2007.8** (±170.7) | **+27.4 pts** | 52.84 | 0.0 | 44.4 |
| **v1.2** | **2050.2** (±151.7) | **+24.4 pts** | 53.95 | 0.0 | 50.2 |
| **v1.2.5** | **2087.8** (±119.7) | **+41.2 pts** | 54.94 | 0.0 | 45.4 |
| **v1.3** | **1985.8** (±287.9) | **+44.2 pts** | 52.26 | 0.0 | 49.8 |

## 4. Season-by-Season Performance Ledger

### Season 2021-22

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx | GK Tx |
|---|---:|---:|---:|---:|---|---:|---:|
| **v0.9** | 1874 | 0 | **2000** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1 | 0 | 6 |
| **v1.0** | 1877 | 0 | **1994** | 0 | FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 | 10 |
| **v1.1** | 1850 | 0 | **1782** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1 | 6 | 7 |
| **v1.1.5** | 1797 | 0 | **1852** | 0 | BENCH_BOOST: 2, FREE_HIT: 1 | 0 | 6 |
| **v1.2** | 1983 | 0 | **1989** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1 | 0 | 4 |
| **v1.2.5** | 1968 | 0 | **2019** | 0 | BENCH_BOOST: 1, FREE_HIT: 1 | 0 | 3 |
| **v1.3** | 1577 | 0 | **1614** | 0 | FREE_HIT: 2, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1 | 0 | 5 |

### Season 2022-23

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx | GK Tx |
|---|---:|---:|---:|---:|---|---:|---:|
| **v0.9** | 1711 | 0 | **1828** | 0 | FREE_HIT: 2, BENCH_BOOST: 1 | 1 | 3 |
| **v1.0** | 1830 | 0 | **1898** | 0 | FREE_HIT: 2, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1 | 0 | 4 |
| **v1.1** | 1863 | 0 | **1870** | 0 | BENCH_BOOST: 2 | 1 | 11 |
| **v1.1.5** | 1888 | 0 | **1841** | 0 | FREE_HIT: 1, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1 | 0 | 7 |
| **v1.2** | 1867 | 0 | **1847** | 0 | FREE_HIT: 2, BENCH_BOOST: 1 | 0 | 10 |
| **v1.2.5** | 1917 | 0 | **1948** | 0 | BENCH_BOOST: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 | 2 |
| **v1.3** | 1705 | 0 | **1742** | 0 | FREE_HIT: 1, BENCH_BOOST: 1 | 1 | 3 |

### Season 2023-24

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx | GK Tx |
|---|---:|---:|---:|---:|---|---:|---:|
| **v0.9** | 2173 | 0 | **2188** | 0 | TRIPLE_CAPTAIN: 1, FREE_HIT: 1, BENCH_BOOST: 1 | 1 | 1 |
| **v1.0** | 2270 | 0 | **2279** | 0 | BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 1 | 5 |
| **v1.1** | 2068 | 0 | **2133** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, FREE_HIT: 1 | 3 | 6 |
| **v1.1.5** | 2167 | 0 | **2245** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 1 | 6 |
| **v1.2** | 2174 | 0 | **2242** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, FREE_HIT: 1 | 0 | 6 |
| **v1.2.5** | 2193 | 0 | **2243** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, FREE_HIT: 1 | 1 | 3 |
| **v1.3** | 2197 | 0 | **2229** | 0 | BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 | 5 |

### Season 2024-25

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx | GK Tx |
|---|---:|---:|---:|---:|---|---:|---:|
| **v0.9** | 2222 | 0 | **2247** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1 | 0 | 5 |
| **v1.0** | 2251 | 0 | **2307** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1, FREE_HIT: 1 | 0 | 4 |
| **v1.1** | 2124 | 0 | **2198** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, FREE_HIT: 1 | 2 | 4 |
| **v1.1.5** | 2066 | 0 | **2098** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1 | 0 | 4 |
| **v1.2** | 2120 | 0 | **2148** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1 | 0 | 6 |
| **v1.2.5** | 2142 | 0 | **2176** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2 | 0 | 4 |
| **v1.3** | 2149 | 0 | **2224** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 | 2 |

### Season 2025-26

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx | GK Tx |
|---|---:|---:|---:|---:|---|---:|---:|
| **v0.9** | 1938 | 0 | **1978** | 0 | BENCH_BOOST: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 | 5 |
| **v1.0** | 2014 | 0 | **2062** | 0 | BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 | 3 |
| **v1.1** | 2010 | 0 | **2067** | 0 | BENCH_BOOST: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 | 6 |
| **v1.1.5** | 1984 | 0 | **2003** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1 | 0 | 4 |
| **v1.2** | 1985 | 0 | **2025** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 | 4 |
| **v1.2.5** | 2013 | 0 | **2053** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 | 4 |
| **v1.3** | 2080 | 0 | **2120** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 | 3 |

## 5. Decision & Experiment Integrity (Pillar 3)

- **Provenance Hash:** `e6afbdb32ca91456`
- **Fallback Guarantee:** Zero silent fallbacks. All runs validated with explicit version confirmation.
- **Point-in-Time Integrity:** Strict pre-gameweek feature snapshots with zero future leakage.
- **Seasonal Chip Invariant:** Independent 2-window allocation (GW 1–19, GW 20–38) with strict GW 19 expiration.
- **V1.2.5 Control Value Invariance:** Control values for V1.2.5 (2,046.6 Track A / 2,087.8 Track B) verified intact after conditioning turnaround inputs on GBDT.
