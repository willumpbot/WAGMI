# /prompt-calibrate — Benchmark and Tune Agent Prompts

## Description
Systematically evaluate agent prompt effectiveness against historical decisions, identify weak spots, and tune prompts for better accuracy without breaking the pipeline contract.

## Arguments
- `$ARGUMENTS` — Optional: agent name ("regime", "trade", "risk", "critic", "learning") or "all"

## Workflow

### 1. Baseline Collection
Load historical agent decisions for the target agent(s):
- Read `bot/data/llm/decisions.jsonl` — extract per-agent outputs
- Read `bot/data/trades.csv` — correlate decisions with actual outcomes
- Need minimum 20 decisions per agent for meaningful analysis

For each agent, compute baseline metrics:
- **Accuracy**: How often was the agent's prediction correct?
  - Regime Agent: classified regime vs what price actually did
  - Trade Agent: go/skip/flip vs actual profitable direction
  - Risk Agent: sizing appropriateness vs actual PnL magnitude
  - Critic Agent: approve/veto accuracy (read `bot/data/llm/growth/veto_tracker.json`)
  - Learning Agent: lesson relevance (are extracted lessons being used?)

### 2. Prompt Analysis
Read the current prompt from `bot/llm/agents/prompts.py`:

**Structure Check:**
- Does it follow OBSERVE → RECALL → REASON → DECIDE → JUSTIFY?
- Does it use shared vocabulary exactly? (regime names, action names, confidence scale)
- Is the JSON output schema clearly defined with examples?
- Are few-shot examples included? Are they representative?
- Is it within the max_tokens budget? (Check `bot/llm/agents/base.py` for limits)

**Content Check:**
- Does the prompt reference all available upstream data?
- Are edge cases handled? (missing data, conflicting signals, extreme volatility)
- Is the confidence scale calibrated? (does "80% confidence" mean the same thing to every agent?)
- Does it reference memory/history effectively?

### 3. Failure Pattern Analysis
For each incorrect decision:
- What data was available to the agent?
- What did the agent output?
- What would have been correct?
- Categorize the failure:
  - **Data blindness**: Relevant data was available but agent ignored it
  - **Prompt gap**: Scenario not covered in prompt instructions
  - **Calibration error**: Agent was overconfident or underconfident
  - **Context miss**: Missing memory context that would have helped
  - **Model limitation**: Haiku too weak for this complexity (needs Sonnet)
  - **Format error**: Output JSON didn't parse correctly

### 4. Calibration Analysis
Read `bot/data/feedback/confidence_state.json` for system-level calibration:
- Per confidence bin: predicted win rate vs actual win rate
- Per agent: is this agent's confidence systematically biased?

Build calibration curve per agent:
```
AGENT CALIBRATION: Trade Agent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Predicted Conf  Actual WR   Gap      Verdict
50-60%          45%         -8%      Slightly overconfident
60-70%          58%         -6%      Slightly overconfident
70-80%          71%         -3%      Well calibrated
80-90%          82%         +0%      Well calibrated
90-100%         78%         -14%     OVERCONFIDENT ⚠
```

### 5. Prompt Improvement Proposals
Based on failure patterns and calibration, propose specific changes:

For each proposal:
- **What to change**: Exact section of the prompt to modify
- **Why**: Which failure pattern this addresses (with data)
- **Expected impact**: How many past failures this would have fixed
- **Risk**: Could this change break downstream agents?
- **Verification**: How to test the change

**Types of improvements:**
- Add missing edge case handling
- Improve few-shot examples (replace with real historical examples)
- Add explicit calibration guidance ("80% means you'd bet 4:1")
- Strengthen data referencing ("you MUST cite the ATR value")
- Tighten JSON schema enforcement
- Adjust token budget if truncation detected

### 6. A/B Test Framework
For each proposed change:
1. Load 10 historical decision snapshots where the agent failed
2. Show the user the current prompt output vs what the improved prompt would say
3. Score: how many failures does the new prompt fix?
4. Check: does the new prompt break any previously correct decisions?

### 7. Apply Changes (with confirmation)
If user approves:
- Edit `bot/llm/agents/prompts.py` with the improved prompt
- Run agent tests: `cd bot && pytest tests/ -k "agent or multi_agent" -v`
- Verify downstream agents still parse the output correctly
- Commit: "tune: calibrate <agent> prompt based on N-decision analysis"

NEVER auto-apply prompt changes without user confirmation.

### 8. Report
```
PROMPT CALIBRATION REPORT — <agent>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Decisions Analyzed:  N
Accuracy (current):  XX%
Calibration Error:   ±X.X%

TOP FAILURE PATTERNS:
1. Data blindness (X cases) — ignoring ATR in volatile regimes
2. Overconfidence at 90%+ (X cases) — predicts wins but only 78% WR
3. Prompt gap (X cases) — no guidance for low-liquidity scenarios

PROPOSED CHANGES:
1. [Change description] — fixes ~X failures, risk: LOW
2. [Change description] — fixes ~X failures, risk: MEDIUM

ESTIMATED ACCURACY AFTER CHANGES: XX% (+X%)
```
