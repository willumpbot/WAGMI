# PREREG — the 5m shadow-stop test. **Sealed at n=3, before any arm was read.**

_Analysis plan for `server_exports/stop_shadow.json` (server's `tools/hivemind/stop_shadow.py`,
live since 2026-10-09). Written when the file contains **3 records, one of them still open**, at the
server's explicit request: "yes, seal its prereg now at n=3 — that's the right moment."_

**Why now is the right moment:** this is a slow accumulator (~2 entries/day). At n=120 I will have
seen the data; at n=3 I cannot have. **Every number in §§2–6 below is therefore a commitment, not a
description.**

---

## 1. What the instrument measures, and what it does not

Each live bot entry gets four arms walked on **HL 5m bars** from the fill to the first of **its own
stop** or **the bot's actual tp2**, else the close at a **96h cap**. Ties inside a bar resolve as the
**stop** (pessimistic). Outcome in **R of the bot's original risk** `|entry − sl|`.

| arm | stop |
|---|---|
| **bot** | the bot's actual `sl` |
| **1.0x / 1.5x / 2.0x** | that multiple of `exp_move` at the fill (`volforecast`, daily closes strictly before the fill) |

**It is a stop-vs-target GEOMETRY test, not a P&L forecast.** It ignores the exit agent, partials and
trailing. **That is a feature here:** X2's baseline had to reproduce the bot's realised behaviour,
which entangled it with the agent and forced a declared deviation. **Here every arm — the bot's
included — is geometry-only, so the agent drops out of both sides of every comparison.** The
write-up must say so in its first line, because no arm is an earnings estimate.

## 2. Primary contrast and the governing statistic

**`1.0x − bot`, in R.** Secondary: `1.5x − bot`, `2.0x − bot`.

**Governing figure: the equal-weighted mean over fill-DAY clusters**, printed beside the pooled
per-entry mean. **On disagreement the day mean governs.** Day-block bootstrap, 4,000 reps, for CIs.

**Clustering is by fill day, not by entry**, because the bot opens several positions a day on a
6-symbol universe whose majors co-move. **The clustering standard applies to the number being
acted on, not only to its CI** — the error that turned an M2 result from +0.09% to −3.93%.

## 3. The stopping rule, fixed now so there is no peeking

**The test is run ONCE, at n = 150 resolved entries** (`done == true`), or on **2027-04-12**,
whichever comes first.

**No interim looks at any arm difference.** I may report counts, resolution rates and data-health
checks at any time — **those do not touch the contrast.** If I do look at an arm difference earlier
for any reason, that look is **declared in the results document** and the significance bar is
adjusted for it.

## 4. Decision rule

**SUPPORT for "widen the bot's stop to ≥ 1× exp_move"** requires ALL of:

1. day-clustered mean of `1.0x − bot` **> 0**, CI excluding zero at **|z| > 2.39** (Bonferroni, 3
   arms, two-sided 0.05/3);
2. the **equal-weighted day mean agrees in sign** with the pooled mean;
3. **sign-stable across halves** split at the median fill day;
4. the effect **exceeds the MDE** of §5;
5. **the no-edge control of §6 does not reproduce it.**

**AGAINST**: significantly negative under the same bar. **UNDERPOWERED**: anything else —
**including positive-but-below-MDE, which is not evidence of absence.**

## 5. Power, stated in advance

MDE by **simulation** on the accrued dispersion at n=150, not a restated CI half-width.

**Pre-commitment:** X2's measured floor was **0.810R** on 46 day-clusters. If this test's floor at
n=150 **exceeds 0.25R**, the verdict is **UNDERPOWERED regardless of the point estimate** — the same
clause that decided X2, carried forward deliberately.

**And an honest expectation, recorded now:** ~2 entries/day over ~75 fill-days is **unlikely** to
clear 0.25R. **I expect UNDERPOWERED and am sealing it anyway**, because a pre-stated floor is the
only thing that makes a null informative.

## 6. Placebos — including the one X2 was missing

1. **Arm-label permutation within fill-day cells**, 2,000 draws. Measured size must be ≈5%. **If it
   is not, the result is "unmeasurable", not "nothing".**
2. **🔴 Driftless-GBM no-edge control.** Replace the 5m path with a driftless GBM at each coin's own
   realised vol, keep everything else identical, and read the spread of `1.0x − bot` in worlds with
   no edge by construction. **X2 omitted this and it mattered:** its arm-permutation placebo passed,
   but the GBM control showed a no-edge world beats +0.18R **14% of the time**. A wider stop can
   score better in R on any price process — fewer stop-outs against a fixed denominator — so
   **a result inside the no-edge spread is not evidence.**
3. **One-bar look-ahead probe.** Granting the stop one bar of foresight **must** turn the wider arm
   significantly positive. If it does not, the harness is not measuring what it claims.

## 7. Pre-declared deviations policy

Any departure from §§1–6 goes in the results document **as a deviation with its effect on the
number.** This clause exists because I wrote "nothing below deviates" on 2026-10-11 and then found
two undeclared M2 deviations, and because X2's own guard caught two errors in its sealed prereg.

## 8. Out of scope

- **No bot change on SUPPORT** without the owner's yes.
- **No target re-optimisation.** tp2 is held at the bot's actual value.
- **No claim about the exit agent**, in either direction. §1 removes it from both sides; that is not
  a finding about its value.
- **One addition requested of the server and not yet present:** `tp1` first-touch per arm. If it
  lands, it is **descriptive only** — it does not enter §2 and cannot become the headline.
