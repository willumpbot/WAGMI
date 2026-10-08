# Proposal C — exits: the simple target already wins, and early time stops hurt

_2026-10-08. 15,663 signals, stop held fixed at ×8, train 2026-02-11→04-15 / test 04-16→06-05.
Script: `exits.py`. Data: `exits.json`._

---

## Headline

**No exit policy beats a flat 0.5R target. Trailing stops, breakeven stops and scale-outs all come
back as no difference. But three policies are significantly WORSE, and they are all early time
stops — which matters, because the bot's `TIME_STOP_HOURS` is 2.**

Cutting a trade at 4 hours costs **0.116R** against letting it run to 48 hours with the stop in place.

---

## Results

Stop width fixed at the geometry plateau (×8) so only the exit varies. Every comparison is paired on
identical signals against the `target_0.5R` baseline.

| policy | train R | test R | vs baseline on test | verdict |
|---|---|---|---|---|
| **target_0.5R** | −0.0653 | **+0.0688** | *(baseline)* | **best** |
| trail_after_1.0R | −0.0806 | +0.0675 | −0.0012 [−0.035, +0.039] | no difference |
| target_1.0R | −0.0782 | +0.0654 | −0.0033 [−0.028, +0.022] | no difference |
| scaleout_half_0.5R | −0.0740 | +0.0650 | −0.0038 [−0.019, +0.014] | no difference |
| target_1.5R | −0.0823 | +0.0644 | −0.0044 [−0.039, +0.030] | no difference |
| trail_after_0.5R | −0.0818 | +0.0641 | −0.0046 [−0.037, +0.028] | no difference |
| target_2.0R | −0.0830 | +0.0623 | −0.0064 [−0.044, +0.033] | no difference |
| trail_after_0.25R | −0.0831 | +0.0598 | −0.0090 [−0.038, +0.023] | no difference |
| breakeven_after_1.0R | −0.0828 | +0.0595 | −0.0093 [−0.058, +0.043] | no difference |
| breakeven_after_0.5R | −0.0847 | +0.0586 | −0.0101 [−0.051, +0.031] | no difference |
| time_48h | −0.0818 | +0.0542 | −0.0146 [−0.066, +0.038] | no difference |
| **time_24h** | −0.0747 | −0.0126 | **−0.0813** [−0.150, −0.007] | **worse** |
| **time_12h** | −0.0298 | −0.0251 | **−0.0939** [−0.164, −0.021] | **worse** |
| **time_4h** | −0.0148 | −0.0470 | **−0.1158** [−0.190, −0.044] | **worse** |

13 policies compared, ~0.7 false positives expected at p<0.05. **The only significant results are
the three negatives**, which is the opposite of what a mining exercise usually produces and is a good
sign that the sweep is honest.

---

## What this means

### 1. Exit cleverness adds nothing
Trailing after +0.25R / +0.5R / +1.0R, moving to breakeven after +0.5R / +1.0R, and taking half off
at 0.5R and trailing the rest — **all within noise of simply taking 0.5R and leaving.** Every point
estimate is slightly *negative*, which is what you would expect from adding a mechanism that can only
cut winners short or widen the loss band.

Combined with `GEOMETRY.md`'s finding that near targets beat far ones at every stop width, the picture
is consistent: **on a signal stream with no directional edge, the best exit is the earliest one that
clears costs.** There is no trend to ride, so there is nothing for a trailing stop to capture.

### 2. Early time stops are the one real mistake
The three significant results are all time stops, and they get monotonically worse the earlier they
fire: −0.0813R at 24h, −0.0939R at 12h, **−0.1158R at 4h**. A 48h time stop is indistinguishable from
the baseline, which makes sense because the simulation horizon is 48h.

**This is directly relevant to the live bot: `TIME_STOP_HOURS` is set to 2.** The archive shows this
value has been argued over repeatedly — raised to 48 by the July swarm's recommendation, cut 2h→1h on
2026-05-07 to unblock signal flow, and left at 2 on the desktop. This sweep says the direction of the
July recommendation was right even though its reasoning (confidence floors) was not: **short time
stops destroy value, and the cost is roughly 0.1R per trade.**

Why? A time stop fires regardless of where price is. With a wide stop and a near target, most trades
resolve on their own within 48h; cutting at 4h closes a large fraction of them mid-path at whatever
the mark happens to be, which is a coin flip minus fees.

### 3. The train half is negative everywhere
Every policy is negative on train (−0.015 to −0.085) and the good ones are positive on test
(+0.054 to +0.069). That is the same regime difference flagged in `ADAPTIVE_STOPS.md` — the two halves
of this corpus differ — and it is why only the **paired** comparison is quoted. The absolute level is
not the claim; the difference between policies on identical signals is.

---

## Trader rules

1. **Take profit at 0.5R and stop managing it.** Trailing, breakeven and scale-out are all within
   noise of it, and every one is slightly negative.
2. **Do not cut a trade before 48 hours.** A 4-hour time stop costs **0.116R** per trade versus
   letting the stop do its job.
3. **Raise the bot's `TIME_STOP_HOURS` from 2 toward 48** — this is the one config change this sweep
   supports, worth about **0.1R per trade**.

## Limits
- Stop width is fixed at ×8. A different stop could in principle favour a different exit; the
  monotone geometry surface makes that unlikely but it is untested.
- 48h horizon means anything beyond 48h is unmeasurable here, so "hold longer than 48h" is not
  evaluated — only "do not cut before it".
- Trailing is implemented in R units off the running peak with a 1R trail distance. A tighter or
  looser trail was not swept.
- Single train/test split, as in the rest of the corpus work. The three negative findings are large
  enough relative to their intervals that a walk-forward is unlikely to overturn them, but it has not
  been run.
