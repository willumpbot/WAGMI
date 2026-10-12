# PREREG — does a second chat picking up a coin predict its FUTURE return? **Sealed at n=35, before any outcome was compared.**

_Answering the half of the server's Z2 item that does not require `caller_hash`. Written while the
corrected 2026 set holds **35 re-called coins of 261** — far too thin to test — for the same reason
the shadow prereg was sealed at n=3: at 320 I will have seen the data, and today I cannot have._

---

## 0. What the corpus actually contains, measured first

| | |
|---|---|
| corrected 14d calls | 261 |
| called **more than once** | **35 (13%)** |
| of those, called in **more than one chat** | **35 — all of them** |
| called 3+ times | **0** |

**So "re-called" in this corpus means "picked up by a second chat", never "repeated by the same
chat."** That is a different hypothesis from the caller-skill one the server framed: it is
**cross-chat confirmation**, not individual form. The prereg tests what the data contains, not what
the brief assumed.

**At 2,479 calls the 13% rate implies ~320 re-called coins. The test runs at n ≥ 250 re-called, or
when the fetch completes, whichever is first.**

## 1. 🔴 The trap this design exists to avoid

**A coin gets picked up by a second chat BECAUSE it moved.** So "re-called coins did better" is
close to tautological if the measurement window contains the move that caused the re-call.

**Therefore the outcome is measured from the SECOND call forward, never from the first.** The
question is:

> **Given a coin has just been picked up by a second chat, what happens NEXT?**

That is tradeable and it is not circular. **Measuring from the first call would answer "do coins
that went up go up", which is not a question.**

**And the comparison group is matched the same way:** single-chat calls, outcome measured from their
only call. **Both arms therefore measure "forward return from a call", differing only in whether a
second chat had already spoken.**

## 2. Primary test

| | |
|---|---|
| **treated** | coins called in ≥2 chats; outcome from the **second** call |
| **control** | coins called in exactly 1 chat; outcome from that call |
| **outcome** | the best-performing exit rule at 7d and 14d from `FATTAIL_HORIZONS.md` — stated now as **sell at 1.5×**, 14d — plus peak-multiple reached, both pre-fee |
| **statistic** | difference in means, **equal-weighted over call-days**, printed beside the pooled difference |
| **CI** | day-block bootstrap, 4,000 reps, resampling whole call-days |
| **dead handling** | dead coins = −100%, as a **rate measured on the same cohort**, printed with its denominator |

**The equal-weighted day figure governs on disagreement with pooled.** Non-negotiable; it is the
error that turned an M2 result from +0.09% to −3.93% and that I re-made in `fattail2` nine hours ago.

## 3. Decision rule, fixed now

**SUPPORT** for "cross-chat confirmation predicts forward return" requires ALL of:

1. equal-weighted day-mean difference **> 0** with CI excluding zero at **|z| > 2.24**
   (Bonferroni over the 2 horizons, two-sided 0.05/2);
2. **pooled and equal-weighted agree in sign**;
3. **sign-stable across halves** split at the median call-day;
4. effect **exceeds the MDE** of §4;
5. **survives the §5 placebo.**

**AGAINST**: significantly negative. **UNDERPOWERED**: everything else, explicitly including
positive-but-below-MDE.

## 4. Power

MDE by simulation on the accrued dispersion at the stopping n, **not** a restated CI half-width.

**Pre-commitment:** `fattail2` measured a per-call-day SD large enough that 63 call-days gave the
best rule a CI of roughly ±9 points. **If the MDE at the stopping n exceeds 10 percentage points,
the verdict is UNDERPOWERED regardless of the point estimate.**

**Recorded expectation: I expect UNDERPOWERED or a small negative.** The honest prior is that a
second chat posting a contract is a lagging indicator, and lagging indicators of a mean-reverting
pump predict a *fall*. **Writing that down now so a positive result has to work for it.**

## 5. Placebos, and the one that matters here

1. **Time-shifted placebo.** Re-run with each treated coin's second-call timestamp replaced by a
   random other treated coin's second-call timestamp, 2,000 draws. **Measured size must be ≈5%.**
   This tests whether the effect is about the *re-call event* or merely about *when in the window a
   second look happens.*
2. **Pseudo-treatment placebo.** Label a random 13% of single-chat coins as "treated", preserving
   the call-day distribution. Must be null. **If it is not, the construction is picking up day
   effects rather than re-calls.**
3. **Driftless-GBM no-edge control**, as in `x2_gbm_placebo.py`. **X2's omission of this cost a
   wrong gloss on a +0.19R result**, and the same structural risk is present here: two groups
   measured over different windows can differ on arithmetic alone.

## 6. Declared in advance

- **The second-call lag is a covariate, not a nuisance.** Median delay between first and second call
  will be reported, and the result reported **split at that median**, because a 2-hour pickup and a
  10-day pickup are not the same event.
- **No caller identity is used anywhere.** `caller_hash` is never read by this machine; the treated
  set is defined purely by `chat` and `ca`. If the test ever appears to need caller identity, it
  stops and goes back to the server.
- **Deviations** go in the results document with their effect on the number, per §9 of the X2 prereg
  and for the same reason: I have broken that rule before.

## 7. Out of scope

- **No trading recommendation on SUPPORT** without the owner's yes, and not before costs — `§2` of
  `LAPTOP_REPLY_99` puts round-trip cost above **24%** for a $500 ticket on the median pool, so a
  forward edge would have to be very large to survive execution.
- **No claim about caller skill.** This is cross-chat confirmation; the caller-form question belongs
  to the server and stays there.
