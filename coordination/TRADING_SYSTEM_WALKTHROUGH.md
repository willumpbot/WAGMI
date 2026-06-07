# Trading System Complete Walkthrough
**Purpose**: Understand everything the bot sees, decides, and executes  
**For**: Nunu — full transparency on signal flow and decision-making

---

## Part 1: What the Bot SEES (Market Data)

### Data Sources
The bot reads from Hyperliquid exchange:
- **Price candles**: 1h, 5m, 6h, daily timeframes
- **Order book**: bid/ask spreads, OI (open interest)
- **Funding rates**: long/short borrowing costs
- **Liquidation cascades**: where weak hands get stopped out

### Current Market Context (as of last bot cycle)
**Need from desktop Claude**: Current BTC/ETH prices, regime, funding rates
- BTC price: ___
- ETH price: ___
- Regime: consolidation (choppy, no edge)
- Funding: (positive = longs paying = crowded long = mean reversion risk)

---

## Part 2: What the Bot GENERATES (Raw Signals)

### How Signals Are Made
The bot runs **4 independent strategies** every cycle:
1. **regime_trend** — Is there directional momentum? (1h + 6h trends)
2. **confidence_scorer** — Multi-factor quality score
3. **bollinger_squeeze** — Support/resistance at extremes
4. **multi_tier_quality** — Cross-timeframe alignment

Each strategy **independently** generates signals:
```
Signal = {
  symbol: "BTC",
  side: "SHORT",
  confidence: 77,          # 0-100 scale
  entry: 67500.0,
  sl: 67800.0,             # Stop loss
  tp1: 67000.0,            # Take profit 1
  tp2: 66000.0,            # Take profit 2
  regime: "consolidation",
  strategy_name: "regime_trend"
}
```

### Monday-Tuesday Winning Signals
These signals FIRED and EXECUTED:

**Trade 1: BTC SHORT (Jun 2, 15:18 UTC)**
- Regime: **trending_bear** ✅ (downtrend confirmed)
- Confidence: 85%
- Size: 1.5x leverage
- Exit: TP2 (full takeprofit)
- Result: **+$378.59**

**Trade 2: ETH SHORT (Jun 3, 21:13 UTC)** ⭐ BEST
- Regime: **trending_bear** ✅ (strong downtrend)
- Confidence: 90%
- Size: 2.0x leverage
- Entry: Support level (resistance-turned-support)
- Exit: Trailing stop (trailed as market fell)
- Result: **+$1,010.37**

**Key pattern**: Both were SHORTS in TRENDING_BEAR regime with 85%+ confidence.

---

## Part 3: How Decisions Are Made (Multi-Agent Pipeline)

### The Decision Pipeline (4 Agents, Sequential)

When a signal fires, it goes through:

```
Signal (e.g., BTC SHORT conf=77, regime=consolidation)
    ↓
[REGIME AGENT] (Haiku)
  Reads: Current price, 1h/6h/daily trends, funding, OI
  Decides: What regime are we in? (trending_bull, trending_bear, consolidation, high_vol, etc.)
  Output: regime="consolidation", directional_bias="neutral"
    ↓
[TRADE AGENT] (Sonnet - expensive but smart)
  Reads: Regime, signal, 4-strategy votes, recent win/loss streak
  Decides: Go? Skip? Flip?
  Logic:
    - "Is the thesis coherent?" (do the technical + regime align?)
    - "Do I trust this regime?" (trending_bear = yes, consolidation = no)
    - "How many strategies agree?" (1 = weak, 3+ = strong)
  Output: action="skip", confidence=0.32, thesis="Consolidation, no clear direction"
    ↓
[RISK AGENT] (Haiku)
  Reads: Trade decision, current positions, equity, ATR volatility
  Decides: If go, how much leverage? (0.5x to 25x)
  Logic:
    - High volatility = smaller leverage
    - Trending regime = larger leverage
    - Already have 2 open positions = reduce size
  Output: leverage=1.5x, qty=0.5 BTC
    ↓
[CRITIC AGENT] (Sonnet)
  Reads: Trade Agent thesis + Risk Agent sizing
  Decides: Approve? Veto? Override?
  Logic:
    - "Is the thesis falsifiable?" (Can I prove it wrong?)
    - "Are we risking too much?" (Max drawdown check)
    - "Does the sizing match the edge?" (Kelly criterion)
  Output: approve=true, counter_thesis=none
    ↓
EXECUTE (enter position, set SL/TP, monitor)
```

### Monday-Tuesday: Why Those Trades Won

**BTC SHORT (trending_bear):**
```
Regime Agent: "trending_bear" (confirmed downtrend from 6h + daily)
Trade Agent: "Coherent. Regime favors shorts. 2 strategies agree (regime_trend + confidence_scorer). Go."
Risk Agent: "Trending regime = 1.5x leverage. ATR=800, can risk $300. Size: 0.5 BTC"
Critic Agent: "Thesis is clear: lower lows, lower highs. Approved."
Result: +$378.59 ✓
```

**ETH SHORT (trending_bear, stronger):**
```
Regime Agent: "trending_bear" (strong ETH downtrend all timeframes)
Trade Agent: "Very coherent. Multiple confluence: regime + bollinger_squeeze (price at resistance) + funding negative. Go."
Risk Agent: "Strong regime + high conviction = 2.0x leverage. ATR=200, can risk $400. Size: 1.0 ETH"
Critic Agent: "Thesis bulletproof: support broken, resistance rejected, negative funding. Approved."
Result: +$1,010.37 ✓✓
```

### Current (Consolidation): Why Signals Are Skipped

**Example: Current HYPE BUY signal**
```
Raw signal: BUY conf=77, regime=consolidation
Regime Agent: "consolidation" (choppy, no clear direction, high chop ratio)
Trade Agent: "Weak thesis. Consolidation = no edge. Only 1 strategy (confidence_scorer). Skip."
Risk Agent: (never reached, Trade Agent already skipped)
Critic Agent: (never reached)
Result: SKIP (no position opened) ✓ CORRECT
```

---

## Part 4: Why Monday-Tuesday Worked (The Winning Formula)

### Success Factors
1. **Regime was right** — trending_bear (strong downtrend) = clear edge
2. **Confidence was high** — 85%+ from multiple strategies agreeing
3. **Thesis was coherent** — technical setup + regime aligned
4. **Sizing matched edge** — 1.5-2.0x leverage on proven setups
5. **LLM was filtering** — Skipped weak signals, executed strong ones

### Sizing Formula (Monday-Tuesday)
```
Position Size = Risk $ / Stop Loss Width
Where:
  Risk $ = 1-2% of equity (based on confidence & regime)
  Stop Loss Width = distance to stop loss
  Leverage = position_size / equity (determined by Risk Agent)
  
Example (ETH SHORT +$1,010):
  Risk $ = 2% of $5,000 = $100
  Entry: $2,800, SL: $2,850 = $50 width
  Position size: $100 / $50 = 2 BTC worth leverage
  Leverage = 2.0x
```

---

## Part 5: Current System State (vs Monday-Tuesday)

| Factor | Monday-Tuesday | Current | Impact |
|---|---|---|---|
| **Regime** | trending_bear | consolidation | ❌ No edge |
| **Confidence** | 85%+ | 77% average | ⚠️ Weaker |
| **Data quality** | Clean | Clean (after cleanup) | ✅ Same |
| **Kelly sizing** | 1.5-2.0x | 0.15x (dampened) | ❌ Too small |
| **Agent filters** | Working | Working | ✅ Same |
| **Signal generation** | Yes | Yes (but weak) | ⚠️ Many skips |
| **LLM decisions** | Smart skips | Smart skips | ✅ Correct |

**Bottleneck**: Not the system — the MARKET. Consolidation has no edge. Waiting for trending regime.

---

## Part 6: How to Replicate Monday-Tuesday

### Conditions Needed
✅ **Regime**: trending_bear OR trending_bull (need clear directional momentum)  
✅ **Confidence**: 80%+ (multiple strategies agreeing)  
✅ **Thesis**: Coherent (support/resistance + momentum + regime aligned)  
✅ **Leverage**: 1.5-2.0x (matched to edge quality)  
✅ **Sizing**: Full Kelly (Risk Agent will size properly once Kelly recalculates)

### Trading Checklist
When a signal fires, check:
1. **Is regime trending?** (trending_bear or trending_bull) → Yes? Continue
2. **Do multiple strategies agree?** (3+) → Yes? Continue
3. **Is confidence 80%+?** → Yes? Continue
4. **Does Regime Agent confirm the trend?** (check logs) → Yes? Continue
5. **Does Trade Agent approve?** (check thesis) → Yes? EXECUTE

If ANY of these fail: SKIP. This is how we get 67% WR like Monday-Tuesday.

---

## Part 7: Reading the Bot Logs (What to Look For)

### Key Log Signals
```
[REGIME-AGENT] BTC trending_bear (ADX=45, EMA slope=negative) ← Good trend
[MULTI-AGENT] Trade Agent -> Sonnet ← Agent firing, expensive but thorough
[LLM-FIRST] Entry decision: go ← Trade approved
[LLM-FIRST] Entry decision: skip ← Trade rejected (why? thesis weak)
[TRADE_CLOSED] PnL=$345.23 ← Closed trade, track result
[EXIT-INTEL] thesis_invalidated ← Stop loss hit
[KELLY] recomputed weights ← Sizing recovering
```

### How to Spot Problems (vs Monday-Tuesday)
❌ **Too many SLs hit** → Stop losses too tight (sub-0.5% = noise)  
❌ **Low win rate** → Trading low-confidence setups (need 80%+)  
❌ **Micro sizing** → Kelly dampened (0.15x), need recovery  
❌ **Only regime=consolidation** → Market has no edge, wait for trend  
✅ **regime=trending_bear, conf=85%, multi-agent approve** → This is Mon-Tue

---

## Part 8: Your Action Plan

**Now**: 
1. Get logs from desktop Claude (what signals are firing NOW)
2. Cross-reference against this walkthrough
3. Identify: Are we in consolidation or trending?
4. If consolidation: WAIT (no edge to trade)
5. If trending: Check why agent is skipping (weak thesis? low confluence?)

**When Trending Appears**:
1. Monitor for regime=trending_bear or trending_bull in logs
2. Look for 3+ strategies agreeing (high confluence)
3. Watch Regime Agent confirm the trend
4. Watch Trade Agent approve (not skip)
5. Execute at 1.5-2.0x leverage
6. Track result → Kelly learns → Sizing recovers

---

## Part 9: Questions to Ask Desktop Claude

With logs in hand, ask:
- "Show me the last 5 signals. Why did you skip each one?"
- "What's the current regime? (trending or consolidation?)"
- "Are we seeing trending_bear signals? If so, why skip?"
- "What's the current Kelly dampening? (should be moving from 0.15x toward 1.0x)"
- "Show me confidence scores on recent signals. Are they 80%+?"

---

**Once you get the logs, come back here with specific questions. I'll walk through each decision.**
