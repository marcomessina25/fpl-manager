# Historical Initial Squad Backtest: Season 2023-24 (GW 1–3)

**Protocol:** Strict point-in-time pre-GW1 reconstruction (zero future leakage).
**Strategic Horizon:** 3 Gameweeks | **Predictor:** `v1.0.1` | **Decision Engine:** `v1.0.1`

## 1. Starting State Quality Comparison (GW 1–5)

| Starting Squad Strategy | Horizon xP | Realized Horizon Pts | Delta (Real - xP) | Bank | Bench Value | Early Transfers |
|---|---:|---:|---:|---:|---:|---:|
| Baseline A (Template) | 98.1 | 111 | +12.9 | £0.0m | £26.0m | 0 |
| Baseline B (Single-GW Optimizer) | 89.23 | 124 | +34.8 | £0.0m | £20.0m | 2 |
| Candidate Maximum EV | 345.15 | 146 | -199.2 | £0.0m | £20.0m | 2 |
| Candidate Balanced | 345.0 | 144 | -201.0 | £0.0m | £20.0m | 2 |
| Candidate High Floor | 91.83 | 146 | +54.2 | £0.0m | £22.0m | 2 |
| Candidate High Ceiling | 92.99 | 133 | +40.0 | £0.0m | £20.0m | 3 |
| Candidate Flexibility | 343.62 | 124 | -219.6 | £0.0m | £20.0m | 2 |

## 2. Downstream Decision Outcomes (GW 1–3)

| Starting Squad Strategy | Net Points | Gross Points | Hits | Transfers | 0-Min Starters | Bench Regret | Strategic Regret |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline A (Template) | **111** | 111 | 0 | 0 | 6 | 14 | 51 |
| Baseline B (Single-GW Optimizer) | **139** | 139 | 0 | 2 | 6 | 3 | 23 |
| Candidate Maximum EV | **162** | 162 | 0 | 2 | 5 | 3 | 0 |
| Candidate Balanced | **160** | 160 | 0 | 2 | 5 | 3 | 2 |
| Candidate High Floor | **155** | 155 | 0 | 2 | 7 | 1 | 7 |
| Candidate High Ceiling | **152** | 152 | 0 | 3 | 6 | 6 | 10 |
| Candidate Flexibility | **139** | 139 | 0 | 2 | 6 | 3 | 23 |

## 3. Key Findings

- **Top Strategic Strategy:** `Candidate Maximum EV`
- **Strategic vs Single-GW Delta:** +21 pts
- **Evaluation Standard:** Hindsight reference is recorded for regret attribution only and was never exposed to the optimizer.
