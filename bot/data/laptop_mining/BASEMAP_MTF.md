# Mission 6 — multi-timeframe base-rate maps

_2026-10-08. Panel: 8,038 symbol-days, 10 coins, 2024-07-06 → 2026-10-07 (4h history starts
2024-06-27). Train < 2025-06-01 (3,098) / test ≥ 2025-06-01 (4,940).
Scripts: `basemap_mtf.py`, `basemap_mtf_audit.py`. Data: `basemap_mtf.json`, `basemap_mtf_audit.json`._

---

## Headline

**The map is built and ships as `basemap_mtf.json`, but the desk should NOT adopt it. Adding the 4h
view makes the base rates worse, not better — it fragments 8,038 rows across 144 states and the
signal dissolves into noise. The daily-only basemap the server already runs is the right
granularity, and it is the only version that beats a shuffled-label null.**

| key granularity | states | testable¹ | return repeats | null | verdict |
|---|---|---|---|---|---|
| **daily only (4 fields) — what the server runs today** | 22 | 11 | **72.7%** | 44.5% | ✅ **beats null** |
| daily + 4h structure (5 fields) | 42 | 14 | 50.0% | 48.2% | chance |
| daily + full 4h (7 fields) | 144 | 19 | 36.8% | 46.6% | chance |
| structure + driver only (2 fields) | 4 | 4 | 75.0% | 35.0% | suggestive, only 4 states |

¹ states with n ≥ 30 in **both** halves — the only ones whose stability can be judged at all.

Stability falls monotonically as granularity rises: **72.7% → 50.0% → 36.8%**. That is the signature
of sample fragmentation, not of a better model.

---

## Why "6 of 144 stable" was a misleading way to put it

My first pass reported 6 of 144 states stable at 1d. The honest denominator is **19**, not 144 — only
19 states have n ≥ 30 in both halves. Everything else is untestable, not unstable.

And 19 is the right frame for the real test. Against a **shuffled-label null** (state labels permuted
within each symbol, preserving sample shape while destroying meaning):

| | observed | null | 95% null range | verdict |
|---|---|---|---|---|
| return direction repeats | 7/19 = **36.8%** | 46.8% | [31.8, 60.1] | indistinguishable — in fact *below* chance |
| volatility level repeats (±25%) | 9/19 = **47.4%** | 55.1% | [42.1, 68.2] | indistinguishable — also below chance |

Neither returns nor volatility are stable per state at 7-field granularity.

## This does not contradict mission 5

`COOPERATION.md` found volatility genuinely predictable: corr(today's ATR%, next-5-day realised vol)
= **+0.341 full, +0.353 on test**. That is a *continuous* relationship across 18,201 rows.

Chopping the same information into 144 categorical buckets destroys it. Each state gets ~56 rows on
average, split across two halves and ten symbols. The predictability is real; the bucketing is what
fails.

**Practical consequence: forecast volatility as a continuous function (mission 7), not by looking it
up in a state table.**

---

## What was built anyway, and how to read it

`basemap_mtf.json` follows the server's loader shape so it drops straight in if ever wanted:

```
key   = "STRUCT|STRETCH|RANGE|DRIVER|4hSTRUCT|4hSTRETCH|4hDRIVER"   (7 pipe-separated fields)
out   = {"built", "schema", "key_fields", "cutoff", "horizons",
         "latest": {SYM: {...}}, "keys": {key: {"1d"/"3d"/"5d": {"all": stats, SYM: stats}}},
         "stability": {key: {"1d"/"3d"/"5d": {"train": stats, "test": stats, "stable": bool}}}}
stats = {n, n_eff, up_pct, median_pct, p25_pct, p75_pct, vol_median_pct, vol_p75_pct}
```

Additions over the server's `table.json`: three extra key fields, a `stability` block, and
`vol_median_pct` / `vol_p75_pct` on every cell. 144 states, 0.76 MB.

The 4h state is sampled at the **last closed 4h bar at or before the daily close**, so there is no
lookahead into the day being predicted. Daily definitions are copied from `basemap.py` unchanged
(EMA20/50, close vs EMA20, third of the 20-day range, +DI vs −DI).

### The six states that passed the 1d stability filter
Shown for completeness. Given the audit above, treat these as **not established** — six passes out of
nineteen testable is below the shuffled-label null.

| state | n | up% | median% | train med | test med | vol med |
|---|---|---|---|---|---|---|
| DOWN\|BELOW\|MID\|SELLERS\|UP\|ABOVE\|BUYERS | 157 | 40.1 | −0.61 | −1.05 | −0.49 | 2.25 |
| UP\|BELOW\|LOW\|SELLERS\|DOWN\|BELOW\|SELLERS | 381 | 56.7 | +0.57 | +0.70 | +0.55 | 2.19 |
| UP\|ABOVE\|HIGH\|BUYERS\|UP\|BELOW\|BUYERS | 106 | 48.1 | −0.35 | −0.07 | −0.38 | 2.93 |
| DOWN\|BELOW\|MID\|SELLERS\|UP\|BELOW\|SELLERS | 107 | 44.9 | −0.35 | −0.61 | −0.14 | 2.07 |
| DOWN\|BELOW\|LOW\|SELLERS\|DOWN\|ABOVE\|BUYERS | 210 | 53.3 | +0.34 | +0.76 | +0.28 | 1.83 |
| UP\|ABOVE\|MID\|BUYERS\|UP\|BELOW\|SELLERS | 183 | 44.8 | −0.21 | −0.40 | −0.07 | 2.58 |

Largest median is 0.61% and up-rates sit between 40% and 57% — small even if they were real.

### The "4h adds 13 points of up% spread" number is an artifact
A first cut showed the 4h overlay opening a mean 13.0-point spread in up-rate inside a daily state.
That spread is what fragmentation produces: sub-states with 30–60 observations scatter widely around
their parent. The granularity table is the controlled version of the same question, and it says the
4h overlay costs stability rather than adding resolution.

---

## Recommendation for the desk

1. **Keep `basemap.py` exactly as it is.** The daily 4-field map repeats 72.7% of the time against a
   44.5% null — it is the one base-rate structure here that is better than chance.
2. **Do not headline `basemap_mtf.json`.** It is committed for reproducibility and in case a much
   larger 4h history later makes it viable; 8,038 rows is not enough for 144 states.
3. If more resolution is ever wanted, **add fields one at a time and re-run
   `basemap_mtf_audit.py`** — the granularity table is the test that matters. `daily + 4h structure`
   (5 fields, 42 states) is already at chance, so the budget is spent.
4. **Headline volatility continuously instead** (mission 7). It is the quantity that actually
   survives out of sample.

## Method notes
- Stability for returns = both halves have n ≥ 30, medians share sign, up-rates within 15 points.
- Stability for volatility = both halves n ≥ 30 and median vols within 25% of each other, relative.
- Shuffled-label null: 30–40 permutations of the state label within each symbol, re-running the whole
  stability count each time. This keeps state sizes and the symbol mix intact while removing meaning.
- `vol{h}` is the standard deviation of the **next** h daily returns (h > 1), or |next-day return| at h = 1.
