# Profitability Roadmap — From Code to Cash

> Written 2026-03-09. Every phase must prove profitability before advancing.
> **Philosophy: No shortcuts. Prove the edge at every layer before adding the next.**

---

## Current State (March 9, 2026)

**What's built:**
- 3 active strategies (regime_trend PF=2.0, confidence_scorer PF=1.27, multi_tier_quality PF=1.25; monte_carlo disabled PF=0.0)
- 6-gate RiskFilterChain with MTM-aware circuit breakers (just fixed)
- Multi-agent LLM system (5 agents: Regime, Trade, Risk, Critic, Learning + Exit agent)
- Order execution layer (paper + live modes via CCXT/Hyperliquid)
- Position manager with state machine, trailing stops, trade profiles
- Deep memory + self-teaching + growth orchestrator
- 999 tests passing, 0 failures

**What's unproven:**
- No 180-day backtest with all recent fixes
- No paper trading validation on live prices
- LLM agents never tested against live market conditions
- Multi-agent vs monolithic vs no-LLM: no comparative data
- Strategy performance in 2026 market conditions unknown

---

## PHASE 1: PROVE THE BASELINE (No LLM)

> **Goal:** Confirm strategies are profitable *without* any LLM involvement.
> If the base isn't profitable, adding LLM is lipstick on a pig.

### 1A. Full Historical Backtest (180-day, all fixes applied)
- [ ] Run backtest: SOL, HYPE, ETH — 180 days with ALL profitability fixes
- [ ] Compare to pre-fix 180d baseline (if available)
- [ ] **Pass criteria:**
  - Sharpe > 1.0 (risk-adjusted return beats buy-and-hold)
  - Max drawdown < 15%
  - Profit factor > 1.3 across all symbols combined
  - Win rate > 40% (with R:R > 1.5, 40% WR is profitable)
  - Fee drag < 25% of gross profit
  - At least 50 trades per symbol (statistical significance)

### 1B. Regime-Segmented Analysis
- [ ] Break backtest results by regime (trend, range, high_vol, panic)
- [ ] Identify which strategies win/lose in each regime
- [ ] **Key question:** Are there regimes where ALL strategies lose? If yes, the bot should sit out those regimes entirely (regime filter before ensemble)
- [ ] Map strategy performance by:
  - Hour of day (funding rate resets at 00:00/08:00/16:00 UTC)
  - Day of week (weekend vs weekday volume differences)
  - Volatility bucket (low/med/high ATR)

### 1C. Out-of-Sample Validation
- [ ] Split 180 days: train on first 120, validate on last 60
- [ ] If strategy parameters were tuned on the full 180d, results are overfitted
- [ ] **Pass criteria:** Out-of-sample Sharpe within 50% of in-sample
- [ ] If OOS degrades >50%, the strategies are overfit → must retune on training set only

### 1D. Monte Carlo Stress Testing
- [ ] Randomize trade order (1000 permutations) → confidence interval for final equity
- [ ] Simulate 3x fee drag (15 bps → 45 bps) → still profitable?
- [ ] Simulate 2x slippage → still profitable?
- [ ] Simulate funding rate bleed (0.03%/8h on all positions) → what's the break-even hold time?

### 1E. Fix What Backtest Reveals
- [ ] Tune strategy parameters based on 120d training set
- [ ] Re-validate on 60d OOS
- [ ] If a strategy has PF < 1.0 across all regimes → disable it (like monte_carlo)
- [ ] If ensemble is too aggressive in certain regimes → add regime-based ensemble weight adjustment

**Exit criteria for Phase 1:**
```
✓ 180d backtest with all fixes: Sharpe > 1.0, PF > 1.3, DD < 15%
✓ OOS validation: Sharpe within 50% of in-sample
✓ Regime analysis: know where we win and where we bleed
✓ Stress test: profitable at 3x fees and 2x slippage
```

---

## PHASE 2: PROVE THE LLM ADDS VALUE

> **Goal:** Quantify exactly how much (or how little) the LLM improves results.
> Run the same backtest with LLM in ADVISORY mode — it sees everything, touches nothing.

### 2A. LLM Advisory Backtest (Offline Replay)
- [ ] Replay the 180d backtest data through the multi-agent pipeline
- [ ] LLM sees every signal but CANNOT influence execution (ADVISORY mode)
- [ ] Log every LLM decision: go/skip/flip, confidence, regime classification
- [ ] After replay, compare:
  - Trades LLM would have vetoed → were they losers? (veto accuracy)
  - Trades LLM would have flipped → would the flip have been profitable? (flip accuracy)
  - Regime classifications → did they match actual regime changes?
  - Confidence adjustments → did higher LLM confidence correlate with higher WR?

### 2B. Quantify LLM Edge
- [ ] **Veto value:** Sum PnL of trades LLM would have vetoed. If negative → LLM saves money
- [ ] **Sizing value:** Compare LLM-suggested sizes vs baseline fixed sizes → which equity curve is better?
- [ ] **Regime value:** When LLM correctly identifies regime shift → are the next 5 trades more profitable?
- [ ] Calculate: LLM cost per month vs LLM value per month
  - Break-even: LLM must save/earn more than its API cost (~$120-600/mo depending on tier)
  - If LLM costs $130/mo but only saves $80/mo in avoided losers → net negative

### 2C. Agent-Level Attribution
- [ ] Which agents add the most value?
  - Regime Agent: Does its regime classification predict next-5-trade PnL?
  - Trade Agent: Does go/skip accuracy exceed ensemble-only?
  - Risk Agent: Does its sizing improve Sharpe vs fixed sizing?
  - Critic Agent: Does its veto save money or kill winners?
  - Learning Agent: Does memory-informed trading improve over time?
- [ ] If an agent adds no value → demote to Haiku or disable
- [ ] If an agent is actively harmful (Critic vetoes too many winners) → retune prompt

### 2D. LLM Architecture Decision: Queen Bee Model
Your insight about queen/worker bee architecture is exactly right. Based on 2A-2C data:

**Option A: Hierarchical (Queen Bee)**
```
Opus (Queen) — runs 1x/hour or on regime shift
  ├── Sets regime classification (authoritative)
  ├── Sets portfolio-level strategy (risk appetite, sector bias)
  ├── Issues standing orders ("avoid BTC longs until funding normalizes")
  └── Reviews worker decisions every N trades

Haiku (Workers) — run on every signal
  ├── Execute within Queen's framework
  ├── Quick go/skip decisions against standing orders
  ├── Flag exceptions that need Queen review
  └── Cheap enough to run on every candle ($0.0001/call)
```

**Estimated cost:** Opus 24 calls/day × $0.015 = $0.36/day + Haiku 400 calls/day × $0.0001 = $0.04/day = **~$12/month** (vs current ~$120/month)

**Option B: Current Multi-Agent (Democratic)**
```
Regime (Haiku) → Trade (Sonnet) → Risk (Haiku) → Critic (Sonnet)
Cost: ~$0.01/decision × 400/day × 30 = ~$120/month
```

**Option C: Hybrid**
```
Opus (Queen) — sets strategic context 1x/hour
Haiku workers — execute per-signal decisions within context
Sonnet (Specialist) — called only for high-value triggers (regime shifts, large positions)
Estimated: ~$30-50/month
```

**Decision:** Phase 2B data will show which option maximizes (LLM value - LLM cost).

**Exit criteria for Phase 2:**
```
✓ LLM veto accuracy > 60% (more losers vetoed than winners)
✓ LLM-assisted backtest Sharpe > baseline Sharpe by > 10%
✓ LLM cost < LLM value (positive ROI on API spend)
✓ Architecture decision made (queen bee vs democratic vs hybrid)
```

---

## PHASE 3: BACKTEST WITH CHOSEN LLM ARCHITECTURE

> **Goal:** Run full backtest with the LLM architecture chosen in Phase 2.

### 3A. Implement Queen Bee (if chosen)
- [ ] Create `bot/llm/agents/queen.py` — Opus strategic agent
  - Runs on schedule (1x/hour) + on-demand (regime shift, large drawdown)
  - Outputs: regime mandate, risk appetite, sector directives, standing orders
  - Standing orders persist until explicitly revoked or expired
- [ ] Create `bot/llm/agents/worker.py` — Haiku execution agents
  - Receive Queen's context as system prompt prefix
  - Quick go/skip/size decisions within Queen's framework
  - Flag out-of-mandate situations for Queen review
- [ ] Modify coordinator to support hierarchical pipeline
- [ ] Add cost tracking per tier (Queen vs Worker separation)

### 3B. Full Pipeline Backtest
- [ ] 180d backtest with full LLM pipeline (cached/mocked responses for reproducibility)
- [ ] Compare three curves:
  1. Baseline (strategies only, no LLM)
  2. Current multi-agent
  3. New architecture (queen bee or chosen option)
- [ ] **Pass criteria:**
  - New architecture curve > baseline curve (higher Sharpe, lower DD)
  - Cost per trade < value per trade
  - No regime where LLM makes things worse

### 3C. Sensitivity Analysis
- [ ] What happens when LLM API goes down? (fallback to baseline — must still be profitable)
- [ ] What happens when LLM hallucinates? (confidence caps, flip rate limits)
- [ ] What happens when LLM latency spikes? (timeout + fallback)
- [ ] What happens at different autonomy levels? (VETO_ONLY vs SIZING vs DIRECTION)

**Exit criteria for Phase 3:**
```
✓ Full pipeline backtest: Sharpe improvement > 15% vs baseline
✓ Max drawdown with LLM <= max drawdown without LLM
✓ Fallback to baseline is seamless and still profitable
✓ Cost per month < 20% of expected monthly profit
```

---

## PHASE 4: PAPER TRADING (Live Prices, No Real Money)

> **Goal:** Validate that backtest results reproduce on live market data.

### 4A. Paper Trade Without LLM (1-2 weeks)
- [ ] Set `ENVIRONMENT=paper`, connect to Hyperliquid API
- [ ] Run on SOL, HYPE (most liquid, most backtest data)
- [ ] Compare paper results to backtest for the same period
- [ ] **Pass criteria:**
  - Paper equity curve within ±5% of backtest equity curve
  - Trade count within ±20% of backtest
  - If divergence > 10% → find the gap (slippage? data lag? timing?)

### 4B. Paper Trade With LLM in VETO_ONLY (2-4 weeks)
- [ ] Enable `LLM_MULTI_AGENT=true`, `LLM_MODE=VETO_ONLY`
- [ ] LLM can reject trades but cannot initiate, flip, or size
- [ ] Track:
  - How many trades vetoed per day
  - PnL of vetoed trades (would they have won or lost?)
  - Regime classification accuracy vs actual price action
  - LLM latency impact on execution timing
  - API cost per day
- [ ] **Pass criteria:**
  - Veto accuracy > 55% (more losers caught than winners killed)
  - Total PnL with LLM >= PnL without LLM
  - API cost < daily expected profit
  - No system crashes or unhandled exceptions over 2 weeks

### 4C. Paper Trade With Full LLM (2-4 weeks)
- [ ] Increase to `LLM_MODE=SIZING` for 1 week, then `DIRECTION` for 1 week
- [ ] At each level, compare to VETO_ONLY results
- [ ] If a higher autonomy level hurts performance → stay at the lower level
- [ ] **Pass criteria per level:**
  - SIZING: Sharpe >= VETO_ONLY Sharpe
  - DIRECTION: Sharpe >= SIZING Sharpe AND flip accuracy > 55%

### 4D. Production Hardening During Paper
- [ ] Wire position reconciliation (handle bot restart)
- [ ] Test stale data handling (kill API connection, verify bot pauses trading)
- [ ] Test circuit breaker triggers on live data
- [ ] Verify Telegram/Discord alerts fire correctly
- [ ] Monitor memory usage, log file sizes, disk space over 2 weeks
- [ ] Test graceful shutdown and restart (no orphaned positions)

**Exit criteria for Phase 4:**
```
✓ 2+ weeks paper trading with consistent profitability
✓ Paper results within ±10% of backtest expectations
✓ No system crashes over full paper period
✓ LLM adds measurable value at chosen autonomy level
✓ All production hardening items checked
```

---

## PHASE 5: COPY TRADING + SMALL LIVE

> **Goal:** Start risking real capital at minimal size while maintaining paper as control.

### 5A. Parallel Run (Paper + Live Mirror)
- [ ] Run TWO instances simultaneously:
  - Instance 1: Paper trading (control — continues from Phase 4)
  - Instance 2: Live trading with $1,000-$2,000 capital
- [ ] Live instance mirrors paper decisions but with real execution
- [ ] Compare fills: live slippage vs paper slippage
- [ ] **Pass criteria:**
  - Live fills within 5 bps of paper fills
  - No unexpected order rejections
  - Exchange API stable over 48h+ continuous operation

### 5B. Conservative Live Parameters
```
Risk per trade:      1% (not 2%)
Max leverage:        2x (not 25x)
Max open positions:  2 (not 3)
Symbols:            SOL, HYPE only
LLM mode:           VETO_ONLY (safest proven level)
Circuit breaker:     3% daily loss limit (not 5%)
```

### 5C. Scale Decision Framework
After 2+ weeks of profitable live trading:

| Metric | Maintain | Scale Up | Scale Down |
|--------|----------|----------|------------|
| Weekly PnL | Positive 2/3 weeks | Positive 3/3 weeks | Negative 2/3 weeks |
| Max drawdown | < 5% | < 3% | > 7% |
| Win rate | > 40% | > 50% | < 35% |
| Sharpe (annualized) | > 1.0 | > 2.0 | < 0.5 |
| LLM ROI | Positive | > 3x cost | Negative |

**Scale-up sequence:**
1. $1-2k → $5k (after 2 profitable weeks)
2. $5k → $10k (after 4 profitable weeks)
3. $10k → $25k (after 8 profitable weeks)
4. $25k → target allocation (after 3 profitable months)

At each step: increase risk_per_trade by 0.5%, increase max_leverage by 0.5x, add 1 symbol.

**Exit criteria for Phase 5:**
```
✓ 2+ weeks live trading with positive PnL
✓ Live results within ±15% of paper results
✓ No exchange API issues, no orphaned positions
✓ Scale-up criteria met for next tier
```

---

## PHASE 6: FULL LIVE + CONTINUOUS IMPROVEMENT

> **Goal:** Run at target allocation with continuous monitoring and improvement.

### 6A. Full Live Trading
- [ ] Target allocation deployed
- [ ] All symbols active (SOL, HYPE, ETH, BTC)
- [ ] LLM at optimal autonomy level (determined by Phase 4)
- [ ] Daily monitoring dashboard active
- [ ] Alert system for anomalies (Telegram/Discord)

### 6B. Continuous Improvement Loop
```
Weekly:
  - Review trade log, identify worst 3 trades
  - Check regime classification accuracy
  - Compare actual vs expected PnL
  - LLM cost audit

Monthly:
  - Full backtest with latest 30d data (walk-forward)
  - Strategy weight analysis (is one strategy dominating?)
  - LLM agent calibration check
  - Parameter sensitivity analysis
  - Out-of-sample validation on new data

Quarterly:
  - Consider new strategies (funding rate, order flow)
  - Evaluate new LLM models (cost/performance ratio)
  - Review and prune deep memory
  - Consider adding new symbols
```

### 6C. New Alpha Sources (Future)
- [ ] Funding rate strategy (counter-trade extreme funding)
- [ ] Order flow analysis (Hyperliquid L2 data)
- [ ] Cross-exchange arbitrage signals
- [ ] Telegram/Discord signal ingestion (already scaffolded)
- [ ] Strategy discovery agent activation

---

## PHASE DEPENDENCIES

```
Phase 1 (Baseline Backtest)
  ↓ must prove profitability
Phase 2 (LLM Value Quantification)
  ↓ must prove LLM adds value
Phase 3 (Full Pipeline Backtest)
  ↓ must prove architecture works
Phase 4 (Paper Trading)
  ↓ must match backtest within ±10%
Phase 5 (Small Live)
  ↓ must prove live execution works
Phase 6 (Full Live)
```

**No skipping phases.** Each phase's exit criteria must be met before advancing.
If any phase fails, go back to the previous phase, fix the issue, and re-validate.

---

## RISK BUDGET

| Risk Category | Budget | Mitigation |
|---------------|--------|------------|
| Strategy degradation | Sharpe drops below 0.5 | Pause trading, re-backtest, retune |
| LLM hallucination | Single bad trade > 3% equity | Confidence caps, flip rate limits, CB |
| Exchange risk | Hyperliquid downtime | Auto-pause on stale data, multi-exchange future |
| LLM cost overrun | API bill > monthly profit | Cost tracker hard limits, downgrade to Haiku |
| Overfitting | OOS Sharpe < 50% of IS Sharpe | Walk-forward validation, regime-segmented analysis |
| Correlation blowup | All positions move against | Max 2-3 positions, correlation guard, MTM CB |

---

## ESTIMATED TIMELINE

| Phase | Duration | Dependency |
|-------|----------|------------|
| Phase 1: Baseline Backtest | 1-3 days (compute) | None |
| Phase 2: LLM Value Proof | 1-2 days (replay + analysis) | Phase 1 pass |
| Phase 3: Full Pipeline Backtest | 1-2 days | Phase 2 architecture decision |
| Phase 4: Paper Trading | 4-8 weeks | Phase 3 pass |
| Phase 5: Small Live | 4-8 weeks | Phase 4 pass |
| Phase 6: Full Live | Ongoing | Phase 5 scale criteria |

**Total to first dollar at risk: ~2-4 months of validation.**
This is conservative. Rushing to live trading is how bots lose money.

---

*This document supplements ROADMAP.md with a profitability-focused sequence.
ROADMAP.md covers the full technical buildout; this document covers the validation path to real money.*
