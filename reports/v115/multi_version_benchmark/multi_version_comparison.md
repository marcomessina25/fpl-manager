# Multi-Version Historical Benchmark Ledger: V0.9 vs V1.0 vs V1.1 vs V1.1.5

**Historical Seasons:** 2023-24 (1 seasons evaluated)
**Evaluation Window:** GW 1–19 | **Predictor:** `v1.0.1` | **Benchmark Date:** 2026-09-25

## 1. Executive Summary: Multi-Season Cross-Version Comparison

### Track A: Without Chips (Isolating Base Decision Engine & Squad Construction)

| Engine Version | Architectural Focus | Mean Net Pts | Delta vs V0.9 | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---|---:|---:|---:|---:|---:|
| **v0.9** | Learned Participation Baseline | **1010.0** (±0.0) | +0.0 pts | 53.16 | 0.0 | 18.0 |
| **v1.0** | Canonical Single-GW Decision Engine | **1046.0** (±0.0) | +36.0 pts | 55.05 | 0.0 | 18.0 |
| **v1.1** | Strategic Squad Optimization (Multi-GW Init) | **949.0** (±0.0) | -61.0 pts | 49.95 | 0.0 | 19.0 |
| **v1.1.5** | Departure Engine + Dead Capital Offload + Seasonal Chips | **949.0** (±0.0) | -61.0 pts | 49.95 | 0.0 | 19.0 |

### Track B: With Chips (Sequential 2-Window Seasonal Replay: GW 1–19, GW 20–38)

| Engine Version | Mean Net Pts (Track B) | Chip Gain (Track B - Track A) | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---:|---:|---:|---:|---:|
| **v0.9** | **1010.0** (±0.0) | **+0.0 pts** | 53.16 | 0.0 | 28.0 |
| **v1.0** | **1069.0** (±0.0) | **+23.0 pts** | 56.26 | 0.0 | 25.0 |
| **v1.1** | **963.0** (±0.0) | **+14.0 pts** | 50.68 | 0.0 | 29.0 |
| **v1.1.5** | **963.0** (±0.0) | **+14.0 pts** | 50.68 | 0.0 | 29.0 |

## 2. Season-by-Season Performance Ledger

### Season 2023-24

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 1010 | 0 | **1010** | 0 | WILDCARD: 1, TRIPLE_CAPTAIN: 1 | 0 |
| **v1.0** | 1046 | 0 | **1069** | 0 | BENCH_BOOST: 1, TRIPLE_CAPTAIN: 1, WILDCARD: 1 | 0 |
| **v1.1** | 949 | 0 | **963** | 0 | TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1, WILDCARD: 1 | 0 |
| **v1.1.5** | 949 | 0 | **963** | 0 | TRIPLE_CAPTAIN: 1, BENCH_BOOST: 1, WILDCARD: 1 | 0 |

## 3. Decision & Experiment Integrity (Pillar 3)

- **Provenance Hash:** `aa3f1f1bcd4991d1`
- **Fallback Guarantee:** Zero silent fallbacks. All runs validated with explicit version confirmation.
- **Point-in-Time Integrity:** Strict pre-gameweek feature snapshots with zero future leakage.
- **Seasonal Chip Invariant:** Independent 2-window allocation (GW 1–19, GW 20–38) with strict GW 19 expiration.
