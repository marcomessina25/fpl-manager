# Historical Initial Squad Backtest: Season 2023-24 (GW 1–10)

**Protocol:** Strict point-in-time pre-GW1 reconstruction (zero future leakage).
**Strategic Horizon:** 5 Gameweeks | **Predictor:** `v1.0.1` | **Decision Engine:** `v1.0.1`

## 1. Starting State Quality Comparison (GW 1–5)

| Starting Squad Strategy | Horizon xP | Realized Horizon Pts | Delta (Real - xP) | Bank | Bench Value | Early Transfers |
|---|---:|---:|---:|---:|---:|---:|
| Baseline A (Template) | 56.73 | 33 | -23.7 | £36.0m | £16.5m | 3 |
| Baseline B (Single-GW Optimizer) | 160.67 | 199 | +38.3 | £0.0m | £20.0m | 3 |
| Candidate Maximum EV | 188.17 | 209 | +20.8 | £0.0m | £21.0m | 3 |
| Candidate Balanced | 188.13 | 209 | +20.9 | £0.0m | £21.0m | 3 |
| Candidate High Floor | 185.44 | 252 | +66.6 | £0.0m | £22.0m | 3 |
| Candidate High Ceiling | 185.24 | 235 | +49.8 | £0.0m | £22.0m | 3 |
| Candidate Flexibility | 188.17 | 209 | +20.8 | £0.0m | £21.0m | 3 |

## 2. Downstream Decision Outcomes (GW 1–10)

| Starting Squad Strategy | Net Points | Gross Points | Hits | Transfers | 0-Min Starters | Bench Regret | Strategic Regret |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline A (Template) | **445** | 445 | 0 | 10 | 36 | 12 | 143 |
| Baseline B (Single-GW Optimizer) | **527** | 527 | 0 | 10 | 14 | 42 | 61 |
| Candidate Maximum EV | **522** | 522 | 0 | 10 | 12 | 29 | 66 |
| Candidate Balanced | **522** | 522 | 0 | 10 | 12 | 29 | 66 |
| Candidate High Floor | **569** | 569 | 0 | 10 | 13 | 25 | 19 |
| Candidate High Ceiling | **588** | 588 | 0 | 10 | 16 | 19 | 0 |
| Candidate Flexibility | **522** | 522 | 0 | 10 | 12 | 29 | 66 |

## 3. Key Findings

- **Top Strategic Strategy:** `Candidate High Ceiling`
- **Strategic vs Single-GW Delta:** -5 pts
- **Evaluation Standard:** Hindsight reference is recorded for regret attribution only and was never exposed to the optimizer.
