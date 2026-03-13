# SYSTEM ANALYSIS — Full State Assessment (March 12, 2026)

## Executive Summary

nunuIRL is a **production-grade autonomous crypto trading system** with 11 strategies, 9 LLM specialist agents, multi-layered execution safety, and comprehensive monitoring. The architecture is mature. The challenge now is **proving profitability through systematic validation**.

**Current phase:** Phase 1A (Baseline Backtest) — proving strategies alone can generate edge.

**30-day backtest results (no LLM):**
- Net PnL: +$5,536 (+11.2% on $50k)
- 8 positions taken, 77% win rate by trade events
- HYPE: 100% WR (4/4), SOL: 0% WR (0/2), BTC: 50% WR (1/2)
- Trailing stops are the profit engine — every winner hit TP1 then trailed further
- Ensemble pass rate: 3.4% (1,500+ signals → 51 pass → 8 trades)

**Key problem:** 8 trades is not statistically significant. Need 30+ per symbol to validate.

---

## System Inventory

### Strategies (11 total, all wired into ensemble)

| Strategy | Timeframes | Status | Notes |
|----------|-----------|--------|-------|
| regime_trend | 1h, 6h | Active, profitable | Most consistent performer |
| confidence_scorer | 1h, 6h | Active, weak | PF 0.08 in 2-agree, blocked in combos |
| multi_tier_quality | 5m, 1h, 6h | Active, weak | "Biggest PnL loser" per code comments |
| monte_carlo_zones | daily | Active, muted | Returns None on HOLD (most conditions) |
| bollinger_squeeze | 1h | Active | Bandwalk + squeeze breakout signals |
| vmc_cipher | 1h | Active | Multi-oscillator confluence |
| probability_engine | 1h, 6h | Active | EV-based with Bayesian weighting |
| oi_delta | 1h | Needs exchange metadata | May not work in backtest |
| funding_rate | 1h | Needs exchange metadata | May not work in backtest |
| lead_lag | 1h | Active (BTC→alt) | Generates signals for alts |
| liquidation_cascade | 1h | Needs exchange metadata | May not work in backtest |

**Issue:** Only ~4-5 strategies actively fire in backtest. With min_votes=3, need 3/4 agreement = extremely restrictive.

### LLM Multi-Agent System (9 agents, all production-ready)

| Agent | Model | Role | Required | Status |
|-------|-------|------|----------|--------|
| Regime | Haiku | Market regime classification | Yes | Production |
| Quant | Haiku | Statistical edge analysis | No | Production |
| Trade | Sonnet | Directional thesis, go/skip/flip | Yes | Production |
| Risk | Haiku | Position sizing, portfolio risk | No | Production |
| Critic | Sonnet | Stress-test thesis, counter-thesis veto | No | Production |
| Learning | Haiku | Post-trade lesson extraction | No | Production |
| Exit | Haiku | Open position monitoring | No | Production |
| Scout | Haiku | Idle-time prep, watchlists | No | Production |
| Overseer | Sonnet | System health, cross-trade patterns | No | Production |

Pipeline: Regime → Quant → Trade → Risk → Critic → (Consistency Check) → Output
Cost: ~$0.007/decision cycle

### Execution Safety (Grade: A)

**6-Gate Signal Pipeline:**
1. Signal validity (R:R, stop width, TP correctness)
2. Circuit breaker check (daily loss, streak, drawdown)
3. Max open positions cap (default 3)
4. Correlation guard (0.85 threshold)
5. Leverage decision (6-tier system, Kelly-informed)
6. Liquidation safety (SL must trigger before liquidation)

**Additional systems:**
- Graduated drawdown risk (6 progressive bands)
- OpsGuard (rate limiting, kill switch, exposure caps)
- Progressive trailing stops (profile-driven tightening curves)
- Early exit on momentum reversal
- Hold time limits per trade profile (4h scalp → 48h regime)
- Liquidity guard (dead market rejection)
- Price guard (snapshot age, slippage, spread)
- Position reconciliation on startup

### Feedback & Learning (70-80% mature, awaiting data)

| Component | Lines | Status | Active |
|-----------|-------|--------|--------|
| Signal Quality Scorer | 497 | Mature | Yes |
| Parameter Tuner | 427 | Mature, trust-gated | Yes |
| Strategy Weights | 221 | Mature, exponential decay | Yes |
| Feedback Loop Orchestrator | 429 | Mature | Partial |
| Deep Memory (7 modules) | 931 | Built | Awaiting trades |
| Self-Teaching (5 levels) | 51KB | Built | Awaiting 3+ days data |
| Hypothesis Tracker | ~300 | Built | Awaiting data |
| Self-Improvement Engine | ~300 | Built | Awaiting data |
| Learning Integration | 444 | Built | Blocked (agents not active) |
| Evolution Tracker | 1023 | Mature | Needs trades.csv |

**Key insight:** The learning infrastructure is comprehensive but dormant. Once trading begins, it activates automatically.

### External Integrations (All production-ready)

| Component | Status | Notes |
|-----------|--------|-------|
| Telegram Bot | Active | 40+ commands, signal ingestion, kill switch |
| Discord Router | Active | 3-tier confidence routing with dedup |
| Web Dashboard | Active | Next.js + built-in Python server |
| FastAPI Backend | Active | Signals, strategies, metrics endpoints |
| Prometheus | Active | Trading volume, drawdown, error rates |
| Grafana | Active | Auto-provisioned dashboards |
| Docker Compose | Active | 12 containers, multi-bot parallel |
| GitHub Actions CI | Active | Pytest + replay smoke tests |

### Test Suite

- **1,177 tests** across 41 files, zero skips
- **Strong:** Safety, LLM agents, feedback loops, profitability math
- **Gaps:** Backtest runner (0 tests), CLI modes, deployment gate, monitoring
- **Blocked:** 4 files fail import (missing pandas)

---

## Known Bugs

### Backtest Runner Display (runner.py)
1. **Win rate shows 0%** — Line 393 reads `win_rate_pct` key but actual key is `win_rate` (decimal). Fix: `res.get("win_rate", 0) * 100`
2. **exit_types crash** — Line 446 sorts dict values as ints, but they're nested dicts. Fix: access `.get("trades", 0)`
3. **Quant analytics error** — TradeEvent objects vs expected dicts in some code paths
4. **Deployment gate broken** — Reports 0 trades, -1036% drawdown (nonsensical)

### Test Suite
5. **4 test files fail import** — Missing pandas dependency (test_chop_detector, test_ensemble_weights, test_new_strategies, test_phase2)

### Tech Debt
6. **multi_strategy_main.py is 6,028 lines** — Needs breakup into tick_processor, llm_integration, position_wiring, analytics

---

## Critical Path to Profitability

```
Phase A: Fix instrumentation (backtest bugs, test imports)
    ↓
Phase B: Tune ensemble for more trades (data-driven, not blind)
    ↓
Phase C: Run 100-day definitive baseline backtest
    ↓  Exit: Sharpe>1.0, PF>1.3, DD<20%, 30+ trades/symbol
Phase D: Enable LLM, prove it adds value vs baseline
    ↓  Exit: LLM Sharpe > baseline Sharpe
Phase E: Paper trading 48-72h (learning systems activate)
    ↓  Exit: Paper matches backtest ±10%
Phase F: Live trading (conservative: 1 symbol, 1% risk, 3x max)
    ↓  Exit: Live matches paper ±15%
Phase G: Scale + continuous improvement
```

### Phase B Deep Dive: Why We Need More Trades

The system's 3.4% signal pass rate is driven by:
- `min_votes=3` with only 4 active strategies = need 75% agreement
- Confidence floors: 60% normal, 88% ranging (almost impossible)
- ADX threshold 22 rejects weak-but-tradeable trends
- Several strategies produce no signals (need exchange metadata)
- Opposition veto ratio 1.5x kills borderline signals

**Not proposing to blindly lower gates.** Proposing to:
1. Analyze which strategy combinations produce profitable trades
2. Test min_votes=2 with the BEST 2-strategy combos only
3. Test ADX threshold sensitivity (22 → 18-20)
4. Test confidence floor sensitivity (88% → 75-80% in ranging)
5. Validate changes with walk-forward to prevent overfitting

### Execution Safety Gaps for Live Trading

| Gap | Priority | Fix |
|-----|----------|-----|
| No continuous liquidation monitoring | High | Check liq distance every price update |
| Position state not persisted per tick | High | Save SL/TP/state to JSON every update |
| No daily slippage aggregate tracking | Medium | Add to circuit breaker |
| Funding costs lost on restart | Medium | Persist to funding_log.jsonl |
| Live order retry not proven at scale | Medium | Test with limit orders first |
| Correlation matrix lags regime shifts | Low | Use 7d window, retrain daily |

---

## File Reference Map

**Entry Points:**
- `bot/run.py` — Quick launcher
- `bot/cli.py` — Full CLI (8 modes)
- `bot/multi_strategy_main.py` — Main loop (6,028 lines)

**Core Systems:**
- `bot/strategies/ensemble.py` — Weighted veto voting
- `bot/llm/agents/coordinator.py` — 9-agent pipeline (2,217 lines)
- `bot/execution/position_manager.py` — State machine + trailing stops
- `bot/core/signal_pipeline.py` — 6-gate risk filter
- `bot/execution/risk.py` — Circuit breakers
- `bot/execution/leverage.py` — 6-tier leverage system
- `bot/backtest/engine.py` — Backtest engine (~2,000 lines)

**Configuration:**
- `bot/trading_config.py` — All parameters (490+ lines)
- `.env.example` — 100+ environment variables

**Planning:**
- `ROADMAP.md` — Technical roadmap (Phases 1-7.3 done)
- `PROFITABILITY_ROADMAP.md` — Validation path to real money
- `PHASE_COMPLETION_STATUS.md` — LLM meta-brain phase tracking
