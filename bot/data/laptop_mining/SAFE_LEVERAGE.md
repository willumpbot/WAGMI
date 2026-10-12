# Mission 9 — safe leverage and adverse-excursion tables

_2026-10-08. 12,994 coin-days across 17 perps, 2024-06-27 → 2026-10-04, path measured on 4h bars.
Train < 2025-06-01 (4,708) / test ≥ 2025-06-01 (8,286). Script: `safe_leverage.py`.
Data: `safe_leverage.json`._

---

## Headline

**The table works, and the single number that matters is this: leverage should be cut roughly in half
when the volatility forecast is hot. For BTC the 99th-percentile one-day move against you goes from
4.7% on the calmest fifth of days to 11.7% on the hottest — so safe leverage falls from about 17x to
about 8x on the same coin.**

Out of sample the bounds hold up: the p95 level built on train covers **94.6%** of test days (claimed
95), and p99 covers **97.7%** (claimed 99). Slightly optimistic, so apply a haircut — see below.

---

## The table, condensed (1-day horizon, long side, 99th percentile)

Q1 = calmest fifth of days by forecast, Q5 = hottest. `maxL` = the largest leverage whose liquidation
sits beyond that adverse move, capped at the coin's own maximum.

| coin | HL max | Q1 forecast | Q1 p99 adverse | **Q1 max lev** | Q5 forecast | Q5 p99 adverse | **Q5 max lev** |
|---|---|---|---|---|---|---|---|
| **BTC** | 40x | 1.57% | 4.70% | **16.8x** | 3.16% | 11.73% | **7.7x** |
| **ETH** | 25x | 2.09% | 6.67% | **11.5x** | 4.18% | 15.52% | **5.7x** |
| **XRP** | 20x | 1.97% | 6.17% | **11.5x** | 5.81% | 22.43% | **4.0x** |
| **SOL** | 20x | 2.53% | 7.18% | **10.3x** | 4.71% | 19.37% | **4.6x** |
| ARB | 10x | 2.87% | 6.25% | 8.9x | 5.45% | 28.69% | 3.0x |
| LINK | 10x | 2.60% | 7.28% | 8.1x | 5.35% | 25.31% | 3.3x |
| DOGE | 10x | 2.50% | 8.20% | 7.6x | 5.15% | 21.02% | 3.8x |
| AVAX | 10x | 2.86% | 8.36% | 7.5x | 5.08% | 22.44% | 3.6x |
| UNI | 10x | 2.88% | 8.78% | 7.3x | 5.52% | 26.07% | 3.2x |
| NEAR | 10x | 3.08% | 10.08% | 6.6x | 5.19% | 21.10% | 3.8x |
| WLD | 10x | 3.66% | 11.29% | 6.1x | 6.36% | 26.07% | 3.2x |
| **HYPE** | 10x | 3.49% | 13.02% | **5.5x** | 5.93% | 20.53% | **3.9x** |
| SUI | 10x | 3.29% | 13.18% | 5.5x | 5.78% | 22.02% | 3.7x |
| ENA | 10x | 3.98% | 13.31% | 5.5x | 6.86% | 21.75% | 3.7x |

Full table — all five quintiles, 1/3/5-day horizons, long and short separately — is in
`safe_leverage.json`, keyed `coin → quintile → horizon → side → {p95, p99}` plus
`max_lev_long_1d_p99` / `max_lev_short_1d_p99`.

### Three things to read off it

1. **Leverage roughly halves from calm to hot.** BTC 16.8x → 7.7x, ETH 11.5x → 5.7x, SOL 10.3x → 4.6x.
   A fixed leverage setting is wrong in both regimes: too timid when calm, dangerous when hot.
2. **The alts are not the majors.** On a hot day ARB's 99th-percentile adverse move is **28.7%** —
   nearly three times BTC's 11.7%. Safe leverage there is 3x, and HL's 10x cap is far above what the
   price action justifies.
3. **HYPE behaves like a small-cap even on calm days.** Its Q1 adverse move (13.0%) is larger than
   BTC's *hottest* quintile (11.7%). Worth knowing given how much of the bot's book sits in HYPE.

---

## Does the table hold out of sample?

Built on train days only, then checked against test days. This is the question that decides whether
it is usable at all — a table that claims 99% and delivers 90% is worse than no table.

| horizon | side | claimed | actual p95 coverage | actual p99 coverage | cells |
|---|---|---|---|---|---|
| 1d | long | 95 / 99 | 94.8% | 97.9% | 64 |
| 1d | short | 95 / 99 | **91.3%** | 96.5% | 64 |
| 3d | long | 95 / 99 | 96.5% | 98.4% | 64 |
| 3d | short | 95 / 99 | 94.6% | 97.7% | 64 |
| 5d | long | 95 / 99 | 96.4% | 98.2% | 64 |
| 5d | short | 95 / 99 | 94.1% | 97.3% | 64 |
| **overall** | | **95 / 99** | **94.6%** | **97.7%** | 384 |

**Verdict: usable, with a haircut.** The p99 bound delivers 97.7% rather than 99%, and 13% of
individual cells held less than 95% of the time.

**Shorts are consistently worse covered than longs** (91.3% vs 94.8% at one day). Upside spikes are
fatter than downside ones in this sample, so a short needs more room than the symmetric reading
suggests. The JSON keeps long and short separate — use the right one.

### Recommended haircut
**Divide the table's max leverage by 1.5**, which converts a nominal p99 bound into something closer
to a genuine 99%, and absorbs the two costs the liquidation maths ignores (below). For BTC that means
**11x when calm, 5x when hot** rather than 17x and 7.7x.

---

## The leverage maths, stated so it can be checked

```
adverse tolerance  =  1/L  -  mm           (fraction of entry, before liquidation)
max safe L         =  1 / (adverse/100 + mm)
mm                 =  1 / (2 x coin maxLeverage)
```

`mm` is Hyperliquid's documented maintenance fraction — half the initial margin at maximum leverage.
So BTC at 40x max has mm = 1.25%, HYPE at 10x has mm = 5.00%.

**Two things this deliberately excludes, both of which make the answer optimistic:**
- **funding**, which on a multi-day hold in a high-funding regime can be a meaningful drag on margin
- **fees and slippage** on entry and on liquidation

That is the main reason for the 1.5x haircut rather than trusting the raw number.

---

## Method notes
- Adverse excursion is measured from each day's **4h opening price**, taking the worst low (long) or
  worst high (short) across the whole 1/3/5-day window — so it is an intraday path measure, not
  close-to-close. Close-to-close would badly understate liquidation risk.
- Volatility quintiles are cut on **train-only** forecast values per coin, so the buckets are not
  fitted to the test period.
- Quintiles rather than deciles: deciles left under 30 train days per coin-bucket, below the n≥13
  house rule once split by horizon and side.
- The forecast is the pooled HAR model from `VOLATILITY.md`, fitted on train days (18,850 rows,
  smearing 1.7358) and applied forward.
- `ZEC`, `PUMP` and `VVV` were fetched but have too little pre-2025-06 history to bucket on train;
  they are excluded rather than reported on thin data.

## How the terminal should use it
1. Read `safe_leverage.json`, pick the coin, look up the quintile the live forecast falls in.
2. Show `max_lev_long_1d_p99 / 1.5` as the ceiling, and grey out anything above it.
3. Use the matching `p99` adverse move as the "worst realistic case" line on the position calculator,
   alongside the `ADAPTIVE_STOPS.md` recommendation (stop = 2× forecast move, target 0.5R).
4. Flag the short side separately — it needs more room than the long side at the same forecast.
