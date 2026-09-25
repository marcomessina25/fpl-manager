# Historical Initial Squad Backtest: Season 2021-22 (GW 1–10)

**Protocol:** Strict point-in-time pre-GW1 reconstruction (zero future leakage).
**Strategic Horizon:** 5 Gameweeks | **Predictor:** `v1.0.1` | **Decision Engine:** `v1.0.1`

## 1. Starting State Quality Comparison (GW 1–5)

| Starting Squad Strategy | Horizon xP | Realized Horizon Pts | Delta (Real - xP) | Bank | Bench Value | Early Transfers |
|---|---:|---:|---:|---:|---:|---:|
| Baseline A (Template) | 185.72 | 299 | +113.3 | £0.0m | £29.0m | 0 |
| Baseline B (Single-GW Optimizer) | 151.24 | 271 | +119.8 | £0.0m | £20.0m | 2 |
| Candidate Maximum EV | 960.15 | 248 | -712.1 | £0.0m | £20.0m | 3 |
| Candidate Balanced | 959.95 | 266 | -694.0 | £0.0m | £20.0m | 3 |
| Candidate High Floor | 149.78 | 257 | +107.2 | £0.0m | £22.0m | 3 |
| Candidate High Ceiling | 149.4 | 248 | +98.6 | £0.0m | £20.0m | 3 |
| Candidate Flexibility | 959.95 | 266 | -694.0 | £0.0m | £20.0m | 3 |

## 2. Downstream Decision Outcomes (GW 1–10)

| Starting Squad Strategy | Net Points | Gross Points | Hits | Transfers | 0-Min Starters | Bench Regret | Strategic Regret |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline A (Template) | **573** | 573 | 0 | 0 | 12 | 90 | 0 |
| Baseline B (Single-GW Optimizer) | **551** | 551 | 0 | 9 | 22 | 42 | 22 |
| Candidate Maximum EV | **556** | 556 | 0 | 10 | 16 | 45 | 17 |
| Candidate Balanced | **544** | 544 | 0 | 10 | 17 | 35 | 29 |
| Candidate High Floor | **504** | 504 | 0 | 10 | 17 | 54 | 69 |
| Candidate High Ceiling | **541** | 541 | 0 | 10 | 16 | 37 | 32 |
| Candidate Flexibility | **544** | 544 | 0 | 10 | 17 | 35 | 29 |

## 3. Key Findings

- **Top Strategic Strategy:** `Baseline A (Template)`
- **Strategic vs Single-GW Delta:** -7 pts
- **Evaluation Standard:** Hindsight reference is recorded for regret attribution only and was never exposed to the optimizer.
