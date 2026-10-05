# V1.3.5 Optimizer Decision-Quality Study — Final Summary

## Executive Verdict & Key Findings

The V1.3.5 study isolated the incremental decision-level effect of each optimizer mechanism holding the quantitative predictor frozen.

### Key Discoveries

1. **Multi-Gameweek Horizon Value ($B_0 \to B_1$):** Expanding planning horizon from $H=1$ to $H=3$ with exponential discounting ($\gamma=0.75$) yields immediate point stability and reduces myopic churn.
2. **Goalkeeper Churn Suppression ($B_3 \to B_4$):** Enforcing role-specific hurdles ($3.0$ pts) on healthy goalkeepers prevents zero-utility goalkeeper transfers, preserving free transfers for outfield assets.
3. **Candidate Pool Breadth ($B_4 \to B_5$):** Expanding search from 5 to 25 candidates per role unlocks higher-quality transfer paths with minimal runtime overhead.
4. **Mathematical Regret Decomposition:** Successfully separated prediction regret from optimizer regret, verifying the invariant $\text{Total Decision Regret} = \text{Prediction Regret} + \text{Optimizer Regret}$.

### Deliverables Summary

- Manifest: [`experiment_manifest.json`](experiment_manifest.json)
- Ablation Matrix: [`optimizer_ablation.md`](optimizer_ablation.md) and [`optimizer_ablation.csv`](optimizer_ablation.csv)
- Regret Decomposition: [`regret_analysis.md`](regret_analysis.md) and [`regret_analysis.csv`](regret_analysis.csv)
- Runtime Budget: [`runtime_analysis.csv`](runtime_analysis.csv)
