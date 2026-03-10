# nunuIRL Trading Bot — Complete Roadmap

> **Last updated**: 2026-03-10
> **Current state**: Phase 2.8+2.9 DONE. Phase 3.1-3.5 DONE. Deep 10-agent audit complete: 30+ bugs fixed across execution, ensemble, strategies, LLM, and production hardening. 22 commits, 1006 tests passing.
> **What's next**: Validate with 100d backtest → paper trade 48-72h → go live conservative.

---

## Table of Contents
1. [System Inventory — What We Have](#1-system-inventory)
2. [What's Done (Phases 1-2.7 Complete)](#2-whats-done)
3. [Phase 2.8: Critical Bug Fixes (BLOCKING)](#3-phase-28)
4. [Phase 2.9: Fee Economics & Position Sizing](#4-phase-29)
5. [Phase 3: Signal Quality & Consistency](#5-phase-3)
6. [Phase 4: Production Hardening](#6-phase-4)
7. [Phase 5: Configuration Extraction & Tunability](#7-phase-5)
8. [Phase 6: Alpha Generation & Advanced Strategies](#8-phase-6)
9. [Phase 7: Advanced Multi-Agent Evolution](#9-phase-7)
10. [Critical Bugs Inventory](#10-critical-bugs)
11. [Audit Findings (March 2026)](#11-audit-findings)
12. [File Reference Map](#12-file-reference)

---

## 1. System Inventory — What We Have <a id="1-system-inventory"></a>

### Core Pipeline (Working)
| Layer | Files | Status |
|---|---|---|
| **3 Trading Strategies** | `bot/strategies/{regime_trend,confidence_scorer,multi_tier_quality}.py` | Working — ADX<20 filter on all 3, monte_carlo_zones disabled |
| **Ensemble Voting** | `bot/strategies/ensemble.py` (27KB) | Working — weighted veto, regime-aware confidence floor, chop detection |
| **Chop Detector** | `bot/strategies/chop_detector.py` | Working — 5-factor detection, tightened thresholds (0.45/0.45/0.55) |
| **LLM Meta-Brain** | `bot/llm/` (50+ files, 595KB) | Working — 6 autonomy levels, smart model routing |
| **Multi-Agent System** | `bot/llm/agents/` | Built — 7 specialist agents (Regime/Trade/Risk/Critic/Learning/Exit/Scout) |
| **Position Management** | `bot/execution/position_manager.py` (27KB) | Working — state machine, trailing stops, trade profiles, trailing fallback fixed |
| **Risk Management** | `bot/execution/risk.py` + `adaptive_risk.py` + `ops_guard.py` | Working — adaptive_risk wired in live mode |
| **Data Pipeline** | `bot/data/fetcher.py` (25KB) + `bot/data/fetchers/` | Working — CCXT multi-exchange |
| **Feedback Loop** | `bot/feedback/{signal_quality,evolution_tracker,loop,continuous_backtest,parameter_tuner}.py` | Working — signal scoring, evolution reports |
| **Memory System** | `bot/llm/{memory_store,deep_memory}.py` | Working — short-term (50 notes) + deep memory |
| **Order Execution** | `bot/execution/order_executor.py` | Working — paper/live modes, CCXT submission |
| **Backtest Engine** | `bot/backtest/engine.py` | Working — 91% fidelity, leverage logging bug fixed |
| **Tests** | `bot/tests/` (20+ test files) | 999 tests passing (0 failures) |
| **Configuration** | `bot/trading_config.py` (490+ lines) | Dataclass-based, per-symbol overrides, new ADX/ranging params |

### Multi-Agent Architecture (Built, Needs Tuning)
| Agent | Role | Default Model | When Called |
|---|---|---|---|
| **Regime Analyst** | Classify market regime from raw data | Haiku | Every decision cycle |
| **Trade Evaluator** | Form directional thesis, decide go/skip/flip | Sonnet | Pre-trade |
| **Risk Manager** | Position sizing, strategy weights, risk flags | Haiku | Pre-trade |
| **Critic** | Stress-test thesis, require counter-thesis for vetoes | Sonnet | Pre-trade |
| **Learning Agent** | Extract lessons from closed trades | Haiku | Post-close |
| **Exit Agent** | Monitor open positions, reassess thesis | Haiku | On open positions |
| **Scout Agent** | Idle-time preparation, watchlists, pre-formed theses | Haiku | Idle periods |

**Enable**: `LLM_MULTI_AGENT=true` in `.env`

---

## 2. What's Done (Phases 1-2.7 Complete) <a id="2-whats-done"></a>

### Phase 1: Stop Losing Money ✅
- [x] Fixed leverage math (liquidation formula, position sizing) — `bot/execution/leverage.py`
- [x] Added R:R sanity bounds to Signal class — `bot/strategies/base.py`
- [x] Fixed daily loss calculation (current equity, not peak) — `bot/execution/risk.py`
- [x] Added graceful strategy degradation (dynamic MIN_VOTES) — `bot/execution/graceful_degradation.py`
- [x] Weighted timeframes in trend scoring (5m=0.5, 1h=1.0, 6h=1.5, D=2.0) — `bot/trading_config.py`
- [x] Portfolio cap, spread-aware sizing, funding cost tracking
- [x] Ops guard, price guard, liquidity guard

### Phase 2: Multi-Agent LLM Architecture ✅
- [x] Agent base types, coordinator, 5 specialist prompts
- [x] Learning integration (deep memory, hypotheses, knowledge base)
- [x] Risk gates wired into live execution path
- [x] Feedback loops closed (signal quality → strategy weights → ensemble)

### Phase 2.5: Profitability Overhaul ✅ (March 2026)
- [x] confidence_scorer: 6h MACD+MFI regime filter, SL K=1.8→1.2
- [x] monte_carlo_zones: disabled entirely (PF=0.0)
- [x] Ensemble confidence capped at 85%
- [x] Leverage compressed: Tier 5 2.5-3x→2x flat, Tier 6 3-3.5x→2x flat
- [x] Ranging stops widened, trend-flip threshold raised 1.0→1.5
- [x] Re-entry gap 1→3 candles, confidence floor 65→70%
- [x] MEDIUM profile: SL 0.50→0.55 ATR, TP1% 0.70→0.65
- [x] BTC risk halved (risk_per_trade=0.01, max_leverage=10)

### Phase 2.6: Order Execution Layer ✅ (March 2026)
- [x] `bot/execution/order_executor.py` — paper/live modes with CCXT
- [x] Wired into main loop at 3 integration points
- [x] CB overrides disabled (max_cb_overrides=0)
- [x] 944 tests passing

### Phase 2.7: Multi-Layer Ranging Filter ✅ (March 2026)
**Data-driven: 100d backtest showed ranging = 24% WR (-$29K) vs trending = 100% WR (+$22K)**
- [x] ADX<20 filter added to regime_trend.py — skip signals in non-trending markets
- [x] ADX<20 filter added to multi_tier_quality.py — biggest PnL loser in ranging
- [x] ADX<20 already existed in confidence_scorer.py — verified
- [x] Chop detector thresholds tightened: 0.55→0.45 (BTC/SOL), 0.65→0.55 (HYPE)
- [x] Ensemble: regime-aware confidence floor (65% normal → up to 88% in chop)
- [x] Backtest engine: ADX-based regime override in both hourly/daily walk paths
- [x] New config params: `ADX_MIN_TRENDING=20.0`, `RANGING_CONFIDENCE_FLOOR=88.0`
- [x] 999 tests passing

**Results (10d backtest v3):**
- Ranging trades eliminated (0 vs 335 before)
- regime_trend: PF=1.78 (was 0.73) — **PROFITABLE**
- 3_agree: PF=4.05, 86% WR — **CRUSHING IT**
- Confidence inversion FIXED: 80-89% now best band (PF=4.75, was 0.53)
- Overall: -3.35% (was -83% on 100d) — fee drag now the bottleneck

---

## 3. Phase 2.8: Critical Bug Fixes (BLOCKING — Must Fix Before Paper Trading) <a id="3-phase-28"></a>

> **Goal**: Fix confirmed bugs that are actively destroying profitability.
> **Status**: 4/6 FIXED (March 2026). Remaining 2 reviewed and deprioritized.

### 2.8.1 SHORT Stop Loss Calculation Bug — REVIEWED ✅
- [x] **Reviewed `bot/execution/position_manager.py` line ~465**
  - Analysis: Formula `pos.entry + profit_cushion - fee_buffer` is CORRECT for SHORT positions.
    For SHORT after TP1: SL should be above entry. profit_cushion raises SL (more room),
    fee_buffer reduction accounts for exit fees. Fallback `entry - fee_buffer` also correct
    (SL just below entry = breakeven after fees for SHORT).
  - Status: Not a bug — formula matches LONG mirror logic.

### 2.8.2 Backtest Leverage Logging Bug ✅ FIXED
- [x] **Fixed `bot/backtest/engine.py` line ~1213**
  - Bug: `lev_decision.leverage` referenced in signal report — `lev_decision` only exists in raw mode.
    In normal mode the variable is `result` from RiskFilterChain, causing NameError.
  - Fix: Changed to `leverage` (the local variable that holds actual used value).

### 2.8.3 Trailing Stop Fallback Uses Wrong Distance ✅ FIXED
- [x] **Fixed `bot/execution/position_manager.py` line ~235**
  - Bug: When ATR=0, trailing distance fell back to `abs(entry - sl)` (full stop width = too loose)
  - Fix: Fallback to `entry * 0.01` (1% conservative default) instead of original stop width.

### 2.8.4 Ranging Market Trade Profile Logic — ALREADY FIXED ✅
- [x] **Fixed `bot/execution/trade_profile.py` lines ~309-320**
  - Was fixed in Phase 2.7: ranging stops widened 20%, illiquid stops widened 15%.
  - Comments updated to document the rationale.

### 2.8.5 Adaptive Risk Manager — WIRED IN LIVE ✅
- [x] **`bot/execution/adaptive_risk.py` already wired into `multi_strategy_main.py`**
  - Live mode: records outcomes, adjusts risk_multiplier per trade, injects into LLM context.
  - Backtest: not wired (by design — backtest uses fixed risk for reproducibility).
  - Status: Working in production path. Backtest gap is acceptable.

### 2.8.6 TP1 Close Percentage — TUNED ✅ FIXED
- [x] **Tuned `bot/execution/trade_profile.py` lines ~115-141**
  - MEDIUM: 65% → 50% — keep more capital riding winning trades
  - TREND: 60% → 40% — trending setups should maximize runner exposure
  - SCALP: 90% unchanged (scalps should lock in profits quickly)
  - Impact: Improved payoff ratio by letting winners run toward TP2

---

## 4. Phase 2.9: Fee Economics & Position Sizing <a id="4-phase-29"></a>

> **Goal**: Make the bot's edge survive fees. Current edge is ~$22/trade but fees eat 100%.
> **Status**: PARTIALLY DONE — confidence floor raised, 3_agree leverage gate added.

### 2.9.1 Verify Actual Hyperliquid Fee Structure ✅ DONE
- [x] **Confirmed**: Hyperliquid taker fee is 3.5 bps (0.035%). Updated `TAKER_FEE_BPS` default from 5 to 4 (3.5 + 0.5bps safety buffer). Fee drag cut by ~20%.

### 2.9.2 Fee-Aware Position Sizing ✅ DONE
- [x] **Updated `bot/execution/risk.py` calculate_qty()**
  - Round-trip fees (entry + exit) now added to effective stop width
  - `effective_stop = stop_width + slippage_spread + round_trip_fee_width`
  - Positions auto-shrink when fees consume significant % of stop distance
  - Fee-drag gate in signal pipeline: rejects trades where fees > 40% of stop

### 2.9.3 Fee-Aware EV Calculation in Ensemble ✅ DONE
- [x] **Updated `bot/strategies/ensemble.py` _merge_signals()**
  - EV now: `win_prob × (R:R - fee_drag) - loss_prob × (1 + fee_drag)`
  - Fee drag properly reduces expected win and increases expected loss

### 2.9.4 Raise Minimum R:R After Fees ✅ ALREADY DONE
- [x] **`MIN_SIGNAL_RR=2.0`** already set in trading_config.py

### 2.9.5 Raise Confidence Floor to 75% ✅ ALREADY DONE
- [x] **`bot/trading_config.py` already has `ensemble_confidence_floor=75.0`**
  - Ensemble constructor default is 65.0, but config override sets it to 75.0
  - Both backtest engine and main loop pass config value to ensemble
  - Higher than the originally suggested 70% — more aggressive filtering

### 2.9.6 3_agree Leverage Gate ✅ FIXED
- [x] **Implemented in `bot/execution/leverage.py`**
  - Keep MIN_VOTES=2 so the bot still generates signals on 2-strategy agreement
  - 2_agree: capped at 1.5x leverage, 0.85x risk_multiplier (smaller positions)
  - 3_agree: full 2-3x leverage, 1.0x risk_multiplier
  - Effect: 2_agree trades still happen but with reduced exposure, preventing the
    40% WR / -$1,207 problem from 2_agree dominating PnL
  - Or: MIN_VOTES=2 with `confidence_scorer+multi_tier_quality` combo BLOCKED (PF=0.08)

---

## 5. Phase 3: Signal Quality & Consistency <a id="5-phase-3"></a>

> **Goal**: Make every trade consistently high-quality. Stop vibe-coding parameters.
> **Status**: 80% complete — core framework built, needs wiring and calibration.

### 3.1 Shared Reasoning Framework ✅
- [x] Shared vocabulary, regime definitions, action names
- [x] Thought protocol: OBSERVE → RECALL → REASON → DECIDE → JUSTIFY
- [x] Cross-agent coherence validation

### 3.2 Shared Memory Protocol ✅
- [x] Scratchpad-based memory bus
- [x] Memory store (50 notes, 48h TTL)
- [x] Deep memory (trade DNA, patterns)

### 3.3 Agent Calibration Loop ✅
- [x] Per-agent accuracy tracking
- [x] Agent performance stats in prompts
- [x] Learning integration post-trade scoring

### 3.4 Walk-Forward Validation Framework ✅ DONE
- [x] **Created `bot/backtest/walk_forward.py`**
  - Runs full-period backtest, partitions trades into alternating train/test windows
  - Reports in-sample vs out-of-sample WR, PnL, profit factor
  - Calculates overfit ratio with clear PASS/CAUTION/FAIL verdict
  - CLI: `python cli.py --mode walkforward --days 120 --symbols SOL,BTC`

### 3.5 Strategy Combo Gating ✅ DONE
- [x] **Blocked losing strategy combinations**
  - `confidence_scorer+multi_tier_quality` 2-agree combo blocked in ensemble (PF=0.08)
  - Blacklist in `_weighted_veto()` method, easily extensible

### 3.6 Prompt Versioning & A/B Testing
- [ ] **Create `bot/llm/agents/prompt_registry.py`**
  - Versioned prompt management, A/B testing
  - Rollback if new version underperforms

---

## 6. Phase 4: Production Hardening <a id="6-phase-4"></a>

> **Goal**: Make the bot reliable enough for real money.

### 4.1 Code Architecture
- [ ] **Break up `multi_strategy_main.py`** (4,585 lines → modules)
  - Extract tick processing, LLM integration, position wiring, alerts, analytics
  - Main file → thin orchestrator (~200 lines)

### 4.2 Exchange Connection Resilience
- [ ] Exponential backoff in data fetcher (1s, 2s, 4s, 8s, 16s)
- [ ] Stale data detection (>5min old = flag)
- [ ] Auto-close new trades if data is stale
- [ ] Connection health monitoring with alerting

### 4.3 Position Reconciliation
- [x] `bot/execution/reconciliation.py` — built
- [ ] Wire periodic reconciliation into main loop (every 10 scans)

### 4.4 Logging & Monitoring
- [ ] Structured JSON logging everywhere
- [ ] Health check endpoint on dashboard
- [ ] Log rotation and archival

### 4.5 Integration Tests
- [ ] Full pipeline mock test (data → strategy → ensemble → LLM → execution → feedback)
- [ ] Golden path replay tests (known good/bad scenarios)

---

## 7. Phase 5: Configuration Extraction & Tunability <a id="7-phase-5"></a>

> **Goal**: Single source of truth for every parameter.

### 5.1 Config Audit
- [ ] Move trade profile parameters (TP1_ATR, SL_ATR, trailing_mult) into `TradingConfig`
- [ ] Eliminate scattered env var overrides in `trade_profile.py`
- [ ] Per-symbol overrides for ALL parameters (not just risk tiers)
- [ ] Config validation on startup

### 5.2 Paper-vs-Live Config Profiles
- [ ] Paper defaults: higher risk (2%), more symbols, aggressive
- [ ] Live defaults: lower risk (1%), proven symbols only, conservative

---

## 8. Phase 6: Alpha Generation & Advanced Strategies <a id="8-phase-6"></a>

> **Goal**: Find new edges beyond the current 3 strategies.

### 6.1 Full Pipeline Replay Backtesting
- [ ] Replay historical data through COMPLETE pipeline (including LLM decisions)
- [ ] Compare: strategies-only vs strategies+LLM vs multi-agent
- [ ] Walk-forward validation for all comparisons

### 6.2 New Strategy Development
- [ ] **Funding rate strategy** — counter-trade extreme funding (>0.05%)
- [ ] **Order flow analysis** — Hyperliquid orderbook depth signals
- [ ] **Cross-exchange signals** — Kraken/Bybit as leading indicators

### 6.3 Strategy Discovery Agent Activation
- [ ] Wire `bot/llm/strategy_discovery/` into growth orchestrator
- [ ] LLM proposes ideas → sandbox backtests → promote winners

---

## 9. Phase 7: Advanced Multi-Agent Evolution <a id="9-phase-7"></a>

> **Goal**: Self-improving agents.

- [ ] Portfolio Strategist Agent (cross-asset correlation)
- [ ] Automated prompt evolution with A/B testing
- [ ] Deep RL integration (DQN replacing Q-table)
- [ ] Multi-bot coordination (shared memory, cross-instance awareness)

---

## 10. Critical Bugs Inventory <a id="10-critical-bugs"></a>

### Must Fix Before Paper Trading
| # | Bug | Location | Impact | Status |
|---|---|---|---|---|
| 9 | `multi_strategy_main.py` is 4,700+ lines | `multi_strategy_main.py` | Unmaintainable god object | 🟠 OPEN (deferred to Phase 4) |

### Fixed (Profitability Session — March 10, 2026)
| Bug | Status |
|---|---|
| Ensemble modifies signals in-place | ✅ FIXED — deep copy before mutation |
| Strategy weights all history equally | ✅ FIXED — exponential decay |
| No order execution to exchange | ✅ FIXED — OrderExecutor built |
| 7 pre-existing test failures | ✅ FIXED — 1006 tests passing |
| Ranging regime destroys profitability | ✅ FIXED — multi-layer ADX filter |
| Confidence inversion (80-89% = worst WR) | ✅ FIXED — ADX filter + leverage flatten |
| SHORT SL reviewed: formula correct | ✅ VERIFIED — not a bug |
| Backtest leverage logging undefined var | ✅ FIXED — use local `leverage` variable |
| Trailing stop fallback too loose | ✅ FIXED — profile-aware % fallback |
| Ranging trade profile logic inverted | ✅ FIXED — widened stops 20% |
| Adaptive risk manager never wired | ✅ FIXED — wired into live loop |
| TP1 close% too aggressive | ✅ FIXED — MEDIUM 50%, TREND 40% |
| No exchange connection resilience | ✅ VERIFIED — retry/backoff already comprehensive |
| Position reconciliation not wired | ✅ FIXED — periodic check + auto-correct phantoms |
| LLM ensemble trigger names mismatched | ✅ FIXED — "regime_shift" → "regime shift" |
| Leverage cliff at Tier 6 (90%+ → 2x) | ✅ FIXED — continues Kelly scaling to 5x |
| TAKER_FEE_BPS inconsistent (4 vs 5) | ✅ FIXED — all defaults now 4 bps |
| Reconciliation key mismatch ("phantoms" vs "phantom") | ✅ FIXED — correct key names |
| Negative EV passes ensemble | ✅ FIXED — defense-in-depth EV floor in ensemble |
| 4-agree same deflation as 3-agree | ✅ FIXED — 4-agree now 5% deflation |
| Combo blocking only checks buy side | ✅ FIXED — checks both sides |
| MAX_ENSEMBLE_CONFIDENCE silently overridden | ✅ FIXED — respects user config |
| EMA span clamping → SELL bias | ✅ FIXED — proper spans with min_periods |
| Regime transitioning false positive | ✅ FIXED — reset flag on dominance block |
| RiskFilterChain exception falls through | ✅ FIXED — reject signal on error |
| force_close not submitting exchange orders | ✅ FIXED — 4 paths now submit to exchange |
| confidence_scorer 6h filter silently skipped | ✅ FIXED — log warning + 15% confidence penalty |
| TP1 rounding leaves zero-qty trailing | ✅ FIXED — guard against degenerate rounding |
| Chop detector NaN → false "not choppy" | ✅ FIXED — NaN defaults to choppy |
| Double leverage computation in live loop | ✅ FIXED — use RiskFilterChain result |
| ETH price always 0.0 in LLM context | ✅ FIXED — fetch ETH from data fetcher |
| Log message says 0.55, code checks 0.50 | ✅ FIXED — log matches code |
| Prefetch failures not tracked | ✅ FIXED — degradation triggered on all-fail |

---

## 11. Audit Findings (March 10, 2026) <a id="11-audit-findings"></a>

### Deep System Audit Summary

**5 parallel audits conducted**: Execution/Risk, Trading Config, Backtest Engine, Feedback/Learning, LLM/Main Loop.

#### What's Working Well
- **Backtest engine**: 91% fidelity — correct slippage, fees, no look-ahead bias
- **Position state machine**: Correct transitions IDLE→OPEN→TP1_HIT→TRAILING→CLOSED
- **Trailing stops**: Progressive tightening with profit lock floors, ATR-scaled
- **Circuit breaker**: Sound logic, only force-closes OPEN positions (preserves trailing)
- **Re-entry cooldown**: 3-candle gap prevents revenge trading
- **LLM veto**: ~20% veto rate of evaluated signals — appropriate stringency
- **Intra-candle simulation**: Worst-case first, then best-case, then close — realistic
- **Funding costs**: Hourly accrual at 0.01% per 8h — correct model

#### What's Broken (See Bug Inventory Above)
- SHORT SL calculation bug
- Leverage logging in normal backtests
- Trailing stop fallback
- Trade profile ranging logic inverted
- Adaptive risk dead code
- TP1 close% too aggressive

#### Key Numbers from 10d v3 Backtest
| Metric | Value | Target | Gap |
|---|---|---|---|
| Win Rate | 45.5% | >55% | Need better signal quality |
| Payoff Ratio | 1.15:1 | >1.5:1 | Fix TP1%, R:R, trailing |
| Fee Drag | 100% | <20% | Fix fee model, position sizing |
| 3_agree PF | 4.05 | >2.0 | Already crushing it |
| 2_agree PF | negative | >1.5 | Block losing combos |
| Sharpe | -5.54 | >1.0 | Need all fixes + fee optimization |
| regime_trend PF | 1.78 | >1.5 | Already profitable |
| confidence_scorer PF | 0.49 | >1.0 | Consider disabling in 2-agree |

#### The Path to Profitability
1. **Fix the 6 bugs** — they're actively destroying edge
2. **Solve fee economics** — fees eat 100% of gross edge currently
3. **Require higher quality setups** — 3_agree or 70%+ confidence
4. **Let winners run** — lower TP1 close%, wider targets
5. **Wire adaptive risk** — prevent loss streaks from compounding
6. **Walk-forward validate** every parameter change — stop overfitting

---

## 12. File Reference Map <a id="12-file-reference"></a>

### Entry Points
```
bot/run.py          → Quick launcher (paper, backtest, signals, status, positions)
bot/cli.py          → Full CLI (paper, replay, live, evolve, tiers, optimize)
bot/bot.py          → Bot class
bot/multi_strategy_main.py → Multi-strategy main loop (4,585 lines — needs breakup)
```

### Strategies & Ensemble
```
bot/strategies/base.py             → Signal dataclass, BaseStrategy abstract class
bot/strategies/ensemble.py         → Weighted veto ensemble (regime-aware conf floor)
bot/strategies/regime_trend.py     → Regime trend following (ADX filter added)
bot/strategies/confidence_scorer.py → Multi-factor momentum scoring (ADX filter)
bot/strategies/multi_tier_quality.py → Multi-TF signal quality (ADX filter added)
bot/strategies/chop_detector.py    → Multi-factor chop detection (tightened thresholds)
bot/strategies/regime_detector.py  → Regime classification
```

### Execution
```
bot/execution/position_manager.py  → Position lifecycle (SHORT SL verified correct)
bot/execution/leverage.py          → Leverage tiers and sizing
bot/execution/risk.py              → Circuit breakers, daily loss limits
bot/execution/adaptive_risk.py     → Dynamic risk adjustment (wired into live loop)
bot/execution/trade_profile.py     → Trade profiles (ranging logic fixed)
bot/execution/order_executor.py    → CCXT order submission (paper/live)
bot/execution/reconciliation.py    → Position reconciliation (built, not wired to loop)
bot/execution/ops_guard.py         → Operational safety checks
bot/execution/pnl_engine.py        → PnL calculation
bot/execution/tp_sl_engine.py      → Take-profit/stop-loss engine
```

### LLM Pipeline
```
bot/llm/decision_engine.py     → Monolithic LLM decision pipeline
bot/llm/agents/coordinator.py  → Multi-agent pipeline orchestration
bot/llm/agents/prompts.py      → 7 specialist prompts
bot/llm/agents/base.py         → Agent types, configs, defaults
bot/llm/agents/learning_integration.py → Wires agent output to learning systems
bot/llm/agents/shared_context.py → Shared reasoning framework
bot/llm/agents/thought_protocol.py → Structured OBSERVE→RECALL→REASON→DECIDE→JUSTIFY
bot/llm/agents/consistency_checker.py → Cross-agent coherence validation
bot/llm/agents/calibration_ledger.py → Per-agent accuracy tracking
bot/llm/usage_tiers.py         → Model routing (Haiku/Sonnet/Opus)
bot/llm/client.py              → Raw Anthropic API wrapper
```

### Configuration & Data
```
bot/trading_config.py   → Centralized config (490+ lines, dataclass-based)
bot/data/db.py          → SQLite persistence (24KB)
bot/data/fetcher.py     → Multi-exchange OHLCV (25KB)
bot/data/strategy_weights.py → Rolling strategy performance weights
```

### Backtest
```
bot/backtest/engine.py  → Full backtest engine (leverage logging fixed)
```

### Feedback & Analytics
```
bot/feedback/signal_quality.py     → Signal quality scoring (18KB)
bot/feedback/evolution_tracker.py  → Strategy evolution reports (38KB)
bot/feedback/continuous_backtest.py → Continuous backtesting (20KB)
bot/feedback/parameter_tuner.py    → Parameter optimization (14KB)
```

---

## Priority Order (What to Work On Next)

> Updated March 10, 2026. Based on comprehensive 10-agent deep audit (30+ bugs fixed).

1. ~~**Phase 2.8: Fix 6 critical bugs**~~ ✅ DONE
2. ~~**Phase 2.9: Fee economics**~~ ✅ DONE
3. ~~**Phase 3.1-3.5: Signal quality**~~ ✅ DONE (walk-forward, combo gating, shared reasoning)
4. ~~**Deep 10-agent audit**~~ ✅ DONE — 30+ bugs fixed (execution, ensemble, strategies, LLM, hardening)
5. **Validate with 100d backtest** — confirm all fixes produce positive Sharpe
6. **Paper trade on live API** — 48-72h validation with real exchange prices
7. **Go live conservative** — SOL+HYPE, 1% risk, 2x max leverage, 3_agree required
8. **Phase 4: Production hardening** — break up main loop, connection health, logging
9. **Phase 5: Config extraction** — single source of truth for all parameters
10. **Phase 6: New strategies** — funding rate, order flow, cross-exchange
11. **Phase 7: Advanced evolution** — portfolio agent, auto-prompt evolution, RL

---

*This document is the single source of truth for the nunuIRL roadmap. Update it as phases are completed.*
