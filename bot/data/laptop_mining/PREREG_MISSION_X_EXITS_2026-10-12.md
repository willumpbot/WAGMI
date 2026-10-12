# PRE-REGISTRATION — Mission X: does any exit rule actually beat the bot's current exit?

**Sealed 2026-10-12, before any path has been scored against any exit rule.** Mission X, owner
verbatim via the server: *"if we havent done an insane amount of data pulling on exit math then we
need to do that, that can be something the laptop works on."*

## 0. Why this prereg is unusually strict about the grid

The brief's grid is **stop (4) × target (6) × partials (6+) × trailing × breakeven × time (4) ×
funding-aware**, which is **thousands of cells** on a few hundred real entries. **Something will
look excellent by chance, with certainty.** Prior exit work in this project has already refuted
trailing exits, 2x/0.5R/48h, "never close before TP1", stop-tightening, and the breakeven ratchet —
every one on ~300 bot trades. **Going wider on the same data without fixing the multiplicity first
would manufacture a winner.**

So: **16 primary cells, declared below. Everything else is sensitivity and may never be promoted
to a finding.**

## 1. 🔴 The arm that makes this study self-validating

Three entry arms, and **arm B is a placebo that must come out near zero:**

| arm | entries | role |
|---|---|---|
| **A** | every bot entry in `trade_ledger.csv` (actual side, `stop_initial`, tp levels where logged) | **the real test**, baselined against the bot's own realised exit |
| **B** | **entry-agnostic synthetic**: random timestamps, both sides, matched to the bot's coin mix and side ratio | **PLACEBO** |
| **C** | `plans.json` + `ai_plans.json` | descriptive only, n is tiny |

**The prediction for arm B, written before running:** for a random entry on a near-martingale
price, **no stop/target/trailing combination can produce positive expected R before costs.** Arm B
should therefore return **mean R ≈ −(fees + funding) for every one of the 16 rules**, with no rule
separating from the others beyond noise.

**If any rule shows a positive mean R on arm B, the harness is broken** — look-ahead in the path, a
survivorship filter, or a sign error — **and no result from arm A may be reported until it is
found.** This is the test that can fail, and it is the first thing that runs.

## 2. The 16 primary cells, fixed now

Stop and target are expressed in the units the planner already uses: stop = `k × exp_move`, target
in multiples of risk (R).

| | target 2R | target 4R | no target |
|---|---|---|---|
| **stop 1× exp_move** | cell 1 | cell 2 | cell 3 |
| **stop 2×** | cell 4 | cell 5 | cell 6 |
| **stop 3×** | cell 7 | cell 8 | cell 9 |
| **stop 4×** | cell 10 | cell 11 | cell 12 |

Plus four named alternatives, each at **stop 2× exp_move** so they are comparable to cell 4/5/6:

13. **`partial_50_at_1R`** — sell 50% at 1R, remainder runs to 4R or stop
14. **`trail_after_1R`** — once 1R is reached, trail at 1× exp_move from the peak
15. **`breakeven_at_1R`** — once 1R is reached, move the stop to entry
16. **`time_48h`** — exit at 48 hours regardless

**Max hold for every cell is 96 hours**, so no rule can win by holding forever.

## 3. Costs, stated before any result

- **Fees: 18 bps round trip** (2 legs × 9 bps). ⚠️ **The brief says "9 bps round trip"**; I read 9
  bps as per-leg, as everywhere else in this project. **If the brief meant 9 bps total, every net
  figure here is 9 bps pessimistic** — flagged rather than silently chosen.
- **Realised funding** over the actual hold, from `funding_hist` (now 506k+ rows, per-coin current),
  signed so that paying funding reduces the return.
- Partial exits pay fees on each leg.

## 4. Statistic, and the number that governs

- Per trade: **realised R** net of fees and funding.
- Reported as **mean R pooled over trades AND equal-weighted over calendar days**, side by side.
  **The day-weighted figure governs.** `corr(trades per day, day mean R)` printed beside both.
- **Day-block bootstrap.** **MDE printed for every cell before any verdict.**
- Multiplicity: **16 primary cells, Bonferroni two-sided 0.05/16 → |z| > 2.95.**
- **Baseline for arm A is the bot's own realised exit**, so every cell is reported as a *difference*
  from what actually happened, paired per trade.

## 5. Pre-specified breakdowns (not extra tests)

By **side**, by **majors vs small caps** (top-15 trailing volume vs the rest), by **regime** from the
scanner's trend flags, and **walk-forward halves** with sign-stability required. These are reported
for the primary cells only. **A cell that wins overall but flips sign across halves is not a
finding**, per the M3 lesson where 5 of 6 rules changed sign.

## 6. 🔴 Power, stated before any verdict

Arm A has **~295 closed trades over ~59 trading days**, so the clustered n is **~59, not 295**.
Realised R is heavy-tailed. **I expect most primary cells to be underpowered against the
differences that matter**, and prior exit work on this same data found effects of −0.13 to −0.20R.
**At 59 day-blocks a difference of 0.2R will sit near the detection floor**, and the verdict table
has an explicit UNDERPOWERED outcome so a null is not later read as evidence of equivalence.

Arm B carries as many synthetic entries as wanted (target: **20,000**, matched to the coin mix), so
the placebo is well powered **by construction** — which is the point: the arm that must detect a
bug is the one with the most data.

## 7. Verdict rule, fixed now

| outcome | conclusion |
|---|---|
| **arm B shows any rule with positive mean R** | **HARNESS BROKEN.** Nothing is reported from arm A until the cause is found |
| a cell beats the bot's exit at \|z\| > 2.95 on the **day-weighted paired** difference, net of costs, sign-stable across halves | **CANDIDATE** — then red-teamed, then a SUPPORT verdict is considered |
| a cell wins but MDE > the effect | **UNDERPOWERED — no finding** |
| nothing beats the baseline | **the bot's current exit is not improvable on this data** — reported plainly, which the brief says is the likely outcome |

**No bot change on this prereg alone.** Any change needs a red-teamed SUPPORT verdict and the
owner's yes, and the deliverable for the owner is **one plain table of what survives** — including
the case where that table is empty.

## 8. What I am explicitly NOT redoing

Per the brief: the trailing exit sim, 2x/0.5R/48h, "never close before TP1", stop-tightening, the
exit agent's neutrality, July's 68% MFE capture, and the breakeven ratchet are **already refuted or
settled on the bot's own trades.** They are cited, not repeated. **What is new here is arm B** —
judging exit rules on entries with no skill in them — and the 169-coin × 208-day universe behind it.
