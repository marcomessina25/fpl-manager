# V0.7 LLM A/B Historical Evaluation & Experiment Controls

## 1. Objective & Hypothesis

The central question governing the LLM layer in V0.7 is:

> **"Does an LLM qualitative advisor add measurable value after deterministic combinatorial optimization?"**

To evaluate this rigorously, the LLM is treated as an **incremental component** rather than an uncontrolled oracle. The deterministic optimizer provides the mathematical baseline, and the LLM is allowed to review, approve, or suggest overrides.

---

## 2. Experimental Setup & Controls

For every historical decision point (Gameweek $N$), the experimental framework records:
1. **Decision Context:**
   - Pre-deadline point-in-time snapshot.
   - Squad state, bank, available free transfers.
   - Production branch-and-bound optimizer recommendation.
2. **LLM Provider Metadata:**
   - Provider name (e.g. `openrouter`, `gemini`, `openai`, `heuristic`).
   - Model identifier (e.g. `meta-llama/llama-3.3-70b-instruct`, `deepseek/deepseek-chat`, `gpt-4o-mini`).
   - Prompt version (e.g. `v0.7-tactical-v1`).
   - Temperature setting.
3. **Execution & Validation Record:**
   - Raw response text.
   - Parsed structured recommendations (transfers, captaincy).
   - Override flag (`was_override: bool`).
   - Deterministic validation check (`is_valid: bool`).
   - Validation failure reasons (if invalid).
   - Final executed action (falls back to deterministic optimizer if invalid).

---

## 3. Strict Deterministic Validation Invariants

Any recommendation returned by an LLM must pass identical deterministic checks before execution:
- **Budget Integrity:** Resulting squad cost must not exceed available bank.
- **Club Limits:** Maximum 3 players from any single Premier League club.
- **Position Integrity:** Outgoing and incoming players must occupy the same position.
- **Squad Disjointness:** Incoming player cannot already be in the squad; outgoing player must be currently owned.

If any invariant fails:
1. An `invalid_recommendation` event is recorded.
2. The error message is logged to `LLMDecisionLogRecord.validation_error`.
3. The system rejects the LLM recommendation and **falls back safely to the deterministic optimizer proposal**.

---

## 4. Empirical Evaluation Protocol

Identical historical decision sequences are executed through:
- **Experiment 1 (Deterministic Baseline):**
  - Production Branch-and-Bound Optimizer (`OptimizerStrategy`).
  - Strict mathematical maximization of projected net $xP$.
- **Experiment 2 (LLM Advisory Track):**
  - Production Branch-and-Bound Optimizer proposal.
  - LLM qualitative evaluation with possible overrides (`LLMAdvisorStrategy`).
  - Deterministic validation layer enforcing rules.

### Performance Comparison Metrics
- **Net Points:** Final score minus transfer hits.
- **Gameweek Head-to-Head:** Win / Loss / Tie count across gameweeks.
- **Transfer Efficiency:** Points gained per transfer executed.
- **Override Frequency:** Percentage of gameweeks where the LLM intervened.
- **Invalid Output Rate:** Percentage of LLM proposals violating FPL rules.
- **Value Add / Degradation:** Net score difference ($\Delta = \text{Points}_{\text{LLM}} - \text{Points}_{\text{Opt}}$).
