> # 🔧 Server answered: the two confidence numbers are DIFFERENT. This tested the ledger column, not the floor's input.
>
> Ledger `confidence_score` = `pos.confidence` (`multi_strategy_main.py:4274`) — the position's **final**
> confidence at entry, after the LLM pipeline. **The floor gates something else:** `adjusted_conf`
> (`feedback/loop.py:140-190`) = quality-adjusted *signal* confidence + tuner calibration offset, compared
> against `effective_floor` = the adaptive floor blended with the tuner floor by trust, raised to
> `live_edge.get_breakeven_confidence_floor()` plus symbol difficulty.
>
> **So the honest scope of this document is: "does the final position confidence rank trades?" Answer: no.**
> It is **not** a test of the floor mechanism, and the title should be read that way.
>
> **But one link makes it bear on the mechanism anyway.** `get_breakeven_confidence_floor()` **reads the
> ledger confidence** — the very column shown here not to rank trades. So the breakeven component of the
> live floor is derived from a quantity with no measurable relationship to per-trade P&L (pooled −0.181,
> equal-weighted −0.087, both under the n=176 MDE of 0.213). That does not make the floor harmful; it means
> **one of its inputs carries no demonstrated signal.**
>
> The server's summary — *"a floor cuts activity, not selects quality"* — holds either way, and they are
> presenting it that way with **no bot change proposed.** I have asked for the `SIGNAL_FILTERED` / gate-line
> slice of `trade_events.jsonl` so the floor's **actual** input can be tested properly.

# Mission E: the confidence floor does not select better trades. Raising it reduces losses **only by trading less**.

_2026-10-11. `conf_floor.py`. 293 closes, of which **176 carry a populated `confidence_score`**.
Era-aware, with a shuffled-threshold placebo as the headline statistic._

---

## ⚠️ First, the trap I walked into and backed out of

On the full 293-trade ledger every floor looks **monotonically worse**, which reads as "the confidence
score is actively harmful." **It is the era artifact a third time.**

| month | trades | with `confidence_score == 0` |
|---|---|---|
| 2026-06 | 132 | **117 — 89%** |
| 2026-07 | 142 | **0 — 0%** |
| 2026-09 | 15 | 0 |
| 2026-10 | 4 | 0 |

**The score did not exist before July.** So `confidence == 0` is a near-perfect proxy for *June*, and June
was the profitable month. The floor curve on the full ledger measures **how much June you keep**, not
confidence. The apparent "+$2.66/trade for zero-confidence trades" is era: within era 1 it is **+$1.88,
t = 0.32**, the week-clustered CI is **[−$11.67, +$16.23]**, and only **2 weeks** contain both groups.

Everything below is restricted to the **176 trades where the score is actually populated.**

## 🔴 The answer

Baseline on those 176 trades: **−$1.71/trade, −$300.71 total.**

| floor | kept | mean $/trade | total $ |
|---|---|---|---|
| 35.0 (all) | 176 | **−1.71** | −300.71 |
| 53.4 | 158 | −1.90 | −299.91 |
| 58.9 | 141 | −2.25 | −316.90 |
| 65.0 | 106 | −3.13 | −331.69 |
| 69.5 | 71 | −4.22 | −299.62 |
| 75.5 | 36 | **−4.91** | **−176.66** |

**The mean per trade gets monotonically worse as the floor rises. The total loss shrinks.** Those are not
in conflict, and the distinction is the whole finding:

> **A higher floor cuts your losses by cutting your activity, not by picking better trades.** At a floor
> of 75.5 you lose $177 instead of $301 — but each trade you still take is **$3.20 worse**. You could get
> the same effect by taking fewer trades at random.

**Best in-sample gain from any floor: $+0.00/trade.** No floor beats taking everything.

## The placebo, which is the statistic that matters

Sweeping a threshold and reporting the best one always flatters itself. So: the same search on **shuffled**
confidence.

| | best in-sample gain |
|---|---|
| **observed** | **$+0.00/trade** |
| shuffled, mean | +$0.88 |
| shuffled, 95th percentile | +$2.45 |
| shuffled, max | +$4.00 |

**p = 1.000.** Randomly permuted confidence finds a *better* floor than the real score does. The real score
is not merely uninformative — it ranks trades slightly worse than chance, though read the power line below
before taking that further.

**Correlation with P&L:** pooled **−0.181**, equal-weighted by week **−0.087** (7 weeks). The 80%-power
MDE at n=176 is **0.213**, so **both are below the detection floor.** I cannot claim the score is
anti-predictive. I can claim there is no positive relationship to find at this sample size.

## Trader rules — one number each
1. **A confidence floor does not improve trade selection.** Best achievable gain is **$0.00/trade**, and
   shuffled confidence does better.
2. **If the goal is to lose less, the lever is trading less — not filtering by confidence.** A floor at
   75.5 cuts the loss from $301 to $177 purely by discarding 140 of 176 trades.
3. **Ignore any confidence number from before July.** It was not populated; 117 trades carry a literal
   zero and they are all June.

## Limits
- **176 trades, 10 weeks, and 142 of them are July** — the month that lost $317. This is substantially
  "within July, confidence does not rank trades." It is not established for a different regime.
- `confidence_score` here is the **logged entry value**, not the `AdaptiveConfidenceFloor` state in
  `confidence_state.json` / `feedback/adaptive_confidence.py:81`. If the live floor gates on a different
  quantity, this tests the ledger's column and not that mechanism — **worth the server confirming they are
  the same number.**
- The placebo tests *threshold mining*, which is the relevant null for "should we set a floor." It does
  **not** test whether confidence predicts something other than per-trade P&L.
- Not red-teamed.
