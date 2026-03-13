# nunuIRL Trading Bot — Complete Roadmap

> **Last updated**: 2026-03-13
> **Current state**: Phase 8 DONE. **Quant-grade mathematical foundation** — Kelly criterion wired into live position sizing (half-Kelly, bounded [0.5%-4%], portfolio heat cap 6%), EV calculation includes slippage drag (parity with risk.py), ADX graduated penalty replaces binary cutoff, win probability deflators configurable via trading_config.py, signal success metric tied to 1R (stop-loss based), strategy weights use age-weighted exponential decay (14-day half-life), calibration bins doubled to 10 with isotonic regression, 14 stale docs removed. 1177+ tests.
> **What's next**: Run 30d backtest to validate quant changes → paper trade → LLM value quantification (Phase 2 of profitability roadmap).

---

## Table of Contents
1. [System Inventory — What We Have](#1-system-inventory)
2. [What's Done (Phases 1-7.1+)](#2-whats-done)
3. [Phase 2.8: Critical Bug Fixes](#3-phase-28)
4. [Phase 2.9: Fee Economics & Position Sizing](#4-phase-29)
5. [Phase 3: Signal Quality & Consistency](#5-phase-3)
6. [Phase 4: Production Hardening](#6-phase-4)
7. [Phase 5: Configuration Extraction & Tunability](#7-phase-5)
8. [Phase 6: Alpha Generation & Advanced Strategies](#8-phase-6)
9. [Phase 7: Advanced Multi-Agent Evolution](#9-phase-7)
10. [Known Issues & Tech Debt](#10-known-issues)
11. [Audit Findings (March 2026)](#11-audit-findings)
12. [File Reference Map](#12-file-reference)

---

## 1. System Inventory — What We Have <a id="1-system-inventory"></a>

### Core Pipeline (Working)
| Layer | Files | Status |
|---|---|---|
| **11 Trading Strategies** | `bot/strategies/{regime_trend,confidence_scorer,multi_tier_quality,funding_rate,oi_delta,bollinger_squeeze,vmc_cipher,lead_lag,liquidation_cascade,probability_engine}.py` + monte_carlo_zones (gated) | Working — 3 original + 7 new quant strategies (Phase 6), monte_carlo_zones disabled via env |
| **Ensemble Voting** | `bot/strategies/ensemble.py` | Working — weighted veto, regime-aware confidence floor, chop detection, soft-filter annotations |
| **Chop Detector** | `bot/strategies/chop_detector.py` | Working — 5-factor detection, tightened thresholds (0.45/0.45/0.55) |
| **Regime Detection** | `bot/strategies/regime_detector.py` + standalone in main loop | Working — fed by strategy metadata + tick-level 1h price data + LLM Regime Agent feedback |
| **LLM Meta-Brain** | `bot/llm/` (50+ files) | Working — 6 autonomy levels, smart model routing, brain wiring complete |
| **Multi-Agent System** | `bot/llm/agents/` | Working — 9 specialist agents (Regime/Trade/Risk/Critic/Learning/Exit/Scout/Overseer/Quant) |
| **Brain Intelligence** | `bot/llm/{thesis_tracker,confidence_calibrator,counterfactual_learner,brain_wiring,quant_data}.py` | Working — all wired into coordinator pipeline |
| **Position Management** | `bot/execution/position_manager.py` | Working — state machine, trailing stops, trade profiles |
| **Risk Management** | `bot/execution/risk.py` + `adaptive_risk.py` + `ops_guard.py` + `graduated_drawdown.py` | Working — graduated 6-band risk reduction, streak/time/regime penalties |
| **Data Pipeline** | `bot/data/fetcher.py` + `bot/data/fetchers/` | Working — CCXT multi-exchange, parallel prefetch |
| **Feedback Loop** | `bot/feedback/{signal_quality,evolution_tracker,loop,continuous_backtest,parameter_tuner}.py` | Working — signal scoring, evolution reports, regime-aware splitting |
| **Memory System** | `bot/llm/{memory_store,deep_memory}.py` | Working — short-term (100 notes) + deep memory |
| **Soft Filter Architecture** | `bot/core/filter_annotations.py` + ensemble `evaluate_with_annotations()` | Working — near-miss signals visible to LLM for learning |
| **Signal Tracker** | `bot/core/signal_tracker.py` | Working — all signals tracked (approved + rejected) |
| **Order Execution** | `bot/execution/order_executor.py` | Working — paper/live modes, CCXT submission |
| **Backtest Engine** | `bot/backtest/engine.py` + `walk_forward.py` + `quant_analytics.py` + `deployment_gate.py` | Working — all 11 strategies, quant analytics (VaR/CI/Kelly/MC), signal digest, deployment gate, pre-seed learning |
| **Tests** | `bot/tests/` (41 test files) | 1177 tests passing (0 failures) |
| **Configuration** | `bot/trading_config.py` (490+ lines) | Dataclass-based, per-symbol overrides |

### Multi-Agent Architecture (9 Agents)
| Agent | Role | Default Model | Max Tokens | When Called |
|---|---|---|---|---|
| **Regime Analyst** | Classify market regime from raw data | Haiku | 2048 | Every decision cycle |
| **Trade Evaluator** | Form directional thesis, decide go/skip/flip | Sonnet | 3072 | Pre-trade |
| **Risk Manager** | Position sizing, strategy weights, risk flags | Haiku | 2048 | Pre-trade |
| **Critic** | Stress-test thesis, require counter-thesis for vetoes | Sonnet | 3072 | Pre-trade |
| **Learning Agent** | Extract lessons from closed trades | Haiku | 2048 | Post-close |
| **Exit Agent** | Monitor open positions, reassess thesis | Haiku | 1024 | On open positions |
| **Scout Agent** | Idle-time preparation, watchlists, pre-formed theses | Haiku | 1536 | Idle periods |
| **Overseer Agent** | System health audits, degradation detection | Sonnet | 2048 | Periodic |
| **Quant Agent** | Statistical analysis, probability calculations | Sonnet | 1536 | On demand |

**Enable**: `LLM_MULTI_AGENT=true` in `.env`

### Brain Intelligence Pipeline (All Wired to Coordinator)
| Component | File | What It Does | Wired? |
|---|---|---|---|
| **Thesis Tracker** | `thesis_tracker.py` | Records every Trade Agent prediction, measures accuracy by regime/symbol/setup type | ✅ coordinator.py:896 |
| **Confidence Calibrator** | `confidence_calibrator.py` | Builds calibration curve from outcomes, deflates overconfident predictions | ✅ coordinator.py:907 |
| **Counterfactual Learner** | `counterfactual_learner.py` | Tracks skipped trades, computes hypothetical PnL, identifies over-aggressive filters | ✅ coordinator.py:913 |
| **Regime Feedback** | Graduated drawdown + regime-aware feedback | Per-regime win rates, confidence floors, risk multipliers | ✅ coordinator.py:924 |
| **Graduated Risk** | `graduated_drawdown.py` | Peak equity tracking, 6 progressive drawdown bands | ✅ coordinator.py:932 |

---

## 2. What's Done (Phases 1-7.1+) <a id="2-whats-done"></a>

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

### Phase 2.7: Multi-Layer Ranging Filter ✅ (March 2026)
- [x] ADX<20 filter in regime_trend, multi_tier_quality, confidence_scorer
- [x] Chop detector thresholds tightened: 0.55→0.45 (BTC/SOL), 0.65→0.55 (HYPE)
- [x] Ensemble: regime-aware confidence floor (65% normal → up to 88% in chop)
- [x] Backtest engine: ADX-based regime override in both hourly/daily walk paths
- **Results (10d backtest v3)**: Ranging trades eliminated, 3_agree PF=4.05 (86% WR)

### Phase 3.6: Anti-Spam Overhaul ✅ (March 11, 2026)
- [x] `min_votes_required`: 2→3, `veto_ratio`: 1.3→1.5
- [x] `ensemble_confidence_floor`: 75→80, `min_signal_rr`: 1.5→1.8
- [x] `min_signal_ev`: 0.15→0.20, `max_fee_drag`: 40%→30%
- [x] Cooldowns: loss 5min, win 3min, dedup 10min
- [x] `scan_interval`: 60s, rotations: 1/hr, 4/day
- [x] 2-agree win prob deflation: 70%→55%

### Phase 6.2: New Quant Strategies ✅ (March 11, 2026)
- [x] **7 new strategies** all working, env-toggleable, following Signal contract
- [x] Funding Rate, OI Delta, Bollinger Squeeze, VMC Cipher, Lead-Lag, Liquidation Cascade, Probability Engine

### Phase 6.3: LLM Brain Intelligence ✅ (March 11, 2026)
- [x] Thesis Tracker, Confidence Calibrator, Counterfactual Learner — all wired into coordinator

### Phase 7.1: Proactive Risk + Brain Wiring ✅ (March 11, 2026)
- [x] Graduated drawdown risk reduction — 6 progressive bands (normal → circuit breaker)
- [x] Regime-aware feedback splitting — per-regime confidence floors, risk multipliers, strategy weights
- [x] Wire brain upgrades into live pipeline — thesis→coordinator, calibrator→merge, counterfactual→ensemble
- [x] Overseer Agent enhanced — brain upgrade data injected
- [x] Quant data backbone — full quantitative enrichment pipeline
- [x] Strategy signal digest — LLM sees all strategy readings, not just passing signals

### Phase 7.2: Zero-Trade Blocker Fix ✅ (March 12, 2026)
**Root cause discovered and fixed: regime was ALWAYS "unknown", causing cascading signal blocks.**

- [x] **Regime metadata fix** — All 11 strategies now set `metadata["regime"]` as a string. Previously only set as dict or not at all. Each strategy uses its own indicators to classify (ADX, OI type, squeeze state, cascade severity, etc.)
- [x] **Standalone regime classification** — Runs every tick in `_process_symbol()` using 1h price volatility, independent of signal generation. Breaks the chicken-and-egg loop.
- [x] **LLM regime feedback loop** — Regime Agent output feeds back to system-wide `RegimeTransitionDetector` and `_tick_regime_cache`.
- [x] **STRATEGY_REGIME_FIT expanded** — All 11 strategies mapped across 8 regimes (was: only 4 strategies across 7 regimes). Added `consolidation` regime.
- [x] **Blocked combos relaxed** — Only `confidence_scorer+multi_tier_quality` blocked (PF 0.08).
- [x] **Scout Agent truncation fix** — `max_tokens` 768→1536.

### Phase 7.3: Backtest Regime Parity + Prompt Modernization ✅ (March 12, 2026)
- [x] **STRATEGY_REGIME_FIT wired into backtest engine** — Both hourly and daily walk paths now apply regime-fit strategy filtering before ensemble.evaluate(), matching live path behavior. Strategies marked "avoid" in current regime are disabled.
- [x] **Agent prompts updated for 11 strategies** — Trade Agent has full strategy reference table (what each detects), updated confluence scoring with derivatives/oscillator categories. Risk Agent strategy weights expanded to all 11. Critic coherence checklist expanded.
- [x] **Confluence calibration updated** — "4 strategies agree" → "5+ strategies agree" (reflects 11-strategy ensemble). MIN_VOTES=3 documented in prompts.
- [x] **ranging_confidence_floor config wired** — Now passed from TradingConfig to Ensemble constructor (was hardcoded 88.0, now respects RANGING_CONFIDENCE_FLOOR env var).
- [x] **Brain wiring error visibility** — 5 error log locations in coordinator.py promoted debug→info so brain component failures are visible in normal output.

---

## 3. Phase 2.8: Critical Bug Fixes ✅ COMPLETE <a id="3-phase-28"></a>

> All 6 bugs reviewed and resolved. See "Fixed Bugs" table in Section 10.

---

## 4. Phase 2.9: Fee Economics & Position Sizing ✅ COMPLETE <a id="4-phase-29"></a>

- [x] Hyperliquid taker fee confirmed: 3.5 bps (TAKER_FEE_BPS=4 with safety buffer)
- [x] Fee-aware position sizing: round-trip fees added to effective stop width
- [x] Fee-aware EV in ensemble: `win_prob × (R:R - fee_drag) - loss_prob × (1 + fee_drag)`
- [x] MIN_SIGNAL_RR=2.0, ensemble_confidence_floor=75.0 (config override to 80)
- [x] 3_agree leverage gate: MIN_VOTES=3, 2_agree capped at 1.0x

---

## 5. Phase 3: Signal Quality & Consistency ✅ MOSTLY COMPLETE <a id="5-phase-3"></a>

- [x] Shared reasoning framework (vocabulary, thought protocol, coherence validation)
- [x] Shared memory protocol (scratchpad bus, deep memory)
- [x] Agent calibration loop (per-agent accuracy tracking)
- [x] Walk-forward validation framework (`bot/backtest/walk_forward.py`)
- [x] Strategy combo gating (losing combos blocked)
- [x] Anti-spam overhaul (3-agree, 10 tightened gates)

### 3.7 Prompt Versioning & A/B Testing — NOT STARTED
- [ ] **Create `bot/llm/agents/prompt_registry.py`**
  - Versioned prompt management, A/B testing framework
  - Rollback if new version underperforms
  - Priority: LOW (do after paper trading proves the pipeline works)

---

## 6. Phase 4: Production Hardening <a id="6-phase-4"></a>

> **Goal**: Make the bot reliable enough for real money.
> **Status**: Partially done. Reconciliation wired. Main file still too large.

### 4.1 Break Up `multi_strategy_main.py` — HIGH PRIORITY
- [ ] **Currently 6,028 lines** — extract into focused modules:
  - `bot/core/tick_processor.py` — per-symbol tick evaluation logic (~1500 lines)
  - `bot/core/llm_integration.py` — LLM trigger management, meta-brain invocation (~800 lines)
  - `bot/core/position_wiring.py` — position lifecycle, exit intelligence (~600 lines)
  - `bot/core/analytics.py` — performance tracking, degradation, alerts (~500 lines)
  - Main file → thin orchestrator (~300 lines)
- This is the single biggest tech debt. Every change risks merge conflicts and cognitive overload.

### 4.2 Exchange Connection Resilience ✅ MOSTLY DONE
- [x] Exponential backoff in data fetcher — already comprehensive
- [x] Parallel prefetch with failure tracking
- [x] Degradation awareness (all-fail → skip processing)
- [ ] Auto-close new trades if data is stale (>5min old candles)
- [ ] Connection health monitoring dashboard endpoint

### 4.3 Position Reconciliation ✅ WIRED
- [x] `bot/execution/reconciliation.py` — built
- [x] Wired into main loop (startup + periodic)
- [x] Auto-corrects phantom positions

### 4.4 Logging & Monitoring
- [ ] Structured JSON logging everywhere (currently mixed format)
- [ ] Health check endpoint on web dashboard
- [ ] Log rotation and archival

### 4.5 Integration Tests
- [ ] Full pipeline mock test (data → strategy → ensemble → LLM → execution → feedback)
- [ ] Golden path replay tests (known good/bad scenarios)

---

## 7. Phase 5: Configuration Extraction & Tunability <a id="7-phase-5"></a>

> **Goal**: Single source of truth for every parameter.
> **Status**: NOT STARTED. Low priority until paper trading validates the pipeline.

### 5.1 Config Audit
- [ ] Move trade profile parameters (TP1_ATR, SL_ATR, trailing_mult) into `TradingConfig`
- [ ] Eliminate scattered env var overrides in `trade_profile.py`
- [ ] Per-symbol overrides for ALL parameters (not just risk tiers)
- [ ] Config validation on startup (catch typos, out-of-range values)

### 5.2 Paper-vs-Live Config Profiles
- [ ] Paper defaults: higher risk (2%), more symbols, aggressive
- [ ] Live defaults: lower risk (1%), proven symbols only, conservative

---

## 8. Phase 6: Alpha Generation & Advanced Strategies ✅ MOSTLY COMPLETE <a id="8-phase-6"></a>

### 6.1 Full Pipeline Replay Backtesting — NOT STARTED
- [ ] Replay historical data through COMPLETE pipeline (including LLM decisions)
- [ ] Compare: strategies-only vs strategies+LLM vs multi-agent
- [ ] Walk-forward validation for all comparisons
- **Blocker**: Needs real LLM decision history from paper trading first

### 6.2 New Strategy Development ✅ DONE
- [x] 7 new quant strategies, all following Signal contract, env-toggleable
- [x] All strategies now set `metadata["regime"]` for system-wide regime detection

### 6.3 LLM Brain Intelligence ✅ DONE
- [x] Thesis Tracker, Confidence Calibrator, Counterfactual Learner — all wired

### 6.4 Strategy Discovery Agent — NOT STARTED
- [ ] Wire `bot/llm/strategy_discovery/` into growth orchestrator
- [ ] LLM proposes ideas → sandbox backtests → promote winners
- Files exist (`research_agent.py`, `proposals.py`, `sandbox.py`) but aren't activated

### 6.5 Future Strategy Ideas
- [ ] **Order flow analysis** — Hyperliquid orderbook depth signals
- [ ] **Cross-exchange signals** — Kraken/Bybit as leading indicators

---

## 9. Phase 7: Advanced Multi-Agent Evolution <a id="9-phase-7"></a>

> **Goal**: Self-improving agents with proactive risk management.
> **Status**: 7.1 COMPLETE (graduated risk, regime feedback, brain wiring, overseer). 7.2 COMPLETE (zero-trade fix).

### 7.1 Proactive Risk Management ✅ DONE
- [x] Graduated drawdown risk reduction — 6 progressive bands, streak/time/regime penalties
- [x] Regime-aware feedback splitting — per-regime confidence floors, risk multipliers
- [x] Brain upgrades wired into coordinator
- [x] Overseer Agent enhanced with brain data injection

### 7.2 Zero-Trade Blocker ✅ DONE (March 12, 2026)
- [x] Fixed regime classification across all strategies
- [x] Standalone tick-level regime detection
- [x] LLM regime feedback loop to system-wide detector
- [x] STRATEGY_REGIME_FIT: 4→11 strategies, 7→8 regimes
- [x] Relaxed blocked combos for 11-strategy ensemble
- [x] Scout Agent max_tokens 768→1536

### 7.3 Self-Improving Architecture — NOT STARTED
- [ ] Portfolio Strategist Agent (cross-asset correlation, portfolio-level sizing)
- [ ] Automated prompt evolution with A/B testing
- [ ] Deep RL integration (DQN replacing Q-table in growth system)
- [ ] Multi-bot coordination (shared memory, cross-instance awareness)
- [ ] Curriculum advancement with measurable thresholds

### 7.4 Hour-Gated Trading — NOT STARTED
- [ ] Auto-pause during historically losing hours
- [ ] Requires 30+ days of live data to determine which hours lose money
- [ ] Could be informed by thesis tracker accuracy-by-hour

---

## Phase 8: Quant-Grade Mathematical Foundation (March 13, 2026) <a id="phase-8"></a>

> Remove hardcoded magic numbers, wire orphaned quant systems, and reach
> mathematically rigorous position sizing and signal evaluation.

### 8.1 Kelly Criterion Position Sizing ✅
- [x] Wire half-Kelly from `quant_data.py` into `risk.py:calculate_qty()`
- [x] Add portfolio heat cap (sum of open risk% ≤ 6%)
- [x] Bound Kelly [0.5%, 4%], require 20+ trades per setup/regime
- [x] Fallback to fixed 2% when insufficient data

### 8.2 EV Calculation Parity ✅
- [x] Add `slippage_drag` to ensemble EV formula (matches `risk.py`)
- [x] Log slippage drag in negative-EV rejection messages

### 8.3 Graduated Filters (Remove Binary Cliffs) ✅
- [x] ADX: binary cutoff → graduated penalty (hard reject only below 10)
- [x] Signal success: 0.5% arbitrary → 1R-based definition tied to stop loss

### 8.4 Data-Driven Deflators ✅
- [x] Move win_prob deflators (0.55/0.68/0.80/0.90) to `trading_config.py`
- [x] Make configurable via env vars (WP_DEFLATOR_*)
- [x] Strategy weights: add age-weighted decay (14-day half-life)
- [ ] Build auto-tuner using Wilson CI from trade history (needs live data)

### 8.5 Calibration Refinement ✅
- [x] Increase calibration bins from 5→10 (5-point width)
- [x] Increase MIN_SAMPLES_PER_BIN from 5→8 for thinner bins
- [x] Add isotonic regression (pool-adjacent-violators) for monotonic curve

### 8.6 Documentation Consolidation ✅
- [x] Remove 14 stale markdown files from repo root
- [x] Add Phase 8 to ROADMAP.md

---

## 10. Known Issues & Tech Debt <a id="10-known-issues"></a>

### Active Issues
| # | Issue | Location | Impact | Priority |
|---|---|---|---|---|
| 1 | `multi_strategy_main.py` is 6,028 lines | Main loop | Unmaintainable god object, merge conflicts | HIGH |
| 2 | Standalone regime heuristic is simplistic | `multi_strategy_main.py:2290-2315` | Uses volatility proxy, not real ADX. Works but could be more accurate with proper TA. | MEDIUM |
| 3 | No stale data auto-close | Data pipeline | Could trade on old candles during exchange outage | MEDIUM |
| 4 | Structured logging incomplete | Throughout | Mixed log formats, harder to parse in production | LOW |
| 5 | Strategy discovery not wired | `llm/strategy_discovery/` | Files exist but aren't activated | LOW |

### Optimization Opportunities
| Opportunity | Expected Impact | Effort |
|---|---|---|
| **Paper trade 48-72h** — validate regime classification + signal frequency | CRITICAL: proves or disproves all recent fixes | Low (just run it) |
| **Backtest with regime fix** — rerun 100d backtest to see impact of proper regime | HIGH: quantifies the fix | Low |
| **Monte Carlo re-evaluation** — test with new 11-strategy ensemble | MEDIUM: might be viable now with 3-agree gate | Low |
| **Per-strategy regime performance** — which strategies actually work in which regime | HIGH: data-driven STRATEGY_REGIME_FIT tuning | Medium |
| **Tune standalone regime thresholds** — use proper ADX/ATR instead of price volatility proxy | MEDIUM: more accurate regime classification | Medium |

### Fixed Bugs (All Sessions)
| Bug | Status |
|---|---|
| Ensemble modifies signals in-place | ✅ FIXED — deep copy before mutation |
| Strategy weights all history equally | ✅ FIXED — exponential decay |
| No order execution to exchange | ✅ FIXED — OrderExecutor built |
| Ranging regime destroys profitability | ✅ FIXED — multi-layer ADX filter |
| Confidence inversion (80-89% = worst WR) | ✅ FIXED — ADX filter + leverage flatten |
| SHORT SL reviewed: formula correct | ✅ VERIFIED — not a bug |
| Backtest leverage logging undefined var | ✅ FIXED — use local `leverage` variable |
| Trailing stop fallback too loose | ✅ FIXED — profile-aware % fallback |
| Ranging trade profile logic inverted | ✅ FIXED — widened stops 20% |
| Adaptive risk manager never wired | ✅ FIXED — wired into live loop |
| TP1 close% too aggressive | ✅ FIXED — MEDIUM 50%, TREND 40% |
| Exchange connection resilience | ✅ VERIFIED — retry/backoff comprehensive |
| Position reconciliation not wired | ✅ FIXED — periodic check + phantom correction |
| LLM ensemble trigger names mismatched | ✅ FIXED |
| Leverage cliff at Tier 6 | ✅ FIXED — continues Kelly scaling |
| TAKER_FEE_BPS inconsistent | ✅ FIXED — all defaults now 4 bps |
| Reconciliation key mismatch | ✅ FIXED |
| Negative EV passes ensemble | ✅ FIXED — defense-in-depth EV floor |
| 4-agree same deflation as 3-agree | ✅ FIXED — 4-agree now 5% deflation |
| Combo blocking only checks buy side | ✅ FIXED — checks both sides |
| MAX_ENSEMBLE_CONFIDENCE silently overridden | ✅ FIXED |
| EMA span clamping → SELL bias | ✅ FIXED — proper spans with min_periods |
| Regime transitioning false positive | ✅ FIXED |
| RiskFilterChain exception falls through | ✅ FIXED — reject signal on error |
| force_close not submitting exchange orders | ✅ FIXED — 4 paths now submit |
| confidence_scorer 6h filter silently skipped | ✅ FIXED |
| TP1 rounding leaves zero-qty trailing | ✅ FIXED |
| Chop detector NaN → false "not choppy" | ✅ FIXED |
| Double leverage computation | ✅ FIXED |
| ETH price always 0.0 in LLM context | ✅ FIXED |
| Log/code threshold mismatch | ✅ FIXED |
| Prefetch failures not tracked | ✅ FIXED |
| **Regime always "unknown"** | ✅ FIXED — strategies now set `metadata["regime"]` as string |
| **STRATEGY_REGIME_FIT missing 7 strategies** | ✅ FIXED — all 11 strategies mapped |
| **Blocked combos too aggressive** | ✅ FIXED — only block proven loser (PF 0.08) |
| **Scout Agent JSON truncation** | ✅ FIXED — max_tokens 768→1536 |
| **Regime never fed from tick data** | ✅ FIXED — standalone classification every tick |
| **LLM regime not fed back to system** | ✅ FIXED — Regime Agent → RegimeTransitionDetector |

---

## 11. Audit Findings (March 2026) <a id="11-audit-findings"></a>

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
- **Regime classification**: Now working end-to-end (fixed March 12)
- **Brain intelligence**: Thesis/calibration/counterfactual all wired and populating data

#### Key Numbers from 10d v3 Backtest (Pre-Regime Fix)
| Metric | Value | Target | Gap |
|---|---|---|---|
| Win Rate | 45.5% | >55% | Need better signal quality |
| Payoff Ratio | 1.15:1 | >1.5:1 | Fix TP1%, R:R, trailing |
| Fee Drag | 100% | <20% | Fix fee model, position sizing |
| 3_agree PF | 4.05 | >2.0 | Already crushing it |
| 2_agree PF | negative | >1.5 | Block losing combos |
| Sharpe | -5.54 | >1.0 | Need all fixes + fee optimization |
| regime_trend PF | 1.78 | >1.5 | Already profitable |

**Note**: These numbers are pre-regime-fix. Rerun backtest to see impact of proper regime classification.

---

## 12. File Reference Map <a id="12-file-reference"></a>

### Entry Points
```
bot/run.py          → Quick launcher (paper, backtest, signals, status, positions)
bot/cli.py          → Full CLI (paper, replay, live, evolve, tiers, optimize, walkforward)
bot/bot.py          → Bot class
bot/multi_strategy_main.py → Multi-strategy main loop (6,028 lines — needs breakup)
```

### Strategies & Ensemble
```
bot/strategies/base.py               → Signal dataclass, BaseStrategy abstract class
bot/strategies/ensemble.py           → Weighted veto ensemble (regime-aware, soft-filter)
bot/strategies/regime_trend.py       → Regime trend following (ADX filter, regime metadata)
bot/strategies/confidence_scorer.py  → Multi-factor momentum scoring (ADX filter, regime metadata)
bot/strategies/multi_tier_quality.py → Multi-TF signal quality (ADX filter, regime metadata)
bot/strategies/monte_carlo_zones.py  → Monte Carlo S/R (disabled, regime metadata added)
bot/strategies/funding_rate.py       → Funding rate mean-reversion (regime metadata)
bot/strategies/oi_delta.py           → Open interest delta (regime metadata)
bot/strategies/bollinger_squeeze.py  → Bollinger/Keltner squeeze + bandwalk (regime metadata)
bot/strategies/vmc_cipher.py         → 5-oscillator confluence + divergence (regime metadata)
bot/strategies/lead_lag.py           → BTC→alt catch-up trades (regime metadata)
bot/strategies/liquidation_cascade.py → Post-cascade reversal (regime metadata)
bot/strategies/probability_engine.py → Regime-conditional Monte Carlo (regime metadata)
bot/strategies/chop_detector.py      → Multi-factor chop detection
bot/strategies/regime_detector.py    → Regime classification + transition detection
```

### Execution
```
bot/execution/position_manager.py  → Position lifecycle state machine
bot/execution/leverage.py          → Leverage tiers and sizing
bot/execution/risk.py              → Circuit breakers, daily loss limits
bot/execution/adaptive_risk.py     → Dynamic risk adjustment (wired)
bot/execution/graduated_drawdown.py → 6-band progressive risk reduction
bot/execution/trade_profile.py     → Trade profiles (SCALP/MEDIUM/TREND/REGIME)
bot/execution/order_executor.py    → CCXT order submission (paper/live)
bot/execution/reconciliation.py    → Position reconciliation (wired)
bot/execution/ops_guard.py         → Operational safety checks
bot/execution/pnl_engine.py        → PnL calculation
bot/execution/tp_sl_engine.py      → Take-profit/stop-loss engine
```

### LLM Pipeline
```
bot/llm/decision_engine.py          → Monolithic LLM decision pipeline
bot/llm/agents/coordinator.py       → Multi-agent pipeline orchestration
bot/llm/agents/prompts.py           → 9 specialist prompts
bot/llm/agents/base.py              → Agent types, configs, defaults (9 agents)
bot/llm/agents/learning_integration.py → Wires agent output to learning systems
bot/llm/agents/shared_context.py     → Shared reasoning + STRATEGY_REGIME_FIT (11 strategies, 8 regimes)
bot/llm/agents/thought_protocol.py   → OBSERVE→RECALL→REASON→DECIDE→JUSTIFY
bot/llm/agents/consistency_checker.py → Cross-agent coherence validation
bot/llm/agents/calibration_ledger.py → Per-agent accuracy tracking
bot/llm/usage_tiers.py              → Model routing (Haiku/Sonnet/Opus)
bot/llm/client.py                   → Raw Anthropic API wrapper
bot/llm/thesis_tracker.py           → Directional prediction accuracy (wired)
bot/llm/confidence_calibrator.py    → Confidence curve calibration (wired)
bot/llm/counterfactual_learner.py   → Missed opportunity analysis (wired)
bot/llm/quant_data.py               → Quantitative data enrichment
bot/llm/brain_wiring.py             → Centralized getter functions for brain components
```

### Core Pipeline
```
bot/core/signal_pipeline.py        → 6-stage sequential risk filter
bot/core/signal_tracker.py         → All signal tracking (approved + rejected)
bot/core/filter_annotations.py     → Soft-filter architecture (near-miss signals)
```

### Configuration & Data
```
bot/trading_config.py   → Centralized config (490+ lines, dataclass-based)
bot/data/db.py          → SQLite persistence
bot/data/fetcher.py     → Multi-exchange OHLCV + parallel prefetch
bot/data/strategy_weights.py → Rolling strategy performance weights
```

### Backtest
```
bot/backtest/engine.py        → Full backtest engine (91% fidelity)
bot/backtest/walk_forward.py  → Walk-forward validation
```

### Feedback & Analytics
```
bot/feedback/signal_quality.py     → Signal quality scoring
bot/feedback/evolution_tracker.py  → Strategy evolution reports
bot/feedback/continuous_backtest.py → Continuous backtesting
bot/feedback/parameter_tuner.py    → Parameter optimization
```

---

## Priority Order (What to Work On Next)

> Updated March 12, 2026. All regime fixes complete. All 11 strategies emit regime metadata. Backtest engine has regime-fit filtering. Agent prompts modernized for 11 strategies. Focus: paper validate → backtest with regime fix → go live.

### Completed
1. ~~**Phase 2.8: Fix 6 critical bugs**~~ ✅ DONE
2. ~~**Phase 2.9: Fee economics**~~ ✅ DONE
3. ~~**Phase 3.1-3.6: Signal quality + anti-spam**~~ ✅ DONE
4. ~~**Deep 10-agent audit**~~ ✅ DONE — 30+ bugs fixed
5. ~~**Phase 6.2: 7 new quant strategies**~~ ✅ DONE
6. ~~**Phase 6.3: LLM brain intelligence**~~ ✅ DONE
7. ~~**Phase 7.1: Proactive risk + brain wiring**~~ ✅ DONE
8. ~~**Phase 7.2: Zero-trade blocker**~~ ✅ DONE — regime was always "unknown"
9. ~~**Phase 7.3: Backtest regime parity + prompt modernization**~~ ✅ DONE — all 11 strategies set regime metadata, backtest applies STRATEGY_REGIME_FIT, agent prompts updated

10. ~~**Phase 8: Quant-grade mathematical foundation**~~ ✅ DONE — Kelly sizing wired, EV slippage parity, ADX graduated, deflators configurable, age-weighted strategy weights, isotonic calibration

### NOW — Critical Path to Profitability
11. **Run 30d backtest with quant changes** — Validate Kelly sizing, tighter EV, graduated ADX
    - `cd bot && python run.py backtest --symbols BTC SOL HYPE --days 30`
    - Check: Kelly sizing logs appear, fewer marginal signals pass EV, ADX 10-22 signals penalized not killed

12. **Paper trade 48-72h** — Run with `cd bot && python run.py paper`. Watch for:
    - Are signals actually being generated now? (regime fix should unlock them)
    - Kelly sizing modulating risk per trade (check logs)
    - Which of the 11 strategies contribute to consensus?
    - Thesis accuracy tracking from first live predictions

### NEXT
12. **Go live conservative** — SOL+HYPE only, 1% risk, max 3x leverage, 3_agree required
13. **Phase 4.1: Break up `multi_strategy_main.py`** — 6,028 lines is unsustainable
14. **Per-strategy regime performance** — data-driven tuning of STRATEGY_REGIME_FIT (needs paper data)
15. **Phase 5: Config extraction** — single source of truth, startup validation
16. **Telegram signal integration** — wire incoming Telegram signals to Scout Agent
17. **Phase 7.4: Self-improving architecture** — portfolio agent, auto-prompt evolution

### BACKLOG
17. Monte Carlo strategy re-evaluation with 11-strategy ensemble
18. Proper ADX-based standalone regime (replace volatility proxy)
19. Phase 6.1: Full pipeline replay backtesting (needs LLM decision history)
20. Phase 6.4: Strategy discovery agent activation
21. Hour-gated trading (needs 30+ days of live data)
22. Prompt versioning & A/B testing
23. Order flow analysis (Hyperliquid orderbook depth)
24. Cross-exchange signals (Kraken/Bybit as leading indicators)
25. Deep RL integration
26. Multi-bot coordination

---

*This document is the single source of truth for the nunuIRL roadmap. Update it as phases are completed.*
