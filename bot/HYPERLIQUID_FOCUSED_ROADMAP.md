# Hyperliquid-Focused Roadmap: Genius Quant System on Single Exchange

**Philosophy:** Stop thinking about multiple edge sources. Dominate **one exchange** with **exceptional precision**. Hyperliquid is deep, liquid, and data-rich. We'll become the best Hyperliquid quant system.

**Decision:** NO cross-exchange arbitrage, NO pair trading, NO risky off-exchange features.
**Focus:** Scalping, conviction, funding analysis, liquidation prediction, market microstructure — all **on Hyperliquid**.

---

## **Why Hyperliquid?**

- **Deep liquidity:** Can execute large positions without slippage
- **Perpetual-native:** Funding rates, open interest, liquidation cascades unique to perpetuals
- **Fast execution:** Sub-second fills
- **Data richness:** Orderbook depth, open interest delta, liquidation maps

**Our competitive advantage:** We'll understand Hyperliquid's microstructure **better than any other bot**.

---

## **Phase 4: SCALPING + CONVICTION (Current, 3 weeks)**

### **Status: ✅ INFRASTRUCTURE COMPLETE, TESTING BEGINS**

**What's Built:**
- ✅ Micro-Trend Detector (5m trend classification)
- ✅ Scalper Agent (1m micro-scalp opportunities)
- ✅ Conviction Agent (2.5x leverage authorization)
- ✅ Executor Timing Optimizer (market vs limit vs scaled)

**What's Next:**
1. Unit testing (50+ tests) — 2 days
2. 30-day backtest — 1 day
3. 2-week paper trading — 14 days
4. Go/no-go decision — decide based on metrics

**Success Criteria (Hard Gates):**
- Scalp win rate ≥45%
- Conviction win rate ≥70%
- Combined Sharpe ≥1.2
- Max drawdown ≤15%
- Zero execution bugs

**Expected Revenue:** $1,770-6,550/month (if all metrics pass)

---

## **Phase 4.5: HYPERLIQUID MICROSTRUCTURE MASTERY** (Parallel with Phase 4 testing, 2-3 weeks)

**These are "Hyperliquid-native" features that only work on perpetuals. Build while Phase 4 is in paper trading.**

### **1. Liquidation Cascade Detector**

**What:** Detect when liquidation cascades are happening NOW (not after)
**Why:** Cascades create micro-volatility + opportunities for quick scalps
**Data:** Open interest delta, liquidation heatmap, funding rate spikes

**Agent: Liquidation Scout (Haiku)**
- Runs every 1m
- Detects: "Heavy liquidation pressure at $125.50", "Risk of cascade if BTC breaks $68k"
- Output: Severity level 0-5, direction, recommended action (fade/ride cascade)
- Cost: $0.0005/call = $0.036/month
- Expected edge: 1-2% per trade on cascade trades (~3-5 per day)

```json
{
  "cascade_severity": 0-5,
  "liquidation_level": "$125.50",
  "direction": "buyers_liquidating (bearish)" | "sellers_liquidating (bullish)",
  "funding_impact": "+0.02% funding rate increase expected",
  "opportunity": "scalp_the_bounce" | "fade_the_move" | "wait_for_stability",
  "confidence": 0.72,
  "expected_pnl": "+0.5-1.5% if correct"
}
```

---

### **2. Funding Rate Dynamics Analyzer**

**What:** Understand WHEN to size based on funding rate impact
**Why:** Funding drag affects profitability — don't hold through heavy funding
**Data:** Current funding rate, historical funding patterns, position hold time

**Agent: Funding Optimizer (Haiku)**
- Runs per signal
- Questions: "Is holding 4h profitable if funding stays at +0.04%?"
- Output: Adjusted position size, suggested hold time, funding impact
- Cost: $0.001/signal = $0.06/month
- Expected edge: 0.3-0.5% better position sizing (avoid funding drag traps)

```json
{
  "current_funding": "+0.0425% per 8h",
  "funding_trend": "rising" | "stable" | "falling",
  "expected_funding_cost_on_trade": "-0.08% over 4h",
  "adjusted_size_multiplier": 0.85,
  "max_profitable_hold": "3h",
  "recommendation": "Size down 15% OR close early if thesis holds",
  "funding_impact_on_pnl": "-0.08% (material)"
}
```

---

### **3. Open Interest Momentum Analyzer**

**What:** Track open interest changes to detect directional shifts
**Why:** OI expansion = directional conviction, OI contraction = position closing
**Data:** OI delta, rate of change, historical OI patterns

**Agent: OI Analyst (Haiku)**
- Runs every 5m
- Detects: "OI expanding +5% on BUY side (bullish)", "OI collapsing (liquidation cascade likely)"
- Output: Direction implied by OI, conviction level, expected duration
- Cost: $0.0003/call = $0.013/month
- Expected edge: Better direction timing (ride OI momentum)

```json
{
  "oi_direction": "expanding_long" | "expanding_short" | "contracting",
  "oi_velocity": "+2.3%/hour" | "-1.5%/hour",
  "implied_direction": "bullish (long expansion)",
  "conviction": 0.78,
  "expected_move": "+2-3% over next 4h",
  "duration": "stable for ~4h, then likely reversal"
}
```

---

### **4. Orderbook Depth Predictor**

**What:** Predict market moves based on bid/ask imbalance
**Why:** Wide imbalance = one-sided market, moves continue
**Data:** Live orderbook, bid/ask ratio, depth by price level

**Agent: Orderbook Analyzer (Haiku)**
- Runs every 5-10s (very frequent)
- Detects: "Ask side weak (sellers thin), expecting move up", "Bid side heavy (buyers queuing), expecting pullback"
- Output: Directional bias, strength, expected move
- Cost: $0.0001/call × 144/day = $0.01/month
- Expected edge: 0.2-0.5% better entry/exit timing

```json
{
  "bid_ask_ratio": 0.72,
  "interpretation": "More bids than asks (buyers pushing)",
  "expected_bias": "continuation_up",
  "strength": 0.65,
  "best_entry_method": "market_now (capture momentum)",
  "best_exit_method": "limit_at_resistance (buyers might push through)"
}
```

---

### **5. Slippage Predictor**

**What:** Estimate actual fill price vs market price
**Why:** Big orders might not fill at market price
**Data:** Recent fill data, current orderbook, historical slippage patterns

**Deterministic (No LLM):**
```python
def predict_slippage(size_usd, symbol, current_spread, recent_fills):
    """
    Example: 10k SOL order
    - Avg spread: 0.03
    - Orderbook depth at mid: 500k (thick)
    - Recent slippage: 0.05-0.10%
    - Predicted slippage: ~0.08%
    - Adjusted price: market + 0.08%
    """
    # Uses orderbook depth + recent fills to estimate
    return slippage_estimate
```

**Expected edge:** 0.1-0.3% better average execution

---

### **6. Thesis Validation Engine (Enhanced)**

**What:** Check historical accuracy of similar theses
**Why:** "BTC breaks resistance, SOL follows" — how often did this work?
**Data:** Deep memory, trade history, pattern library

**Deterministic (No LLM):**
```python
def validate_thesis(thesis_string, deep_memory, minimum_n=10):
    """
    Example thesis: "BTC broke 6h resistance, SOL lagging 15min, regime=trend"

    Search deep_memory for similar theses:
    - Match: "BTC 6h breakout + SOL lag + trend" → 22 trades, 73% WR
    - Match: "BTC resistance break + SOL + trend" → 18 trades, 69% WR
    - Similar: "BTC moving + SOL + trend" → 45 trades, 62% WR (weaker)

    Return: validation_score, historical_WR, confidence_adjustment
    """
    return {
        "status": "validated" | "novel" | "failed_pattern",
        "historical_wr": 0.71,
        "n_similar_trades": 22,
        "confidence_adjustment": +0.10
    }
```

**Expected edge:** 2-3% better signal quality (avoid low-edge patterns)

---

### **7. Scalp Pattern Library (Built From History)**

**What:** Learn which scalp setups have best win rates
**Why:** "RSI<15 + volume>1.5x + bouncing" might be 65% WR vs "RSI<20 + volume>1.2x" 48% WR
**Process:** Weekly offline analysis of all scalps

**Output:**
```json
{
  "high_edge_patterns": [
    {
      "name": "RSI<15 + volume>1.5x + bouncing_from_low",
      "wr": 0.65,
      "n": 42,
      "avg_profit": 0.85,
      "confidence_boost": +0.20,
      "condition": "Use this pattern aggressively"
    },
    {
      "name": "RSI>85 + volume>1.3x + exhaustion_forming",
      "wr": 0.61,
      "n": 35,
      "avg_profit": 0.75,
      "confidence_boost": +0.15
    }
  ],
  "low_edge_patterns": [
    {
      "name": "Mid-trend dip (RSI 40-60) + volume<0.8x",
      "wr": 0.35,
      "reason": "Pure noise, no edge",
      "action": "Skip these"
    }
  ]
}
```

**Expected edge:** 2-3% improved scalp win rate

---

## **Phase 4.5 Summary**

| Component | Cost/Month | Expected Edge | Priority |
|-----------|-----------|---------------|----------|
| Liquidation Scout | $0.04 | 1-2% per cascade | HIGH |
| Funding Optimizer | $0.06 | 0.3-0.5% better sizing | MEDIUM |
| OI Momentum | $0.01 | Better timing | MEDIUM |
| Orderbook Analyzer | $0.01 | 0.2-0.5% execution | MEDIUM |
| Slippage Predictor | $0.00 | 0.1-0.3% better fills | LOW |
| Thesis Validator | $0.00 | 2-3% signal quality | HIGH |
| Scalp Library | $0.00 | 2-3% higher WR | HIGH |

**Total Phase 4.5 Cost:** +$0.12/month
**Total Phase 4.5 Expected Edge:** +3-5% improvement across all metrics
**ROI:** 1,000x

**Timeline:** 2-3 weeks (parallel with Phase 4 testing)

---

## **Phase 5: HYPERLIQUID MARKET INTELLIGENCE** (After Phase 4 goes live, 3-4 weeks)

**NOT PHASE 5 from original roadmap.** This is Hyperliquid-specific intelligence.

### **1. Symbol Rotation Detector**

**What:** Detect when market interest rotates (BTC → SOL → AVAX cycle)
**Why:** Catch momentum shifts before price moves
**Data:** Open interest by symbol, relative strength, funding rate spreads

**Agent: Symbol Rotator (Haiku)**
- Weekly analysis
- Detects: "Interest rotating from SOL to AVAX (OI +12% AVAX, -8% SOL)"
- Output: Which symbols to size up/down
- Cost: $0.002/week = $0.01/month
- Expected edge: 1-2% per month (catch rotation early)

---

### **2. Regime-Specific Strategy Selector**

**What:** Different strategies work in different regimes
**Why:** Scalping works in high_volatility, but fails in chop
**Data:** Current regime, strategy historical WR by regime

**Logic (Deterministic):**
```python
def get_strategy_weights_for_regime(regime, historical_perf):
    """
    Example:
    - trend regime: Scalping 60% WR, Conviction 75% WR → use both
    - range regime: Scalping 35% WR (bad), Conviction 65% WR → scalp less, conviction more
    - panic regime: Both underperform → reduce size
    """
    return regime_optimized_weights
```

**Expected edge:** 2-4% by avoiding strategies that don't work in current regime

---

### **3. Self-Teaching Curriculum (Advanced)**

**What:** Agents improve themselves continuously
**Why:** Each week, we learn what works better
**System:**
- Week 1: Baseline prompts
- Week 2: Analyze results, identify failures
- Week 3: Update prompts based on data
- Week 4+: Compounding improvements

**Example:**
- Regime Agent was 62% accurate on regime detection
- Analysis shows: "misses low_liquidity regime (44% accuracy)"
- Improvement: Add liquidity-specific rules to Regime Agent
- New accuracy: 68%

**Expected improvement:** 0.5-1% monthly (compounding)

---

## **Phase 5 Summary**

| Component | Cost/Month | Expected Edge | Timeline |
|-----------|-----------|---------------|----------|
| Symbol Rotator | $0.01 | 1-2% monthly | 1 week |
| Regime Optimizer | $0.00 | 2-4% better execution | 1 week |
| Self-Teaching | $0.01 | 0.5-1% monthly | Ongoing |

**Total Phase 5 Cost:** +$0.02/month
**Total Phase 5 Expected Edge:** 2-5% improvement
**ROI:** Unlimited (compounding)

**Timeline:** 3-4 weeks (after Phase 4 live)

---

## **THE COMPLETE SYSTEM** (Post-Phase 5)

### **Revenue Projections**

| Component | Frequency | Win Rate | Avg Profit | Monthly |
|-----------|-----------|----------|-----------|---------|
| **Scalping** | 100/day | 50% | 0.5% | $300 |
| **Conviction** | 7/month | 72% | 2% | $550 |
| **Liquidation** | 15/month | 60% | 1.2% | $200 |
| **OI Momentum** | 20/month | 55% | 0.8% | $150 |
| **Base Trend** | 4/day | 55% | 0.8% | $220 |
| **Symbol Rotation** | 2-3/month | 65% | 1.5% | $100 |
| **TOTAL** | ~150 trades | 56% avg | 0.9% avg | **$1,520** |

**Conservative Estimate:** $1,500-2,000/month
**Optimistic Estimate:** $3,000-5,000/month (if all edges compound)

**Total System Cost:** $3.00-3.50/month
**Monthly Profit/Cost Ratio:** 500-1,500x

---

## **Genius Quant System: Core Principles**

### **1. Reliability First**

- ✅ Every edge validated on historical data (minimum 20 trades)
- ✅ Every agent tested against paper trading benchmarks
- ✅ Every signal logged with full reasoning trail
- ✅ Every failure analyzed for systemic issues

### **2. Data Integrity**

- ✅ Hyperliquid data fetched every minute (no stale data)
- ✅ OHLCV validated against multiple sources
- ✅ Open interest, funding rates, liquidation maps verified
- ✅ All calculations double-checked (PnL math = critical)

### **3. Responsible Risk**

- ✅ No overleveraging (conviction only on >90% alignment)
- ✅ No overconfidence (discount confidence 10-20% as safety margin)
- ✅ Tight stops (0.1-0.3% risk per trade)
- ✅ Circuit breakers (daily loss limit, consecutive loss pause)

### **4. Continuous Learning**

- ✅ Weekly pattern analysis (what's working now?)
- ✅ Monthly strategy review (what should we change?)
- ✅ Quarterly curriculum advancement (agents improve)
- ✅ Ad-hoc debugging (when something breaks, root cause it)

### **5. Transparency**

- ✅ All trades logged: entry, exit, reasoning, outcome
- ✅ All failures analyzed: why did this fail? What's the lesson?
- ✅ All costs tracked: LLM spend, trading costs, net PnL
- ✅ All hypotheses tested: before adding to production

---

## **Implementation Timeline**

```
WEEK 1-3: Phase 4 Testing
├─ Unit tests (50+)
├─ 30-day backtest
├─ 2-week paper trading
└─ Go/no-go decision

WEEK 3-4: Phase 4.5 Build (Parallel)
├─ Liquidation Cascade Detector
├─ Funding Optimizer
├─ OI Momentum Analyzer
├─ Orderbook Analyzer
├─ Scalp Pattern Library
└─ Thesis Validator enhancement

WEEK 5-6: Phase 4.5 Testing
├─ Backtest all 6 components
├─ 2-week paper trading
└─ Integration with Phase 4

WEEK 6-8: Phase 5 Build
├─ Symbol Rotator
├─ Regime Optimizer
├─ Self-Teaching System
└─ Full system integration

WEEK 8+: Genius Quant System LIVE
├─ Continuous monitoring
├─ Weekly pattern analysis
├─ Monthly strategy review
└─ Quarterly advancement
```

**Total Timeline:** 8 weeks to fully deployed "Genius Quant" system on Hyperliquid

---

## **Success Metrics**

### **Short-Term (Phase 4, 3 weeks)**
- [ ] Scalp win rate ≥45%
- [ ] Conviction win rate ≥70%
- [ ] Combined Sharpe ≥1.2
- [ ] Max drawdown ≤15%

### **Medium-Term (Phase 4.5, 6 weeks)**
- [ ] System PnL ≥0.3%/day
- [ ] Sharpe ≥1.5
- [ ] Monthly revenue ≥$1,500
- [ ] Zero catastrophic failures

### **Long-Term (Phase 5, 8 weeks)**
- [ ] System PnL ≥0.5%/day
- [ ] Sharpe ≥1.8
- [ ] Monthly revenue ≥$2,500
- [ ] AI agents self-improving (prompt updates working)
- [ ] Thesis accuracy >65%

---

## **What We're NOT Doing**

❌ **NO cross-exchange arbitrage** (Hyperliquid-only)
❌ **NO pair trading** (too complex, Hyperliquid single-asset)
❌ **NO spot trading** (perpetuals only)
❌ **NO risky off-chain features** (stay on-exchange)
❌ **NO unvalidated hypotheses** (everything tested first)

---

## **What We ARE Doing**

✅ **Perfecting Hyperliquid** (single exchange mastery)
✅ **Scalping** (high frequency, tight stops)
✅ **Conviction trading** (rare, high-confidence)
✅ **Funding analysis** (perpetual-specific edge)
✅ **Liquidation prediction** (market microstructure)
✅ **Self-teaching** (agents improve weekly)
✅ **Data integrity** (every number verified)
✅ **Responsible risk** (never overlever, always safe)

---

## **The Vision**

Build a **"Genius Quant System"** that:

1. **Understands Hyperliquid deeply** — Better than any human trader
2. **Executes flawlessly** — Sub-second fills, minimal slippage
3. **Thinks multi-agent** — 10+ specialist agents working together
4. **Learns continuously** — Better each week than last
5. **Manages risk obsessively** — Never lose more than 15%
6. **Trades with conviction** — Only fire when ALL signals align
7. **Scales gracefully** — 100+ trades/day without degradation
8. **Earns reliably** — $1,500-3,000/month consistently

---

**This is not a get-rich-quick scheme. This is a genuine quant system built on sound edge theory, continuous validation, and obsessive reliability.**

**By Week 8, you'll have a system that knows Hyperliquid better than 99% of traders.**

---

**Last Updated:** 2026-03-20
**Status:** Ready to execute
