# Cross-sectional ranking — the last unasked structural question, answered

_2026-10-08. Self-proposed (Proposal B in `LAPTOP_PROPOSALS.md`), executed immediately.
20,055 coin-days, 11 coins, 2,145 days, 2020-11-22 → 2026-10-06. Train < 2025-06-01.
Script: `cross_sectional.py`. Data: `cross_sectional.json`._

---

## Headline

**No. Cross-sectional ranking fails exactly the way time-series direction failed — and at a 1-day
hold it is structurally dead on fees alone. Of 18 signal-horizon cells, zero are significantly
positive and sign-stable, while five are significantly NEGATIVE.**

This closes the last genuinely different directional question available in this data. The project's
directional tally is now roughly **98 tests across four datasets with nothing surviving**.

---

## Why this test was worth running

Every prior test asked *"will this coin go up?"* This asked *"will it go up **more than the
others**?"* — a different question, not a reframing:

- a long-short basket is **market-neutral by construction**, so beta and market drift cancel
- that immunises it against the exact failure that fooled the 2025 carry analysis, where an apparent
  +81 bps turned out to be day-selection rather than skill
- and it mattered here because `always-long` was itself **not significant** over this period
  (+0.135%, CI [−0.043, +0.313]), so there was no free beta masking anything

If cross-sectional had worked, it would have been the first real edge. It didn't.

---

## Results

Long the top 3 coins by each signal, short the bottom 3, equal weight, net of 4 × 9 bps (both legs,
in and out). Block bootstrap on day with the block matched to the horizon. The **shuffled-rank null**
keeps the basket structure and destroys the signal.

### 1-day hold
| signal | train | test | test CI95 | shuffled null | verdict |
|---|---|---|---|---|---|
| mom7 | −0.176 | **−0.300** | [−0.520, −0.065] | −0.364 | **significantly negative** |
| mom30 | −0.083 | **−0.250** | [−0.486, −0.021] | −0.324 | **significantly negative** |
| rev3 | −0.513 | **−0.407** | [−0.660, −0.147] | −0.425 | **significantly negative** |
| trend | −0.123 | **−0.268** | [−0.490, −0.041] | −0.360 | **significantly negative** |
| vol22 | −0.454 | **−0.485** | [−0.742, −0.251] | −0.372 | **significantly negative** |
| stretch | −0.139 | −0.150 | [−0.389, +0.076] | −0.321 | no edge |
| rsi | −0.090 | −0.128 | [−0.372, +0.118] | −0.329 | no edge |
| bb | −0.061 | −0.149 | [−0.366, +0.083] | −0.362 | no edge |
| rangepos | −0.169 | −0.199 | [−0.421, +0.041] | −0.373 | no edge |

### 5-day hold
| signal | train | test | test CI95 | shuffled null | verdict |
|---|---|---|---|---|---|
| trend | **+1.300** [+0.381, +2.356] | −0.162 | [−1.034, +0.698] | −0.370 | collapses |
| mom30 | **+1.118** [+0.123, +2.140] | −0.077 | [−0.941, +0.870] | −0.237 | collapses |
| rsi | **+1.090** [+0.169, +2.080] | +0.595 | [−0.259, +1.531] | −0.331 | not significant |
| stretch | **+0.979** [+0.020, +1.990] | +0.437 | [−0.408, +1.423] | −0.224 | not significant |
| bb | +0.964 | +0.424 | [−0.466, +1.353] | −0.348 | not significant |
| mom7 | +0.370 | +0.147 | [−0.614, +1.023] | −0.537 | not significant |
| rangepos | +0.230 | +0.352 | [−0.479, +1.347] | −0.432 | not significant |
| rev3 | −0.728 | −0.558 | [−1.389, +0.209] | −0.308 | not significant |
| vol22 | −0.981 | −0.778 | [−1.789, +0.151] | −0.190 | not significant |

---

## The two things that explain the whole table

**1. At a 1-day hold, fees kill it before signal quality matters.** A long-short basket pays four
legs — long in, long out, short in, short out — so **0.36% per day**. The shuffled null lands at
−0.32 to −0.43%, which *is* the fee drag. No daily cross-sectional spread among 11 large-cap crypto
perps is reliably bigger than 36 bps, so the 1-day version was arithmetically dead before it started.
Five signals coming out significantly negative is simply fees showing through.

**2. At a 5-day hold the fee is amortised, and then the signals vanish.** Four cells look strong on
train (+0.96% to +1.30%, CIs excluding zero) and every one collapses on test. `trend` goes +1.300 →
−0.162; `mom30` goes +1.118 → −0.077. This is the same train-only pattern that killed
`chop_floor`, the high-consensus 5-day cell, and the muted-strategy inversions.

With 18 cells, ~0.9 false positives were expected at p<0.05. Four train-significant cells that all
die out of sample is consistent with exactly that.

---

## Trader rules

1. **Do not trade a daily long-short crypto basket — it pays 0.36% a day in fees**, which is more
   than the spread between the best and worst of 11 majors is reliably worth.
2. **Momentum ranking is the worst of the nine**, not the best: −0.300% per day on test for 7-day
   momentum, significantly negative.
3. **Treat any 5-day cross-sectional backtest as unproven until it is split** — four of nine looked
   significant on train and none survived.

## What this means for the project

Direction should now be treated as **answered in the negative** for anything derivable from price
history. Across four independent datasets we have tested time-series direction, per-slice direction,
voice consensus, strategy inversion, level breaks and now cross-sectional ranking — about 98 tests —
with nothing surviving a train/test split.

The remaining places a directional edge could still hide all require **new data**, not new methods:
the owner's own fills (Proposal A), order flow, or on-chain positioning. Running more variants on the
same candles is no longer informative, and each additional test makes a false positive more likely.

What *does* work is unchanged and worth repeating: **geometry** (−0.5R recoverable, validated four
ways), **volatility forecasting** (22/22 folds), and **consensus as a size gauge** (non-overlapping
CIs on move magnitude).

## Method notes
- Signals are continuous scores ranked across coins each day: 7d and 30d momentum, 3d reversal,
  stretch vs EMA20, EMA20/EMA50 trend, RSI, Bollinger position, 20-day range position, and negative
  22-day volatility (a low-vol preference).
- Days with fewer than 2K+1 = 7 coins available are dropped, leaving 2,145 days.
- Fees: 9 bps per leg per side, so 36 bps per round trip on the paired basket.
- Shuffled-rank null: the signal column is permuted within each day, preserving basket size, coin
  universe and fee structure.
- All forward returns use `shift(-h)`; no lookahead.
