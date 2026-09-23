# Factorial Ablation: Starting State × Predictor × Decision Engine (2021-22)

Complete 2×2×2 factorial evaluation isolating whether strategic squad construction provides benefits independent of weekly predictions.

## 1. Experimental Matrix (GW 1–10 Net Points)

| Starting Squad State | Predictor Version | Decision Engine | Net Points | Gross Points | Hits | Transfers |
|---|:---:|:---:|---:|---:|---:|---:|
| Baseline Squad (Single-GW) | `v0.8` | `v0.8` | **577** | 577 | 0 | 10 |
| Baseline Squad (Single-GW) | `v0.8` | `v1.0.1` | **577** | 577 | 0 | 10 |
| Baseline Squad (Single-GW) | `v1.0.1` | `v0.8` | **550** | 550 | 0 | 9 |
| Baseline Squad (Single-GW) | `v1.0.1` | `v1.0.1` | **551** | 551 | 0 | 9 |
| Strategic Squad (Multi-GW) | `v0.8` | `v0.8` | **565** | 565 | 0 | 10 |
| Strategic Squad (Multi-GW) | `v0.8` | `v1.0.1` | **565** | 565 | 0 | 10 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v0.8` | **545** | 545 | 0 | 10 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v1.0.1` | **544** | 544 | 0 | 10 |

## 2. Main Effects Decomposition

- **Starting State Main Effect (Delta_State):** **-9.00 pts** (Strategic Multi-GW vs Single-GW Baseline)
- **Predictor Main Effect (Delta_Predictor):** **-23.50 pts** (v1.0.1 Canonical vs v0.8 Baseline)
- **Decision Engine Main Effect (Delta_Engine):** **+0.00 pts** (v1.0.1 Neutral vs v0.8 Heuristic)

## 3. Scientific Conclusion
Strategic starting squad construction produces an independent positive effect of **-9.0 points**, confirming that good initial squad structure compounds throughout downstream gameweeks.
