# /agent-debug — Trace and Debug Agent Decisions

## Description
Investigate why the multi-agent LLM pipeline made a specific decision. Traces the full agent chain, identifies inconsistencies, and pinpoints the failure point.

## Arguments
- `$ARGUMENTS` — Optional: symbol name, trade ID, or "last" for most recent decision

## Workflow

### 1. Locate the Decision
- If `$ARGUMENTS` contains a trade ID or symbol, search `bot/data/llm/decisions.jsonl` for matching entries
- If `$ARGUMENTS` is "last" or empty, read the last entry from `bot/data/llm/decisions.jsonl`
- Parse the decision JSON and extract the full agent chain

### 2. Trace Agent Pipeline
For each agent in the pipeline (Regime → Trade → Risk → Critic), extract and display:

**Regime Agent:**
- Input: What market data did it receive?
- Output: What regime did it classify? (must be one of: trend, range, panic, high_volatility, low_liquidity, news_dislocation, unknown)
- Confidence: How confident was it?
- Check: Does the regime match observable market conditions?

**Trade Agent:**
- Input: Did it receive Regime Agent's output correctly?
- Output: What action? (go/skip/flip) What direction? What confidence?
- Check: Is the action consistent with the declared regime?

**Risk Agent:**
- Input: Did it receive Trade Agent's output correctly?
- Output: What position size? What leverage? Any flags?
- Check: Does sizing respect circuit breakers? Is leverage within bounds?

**Critic Agent:**
- Input: Did it receive the full chain?
- Output: Approve or challenge/veto? What reasoning?
- Check: If it vetoed, was the veto justified? If it approved a bad trade, why?

### 3. Consistency Analysis
Run cross-agent checks:
- Read `bot/llm/agents/consistency_checker.py` to understand the consistency framework
- Check vocabulary alignment (regime names, action names match shared vocabulary)
- Check confidence calibration (is 80% confidence from Regime similar in meaning to 80% from Trade?)
- Check for contradictions (e.g., Regime says "panic" but Trade says "go long with high confidence")
- Verify the thought protocol was followed (OBSERVE → RECALL → REASON → DECIDE → JUSTIFY)

### 4. Memory Context Check
- Read `bot/data/llm/llm_memory.json` — what short-term memories were available?
- Read `bot/data/llm/deep_memory/` — what long-term patterns were relevant?
- Check: Did agents have access to relevant historical context?
- Check: Were any stale memories influencing decisions?

### 5. Cost & Model Check
- What model was used for each agent? (Check `bot/llm/usage_tiers.py` routing)
- Was the right tier used? (High-value trigger → should use Opus/Sonnet, not Haiku)
- Token usage: was any agent hitting max_tokens and getting truncated?

### 6. Root Cause Report
Categorize the issue:
- **Data Problem**: Agent received stale/incomplete data
- **Prompt Problem**: Agent prompt doesn't handle this scenario well
- **Consistency Problem**: Agents contradicted each other
- **Memory Problem**: Wrong/stale memories influenced decision
- **Model Problem**: Wrong model tier for the trigger importance
- **Merge Problem**: `coordinator.py:_merge_outputs()` didn't handle output correctly
- **Correct Decision**: The pipeline actually worked correctly

### 7. Fix Suggestions
Based on root cause:
- Propose specific prompt modifications (with exact file + line references)
- Suggest memory pruning if stale data was the issue
- Recommend model tier adjustments
- Identify any code changes needed in coordinator or merger logic
- Always reference the shared vocabulary and thought protocol constraints
