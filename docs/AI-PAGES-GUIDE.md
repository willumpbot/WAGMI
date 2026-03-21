# AI Info Pages Guide

**Complete walkthrough of the three flagship AI transparency pages.**

---

## Overview

WAGMI offers three interconnected dashboards that expose the AI system's internal reasoning:

1. **[AI Decisions](/ai-decisions)** — The Decision Theater
2. **[Agent Intelligence](/agent-intelligence)** — The Agent Brain Dashboard
3. **[LLM Audit](/llm-audit)** — Cost & Model Routing Analysis

Together, they tell the complete story of **how the bot thinks, decides, and learns**.

---

## Page 1: AI Decisions (The Decision Theater)

**URL**: `/ai-decisions`
**Purpose**: Real-time LLM decision transparency
**Audience**: Traders who want to see "why did the bot trade (or not trade)?"

### What You're Looking At

This page streams every LLM decision from the bot, showing:
- **Agent Pipeline Flow** — Visual representation of the 9-agent pipeline
- **Decision Feed** — Every decision with full reasoning
- **Veto Reason Keywords** — Word cloud of why decisions were blocked
- **Model Usage** — Which Claude model (Opus/Sonnet/Haiku) made each decision

### Key Sections

#### Agent Pipeline Flow (Visual)

```
Regime → Trade → Risk → Critic → [DECISION]
  ↓       ↓       ↓      ↓
  ✓       ✓       ✓      ✓
 72%     82%     78%    VETO
```

**What it shows**:
- Green circles = agent ran and agreed
- Orange circles = agent ran but flagged concerns
- Red circles = agent actively objected
- Confidence below each agent = how sure was that agent?

**Read it like this**:
- All agents present? = consensus decision
- Agent missing? = pipeline stopped there (usually means earlier agent said "skip" so later stages didn't run)
- Critic shows VETO? = trade was blocked despite Trade Agent saying "proceed"

#### Recent Decisions (The Feed)

Each entry shows:

```
Symbol: BTC
Action: GO → PROCEED (Trade Agent said yes)
Status: ✓ ALLOWED (All gates passed)

Regime: trend | Confidence: 0.82
Model: claude-sonnet-4 | Cost: $0.003

Trigger: PRE_TRADE
Mode: DIRECTION (LLM can suggest direction)
Will Trade: YES ✓

Full Notes:
  OBSERVE: Price broken above 6h resistance...
  RECALL: Similar breakout happened 3 days ago...
  REASON: Strong uptrend continuation likely...
  DECIDE: BUY with confidence 0.82
  JUSTIFY: Multiple factors aligned (trend + volume + momentum)
```

**How to read**:
- **Symbol**: Which trading pair?
- **Action**: What did Trade Agent recommend? (proceed/skip/flip)
- **Status**: Did the decision pass all gates? (ALLOWED/BLOCKED/VETOED)
- **Regime**: Market condition (trend/range/panic/etc.)
- **Confidence**: Trade Agent's confidence (0-1)
- **Model**: Which Claude model made the decision?
- **Trigger**: What triggered this decision? (PRE_TRADE/REGIME_SHIFT/etc.)
- **Mode**: LLM autonomy level (ADVISORY/VETO_ONLY/DIRECTION/FULL)
- **Will Trade**: YES = decision to execute | NO = decision to skip

**Red flags to watch**:
- Confidence 0.40-0.50? = Uncertain decision, might flip
- Status "BLOCKED"? = System gates rejected it (portfolio risk, position size, etc.)
- Status "VETOED"? = Critic overrode Trade Agent with evidence
- Frequent "FLIP" actions? = Market indecision, probably not a good entry

#### Veto Reason Keywords (Word Cloud)

Shows the most common words in veto decisions, sized by frequency.

**Color meanings**:
- Red = Risk-related words (stop, loss, drawdown, exposure, leverage)
- Orange = Regime-related words (trend, panic, volatility, market, shift)
- Gray = Other (position, signal, confidence)

**Use it to spot patterns**:
- Lots of red? = System is risk-averse, maybe tighten stops
- Lots of orange? = Regime shifts causing rejections, maybe improve regime detection
- Balanced colors? = Good mix of risk-conscious and regime-aware vetoes

#### Model Routing Matrix

Shows how decisions are distributed across Claude models:

```
┌─────────────────────────────────────┐
│ Haiku:  40% │ Sonnet:  50% │ Opus:  10% │
└─────────────────────────────────────┘

Trigger × Model Matrix:
  PRE_TRADE       → 80% Sonnet, 20% Opus (high-value decisions)
  POSITION_CLOSED → 100% Haiku (low-value, learning)
  PERIODIC        → 100% Haiku (lightweight checks)
  HIGH_CONFIDENCE → 60% Sonnet, 40% Opus (important)
```

**What to look for**:
- Is PRE_TRADE using expensive models (Opus/Sonnet)? = Smart routing ✓
- Are low-value triggers (POSITION_CLOSED) using Haiku? = Cost-efficient ✓
- Lots of Opus usage? = Might be overspending, consider RECOMMENDED tier

### How to Use It

**Daily check**:
- Scan the Recent Decisions feed
- Do the notes make sense for the market conditions?
- Any surprising vetoes? Click to expand the notes

**Weekly check**:
- Look at the model routing matrix
- Is cost-per-decision reasonable?
- Are expensive models (Opus) used on high-value decisions?

**Debugging**:
- Symbol keeps getting vetoed? = Click a veto entry to see the Critic's reasoning
- Lots of "BLOCKED" instead of "VETOED"? = Issue with risk gates, not LLM

---

## Page 2: Agent Intelligence (The Agent Brain Dashboard)

**URL**: `/agent-intelligence`
**Purpose**: Per-agent performance, beliefs, calibration
**Audience**: ML engineers and power users who want to understand agent accuracy

### What You're Looking At

Nine specialized agents, each with their own:
- Accuracy across different market regimes
- Calibration curves (how well does the agent predict its own accuracy?)
- Beliefs and lessons learned
- Debate outcomes when agents disagree

### Key Sections

#### Agent Grid (Overview)

Each agent card shows:

```
┌─────────────────────────────┐
│ 🌊 REGIME AGENT      [ACTIVE]│
├─────────────────────────────┤
│ Decisions:  142             │
│ Accuracy:   ████████░  72%  │
│ Beliefs:    18              │
│ Status:     Learning        │
└─────────────────────────────┘
```

**Colors mean**:
- Green bar (accuracy 60+%) = Agent is reliable
- Orange bar (accuracy 50-60%) = Agent is learning
- Red bar (accuracy <50%) = Agent is struggling, investigate

**Click an agent** to see detailed breakdown.

#### Team Calibration Summary

Shows how well each agent predicts its own accuracy:

```
🌊 Regime    │ 72% accuracy │ Cal err: 4.2%  │ n=142
🎯 Trade     │ 78% accuracy │ Cal err: 3.1%  │ n=156
🛡️  Risk     │ 61% accuracy │ Cal err: 8.5%  │ n=142
⚖️  Critic    │ 68% accuracy │ Cal err: 5.3%  │ n=89
```

**What calibration error means**:
- 0% error = Agent perfectly predicts its own accuracy (ideal)
- <5% error = Well-calibrated, agent confidence is trustworthy
- 5-10% error = Somewhat overconfident, predictions are ~5% optimistic
- >10% error = Poorly calibrated, agent predictions not reliable

**Use this to**:
- Identify agents that need retraining (high cal error)
- Trust high-confidence predictions from well-calibrated agents
- Downweight low-calibrated agents in future decisions

#### Agent Detail Panel (Expanded)

Click an agent to see:

**Accuracy by Regime**:
```
trend        ████████░  72% | n=42
range        ███████░░  65% | n=31
panic        █████░░░░  52% | n=18
high_vol     ██████░░░  63% | n=24
unknown      ████░░░░░  41% | n=15
```

**Read it like**:
- Agent good in trends? = Use more confidence in trend regimes
- Agent terrible in panic? = Might need special panic handling
- "Unknown" regime has low accuracy? = Regime classification needs work

**Calibration Curve**:
```
Predicted   Actual    n
  50%   →   48%      12  ✓ (well-calibrated)
  60%   →   61%      18  ✓ (well-calibrated)
  70%   →   74%      14  ✗ (overconfident by 4%)
  80%   →   77%       8  ✗ (overconfident by 3%)
  90%   →   82%       6  ✗ (overconfident by 8%)
```

**What this means**:
- Agent says "80% confidence" → Actual accuracy is ~77% (slightly overconfident)
- Agent says "50% confidence" → Actual accuracy is ~48% (well-calibrated)
- **Green** = agent is accurate about its own confidence
- **Orange/Red** = agent is overconfident (thinks it's better than it actually is)

**Recent Decisions** (for this agent):
```
regime      decision    confidence    correct?
trend       proceed     0.82         ✓ CORRECT
range       skip        0.61         ✓ CORRECT
panic       flip        0.55         ✗ WRONG (marked red)
trend       proceed     0.79         ✓ CORRECT
```

#### Recent Debates

When agents strongly disagree, a "debate" is recorded:

```
DIRECTION: Bullish vs Bearish
Consensus: Bullish ✓ | Confidence: 0.72
Agreement Score: 68% (2-3 agents disagreeing)

Dissenting:
  - Risk Agent: Worried about position size
  - Critic Agent: Concerned about recent losses

Arguments For Bullish:
  + Strong uptrend on 6h chart
  + Volume increasing
  + Momentum positive

Arguments Against:
  - Recent drawdown 5.2%
  - High leverage already on
  - Not enough recovery time

Risk Flags:
  ⚠️ Account drawdown is 5.2%, consider sizing down
  ⚠️ Leverage ratio is 1.8x, approaching limits
```

**Read debates like**:
- High agreement (90%+)? = Consensus is solid, confidence in decision
- Low agreement (60%-)? = Significant disagreement, probably skip trade
- Risk agents dissenting? = Something wrong with position sizing/risk
- Multiple risk flags? = Pass on this trade

### How to Use It

**Daily check**:
- Scan the Team Calibration Summary
- Any agent with >8% calibration error? = Flag for retraining
- All agents 70%+ accuracy? = System is learning well ✓

**Weekly check**:
- Drill into each agent's accuracy by regime
- Which regimes does the system perform worst in?
- Hypothesis: "Trade agent bad in panic?" → Confirm from data
- Action: Improve panic regime detection in Regime Agent

**Debugging**:
- Trade keeps getting vetoed? → Check Critic's recent decisions
- Wrong direction frequently? → Check Trade Agent accuracy in that regime
- Risk flags ignored? → Check Risk Agent calibration

---

## Page 3: LLM Audit (Cost & Model Routing)

**URL**: `/llm-audit`
**Purpose**: Cost tracking and model routing optimization
**Audience**: Finance-minded traders, ops engineers

### What You're Looking At

Complete breakdown of **how much the LLM system costs** and **whether it's spending money wisely**.

### Key Sections

#### Model Distribution (Pie Chart)

```
┌─────────────────────────────┐
│ Haiku:  45% ($0.045/day)   │
│ Sonnet: 45% ($0.135/day)   │
│ Opus:   10% ($0.150/day)   │
│ Total:           $0.330/day │
└─────────────────────────────┘
```

**What to look for**:
- Haiku 40-50%? = Good (cheap, low-value decisions)
- Sonnet 40-50%? = Good (mid-tier, important decisions)
- Opus >20%? = Might be overspending, check routing rules
- Total <$0.50/day? = Efficient ✓

#### Trigger × Model Matrix

Shows which decision types use which models:

```
Trigger              │ Haiku │ Sonnet │ Opus  │ Avg Cost
PRE_TRADE            │   0%  │  80%   │  20% │ $0.009
REGIME_SHIFT         │  10%  │  80%   │  10% │ $0.005
POSITION_CLOSED      │ 100%  │   0%   │   0% │ $0.0001
HIGH_CONFIDENCE      │   5%  │  70%   │  25% │ $0.009
PERIODIC             │ 100%  │   0%   │   0% │ $0.0001
MEMORY_EVENT         │ 100%  │   0%   │   0% │ $0.0001
```

**Read it like**:
- PRE_TRADE (pre-entry decisions) uses 80% Sonnet, 20% Opus? = Good (high-value triggers use better models)
- POSITION_CLOSED uses 100% Haiku? = Excellent (low-value, cheap models)
- HIGH_CONFIDENCE mostly Sonnet/Opus? = Makes sense (important decisions)

**Optimization opportunities**:
- See HIGH_CONFIDENCE with high Opus usage? = Consider dropping Opus to just Sonnet
- See PERIODIC with Sonnet? = Downgrade to Haiku (waste of money)

#### Cost Per Decision Type

```
Agent Type       │ Avg Cost │ Count │ Total
─────────────────┼──────────┼───────┼─────────
Regime Agent     │ $0.0001  │  156  │ $0.0156
Trade Agent      │ $0.003   │  142  │ $0.426
Risk Agent       │ $0.0001  │  142  │ $0.0142
Critic Agent     │ $0.003   │  89   │ $0.267
Learning Agent   │ $0.0001  │  112  │ $0.0112
Exit Agent       │ $0.0001  │  45   │ $0.0045
Scout Agent      │ $0.0001  │  23   │ $0.0023
─────────────────┴──────────┴───────┴─────────
Total per cycle  │          │       │ $0.743
```

**Interpretation**:
- Trade + Critic = 57% of cost (they use Sonnet)
- Learning + Exit + Scout = <2% of cost (they use Haiku)
- **Cost per trade** = Total ÷ number of trades executed

**Optimization**:
- If cost/trade is >$0.01, consider:
  - Switching Trade Agent to Haiku for low-confidence decisions
  - Reducing Critic invocations (only for >80% confidence)
  - Using CONSERVATIVE tier instead of RECOMMENDED

#### Historical Cost Trend

Shows daily cost over time:

```
Daily LLM Cost (last 7 days)
$0.40 │     ╱╲
$0.35 │    ╱  ╲    ╱╲
$0.30 │   ╱    ╲  ╱  ╲─╲
$0.25 │  ╱      ╲╱     ╲
      └─────────────────────
        Mon Tue Wed Thu Fri Sat Sun
```

**What to look for**:
- Upward trend? = More trades or using Opus more → Check why
- Spike on one day? = Regime shift triggered high-value decisions → Normal
- Flat line? = System consistent → Good
- Budget: $0.50/day? Then you have ~$15/month LLM cost at this rate

### Cost Tiers Explained

WAGMI offers three cost tiers (set `LLM_USAGE_TIER` in `.env`):

#### CONSERVATIVE
- Uses mostly Haiku, saves Sonnet/Opus for emergencies
- Cost: ~$0.05-0.10/day
- Accuracy: 65-70%
- Use when: On a budget or learning

#### RECOMMENDED (Default)
- Balances cost and accuracy
- Uses Sonnet for high-value decisions, Haiku for low-value
- Cost: ~$0.20-0.40/day
- Accuracy: 75-80%
- **Use when**: Standard trading, good balance

#### AGGRESSIVE
- Uses Sonnet/Opus for everything
- Cost: ~$0.50-1.00/day
- Accuracy: 82-88%
- Use when: High-stakes trading, can afford premium accuracy

### How to Use It

**Daily check**:
- What was the total cost yesterday?
- How many trades did that represent?
- Cost per trade reasonable? (Target: $0.005-0.010)

**Weekly check**:
- Plot cost trend
- Is spending increasing/decreasing? Why?
- Check which triggers are most expensive
- Any opportunities to switch models?

**Monthly optimization**:
- Compare actual results vs model predictions
- Did expensive Opus decisions actually improve win rate?
- Can we downgrade any expensive triggers to cheaper models?

**Example optimization**:
```
Current: HIGH_CONFIDENCE trigger uses 25% Opus
Experiment: Switch to 100% Sonnet (no Opus)
Result: Win rate drops 1.2%, but cost drops 40%
Decision: Keep Sonnet-only (ROI positive)
```

---

## How They Work Together

```
AI Decisions Page
  ↓ Shows real-time decisions + model usage
  ↓
LLM Audit Page
  ↓ Shows cost per model + routing analysis
  ↓
Agent Intelligence Page
  ↓ Shows if decisions are actually correct
  ↓
Feedback Loop
  ↓ "Trade Agent wrong in panic regime? Retrain."
```

**Full workflow**:

1. **See a bad trade** on AI Decisions
2. **Check cost** on LLM Audit (was it cheap or expensive?)
3. **Check agent accuracy** on Agent Intelligence (agent making bad calls?)
4. **Adjust config**:
   - If expensive agent is accurate: keep using expensive models
   - If expensive agent is inaccurate: switch to cheaper model or retrain
   - If regime-specific issue: improve Regime Agent's detection

---

## Pro Tips

### Finding Bugs
- AI Decisions: Scan for patterns in veto reasons
- Agent Intelligence: Check if agent accuracy drops in specific regime
- LLM Audit: See if expensive models are beating cheap models

### Optimizing Cost
- LLM Audit: Find expensive triggers used on low-value decisions
- Example: PRE_TRADE using 50% Opus? → Switch to 100% Sonnet
- Save ~$0.006/trade with 1% accuracy drop → Probably worth it

### Improving Accuracy
- Agent Intelligence: Find agents with low calibration
- Retrain low-calibration agents more frequently
- Check regime-specific accuracy drops
- Example: "Trade Agent 72% overall but 45% in panic" → Needs panic training

### Understanding Decisions
- AI Decisions: Read the full OBSERVE→REASON→DECIDE flow
- Ask: "Does this reasoning make sense for the market?"
- If not: Check if Regime Agent is misclassifying regime

---

## Quick Reference

| Page | Best For | Key Metric | Check When |
|------|----------|-----------|-----------|
| **AI Decisions** | Understanding "why" | Veto rate | Bad trades happening |
| **Agent Intelligence** | Improving accuracy | Per-regime accuracy | Weekly optimization |
| **LLM Audit** | Controlling costs | Cost per decision | Monthly planning |

All three pages update **every minute** from live bot data. Data is at least 5 minutes fresh.

