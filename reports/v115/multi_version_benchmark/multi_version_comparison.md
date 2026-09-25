# Multi-Version Historical Benchmark Ledger: V0.9 vs V1.0 vs V1.1 vs V1.1.5

**Historical Seasons:** 2021-22 (1 seasons evaluated)
**Evaluation Window:** GW 1–3 | **Predictor:** `v1.0.1` | **Benchmark Date:** 2026-09-25

## 1. Executive Summary: Multi-Season Cross-Version Comparison

### Track A: Without Chips (Isolating Base Decision Engine & Squad Construction)

| Engine Version | Architectural Focus | Mean Net Pts | Delta vs V0.9 | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---|---:|---:|---:|---:|---:|
| **v0.9** | Learned Participation Baseline | **192.0** (±0.0) | +0.0 pts | 64.00 | 0.0 | 2.0 |
| **v1.0** | Canonical Single-GW Decision Engine | **200.0** (±0.0) | +8.0 pts | 66.67 | 0.0 | 2.0 |
| **v1.1** | Strategic Squad Optimization (Multi-GW Init) | **167.0** (±0.0) | -25.0 pts | 55.67 | 0.0 | 3.0 |
| **v1.1.5** | Departure Engine + Dead Capital Offload + Seasonal Chips | **167.0** (±0.0) | -25.0 pts | 55.67 | 0.0 | 3.0 |

### Track B: With Chips (Sequential 2-Window Seasonal Replay: GW 1–19, GW 20–38)

| Engine Version | Mean Net Pts (Track B) | Chip Gain (Track B - Track A) | Mean Pts/GW | Mean Hits | Mean Transfers |
|---|---:|---:|---:|---:|---:|
| **v0.9** | **192.0** (±0.0) | **+0.0 pts** | 64.00 | 0.0 | 2.0 |
| **v1.0** | **200.0** (±0.0) | **+0.0 pts** | 66.67 | 0.0 | 2.0 |
| **v1.1** | **167.0** (±0.0) | **+0.0 pts** | 55.67 | 0.0 | 3.0 |
| **v1.1.5** | **167.0** (±0.0) | **+0.0 pts** | 55.67 | 0.0 | 3.0 |

## 2. Season-by-Season Performance Ledger

### Season 2021-22

| Engine Version | Track A Net | Track A Hits | Track B Net | Track B Hits | Chips Deployed (Track B) | Dead Capital Tx |
|---|---:|---:|---:|---:|---|---:|
| **v0.9** | 192 | 0 | **192** | 0 | None | 0 |
| **v1.0** | 200 | 0 | **200** | 0 | None | 0 |
| **v1.1** | 167 | 0 | **167** | 0 | None | 0 |
| **v1.1.5** | 167 | 0 | **167** | 0 | None | 0 |

## 3. Decision & Experiment Integrity (Pillar 3)

- **Provenance Hash:** `af80d38c0603a567`
- **Fallback Guarantee:** Zero silent fallbacks. All runs validated with explicit version confirmation.
- **Point-in-Time Integrity:** Strict pre-gameweek feature snapshots with zero future leakage.
- **Seasonal Chip Invariant:** Independent 2-window allocation (GW 1–19, GW 20–38) with strict GW 19 expiration.
