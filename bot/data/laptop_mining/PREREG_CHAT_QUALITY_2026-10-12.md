# PREREG — do the three chats differ in outcome? **Sealed before any chat × outcome statistic was computed.** And one pair can never be compared at all.

_The "which calls" half, following the settled finding that **the exit rule is not the lever** (1.5×,
2× and 3× all return −9 to −11% at every horizon, so whatever is wrong sits in asset selection).
**Needs no caller identity** — only `chat`, `call_ts` and the outcome. Design facts below were read
from call counts and dates only._

---

## 0. 🔴 What the calendar already rules out

| chat | calls so far | **active days** | window |
|---|---|---|---|
| `syndicate` | 206 | 24 | 2026-08-24 → 10-08 |
| **`dtn`** | **204** | **7** | 2026-05-12 → 06-21 |
| `dtn_hitters` | 174 | 74 | 2026-04-25 → 10-08 |

**Shared active days, which is the only basis on which two chats can be compared without
calendar-time confounding:**

| pair | shared days (now) | at full corpus |
|---|---|---|
| `dtn_hitters` × `syndicate` | 14 | **~32** |
| `dtn` × `dtn_hitters` | 1 | **~24** |
| **`dtn` × `syndicate`** | **0** | **0 — permanently** |

**`dtn` ends 2026-06-21 and `syndicate` begins 2026-08-24. They never coexist, so no amount of data
can compare them.** That pair is out of scope by arithmetic, not by choice, and saying so now
prevents a later "dtn beat syndicate" claim that would be entirely a market-regime difference.

**And `dtn` posts 204 calls across 7 days.** Its within-chat clustering is extreme — effectively
~7 independent observations — so any statistic involving `dtn` is governed by a handful of days
regardless of its call count. **This is why the clustering unit is the day and not the call**, and
it is the single most important fact in this document.

## 1. The test

| | |
|---|---|
| **comparison** | `dtn_hitters` vs `syndicate`, **restricted to days both were active** |
| **outcome** | `hit2x_7d`, and `ret_7d` as a continuous secondary |
| **statistic** | difference in outcome rate, **equal-weighted over shared call-days**, printed beside the pooled difference |
| **CI** | day-block bootstrap over shared days, 4,000 reps |
| **dead** | `dead` rows are outcome false, never dropped; the per-chat death rate is reported separately because it may be the whole story |
| **secondary** | `dtn` vs `dtn_hitters` on their shared days, reported with its own day count and **not** combined with the primary |

**The equal-weighted shared-day mean governs.** Pooling across chats with different call volumes on
different days is exactly how a volume difference masquerades as a quality difference.

## 2. Decision rule

**SUPPORT for "the chats differ in call quality"** requires ALL of:

1. equal-weighted shared-day difference with CI excluding zero at **|z| > 2.24** (Bonferroni over
   the 2 outcomes);
2. pooled and equal-weighted agree in sign;
3. the sign is **stable across the first and second half of the shared days**;
4. the effect exceeds the MDE of §3;
5. it **survives the §4 placebo**.

**AGAINST**: significantly reversed. **UNDERPOWERED**: everything else.

## 3. Power — and the floor is stated now because it is probably fatal

`fattail2` measured an equal-weighted CI half-width of roughly **6 points on 83 call-days**. Scaling
to **~32 shared days** gives ~**10 points** per arm, so a *difference* between two arms carries a
floor near **14 percentage points** of hit rate.

**Pre-commitment: if the simulated MDE exceeds 15 percentage points, the verdict is UNDERPOWERED
regardless of the point estimate.** At a base hit rate around 45%, that means only a gap like
38% vs 52% could be detected. **I expect UNDERPOWERED.**

## 4. Placebo

**Chat-label shuffle within shared days**, 2,000 draws — measured size must be ≈5%. **If it is not,
the result is "unmeasurable", not "nothing".** Shuffling within day preserves the day structure, so
it tests chat identity specifically rather than which days each chat happened to be active on.

## 5. Stopping rule

**Runs ONCE, at fetch completion or 2026-10-20, whichever is first.** No run before then, for the
same reason as the caller-form prereg: the shared-day count is still growing and I must not pick the
moment.

## 6. Declared in advance

- **The per-chat death rate is reported whatever the outcome result says.** If one chat's calls die
  more often, that is a quality difference and it may be more interpretable than any return
  difference — but it is **not** the primary test and cannot be substituted for it after the fact.
- **No caller identity is read.** Chat is a channel, not a person.
- **Deviations** go in the results document with their effect on the number.
