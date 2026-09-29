# Multi-Version Historical Benchmark Ledger: V0.9 vs V1.0 vs V1.1 vs V1.1.5 vs V1.2

**Historical Seasons:** 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (5 seasons evaluated)
**Evaluation Window:** GW 1–38 | **Predictor:** `v1.0.1` | **Benchmark Date:** 2026-09-29

## 1. Executive Summary: Multi-Season Cross-Version Comparison

### Track A: Without Chips (Isolating Base Decision Engine & Squad Construction)

| Engine Version | Architectural Focus | Mean Net Pts | Delta vs V0.9 | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---|---:|---:|---:|---:|---:|
| **v0.9** | Learned Participation Baseline | **1983.6** (±212.8) | +0.0 pts | 52.20 | 0.0 | 36.0 |
| **v1.0** | Canonical Single-GW Decision Engine | **2048.4** (±205.2) | +64.8 pts | 53.91 | 0.0 | 36.2 |
| **v1.1** | Strategic Squad Optimization (Multi-GW Init) | **1983.0** (±122.4) | -0.6 pts | 52.18 | 0.0 | 37.8 |
| **v1.1.5** | Departure Engine + Dead Capital Offload + Seasonal Chips | **1980.4** (±145.2) | -3.2 pts | 52.12 | 0.0 | 37.4 |
| **v1.2** | Strategic Squad Balancing (XI vs Bench) + Unavailability Modeling | **2025.8** (±122.0) | +42.2 pts | 53.31 | 0.0 | 37.4 |

### Track B: With Chips (Sequential 2-Window Seasonal Replay: GW 1–19, GW 20–38)

| Engine Version | Mean Net Pts (Track B) | Chip Gain (Track B - Track A) | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---:|---:|---:|---:|---:|
| **v0.9** | **2048.2** (±169.4) | **+64.6 pts** | 53.90 | 0.0 | 49.6 |
| **v1.0** | **2108.0** (±178.9) | **+59.6 pts** | 55.47 | 0.0 | 48.8 |
| **v1.1** | **2010.0** (±177.0) | **+27.0 pts** | 52.89 | 0.0 | 48.4 |
| **v1.1.5** | **2007.8** (±170.7) | **+27.4 pts** | 52.84 | 0.0 | 44.4 |
| **v1.2** | **2050.2** (±151.7) | **+24.4 pts** | 53.95 | 0.0 | 50.2 |

## 2. Season-by-Season Performance Ledger

### Season 2021-22

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 1874 | 0 | **2000** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1 | 0 |
| **v1.0** | 1877 | 0 | **1994** | 0 | FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.1** | 1850 | 0 | **1782** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1 | 6 |
| **v1.1.5** | 1797 | 0 | **1852** | 0 | BENCH_BOOST: 2, FREE_HIT: 1 | 0 |
| **v1.2** | 1983 | 0 | **1989** | 0 | FREE_HIT: 2, TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1 | 0 |

### Season 2022-23

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 1711 | 0 | **1828** | 0 | FREE_HIT: 2, BENCH_BOOST: 1 | 1 |
| **v1.0** | 1830 | 0 | **1898** | 0 | FREE_HIT: 2, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.1** | 1863 | 0 | **1870** | 0 | BENCH_BOOST: 2 | 1 |
| **v1.1.5** | 1888 | 0 | **1841** | 0 | FREE_HIT: 1, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.2** | 1867 | 0 | **1847** | 0 | FREE_HIT: 2, BENCH_BOOST: 1 | 0 |

### Season 2023-24

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 2173 | 0 | **2188** | 0 | TRIPLE_CAPTAIN: 1, FREE_HIT: 1, BENCH_BOOST: 1 | 1 |
| **v1.0** | 2270 | 0 | **2279** | 0 | BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 1 |
| **v1.1** | 2068 | 0 | **2133** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, FREE_HIT: 1 | 3 |
| **v1.1.5** | 2167 | 0 | **2245** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 1 |
| **v1.2** | 2174 | 0 | **2242** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, FREE_HIT: 1 | 0 |

### Season 2024-25

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 2222 | 0 | **2247** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1 | 0 |
| **v1.0** | 2251 | 0 | **2307** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1, FREE_HIT: 1 | 0 |
| **v1.1** | 2124 | 0 | **2198** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, FREE_HIT: 1 | 2 |
| **v1.1.5** | 2066 | 0 | **2098** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1 | 0 |
| **v1.2** | 2120 | 0 | **2148** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 1 | 0 |

### Season 2025-26

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 1938 | 0 | **1978** | 0 | BENCH_BOOST: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.0** | 2014 | 0 | **2062** | 0 | BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 |
| **v1.1** | 2010 | 0 | **2067** | 0 | BENCH_BOOST: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.1.5** | 1984 | 0 | **2003** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.2** | 1985 | 0 | **2025** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 |

## 3. Decision & Experiment Integrity (Pillar 3)

- **Provenance Hash:** `b2e8ab73e40133f9`
- **Fallback Guarantee:** Zero silent fallbacks. All runs validated with explicit version confirmation.
- **Point-in-Time Integrity:** Strict pre-gameweek feature snapshots with zero future leakage.
- **Seasonal Chip Invariant:** Independent 2-window allocation (GW 1–19, GW 20–38) with strict GW 19 expiration.
