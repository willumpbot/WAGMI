# LIVE THIS WEEK: Fast-Track Deployment Plan

**Timeline:** Deploy to paper TODAY. Go live after 20-30 real trades (~2-3 days).
**Approach:** Real market validation only. No LLM backtests. No multi-week testing.
**Philosophy:** The market is the backtest. 20-30 trades will tell us everything.

---

## **PHASE 4 DEPLOYMENT: SIMPLIFIED**

### **What Ships This Week**

**Minimum Viable System:**
- ✅ Micro-Trend Detector (5m classification)
- ✅ Scalper Agent (1m scalp signals)
- ✅ Conviction Agent (alignment checker)
- ✅ Paper trading mode enabled
- ✅ Real-time trade logging
- ✅ Simple monitoring dashboard

**What We Skip:**
- ❌ Lengthy backtests (already done, proven edge theory)
- ❌ Multi-week paper trading (costly, unnecessary)
- ❌ "Perfect code" phase (good enough works)
- ❌ Exhaustive testing (real trades are the test)

---

## **DEPLOYMENT CHECKLIST: 3 DAYS**

### **Day 1 (Today): Code Ready**

- [ ] Phase 4 agents in coordinator
- [ ] All imports working (no crashes)
- [ ] Paper trading mode enabled
- [ ] Trade logging to `decisions.jsonl`
- [ ] Real-time monitoring dashboard starts

**Acceptance:** System boots without errors

---

### **Day 2-3: Live in Paper**

**Enable on SOL only (single symbol):**
- Micro-Trend runs every 5m
- Scalper runs every 1m
- Conviction checks every signal
- All trades logged with full context

**Monitor:**
- Every signal: timestamp, confidence, reasoning
- Every trade: entry, exit, PnL
- Every error: logged immediately
- Win rate: Track in real-time

**Expected:** 20-30 trades over 48 hours of active trading

---

## **GO/NO-GO GATE (After 20-30 Trades)**

### **ONLY 2 Questions:**

1. **Did it work in real market?**
   - Win rate ≥40% (scalp) or ≥60% (conviction)?
   - Yes → Go live
   - No → Iterate, retry on paper

2. **Any execution bugs?**
   - System stable?
   - Orders filled as expected?
   - Monitoring data clean?
   - Yes → All good
   - No → Fix, retry on paper

### **That's it. No other criteria.**

---

## **REAL-TIME MONITORING: Simple Dashboard**

### **What We Track (Live)**

```
┌─────────────────────────────────────────────┐
│ PHASE 4 SYSTEM - LIVE MONITORING            │
├─────────────────────────────────────────────┤
│                                             │
│ TRADES TODAY: 23                            │
│ Win Rate: 52% (12W / 11L)                   │
│ Avg Win: 0.65%  Avg Loss: 0.42%             │
│ Expected Daily: +0.25%                      │
│                                             │
│ LAST 5 TRADES:                              │
│ ✅ Scalp 1m: +0.52% (RSI 18→45)             │
│ ✅ Scalp 1m: +0.68% (volume spike)          │
│ ❌ Scalp 1m: -0.41% (false bounce)          │
│ ✅ Conviction: +1.2% (alignment 0.92)       │
│ ✅ Scalp 1m: +0.45% (exhaustion fade)       │
│                                             │
│ SYSTEM HEALTH:                              │
│ Avg Latency: 180ms ✅                       │
│ Fill Rate: 98% ✅                           │
│ Errors: 0 ✅                                │
│ Slippage Actual: 0.08% (expected 0.10%) ✅  │
│                                             │
└─────────────────────────────────────────────┘
```

### **Key Metrics (Updated Every Trade)**

```python
# Real-time tracking
trades_today = 23
wins = 12
losses = 11
win_rate = 52%
avg_win = 0.65%
avg_loss = 0.42%
expected_daily = (0.52 * 0.65%) - (0.48 * 0.42%) = +0.25%

# System health
avg_latency_ms = 180
fill_rate = 0.98
execution_errors = 0
slippage_vs_expected = 0.08% vs 0.10%

# Confidence in edge
confidence = "MEDIUM" (23 trades, 52% WR, need >30 for high confidence)
```

---

## **DECISION FRAMEWORK: 20-30 Trades**

### **Go Live If:**

```
Win Rate ≥40% (scalp) OR ≥60% (conviction) ?
├─ YES → Go live (expected value proven in real market)
└─ NO  → Iterate on paper, retry

System Stable (no crashes, fills working) ?
├─ YES → Go live
└─ NO  → Fix bugs, retry on paper

Slippage Reasonable (actual ~= expected) ?
├─ YES → Go live
└─ NO  → Adjust sizing down, retry on paper
```

### **Do NOT Go Live If:**

```
Win Rate <40% on 20+ trades ?
└─ NO-GO: Edge doesn't exist in real market. Back to drawing board.

Execution Bugs Found ?
└─ NO-GO: Fix, then retry on paper. Never go live with known bugs.

Slippage 2x Expected ?
└─ NO-GO: Position sizing too large. Reduce 50%, retry on paper.
```

---

## **PAPER → LIVE TRANSITION: 1 Hour**

### **Once Gate Passes (20-30 trades, WR≥40%)**

**Hour 1: Live with Minimum Risk**

```python
# Position sizing (TINY to start)
risk_per_trade = 0.01% of account (minimum)
max_daily_risk = 0.05% of account
max_position = $100 (test fills, execution)

# Monitoring
Track every trade
Alert on ANY error
Kill switch ready (Ctrl+C kills all orders)

# Success Criteria (First 10 trades)
Same win rate as paper?
  ├─ YES → Scale to 0.05% per trade
  └─ NO  → Something's different, debug

Same execution quality?
  ├─ YES → Proceed
  └─ NO  → Check market conditions, latency
```

**Hour 2-24: Monitor Closely**

```
After 10 live trades:
- Compare to paper (should be similar)
- If WR matches paper: Scale to 0.1% per trade
- If WR diverges >10%: Something's wrong, investigate

After 50 live trades:
- If WR>40% and stable: Scale to full position sizing (0.3% per trade)
- If WR degrading: Reduce back to 0.05%, debug
```

---

## **WHAT EACH NUMBER MEANS**

### **Win Rate (Real Validator)**

```
20 trades, 50% WR = "Maybe an edge" (could be luck)
30 trades, 50% WR = "Probably an edge" (less likely luck)
50 trades, 50% WR = "Definitely an edge" (statistically significant)
100+ trades, 45% WR = "Confirmed edge" (consistent, real)

For go/no-go: 20-30 trades at ≥40% WR = GOOD ENOUGH to go live
```

### **Sharpe Ratio (Risk-Adjusted Return)**

```
Sharpe = (avg_daily_pnl - risk_free_rate) / std_dev(daily_pnl)

Target: >1.0 (means 1% return for 1% risk)
Paper Sharpe: 1.2-1.5 (expected)
Live Sharpe: Should match paper (if execution is similar)

If live Sharpe <0.8: Something wrong, debug
```

### **Max Drawdown (Worst-Case Loss)**

```
Expected: <15% (based on 0.3% risk per trade)
Paper: Should show <5% drawdown on 30 trades
Live: Will vary, but shouldn't exceed paper by >2x

If live drawdown >10%: Reduce risk, debug
```

---

## **REAL TRADE CHECKLIST: Per Signal**

### **Every Time System Generates Signal:**

```json
{
  "timestamp": "2026-03-20 14:32:45",
  "symbol": "SOL",
  "signal_type": "scalp|conviction",
  "confidence": 0.68,
  "entry_price": 125.42,
  "target_price": 125.68,
  "stop_loss": 125.32,
  "expected_rr": 2.6,
  "thesis": "RSI=18, volume>1.5x, bouncing_from_low",
  "status": "FIRED|REJECTED",
  "reject_reason": "confidence too low"
}
```

### **Every Trade That Executes:**

```json
{
  "timestamp": "2026-03-20 14:32:46",
  "entry_filled": 125.43,
  "actual_slippage": 0.01,
  "position_size": "$100",
  "hold_time": 120,
  "exit_filled": 125.67,
  "pnl": 0.52,
  "pnl_pct": 0.65,
  "status": "WIN|LOSS",
  "reason": "hit_tp|hit_sl|manual"
}
```

### **Analysis (End of Day):**

```
Signals generated: 47
Signals fired: 23
Win trades: 12
Loss trades: 11
Win rate: 52%

By type:
Scalp: 18 trades, 50% WR
Conviction: 5 trades, 80% WR
```

---

## **FAST-TRACK DECISION TREE**

```
Monday Morning: Deploy to paper on SOL
                ↓
Tuesday/Wednesday: Monitor 20-30 trades
                ↓
                Win Rate ≥40%? ─→ YES ─→ Any bugs? ─→ NO ─→ GO LIVE
                     ↓                                      (Wed evening)
                    NO
                     ↓
              Fix + retry on paper
                     ↓
              Another 20 trades
                ↓
         Win Rate ≥40%? ─→ YES ─→ GO LIVE
              ↓
             NO ─→ Go back to development
```

---

## **RISK MANAGEMENT: Live Money**

### **Start Tiny**

```
First 10 trades (live): 0.01% risk per trade
  - Goal: Prove execution works
  - Position size: ~$100

Trades 11-50 (live): 0.05% risk per trade
  - Goal: Prove WR matches paper
  - Position size: ~$500

Trades 51+ (live): 0.1-0.3% risk per trade
  - Goal: Scale to target position size
  - Position size: $1,000-3,000
```

### **Kill Switches**

```
If any single trade: Loss > 1% of account → KILL SYSTEM (manual override)
If daily loss > 0.5% of account → PAUSE trading (circuit breaker)
If 3 consecutive losses → PAUSE 1 hour (emotional recovery)
If win rate drops <35% on rolling 20 trades → PAUSE, debug
```

---

## **EXPECTED OUTCOMES**

### **Best Case (System Works)**

```
Paper: 23 trades, 52% WR, +0.25% daily = +$250/day potential
Live:  First 10 trades match paper (50% WR)
       → Scale to 0.05% risk
       → Expected daily: +$100-200/day
       → Month 1 live: $2,000-6,000 profit

This is the dream. Execute with discipline.
```

### **Moderate Case (System Partially Works)**

```
Paper: 30 trades, 45% WR, +0.15% daily
Live:  Matches paper (45% WR)
       → Scale carefully (0.05% risk)
       → Expected daily: $50-100/day
       → Month 1: $1,000-3,000 profit

Still profitable. Not amazing, but real.
```

### **Worst Case (System Doesn't Work)**

```
Paper: 25 trades, 38% WR, -0.05% daily
Live:  Matches paper (38% WR)
       → Expected: Small losses
       → Decision: Kill system, back to development
       → Month 1: Learn what was wrong, iterate

This is OK. Better to find out on $100 trades than $10k trades.
```

---

## **SUCCESS DEFINITION**

### **After 20-30 Paper Trades:**

You have ONE of three outcomes:

1. **✅ GO LIVE** (Win rate ≥40%, no bugs)
   - Deploy with minimum risk ($100 positions)
   - Scale based on real results
   - Target: $1,000-5,000/month by month 3

2. **🔄 ITERATE** (Win rate 35-40%, some promise)
   - Fix + retry on paper (another 20 trades)
   - Adjust confidence gates, sizing
   - Go live once >40% confirmed

3. **❌ BACK TO DEVELOPMENT** (Win rate <35%, no edge)
   - Edge doesn't exist in real market
   - Debug prompts, logic
   - Rebuild and retry

---

## **THE REAL TRUTH**

**20-30 real trades > 60-day LLM backtest**

Real market will tell you EVERYTHING:
- Does the edge exist? (Win rate)
- Can we execute? (Slippage, fills)
- Is the system stable? (No crashes)
- Are we ready? (Yes or no)

**LLM backtests cost $10 and lie. Real trades cost nothing and tell the truth.**

---

**Monday: Deploy to paper on SOL**
**Wednesday: Make go/no-go decision**
**Thursday: Live with real money (if gate passes)**

That's the timeline. That's how serious quants operate.

Ready to ship?

---

**Last Updated:** 2026-03-20
**Status:** Ready to deploy
**Deployment:** THIS WEEK
