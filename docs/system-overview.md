# WAGMI System Overview

## The Problem

Traditional trading systems:
- Use **fixed rules** that degrade over time
- Have **static strategies** that don't adapt
- Require **manual optimization** every few weeks
- Leave **profitable edges undiscovered**
- Can't **systematically test** improvements

Most traders optimize manually. Most LLM systems ask "should I trade?" but don't ask "how can I trade better?"

---

## The Solution: Multi-Agent Autonomous Brain

WAGMI is a **two-tier multi-agent AI system** that works together to:

### Real-Time Tier (9 Agents)
1. **Classify** market regime and directional bias
2. **Form** trading theses with confluence scoring
3. **Size** positions using Kelly Criterion
4. **Veto** overconfident or risky decisions (Critic Agent)
5. **Execute** or skip trades with full transparency

### Optimization Tier (6 Agents)
1. **Discover** what makes trades profitable
2. **Test** improvements automatically (daily)
3. **Apply** proven optimizations to live trading
4. **Learn** from outcomes continuously
5. **Scale** profitably as accuracy improves

Think of it as hiring 15 expert traders (9 on real-time decisions, 6 on overnight optimization) who work 24/7, make informed decisions, and tell you exactly how to improve.

---

**🎯 Want the full technical breakdown?** → Read **[AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md)** for complete details on all 9+6 agents.

---

## Core Concept: Two-Tier Decision Making

The 9-agent pipeline makes **real-time trading decisions** with full reasoning transparency. The 6-agent swarm then **discovers improvements overnight** by analyzing what actually works.

### Real-Time Pipeline

When a signal fires, the 9-agent pipeline decides in ~2 seconds:

```
Signal → Regime Classification → Trade Thesis → Risk Sizing → Critic Veto → Execute/Skip
  ↓          ↓                      ↓             ↓              ↓
Haiku      Forms opinion      Uses KellyCriterion   Final      Log decision
         on market state       + portfolio risk    authority
```

All reasoning is logged and visible on the **[/ai-decisions page](/ai-decisions)**.

### Offline Optimization

After 7 days of trading, the 6-agent swarm wakes up:

```
Analyze: All single-signal trades from past week
  ↓
6 Agents think in parallel:
  - "Entry timing could be better" → +6% win rate
  - "Exits aren't optimal" → +12% profit factor
  - "Position sizing too conservative" → +3% Sharpe
  ↓
Recommend top 3 improvements
  ↓
Apply best recommendations to live config
  ↓
Measure actual results over next week
```

---

## Single-Signal Optimization Focus

Most trading systems use **ensemble voting**:
- Strategy A says: BUY
- Strategy B says: SELL
- Strategy C says: HOLD
- System decides: majority rules

But **single-signal trades** (only 1 strategy fires) are different:
- **Higher conviction** (the one opinion is very strong)
- **Clearer patterns** (less noise from ensemble)
- **Customizable** (optimize specifically for that signal)
- **More profitable** (historically better performers)

**WAGMI focuses on these high-conviction trades and makes them even better.**

---

## How It Works: Daily Cycle

### 00:00 UTC - The Swarm Wakes Up

```
Step 1: AUDIT (Extract & Analyze)
  ↓ Find all single-signal trades from last 7 days
  ↓ Compute: win rate, profit factor, Sharpe ratio
  ↓ Break down by: strategy, regime, symbol, entry type
  ↓ Result: "We have 47 single-signal trades, 58% WR, PF=2.1"

Step 2: SWARM (6 Agents Think in Parallel)
  ├─ Entry Optimizer: "Wait for pullback gains +6% WR"
  ├─ Exit Specialist: "Trailing stops beat fixed TP by 12%"
  ├─ Sizing Specialist: "Kelly says size up 25% in trends"
  ├─ Regime Tuner: "Panic regime needs 50% tighter stops"
  ├─ Pattern Discoverer: "SOL momentum plays during Asian hours"
  └─ Multi-Signal Comparator: "Single signal beats ensemble 62% when confident"

Step 3: RANK (Prioritize by Impact)
  ↓ Entry Optimizer's pullback idea: +6% WR, 72% confidence → Score: High
  ↓ Exit Specialist's trailing: +12% PF, 68% confidence → Score: Very High
  ↓ Others ranked below
  ↓ Result: Top 5 recommendations ready

Step 4: APPLY (Update Trading Config)
  ↓ If recommendation confidence >65% AND impact >3%:
     Apply to live config
  ↓ Start tracking actual outcomes

Step 5: MEASURE (Check If It Actually Worked)
  ↓ After 7 days: "Did pullback entries really improve WR?"
  ↓ Actual result: +5.8% WR (vs +6% estimated)
  ↓ Entry Optimizer accuracy: +1 to scorecard

Step 6: LEARN (Update Agent Trust)
  ↓ Entry Optimizer: "You were right 72% of the time"
  ↓ Exit Specialist: "You were right 78% of the time"
  ↓ Future recommendations weighted by accuracy
```

---

## The 6 Agents Explained

### Agent 1: Entry Optimizer

**Question**: When should I enter?

**Focuses On**:
- Market now vs wait for pullback vs reclaim level
- Entry timing by regime (trend vs range vs panic)
- Symbol-specific patterns (BTC acts different than SOL)
- Time-of-day effects (Asian hours vs London fix)

**Example Discovery**:
```
"SOL + regime:trend + wait for pullback to EMA20"
Result: 58% WR → 64% WR (+6%)
Confidence: 72%
→ If applied to 20 trades/month: +1.2 win per month
```

**Expected Impact**: +2-8% WR improvement

---

### Agent 2: Exit Specialist

**Question**: When should I exit and how?

**Focuses On**:
- Fixed TP vs trailing stop vs time-based exit
- Exit timing by regime (tight stops in panic, wide in trend)
- Profit factor optimization (maximize wins per loss)
- Risk reduction (avoid leaving money on table)

**Example Discovery**:
```
"High-volatility regime + trailing stop (1.5x ATR)"
Result: PF 1.8 → PF 2.8 (+55% better)
Confidence: 68%
→ Every trade that hits profit targets now keeps more
```

**Expected Impact**: +5-15% profit factor improvement

---

### Agent 3: Sizing Specialist

**Question**: How big should my position be?

**Focuses On**:
- Kelly Criterion calculation (mathematical optimal size)
- Regime-adaptive sizing (size up in high-confidence regimes)
- Account-size scaling ($500 vs $10,000 accounts)
- Drawdown management (never take on unnecessary risk)

**Example Discovery**:
```
"regime_trend has 58% WR, avg_win +2.5%, avg_loss -1.0%"
Kelly = (0.58 × 2.5 - 0.42 × 1.0) / 2.5 = 0.70 (70% of bankroll)
Half-Kelly = 3.5% risk per trade (safe)
→ Size all trend trades at 3.5% instead of 2%
```

**Expected Impact**: +8-20% Sharpe ratio improvement

---

### Agent 4: Regime Tuner

**Question**: What parameters work best in each market condition?

**Focuses On**:
- Regime-specific entry rules (what works in trends vs ranges)
- Stop-loss width by regime (wider in trends, tighter in panic)
- Take-profit targets by regime
- Strategy performance per regime

**Example Discovery**:
```
Analysis across all trades:
- Trend regime: regime_trend 71% WR, multi_tier_quality 62% WR
  → Recommend sizing 1.5x on regime_trend in trends
- Panic regime: all strategies <45% WR
  → Recommend skipping or 0.5x sizing in panic
```

**Expected Impact**: +3-10% WR by regime-specific optimization

---

### Agent 5: Pattern Discoverer

**Question**: What hidden profitable patterns exist?

**Focuses On**:
- Symbol + regime combinations (when do certain assets perform best?)
- Time-of-day patterns (momentum during Asian hours?)
- Volume patterns (do volume spikes predict moves?)
- Cross-asset correlations (when BTC moves, alts follow)

**Example Discovery**:
```
Mining 6 months of trades:
"SOL in trend regime during 00:00-08:00 UTC"
Results: 12/14 wins (85% WR), avg +2.1% per trade
Sample size: 14 (small but consistent)
Confidence: 69%
→ "Consider sizing 1.5x on this pattern"
```

**Expected Impact**: +2-3 new profitable patterns per month

---

### Agent 6: Multi-Signal Comparator

**Question**: When should I trust single signal vs ensemble?

**Focuses On**:
- Single signal win rate vs ensemble win rate
- When does single signal beat consensus?
- Conflict resolution (if single says yes, ensemble says no)
- Trust calibration (when is single signal most reliable?)

**Example Discovery**:
```
Analyzing conflicts:
- When single fires + ensemble disagrees:
  Single: 48% WR
  Ensemble: 72% WR
  → Ensemble is more reliable in conflicts

- When both single AND ensemble agree:
  Both: 82% WR
  → This is your highest-conviction setup
```

**Expected Impact**: +2-5% accuracy on high-conviction decisions

---

## Data Flow: From Trade to Knowledge

```
TRADING EXECUTION
    ↓
Trade closed: entry $50k, exit $51k, PnL +$100
    ↓
SINGLE-SIGNAL AUDIT
    ├─ Extract: Single strategy fired (regime_trend)
    ├─ Compute: Win rate 58%, profit factor 2.1
    ├─ Classify: Regime=trend, Symbol=BTC, Entry=pullback
    └─ Store: In single_signal_trades.jsonl
    ↓
6-AGENT SWARM
    ├─ Entry Optimizer reads: "Entry adjustments work?"
    ├─ Exit Specialist reads: "Exit timing optimal?"
    ├─ Sizing Specialist reads: "Position size right?"
    ├─ Regime Tuner reads: "Regime-specific rules?"
    ├─ Pattern Discoverer reads: "Any new patterns?"
    └─ Multi-Signal reads: "Single vs ensemble?"
    ↓
RECOMMENDATIONS
    ├─ "BTC pullbacks in trend: +6% WR" (Entry Optimizer)
    ├─ "Trailing stops beat fixed: +12% PF" (Exit Specialist)
    └─ ... (4 more recommendations)
    ↓
FEEDBACK LOOP
    ├─ Rank by impact × confidence
    ├─ Apply top recommendations to config
    ├─ Track actual outcome for 7 days
    └─ Update agent accuracy
    ↓
LIVE IMPROVEMENT
    ├─ New config deployed
    ├─ Next entries use "wait for pullback"
    ├─ Win rate improves
    └─ Cycle repeats daily
```

---

## Why This Actually Works

### 1. Specialization > Generalization
- One LLM can't hold all trading concepts simultaneously
- Six specialists each master their domain
- More focused → better recommendations

### 2. Evidence-Based > Opinion-Based
- Every recommendation measured against actual outcomes
- Agents learn which recommendations worked
- Accuracy curves improve over time

### 3. Autonomous > Manual
- Runs daily without human intervention
- No weekly manual optimization meetings
- Scales as account grows

### 4. Safe Experimentation > Risky Changes
- Tests only on single-signal trades (controlled sandbox)
- Measured over 7 days before decision
- Can roll back if degraded

### 5. Compound Learning > Static System
- Day 1: Agent accuracy 55-60%
- Week 2: Agent accuracy 65-70%
- Week 4: Agent accuracy 72-78%
- Each improvement builds on previous
- **System gets smarter every day**

---

## Real-World Example

### Scenario: You Have $1000 Account

**Before WAGMI:**
```
20 trades/month
50% win rate
+$100/month profit
Strategy: static rules, no optimization
```

**After WAGMI (Week 1):**
```
Swarm running, collecting data
No changes yet
Cost: ~$0.15 in tokens
Profit: Same ($100/month)
```

**After WAGMI (Week 2):**
```
Entry Optimizer: "Pullback entries +6% WR"
Applied to 4 trades/week = 16/month
New WR: 52% (on 16) + 50% (on 4) = 51.5% overall
Profit: +$102/month
Cost: ~$0.15/month
Net: +$2/month
```

**After WAGMI (Week 3):**
```
Exit Specialist: "Trailing stops +10% PF"
Sizing Specialist: "Kelly sizing improves Sharpe"
New WR: 55% overall
Profit: +$125/month
Cost: ~$0.15/month
Net: +$25/month (25x ROI)
```

**After WAGMI (Week 4):**
```
Multiple rules active
4 of 6 agents >70% accurate
New WR: 57% overall
Profit: +$150/month
Cost: ~$0.15/month
Net: +$50/month (333x ROI)
```

**After WAGMI (Month 2+):**
```
Rules proven, scaling up
Size positions 1.5-2x
Frequency increased
Profit: +$300-500/month
Cost: ~$0.15/month
Net: $300+/month (2000x ROI)
```

---

## Key Metrics

| Metric | Baseline | After 4 weeks | After 8 weeks |
|--------|----------|---------------|---------------|
| Single-signal WR | 52% | 55-57% | 58-60% |
| Profit Factor | 1.8 | 2.0-2.3 | 2.3-2.8 |
| Sharpe Ratio | 1.2 | 1.5-1.8 | 1.8-2.2 |
| Patterns Known | 0 | 2-3 new | 5-7 new |
| Agent Accuracy | 55-60% | 65-70% | 72-78% |
| Monthly ROI | Baseline | +10-20% | +25-50% |

---

## The Vision

**WAGMI isn't just a trading bot. It's an autonomous learning system that makes you a better trader every single day.**

- It finds patterns you'd never discover manually
- It tests improvements you'd be too scared to try
- It optimizes ruthlessly based on actual outcomes
- It scales profitably as it gets smarter

By harnessing 6 specialized AI agents, continuous learning, and evidence-based optimization, WAGMI turns intuition into strategy and strategy into compounding profit growth.

**The market changes. WAGMI adapts. Every day.**

---

**Next**: [Quick Start Guide](./quick-start.md) to deploy your swarm
