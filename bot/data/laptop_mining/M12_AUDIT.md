# Audit of Mission 12 (`MEMECARD.md`) — **this one holds up.** One wording error worth fixing; the reasoning is the best in the folder.

_2026-10-11. First review this doc has ever had. Audited the same way as M9, M10 and M11, which all
had real problems. **This one does not.**_

---

## 🟢 Verdict: no finding to retract, no number to change

I went in expecting the same failure as the others — a confident claim resting on a sample too small or
a cluster that does not bind. **Instead this document already contains the critique I would have
written, and acts on it against its own measurement.**

Saying so matters. If every audit found a fatal flaw, the audits would be a mannerism rather than a check.

## What it does right, specifically

**1. It flags survivorship bias itself, and sizes it honestly.**

> *"Survivorship bias is one-sided and large. Tokens that rugged hard enough to be delisted cannot be
> sampled at all, and those are precisely the most volatile. So the true ratio is higher than 0.917."*

The calibration sample is `min_days: 60` across 23 pools — **survivors by construction.** That was my
headline finding before I read far enough, and the doc had already got there.

**2. It refuses to ship its own measured correction, for the right reason.**

It measured 0.944× and set `MEME_VOL_MULTIPLIER = 1.0`, because *"over-warning costs a missed trade;
under-warning costs the position."* **That is asymmetric-loss reasoning applied correctly** — declining
a measured adjustment because the error directions are not equally costly. Nothing else in this folder
does that.

**3. It states its own sample shortfall.** 23 pools against the ~100 the mission asked for, with the
reason (only 23 of ~400 sampled had 60+ days).

**4. It reports the inconvenient statistic.** Correlation is only **0.232**, and it draws the correct
conclusion: *"use it for sizing, not for picking between tokens."* A weaker doc would have led with the
calibration ratio and buried the correlation.

**5. The dead-pool trap is a real catch.** BONK with $1.7M liquidity and **$185** of 24h volume,
reading as 0.25% daily vol because the price was stale. That is the exact failure a naive card would
ship, and it drove the geometric liquidity-and-turnover score.

## 🔧 The one thing to fix: a factor of 2 in the explanation

The doc says a trade of size `S` *"moves price by roughly `2S/L`"*. **The shipped cap is right; that
sentence is not.** Derived for a constant-product pool with `L = 2y` and verified numerically:

| trade into a $1M pool | average slippage paid | pool price actually moves |
|---|---|---|
| $1,000 | **0.200%** (= 2S/L) | **0.400%** (= 4S/L) |
| $10,000 | **2.000%** (= 2S/L) | **4.040%** (≈ 4S/L) |

- **`cap = L/100` is correct** for the stated purpose: 2% average slippage on your own fill.
- **But the pool's price moves ~`4S/L`, twice the quoted figure.** The sentence conflates *average fill
  price versus spot* with *price impact on the pool*.

**Why it matters a little:** anyone sizing to an acceptable **price-impact** budget rather than a
**fill-slippage** budget would be off by 2×. The shipped number answers the right question — only the
explanation is loose. **One-sentence fix, no code change.**

## Not raised as criticism, but worth recording

- **No CI on the 0.944× ratio**, and 3,586 predictions across 23 pools are clustered both within pool
  and across pools on the same day — so the effective n is far below 3,586. **This does not change the
  conclusion**, because the doc ships 1.0 regardless and documents why. If anyone ever revisits the
  multiplier with a bigger sample, that is when a clustered interval becomes necessary.
- **Decile 1 at 0.41×** is excluded as stale pools. That is a judgement call, stated openly, and the
  reasoning holds — a near-zero-movement pool is not a trading case.

## For the owner, in one line

**The card tells you how volatile a coin is *given it survives*. It cannot tell you the chance it goes
to zero — and on memecoins that is what actually takes the money.** The doc is honest about this; it is
worth repeating anywhere the card's output is shown, because it is the limit most likely to be forgotten
in the moment someone sends a ticker.
