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
