# /cost-audit — LLM Cost Tracking and Optimization

## Description
Audit LLM API spending, identify waste, and optimize model routing for cost efficiency without sacrificing decision quality.

## Arguments
- `$ARGUMENTS` — Optional: time range ("today", "7d", "30d") or "breakdown"

## Workflow

### 1. Gather Cost Data
- Read `bot/llm/cost_tracker.py` — extract spending records
- Read `bot/data/llm/decisions.jsonl` — count decisions and model usage
- Read `bot/llm/usage_tiers.py` — current routing rules

### 2. Spending Summary
Calculate totals by time period:
```
LLM COST AUDIT — <date range>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Period    Calls  Tokens(in)  Tokens(out)  Cost
Today     XX     XXX,XXX     XX,XXX       $X.XX
7d        XXX    X,XXX,XXX   XXX,XXX      $XX.XX
30d       XXXX   XX,XXX,XXX  X,XXX,XXX    $XXX.XX
```

### 3. Cost by Model
Break down by model tier:
```
MODEL BREAKDOWN
━━━━━━━━━━━━━━
Model    Calls   Avg Tokens   Cost     % of Total
Haiku    XXX     ~500         $X.XX    XX%
Sonnet   XXX     ~1,200       $XX.XX   XX%
Opus     XX      ~2,000       $XX.XX   XX%
```

### 4. Cost by Agent (if multi-agent)
Per-agent spending:
```
AGENT COSTS
━━━━━━━━━━━
Agent     Model    Calls   Cost/Call   Total    Value*
Regime    Haiku    XXX     $0.0001     $X.XX    HIGH
Trade     Sonnet   XXX     $0.003      $XX.XX   MEDIUM
Risk      Haiku    XXX     $0.0001     $X.XX    HIGH
Critic    Sonnet   XXX     $0.003      $XX.XX   MEDIUM
Learning  Haiku    XX      $0.0001     $X.XX    HIGH

* Value = cost vs benefit (did this agent's decisions make/save money?)
```

### 5. Cost by Trigger
Break down by what triggered the LLM call:
```
TRIGGER COSTS
━━━━━━━━━━━━━
Trigger         Model    Calls   Cost     EV/Call
PRE_TRADE       Sonnet   XXX     $XX.XX   +$X.XX
REGIME_SHIFT    Opus     XX      $XX.XX   +$X.XX
POSITION_CLOSED Sonnet   XXX     $XX.XX   +$X.XX
PERIODIC        Haiku    XXX     $X.XX    -$X.XX   ← waste?
MEMORY_EVENT    Haiku    XX      $X.XX    +$X.XX
```

### 6. Waste Detection
Flag potentially wasteful spending:
- **Low-value triggers on expensive models**: PERIODIC using Sonnet instead of Haiku
- **Redundant calls**: Same decision within 5 minutes
- **Truncated responses**: Agent hitting max_tokens (paying for incomplete output)
- **Overridden decisions**: LLM said "go" but signal pipeline rejected anyway (wasted call)
- **Learning Agent calls with no new information**: Closed trade was too similar to previous

### 7. Optimization Recommendations
Based on findings:

**Tier 1 (Free — just config changes):**
- Downgrade specific triggers to cheaper models
- Increase minimum interval between PERIODIC calls
- Skip LLM call when ensemble confidence is very high (>90%) or very low (<30%)
- Reduce max_tokens for agents that consistently use <50% of budget

**Tier 2 (Code changes):**
- Cache regime classification (don't re-classify if data hasn't changed much)
- Batch multiple symbols into single LLM call where possible
- Short-circuit pipeline: if Regime says "unknown", skip Trade/Risk/Critic

**Tier 3 (Architectural):**
- Move more decisions to rule-based (no LLM) when patterns are clear
- Train a small local model for regime classification (replace Haiku calls)

### 8. Projected Savings
```
OPTIMIZATION IMPACT
━━━━━━━━━━━━━━━━━━━
Change                          Monthly Savings   Quality Impact
Downgrade PERIODIC to Haiku     -$XX/mo           None
Skip LLM on extreme confidence  -$XX/mo           Minimal
Cache regime for 5min           -$XX/mo           None
Total potential savings:         -$XX/mo (XX% reduction)
```
