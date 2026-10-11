# Intraday: weak cross-sectional **reversal**, 0.4–5.2 bps, against a 36 bps fee wall. The best-powered test in this project, and it answers v2's question.

_2026-10-11. `intraday_disp.py`. 32,742 bars, 6 coins, 456 hourly blocks, 2026-09-22 → 10-11.
First use of the 5m archive the server started on 10-09 after I found Hyperliquid deletes 5m after
~17 days. Follows `CROSS_SECTIONAL_V2.md`._

---

## 1. 🟢 Power first — and for once it is good

**80%-power MDE: 3.7 bps.** That is the smallest detectable spread in anything I have run here. Earlier
tests in this project had MDEs of 90–128% *annualised*; this one resolves fractions of a basis point.

**Why:** 5m return autocorrelation is **−0.025 at lag 1 and dead by lag 2–3**, so hourly blocks (12
bars) sit comfortably beyond the dependence — giving **456 clusters** where the 20 calendar days would
have given 20. The clustering unit was chosen from the data, not by feel.

## 2. The result: every cell negative. Short-horizon **reversal**, not momentum.

All 16 cells. Positive would mean the recent winner keeps winning:

| lookback → horizon | spread | z | |
|---|---|---|---|
| 5min → 5min | **−0.8 bps** | −2.20 | weak |
| 15min → 60min | **−3.7 bps** | −2.47 | weak |
| 30min → 60min | **−5.2 bps** | **−2.67** | weak (largest) |
| 60min → 30min | −3.4 bps | −2.47 | weak |
| *(11 of 16 cells at \|z\| > 1.96)* | | | |

**None clears Bonferroni (|z| > 2.88).** But the sign is negative in **16 of 16**, which is itself
informative: a coin flip gives all-16-one-way about 1 time in 32,000.

**So: the recent intraday winner gives a little back.** Consistently, weakly, everywhere.

## 3. ⚠️ And it is 7–90× too small to trade

Fees are **4 × 9 bps = 36 bps per round trip.** The largest effect is **5.2 bps over an hour.**

**I stated this before running** rather than discovering it afterwards, because it determines what the
test is for: it can detect structure it could never trade. That is a legitimate thing to do — the
answer feeds v2 — but it is not a strategy and must never be read as one.

## 4. 🔴 Unlike v2, this is NOT a few-events artifact — and that is the interesting part

v2's daily "momentum" lived in 25 of 494 days with 81% of the return. Applying the same check here:

| cell | top 1% of bars | bars positive |
|---|---|---|
| 5min → 5min | −140% of total | **47%** |
| 30min → 30min | −116% | **47%** |
| 60min → 60min | −59% | **48%** |

**A negative "top 1% share" with 47% of bars positive means the opposite of concentration** — the total
is small relative to individual bar swings, and the tilt is spread across tens of thousands of
observations. **This is a broad, weak, real tilt.** v2's was a narrow, large, fragile one.

**That contrast is the finding.** Two tests, same estimator, same paired null, opposite character:

| | daily (v2) | intraday (this) |
|---|---|---|
| direction | momentum | **reversal** |
| where the return lives | **25 of 494 days** | spread across 32,742 bars |
| why untradeable | **fills** on violent days | **fees**, by 7–90× |
| power | MDE 90–128%/yr | **MDE 3.7 bps** |

Short-horizon reversal plus medium-horizon momentum is the textbook picture, and it is mildly
reassuring that six coins over 20 days reproduce it.

## 5. What this answers for v2 — and what it does not

**v2's open question was whether a close-based daily signal is reachable, or whether the spread opens in
one unreachable jump.** Partial answer:

**A 5-minute execution delay costs under 1 bp** (the 5min→5min cell is −0.8 bps). So **delay is not the
problem.** If you compute a signal at the close and enter five minutes later, adverse selection costs
you almost nothing.

**Which means v2's fill problem is not about timing — it is about gaps and depth.** On a day when coins
move 20%, the cost is the book being thin and prices jumping, not the five minutes you took to react.

**And I cannot measure that with what we have.** 5m OHLC shows where price went, not how much size was
available at each level.

## 6. 🔧 One data ask, with the justification attached

**The terminal already polls the order book every 2 seconds and throws it away.**

Archiving even a thin slice — top-of-book spread and depth within 0.5% at, say, 1-minute intervals for
the 6 coins — would make v2's question answerable for the first time. It is the only missing piece
between "the spread exists" and "the spread was reachable", and **it has the same expiry problem as
5m candles: if we do not store it, it is gone.** That argument has already been right once.

Rough cost: 6 coins × 1,440 minutes × a few fields ≈ **under 2 MB/day**.

## 7. Verdict
**No tradeable finding. One real structural fact** (weak intraday reversal, 16/16 negative, well
powered), **one useful answer for v2** (delay is not the problem), **and one data ask** that would close
the loop v2 opened.

## Limits
- **20 days, 6 coins.** The hourly blocking gives honest intervals, but 20 days cannot speak to regime
  dependence — this could look different in a quiet market.
- **The paired null cancels fees by construction**, which is why §3 states the hurdle separately. The
  test is blind to the thing that makes the result untradeable; that is deliberate and stated.
- **5 of 6 coins minimum per timestamp.** With 6 coins the rank-weighted spread is coarse — ranks run
  0–5, so the weights are blunt compared with the 17-coin daily panel.
- **Bonferroni over 16 is conservative given the cells overlap heavily** (a 60-minute lookback contains
  the 5-minute one). Nothing clears either way, so the correction does not change the verdict.
