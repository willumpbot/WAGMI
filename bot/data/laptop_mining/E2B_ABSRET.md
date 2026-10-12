# Mission E2b — **NO VERDICT, and after two sealed attempts the approach is the problem, not the metric.** The question needs the owner-plan A/B, which has n=2.

_2026-10-12. `e2b_absret.py`, running `PREREG_E2B_ABSRET_2026-10-12` (sealed `da0cbf4a`). Same 86
tighten events, outcome switched to absolute return (% of entry, net of 9 bps)._

---

## 1. The numbers, and the criterion that stops me reporting them as a finding

| TIGHTEN − KEEP, % of entry | |
|---|---|
| equal-weighted day mean | **+0.762%** |
| CI95 (34 days) | [+0.277%, +1.264%], z **+3.09** |
| pooled | +0.590% — signs agree |
| halves | +0.899% / +0.625% — sign-stable |
| **GBM no-edge median** | **+0.171%** |
| **GBM 95% spread** | **[−0.834%, +0.813%]** |
| **measured value** | **INSIDE the spread** |
| MDE | **0.65% of entry** vs the prereg's 0.31% floor |

**Two independent stops.** The measurement sits inside the no-edge spread, and the MDE is 2× the
floor I committed to. **UNDERPOWERED, no finding.**

## 2. 🔴 And §2's prediction failed, which is the more useful result

The prereg predicted: *"The GBM no-edge control should now come back ≈ 0 … if it is still materially
non-zero, the metric is STILL wrong and I will say so rather than report the arms."*

**It came back +0.171% — about 22% of the measured effect.** So by criterion 6 I am not reporting the
arms as a result, and the metric is not certified.

**I looked for the cause and did not find it in the obvious place.** The GBM paths start at the
*entry* price while a tighten fires mid-position — but that gap is **0.09% at the median** (p10
−1.06%, p90 +1.23%, with 52% of tightens firing underwater), too small to produce +0.171%. **The fee
cancels in a paired difference. The pessimistic tie rule would bias negative, not positive.** So the
asymmetry is somewhere in the barrier geometry I have not isolated.

**I am not going to keep hunting for a third metric.** Two sealed attempts, two no-verdicts, and in
both cases the no-edge control explained a result that looked strong (z 4.69, then z 3.09). **That
is the signature of a design that cannot answer the question, not of a metric that needs one more
tweak.**

## 3. Why barrier-replay cannot settle this on 86 events

**The treatment moves a barrier, and the outcome depends on barrier crossings.** Any metric built
from "where did the path exit" inherits the geometry of the thing being changed. The GBM control is
the right guard, and it keeps absorbing the signal — which is the honest message: **the effect being
looked for (~0.2–0.3% of entry) is smaller than the simulation noise this design generates
(±0.8%).**

**More events would not obviously fix it either.** 86 events on 34 days gives an MDE of 0.65%; the
target is 0.31%, so it needs ~4× the events — roughly 350 tightens, which at the observed rate is
over a year away.

## 4. 🟢 The design that CAN answer it, and what it needs

**`plans.json`'s `bot_result` (the plan graded on the owner's own levels) vs `exec_result` (what the
bot actually did) is the correct experiment.** Same plan, same thesis, two outcomes, no simulation,
no barrier replay, no metric ambiguity.

**It has 5 plans and 2 with both columns populated.** Reported descriptively, per instruction:

| | |
|---|---|
| plans in `plans.json` | **5** |
| with both `bot_result` and `exec_result` | **2** |
| statistic computed | **none** — n=2 cannot support one |

**The documented case remains the strongest single piece of evidence:** plan `11624f4364`, stop moved
85,600 → 83,776.1, scratched at **+$1.92**, subsequent high 84,315 (never within 1,300 of his stop),
price now ~82,508 — **~+0.7R and still alive toward target.**

## 5. What I would tell the owner — three rules, one number each

1. **Two careful attempts could not prove this generally, and I am stopping rather than trying a
   third metric.** Both times a coin-flip market reproduced the result.
2. **Your own trade is still the best evidence there is.** The engine moved your stop **1,824
   points** and scratched a thesis that is now ~+0.7R.
3. **What settles it is more of your own plans, not more analysis.** There are **2** with a usable
   before/after, and the design needs no simulation at all.

## Limits
- 86 events, 34 days, 6 symbols; 82 of 86 replays used 1h bars.
- Neither arm models further LLM intervention — KEEP is "left alone with the original stop".
- The GBM control's own non-zero median is unexplained and is the reason no verdict is issued.
- Labels inside `e2b_absret.py` still read "R" in places; the harness was cloned from E2 and the
  **quantity is absolute return**. Cosmetic, declared rather than silently left.
