# Expected Points (xP) and Minutes (xM) Model

> **Status:** Active in V0.3. Updated on 2026-09-04.
> **Source Module:** [`src/fpl_manager/expected_points.py`](../src/fpl_manager/expected_points.py)

---

## 1. Purpose and Principles

In accordance with [`docs/architecture.md`](architecture.md), FPL Manager separates deterministic facts, quantitative models, and human/LLM analysis:

```
Official FPL Snapshot -> Quantitative Projection (xM, xP, Uncertainty) -> Legal Optimizer -> Reports
```

The expected-points ($xP$) model provides a transparent, verifiable, and deterministic expectation of points scored by a player in an upcoming fixture or gameweek.

### Core Design Rules
- **No Black-Box Magic:** Every projection can be inspected, traced, and mathematically reproduced from official snapshot data.
- **Independence from LLMs:** Projections do not rely on LLM prompts or unstructured news text.
- **Rule Safety First:** Projections guide selection, but all squad compositions and starting lineups must pass the independent validator in [`src/fpl_manager/rules.py`](../src/fpl_manager/rules.py).

---

## 2. Mathematical Formulation

### 2.1 Availability Model ($\text{Availability}$)

Player availability probability ($A_{\text{prob}} \in [0.0, 1.0]$) is derived deterministically from the official FPL status and explicit round chance flags:

1. If `chance_of_playing_next_round` is present:
   $$A_{\text{prob}} = \frac{\text{chance\_of\_playing\_next\_round}}{100.0}$$
2. Otherwise, from official status code:
   - `a` (Available): $1.00$ ($100\%$)
   - `d` (Doubtful): $0.75$ ($75\%$)
   - `i`, `s`, `u` (Injured/Suspended/Unavailable): $0.00$ ($0\%$)

### 2.2 Expected Minutes Model ($xM$)

Expected minutes played per match fixture accounts for squad role, start likelihood, and availability:

1. **Price/Position Prior:**
   - Goalkeepers: $\ge £4.5\text{m} \implies P(\text{start}) = 0.95$, $M_{\text{start}} = 90.0$; $< £4.5\text{m} \implies P(\text{start}) = 0.05$, $M_{\text{start}} = 10.0$.
   - Outfield:
     - Premium ($\ge £8.0\text{m}$): Prior $P(\text{start}) = 0.92$, $M_{\text{start}} = 85.0$
     - Mid-tier ($£6.0\text{m} - £7.9\text{m}$): Prior $P(\text{start}) = 0.82$, $M_{\text{start}} = 78.0$
     - Rotation ($£5.0\text{m} - £5.9\text{m}$): Prior $P(\text{start}) = 0.65$, $M_{\text{start}} = 68.0$
     - Budget ($£4.5\text{m}$): Prior $P(\text{start}) = 0.50$, $M_{\text{start}} = 55.0$
     - Enabler ($£4.0\text{m}$): Prior $P(\text{start}) = 0.15$, $M_{\text{start}} = 25.0$
2. **Bayesian Shrinkage on Observed Starts:**
   When finished matches $N > 0$:
   $$w = \min\left(0.85, \frac{N}{6}\right)$$
   $$P_{\text{start\_fit}} = w \times \left(\frac{\text{starts}}{N}\right) + (1 - w) \times \text{prior\_start}$$
   $$M_{\text{start\_fit}} = w \times \left(\frac{\text{minutes}}{\text{starts}}\right) + (1 - w) \times \text{prior\_mins}$$
3. **Availability & Expected Minutes:**
   $$P(\text{start}) = P_{\text{start\_fit}} \times A_{\text{prob}}$$
   $$P(\text{sub}) = P_{\text{sub\_fit}} \times A_{\text{prob}}$$
   $$xM = \min(90.0, P(\text{start}) \times M_{\text{start\_fit}} + P(\text{sub}) \times 20.0)$$
   $$P(\ge 60) = P(\text{start}) \times (0.95 \text{ if } M_{\text{start\_fit}} \ge 60 \text{ else } 0.35)$$

### 2.3 Component-Based Expected Points ($xP_{\text{comp}}$)

For a fixture $f$ with fixture difficulty rating $\text{FDR} \in [1, 5]$ and venue multiplier $V \in \{1.06 \text{ (H)}, 0.94 \text{ (A)}\}$:

$$xP_{\text{comp}} = \max(0.0, xP_{\text{appearance}} + xP_{\text{attack}} + xP_{\text{defense}} + xP_{\text{bonus}} - xP_{\text{deduction}})$$

1. **Appearance Points:**
   $$xP_{\text{appearance}} = 2.0 \times P(\ge 60) + 1.0 \times P(1..59)$$
2. **Attacking Threat (Opta $xG$ & $xA$):**
   Using official $xG_{90}$ and $xA_{90}$ blended with position/price priors:
   $$xG_f = xG_{90} \times \left(\frac{xM}{90}\right) \times [1.0 + (3 - \text{FDR}) \times 0.10] \times V$$
   $$xA_f = xA_{90} \times \left(\frac{xM}{90}\right) \times [1.0 + (3 - \text{FDR}) \times 0.10] \times V$$
   $$xP_{\text{attack}} = xG_f \times \text{GoalPoints}(\text{pos}) + xA_f \times 3.0$$
   *(Goal points: GKP/DEF = 6, MID = 5, FWD = 4; Assists = 3)*
3. **Defensive Points & Clean Sheets:**
   Clean sheet probability:
   $$P(\text{CS}) = \text{clamp}\Big(0.32 \times [1.0 + (3 - \text{FDR}) \times 0.15] \times [1.15 \text{ (H)} / 0.85 \text{ (A)}], 0.05, 0.65\Big)$$
   - GKP & DEF: $xP_{\text{CS}} = 4.0 \times P(\text{CS}) \times P(\ge 60)$
     - Goals conceded penalty: $-0.5 \times \max(0, xGC_f - 0.5) \times P(\ge 60)$
   - MID: $xP_{\text{CS}} = 1.0 \times P(\text{CS}) \times P(\ge 60)$
   - FWD: $xP_{\text{defense}} = 0.0$
4. **Bonus Points:**
   $$xP_{\text{bonus}} = \min(1.8, 0.35 \times xP_{\text{attack}} + [0.25 \text{ if } P(\text{CS}) > 0.35 \text{ and } \text{pos} \le 2])$$
5. **Disciplinary Deductions:**
   $$xP_{\text{deduction}} = 0.15 \times \left(\frac{xM}{90}\right)$$

### 2.4 Baseline Blend

To maintain stability across low-sample regimes (early season or brand-new transfers), the component model is blended with the price-tier baseline prior:
$$xP_{\text{final}} = 0.70 \times xP_{\text{comp}} + 0.30 \times xP_{\text{baseline}}$$

### 2.5 Uncertainty Quantification (Floor & Ceiling)

1. **Floor ($xP_{\text{floor}}$, 10th percentile):**
   The guaranteed/floor expectation when a player plays without an attacking return or clean sheet:
   $$xP_{\text{floor}} = \begin{cases} \max(0.0, xP_{\text{appearance}} - xP_{\text{deduction}}) & \text{if } P(\ge 60) \ge 0.50 \\ 0.0 & \text{otherwise} \end{cases}$$
2. **Ceiling ($xP_{\text{ceiling}}$, 90th percentile):**
   Captures upside/haul potential for captaincy and differential evaluation:
   $$\sigma_{\text{attack}} = 1.3 \times xP_{\text{attack}} + 0.8$$
   $$\sigma_{\text{defense}} = \sqrt{P(\text{CS}) \times (1 - P(\text{CS})) \times 16} \times P(\ge 60) \quad (\text{DEF/GKP})$$
   $$\sigma_{\text{total}} = \sqrt{\sigma_{\text{attack}}^2 + \sigma_{\text{defense}}^2} \times \left(\frac{xM}{90}\right)$$
   $$xP_{\text{ceiling}} = xP_{\text{final}} + 1.645 \times \sigma_{\text{total}}$$

---

## 3. Gameweek & Multi-Gameweek Aggregation

For any gameweek $GW$:
- **Blank Gameweek (0 fixtures):** $xP = 0.0, xM = 0.0, \text{Floor} = 0.0, \text{Ceiling} = 0.0$
- **Single Gameweek (1 fixture):** $xP = xP(p, f_1)$
- **Double Gameweek (2 fixtures):** $xP = xP(p, f_1) + xP(p, f_2)$

Across multi-gameweek horizons ($GW_1 \dots GW_H$ via `project_multi_gameweek_profiles`):
$$\text{Total } xP = \sum_{GW} xP_{GW}, \quad \text{Total Floor} = \sum_{GW} \text{Floor}_{GW}, \quad \sigma_{\text{multi}} = \sqrt{\sum_{GW} \sigma_{GW}^2}$$

---

## 4. Downstream Applications in V0.3

1. **Starting XI Selection ([`src/fpl_manager/lineup.py`](../src/fpl_manager/lineup.py)):**
   Optimizes legal formations and outputs floor and ceiling intervals for the starting team.
2. **Captaincy Selection:**
   Evaluates expected points and ceiling haul potential for armband designation.
3. **Transfer Search & Strategic Optimization:**
   Feeds expected minutes, uncertainty, and multi-week projections into the transfer and wildcard solver.

