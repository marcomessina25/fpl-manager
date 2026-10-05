# V1.3.5 Decision-Regret Decomposition Analysis

## Mathematical Framework

$$\text{Total Decision Regret} = \text{Prediction Regret} + \text{Optimizer Regret}$$

- **Prediction Regret:** Loss attributable to imperfect forecasting ($	ext{Hindsight} - 	ext{Best Model}$).  
- **Optimizer Regret:** Loss attributable to optimizer heuristics, constraints, or horizons ($	ext{Best Model} - 	ext{Selected}$).  
- **Total Decision Regret:** Combined shortfall relative to perfect retrospective benchmark ($	ext{Hindsight} - 	ext{Selected}$).  

## Mean Regret by Ablation Variant (Sampled Decision Points)

| Variant | Mean Prediction Regret | Mean Optimizer Regret | Mean Total Decision Regret | Identity Verified |
|---|---:|---:|---:|:---:|
| **B0** | 20.17 pts | 1.00 pts | **21.17 pts** | ✅ |
| **B3** | 20.83 pts | 0.00 pts | **20.83 pts** | ✅ |
| **B7** | 21.83 pts | 0.00 pts | **21.83 pts** | ✅ |

---
