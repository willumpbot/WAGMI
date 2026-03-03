# /model-route-tune — Optimize Haiku/Sonnet/Opus Routing

## Description
Analyze model routing effectiveness and optimize which Claude model (Haiku/Sonnet/Opus) is used for each agent and trigger type. Balances cost, accuracy, and latency.

## Arguments
- `$ARGUMENTS` — Optional: "cost-focus" (minimize spend), "accuracy-focus" (maximize correctness), "balanced" (default), or specific agent ("regime", "trade")

## Workflow

### 1. Current Routing Configuration
Read `bot/llm/usage_tiers.py` and extract current routing:

```
CURRENT MODEL ROUTING
━━━━━━━━━━━━━━━━━━━━━
Tier: <CURRENT_TIER> (from LLM_USAGE_TIER env)

Agent         Default Model   Override (env)   Cost/Call
Regime        Haiku           —                $0.0001
Trade         Sonnet          —                $0.003
Risk          Haiku           —                $0.0001
Critic        Sonnet          —                $0.003
Learning      Haiku           —                $0.0001

Trigger Routing (AGGRESSIVE+ tier):
  HIGH_VALUE:   PRE_TRADE, REGIME_SHIFT → Opus ($0.015)
  MEDIUM:       POSITION_CLOSED, HIGH_CONF → Sonnet ($0.003)
  LOW:          PERIODIC, MEMORY_EVENT → Haiku ($0.0001)

Budget: $<DAILY_BUDGET>/day (from LLM_DAILY_BUDGET_USD)
Auto-downgrade: at 70% soft limit, 90% hard limit
```

### 2. Performance by Model
Read `bot/data/llm/decisions.jsonl` and correlate model used with outcome:

```
MODEL PERFORMANCE
━━━━━━━━━━━━━━━━━
Model    Decisions   Win Rate   Avg Conf   Calibration   Avg Latency
Haiku    N           XX%        X.XX       ±X.X%         XXXms
Sonnet   N           XX%        X.XX       ±X.X%         XXXms
Opus     N           XX%        X.XX       ±X.X%         X,XXXms
```

Key questions:
- Does Opus actually produce better decisions than Sonnet?
- Does Sonnet outperform Haiku for the agents currently using Haiku?
- Is the latency difference significant for trading speed?

### 3. Per-Agent Model Analysis
For each agent, evaluate if the current model is optimal:

**Regime Agent (currently Haiku):**
- Regime classification accuracy with Haiku: XX%
- Does the task complexity warrant Sonnet? (regime classification is relatively simple)
- Are there edge cases where Haiku gets confused? (complex multi-regime scenarios)
- Recommendation: [keep Haiku / upgrade to Sonnet for specific triggers]

**Trade Agent (currently Sonnet):**
- Trade decision accuracy with Sonnet: XX%
- Would Opus improve accuracy? (this is the main decision-maker)
- Cost impact of upgrading to Opus: +$X.XX/decision
- Is the extra accuracy worth the cost?
- Recommendation: [keep Sonnet / upgrade to Opus for high-value / downgrade to Haiku for low-value]

**Risk Agent (currently Haiku):**
- Sizing quality with Haiku: XX% appropriate
- Are risk flags being caught? (compare with actual risk events)
- Is sizing systematically biased? (always too high/low)
- Recommendation: [keep Haiku / upgrade for complex portfolio states]

**Critic Agent (currently Sonnet):**
- Veto accuracy with Sonnet: XX%
- Would Haiku be sufficient? (Critic sees structured agent outputs, not raw data)
- Would Opus improve veto quality?
- Recommendation: [keep Sonnet / test Haiku / upgrade to Opus]

**Learning Agent (currently Haiku):**
- Lesson quality assessment
- Are lessons actionable or generic?
- Would Sonnet produce more nuanced lessons?
- Recommendation: [keep Haiku / try Sonnet for important trades]

### 4. Per-Trigger Model Analysis
For each trigger type, evaluate ROI:

```
TRIGGER ROI ANALYSIS
━━━━━━━━━━━━━━━━━━━━
Trigger             Current Model  Calls  Cost    Value   ROI
PRE_TRADE           Sonnet/Opus    N      $XX     $XXX    X.Xx
REGIME_SHIFT        Sonnet/Opus    N      $XX     $XXX    X.Xx
POSITION_CLOSED     Sonnet         N      $XX     $XXX    X.Xx
HIGH_CONFIDENCE     Sonnet         N      $XX     $XXX    X.Xx
PERIODIC            Haiku          N      $X      $XX     X.Xx
MEMORY_EVENT        Haiku          N      $X      $XX     X.Xx
STRATEGY_DISAGREE   Sonnet         N      $XX     $XXX    X.Xx
```

Identify:
- High ROI triggers → may warrant model upgrade
- Negative ROI triggers → downgrade or skip entirely
- Redundant triggers → combine or eliminate

### 5. Cost-Downgrade Impact
Read `bot/llm/cost_tracker.py` — analyze downgrade events:
- How often does auto-downgrade activate?
- What's the decision quality during downgraded periods?
- Is the soft limit (70%) too aggressive or too conservative?
- Are HIGH_VALUE triggers properly protected from downgrade?

### 6. Token Efficiency
For each agent:
- Average input tokens vs max_tokens budget
- Average output tokens vs max_tokens
- Truncation rate (hitting max_tokens)
- Token waste (max_tokens >> actual output)

```
TOKEN EFFICIENCY
━━━━━━━━━━━━━━━━
Agent     Max Tokens  Avg Input  Avg Output  Utilization  Truncated
Regime    512         XXX        XXX         XX%          X%
Trade     1024        XXX        XXX         XX%          X%
Risk      512         XXX        XXX         XX%          X%
Critic    768         XXX        XXX         XX%          X%
Learning  512         XXX        XXX         XX%          X%
```

Recommendations:
- Reduce max_tokens for underutilized agents (saves money)
- Increase max_tokens for agents hitting truncation (prevents bad output)

### 7. Optimization Proposals

**Cost-Focused:**
- Downgrade agents where cheaper model performs equally well
- Reduce max_tokens for under-utilizing agents
- Skip low-ROI trigger types entirely
- Tighten trigger cooldowns to reduce call frequency

**Accuracy-Focused:**
- Upgrade Trade Agent to Opus for PRE_TRADE triggers
- Upgrade Critic to Opus for high-value decisions
- Increase max_tokens to prevent truncation
- Add ensemble mode for critical decisions

**Balanced (default):**
- Keep current routing with specific adjustments
- Targeted upgrades only where ROI > 2x
- Targeted downgrades only where quality is preserved

### 8. A/B Test Plan
For each proposed routing change:
- Estimated cost impact ($/month)
- Expected accuracy impact (%)
- Suggested test: run X decisions with new routing, compare
- Minimum sample size for statistical significance

### 9. Apply Changes (with confirmation)
If user approves:
- Update `.env` with model overrides: `AGENT_<ROLE>_MODEL=<model>`
- Update `bot/llm/usage_tiers.py` trigger routing if needed
- Adjust `bot/llm/agents/base.py` max_tokens if needed
- Run: `cd bot && pytest tests/ -k "agent" -v`

### 10. Report
```
MODEL ROUTING OPTIMIZATION — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CURRENT COST: ~$X.XX/day ($XX/month)

PROPOSED CHANGES:
  Regime Agent: Haiku → Haiku (no change)
  Trade Agent: Sonnet → Opus for PRE_TRADE only (+$X.XX/day)
  Risk Agent: Haiku → Haiku (reduce max_tokens 512→384)
  Critic Agent: Sonnet → Haiku for low-conf decisions (-$X.XX/day)
  Learning Agent: Haiku → Sonnet for loss trades (+$X.XX/day)

PROJECTED COST: ~$X.XX/day ($XX/month)
PROJECTED ACCURACY: +X.X% win rate improvement
NET ROI: $X.XX saved per $1 spent on model upgrades

TOKEN OPTIMIZATIONS:
  Total tokens saved/decision: ~XXX
  Truncation reduction: X% → X%
```
