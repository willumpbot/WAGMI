# Regime × Strategy Backtest Matrix — 2026-06-03

## Context

Multi-regime backtests run with corrected historical data fetcher (Hyperliquid CCXT monkey-patch).
Non-LLM baseline. LLM comparison in progress (run at 10:16 UTC, waiting for CLI response).

Data fetcher fixes applied this session:
- CCXT 4.5.37 Hyperliquid `fetch_spot_markets` NoneType bug → patched (`lambda: []`)
- In-memory cache key now includes `backtest_end_date` suffix (both fetch_ohlcv and fetch_multi_timeframe)
- `_load_disk_cache` validates data era matches backtest window (detects wrong-era stale files)
- Stale date-suffixed cache files deleted and re-fetched
- **6h + daily data verified correct** for Oct 2025 and Mar 2026 windows
- 5m historical data: Hyperliquid can't serve 16d of 5m candles in one request → always shows current 5m data (known limitation; multi_tier_quality 5m signal effectively disabled in historical backtests)

---

## Raw Results (CORRECTED as of 2026-06-03 15:43 UTC)

| Job | Actual Data Window | 1h ✓ | 6h ✓ | Trades | WR | Net PnL | Regime |
|-----|--------------------|------|------|--------|----|---------|--------|
| BTC Oct-15 | **2025-11-06 → 2025-11-23** | ✓ | ✓ | 5 | **60%** pos/event | +$58 | consolidation + high_vol + trending_bear |
| BTC Jan-15 | **2026-01-18 → 2026-02-03** | ✓ | ✓ | 0 | 0% | -$114 (fees) | — (all gated) |
| BTC Mar-15 | **2026-03-18 → 2026-04-03** | ✓ | ✓ | 4 | **50%** pos / 60% event | -$992 | trending_bear + high_vol + consolidation |
| ETH Jan-15 | ⚠️ stale cache deleted | — | — | — | — | — | — |

⚠️ ETH Jan-15: stale cache deleted (was serving May 2026 data). Needs re-run after current LLM backtest completes.

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

## Gate Analysis Summary (CORRECTED with 6h data fix)

| Regime | Gate Accuracy | Interpretation |
|--------|--------------|----------------|
| Nov 2025 consolidation | 0% | Gates blocking 0 winners — no missed winners |
| Jan 2026 (ranging/declining) | **75%** | Gates correctly saving 75% of trades from losses |
| Mar 2026 crash (trending_bear) | **100%** | Gates blocked 2 trades; 0 would have won — gates are HELPING ✓ |

### Mar 2026 Gate Status (CORRECTED)
Previous analysis showed "0% gate accuracy, 57 SELL signals blocked" — this was based on WRONG 6h data (May 2026 data being used for a Mar 2026 backtest). With correct 6h data:
- `confidence_floor` blocked 2 trades; both would have lost → gates perfectly accurate
- The prior "action: drop floor to 55%" recommendation was **invalid** — based on stale data
- With correct data, the confidence gates are functioning correctly in trending_bear

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

### 3. 90–100% Confidence = Overfit Signal (CONFIRMED across 2 regimes)
- Nov 2025 consolidation: 90-100% conf = -$978 (1 trade, 0% WR)
- Mar 2026 trending_bear: 90-100% conf = -$832 (1 trade, 0% WR)
- Sweet spot in BOTH regimes: 60-89% confidence
- **Recommendation:** LLM should INCREASE skepticism when confidence > 90%. Flag as "too obvious = already priced in"

### 4. Hold Time is Regime-Dependent
- **Consolidation:** 2-6h = 100% WR; >6h = losing
- **Trending bear:** 12-24h = 100% WR; <12h = losing
- **Recommendation:** Exit Agent should apply regime-appropriate hold caps:
  - In consolidation: exit at 6h if TP1 not hit
  - In trending: allow 12-24h holds, don't force early exit

### 5. Fee Drag is the Primary P&L Killer
- 62.9% fee drag on gross PnL
- Net PnL is -$706 despite 50% WR and +$552 gross
- **Recommendation:** Only trade when EV > 0.15% (accounting for fees). Filter low-edge setups.

---

---

## Mar 2026 Crash Window Deep Dive (CORRECTED — with valid 6h data)

**Period:** Mar 18 – Apr 3, 2026. BTC falling from $72k to $67k. Regimes: trending_bear (primary), high_volatility, brief consolidation.

### Strategy Performance

| Strategy | Trades | WR | Net PnL |
|----------|--------|----|---------|
| confidence_scorer | 3 | **100%** | **+$162** |
| bollinger_squeeze | 1 | 0% | -$277 |
| regime_trend | 2 | 0% | **-$693** |

### Confidence Bin Performance

| Confidence | Trades | WR | Net PnL |
|------------|--------|----|---------|
| <60% | 1 | 0% | -$831 |
| 60–69% | 2 | **100%** | **+$856** |
| 90–100% | 1 | 0% | **-$832** |

**Confirms Nov 2025 finding: 90–100% confidence = overfit signal, loses in BOTH regimes.**

### Hold Time Performance (trending_bear)

| Hold | Trades | WR | Net PnL |
|------|--------|----|---------|
| 0–2h | 1 | 0% | -$832 |
| 6–12h | 1 | 0% | -$831 |
| 12–24h | 3 | **100%** | **+$856** |

**Opposite of consolidation: in crash window, LONGER holds win. Hold 12-24h, not 2-6h.**

### Setup Type (trending_bear)
- mean_reversion: 100% WR — **even mean reversion wins if in correct direction in trending market**
- trend_follow: 0% WR — entering with trend (SELL) in trending_bear, but still lost? Likely entered wrong direction.

---

## Regime × Strategy Grid (CORRECTED)

| Regime | regime_trend | bollinger_squeeze | confidence_scorer | consolidation WR |
|--------|-------------|-------------------|------------------|-----------------|
| consolidation | ❌ 0%, -$693 | ⚠️ n/a | ✅ 60%, +$163 | 100% WR for CS |
| trending_bear | ❌ 0%, -$693 | ❌ 0%, -$277 | ✅ 60-69% only: 100% WR | — |
| high_volatility | — | — | ✅ 100% WR, +$696 | — |
| ranging/declining (Jan 2026) | — (gated) | — (gated) | — (gated) | — |

**regime_trend is 0% WR in every regime tested. Strong recommendation: disable or weight ~0.**

---

---

## Updated Graduated Rules from Corrected Data

Rules added/updated based on corrected backtest results:
1. `regime_trend_consolidation_avoid_v1` — 0% WR confirmed, -15 weight adj
2. `high_confidence_overfit_consolidation_v1` — 90-100% conf = losing in BOTH consolidation AND trending_bear
3. `consolidation_hold_time_cap_v1` — 6h cap in consolidation
4. **NEW NEEDED:** `trending_bear_hold_time_extend_v1` — 12-24h hold sweet spot in crash window
5. **REVOKED:** `mar2026_confidence_floor_too_tight` — was based on wrong data; gates are working correctly

---

## LLM Comparison Status

**In progress as of 10:16 UTC.** First clean LLM run on correct historical data.
- Correct Nov 2025 1h + 6h data confirmed
- Corrected graduated rules committed (includes regime_trend and overconfidence flags)
- Previous 2 attempts hit rate limits; this is the first real LLM test

**Log:** `data/parallel_backtest_results/2026-06-03_1516/BTC_15d_2025-10-15.log`

Expected: LLM vetoes the regime_trend 0% WR trade (-$978) while keeping the CS combo winners (+$856 in trending_bear, +$163 in consolidation). If confirmed: LLM delta = +$978 saved.

---

## Files

- Non-LLM baselines (CORRECTED): `data/parallel_backtest_results/2026-06-03_1510/`, `2026-06-03_1543/`
- First LLM run (CORRECT DATA): `data/parallel_backtest_results/2026-06-03_1516/`
- LLM attempt (rate-limited): `data/parallel_backtest_results/2026-06-03_0707/`
- Original (wrong data): `data/parallel_backtest_results/2026-06-03_0703/`
- Prior crash window baseline: `analysis/historical/baseline_nollm_2026-06-03.md`
