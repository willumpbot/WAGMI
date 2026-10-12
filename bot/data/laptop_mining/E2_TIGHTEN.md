# Mission E2 — **NO FINDING.** The test said tightening helps by +0.41R at z 4.69. A random walk says +0.18R on the same design. **My outcome metric was wrong for the question, and the placebo is the only reason that is visible.**

_2026-10-12. `e2_tighten.py`, running `PREREG_E2_TIGHTEN_2026-10-12` (sealed `e7101577`). 86 applied
`tighten_sl` events, 34 days, paired replay. Answering the owner's "we seemed to get stopped out
before it could truly show?"_

---

## 1. The result, and why it is not a result

| TIGHTEN − KEEP, in R of the original risk | |
|---|---|
| equal-weighted day mean | **+0.4065 R** |
| CI95 (day-block, 34 days) | **[+0.2389, +0.5739]** |
| z | **+4.69** against a 1.96 bar |
| pooled per-event | +0.2946 R — **signs agree** |
| walk-forward halves | +0.3787 / +0.4342 — **sign-stable** |

**Every acceptance criterion in §4 of the prereg is met except one.** On those five numbers alone
this is a strong, stable, significant finding that **tightening stops helps** — the opposite of the
prior evidence and the opposite of my own recorded expectation.

**And it is mechanical:**

| driftless-GBM no-edge control, 300 worlds | |
|---|---|
| median | **+0.1759 R** |
| 95% spread | **[−0.2153, +0.4455]** |
| **measured +0.4065 R** | **INSIDE the spread** |

**A market with no edge whatsoever produces +0.18R on this design, and up to +0.45R.** So the
measured value is not evidence of anything.

**MDE 0.25R against the pre-committed 0.20R floor → UNDERPOWERED as well.** Two independent reasons
to report nothing.

## 2. 🔴 Why it is mechanical — and this is my design error, not a data problem

**The outcome was R of the ORIGINAL risk, and the treatment IS the risk.**

When a stop sits at 1.53% of entry and is moved to 0.87%, a stop-out stops losing 1.00R and starts
losing **0.57R** — because the denominator is still the original 1.53%. **The tighter arm is
arithmetically incapable of losing as much per stop-out.** It fires more often (73 stop-outs vs 67)
but each one costs less, and on this sample the second effect dominates.

**That is a denominator artefact, and I built it into the sealed prereg myself.** Measuring a
stop-distance treatment in units of the pre-treatment stop distance cannot work.

**The right outcome is absolute return** — price change from the tighten moment, per unit held — which
is invariant to the stop distance. **I have not run it.** Substituting an outcome after seeing the
sealed one fail is exactly the move these documents exist to prevent, so it needs a **new prereg**,
and that is the recommendation.

## 3. What this does and does not say about the owner's trade

**His case stands on its own and is not weakened by this.** Plan `11624f4364`: stop moved
85,600 → 83,776.1 (breakeven) after ~6h, scratched at **+$1.92**; afterwards the high was 84,315 —
**never within 1,300 of his stop** — and price is now ~82,508, **~+0.7R and still alive toward his
81,600 target.** That is a real, documented instance of the engine converting a working thesis into
a scratch.

**What I cannot do is generalise it.** One case is one case, the owner-plan A/B is **n=2**, and the
86-event bot analogue came back uninterpretable for the reason in §2.

## 4. 🔴 And the owner-plan A/B is n=2, which should be said plainly

`plans.json` holds **5 plans; 2 have both `bot_result` and `exec_result`.** The server suggested
those two columns as the A/B, and they are the right design — there is just almost no data in it
yet. **Every additional owner plan executed with both columns populated is worth more to this
question than any amount of further analysis of the bot's own tightening.**

## 5. What I would tell the owner — three rules, one number each

1. **Your read on your own trade was correct.** The engine moved your stop **1,824 points** closer
   and scratched you; price never came near your original stop.
2. **I cannot yet prove it is a general problem.** The test I sealed measured the wrong thing, and
   a coin-flip market scores **+0.18R** on it.
3. **The thing that would settle it is more of your own plans, not more analysis.** There are
   **2** with a usable before/after.

## Limits
- **34 day-clusters**, 86 events, 6 symbols. Paired, which helps, but thin.
- **Neither arm models further LLM intervention** — KEEP is "left alone with the original stop", not
  "what the bot would have done".
- **82 of 86 replays used 1h bars** (5m reaches back only ~17 days), so intrabar stop/target
  ordering is coarse — the same limitation X2 hit at the bot's stop widths.
- **No fees or funding** in either arm; they largely cancel in a paired difference.
