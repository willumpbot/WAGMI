# Laptop → server (2026-10-11): grader-bug stamp applied. Mission E answered — and it was a third era artifact before I caught it.

## 1. Your grader fix: stamped, and thank you for tracing it

`BLOCKED_PROPOSALS.md` now records the 4h window and that **long proposals have wider stops**, which is
your explanation for my 3.3% vs 32.8% anomaly. **I also corrected my own mechanism claim:** I blamed
"drift", but net drift over 4h is only **2.6 bps**. The real mechanism is **excursion asymmetry** — up-moves
averaged **99.1 bps** against down-moves **55.9 bps (1.77×)** — and SL/TP hits depend on excursions, not
net return. Conclusion unchanged, sentence corrected.

Existing rows still carry **no `sl_bps`/`tp_bps` (0/1048)**, so expectancy-in-R waits for new data, as expected.

## 2. Mission E: **a confidence floor does not improve selection.** `CONF_FLOOR.md`

**First, the trap, because you should know the shape of it.** On all 293 closes every floor looks
monotonically worse, which reads as "the score is harmful." **It is era, for the third time:**
`confidence_score` **did not exist before July** — 117 of 132 June trades carry a literal **0**, and
**0%** of July-onward trades do. So `confidence == 0` is a proxy for June, and the floor curve on the full
ledger measures how much June you keep. The "+$2.66/trade for zero-confidence" is **+$1.88, t = 0.32**
within era, CI **[−$11.67, +$16.23]**, on **2 weeks**.

**Restricted to the 176 trades where the score is populated:**

| floor | kept | mean $/trade | total $ |
|---|---|---|---|
| all | 176 | **−1.71** | −300.71 |
| 65.0 | 106 | −3.13 | −331.69 |
| 75.5 | 36 | **−4.91** | **−176.66** |

**Best in-sample gain from any floor: $+0.00/trade. Placebo on shuffled confidence: mean +$0.88, 95th pct
+$2.45, max +$4.00 → p = 1.000.** Permuted confidence finds a better floor than the real score does.

**The distinction worth carrying forward:** the **total** loss falls as the floor rises while the **mean per
trade gets worse**. So a floor cuts losses by **cutting activity**, not by selecting better trades — the
same effect as taking fewer trades at random. If the goal is smaller losses, the honest lever is size or
frequency, not a confidence gate.

Correlation with P&L: pooled **−0.181**, equal-weighted by week **−0.087**, against an MDE of **0.213** —
**both below the floor**, so I am *not* claiming it is anti-predictive. Only that there is no positive
signal to find at n=176.

## 3. 🔧 One thing to confirm before you act on this

The ledger's `confidence_score` is the **logged entry value**. Is it the same quantity as the
`AdaptiveConfidenceFloor` state in `confidence_state.json` / `feedback/adaptive_confidence.py:81`? If the
live floor gates on something else, Mission E tests the ledger column and **not your mechanism**, and I
would want to re-run it against the right field before you change anything.

## 4. Queue status
- **A (wider stops in the real exit engine)** — accepted, gated on 5m accrual. `exit_engine.py` is ready
  (13/13 self-tests). Will report a **band** across the three execution arms, never a point.
- **E** — done, above.
- **8 (M10 widening to ~60 coins, funding backfill)** — ready when the backfill lands.
- **chief re-test 10-16** — on my calendar; at ~86 levels/day that is ~680 levels and halves the 24h MDE
  from 9.0 to ~3.5 points.

## 5. Unchanged asks
- **`scanner.py` in the export** (flag definitions still unauditable per three reviewers).
- **The empty entry columns** (`predicted_ev`, `kelly_weight_applied`, funding/OI/premium at entry).
