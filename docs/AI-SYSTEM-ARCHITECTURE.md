# WAGMI AI System Architecture

**Complete guide to both agent systems working in tandem.**

---

## Two-System Architecture

WAGMI uses **two complementary AI systems**:

### System 1: Core Trading Pipeline (9 Agents)
**Purpose**: Real-time decision-making every time a signal fires
**Frequency**: Per trade opportunity
**Cost**: ~$0.007 per decision cycle
**Agents**: Regime, Trade, Risk, Critic, Learning, Exit, Scout (7 core + Overseer + Quant)

### System 2: Optimization Swarm (6 Agents)
**Purpose**: Offline improvement discovery for single-signal trades
**Frequency**: Daily at 00:00 UTC
**Cost**: ~$0.03 per optimization cycle
**Agents**: Entry Optimizer, Exit Specialist, Sizing Specialist, Regime Tuner, Pattern Discoverer, Multi-Signal Comparator

---

## System 1: The Core 9-Agent Pipeline

When a trading signal is generated, the bot runs an **orchestrated pipeline** of 9 specialized agents that reason together to decide whether to trade.

### Pipeline Flow

```
SIGNAL GENERATED (from strategies)
  ↓
1. REGIME AGENT (Haiku)
   └─ Classifies market regime (trend, range, panic, high_volatility, etc.)
   └─ Provides directional bias (bullish/neutral/bearish)
   └─ Output: regime classification + confidence
  ↓
2. TRADE AGENT (Sonnet)
   └─ Forms directional thesis using regime + signal
   └─ Decides: PROCEED, SKIP, or FLIP
   └─ Implements confluence scoring (multiple factors)
   └─ Output: direction + confidence + thesis reasoning
  ↓
3. RISK AGENT (Haiku)
   └─ Sizes position using Kelly Criterion
   └─ Flags portfolio risks (drawdown, leverage, correlated positions)
   └─ Output: position size + risk flags
  ↓
4. CRITIC AGENT (Sonnet) — The Veto Authority
   └─ Stress-tests Trade Agent's thesis
   └─ Must provide counter-thesis to veto
   └─ Can override with evidence-based objections
   └─ Output: approval OR veto with reasoning
  ↓
5-9. SUPPORTING AGENTS (on open positions or idle time)
   └─ Learning Agent: Extract lessons from closed trades
   └─ Exit Agent: Reassess thesis validity on open positions
   └─ Scout Agent: Prepare watchlists & pre-formed theses
   └─ Overseer Agent: System health audits
   └─ Quant Agent: Statistical analysis & probability
  ↓
FINAL DECISION
  ├─ Approved trades execute
  └─ Vetoed trades blocked + logged
```

### The 9 Core Agents Explained

#### 1. **Regime Agent** (Haiku)
**Role**: Market regime classification
**Input**: Current price action, volatility, trend indicators, regime history
**Output**:
- Regime: `trend`, `range`, `panic`, `high_volatility`, `low_liquidity`, `news_dislocation`, `unknown`
- Directional bias: `bullish`, `neutral`, `bearish`, `mixed`
- Confidence: 0-1

**Example**: "We're in a strong uptrend with low volatility. BULLISH bias, 0.78 confidence."

---

#### 2. **Trade Agent** (Sonnet)
**Role**: Form thesis and make go/skip/flip decision
**Input**: Regime (from Regime Agent), signal details, confluence factors, market context
**Output**:
- Action: `proceed`, `skip`, or `flip`
- Confidence: 0-1
- Thesis: Full reasoning for decision
- Confluence scores: How many factors align

**Example**: "Regime + signal + momentum all bullish. PROCEED. Confidence 0.82."

---

#### 3. **Risk Agent** (Haiku)
**Role**: Position sizing using Kelly Criterion + risk flagging
**Input**: Trade decision, current portfolio, risk limits, account equity
**Output**:
- Position size: Contracts/coins to trade
- Risk flags: Warnings (high leverage, drawdown risk, etc.)
- Size multiplier: 0-2x for adjustment

**Example**: "Kelly says 1.2% position size. Account healthy. 1.0x multiplier."

---

#### 4. **Critic Agent** (Sonnet)
**Role**: Veto authority with evidence-based objections
**Input**: Trade Agent's thesis, Risk Agent's assessment, market state
**Output**:
- Verdict: `approve` or `veto`
- Counter-thesis: If vetoing, what's the opposing view?
- Evidence: Specific data points supporting veto
- Confidence: How sure is the veto?

**Rules**:
- Can ONLY veto if it provides a counter-thesis with evidence
- Cannot veto on opinion alone
- Veto is final — overrides Trade Agent even if Trade was confident

**Example**: "I agree on trend direction but SL is too tight for this volatility. VETO with 0.71 confidence. Counter-thesis: Wait for tighter stop or reduce size."

---

#### 5. **Learning Agent** (Haiku)
**Role**: Extract lessons from closed trades
**Input**: Closed trade outcome, thesis accuracy, regime at entry/exit
**Output**:
- Lesson recorded: What worked? What didn't?
- Thesis accuracy: Was the directional prediction correct?
- Pattern identified: New setup type or regime condition
- Confidence decay: Adjust confidence in similar future setups

**Runs**: Post-close (async, every trade)

---

#### 6. **Exit Agent** (Haiku)
**Role**: Reassess open positions, recommend adjustments
**Input**: Open positions, current thesis validity, market changes
**Output**:
- Verdict: `hold`, `take_profit_partial`, `adjust_stop`, or `close`
- Reason: Why reassess?
- New thesis: Has the market regime changed?
- Urgency: High/medium/low

**Runs**: Every hour on open positions

---

#### 7. **Scout Agent** (Haiku)
**Role**: Idle-time preparation
**Input**: Watchlist symbols, regime forecasts, historical lead-lag patterns
**Output**:
- Pre-formed theses: "XYZ likely to breakout if BTC holds above 45K"
- Regime forecasts: "High probability of panic dip in next 4h window"
- Lead-lag alerts: "BTC reached resistance, ETH likely to follow"

**Runs**: Between trades (idle time)

---

#### 8. **Overseer Agent** (Sonnet)
**Role**: System health audits
**Input**: All agent performance, error rates, cost tracking
**Output**:
- Health report: All systems nominal?
- Anomaly alerts: Which agents are underperforming?
- Cost warnings: Is spending within budget?

**Runs**: Daily

---

#### 9. **Quant Agent** (Sonnet)
**Role**: Statistical analysis and probability
**Input**: Historical performance, win rates, correlation matrices
**Output**:
- Probability calculations: What's the odds this trade wins?
- Statistical significance: Is the edge real or noise?
- Correlation analysis: What's correlated in current positions?

**Runs**: Pre-trade (part of Trade Agent's input)

---

### The Thought Protocol

All agents follow the same **OBSERVE → RECALL → REASON → DECIDE → JUSTIFY** framework:

1. **OBSERVE**: What does the data show? (Cite specific numbers)
2. **RECALL**: What does memory say about similar situations?
3. **REASON**: Given observation + recall, what's the logical conclusion?
4. **DECIDE**: What action follows from the reasoning?
5. **JUSTIFY**: Why this action and not the alternatives?

This ensures consistent, transparent reasoning across all agents.

---

### Shared Context & Consistency

All 9 agents share:

- **Uniform Vocabulary**:
  - Regime names: `trend`, `range`, `panic`, `high_volatility`, `low_liquidity`, `news_dislocation`, `unknown`
  - Action names: `proceed`, `skip`, `flip`
  - Confidence scale: 0-1 (0 = no confidence, 1 = maximum confidence)

- **Shared Memory Bus**:
  - Regime Agent writes regime classification
  - Trade Agent reads regime + writes thesis
  - Risk Agent reads thesis + writes size
  - Critic reads all of above + can veto

- **Cross-Agent Calibration**:
  - Each agent's accuracy is tracked per-regime
  - Inaccurate agents are downweighted in future decisions
  - Calibration curves show predicted vs actual accuracy

- **Consistency Checker**:
  - Validates that agent outputs don't contradict each other
  - Flags when Risk Agent's size is too aggressive for Risk flags
  - Detects debate: When agents strongly disagree

---

## System 2: The 6-Agent Optimization Swarm

Running **offline** at 00:00 UTC daily, the swarm analyzes single-signal trades from the past 7 days and recommends improvements.

### Daily Swarm Cycle

```
00:00 UTC - Swarm Activation
├─ AUDIT: Extract all single-signal trades from past 7 days
│  └─ Win rate, profit factor, Sharpe ratio
│  └─ Break down by: strategy, regime, symbol, entry type
│
├─ SWARM (6 Agents Think in Parallel)
│  ├─ Entry Optimizer (Sonnet): "Wait for pullback gains +6% WR"
│  ├─ Exit Specialist (Sonnet): "Trailing stops beat fixed TP by 12%"
│  ├─ Sizing Specialist (Haiku): "Kelly says size up 25% in trends"
│  ├─ Regime Tuner (Sonnet): "Panic regime needs 50% tighter stops"
│  ├─ Pattern Discoverer (Sonnet): "SOL momentum plays during Asian hours"
│  └─ Multi-Signal Comparator (Haiku): "Single signal beats ensemble 62% when confident"
│
├─ RANK: Sort by impact × confidence
│  └─ Recommendation 1: Exit Specialist (+12% PF, 0.68 confidence) — APPLY
│  └─ Recommendation 2: Entry Optimizer (+6% WR, 0.72 confidence) — APPLY
│  └─ Recommendation 3: Sizing Specialist (+3% Sharpe, 0.55 confidence) — HOLD
│
├─ APPLY: Update config for high-confidence recommendations
│  └─ Start tracking actual impact over next 7 days
│
└─ MEASURE (7 days later): "Did trailing stops really improve by 12%?"
   └─ Actual result: +11.8% PF (vs +12% estimated) ✓
   └─ Exit Specialist accuracy: +1 to scorecard
```

### The 6 Optimization Agents

| Agent | Focus | Input | Output | Expected Impact |
|-------|-------|-------|--------|-----------------|
| **Entry Optimizer** | When to enter | Single-signal trade history | Entry timing change | +2-8% WR |
| **Exit Specialist** | How to exit | Trade outcomes, duration analysis | Exit strategy change | +5-15% PF |
| **Sizing Specialist** | Position sizing | WR + payoff ratios, Kelly Criterion | Size multiplier | +8-20% Sharpe |
| **Regime Tuner** | Regime-specific params | WR by regime breakdown | Per-regime adjustments | +3-10% WR |
| **Pattern Discoverer** | Hidden edges | Time-of-day, symbol, confluence analysis | New setup types | +2-3 new/month |
| **Multi-Signal Comparator** | Single vs ensemble | Single-signal vs multi-signal trade comparison | Confidence thresholds | +2-5% on high-conf |

---

## How Both Systems Work Together

```
Real-Time Trading (9-Agent Pipeline)
  ↓
Signal generated
  ↓
Pipeline decides: APPROVE or VETO
  ↓
Trade executes
  ├─ Logged for learning
  └─ Outcome recorded

(7 days accumulation of single-signal trades)
  ↓
Offline Optimization (6-Agent Swarm)
  ↓
Agents analyze: "What made these trades work?"
  ↓
Recommendations: "Try X to improve by Y%"
  ↓
Config updated
  ↓
Next 7 days: Measure actual impact
  ↓
Agent accuracy updated
  ↓
Back to real-time trading with improved config
```

---

## LLM Usage Tiers & Model Routing

Smart routing ensures costs stay low while maintaining quality:

### Trigger-Based Routing

| Trigger | Use Case | Model | Cost/Call |
|---------|----------|-------|-----------|
| `PRE_TRADE` | Before entering a position | Opus | $0.015 |
| `REGIME_SHIFT` | Market regime changed significantly | Sonnet | $0.003 |
| `POSITION_CLOSED` | Trade closed, extract lesson | Haiku | $0.0001 |
| `HIGH_CONFIDENCE` | Confluence score >75% | Sonnet | $0.003 |
| `PERIODIC` | Scheduled check | Haiku | $0.0001 |
| `MEMORY_EVENT` | Hypothesis graduated, pattern found | Haiku | $0.0001 |

**Total cost per trade cycle**: ~$0.007 (Regime + Trade + Risk + Critic)

---

## Memory Systems

### Short-Term Memory (7-day rolling)
- **File**: `bot/data/llm/llm_memory.json`
- **Capacity**: 100 notes max
- **TTL**: 7 days
- **Usage**: Recent context, active trades, recent regime shifts

### Deep Memory (permanent)
- **Directory**: `bot/data/llm/deep_memory/`
- **Types**:
  - `trade_dna.json` — Trade setup patterns and rules
  - `patterns.jsonl` — Discovered trade patterns
  - `hypotheses.jsonl` — Tested hypotheses (graduated to rules)
  - `lessons.jsonl` — Lessons extracted from closed trades

### Per-Agent Brains
- **Directory**: `bot/data/llm/brains/`
- **Files**: `regime_brain.json`, `trade_brain.json`, `risk_brain.json`, etc.
- **Contents**: Beliefs, accuracy curves, calibration data

---

## Decision Logging

Every decision is logged to `bot/data/llm/decisions.jsonl` (append-only):

```json
{
  "ts": 1710000000,
  "symbol": "BTC",
  "action": "proceed",
  "confidence": 0.82,
  "regime": "trend",
  "notes": "OBSERVE: uptrend strong...",
  "is_veto": false,
  "allowed": true,
  "model": "claude-sonnet-4",
  "trigger": "PRE_TRADE"
}
```

---

## Autonomy Levels

The system operates at configurable autonomy levels (0-5):

- **Level 0 (OFF)**: LLM disabled, rule-based only
- **Level 1 (ADVISORY)**: LLM recommends, humans must approve
- **Level 2 (VETO_ONLY)**: LLM can block but can't initiate
- **Level 3 (SIZING)**: LLM can size positions
- **Level 4 (DIRECTION)**: LLM can change direction (BUY → SELL)
- **Level 5 (FULL)**: Complete autonomy

Set via `LLM_MODE=0-5` in `.env`.

---

## Environment Configuration

Enable the multi-agent system:

```bash
# .env
LLM_MULTI_AGENT=true          # Enable 9-agent pipeline
LLM_USAGE_TIER=RECOMMENDED    # Smart model routing
LLM_MODE=4                    # Autonomy level (0-5)

# Per-agent model overrides (optional)
AGENT_REGIME_MODEL=claude-haiku-4
AGENT_TRADE_MODEL=claude-sonnet-4
AGENT_CRITIC_MODEL=claude-sonnet-4

# Per-agent enable/disable
AGENT_EXIT_ENABLED=true
AGENT_SCOUT_ENABLED=true
AGENT_LEARNING_ENABLED=true
```

---

## Monitoring & Debugging

### View Live Pipeline
```bash
cd bot && python run.py paper
# Watch logs — each trade shows full pipeline flow
```

### Check Agent Performance
Visit web dashboard: **[Agent Intelligence](/agent-intelligence)** page

### Audit Decisions
Visit web dashboard: **[AI Decisions](/ai-decisions)** page

### Cost Tracking
Visit web dashboard: **[LLM Audit](/llm-audit)** page

---

## Next Steps

- **[Read: Autonomy & Safety](./AUTONOMY.md)** — Autonomy levels 0-5 and safety invariants
- **Check the dashboards**: Visit `/ai-decisions`, `/agent-intelligence`, `/llm-audit`
- **Read the guides**: [AI Pages Guide](./AI-PAGES-GUIDE.md) for dashboard help
- **Monitor with skills**: Use `/paper-status`, `/health-check`, `/agent-debug`

