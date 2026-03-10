# Profitability Roadmap — From Code to Cash

> Updated 2026-03-10. Every phase must prove profitability before advancing.
> **Philosophy: Test at the same parameters you'll trade at. No watered-down validation.**

---

## Current State (March 10, 2026)

**What's built:**
- 3 active strategies (regime_trend, confidence_scorer, multi_tier_quality; monte_carlo disabled)
- Each strategy toggleable via `STRATEGY_*_ENABLED` env vars
- 6-gate RiskFilterChain with MTM-aware circuit breakers
- Regime filter: blocks trades in ranging markets (29% WR → skipped)
- Multi-agent LLM system (7 agents: Regime, Trade, Risk, Critic, Learning, Exit, Scout)
- Order execution layer (paper + live modes via CCXT/Hyperliquid)
- Position manager with state machine, trailing stops, trade profiles
- Deep memory + self-teaching + growth orchestrator
- 999 tests passing, 0 failures

**Recent fixes (March 10):**
- [x] Regime filter: skip ranging markets (was 75% of trades, 29% WR)
- [x] Confidence floor raised 70→75 (everything <80% was losing)
- [x] TP asymmetry: TP1 1.5R→2.0R, TP2 3.0R→4.0R (payoff was 1.03:1)
- [x] confidence_scorer: require ADX >= 20 (was allowing 0-trend trades)
- [x] confidence_scorer: 6h filter AND→OR (was letting counter-trend trades through)
- [x] Strategy enable/disable env vars for all strategies

**What needs proving:**
- Do these fixes actually improve the 10d backtest?
- 30d+ backtest to get statistical significance
- OOS validation to confirm we're not overfitting
- LLM value quantification

---

## PHASE 1: PROVE THE BASELINE (No LLM)

> **Goal:** Confirm strategies are profitable *without* any LLM involvement.
> If the base isn't profitable, adding LLM is lipstick on a pig.

### 1A. Backtests With All Fixes
- [ ] Re-run 10d backtest with regime filter + TP asymmetry + confidence_scorer fixes
- [ ] Run 30d backtest: SOL, HYPE, BTC — enough trades for statistical significance
- [ ] Run 90d backtest: same symbols — confirm edge persists across market conditions
- [ ] **Pass criteria:**
  - Sharpe > 1.0 (risk-adjusted return beats buy-and-hold)
  - Max drawdown < 20%
  - Profit factor > 1.3 across all symbols combined
  - Win rate > 35% (with R:R >= 2.0, 35% WR is profitable)
  - Fee drag < 25% of gross profit
  - At least 30 trades per symbol (statistical significance)

### 1B. Regime-Segmented Analysis
- [x] Regime filter implemented — ranging markets blocked
- [ ] Break backtest results by regime (trending_bull, trending_bear, mixed)
- [ ] Identify which strategies win/lose in each remaining regime
- [ ] Map strategy performance by:
  - Volatility bucket (low/med/high ATR)
  - Symbol characteristics (BTC vs altcoins)

### 1C. Out-of-Sample Validation
- [ ] Split 90d: train on first 60, validate on last 30
- [ ] **Pass criteria:** Out-of-sample Sharpe within 50% of in-sample
- [ ] If OOS degrades >50%, strategies are overfit → retune on training set only

### 1D. Strategy-Level Decisions
- [ ] If confidence_scorer still PF < 1.0 after fixes → disable via env var, re-test
- [ ] If multi_tier_quality still PF < 1.0 → same treatment
- [ ] Test: regime_trend solo vs 2-strategy vs 3-strategy ensemble
- [ ] Find the minimum viable ensemble that's actually profitable

**Exit criteria for Phase 1:**
```
✓ 30d+ backtest: Sharpe > 1.0, PF > 1.3, DD < 20%
✓ OOS validation: Sharpe within 50% of in-sample
✓ Regime analysis: know where we win and where we bleed
✓ Each active strategy individually PF > 1.0
```

---

## PHASE 2: PROVE THE LLM ADDS VALUE

> **Goal:** Quantify exactly how much (or how little) the LLM improves results.
> Run the same backtest with LLM in ADVISORY mode — it sees everything, touches nothing.

### 2A. LLM Advisory Backtest (Offline Replay)
- [ ] Replay the 90d backtest data through the multi-agent pipeline
- [ ] LLM sees every signal but CANNOT influence execution (ADVISORY mode)
- [ ] Log every LLM decision: go/skip/flip, confidence, regime classification
- [ ] After replay, compare:
  - Trades LLM would have vetoed → were they losers? (veto accuracy)
  - Trades LLM would have flipped → would the flip have been profitable?
  - Regime classifications → did they match actual regime changes?

### 2B. Quantify LLM Edge
- [ ] **Veto value:** Sum PnL of trades LLM would have vetoed. Negative = LLM saves money
- [ ] **Sizing value:** Compare LLM-suggested sizes vs baseline fixed sizes
- [ ] Calculate: LLM cost per month vs LLM value per month
  - Break-even: LLM must save/earn more than its API cost

### 2C. Architecture Decision: Queen Bee vs Democratic

**Option A: Hierarchical (Queen Bee) — ~$12/month**
```
Opus (Queen) — runs 1x/hour or on regime shift
  ├── Sets regime classification (authoritative)
  ├── Sets portfolio-level strategy (risk appetite)
  ├── Issues standing orders
  └── Reviews worker decisions every N trades
Haiku (Workers) — run on every signal (~$0.0001/call)
```

**Option B: Current Multi-Agent — ~$120/month**
```
Regime (Haiku) → Trade (Sonnet) → Risk (Haiku) → Critic (Sonnet)
```

**Option C: Hybrid — ~$30-50/month**
```
Opus (Queen) 1x/hour + Haiku workers + Sonnet for high-value triggers
```

Decision driven by Phase 2B data: which maximizes (LLM value - LLM cost).

**Exit criteria for Phase 2:**
```
✓ LLM veto accuracy > 60%
✓ LLM-assisted Sharpe > baseline Sharpe by > 10%
✓ LLM cost < LLM value (positive ROI)
✓ Architecture decision made
```

---

## PHASE 3: FULL PIPELINE BACKTEST

> **Goal:** Run full backtest with the LLM architecture chosen in Phase 2.

### 3A. Implement Chosen Architecture
- [ ] Build it (queen bee / hybrid / keep current)
- [ ] Add cost tracking per tier

### 3B. Full Pipeline Backtest
- [ ] 90d backtest with full LLM pipeline
- [ ] Compare three curves: baseline / current multi-agent / new architecture
- [ ] **Pass criteria:**
  - New architecture Sharpe > baseline Sharpe
  - Cost per trade < value per trade

### 3C. Resilience Testing
- [ ] LLM API down → fallback to baseline (must still be profitable)
- [ ] LLM hallucination → confidence caps, flip rate limits
- [ ] LLM latency spike → timeout + fallback

**Exit criteria for Phase 3:**
```
✓ Full pipeline Sharpe improvement > 15% vs baseline
✓ Max DD with LLM <= Max DD without LLM
✓ Fallback is seamless and profitable
```

---

## PHASE 4: PAPER TRADING (Live Prices, No Real Money)

> **Goal:** Validate that backtest results reproduce on live market data.
> **Use the SAME parameters we'll trade live with. No artificial safety nets.**

### 4A. Paper Trade Without LLM (3-5 days)
- [ ] Set `ENVIRONMENT=paper`, connect to Hyperliquid API
- [ ] Run on SOL, HYPE, BTC — same symbols, same params as backtest
- [ ] **Same risk_per_trade, same leverage, same everything**
- [ ] **Pass criteria:**
  - Paper equity curve within ±10% of backtest equity curve
  - Trade count within ±20% of backtest
  - If divergence > 15% → find the gap (slippage? data lag? timing?)

### 4B. Paper Trade With LLM (5-7 days)
- [ ] Enable LLM at chosen autonomy level
- [ ] Track veto accuracy, regime classification, cost per day
- [ ] **Pass criteria:**
  - PnL with LLM >= PnL without LLM
  - API cost < daily profit
  - No system crashes over full period

### 4C. Production Hardening
- [ ] Position reconciliation on restart
- [ ] Stale data handling (auto-pause)
- [ ] Circuit breaker verification on live data
- [ ] Telegram/Discord alerts working
- [ ] Graceful shutdown (no orphaned positions)

**Exit criteria for Phase 4:**
```
✓ 1+ week paper trading, profitable
✓ Paper results within ±10% of backtest
✓ No crashes, no orphaned positions
✓ Production hardening complete
```

---

## PHASE 5: LIVE TRADING

> **Goal:** Trade with real money. Same parameters proven in paper.
> **No artificially reduced risk. We tested at these params, we trade at these params.**

### 5A. Go Live
- [ ] Deploy with proven parameters (same as paper/backtest)
- [ ] Start with intended capital allocation
- [ ] **Same risk_per_trade, leverage, symbols as paper**
- [ ] If the edge is real, it works at full size. If it doesn't, we need to go back and fix it, not hide behind small sizing.

### 5B. Monitoring Dashboard
- [ ] Real-time PnL tracking
- [ ] Regime classification accuracy
- [ ] Strategy attribution (which strategy drives PnL)
- [ ] LLM cost vs value
- [ ] Alert on anomalies (unexpected drawdown, high trade frequency)

### 5C. Kill Switches
- [ ] Circuit breakers active (daily loss limit, consecutive loss streak)
- [ ] Manual kill switch via Telegram command
- [ ] Auto-pause if Sharpe drops below 0 over rolling 7 days
- [ ] Auto-pause if paper and live diverge > 20%

**Exit criteria for Phase 5:**
```
✓ 2+ weeks live trading with positive PnL
✓ Live results within ±15% of paper results
✓ No exchange API issues, no orphaned positions
✓ Sharpe > 0.5 over first month
```

---

## PHASE 6: SCALE + CONTINUOUS IMPROVEMENT

> **Goal:** Compound gains, add alpha sources, stay sharp.

### 6A. Scaling
- Add symbols as data proves edge (ETH, other alts)
- Increase capital allocation as track record grows
- Scale decisions based on rolling Sharpe, not feelings

### 6B. Continuous Improvement Loop
```
Weekly:
  - Review trade log, identify worst 3 trades
  - Check regime classification accuracy
  - Compare actual vs expected PnL
  - LLM cost audit

Monthly:
  - Walk-forward backtest with latest 30d data
  - Strategy weight analysis
  - Parameter sensitivity check
  - OOS validation on new data

Quarterly:
  - Evaluate new strategies (funding rate, order flow)
  - Evaluate new LLM models
  - Prune deep memory
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
Phase 1 (Baseline Backtest) ← WE ARE HERE
  ↓ must prove profitability
Phase 2 (LLM Value Quantification)
  ↓ must prove LLM adds value
Phase 3 (Full Pipeline Backtest)
  ↓ must prove architecture works
Phase 4 (Paper Trading)
  ↓ must match backtest within ±10%
Phase 5 (Live Trading)
  ↓ must prove live execution works
Phase 6 (Scale + Improve)
```

**No skipping phases.** Each phase's exit criteria must be met before advancing.
If any phase fails, go back, fix, and re-validate.

---

## RISK BUDGET

| Risk Category | Budget | Mitigation |
|---------------|--------|------------|
| Strategy degradation | Sharpe drops below 0 | Pause trading, re-backtest, retune |
| LLM hallucination | Single bad trade > 3% equity | Confidence caps, flip rate limits, CB |
| Exchange risk | Hyperliquid downtime | Auto-pause on stale data |
| LLM cost overrun | API bill > monthly profit | Cost tracker hard limits, downgrade to Haiku |
| Overfitting | OOS Sharpe < 50% of IS Sharpe | Walk-forward validation, regime analysis |
| Correlation blowup | All positions move against | Max 2-3 positions, correlation guard, MTM CB |

---

## ESTIMATED TIMELINE

| Phase | Duration | Dependency |
|-------|----------|------------|
| Phase 1: Baseline Backtest | 2-3 days | None |
| Phase 2: LLM Value Proof | 1-2 days | Phase 1 pass |
| Phase 3: Full Pipeline Backtest | 1 day | Phase 2 decision |
| Phase 4: Paper Trading | 1-2 weeks | Phase 3 pass |
| Phase 5: Live Trading | Ongoing | Phase 4 pass |
| Phase 6: Scale + Improve | Ongoing | Phase 5 proven |

**Total to first dollar at risk: ~2-3 weeks.**
The bot either has edge or it doesn't. Extended paper trading doesn't create edge — it just delays finding out.

---

*This document supplements ROADMAP.md with a profitability-focused sequence.
ROADMAP.md covers the full technical buildout; this document covers the validation path to real money.*
