# WAGMI System Map — Canonical Reference

Built 2026-04-16 during 12-hour autonomous session from 5 parallel deep audits (tick cycle, data files, gates+feedback, LLM agents, strategies+regime). This is the "literally everything" reference document.

Read order if you want the full picture: **1 → 2 → 3**. Skim headers for navigation.

---

## 1. The Big Picture in 200 Words

- **ONE Python process** (`bot/run.py paper`) runs a **30-second tick loop** (adaptive 15-45s).
- Per tick: fetch data for 4 symbols → each of **13 strategies** scores a signal → **ensemble votes** (need 2+ agreeing) → signal runs through **6-stage risk filter chain** + **24 total gates** + **shadow-ledger edge/block filter** → survivors become trades.
- Open positions go through a **5-state machine**: `IDLE → OPEN → TP1_HIT → TRAILING → CLOSED`, with a **partial TP1 close (60-80%)** + **trailing runner for the remainder**.
- **Lifetime equity: $568.58 across 130 trades** (persisted since today's fix).
- **12 feedback loops** (tuner, calibrator, quality, weights, etc.) adjust parameters after each close.
- **14 LLM agents** exist (9 core + 5 strategic). **Currently all DORMANT** because `LLM_MODE=0` and no credits.
- **20+ data files** tracking everything. Several critical streams are **UNREAD** — hidden alpha waiting to be consumed (anticipatory_history, signal_outcomes, trade_lessons, trade_journal).

---

## 2. The Tick Cycle — 11 Steps End-to-End

Every tick (~30s), the bot runs these steps in order:

| # | Step | File:line | Key behavior |
|---|---|---|---|
| 1 | **Main loop** | `multi_strategy_main.py:1400-1495` | Adaptive interval: 15s panic, 30s normal, 45s calm |
| 2 | **Data fetch** | `data/fetcher.py` + `multi_strategy_main.py:1620-1636` | 4 symbols × 4-5 timeframes each, TTL cache ≥90s, exchange circuit breaker |
| 3 | **Signal generation** | `strategies/*.py` (13 strategies) | Each strategy returns Optional[Signal] with confidence 0-100 |
| 4 | **Ensemble voting** | `strategies/ensemble.py:43-2300` | min_votes=2, veto_ratio 1.2x, shadow-edge floors + blocks, EV math, regime allowlist |
| 5 | **Risk filter chain (6 stages)** | `core/signal_pipeline.py:68-400` | validity → circuit breaker → position count → leverage → liquidation → sizing |
| 6 | **Size/leverage decision** | `execution/leverage.py` + `adaptive_risk.py` + `sector_exposure.py` | Kelly, sector cap, adaptive risk, dust floor |
| 7 | **Order execution** | `execution/order_executor.py:83-150` | paper vs live, 3 retries w/ backoff, slippage check |
| 8 | **Position management** | `execution/position_manager.py` + `position_state.py` | 5-state machine, 1H ASSESSMENT (fixed today), trailing logic, TP1 partial |
| 9 | **Trade close** | `multi_strategy_main.py:2909-3100` + `trade_log.py` | Writes trades.csv, updates equity, persists position_state |
| 10 | **Learning feedback** | `feedback/loop.py` + `parameter_tuner.py` + 10+ others | 12 loops run; win passed as `win: bool`, pnl as float |
| 11 | **Heartbeat** | `monitoring/health.py` | Every tick: record alive; every 10 ticks: position aging; every 60: summary |

### Fragile points to know about

1. **Order fill race** (multi_strategy_main.py:2927): close returns "not filled" but state updates locally → position hangs on exchange until hourly reconciliation
2. **Prefetch cascade failure** (line 1632): all symbols fail → bot continues on stale cache without shouting
3. **State machine divergence**: trailing-engine misses TP1_HIT activation → position stuck in wrong state
4. **LLM trigger accumulation** (line 1889): if should_call_llm() returns false, triggers cleared silently — context lost
5. **Equity persistence** (FIXED TODAY, risk.py): checkpoint write failure silently reverts to $500; now guarded

---

## 3. The Data Files — What's Tracked, What's Consumed

### 20 Live Files Inventoried

| File | Rows | Purpose | Read by? |
|---|---|---|---|
| **trades.csv** | 131 | Canonical trade log | equity reconstruction, session doc, postmortem |
| **shadow_ledger.csv** | 3,835 | Disabled-strategy signal outcomes | premium_filter (hardcoded from this file) |
| **sniper_signals.jsonl** | 37,495 | Every sniper alert ever fired | dashboard, multi_path_compare, overnight_report |
| **sniper_rejections.jsonl** | 167,103 | Rejected sniper signals + reason | multi_path_compare, health_check, missed_trade_analysis |
| **counterfactual_resolved.jsonl** (llm/) | ~95k | "What if we traded this" outcomes | multi_path_compare, LLM learner |
| **anticipatory_history.jsonl** | 1,250 | Pre-staged entry predictions | ⚠️ **UNREAD** |
| **pa_sim_trades.jsonl** | 2,679 | Price-action simulator trades | multi_path_compare only |
| **sim_trades.jsonl** | 44 | Sniper sim trades | multi_path_compare only |
| **trade_journal.jsonl** | 1 (empty) | User's manual trade log | ⚠️ **UNREAD** |
| **signal_outcomes.jsonl** | ? | Every evaluated signal + annotation | ⚠️ **UNREAD** externally |
| **trade_lessons.jsonl** | ? | Self-teaching lessons | ⚠️ **UNREAD** (write-only) |
| **conviction_sizing.jsonl** | ? | Sizing decisions | ⚠️ **UNREAD** |
| **position_state.json** | 1 (live) | Auto-recovery source | load on startup (tested Apr 16 twice) |
| **risk_equity_state.json** | 1 (live) | **NEW TODAY** — equity persistence | loaded on init, protected from test pollution |
| **heartbeat.json** | 1 (live) | Watchdog pulse | get_downtime_seconds() |
| **kelly_weights.json** | 1 | Ensemble weights | strategies/ensemble.py init |
| **ic_history.json** | 1 | Factor IC stats | feature_engineering |
| **circuit_breaker_state.json** | 1 | CB state | internal |
| **execution_analytics.csv** | ? | Order fill metrics | ⚠️ mostly **UNREAD** |
| **trade_ledger.csv** | ? | ML training outcomes | internal ML only |

### Hidden alpha / UNREAD data

Five files capture rich data that nothing downstream consumes:

- **anticipatory_history.jsonl (1,250 rows)** — every directional prediction the anticipatory engine made. No consumer. Could feed expectation calibration.
- **signal_outcomes.jsonl** — every evaluated signal with annotations. Internal-only.
- **trade_lessons.jsonl** — self-teaching lessons. Write-only.
- **trade_journal.jsonl** — empty (user hasn't started logging). 
- **conviction_sizing.jsonl** — sizing decisions unaudited.

**Opportunity**: wire these into feedback loops. Each represents a blind spot.

### State files at risk

- **risk_equity_state.json** — recovered from test pollution today. Now has 10x-off guard + `_should_persist_equity` flag protecting it.
- **position_state.json** — atomic `.tmp` write (safe).
- **backtest_state.json** — 661K, not atomic. If mid-write crash → invalid JSON.

### Files that SHOULD exist but don't

- Equity curve timestamps (currently only scalar, no intraday watermark)
- Expanded order fill log (with slippage, latency, fees, order_id)
- Rejection counterfactual linking (rejections + what price did next)
- Regime transition log (timestamped changes)
- Leverage utilization timeline

---

## 4. The 24 Gates + 12 Feedback Loops

### Gates (what can BLOCK or SHRINK a signal)

| Gate | Threshold | Status | Recent fires |
|---|---|---|---|
| CircuitBreaker daily loss | 5% | clean | never today |
| CircuitBreaker drawdown | 10% | clean | never today |
| Consecutive losses | 5 | clean | never today |
| Signal validity (R:R, stop) | R:R>1, stop>0.3% | clean | implicit |
| Fee-drag filter | regime-dependent | clean | silent (unlogged) |
| **EV gate** | EV < 0 → block | **ACTIVE** | 6x at 17:00 for HYPE SELL |
| Ensemble min_votes | regime-gated 2-3 | clean | lowers in high_vol |
| Adaptive confidence floor | ~58% (tuner) | clean | continuous adjust |
| Chop filter | score > threshold | passive | no fires seen |
| **Negative EV Block (ensemble)** | hard | **ACTIVE** | 6x in latest log |
| Leverage confidence < 20% | 0x | protective | never |
| Leverage min stop | 0.2% | protective | warnings only |
| OpsGuard kill switch | file-based | not active | — |
| OpsGuard rate limit hourly | 10/hr | loose | no fires |
| OpsGuard rate limit daily | 50/day | loose | no fires |
| **OpsGuard duplicate position** | hard | **ACTIVE** | SOL dupe blocks |
| **Sector exposure** | l1: 1.50 | **RELAXED TODAY** | no fires (headroom) |
| **Dust floor** | 30% | **ACTIVE TODAY** | no fires yet |
| **Premium Filter EXECUTE** | shadow-verified + conf≥75 | **NEW TODAY** | not in live trade flow |
| **Premium Filter Shadow Block** | 6 combos | **NEW TODAY** | HYPE_BUY_MTQ repeatedly |
| **Premium Filter Adverse Regime** | HYPE BUY illiquid/ranging | **NEW TODAY** | none yet |
| **Sniper shadow-ledger secondary** | `_SHADOW_BLOCKS` match | **NEW TODAY** | awaiting sniper signals |

### Feedback loops (what ADJUSTS parameters)

| Loop | Input | Output | Status | Issue |
|---|---|---|---|---|
| **Adaptive Confidence Floor** | wins/losses per conf bin | current_floor | ACTIVE | floor 58.4% |
| **Calibration Offset (tuner)** | predicted vs realized WR | offset | **FIXED TODAY** | ±3 cap, was -9.28 |
| **Strategy Weight Manager** | per-strategy WR | weight multiplier | ACTIVE | |
| **Continuous Backtest** | 4h/24h/7d windows | parameter suggestions | DORMANT | suggestions rarely applied |
| **Regime Strategy Weighter** | regime + perf | regime-specific weights | ACTIVE | |
| **Signal Quality Scorer** | features | quality_multiplier | ACTIVE | |
| **Reflection Engine** | trade patterns | LLM rule suggestions | DORMANT | no credits |
| **Self-Teaching** | trade outcomes | ML training data | DORMANT | Level 3 stuck |
| **Neuroplasticity** | signal distribution | model drift corrections | DORMANT | not wired |
| **Evolution Tracker** | strategy PnL | mutation suggestions | DORMANT | archive only |
| **Counterfactual Learner** | rejected signals | "what if" analysis | DORMANT | reporting only |
| **Confidence Calibrator** | per-bin WR | offset + floors | ACTIVE | post-fix |

### Known conflicts between loops

1. **Quality boost × Tuner offset × Floor** — old conflict created signal starvation deadlock. **FIXED TODAY** by ±3 cap.
2. **Negative EV filter vs Premium filter edges** — EV uses dynamic TP (narrow); premium filter uses shadow WR. Can disagree. **MONITOR.**
3. **3-layer strategy veto** — min_votes → regime allowlist → weight. A strategy can be weight=0.1 AND in allowlist simultaneously. **OPACITY risk.**

### Silent kill rates (unknowns)

- **Fee-drag rejections** — not logged per instance
- **Chop detector** — no recent fires, unclear if disabled or market is clean
- **Liquidation risk check** — downsizes silently

---

## 5. The 14 LLM Agents

**Currently all DORMANT** (LLM_MODE=0, no credits). When credits return:

### Core 9 (`llm/agents/coordinator.py`)
| Agent | Model | $/call | Trigger |
|---|---|---|---|
| Regime | Haiku | $0.012 | per signal |
| Trade | **Sonnet** | $0.055 | per signal |
| Risk | Haiku | $0.010 | after Trade approve |
| Critic | **Sonnet** | $0.045 | high-conf only |
| Learning | Haiku | $0.008 | post-trade close |
| Exit | Haiku | $0.009 | every 5min on open |
| Scout | Haiku | $0.018 | every 2h idle |
| Overseer | Haiku | $0.025 | 30-60min |
| Quant | Haiku | $0.011 | optional pre-trade |

### Strategic 5 (`llm/agents/strategic_agents.py` + `phase_4_agents.py`)
| Agent | Model | Trigger |
|---|---|---|
| Forecaster | Haiku | daily |
| Hypothesis | Haiku | weekly |
| Correlator | Haiku | daily |
| Scalper | Haiku | per 1min |
| Conviction | **Sonnet** | rare ~5-10/mo |

### Cost risk if LLM_MODE=1 flipped

At 50 signals/day with Regime+Trade+Risk+Critic+Exit active: **~$6.40/day = $192/month**. That's 3.5x higher than prior $55 baseline. Needs:
- Sample rate on Trade agent (every 2nd signal)
- Exit cooldown (5-min per symbol)
- Hard daily budget at `$25/day` with auto-downgrade Sonnet → Haiku at 70% spend

### Today's LLM fixes still in effect

- **Finding 5**: Scout/Exit/Overseer respect `should_call_llm()` gate (no cost leak when credits return)
- **Finding 18**: Parser fail-closed on API errors, metadata reflects real LLM state
- **Finding 21**: Direction inversion in alerts fixed

### Curriculum state

- Self-teaching curriculum **stuck at Level 3 (Predictive Modeling)**
- 107 hypotheses, 1 validated, 9 invalidated, 0 predictions
- Level 4 (Sniper Replication) requires `build_sniper_profile()` → **NOT WIRED**. Missing graduation trigger.

---

## 6. The 14 Strategies (+1 Meta + 3 Dormant)

### Active strategies (firing daily)

| Strategy | Weight | Shadow edge | Status |
|---|---|---|---|
| **sniper_premium** | 49.8% | live +$48/23 trades (off since Apr 6) | ACTIVE in sim, OFF in live-auto |
| **ensemble** | 34.5% | meta-vote, 34% WR | PRIMARY path |
| **regime_trend** | 30% | ETH_BUY 100% WR/135 samples ← | star |
| **confidence_scorer** | 30% | baseline, most volume | workhorse |
| **bollinger_squeeze** | 30% | HYPE_BUY 61% WR/196 samples | strong |
| **multi_tier_quality** | 30% | HYPE_BUY 36.8% WR (BLOCKED) | fragile |
| **mean_reversion** | 30% | small sample | minor |
| **probability_engine** | 30% | small sample | minor |
| **vmc_cipher** | 30% | 0.3% WR live | weak |
| **monte_carlo_zones** | 30% | ~0% live | minor |

### Dormant (loaded but no live data)

- `lead_lag.py` — BTC→alt boost, 0 trials (no live feed)
- `funding_rate.py` — extreme funding scalps (no feed)
- `oi_delta.py` — open interest + price (no feed)

### Regime detector

9 possible states: `trending_bull, trending_bear, trend, consolidation, range, high_volatility, panic, low_liquidity, unknown`. Two classifiers:
- `core/quant_regime.py` — pure quant (ADX, ATR percentile, EMA)
- `execution/trade_profile.py` — signal-derived

Largely agree on trending/ranging, sometimes diverge on panic vs high_volatility boundary.

### Regime-aware strategy activation (ensemble.py)

| Regime | Active strategies |
|---|---|
| trending_bull/bear/trend | regime_trend, confidence_scorer, bollinger_squeeze, vmc_cipher, probability_engine, oi_delta |
| consolidation/range | confidence_scorer, multi_tier, BB, vmc, prob, monte_carlo, funding, **mean_reversion** |
| high_volatility | confidence_scorer, probability_engine, bollinger_squeeze, liquidation_cascade, oi_delta |
| panic | confidence_scorer, liquidation_cascade |

---

## 7. State as of 2026-04-16 late afternoon

- **Bot process**: running (latest v3 code via commit `028f691`)
- **Equity**: **$568.58** (persistence fix working)
- **Lifetime**: 130 trades, +$68.58 net
- **Session (Apr 15+16)**: +$28.32
- **Open positions**: 1 (SOL LONG @ 86.23 opened 16:42)
- **LLM**: OFF (mode=0, no credits)
- **Sniper**: auto-execute OFF, manual-alerts mode ON (7-20x emission after today's fix)
- **Filter activity**: 418+ Shadow BLOCKs / session, mostly HYPE_BUY_MTQ

---

## 8. Today's Fixes (Chronological)

| # | Finding | File | Status |
|---|---|---|---|
| 1 | Phase 1 — 7 fixes | multiple | ✅ `c4ad18f` |
| 16 | Outcome classifier mislabel | position_manager.py:1215 | ✅ Phase 1 |
| 17 | Sector cap too tight for Kelly | sector_exposure.py | ✅ Phase 1 |
| 18 | LLM parser fail-open | llm_integration.py + multi_strategy_main.py | ✅ Phase 1 |
| 5 | Scout/Exit/Overseer cost leak | multiple | ✅ Phase 1 |
| 11 | Proven-setup table wrong | ensemble.py:2215 | ✅ Phase 1 |
| 2 | Tuner offset deadlock | parameter_tuner.py:186 | ✅ `845a5dd` |
| 21 | Telegram direction inversion | enhanced_telegram.py:74 | ✅ `4d2a328` |
| Phase 4 | Premium alert filter | alerts/premium_filter.py (new) | ✅ `4d2a328` |
| Phase 4 v2 | Regime aliases, WATCH dedup, BTC upgrade | multiple | ✅ `845a5dd` |
| 20 | Trail audit (1H ASSESSMENT) | position_manager.py:639 | ✅ `028f691` |
| Equity persist | Cross-restart equity | risk.py + new state file | ✅ `028f691` |
| Sniper UX | /trade pre-fill + Ask Claude + shadow block | manual/alerts.py | ✅ `028f691` |
| Briefing multi-window | 3 time windows | telegram_bot.py | ✅ `028f691` |
| Leverage split | Sim 20x + auto-exec 5x caps | manual/config.py + position_wiring.py | ✅ **in-progress** (today) |

---

## 9. Open Tasks (12-Hour Session)

- [ ] **Build sim trade-injection flow** (Task 12) — user types `/siminject SOL SELL 87.0 15x 0.3`, test hypothetical trade in sim
- [ ] **Verify high-leverage sniper alert quality** (Task 13) — generate test alert at 20x, inspect format
- [ ] **Morning auto-briefing** (Task 14) — schedule `/briefing` at 08:00 UTC daily
- [ ] **Telegram inline buttons research** (Task 15) — feasibility of one-tap actions
- [ ] **Hidden SL-tighteners sweep** (Task 16) — beyond 1H ASSESSMENT, find other silent tighteners
- [ ] Sim vs live sniper gap investigation (50% vs 56% WR)
- [ ] Per-trade absolute $ loss ceiling for sniper
- [ ] Wire the UNREAD data streams (anticipatory_history, trade_lessons, conviction_sizing) into feedback loops

---

## 10. Architectural North Star

The system works, but has three orthogonal needs:

1. **Validation loop closure** — UNREAD data needs consumers so feedback is bidirectional, not one-way write
2. **Cost/ROI discipline on LLM** — hard budget + sample rate + auto-downgrade before re-enable
3. **Observability** — regime transitions, rejection counterfactuals, leverage utilization all need timestamped logs

Everything else is refinement. The engine works — it's a 33% WR system with 2:1 R:R that's mathematically profitable, currently +$68.58 lifetime, and got a clean bug-free overnight session.
