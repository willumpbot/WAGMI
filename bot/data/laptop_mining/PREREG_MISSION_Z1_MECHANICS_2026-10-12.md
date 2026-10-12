# PRE-REGISTRATION — Mission Z1: how to trade the call stream

**Sealed 2026-10-12, with 0 of 18,437 paths scored.** The pull is running as this is written; nothing
has been measured against any trading rule.

**Owner's reframe, verbatim:** *"i really really doubt we can tell the winners from the duds.
potentially we can see trends in callers, but there are going to be massive trends in how we trade
it."*

So the question is **not** which calls to take. It is **how to trade all of them.**

## 1. The corpus, and why it changes what is answerable

| chat | calls | window |
|---|---|---|
| `dtn` | 10,282 | 2025-03 → 2026-06 |
| `dtn_hitters` | 7,821 | 2025-03 → 2026-10 |
| `syndicate` | 334 | 2026-08 → 10 |
| **total** | **18,437** | **~580 days** |

**M3 failed on power: 199 calls over 31 days, clustered n ≈ 31.** This is ~**580 day-clusters** and
~32 calls/day. **That is the difference between unanswerable and answerable**, and it is why the
same question can now be asked properly.

## 2. 🔴 Dead pools are DUDS, never dropped

M3's verdict was flipped by 20 missing calls: the best rule went **+6.7% → −8.0%** when they were
scored as total losses instead of excluded. These calls are up to 18 months old and many pools will
be gone.

**Pre-committed: every unfetchable call is scored as a total loss (−100%), and the headline is
reported both ways with the gap shown.** The fetcher records a reason per failure so the count is
auditable rather than inferred. **If the two treatments disagree in sign, the answer is a range and
I will say so.**

## 3. The primary grid — 14 cells, not 288

The brief's full grid is 6 delays × 4 stops × 4 scale-outs × 3 time stops = **288 cells.** That is a
multiplicity trap even at 580 clusters. So the primary set is **three single-dimension sweeps**
around one fixed base, and the cross product is sensitivity only.

**Base case:** enter at the call bar, no stop, hold 72h, sell everything at the close.

**Sweep A — scale-out (4 cells), the primary question:**
| id | rule |
|---|---|
| `A1_all_15x` | sell 100% at 1.5× if touched, else at 72h |
| `A2_half_15_half_3x` | 50% at 1.5×, 50% at 3×, remainder at 72h |
| `A3_moonbag_25` | 75% at 1.5×, keep 25% to 7 days |
| `A4_trail_peak` | trail 40% from the running peak |

**Sweep B — first-hour stop (4 cells):** none, −25%, −35%, −50%.

**Sweep C — entry delay (6 cells):** 0, 1, 3, 5, 15, 30 minutes.

**14 primary cells. Bonferroni two-sided 0.05/14 → |z| > 2.93.**

## 4. 🟢 The test that actually matters: cross-chat transfer

The brief's best idea, and it is stronger than a time split: **fit on the DTN chats (18,103 calls),
test on Syndicate (334). Then reverse it.**

A rule that survives transfer between two different chats, different callers, and partly different
eras is doing something real. **A rule that only works in the chat it was fitted on is a chat
artifact.** This is the headline test; the time-ordered split is reported alongside it.

## 5. The concentration question, which may dominate everything

**Pre-specified:** report the share of total P&L from the **top 5% of calls**, per rule.

**If that share is ~all of it, then "never miss the runner" dominates and every upside-capping rule
loses by construction** — which would make `A1_all_15x` the worst rule and `A3_moonbag_25` /
`A4_trail_peak` the only live candidates. **I am writing that prediction down now**, because if it
comes out that way it must read as a confirmed expectation rather than as a discovery.

## 6. Costs — the slippage model, stated before any result

Memecoin round trips are not 18 bps. Pre-committed, by the pool's liquidity **at call time** where
known and by a conservative default otherwise:

| round-trip cost | applied to |
|---|---|
| **6%** | headline |
| 3% | optimistic bound |
| 10% | pessimistic bound |

**Every verdict is reported at all three**, and a rule that only survives at 3% is reported as not
surviving. Partial exits pay the cost on each leg.

## 7. Statistic and power

- Per call: realised return net of cost, as a percentage.
- **Mean per call pooled AND equal-weighted by calendar day, side by side. The day-weighted figure
  governs.** `corr(calls per day, day mean)` printed beside both.
- **Day-block bootstrap; MDE printed before every verdict.**
- Walk-forward halves with **sign stability required** — in M3, 5 of 6 rules flipped.
- Median per call reported alongside the mean, because this distribution is extremely right-skewed
  and the mean alone will mislead.

## 8. Z2 (caller form) — and the constraint I am not going to quietly step over

The brief asks whether a caller's hot streak persists. **The standing rule in this project is that
the PC grades callers locally and the laptop does not build caller grading.**

**How I will satisfy both:** Z2 is run as a **single aggregate persistence statistic** — the
correlation between a caller's trailing form over their previous N calls (strictly before the
current one) and the current call's outcome, pooled across all 313 hashes. **No per-caller figure is
computed, ranked, stored or reported.** That answers *"is form persistent or mean-reverting?"* — a
property of the stream — without producing a grade for anybody.

**If the owner wants per-caller numbers, that is the PC's job and I will say so rather than do it.**

## 9. Verdict rule

| outcome | conclusion |
|---|---|
| a rule beats the base case at \|z\| > 2.93 day-weighted, net of **6%**, sign-stable across halves, **and transfers across chats** | **CANDIDATE** → red-team → then a SUPPORT verdict is considered |
| wins in-chat but fails transfer | **CHAT ARTIFACT — not a finding** |
| wins but MDE > effect | **UNDERPOWERED** |
| the top-5% share is ~all the P&L and every capping rule loses | **"never miss the runner" dominates** — report as the structural answer, with sizing implications |
| nothing beats holding to 72h | **the call stream is not improvable by mechanics on this data** |

**No bot change on this prereg alone.** This is about how the owner trades a call stream by hand, and
it carries no SUPPORT verdict by itself.
