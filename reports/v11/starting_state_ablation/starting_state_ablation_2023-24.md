# Full Factorial Ablation: Starting State × Predictor × Decision Engine (2023-24)

Complete 2×2×2 factorial evaluation evaluating main effects, pairwise interactions, and 3-way interactions without premature independence assumptions.

## 1. Experimental Matrix (GW 1–10 Net Points)

| Starting Squad State (A) | Construction Predictor | Evaluation Predictor (B) | Decision Engine (C) | Net Points | Gross Points | Hits | Transfers |
|---|:---:|:---:|:---:|---:|---:|---:|---:|
| Baseline Squad (Single-GW) | `v1.0.1` | `v0.8` | `v0.8` | **531** | 531 | 0 | 10 |
| Baseline Squad (Single-GW) | `v1.0.1` | `v0.8` | `v1.0.1` | **538** | 538 | 0 | 10 |
| Baseline Squad (Single-GW) | `v1.0.1` | `v1.0.1` | `v0.8` | **527** | 527 | 0 | 10 |
| Baseline Squad (Single-GW) | `v1.0.1` | `v1.0.1` | `v1.0.1` | **527** | 527 | 0 | 10 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v0.8` | `v0.8` | **584** | 584 | 0 | 10 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v0.8` | `v1.0.1` | **591** | 591 | 0 | 10 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v1.0.1` | `v0.8` | **524** | 524 | 0 | 10 |
| Strategic Squad (Multi-GW) | `v1.0.1` | `v1.0.1` | `v1.0.1` | **522** | 522 | 0 | 10 |

## 2. Main Effects Decomposition

- **Grand Mean (y_bar):** **543.00 pts**
- **Starting State Main Effect (Delta_A):** **+24.50 pts** (Strategic Multi-GW vs Single-GW Baseline)
- **Predictor Main Effect (Delta_B):** **-36.00 pts** (v1.0.1 Canonical vs v0.8 Baseline)
- **Decision Engine Main Effect (Delta_C):** **+3.00 pts** (v1.0.1 Neutral vs v0.8 Heuristic)

## 3. Pairwise & Three-Way Interactions

- **Starting State × Predictor (Delta_AB):** **-28.50 pts**
- **Starting State × Decision Engine (Delta_AC):** **-0.50 pts**
- **Predictor × Decision Engine (Delta_BC):** **-4.00 pts**
- **Three-Way Interaction (Delta_ABC):** **-0.50 pts**

## 4. Scientific Interpretation
The starting state main effect is **+24.50 pts**, with interaction terms demonstrating the extent to which starting squad quality couples with downstream weekly decision engines.
