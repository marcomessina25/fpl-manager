# V1.3.5 Optimizer Decision-Quality Study — Final Summary

## Executive Verdict & Key Findings

The V1.3.5 study isolated the incremental decision-level effect of each optimizer mechanism holding the quantitative predictor frozen.

### Key Discoveries

1. **Bench-Aware Multi-Horizon Value ($B_0 \to B_1 \to B_3$):** Multi-GW horizon ($H=3, \gamma=0.75$) without bench awareness is brittle (-56 pts vs control); adding explicit bench weighting ($W_{\text{bench}}=0.15$) surges performance to **2,289.0 pts (+193.0 pts over $B_1$, +137.0 pts over control $B_0$)** by buffering against multi-period prediction error.
2. **Goalkeeper Churn Suppression ($B_3 \to B_4$):** Enforcing role-specific hurdles ($3.0$ pts) on healthy goalkeepers suppresses zero-utility GK transfers, protecting free transfers for outfield assets.
3. **Candidate Pool Regularization ($B_4 \to B_5$):** Expanding search from 5 to 25 candidates caused a severe -147 pt collapse (2,289 to 2,142) due to "search breadth overfitting", where the optimizer aggressively selects noisy prediction tail outliers. Constraining pool size to $N=5$ acts as an essential regularizer.
4. **Mathematical Regret Decomposition:** Formally verified the invariant $\text{Total Decision Regret} \equiv \text{Prediction Regret} + \text{Optimizer Regret}$. Optimizer Regret is 0.00 pts in both $B_3$ and $B_7$; the shortfall in wider search spaces is purely driven by Prediction Regret surging from 6.50 to 21.83 pts.
5. **Starting-State Primacy:** Initial squad construction has compounding leverage (+93 net pts with `maximum_ev` over balanced initialization).
6. **Hardened Production Engine:** Deployed in `DecisionEngineV135` and `resolve_decision_engine("v1.3.5")`, synthesizing $H=3, \gamma=0.75, W_{\text{bench}}=0.15, \text{GK}_{\text{hurdle}}=3.0, N_{\text{pool}}=5$, and default `maximum_ev` initialization.

### Deliverables Summary

- Engine Implementation: [`src/fpl_manager/backtest/decision_engine.py`](../../src/fpl_manager/backtest/decision_engine.py) (`DecisionEngineV135`)
- Manifest: [`experiment_manifest.json`](experiment_manifest.json)
- Ablation Matrix: [`optimizer_ablation.md`](optimizer_ablation.md) and [`optimizer_ablation.csv`](optimizer_ablation.csv)
- Regret Decomposition: [`regret_analysis.md`](regret_analysis.md) and [`regret_analysis.csv`](regret_analysis.csv)
- Runtime Budget: [`runtime_analysis.csv`](runtime_analysis.csv)

