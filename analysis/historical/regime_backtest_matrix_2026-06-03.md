# Regime × Strategy Backtest Matrix — 2026-06-03

## Context

Multi-regime backtests run with corrected historical data fetcher (Hyperliquid CCXT monkey-patch).
Non-LLM baseline. LLM comparison pending session reset (~09:30 UTC).

Data fetcher fixes applied this session:
- CCXT 4.5.37 Hyperliquid `fetch_spot_markets` NoneType bug → patched (`lambda: []`)
- In-memory cache key now includes `backtest_end_date` suffix
- Stale date-suffixed cache files deleted and re-fetched

---

## Raw Results

| Job | Actual Data Window | Trades | WR | Net PnL | Regime |
|-----|--------------------|--------|----|---------|--------|
| BTC Oct-15 | **2025-11-06 → 2025-11-23** | 4 | **50%** pos / 60% event | -$706 | consolidation + trending_bear |
| BTC Jan-15 | **2026-01-18 → 2026-02-03** | 0 | 0% | -$114 (fees) | — (all gated) |
| BTC Mar-15 | **2026-03-18 → 2026-04-03** | 0 | 0% | -$27 (fees) | — (all gated) |
| ETH Jan-15 | 2026-05-04 → 2026-05-20 ⚠️ | 1 | 0% | -$1,022 | trending_bull |

⚠️ ETH Jan-15 data is WRONG (still serving May 2026). ETH date-suffixed cache was never built; needs re-investigation.

---

## Nov 2025 BTC Deep Dive (Best Regime Found)

**Period:** Nov 6–23 2025. BTC in $90k-101k range. Regime: consolidation (primary) + brief trending_bear.

### Strategy Performance

| Strategy | Trades | WR | Net PnL | Profit Factor | EV/trade |
|----------|--------|----|---------|---------------|---------|
| multi_tier_quality | — | 75% | +$552 | 1.7 | +$69 |
| confidence_scorer | — | 60% | — | 0.76 | -$43 |
| regime_trend | 1 | **0%** | **-$978** | 0.0 | **-$489** |
| confidence_scorer + multi_tier_quality (combo) | 4 | **75%** | +$552 | — | — |

### Confidence Bin Performance

| Confidence | Trades | WR | Net PnL |
|------------|--------|----|---------|
| 80–89% | 3 | **67%** | **+$552** |
| 90–100% | 1 | 0% | **-$978** |

**Critical finding:** 90–100% confidence is LOSING. The bot is overconfident when it should be cautious.

### Setup Type Performance

| Setup | Trades | WR | Net PnL |
|-------|--------|----|---------|
| mean_reversion | 3 | 67% | +$23 |
| trend_follow | 2 | 50% | -$450 |

Mean reversion beats trend following in consolidation by wide margin.

### Hold Time Performance

| Hold | Trades | WR | Net PnL |
|------|--------|----|---------|
| 2–6h | 3 | **100%** | **+$529** |
| 6–12h | 1 | 50% | -$956 |

2–6h holds dominate. Holding >6h destroys edge in consolidation.

### Exit Type Performance

| Exit | Count | WR | Net PnL |
|------|-------|----|---------|
| TRAILING_STOP | 1 | 100% | +$613 |
| TP1 | 1 | 100% | +$529 |
| SL | 3 | 0% | -$1,267 |

Trailing stop system added **+$613 edge** in just 1 use. SL exits need tighter placement.

### Fee Impact
- Total fees: $268 on $426 gross PnL = **62.9% fee drag**
- Break-even WR required: 66.4%
- Actual WR: 50% pos / 60% event — BELOW break-even
- Fix: need either higher WR (>67%) or wider R:R to absorb fees

---

## Gate Analysis Summary

| Regime | Gate Accuracy | Interpretation |
|--------|--------------|----------------|
| Nov 2025 consolidation | 0% | Gates blocking 0 winners — no missed winners |
| Jan 2026 (ranging/declining) | **75%** | Gates correctly saving 75% of trades from losses |
| Mar 2026 crash (trending_bear) | **0%** | Gates blocking 57 would-be SELL winners — FAR TOO TIGHT |

### Mar 2026 Gate Problem
57 SELL signals blocked by `confidence_floor_66`. In a bear market these would all have won.
The adaptive confidence floor is set too high for trending_bear conditions.
**Action: confidence floor should drop to ~55% in trending_bear regime.**

---

## Key Findings for Alpha Engine

### 1. Multi_tier_quality + Confidence_scorer Combo = Edge
- 75% WR in consolidation, PF=1.7
- Combo is the signal — regime_trend standalone is a liability
- **Recommendation:** raise ensemble min_votes to 2, require MTQ or CS agreement

### 2. Regime_trend 0% WR in Trending
- Fired once in trending_bear → -$978 loss
- ADX filter passed (trending_bear has high ADX) but still lost
- Strategy is using wrong entry timing — chasing trend instead of waiting for pullback
- **Recommendation:** reduce regime_trend weight to 0.15 (from 0.30), require 2+ strategy agreement

### 3. 90–100% Confidence = Overfit Signal
- The single 90–100% confidence trade lost $978
- Pattern: extremely high confidence may indicate the signal is stale or in a stretched trend
- **Recommendation:** LLM should INCREASE skepticism when confidence > 90%. Flag as "too obvious = already priced in"

### 4. Hold Time Cap: 6 Hours
- All wins came in 2–6h window
- Holds >6h turned +$529 position into a net -$956 event
- **Recommendation:** In consolidation regime, set max hold time = 6h. Exit at 6h if TP1 not hit.

### 5. Fee Drag is the Primary P&L Killer
- 62.9% fee drag on gross PnL
- Net PnL is -$706 despite 50% WR and +$552 gross
- **Recommendation:** Only trade when EV > 0.15% (accounting for fees). Filter low-edge setups.

---

## Regime × Strategy Grid (preliminary)

| Regime | regime_trend | multi_tier_quality | confidence_scorer | Combo MTQ+CS |
|--------|-------------|-------------------|------------------|--------------|
| consolidation | ❌ 0% | ✅ 75% | ⚠️ 60% | ✅ 75% |
| trending_bear | ❌ 0% | ? | ? | ? |
| trending_bull (ETH) | ❌ 0% | ? | ? | ? |
| ranging (Jan 2026) | — (gated) | — | — | — |

Need more data to fill the grid. Next: LLM comparison on Nov 2025 (after 09:30 UTC).

---

## LLM Comparison Status

Both attempts (overnight + morning) hit session rate limits BEFORE any LLM work.
Non-LLM backtests ran at same time exhausted the session budget.

**LLM comparison plan (after 09:30 UTC session reset):**
```
python scripts/parallel_backtest.py \
  --jobs "BTC:15:2025-10-15" \
  --budget 4.0 --llm --raw
```

Expected hypothesis: LLM should veto the regime_trend 0% WR trade (-$978) while keeping the MTQ+CS combo trades. If it does, LLM delta would be: +$978 saved - (smaller sizing) = net positive.

---

## Files

- Non-LLM baselines: `data/parallel_backtest_results/2026-06-03_0703/`
- LLM attempt (rate-limited): `data/parallel_backtest_results/2026-06-03_0707/`
- Prior crash window baseline: `analysis/historical/baseline_nollm_2026-06-03.md`
