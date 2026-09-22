# Mathematical Optimizer & Multi-Gameweek Planning

> **Status:** Canonical Production Release in V1.0 (`v1.0.0`). Updated on 2026-09-22.
> **Source Modules:** [`src/fpl_manager/optimizer.py`](../src/fpl_manager/optimizer.py), [`src/fpl_manager/planner.py`](../src/fpl_manager/planner.py), [`src/fpl_manager/lineup.py`](../src/fpl_manager/lineup.py)

This document details the mathematical optimization engines in **FPL Manager V1.0**:
1. **Exact Combinatorial Branch-and-Bound Multi-Transfer Solver (1–5 Transfers)** (`fpl suggest-transfers`)
2. **Heuristic Local-Search Wildcard & Free-Hit 15-Player Squad Optimizer** (`fpl wildcard` / `fpl free-hit`)
3. **Beam Search & Exhaustive Reference Multi-Gameweek Planning Roadmap** (`fpl plan`)

All algorithms are implemented in **pure Python standard library** (without heavy binary dependencies such as SciPy or PuLP), ensuring zero setup friction, fast start-up, and deterministic reproducibility.

---

## 1. Branch-and-Bound Multi-Transfer Solver (`1–5` Transfers)

### Problem Formulation
Given a current 15-player squad, an available bank balance $B$, and $FT$ available free transfers:
We wish to select a subset of $K \in \{1, 2, 3, 4, 5\}$ players to sell, $\mathcal{S}_{\text{out}} \subset \text{Squad}$ ($|\mathcal{S}_{\text{out}}| = K$), and a corresponding subset of $K$ players to purchase, $\mathcal{S}_{\text{in}} \subset \text{Pool}$ ($|\mathcal{S}_{\text{in}}| = K$), such that:

1. **Position Equality**: For each position $P \in \{\text{GKP}, \text{DEF}, \text{MID}, \text{FWD}\}$, the number of players sold in position $P$ equals the number of players bought in position $P$:
   $$|\mathcal{S}_{\text{in}} \cap P| = |\mathcal{S}_{\text{out}} \cap P|$$
2. **Budget Constraint**:
   $$\sum_{p \in \mathcal{S}_{\text{in}}} \text{Price}(p) \le B + \sum_{p \in \mathcal{S}_{\text{out}}} \text{SellingPrice}(p)$$
3. **Club Limit**:
   $$\text{Count}(T, \text{Squad} \setminus \mathcal{S}_{\text{out}} \cup \mathcal{S}_{\text{in}}) \le 3 \quad \forall \text{ teams } T$$
4. **Objective Function**: Maximize score:
   $$\text{Score} = \Delta \text{Metric}(\mathcal{S}_{\text{in}}, \mathcal{S}_{\text{out}}) - 4 \times \max(0, K - FT) + 0.1 \times \Delta \text{FDR}$$

### Exactness Guarantee (`solve_transfers` vs `solve_transfers_exhaustive`)
In V1.0, `solve_transfers` is mathematically verified against brute-force exhaustive enumeration (`solve_transfers_exhaustive` in [`src/fpl_manager/optimizer.py`](../src/fpl_manager/optimizer.py)) across $K \in \{1, 2, 3, 4, 5\}$ transfers:
- **Exact Global Optimum**: Because candidate position bounds are monotonically sorted and upper-bound pruning only discards subtrees whose theoretical maximum cannot beat the current top-$N$ heap minimum, `solve_transfers` returns the **exact same global optimum** as brute-force exhaustive enumeration for all $K \in \{1..5\}$.

---

## 2. Heuristic Local-Search Wildcard & Free-Hit Optimizer (`solve_wildcard`)

> [!IMPORTANT]
> **Methodological Disclosure (V1.0):** Unlike the 1–5 transfer solver (`solve_transfers`), which is provably exact via admissible branch-and-bound, the 15-player full-squad solver (`solve_wildcard`) is a **multi-stage heuristic local-search optimizer** (`algorithm = "heuristic_local_search_1opt_2opt"`, `is_exact_global_optimum = False`, `optimality_guarantee = "heuristic_local_optimum"`). Every `solve_wildcard` report explicitly embeds these fields in `optimization_metadata`.

### Problem Formulation
Select a legal 15-player squad from the active Premier League pool subject to:
- Exactly 2 Goalkeepers, 5 Defenders, 5 Midfielders, 3 Forwards
- Maximum 3 players from any single Premier League club
- Total squad cost $\le$ Budget ($B$)
- Maximizes starting XI score under the best legal outfield formation.

### Four-Stage Heuristic Local-Search Architecture

```mermaid
flowchart TD
    A["Player Pool: ~650 players"] --> B["Stage 1: Feasible Initial Squad (Cheapest active players with club spread)"]
    B --> C["Stage 2: 1-Opt Greedy Upgrading (Max delta xP / delta cost)"]
    C --> D["Stage 3: 2-Opt Cross-Position Search (Pairwise swaps across positions)"]
    D --> E["Stage 4: Lineup & Captain Optimizer (8 legal formations, Captain + VC, Bench order)"]
    E --> F["Rules Engine Verification (Deterministic check against rules.py)"]
```

---

## 3. V1.0 Risk Profiles & Neutral Strategy Alignment

All optimizers (`lineup.py`, `optimizer.py`, `planner.py`, and `DecisionEngineV10`) share the canonical `RISK_PROFILE_SPECIFICATIONS` defined in [`src/fpl_manager/optimizer.py`](../src/fpl_manager/optimizer.py):

| Risk Profile | Mathematical Objective | `lineup_penalty_weight` | Purpose |
| :--- | :--- | :---: | :--- |
| **`neutral`** *(V1.0 Default)* | $\max \mathbb{E}[xP]$ | `0.00` | Pure expected-points maximization with zero artificial variance penalty |
| **`safe`** | $\max (\mathbb{E}[xP] - 0.15 \times \sigma)$ | `0.15` | Mild downside variance penalty (preserves V0.9 default behavior) |
| **`conservative`** / `floor` | $\max xP_{\text{floor}}$ (10th percentile) | `0.35` | Maximizes guaranteed appearance and floor points |
| **`upside`** / `ceiling` | $\max xP_{\text{ceiling}}$ (90th percentile) | `-0.15` | Maximizes haul potential and ceiling upside |
| **`differential`** | $\max (\mathbb{E}[xP] + 0.25 \times (xP_{\text{ceiling}} - \mathbb{E}[xP]))$ | `-0.10` | Rewards high-upside variance for rank-chasing |

---

## 4. Multi-Gameweek Planning Roadmap (`fpl plan`)

`fpl plan` models the sequential decision tree across a rolling horizon $H$ using **Beam Search** (`generate_multi_gameweek_plan`), and provides an exact reference solver (`plan_multi_gw_exhaustive`) for short horizons ($H \le 3$) to verify zero beam-pruning loss on test fixtures.

### State Dynamics
At each gameweek step $t \in [0, H-1]$:
- **State**: Squad of 15 players, bank balance, available free transfers $FT \in [1, 5]$, and player purchase prices.
- **Actions**:
  - **ROLL**: Make 0 transfers. $FT_{t+1} = \min(5, FT_t + 1)$. Hits = 0.
  - **1_TRANSFER**: Make 1 transfer. Hits = $\max(0, 1 - FT_t) \times 4$.
  - **2_TRANSFERS**: Make 2 transfers. Hits = $\max(0, 2 - FT_t) \times 4$.
- **Step Reward**:
  $$\text{Reward}_t = \text{StartingXI\_xP}(squad_t, GW_t) + \text{Captain\_xP}(squad_t, GW_t) - \text{Hits}_t$$
- **Cumulative Objective**:
  $$\max \sum_{t=0}^{H-1} \text{Reward}_t$$

