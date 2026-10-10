# Mission 5 — log about 115 plans before your own numbers mean anything.

_2026-10-10. Dispersion from the cached signal panel (15,663 sims, 14 ISO weeks); geometry anchored on
`server_exports/plans.json`. Script inline; panel `trailing_exit_panel.csv.gz`.
The server flagged this as "the owner's most important number right now"._

---

## 🔴 The one sentence

> **Log about 115 plans before judging yourself. At a few trades a week that's roughly 9 months —
> and even then you can only see an edge of +0.2R per plan or bigger. Below 51 plans, a winning
> streak is indistinguishable from luck.**

You have **one** plan, and it expired without filling.

---

## Where the number comes from

Per-trade R dispersion, measured across six exit policies on the signal panel:

| exit policy | mean R | **sd R** |
|---|---|---|
| stop ×1, fixed 1R target | −0.2808 | 0.9706 |
| stop ×2, fixed 1R target | −0.1990 | 0.8099 |
| stop ×1, tight trail | −0.1229 | 0.8481 |
| **stop ×2, tight trail** ← closest to your real geometry | −0.1126 | **0.6430** |
| stop ×1, mark to close | −0.5012 | 1.1892 |
| stop ×2, mark to close | −0.3014 | 0.8270 |

Your one plan has a stop at **1.65 expected moves** with a 0.50R target — closest to the ×2 +
tight-trail row, so **sd = 0.643R per plan.** Tighter stops or looser exits push the sd up to 1.19R,
which roughly **triples** every N below.

`N = (1.96 + 0.84)² × sd² / δ²`, 80% power, two-sided 5%:

| plans/week | design effect | **+0.10R** | **+0.20R** | **+0.30R** | **+0.50R** |
|---|---|---|---|---|---|
| 1 | 1.00 | 325 | **82** | 37 | 13 |
| 2 | 1.20 | 391 | 98 | 44 | 16 |
| **3** | **1.41** | 457 | **115** | **51** | 19 |
| 5 | 1.82 | 590 | 148 | 66 | 24 |
| 10 | 2.84 | 922 | 231 | 103 | 37 |

At 3 plans a week: **115 plans ≈ 38 weeks ≈ 8.9 months** to judge a +0.2R edge; **51 plans ≈ 17
weeks ≈ 3.9 months** for +0.3R.

## The correction I nearly shipped

My first pass applied the signal panel's week-clustering inflation directly — **15.17×**, which
multiplies N by **230×** and would have said *18,861 plans* for a +0.2R edge. That is wrong, and
wrong in a way that would have been quietly discouraging.

The signal panel averages **1,119 signals per week**, all moving together with the market. You plan a
handful. The penalty is `1 + (m−1)ρ` with **ρ = 0.205** measured from the panel, so at 1–3 plans a
week the design effect is **1.00–1.41**, not 230. Clustering only bites if you place many plans in
the same week on correlated coins.

Same class of error as the five retractions: a number carried from one context into another where its
assumptions don't hold.

---

## Trader rules — one number each

1. **115 plans.** That's the threshold where a +0.2R edge becomes visible. Until then your results
   are a sample, not a verdict.
2. **51 plans is the earliest anything is readable** — and only if your edge is a large +0.3R.
   Below that, don't update on a streak in either direction.
3. **Don't cluster your plans.** Five plans in one week is worth less than five across five weeks:
   the design effect goes 1.00 → 1.82, costing you ~80% more plans for the same confidence.

## What makes this number smaller
- **A tighter dispersion helps more than more trades.** sd 0.643R → 115 plans; sd 1.19R → 394. The
  ×2-stop-plus-tight-trail combination has the lowest sd of the six policies tested, which is a
  second reason to prefer it beyond its mean.
- **Grading your plans three ways** (as written / bot's levels / bot-managed, which the server already
  does) gives three correlated readings per plan, not three independent ones — it sharpens *why* a
  plan worked, not *whether* you have an edge.

## Limits
- **Dispersion is borrowed from the bot's signals, not your plans.** With n=1 there's no alternative,
  and I'm flagging it rather than hiding it. Your plans are discretionary, on coins you choose, at
  times you choose — the true sd could be meaningfully different in either direction. Re-anchor at
  n ≈ 20.
- Assumes you keep the geometry roughly constant. Changing stop width mid-sample resets the count,
  because sd changes.
- 80% power, two-sided 5%. A one-sided test (you only care whether you're *good*) cuts N by ~21%:
  **91 plans instead of 115** for +0.2R.
- `N` detects a *mean* edge. It says nothing about ruin risk at 7× leverage, which is a separate and
  more urgent question.
