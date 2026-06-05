# Multi-Timeframe Alignment Design

**Date:** 2026-06-02  
**Author:** laptop-claude  
**Source:** Item C from LAPTOP_AUTONOMOUS_MASTER_BRIEF.md

---

## Current State Audit

### What the Fetcher Supports

All 7 timeframes are implemented in `bot/data/fetcher.py`:

| Timeframe | CCXT Limit | Coverage | Status |
|-----------|-----------|----------|--------|
| 5m | 300 candles | ~25 hours | Fetched ✅ |
| 15m | 200 candles | ~50 hours | Fetchable ❌ (zero code references) |
| 30m | 100 candles | ~50 hours | Fetchable ❌ |
| 1h | 200 candles | ~8 days | Fetched ✅ |
| 4h | 200 candles | ~33 days | Fetchable ❌ (zero code references) |
| 6h | 200 candles | ~50 days | Fetched ✅ |
| 1d | 200 candles | ~6 months | Fetched ✅ (monte_carlo_zones) |

### What Strategies Use

| Strategy | Timeframes |
|----------|-----------|
| regime_trend | 1h, 6h |
| monte_carlo_zones | daily |
| multi_tier_quality | 1h, 6h |
| confidence_scorer | 1h, 6h |
| **Union** | **1h, 6h, daily** |

### What LLM Agents See

- **1h technicals**: formatted indicator summary (RSI, EMA, BB, MACD, ATR)
- **5m technicals**: already computed via `compute_all_technicals(_ohlcv_5m)` in `coordinator.py` — agents see 5m indicators alongside 1h
- **Missing**: 15m rhythm, 4h structure, 1d macro narrative

---

## The Gap

Agents decide with: 1h structure + 5m micro-noise + no intermediate context.

The 4h timeframe bridges the 1h entry signal and the daily macro regime. A 1h breakout that aligns with 4h trend is a higher-conviction entry than one that runs against the 4h structure. This is one of the most-cited improvements in systematic trading literature.

15m provides the entry rhythm that 5m is too noisy for: a 15m EMA crossover on the 5m setup gives the timing edge without the noise.

---

## Implementation Plan

### Phase 1 — 4h Context (High Value, Low Effort) — IMPLEMENT NOW

**Files to change:**
1. `bot/multi_strategy_main.py` — add `"4h"` to the timeframes requested per symbol
2. `bot/llm/agents/coordinator.py` — inject 4h technicals into agent snapshot alongside 1h

**What to inject into agents:**
```
4h_trend: bullish/bearish/neutral (based on EMA50 vs price)
4h_rsi: value (overbought/oversold context)
4h_structure: "price above 4h EMA50, 4h RSI=58, ATR_4h=$182"
```

**Why this works:** The 4h lookback (200 candles = 33 days) covers enough history to define the macro intermediate trend. Agent sees "1h says buy, but 4h says we're in a 33-day downtrend" and adjusts confidence accordingly.

**Effort:** ~2 hours. No new strategy needed. Just fetch + compute + inject text string.

### Phase 2 — 15m Entry Rhythm (Medium Value, Low Effort)

**What to add:**
- Fetch 15m OHLCV (200 candles = 50h lookback)
- Compute 15m EMA crossover status: "crossed up 2 candles ago" / "crossed down 5 candles ago"
- Inject as single field: `entry_rhythm: "15m EMA9 crossed above EMA21, 2 candles ago"`

**Why this matters:** 5m is too noisy for timing confirmation. 15m EMA crossovers are the standard entry-timing rhythm in crypto day trading. Currently the bot enters on signal generation, not on entry timing.

**Effort:** ~1 hour.

### Phase 3 — Timeframe Consensus Score (Lower Priority)

**Idea:** Count how many timeframes agree on direction:
- 5m: short-term momentum direction
- 15m: entry rhythm
- 1h: structural direction
- 4h: intermediate trend
- 6h: regime confirmation

Consensus score (0-5): inject into agent context as `tf_consensus: 3/5 bullish`. Agent uses this as a conviction multiplier — trades with high consensus → higher confidence tier → more risk.

**Effort:** ~3 hours. Requires all phases above.

---

## Priority Order

| Phase | What | Effort | Impact |
|-------|------|--------|--------|
| 1 | 4h context in agent snapshot | 2h | High — structural alignment filter |
| 2 | 15m entry rhythm | 1h | Medium — timing confirmation |
| 3 | Timeframe consensus score | 3h | Medium — conviction multiplier |

---

## What NOT to Do

- **Don't add 4h as a strategy signal.** The strategy layer is consensus-based. Adding 4h as another strategy vote would dilute the signal. Use it only for LLM agent context — let the agent interpret it.
- **Don't inject raw OHLCV.** 200 candles of raw 4h data = ~8,000 tokens. Use computed summary strings instead.
- **Don't add 30m.** It's between 15m and 1h and adds redundancy without covering a gap.

---

## Next Steps

Phase 1 (4h context) is the clear immediate win. Implementation can proceed now — it's a pure agent context enrichment with no strategy changes needed.
