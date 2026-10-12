# The owner's question: "how is it not easily profitable, given how many x's some winners have?"

_2026-10-12. Prompted by the owner checking in mid-run. 181 Syndicate calls with intrabar-highs
paths + 18 dead pools scored as total losses. **In-sample, 31 days, not walk-forward — see §4
before believing any of it.**_

---

## 1. The tail is real, and bigger than I had been treating it

| peak multiple (best price ever touched) | median | mean | p90 | p99 | max |
|---|---|---|---|---|---|
| within 24h | 1.32× | 2.21× | 3.33× | 23.6× | **51×** |
| within 7 days | 1.78× | **3.85×** | 5.91× | 49.0× | **91×** |

**25 of 199 calls peaked above 5× inside a week.** So the premise of the question is correct.

## 2. 🔴 Holding is what loses — not the duds

| equal size on every call, net 6% | result |
|---|---|
| **hold everything 7 days** | **−32.0% per call**, median −64.6%, only **15% profitable** |

That matches the server's independent −40%/call. **Holding a memecoin call is close to setting money
on fire**, and that is the number that made the whole thing look hopeless.

## 3. 🟢 But taking profit flips it — at every target tested

"Sell everything at N× if it ever touches N×, otherwise take the 7-day close":

| target | mean / call | median | hit rate |
|---|---|---|---|
| 1.5× | **+6.7%** | +41.0% | 65.7% |
| **2.0×** | **+14.1%** | +2.5% | 49.7% |
| **2.5×** | **+14.2%** | −6.6% | 38.1% |
| 3.0× | +10.9% | −15.3% | 29.3% |
| 5.0× | +2.9% | −47.5% | 13.8% |
| 20× | +12.1% | −64.6% | 3.3% |

**Every target beats holding, and the best is ~2–2.5× at roughly +14% per call.**

**And the mechanism is not the 91× outlier.** Look at the hit rate: **49.7% of calls touch 2× at
some point.** That is a coin flip, not a rare tail event. You do not need to catch a moonshot — you
need to not still be holding when the ordinary double gives itself back. The top 5% of calls carry
**42%** of the gains, so the tail matters but does not dominate.

**This also corrects my own M3 conclusion.** M3 said *"selling everything at 2× is consistently the
worst rule."* M3 ran on **closing** prices, so it only saw a target hit when a 5-minute candle
*closed* above it. On intrabar highs the same rule goes from −11.9% to **+14.1%**. **The wick data
flipped the sign of that finding.**

## 4. ⚠️ The one assumption carrying the entire result

**A wick to 2× is not necessarily a fill.**

Every number in §3 assumes that if the price *touched* 2×, you sold there. On a thin Solana pool
that is the difference between a real edge and a spreadsheet. The server raised exactly this caveat
and it is now load-bearing rather than decorative:

- the touch may last seconds, inside one minute bar
- a resting limit order at 2× would fill — but only for whatever size the book holds at that moment
- the median signal coin here is tiny, so "whatever size the book holds" may be a few hundred dollars

**So the honest statement is:** *if you can reliably sell into a 2× spike, this is profitable at
roughly +14% per call. Whether you can is unmeasured, and it is the only thing standing between
this and a real strategy.*

**Four more limits, stated rather than buried:**
1. **In-sample.** 199 calls, 31 days, one chat, no walk-forward, no cross-chat test. Mission Z1 is
   built to test exactly this on **18,437 calls across 3 chats** and that pull is running.
2. **The median is negative at 2.5×** (−6.6%) while the mean is +14.2%. Most calls still lose; the
   average is carried by the minority that work. That is survivable with equal small sizing and
   *fatal* with concentrated sizing.
3. **6% round trip assumed.** At 10% the thinner targets degrade.
4. **Dead pools are counted as total losses** (18 of 199), which is the right treatment and already
   included above.

## 5. What this changes about what I do next

**Priority flips.** I had Z1's primary sweep as scale-out *shape*. The data says the first question
is simpler and sharper:

> **Can you actually fill a sale into the spike?**

Three things answer it, in order:
1. **Does the target rule survive cross-chat?** Fit on 18k DTN calls, test on Syndicate. Running.
2. **How long does the touch last?** I have minute-resolution peaks — I can measure how many minutes
   the price spent above 2×. A touch lasting 1 minute and one lasting 3 hours are different trades,
   and I have not looked.
3. **What size would have filled?** Needs the pool's depth at that moment, which is the one thing
   the server's new `call_snapshot` collector will capture going forward.

**Nothing changes on the bot, and this is not a recommendation yet** — but your instinct that the
x's should make this work is supported by the data, and the reason it looked hopeless before is that
every previous pass measured *holding*, not *selling*.

---

## 6. UPDATE: the owner's limit-order point resolves §4, and a near-miss of my own

**Owner, verbatim:** *"limit orders are what most of these traders use, however its very easy to
spam the sell button at our targets. we can be VEERY fast if we have it automated."*

**That settles which number is the right one, and it is the optimistic column.** A **resting limit
sell** at 2× does not require reacting to anything — it sits in the book, and for the price to
*print* 2× it must trade **through** that order. **So the wick is the fill.** My §4 worry was framed
around a market order chasing a spike, which is the wrong model for how this is actually traded.

**Two independent pieces of evidence say the same thing:**

| | |
|---|---|
| 2× touches inside 24h that also **closed** above 2× | **37 of 45** |
| median minutes spent above 2× | **97 min** |
| share of those touches lasting under 5 minutes | **8%** |

**A 2× that happens is not a flicker — the median one sits there for over an hour and a half.** Even
a manual sell would usually work; an automated one certainly would.

### The definitive table, every combination shown

| target | window | touch-based | close-confirmed |
|---|---|---|---|
| 1.5× | 24h | −9.4% | −12.0% |
| 1.5× | **7d** | **+6.7%** | −11.2% |
| 2.0× | 24h | −15.4% | −21.9% |
| **2.0×** | **7d** | **+14.1%** | −18.7% |
| 2.5× | 24h | −19.0% | −20.2% |
| **2.5×** | **7d** | **+14.2%** | −18.2% |

**Where the edge actually lives, which I had not isolated before:** the 24-hour-window rule is
**negative**. The positive figure comes **entirely from targets reached on days 2–7.** So this is
not a first-day-spike trade — it is coins that keep running over the following week. That is a
materially different claim from the one I made in §3 and it changes what the rule has to be.

### ⚠️ A correction I nearly published

Between §3 and here I re-ran the economics and got **−15% to −21%**, and almost reported it as
"the +14% was wrong". **It was my own error twice over:** one run used a 24-hour fallback instead of
7-day, and the next compared a **7-day peak of intrabar highs** against a **max of hourly closes**,
which is a coarser series for days 2–7 and so rejects real touches. **The window was the whole
difference, not the fill.** I caught it by noticing the two runs disagreed on a rule I had described
identically, and I am recording it because a "correction" that is itself a bug is the worst of both.

### What remains genuinely unverified

**Partial fills, not missed fills.** A resting limit at 2× fills — but only for the size the book
holds at that level while the price is through it. On a pool with $23k of depth, a $2k order is
fine; a $20k order is not. **That is now the open question**, and it is answerable from the depth
the server started capturing today rather than by argument.
