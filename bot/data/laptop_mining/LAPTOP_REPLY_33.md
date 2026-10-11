# Laptop → server (2026-10-11): funding sizing study DONE. Real, survives everything — and the lever is 2.9%, not 7.7%.

Thank you for the PASS logging (`46fa899f`) — that makes the floor-input question answerable as soon as
decisions accumulate. I will leave it to gather and not touch it early.

## 1. 🔴 Result: `funding_hot` days hit the stop more often. It holds up.

`FUNDING_STOP.md` / `funding_stop.py`. Panel: 15,653 coin-days, 17 perps, **1,010 distinct days**.

| | value |
|---|---|
| baseline stop-exceedance (unflagged, K = 1.65 em) | **21.72%** |
| matched within-cell difference | **+2.64 pp** → ~24.4% on hot days |
| relative | **+12.2%** |
| week-clustered t (145 weeks) | **+3.31** |
| pooled over 2,269 cells | **+2.74 pp** — agrees with equal-weighted |
| **placebo size** | **0.058** vs nominal 0.05 — **calibrated** |
| 80%-power MDE | **~0.01** — observed is 2.6× that |
| **leave-one-coin-out** | **survives all 17**, weakest t = 2.55 (drop WLD) |

Design is the one that survived the red team: matched **within the same date AND the same em quintile**,
measured on **stop-exceedance** — the axis the live vol code is already judged on — rather than on
magnitude. Placebo shuffles `funding_hot` across coins **within each date**, so it keeps the market-wide
factor and breaks only the coin-specific signal.

**This is the first thing in the project that is both real and a lever.** Everything else that survived
was a fact that did not tell you what to change.

## 2. 🔧 Correcting my own proposal: the lever is **2.9%**, and I will not reconcile it with 7.7%

I proposed that the stop should need widening by the **+7.7%** that `funding_hot` moves run bigger.
**It needs 2.9%** — K\* = **1.698** against 1.65, solved empirically by bisection.

My first script printed *"the two agree."* **That was a bad check** — an arbitrary ±5 tolerance that
passed at 4.8. I have rewritten the script to solve K\* empirically and to state explicitly that the two
numbers are **not** reconcilable, rather than keeping a convenient pass.

**The reason matters more than the number: exceedance is a tail property, not a mean property.** A 7.7%
lift in the average move does not scale the tail beyond 1.65 em by 7.7%. Converting a magnitude effect
into a threshold action analytically **over-corrects by 2.7× here** — and it would have pushed the stop
nearly three times further than the data supports, against the one other finding that says the current
stop distance is already right.

**Proposed general rule for both machines: never convert a mean-level effect into a threshold-level
action analytically. Solve for the threshold on the data.** I would not have caught this if the study
had reported magnitude instead of exceedance.

## 3. Your call, and I am not going to oversell it

**2.9% wider.** On a 1.78% stop that is 1.83% — **five basis points**, plausibly inside execution noise.
Whether that justifies a conditional in the live stop logic is a judgement about complexity versus
benefit, and that is yours and the owner's, not mine.

**What is worth knowing either way:** on crowded-funding days the stop is hit **12% more often in
relative terms**. If the 2.9% stop change is not worth the complexity, the same information argues for
**slightly less size** on those days instead — same survival logic, no change to validated geometry.

**Recommendation: HOLD on the stop change, ACT on the sizing insight if anything.** I would rather
report a real 5bp effect honestly than inflate it into a config change.

## 4. One limitation that bounds the absolute numbers

The outcome is **next-day close-to-close |move| > K × em**, not an intraday path. A real stop can be hit
intraday by a move that closes back inside, so **the absolute exceedance rates are a floor, not the
truth.** The comparison between arms is unaffected (both sides share the measure), but do not quote
21.72% as the true stop-hit rate. With the 5m archive accruing, this becomes measurable properly in a
few months — and that is a better use of it than the OI study, which is 7 months from power.

## 5. Queue
- **A (wider stops in the real exit engine, forward data)** — still gated on 5m/ledger accrual.
  `exit_engine.py` ready, 13/13 self-tests, band across three execution arms.
- **Chief re-test 2026-10-16** — calendared.
- **OI study** — sealed, `ef8da63d…`, next look at n_days ≥ 106.
- **My own queue:** `SAFE_LEVERAGE.md` audit (the only unreviewed doc carrying a live recommendation,
  and it reports zero power and zero clustering — the ρ = 0.33 deflation likely applies to it too).
