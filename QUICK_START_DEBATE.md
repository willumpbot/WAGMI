# Quick Start: Interactive Debate System

## Enable Interactive Debate

```bash
# Set environment variable
export LLM_INTERACTIVE_DEBATE=true

# Run paper trading (debates will now run)
cd bot && python run.py paper
```

## Configuration Options

```bash
# Basic: Enable interactive debate
export LLM_INTERACTIVE_DEBATE=true

# Advanced: Use stronger Critic model
export LLM_INTERACTIVE_DEBATE=true
export AGENT_CRITIC_MODEL=claude-opus-4-6

# Advanced: Use specific Critic and Trade models
export LLM_INTERACTIVE_DEBATE=true
export AGENT_CRITIC_MODEL=claude-opus-4-6
export AGENT_TRADE_MODEL=claude-sonnet-4-6

# Monitor: Enable debug logging
export LOG_LEVEL=DEBUG
```

## How It Works

### Simple Example

**Trade Agent proposes:**
```
Action: BUY SOL
Thesis: "SOL bullish due to 4/4 regime alignment, BTC confirming"
Confidence: 75%
```

**Critic evaluates** (WITHOUT seeing 75% confidence):
```
Verdict: CHALLENGE
Counter-thesis: "SOL likely to consolidate, not break up"
Objections:
  1. BTC rejected at resistance (80% likely to matter)
     Impact: Invalidates thesis
  2. Funding rate too high (70% likely)
     Impact: Position too large
  3. Setup historically loses 65% (90% likely)
     Impact: Poor risk/reward
```

**Trade Agent responds:**
```
Concessions: "You're right about setup history and BTC weakness"
Adjusted Confidence: 25% (down from 75%)
Action: SKIP
```

**Debate Resolution:**
```
Critic Wins (critic_score 0.80 > trade_score 0.40 + 0.2)
Final Action: SKIP
Final Confidence: 10%
```

## Monitor Debate Outcomes

### Live Logging
```bash
# Watch debate decisions in real-time
cd bot
python run.py paper 2>&1 | grep "INTERACTIVE_DEBATE"

# Example output:
# [INTERACTIVE_DEBATE] winner=trade trade_score=0.78 critic_score=0.32 final_action=go final_conf=0.75
# [INTERACTIVE_DEBATE] winner=critic trade_score=0.35 critic_score=0.82 final_action=skip final_conf=0.15
# [INTERACTIVE_DEBATE] winner=consensus trade_score=0.55 critic_score=0.52 final_action=go final_conf=0.65
```

### Debate Telemetry File
```bash
# Structured debate outcomes (JSON lines)
tail -f bot/data/llm/debate_telemetry.jsonl

# Example lines:
{
  "ts": 1711000000.5,
  "symbol": "SOL/USD",
  "trade_score": 0.75,
  "critic_score": 0.35,
  "winner": "trade",
  "final_action": "go",
  "final_confidence": 0.78,
  "trade_maintained_thesis": true,
  "critic_concessions": 0
}
```

## Understanding Debate Winners

| Winner | Meaning | Confidence Adjustment |
|--------|---------|----------------------|
| **Trade** | Trade thesis held up well | ±0.05 (slight boost) |
| **Critic** | Critic's objections valid | -0.15 (reduction) |
| **Consensus** | Both had good points | -0.05 (slight discount) |

## Real-World Scenario: When Debate Helps Most

### Scenario 1: Trade Overconfident
```
Trade says: "Go with 85% confidence" (maybe overconfident)
Critic sees thesis WITHOUT confidence
Critic: "Multiple red flags, counter-thesis stronger"
Result: Trade reluctantly reduced to 40%, decision quality improves
```

### Scenario 2: Critic Correctly Identifies Edge Case
```
Trade says: "Proceed, 70% confidence"
Critic finds: "This specific setup has 35% WR historically"
Result: Trade concedes, action becomes SKIP, avoids bad trade
```

### Scenario 3: Consensus on Uncertainty
```
Trade says: "Go, but maybe hold off" (conflicted, 55% confidence)
Critic says: "I agree there's conflict here" (counter-thesis weak)
Result: Consensus outcome, both sides moderate confidence
```

## API Usage (if programmatically calling)

```python
from bot.llm.agents.interactive_debate import (
    InteractiveDebater,
    ThesisProposal,
    CounterThesis,
    Rebuttal,
)

# 1. Create debater
debater = InteractiveDebater()

# 2. Extract Trade Agent's proposal
trade_output = {"a": "go", "c": 0.75, "thesis": "SOL bullish"}
proposal = debater.round1_extract_proposal(trade_output)

# 3. Extract Critic's response
critic_output = {"verdict": "challenge", "counter_thesis": "SOL sideways"}
counter = debater.round1_extract_counter_thesis(critic_output)

# 4. Create rebuttal (manual or from LLM)
rebuttal = Rebuttal(
    action="go",
    adjusted_confidence=0.65,
    maintains_thesis=True,
    rebuttal_points=["BTC weakness temporary"],
    concessions=[]
)

# 5. Score debate
resolution = debater.score_debate(proposal, counter, rebuttal)

# 6. Use results
print(f"Final decision: {resolution.final_action}")
print(f"Final confidence: {resolution.final_confidence:.0%}")
print(f"Winner: {resolution.debate_winner}")
```

## Disabling Interactive Debate

```bash
# Disable (use post-hoc debate synthesis instead)
unset LLM_INTERACTIVE_DEBATE
# or explicitly set to false
export LLM_INTERACTIVE_DEBATE=false

# Verify
echo $LLM_INTERACTIVE_DEBATE  # should be empty or "false"
cd bot && python run.py paper
```

## Troubleshooting

### Debate Not Running
```bash
# Check if enabled
echo $LLM_INTERACTIVE_DEBATE  # should be "true"

# Check logs
cd bot && python run.py paper 2>&1 | grep -i debate

# Should see output like:
# [INTERACTIVE_DEBATE] winner=...
```

### Critic Not Being Called
```bash
# Make sure Critic Agent is enabled
export AGENT_CRITIC_ENABLED=true  # default is true

# Check Critic model
export AGENT_CRITIC_MODEL=claude-sonnet-4-6  # override if needed
```

### Debate Seems to Have No Effect
```bash
# Check confidence values in output
# In debate, confidence can change significantly:
# Original: 75%, After debate: 25%

# Check trade results
# Debate should improve decision quality over time:
# More wins when Trade wins debate
# Fewer losses when Critic wins debate
```

## Performance Tips

### Save Tokens (Reduce Debate Frequency)
```bash
# Only run debate for high-confidence decisions
# Modify prompt to skip debate if confidence < 0.5
export LLM_INTERACTIVE_DEBATE=true
export LLM_MODE=2  # VETO_ONLY - Critic can only block, reduces pipeline
```

### Use Cheaper Critic Model
```bash
# Use Haiku for less rigorous debate (faster, cheaper)
export AGENT_CRITIC_MODEL=claude-haiku-4-5-20251001

# Use Opus only for high-value decisions (slower, more accurate)
export AGENT_CRITIC_MODEL=claude-opus-4-6
```

### Monitor Cost
```bash
# Check token usage
tail -f bot/data/llm/llm_usage.jsonl | grep -i critic

# Estimate cost per debate:
# ~200 tokens average
# Haiku: ~$0.20 per 1000 tokens = $0.00004 per debate
# Sonnet: ~$3 per 1000 tokens = $0.0006 per debate
# Opus: ~$15 per 1000 tokens = $0.003 per debate
```

## Measuring Improvement

Track these metrics to measure if debate helps:

```bash
# 1. Win rate on debated decisions
# Count wins where winner="trade" → should be higher
# Count wins where winner="critic" → should have fewer losses

# 2. Confidence accuracy (Brier score)
# For decisions where Trade proposed 70% confidence
# What % actually won? Should match well after debate

# 3. Token efficiency
# Cost per trade: total_tokens / num_trades
# Should be similar or slightly better (fewer bad trades)

# 4. Sharpe ratio
# Total return / volatility
# Should improve with better decision quality
```

## Further Reading

- `DEBATE_IMPLEMENTATION.md` — Full technical documentation
- `SESSION_SUMMARY.md` — Context and implementation details
- Research papers referenced in DEBATE_IMPLEMENTATION.md

---

**Status**: Ready for use. Debate system is opt-in and disabled by default. Enable with `export LLM_INTERACTIVE_DEBATE=true`.
