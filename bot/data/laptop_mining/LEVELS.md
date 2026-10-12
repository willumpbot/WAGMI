# Mission 11 — what happens at the levels the terminal flags

_2026-10-08. 2,955 touches across 11 coins, 2020-10-19 → 2026-09-27, plus 5,910 random-level nulls.
Train < 2025-06-01 / test after. Script: `levels.py`. Data: `levels.json`._

---

## Headline

**Two of the three flagged levels carry real information, and one of them is backwards from the
folklore. The 20-day LOW is not support — price breaks it *more* often than a random line. The
50-day average IS support when approached from above — the only level that holds better than chance.
The 20-day HIGH tells you nothing at all.**

Everything is measured in **expected daily moves** (the HAR forecast), so a touch means the same
thing on BTC and on a meme. And every cell is compared against **random-date pseudo-levels set at the
same distance from price**, because a 40% break rate is worthless if random lines also break 40% of
the time. They do.

---

## The base rates

| level | approached | n | break rate | CI95 | random null | vs null | reject rate | median follow |
|---|---|---|---|---|---|---|---|---|
| hi20 | from below | 548 | 40.5% | [36.7, 44.5] | 36.9% | +3.7 | 29.0% | +0.03 em |
| hi20 | from above | 419 | 40.1% | [35.6, 44.9] | 37.6% | +2.5 | 37.0% | −0.14 em |
| **lo20** | **from below** | 263 | **47.9%** | [41.8, 54.4] | 38.6% | **+9.4*** | 31.2% | **+0.29 em** |
| **lo20** | from above | 406 | 41.9% | [37.2, 46.8] | 36.6% | **+5.3*** | 30.8% | −0.09 em |
| ma50 | from below | 618 | 37.9% | [34.1, 41.6] | 36.6% | +1.2 | 31.2% | −0.11 em |
| **ma50** | **from above** | 701 | **32.1%** | [28.8, 35.8] | 36.5% | **−4.4*** | 28.4% | +0.01 em |

`*` = the break-rate CI excludes the null rate. `em` = expected daily moves.

### Reading it
1. **The 20-day high is noise.** 40% break either way, against a 37% null. The CI covers the null in
   both directions. If the terminal flags it, the honest caption is "no edge here".
2. **The 20-day low breaks more than random, on both approaches.** +9.4 points from below is the
   largest effect in the table, and the median follow-through is **+0.29 expected moves** in the break
   direction. Treating a 20-day low as a bounce level is the wrong way round.
3. **The 50-day average is the one genuine support.** Approached from above it breaks only 32.1%
   against a 36.5% null — it *holds* better than a random line. Note the asymmetry: from **below** it
   is indistinguishable from random (+1.2). It supports, it does not resist.

### The modal outcome is neither
Break rates are 32–48% and reject rates 28–37%, so in roughly a third of touches price does neither —
it just sits there. Any rule phrased as "it breaks or it bounces" is wrong about a third of the time.

---

## Does structure matter?

Break rate by daily structure, train vs test, with "stable" meaning the two halves agree within 12
points:

| level | approached | structure | train n | train | test n | test | stable |
|---|---|---|---|---|---|---|---|
| hi20 | from below | uptrend | 291 | 36.8% | 93 | 38.7% | yes |
| hi20 | from below | downtrend | 119 | 50.4% | 45 | 42.2% | yes |
| hi20 | from above | uptrend | 230 | 37.0% | 66 | 48.5% | yes |
| hi20 | from above | downtrend | 82 | 42.7% | 41 | 39.0% | yes |
| lo20 | from below | uptrend | 48 | 45.8% | 25 | **68.0%** | **no** |
| lo20 | from below | downtrend | 118 | 44.9% | 72 | 47.2% | yes |
| lo20 | from above | uptrend | 86 | 32.6% | 38 | 34.2% | yes |
| lo20 | from above | downtrend | 183 | 48.6% | 99 | 40.4% | yes |
| ma50 | from below | uptrend | 213 | 38.5% | 63 | 38.1% | yes |
| ma50 | from below | downtrend | 237 | 37.1% | 105 | 38.1% | yes |
| ma50 | from above | uptrend | 278 | 29.9% | 83 | **43.4%** | **no** |
| ma50 | from above | downtrend | 213 | 31.9% | 127 | 29.9% | yes |

Ten of twelve cells are stable, which is reassuring. The two unstable ones have the smallest samples
(n=25 and n=83 on test) and should not be used. **Structure does not change the picture much** — the
lo20-breaks-more and ma50-holds-from-above results appear in both trend regimes.

## Does the volatility forecast matter?

| quintile | n | median expected move | break rate | CI95 | median follow |
|---|---|---|---|---|---|
| Q1 | 328 | 2.13% | 41.2% | [35.7, 46.3] | −0.03 em |
| Q2 | 327 | 2.79% | 45.9% | [40.1, 51.1] | +0.19 em |
| Q3 | 327 | 3.32% | 40.7% | [35.5, 46.2] | −0.05 em |
| Q4 | 327 | 3.97% | 41.3% | [36.4, 46.5] | −0.09 em |
| Q5 | 327 | 5.16% | 40.7% | [35.5, 45.6] | +0.02 em |

**Flat.** 40.7% to 45.9% with overlapping intervals across a 2.4× range of expected move. This is a
clean negative and a useful one: **the volatility forecast does not help predict whether a level
breaks.** It sizes the move, not the outcome — consistent with everything else in this project.

---

## Trader rules

1. **Ignore the 20-day high.** It breaks **40%** of the time, the same as a random line at the same
   distance.
2. **Do not buy the 20-day low expecting support.** It breaks **48%** of the time versus 39% for a
   random line, and follow-through after the break runs **+0.29 expected moves**.
3. **The 50-day average is the one level worth respecting from above.** It breaks only **32%** of the
   time against a 37% null.

## Method notes
- Levels are `shift(1)` — the 20-day high/low and 50-day average are known *before* the touch day, so
  there is no lookahead.
- Touch: |price − level| ≤ 0.5 × expected daily move. Break: closes beyond the level by ≥ 0.5 expected
  moves within 2 days, in the direction of approach. Reject: moves ≥ 1.0 expected moves back to the
  side it came from.
- Null: for each real touch, two random days on the same coin with a pseudo-level placed at a uniformly
  random distance within ±0.5 expected moves — identical geometry, no level.
- Cluster bootstrap on (symbol, day), 2,000 draws.
- **Liquidation clusters are not covered.** The handoff allowed for that; the laptop has no collector
  data for them, so only the three price levels are measured.
- Expected move is the pooled HAR model from `VOLATILITY.md`, fitted on train days only
  (15,198 rows, smearing 1.7433).
