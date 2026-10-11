# Correction to `SMALLCAP_MOMENTUM.md`: the verdict survives, my reasoning for it does not. There **is** a large effect here — **the opposite sign**, and it clears every gate I set.

_2026-10-11, same day. Triggered by a five-lens adversarial red-team of my own null result, then
verified on independently written code (`verify_breakout_tail.py`, `mae_check.log`). Supersedes
§1, §3, §4 and §5 of `SMALLCAP_MOMENTUM.md`._

---

## 1. What I got wrong, listed before anything else

| # | my claim | what is true | direction of my error |
|---|---|---|---|
| 1 | "The gross numbers back it up… you would have seen winners. **The memory is accurate.**" | Equal-weighted **by day** — the unit my own prereg declared — a breakout basket **lost ~2.9%/day gross.** The +0.95% is 9 mega-days out of 173. | **toward the hypothesis** |
| 2 | "Nothing in the table could have been resolved at the size it actually is." | The panel resolves **6–15% effects at \|z\| 5–7.** The binding constraint was **my specification**, not the data. | toward a false null |
| 3 | "All four signals negative at 72h… `S2` closest at −2.88." | Two bugs manufactured it (§3 below). On correct code **nothing at 72h was near the bar.** The direction later turned out right for entirely different reasons. | toward a false finding |
| 4 | "The best cell loses 14 bps at the cheapest cost assumption." | My `net_bps` subtracted fees from the **excess over the null**, not from the trade. The honest claim is "**no excess over a random small cap**", not "it fails on costs." | made the verdict look better-founded than it was |
| 5 | "**Nothing below deviates from** [the prereg]." | **Two deviations**, §3. | the worst one — it is a claim about my own discipline |

**The headline verdict — small-cap momentum DOES NOT STAND — survives all of this.** Every
correction makes the long case *worse*. But I reached a right answer through reasoning that was
wrong in five identifiable places, and that is not the same as being right.

## 2. 🔴 The error that mattered: I clustered the *variance* by day and the *estimate* by event

My prereg, §7, in my own words: *"The clustering unit is therefore the **signal day**, not the
event."* The code applied that to the bootstrap and then took `flat.mean()` — **a mean over
events.** On days when 430 small caps fire together, those 430 got 430 votes.

| `S3_both`, 24h | pooled by event | **equal-weighted by day** |
|---|---|---|
| gross | **+0.951%** | **−2.68%** |
| vs N1 | +0.086% (z 0.08) | **−3.93% (z −6.53)** |
| vs N2 | −0.053% (z −0.08) | **−2.64% (z −4.86)** |

Robust, not an outlier artifact: median day −2.99%, 10%-trimmed −3.30%, and days with ≥5 events
(−2.40%) look like days with ≤3 (−3.09%). Walk-forward stable: −3.90 / −3.96. Dropping the three
worst days still gives −2.56%. **11 of 16 cells clear Bonferroni on the day estimator — negative.**

**And the control that proves this is not just a weighting artifact:** the *eligible basket* is
pooled **+0.2150%** vs equal-weighted **+0.2126%** — identical, because basket day-counts barely
vary. **The divergence exists only for signal events**, because breakouts are numerous precisely on
the days small caps rose (`corr(day event count, day mean) = +0.18 to +0.37`). Weighting by event
therefore samples the good days more heavily — which is the whole mechanism of my error.

**This is precisely the check the 2026-10-08 standard exists to force** — *the equal-weighted block
mean must sit beside every pooled figure for the number being acted on.* I applied it to
`ENTRY_TIMING.md` the same afternoon and omitted it here.

## 3. The two prereg deviations, since I claimed there were none

1. **An undeclared event filter.** `collect()` contains `if len(pl) < 5: continue`, which drops a
   whole timestamp when fewer than 5 eligible coins are simultaneously non-signal. My prereg §1
   authorised dropping a timestamp only for **fewer than 10 eligible coins** — and there were
   **152**. It deleted **441 of 10,368** `S1_breakout` events, all from **one 5-hour episode
   (2026-08-21 22Z → 08-22 04Z)** where 97–99% of coins fired at once. Their mean 24h return was
   **−8.67%.** The filter is outcome-correlated: pool exhaustion *is* the blow-off top. It roughly
   **doubled** my headline gross.
2. **Wrong bootstrap block.** Prereg §7 fixed `block = max(24h, horizon)`; the code hard-coded one
   calendar day at every horizon. At 72h the correct block raises the SE 17–40%, which alone
   collapses §5.

**And my MDE constant was wrong.** `2.8 × se` is the 80%-power constant for two-sided α = 0.05, but
my gate was Bonferroni 0.05/16 (z = 2.955) **and** required both nulls, which at the measured
N1/N2 correlation of 0.80 needs **4.02 × se**. **Every floor I printed was understated by ~43%.**
*(Also: the design effect should use the Kish effective cluster size — 274, not the 123.7 I
featured, so effective n is ~250, not ~650. More clustering than I claimed, not less.)*

## 4. 🟢 What is actually in this data — verified on code I wrote separately

I did not take the red-team's word for it. `verify_breakout_tail.py` re-derives the claim with no
sampling at all (the benchmark is the **full** same-hour cross-section of non-breakout eligible
coins), equal-weighted by day:

**Dose-response at 72h — the stronger the breakout, the worse the outcome:**

| close above its 20-day high | excess vs peers | z |
|---|---|---|
| 0.5–1% | −0.81% | −1.11 |
| 1–2% | −2.19% | −2.93 |
| 2–4% | −3.01% | −3.72 |
| 4–8% | **−6.04%** | **−5.19** |
| **≥8%** | **−14.85%** | **−6.14** |

**Term structure, perfectly monotone — a bad print cannot grow smoothly for a week:**

| 1h | 4h | 12h | 24h | 72h | 168h |
|---|---|---|---|---|---|
| −1.01% | −2.34% | −3.42% | −4.77% | −8.44% | **−10.95%** |
| z −3.25 | −4.42 | −3.92 | −4.48 | −6.74 | **−7.87** |

**A placebo that can fail, and does not fire:** same number of signals per hour, drawn at random
from that hour's eligible coins — placebo mean **−0.19%** across runs, real **−8.44%**, i.e.
**23.6 placebo-sd away.** The estimator is not negative by construction.

**Not concentrated:** top 1% of events = **9%** of the total, top 5% = **39%**, and **69% of
individual events** go the predicted way. That is the opposite of the `CROSS_SECTIONAL_V2` failure
mode.

**And my own 164-coin crossover grid agrees independently** (`crossover_wide169.json`): all 36
cells negative, 10 clearing Bonferroni, strongest z −9.1. Four separate routes, same direction.

**One honest note on my own verification script:** it printed *"does NOT reproduce — red-team
overreached."* **That printed verdict is wrong** and I am not reporting it. Its gate demanded strict
monotonicity across all six bands and failed on one step (−1.48% → −0.81%) between two bands whose
error bars overlap heavily. Bad gate, not a bad result.

## 5. ⚠️ So can it be traded? The statistics say yes and the **capacity** says barely

Shorting the ≥4% tail, 682 events, 140 coins, 132 days — mean 72h move **−5.80%**, median −6.46%,
**69.4% fall.** Then the part an excess return cannot tell you:

| maximum adverse excursion, before the 72h is up | |
|---|---|
| median | **+11.75%** |
| 90th pct | **+50.42%** |
| 95th pct | +80.04% |
| worst | **+239.70%** |

| leverage | liquidated before 72h ends |
|---|---|
| 1× | 3.5% |
| **2×** | **10.3%** |
| 3× | 17.6% |
| 5× | **31.2%** |

**And the coins are tiny:** median trailing volume **$572k/day**, 10th percentile **$131k/day.**

**That is the binding constraint — not the statistics.** A position you could actually fill in a
$572k/day perp is small enough that a 5.8% edge is small absolute money, and anything above 2×
leverage hands back a tenth of the book to liquidations.

**And funding is not in this estimate at all.** On a perp in a blow-off, funding runs against a
short at roughly **1%/day**, so a 72-hour hold plausibly gives back **~3% of the 5.8%** — over half
the edge, before slippage on a $572k/day book. **That single unmeasured term could account for most
of what is left.** j5 now archives `fundingHistory` for every perp, so this is answerable from
tomorrow; it was not answerable before today, which is exactly why the number is absent rather than
estimated.

**One more constraint on what may be claimed:** the effect is measured **relative to other small
caps at the same hour**. Against the *same coin's* full history a breakout actually looks *better*,
because the coin is in a hot phase overall — and with an uncontaminated own-coin control the excess
is **+0.008%, z 0.01**. So the honest statement is *"it underperforms its peers,"* not *"it falls."*
Both happen to be true here (69.4% fell in absolute terms), but only the first is what the test
establishes.

## 6. Verdict, restated

**For the owner's question — "could we have had good calls on the small-cap movers?" — the answer
is now stronger than "no", and it is the useful direction:**

> **Those coins were not an opportunity missed. The further a small cap sits above its 20-day high,
> the worse it does next — and above 8%, it underperforms its peers by about 15% over three days.**

**The deliverable is an AVOID rule, which needs no capacity and no leverage:** a small cap far above
its 20-day high is not a reason to size up; it is a reason to stand down. That is free to apply
and is what §1 of `SMALLCAP_MOMENTUM.md` should have said.

**The SHORT is a separate, un-preregistered claim found by looking**, so it gets
`PREREG_SMALLCAP_FADE_2026-10-11.md` and a prospective test — not a position.

**Nothing changes on the bot.** No SUPPORT verdict is issued here.

## Limits
- **§4 was found by exploration, not pre-specified.** The red-team accounted for **113 cells**
  (Bonferroni \|z\| > 3.55) and the tail clears that bar by a wide margin, with monotone gradients in
  three independent strength variables rather than one best bin — but it was still found by looking,
  which is exactly why §6 seals a forward test instead of claiming it.
- **Survivorship now runs in my favour and I should say so loudly:** delisted pumpers are missing
  and they went to zero, so the true underperformance is **worse** than measured. A result helped by
  a bias needs more scepticism, not less.
- **Funding and borrow are unmeasured**, and on a pumping small-cap perp they are exactly where a
  short edge goes to die.
- **132 days, one regime.** The market-down conditional (−3.8% to −5.4%) versus flat/up (≈0) says
  this may be substantially a down-market effect, and this window had one.
