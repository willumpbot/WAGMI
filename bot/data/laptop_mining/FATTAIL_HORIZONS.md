# 🔴 CORRECTED AGAIN (4th) — **the three horizons were not sharing a base or a data source. On one consistent grid, 24h is NOT clearly negative and the horizon effect on peaks is half what I reported.**

**Caught by the outcomes export for the server**, which produced a row with `peak_24h` 3.72 and
`peak_7d` 2.76 — **impossible**, since a 7-day window contains the 24-hour one. Two defects
underneath it:

1. **Different denominators.** `grids()` sets `base` to the first bar's close *inside* the window.
   The minute grid's first bar is ~1 minute after the call; the hourly grid's is up to an **hour**
   after. So `peak_m` and `peak_h` were normalised to different prices. Measured spread of
   `base_h / base_m`: **p10 0.15, median 0.90, p90 1.58.** **29% of calls had a 7d peak below their
   own 24h peak.**
2. **The minute grid never covered 24h.** `ohlc()` requests `limit=1000`, and 1,000 *minute* bars is
   **16.7 hours**, after which `grids()` forward-fills a constant. The column labelled "24h" was
   really **"~17h, then flat."**

**Fixed** by taking all three horizons from the hourly grid (`peak_h` at indices 24 / 168 / 336), so
they share one base and one source. **Honest cost:** the hourly base is the close of the first hourly
bar at/after the call, so entry is up to an hour late — **a consistent bias across horizons instead
of a varying one between them**, which is what a cross-horizon comparison requires.

**And a standing guard now halts on this:** `assert_monotone()` refuses to report if any longer-window
peak is below a shorter one. It would have caught this on the first run rather than the fourth.

## The corrected numbers, n=261 over 63 call-days, death rate 20.8%, before fees

| horizon | best rule | pooled | **eq-weighted** | **CI95** | verdict |
|---|---|---|---|---|---|
| **24h** | 2.0× | −7.0% | **−4.9%** | [−15.5%, +5.1%] | **negative, spans zero** |
| **7d** | 2.0× | −7.8% | **−6.7%** | [−19.3%, +5.7%] | negative, spans zero |
| **14d** | 1.5× | −8.0% | **−9.1%** | **[−18.5%, −0.8%]** | **LOSES** |

**What this overturns in my own earlier reporting:**

| claim | was | **is** |
|---|---|---|
| 24h best rule | −19.9%, excludes zero | **−4.9%, spans zero** |
| ≥10× within 24h | 0.5% | **2.7%** |
| ≥5× within 24h | 3.7% | **6.9%** |
| max within 24h | 10.99× | **74.47×** |
| ≥10× horizon effect | 0.5% → 5.0% (**tenfold**) | **2.7% → 5.4% (a doubling)** |

**So "the monsters only appear after day one" was overstated.** A 74× move happened *inside* 24
hours; the minute grid could not see it because it stopped at 16.7h and used a different base. **The
horizon effect is real but roughly a doubling, not a tenfold.**

**What still stands:** all three horizons are negative; **14d still excludes zero**; holding is still
worst everywhere; **67% of calls still peak higher after day one** (median ×1.22); and costs still
make every ticket size clearly negative.

**Fourth correction to this result in one day.** Every one came from a consistency check I built
rather than from being caught, and the pattern is now unmistakable: **I have been reporting before
validating the instrument, then validating it afterwards.** The monotonicity guard is the first of
these checks that runs *before* the report rather than after.

---

_Everything below predates this correction. Read its horizon columns as mixed-base and its 24h
column as ~17h._

---

# 🔴 CORRECTED — **the death rate was understated (12.5% → 20.8%) by a double-counting bug in my own loader, and the corrected answer is simpler: buying every call loses at EVERY horizon, before fees.**

**The bug.** The horizon upgrade appends a *new* complete row and leaves the original minute-only row
in the file, because the fetch only appends. My loader counted **rows, not calls**, so an upgraded
call landed in both the "complete" and the "pending" bucket. That inflated the death-rate
denominator — **80 dead of 615 rows (12.5%) instead of 80 dead of 384 calls (20.8%)** — and every
mean below was correspondingly too kind. Fixed by deduping on `ca`, last-wins, which is sound
because the upgrade row is a strict superset of the row it supersedes.

**The corrected answer, n=261 calls over 63 call-days, death rate 20.8%, still before fees:**

| horizon | best rule | pooled | **eq-weighted** | **CI95** | verdict |
|---|---|---|---|---|---|
| **24h** | 1.5× | −23.0% | **−19.9%** | **[−28.6%, −11.7%]** | **LOSES** |
| **7d** | 2.0× | −7.8% | **−6.7%** | [−19.3%, +5.7%] | negative, interval grazes zero |
| **14d** | 1.5× | −8.0% | **−9.1%** | **[−18.5%, −0.8%]** | **LOSES** |

**Holding is still worst everywhere:** −49.9% / −46.4% / −42.5%.

**So the "roughly break-even at 7–14 days" reading is gone.** Two of three horizons now exclude
zero on the governing statistic, the third is negative, **and none of this includes fees** — a 2%
round-trip swap fee takes about two points off each, and price impact only subtracts further.

**What does NOT change:** §2's finding that the runners are real and arrive late. ≥10× still goes
**0.5% → 5.0%**, the max is still **74.47×**, and **67%** of calls still peak higher after day one.
**The mechanism half of the owner's hunch survives every correction; the strategy half is now
clearly negative rather than ambiguous.**

**This is the third correction to this result.** Every one has come from my own checks rather than
from being caught, and every one has moved the picture the same way — toward the simpler, worse
answer. **The direction of that travel is itself information.**

---

_Original write-up follows unedited. **Its headline figures used the 12.5% death rate and are
superseded by the table above.**_

---

# The fat-tail question, settled at three horizons: **the big winners are real and they live past day one — and buying every call still does not clear zero.** Both halves are true.

_2026-10-12. `fattail2.py`, **218 calls over 55 call-days**, 2026 only, inside the free-data window.
Death rate **12.5%** applied as a weight. Horizon stated in every table. **Reported at n=218 against
a threshold of 200 committed in writing beforehand; intermediate states at n=116, 189 and 195 were
observed and are in the commit log.**_

---

## 1. The answer in one table

**Mean return if you bought every call equally.** The **equal-weighted call-day** figure governs;
the pooled figure is shown because it disagrees, and because that disagreement is the trap.

| horizon | best rule | pooled | **equal-weighted** | **CI95 (day-block)** | verdict |
|---|---|---|---|---|---|
| **24 hours** | sell at 1.5× | −14.2% | **−10.3%** | **[−20.4%, −0.8%]** | **LOSES — interval excludes zero** |
| **7 days** | sell at 2.0× | +2.2% | **+2.4%** | **[−13.0%, +18.7%]** | **indistinguishable from zero** |
| **14 days** | sell at 1.5× | +1.4% | **−2.1%** | **[−13.2%, +7.8%]** | **indistinguishable from zero** |

**So: over one day this loses money and we can prove it. Over one to two weeks it is a coin flip
around zero — not profitable, and not clearly unprofitable either.**

**Every rule, for completeness:**

| exit rule | within 24h | within 7d | within 14d |
|---|---|---|---|
| sell all at 1.5× | −14.2% | **+1.2%** | **+1.4%** |
| sell all at 2.0× | −24.6% | **+2.2%** | +0.5% |
| sell all at 3.0× | −33.4% | −0.6% | −0.7% |
| sell all at 5.0× | −36.2% | −9.2% | −6.2% |
| **hold to the end** | **−42.1%** | **−42.5%** | **−36.8%** |

**Holding is the worst rule at every horizon, and that claim is now actually tested** — the earlier
version of it was a 24-hour result wearing a 60-day label.

## 2. 🟢 The owner's hunch is vindicated on mechanism

He has asked three times why this is not profitable given how far some winners run. **The winners are
real, and the reason the earlier study could not see them is that it only looked at the first day.**

| peak multiple reached | within 24h | within 7d | within 14d |
|---|---|---|---|
| median | 1.48× | **1.96×** | 1.96× |
| p90 | 2.92× | 5.89× | 5.99× |
| p99 | 6.68× | 21.41× | **35.62×** |
| **≥2×** | 22.5% | **47.7%** | 47.7% |
| **≥5×** | 3.7% | 12.8% | **13.8%** |
| **≥10×** | **0.5%** | 4.1% | **5.0%** |
| max | 10.99× | **74.47×** | 74.47× |

**≥10× barely exists inside a day (0.5%) and is ten times commoner by two weeks (5.0%).** The
largest call in the set reaches **74×**, and **66% of all calls peak higher after day one** (median
×1.19 further, up to ×60.81).

## 3. Why both halves can be true at once

**Because a target-based rule cannot capture a tail, and holding to capture it eats the median.**

- **Sell at 2×:** a 74× coin pays **+100%** — the same as a coin that merely doubled. **The tail is
  invisible to the rule.**
- **Hold instead:** now the tail pays in full, but you also hold the **12.5% that die** and the
  median call, which is well under water at every horizon. Net **−36.8%** even at 14 days.

**That is the whole answer.** The monsters exist, and no simple rule converts them into a positive
expectation on this sample.

## 4. 🟢 Robustness — the near-zero result is not one lucky call

| best rule | pooled | drop the single best call | top-1 share of all upside |
|---|---|---|---|
| 1.5× @ 24h | −14.2% | −14.4% | 1% |
| 2.0× @ 7d | +2.2% | +1.8% | **1%** |
| 1.5× @ 14d | +1.4% | +1.2% | 1% |

**Removing the best call moves nothing, and no single call carries more than 1% of the total
upside.** So the 7-day near-zero is a property of the distribution, not an outlier artefact.

**And the check that mattered most:** at **n=116** the 7-day figure read **pooled −1.9% / eq-weight
−11.1%** — a 9-point gap that looked like the M2 pooling error. By **n=218** pooled and
equal-weighted agree (**+2.2% vs +2.4%**). **The gap was small-sample noise in the day weights, and
the only reason I know that is that the robustness block was written before the result it judges.**

## 5. What I would tell the owner — three rules, one number each

1. **Your instinct about the big winners is right, and my first answer was wrong because it only
   looked at one day.** ≥10× goes from **0.5%** of calls in 24h to **5.0%** in two weeks.
2. **Buying every call still does not make money.** Over 1–2 weeks the best rule lands at
   **+2.4%** with a range of **−13% to +19%** — a coin flip, before any fees.
3. **Holding for the monsters is the worst thing to do.** **−36.8%**, because you also hold the
   **12.5%** that go to zero and a median call that stays under water.

## Limits
- **No fees, slippage, priority fees or MEV.** Every figure above is therefore **optimistic**, and
  the 7-day result is close enough to zero that costs alone plausibly decide its sign.
- **55 call-days is the real n for inference**, not 218 calls — these arrive in bursts.
- **2026 only**, inside the ~180-day free-data window; 2025 is paywalled (`401`).
- **~13% of the 2,485-call post-floor corpus.** The fetch order is balanced across chat × half-year,
  so the prefix is not cherry-picked, but these numbers will move.
- **"Sell at X" assumes a fill at X**, which the owner's own point about spamming the sell button at
  a target makes defensible rather than fantasy.
- **These are the chats' calls, not the bot's trades.**
