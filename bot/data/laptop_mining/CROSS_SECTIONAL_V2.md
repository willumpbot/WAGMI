# Cross-sectional v2: the estimator is genuinely 1.5× better, 15 of 36 cells "cleared" Bonferroni — and **none of it is tradeable.** The edge lives on 25 days where the backtest's own assumptions break.

_2026-10-11. `cross_sectional_v2.py`. Prompted by the owner: "we aren't data starved… work continuously
at these efforts." Follows `NULLS_AUDIT.md`, which showed v1's MDE was 90–128%/yr so its null meant
little._

---

## 1. What was actually improved, and one thing I wrongly claimed was

**Real gain: the rank-weighted portfolio.** v1 went long the top 3 and short the bottom 3 of 11–17
coins, discarding the middle. Weighting every coin by demeaned rank (normalised to `sum|w| = 2`) is the
same quantity measured better:

| horizon | v1 MDE | v2 MDE | gain |
|---|---|---|---|
| 1d | 0.548% | **0.382%** | **1.44×** |
| 5d | 2.936% | **1.904%** | **1.54×** |
| 10d | 6.212% | 4.109% | 1.51× |
| 20d | 15.622% | 10.547% | 1.48× |

**v1 was discarding about a third of its own precision.** That part stands and should be reused.

**And one claim of mine was false.** I listed "overlapping windows" as an improvement. **v1 already
overlapped** — it took `fwd{hz}` on every day, not every *hz*-th day. I checked instead of assuming,
and it was already there.

## 2. ⚠️ I reintroduced v1's own error mid-run, and caught it

My first pass tested the net return **against zero**. But fees are 4 × 9 bps per round trip, and the
shuffled null lands at **−0.26 to −0.81%**, so testing against zero **scores the fee drag as signal** —
exactly what v1's doc had already identified (*"five signals coming out significantly negative is
simply fees showing through"*). On that broken statistic `rev3` "cleared Bonferroni" at z = −4.68.

**Fixed to a paired statistic:** per day, real minus the mean of 24 rank-shuffled baskets. Fees are
identical in both arms so they cancel, and pairing within day cancels the market move too.

## 3. The result that looked spectacular

With the corrected statistic, **15 of 36 cells clear a 36-test Bonferroni bar** (|z| > 3.09):
`stretch`, `rsi`, `bb`, `rangepos`, `mom7` positive at 1d/5d/10d, and `vol22` negative.

**That is not 15 findings. 15 of 36 clearing a conservative bar is a bug signal**, and the magnitudes
were not survivable: implied annualised Sharpe **3.1–3.3** on daily cross-sectional momentum across 16
liquid coins.

**What I ruled out:**
- **Listing bias** — 16 of 17 coins cover the whole test window; restricting to them moved `stretch` 1d
  from +0.516 to +0.491. Not it.
- **Beta** — a dollar-neutral book is not beta-neutral, and the window rose (+0.148%/day). But regressing
  on the equal-weight market gives **beta +0.03 to +0.11** and alpha surviving at t = 3.2–3.8. Not it.
  *(`vol22` is the exception: beta −0.41, and its result is mostly that short-beta loses in a rising market.)*

## 4. 🔴 What it actually is: a high-dispersion-day exposure that cannot be executed

**The return is not an edge, it is a handful of days.**

| | |
|---|---|
| top 1 day of 494 | **6%** of the total |
| top 5 days | **28%** |
| top 10 days | **45%** |
| **top 25 days (5%)** | **81–84%** |
| days positive | only **55–57%** |

**And those days are not normal days:**

| date | strategy | mean coin move | cross-sectional range |
|---|---|---|---|
| 2025-09-30 | +17.97 | **9.1%** | **63.4%** |
| 2026-06-02 | +14.09 | 6.7% | 45.8% |
| 2025-10-09 | +9.24 | **19.6%** | 34.8% |
| 2026-02-12 | +10.17 | 8.3% | 59.2% |
| *typical day* | — | **3.56%** | — |

**The edge lives on days with 1.5–5.5× normal volatility and cross-sections spreading up to 63%.**
On exactly those days:

1. **Close-to-close fills are fiction.** A day where coins move 20% is a day of gaps and liquidation
   cascades, not a day you get the closing print on 32 legs.
2. **9 bps is fantasy.** Spreads and slippage on a 20%-move day are multiples of that, and the fee
   assumption is the one thing the paired statistic deliberately cancels — so the test is blind to it.
3. **A 2× leveraged 16-coin book meets real depth limits** precisely when everything is moving.

**Plus it is partly two coins.** Leave-one-coin-out on `rsi` 1d: dropping **ZEC costs 32%**, **VVV 19%**.
Two of seventeen coins carry half the effect.

**And the train/test ratio is 1.65–2.97 — the effect is *stronger* out of sample.** Real effects decay
out of sample. One that doubles is telling you the halves differ, not that it generalises.

## 5. Verdict

**NOT TRADEABLE, and not a finding.** The measured spread is real in the data and is an artifact of
measurement assumptions that fail on the only days that matter. **Nothing here should change the bot.**

**What survives and is worth keeping:**
1. **The rank-weighted estimator** — 1.5× more precise for free. Any future cross-sectional work should
   use it, and v1's top-k basket should be retired.
2. **The paired real-minus-null statistic** — fees and market moves cancel by construction, so it cannot
   repeat v1's fee-drag mistake.
3. **A new rule:** *when a backtest's return concentrates in its highest-volatility days, the fill and
   fee assumptions are load-bearing and the result is about those assumptions.* Check concentration
   before celebrating a Sharpe.

## 6. What I would test next, given the data we have
The honest read is that **daily cross-sectional work on 17 coins is exhausted** — the estimator is now
efficient and the signal is an execution artifact. The remaining unexploited data is **intraday**: the
5m archive now has ~19 days × 6 coins and grows daily. A dispersion effect that lives on violent days
is exactly the thing 5m bars can resolve and daily bars cannot, because they can show *when* in the day
the spread opened and whether it was reachable.

**That is a real question I could not have asked a week ago**, and it only becomes answerable as the
archive fills.

## Limits
- The paired null assumes shuffling ranks destroys the signal while preserving structure. It does, but it
  also cancels fees — **deliberately**, which is why §4's point about fees being load-bearing matters.
- MDEs use effective n = days/horizon to account for overlap. If the true dependence runs longer than the
  horizon, all CIs here are still too narrow.
- 36 cells, and the signals are **not independent** — `stretch`, `rsi`, `bb` and `rangepos` all measure
  "price high relative to recent range." Bonferroni over 36 is therefore conservative in count and
  generous in correlation; neither correction changes the verdict, which rests on §4, not on p-values.

---

## 7. ⚠️ CORRECTION, 2026-10-11: §4's fill argument was ASSERTED, and the data runs the other way

§4 rested the verdict partly on two claims I never measured:

> *"9 bps is fantasy. Spreads and slippage on a 20%-move day are multiples of that"* and
> *"A 2× leveraged 16-coin book meets real depth limits precisely when everything is moving."*

The server's SPOF audit shipped an L2 depth archive on 2026-10-11 — the exact data
`INTRADAY_DISP.md` §6 asked for and called *"the only missing piece between 'the spread exists' and
'the spread was reachable'."* It is now in the panel store (`depth`: 61,696 rows, 30 symbols, 101
days, 15-minute cadence) and it says:

| daily \|move\| | n | mean spread | 0.5% depth vs calmest |
|---|---|---|---|
| 0.0–1.7% | 340 | 1.23 bps | 1.00× |
| 1.7–3.5% | 170 | 1.52 bps | 1.48× |
| 3.5–5.8% | 102 | 2.14 bps | 1.96× |
| 5.8–7.8% | 34 | 2.21 bps | 1.65× |
| **7.8–21.3%** | **34** | **2.44 bps** | **1.66×** |

`corr(log daily move, log spread) = +0.237`; `corr(log daily move, log depth) = **+0.190**`.

**Both of my claims fail.** Spreads on the most violent days average **2.44 bps — not multiples of
9 bps, but a quarter of it.** And depth does not collapse; it is **1.66× deeper** on those days than
on the calmest half. **Volatility brings participation.** The intuition that the book empties out
when everything moves is not true for this universe.

**What this does and does not change.** The verdict — **NOT TRADEABLE** — stands, but **not for the
reason §4 gave.** It stands on the parts that were measured: the return living in **25 of 494 days**
(81–84%), **two of seventeen coins carrying half the effect**, and a **train/test ratio of
1.65–2.97** where real effects decay. The fill-and-depth argument was the one leg of §4 that was
intuition dressed as evidence, and it should be struck.

**Limits on this correction, so it is not over-read in turn:** depth is sampled every **15 minutes**,
so a book that was empty for thirty seconds during a liquidation cascade would not show here — this
measures the *day's* conditions, not the *moment's*. The violent-day bin holds only **n=34**, and its
top is a **21.3%** move, whereas §4's worst days had individual coins moving 20%+ with the
cross-section spreading 63%. So the extreme tail remains thinly sampled. The honest statement is
**"not supported, and the point estimate runs the other way"** — not "refuted".
