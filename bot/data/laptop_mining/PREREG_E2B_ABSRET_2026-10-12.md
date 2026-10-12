# PREREG E2b — stop-tightening, measured in ABSOLUTE return. **Sealed before any outcome was replayed.**

_Approved by the server after E2 came back NO FINDING: "R of the original risk is mechanically biased
by a stop-distance treatment." Same 86 events, same paired replay, **outcome changed to % of entry,
net of 9 bps + funding** — invariant to stop distance. Owner decision stays parked until this runs._

---

## 1. What E2 got wrong, so this cannot repeat it

E2 measured **TIGHTEN − KEEP in R of the original risk** and returned **+0.4065 R, z +4.69** — which
looked like a strong finding and was arithmetic. Moving a stop from 1.53% to 0.87% of entry makes a
stop-out cost **0.57R instead of 1.00R**, because the denominator stays at the *pre-treatment*
distance. **The driftless-GBM control scored +0.1759 R on the same design**, and the measured value
sat inside its spread.

**Absolute return has no such denominator.** It is the same quantity for both arms.

## 2. 🟢 A prediction that validates the fix, stated before running

**The GBM no-edge control should now come back ≈ 0.** On a driftless walk, moving a stop changes
*when* you exit but not the expected absolute return, so a mechanically-biased metric would show a
non-zero no-edge median and an unbiased one should not.

**If the GBM median is still materially non-zero, the metric is STILL wrong and I will say so rather
than report the arms.** That makes the control a test of the instrument, not just of the result.

## 3. The test

| | |
|---|---|
| **events** | the same **86** applied `tighten_sl`, 34 days, before→after parsed from `details` |
| **arms** | **KEEP** = the pre-tighten stop · **TIGHTEN** = the stop the engine set |
| **replay** | from the tighten moment to its own stop, `position_tp2`, or 96h; 5m bars where available else 1h; stop wins a tie in a bar |
| **outcome** | `side × (exit − entry) / entry × 100` **− 9 bps − realised funding over that arm's own hold** |
| **primary contrast** | **TIGHTEN − KEEP**, equal-weighted over the **34 tighten-days**, printed beside the pooled per-event mean |
| **CI** | day-block bootstrap, 4,000 reps · **bar \|z\| > 1.96** (one contrast) |

**Funding is computed per arm** because the two arms exit at different times; it largely cancels in
the paired difference and is included for completeness rather than because it is expected to matter.

## 4. Decision rule

**SUPPORT for "owner plans keep the owner's stop; the exit engine may only alert"** requires ALL of:

1. TIGHTEN − KEEP **< 0**, CI excluding zero at **|z| > 1.96**;
2. pooled and equal-weighted **agree in sign**;
3. **sign-stable** across halves split at the median tighten-day;
4. effect **exceeds the MDE** of §5;
5. **falls outside the GBM no-edge spread**;
6. **the GBM median is ≈ 0**, per §2 — otherwise the metric is still biased and nothing is reported.

**AGAINST**: tightening significantly helps. **UNDERPOWERED**: anything else.

## 5. Power

MDE by simulation on the paired per-day differences. **Pre-commitment: the prior "don't tighten"
effect is −0.13 to −0.20R; at the median stop distance of 1.53% of entry that is about
−0.20% to −0.31% of entry. If the MDE exceeds 0.31% of entry, the verdict is UNDERPOWERED regardless
of the point estimate.**

## 6. The owner-plan rows — descriptive only, by instruction

`plans.json` `bot_result` (owner's levels) vs `exec_result` (what the bot did): **5 plans, 2 with
both columns.** Reported as a table with the per-plan difference and **no statistic, no verdict** —
n=2 cannot support one, and the server agreed it is descriptive.

## 7. Confound, unchanged from E2

**Neither arm models further LLM intervention.** KEEP is "the position left alone with its original
stop", not "what the bot would have done". Direction of bias unknown.

## 8. Recorded expectation

**I expect TIGHTEN − KEEP to be slightly negative and to NOT clear the bar**, and I expect the GBM
median to land near zero. Reasoning: the prior evidence is consistent against tightening, but 34
clusters with a ~0.2–0.3% target effect is thin, and E2's own MDE was already at the edge.

**I was wrong in E2 in the direction of my own design, not my expectation — so the expectation
recorded here is held loosely and the GBM check governs.**

## 9. Out of scope

- No exit-engine change without the owner's yes, even on SUPPORT.
- Only `tighten_sl`; the LLM's close and partial actions are a separate question.
- Deviations declared in the results document with their effect on the number.
