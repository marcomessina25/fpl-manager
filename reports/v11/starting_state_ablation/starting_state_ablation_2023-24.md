# Factorial Ablation: Starting State × Predictor × Decision Engine (2023-24)

Complete 2×2×2 factorial evaluation isolating whether strategic squad construction provides benefits independent of weekly predictions.

## 1. Experimental Matrix (GW 1–10 Net Points)

| Starting Squad State | Predictor Version | Decision Engine | Net Points | Gross Points | Hits | Transfers |
|---|:---:|:---:|---:|---:|---:|---:|
| Baseline Squad (Single-GW) | `v0.8` | `v0.8` | **137** | 137 | 0 | 2 |
| Baseline Squad (Single-GW) | `v0.8` | `v1.0.1` | **137** | 137 | 0 | 2 |
| Baseline Squad (Single-GW) | `v1.0.1` | `v0.8` | **137** | 137 | 0 | 2 |
| Baseline Squad (Single-GW) | `v1.0.1` | `v1.0.1` | **139** | 139 | 0 | 2 |
| Strategic Squad (Multi-GW) | `v0.8` | `v0.8` | **158** | 158 | 0 | 2 |
| Strategic Squad (Multi-GW) | `v0.8` | `v1.0.1` | **158** | 158 | 0 | 2 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v0.8` | **158** | 158 | 0 | 2 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v1.0.1` | **160** | 160 | 0 | 2 |

## 2. Main Effects Decomposition

- **Starting State Main Effect (Delta_State):** **+21.00 pts** (Strategic Multi-GW vs Single-GW Baseline)
- **Predictor Main Effect (Delta_Predictor):** **+1.00 pts** (v1.0.1 Canonical vs v0.8 Baseline)
- **Decision Engine Main Effect (Delta_Engine):** **+1.00 pts** (v1.0.1 Neutral vs v0.8 Heuristic)

## 3. Scientific Conclusion
Strategic starting squad construction produces an independent positive effect of **+21.0 points**, confirming that good initial squad structure compounds throughout downstream gameweeks.
