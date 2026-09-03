# Expected Points (xP) Baseline Model

> **Status:** Active in V0.2. Defined on 2026-09-03.
> **Source Module:** [`src/fpl_manager/expected_points.py`](../src/fpl_manager/expected_points.py)

---

## 1. Purpose and Principles

In accordance with [`docs/architecture.md`](architecture.md), FPL Manager separates deterministic facts, quantitative models, and human/LLM analysis:

```
Official FPL Snapshot -> Quantitative Baseline (xP) -> Legal Optimizer (Lineup/Captain) -> Reports
```

The expected-points ($xP$) model provides a transparent, verifiable, and deterministic expectation of points scored by a player in an upcoming fixture or gameweek.

### Core Design Rules
- **No Black-Box Magic:** Every projection can be inspected, traced, and mathematically reproduced from official snapshot data.
- **Independence from LLMs:** Projections do not rely on LLM prompts or unstructured news text.
- **Rule Safety First:** Projections guide selection, but all squad compositions and starting lineups must pass the independent validator in [`src/fpl_manager/rules.py`](../src/fpl_manager/rules.py).

---

## 2. Mathematical Formulation

For each player $p$ in an upcoming fixture $f$ of gameweek $GW$:

$$xP(p, f) = \text{BaseXP}(p) \times \text{Availability}(p) \times \text{FDRMultiplier}(p, f) \times \text{VenueMultiplier}(f)$$

### 2.1 Base Productivity ($\text{BaseXP}$)

A player's baseline productivity per match is estimated using their price tier as a prior, blended with observed historical form once matches are completed.

1. **Price Prior ($P_{\text{prior}}$):**
   In Fantasy Premier League, pricing is an efficient proxy for expected points potential over the season.
   - Base floor at £4.0m is set at $1.5$ points/match.
   - Each £1.0m increase above £4.0m adds $0.65$ points/match.
   $$P_{\text{prior}} = 1.5 + \max(0, \text{Price}_{\text{millions}} - 4.0) \times 0.65$$
   
   *Representative baseline values:*
   - £4.0m budget enabler: $1.50$ pts
   - £4.5m regular starter: $1.83$ pts
   - £6.0m mid-tier asset: $2.80$ pts
   - £8.0m upper asset: $4.10$ pts
   - £10.0m premium: $5.40$ pts
   - £15.0m super-premium (e.g. Haaland): $8.65$ pts

2. **Observed Form Blending (Bayesian Shrinkage):**
   When the season is underway ($\text{finished matches} > 0$ and $\text{total points} > 0$):
   $$\text{ObservedPPG} = \frac{\text{total\_points}}{\text{finished\_matches}}$$
   $$\text{weight} = \min\left(0.80, \frac{\text{finished\_matches}}{10}\right)$$
   $$\text{BaseXP} = \text{weight} \times \text{ObservedPPG} + (1 - \text{weight}) \times P_{\text{prior}}$$

### 2.2 Availability Discount ($\text{Availability}$)

Player availability probability is derived deterministically from the official FPL status code:

| Status Code | Description | Multiplier |
|---|---|---|
| `a` | Available / Active | $1.00$ ($100\%$) |
| `d` | Doubtful / Flagged (75% / 50% chance) | $0.75$ ($75\%$) |
| `i` | Injured | $0.00$ ($0\%$) |
| `s` | Suspended | $0.00$ ($0\%$) |
| `u` | Unavailable / Left league | $0.00$ ($0\%$) |

### 2.3 Fixture Difficulty Multiplier ($\text{FDRMultiplier}$)

FPL assigns an official Fixture Difficulty Rating ($FDR$) from 1 (easiest) to 5 (hardest), where 3 is neutral.
Different positions possess distinct sensitivities to fixture difficulty:
- **Goalkeepers and Defenders:** Clean sheet probability is heavily dictated by opponent strength.
  $$\text{FDRMultiplier}_{\text{DEF/GKP}} = 1.0 + (3 - \text{FDR}) \times 0.15$$
  *(FDR 1: $1.30\times$, FDR 2: $1.15\times$, FDR 3: $1.00\times$, FDR 4: $0.85\times$, FDR 5: $0.70\times$)*
- **Midfielders and Forwards:** Attacking assets have opportunities against both weak and strong defenses.
  $$\text{FDRMultiplier}_{\text{MID/FWD}} = 1.0 + (3 - \text{FDR}) \times 0.10$$
  *(FDR 1: $1.20\times$, FDR 2: $1.10\times$, FDR 3: $1.00\times$, FDR 4: $0.90\times$, FDR 5: $0.80\times$)*

### 2.4 Venue Multiplier ($\text{VenueMultiplier}$)

Reflects historical Premier League home advantage:
- **Home ($H$):** $1.06$ ($+6\%$ expected returns)
- **Away ($A$):** $0.94$ ($-6\%$ expected returns)

---

## 3. Gameweek Aggregation

For any gameweek $GW$:
- **Blank Gameweek (0 fixtures):** $xP = 0.0$
- **Single Gameweek (1 fixture):** $xP = xP(p, f_1)$
- **Double Gameweek (2 fixtures):** $xP = xP(p, f_1) + xP(p, f_2)$

---

## 4. Downstream Applications in V0.2

1. **Starting XI Selection ([`src/fpl_manager/lineup.py`](../src/fpl_manager/lineup.py)):**
   Identifies the legal formation (e.g. 3-5-2, 3-4-3, 4-4-2) that maximizes total starting expected points.
2. **Captaincy Selection:**
   Designates the highest projected starter as primary Captain ($2\times$ multiplier) and second-highest as Vice-Captain.
3. **Optimal Bench Ordering:**
   Orders outfield substitutes strictly by expected points (Sub 1, Sub 2, Sub 3) to optimize automatic substitutions when starters miss out.
4. **Transfer Candidate Recommendations ([`src/fpl_manager/suggest_transfers.py`](../src/fpl_manager/suggest_transfers.py)):**
   Filters transfer candidates by multi-gameweek projected $xP$ and ranks legal 1-, 2-, and 3-transfer combinations by net expected points gain ($\Delta xP - \text{Transfer Hits}$).

---

## 5. Planned Expansions for V0.3

- **Minutes Projection ($xM$):** Explicit modeling of expected minutes (starts vs. substitute appearances).
- **Underlying Stats Integration:** Incorporating Expected Goals ($xG$) and Expected Assists ($xA$) from FPL/Opta feeds.
- **Uncertainty & Variance:** Quantifying upside vs. floor to distinguish steady starters from high-ceiling differentials.
