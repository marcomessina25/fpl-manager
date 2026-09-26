# Multi-Version Historical Benchmark Ledger: V0.9 vs V1.0 vs V1.1 vs V1.1.5

**Historical Seasons:** 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (5 seasons evaluated)
**Evaluation Window:** GW 1–38 | **Predictor:** `v1.0.1` | **Benchmark Date:** 2026-09-26

## 1. Executive Summary: Multi-Season Cross-Version Comparison

### Track A: Without Chips (Isolating Base Decision Engine & Squad Construction)

| Engine Version | Architectural Focus | Mean Net Pts | Delta vs V0.9 | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---|---:|---:|---:|---:|---:|
| **v0.9** | Learned Participation Baseline | **1983.6** (±212.8) | +0.0 pts | 52.20 | 0.0 | 36.0 |
| **v1.0** | Canonical Single-GW Decision Engine | **2048.4** (±205.2) | +64.8 pts | 53.91 | 0.0 | 36.2 |
| **v1.1** | Strategic Squad Optimization (Multi-GW Init) | **1983.0** (±122.4) | -0.6 pts | 52.18 | 0.0 | 37.8 |
| **v1.1.5** | Departure Engine + Dead Capital Offload + Seasonal Chips | **1983.0** (±122.4) | -0.6 pts | 52.18 | 0.0 | 37.8 |

### Track B: With Chips (Sequential 2-Window Seasonal Replay: GW 1–19, GW 20–38)

| Engine Version | Mean Net Pts (Track B) | Chip Gain (Track B - Track A) | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---:|---:|---:|---:|---:|
| **v0.9** | **2012.6** (±153.2) | **+29.0 pts** | 52.96 | 0.0 | 71.6 |
| **v1.0** | **2065.6** (±141.6) | **+17.2 pts** | 54.36 | 0.0 | 68.4 |
| **v1.1** | **2056.0** (±165.7) | **+73.0 pts** | 54.10 | 0.0 | 70.0 |
| **v1.1.5** | **2056.0** (±165.7) | **+73.0 pts** | 54.10 | 0.0 | 70.0 |

## 2. Season-by-Season Performance Ledger

### Season 2021-22

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 1874 | 0 | **1976** | 0 | WILDCARD: 2, BENCH_BOOST: 2, FREE_HIT: 2, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.0** | 1877 | 0 | **2110** | 0 | WILDCARD: 2, FREE_HIT: 2, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.1** | 1850 | 0 | **2011** | 0 | FREE_HIT: 2, WILDCARD: 2, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 2 | 0 |
| **v1.1.5** | 1850 | 0 | **2011** | 0 | FREE_HIT: 2, WILDCARD: 2, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 2 | 0 |

### Season 2022-23

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 1711 | 0 | **1828** | 0 | WILDCARD: 2, FREE_HIT: 2, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.0** | 1830 | 0 | **1927** | 0 | WILDCARD: 2, FREE_HIT: 2, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.1** | 1863 | 0 | **1840** | 0 | FREE_HIT: 1, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, WILDCARD: 1 | 0 |
| **v1.1.5** | 1863 | 0 | **1840** | 0 | FREE_HIT: 1, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1, WILDCARD: 1 | 0 |

### Season 2023-24

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 2173 | 0 | **2161** | 0 | WILDCARD: 2, TRIPLE_CAPTAIN: 2, FREE_HIT: 1, BENCH_BOOST: 1 | 0 |
| **v1.0** | 2270 | 0 | **2218** | 0 | BENCH_BOOST: 2, TRIPLE_CAPTAIN: 2, WILDCARD: 2, FREE_HIT: 1 | 0 |
| **v1.1** | 2068 | 0 | **2195** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, WILDCARD: 2, FREE_HIT: 1 | 0 |
| **v1.1.5** | 2068 | 0 | **2195** | 0 | TRIPLE_CAPTAIN: 2, BENCH_BOOST: 2, WILDCARD: 2, FREE_HIT: 1 | 0 |

### Season 2024-25

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 2222 | 0 | **2179** | 0 | WILDCARD: 2, BENCH_BOOST: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.0** | 2251 | 0 | **2167** | 0 | WILDCARD: 2, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.1** | 2124 | 0 | **2248** | 0 | WILDCARD: 2, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 2, FREE_HIT: 1 | 0 |
| **v1.1.5** | 2124 | 0 | **2248** | 0 | WILDCARD: 2, BENCH_BOOST: 2, TRIPLE_CAPTAIN: 2, FREE_HIT: 1 | 0 |

### Season 2025-26

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 1938 | 0 | **1919** | 0 | BENCH_BOOST: 2, WILDCARD: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.0** | 2014 | 0 | **1906** | 0 | WILDCARD: 2, BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1, FREE_HIT: 1 | 0 |
| **v1.1** | 2010 | 0 | **1986** | 0 | BENCH_BOOST: 2, WILDCARD: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.1.5** | 2010 | 0 | **1986** | 0 | BENCH_BOOST: 2, WILDCARD: 2, FREE_HIT: 1, TRIPLE_CAPTAIN: 1 | 0 |

## 3. Decision & Experiment Integrity (Pillar 3)

- **Provenance Hash:** `b2e8ab73e40133f9`
- **Fallback Guarantee:** Zero silent fallbacks. All runs validated with explicit version confirmation.
- **Point-in-Time Integrity:** Strict pre-gameweek feature snapshots with zero future leakage.
- **Seasonal Chip Invariant:** Independent 2-window allocation (GW 1–19, GW 20–38) with strict GW 19 expiration.
