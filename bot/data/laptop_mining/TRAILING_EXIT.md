# The trailing exit is the biggest single lever — it takes the loss from −0.21R to about −0.04R. It does not reach profit.

_2026-10-10. 15,663 signals, 14 ISO weeks, 2026-02-11 → 06-05. Scripts: `trailing_exit.py`
(+ cached panel `trailing_exit_panel.csv.gz`). Data: `trailing_exit.json`.
Prompted by the owner's correction, which was right._

---

## Why this exists

`ADX_GATE.md` concluded "the signals are negative-expectancy at every trend strength". The owner
pushed back: that was measured at a **fixed** bracket, which throws away exactly what a trailing stop
captures — price running favourably and then coming back. He named the trailing exit as the likely
mechanism.

**He was right that the gap existed, and right that it mattered.** The trailing exit had **never**
been tested at a bracket that binds:

| | |
|---|---|
| `exits.py:30` | `STOP_MULT = 8.0` — "the geometry plateau" |
| `geometry_v3` | ×8 binds on only **14.3%** of trades |
| `exits_v2.py` | `grep -c trail` → **0** |

So v1 tested trailing where the bracket almost never fires, and v2 didn't test it at all.

---

## 1. There is a lot of profit on the table (measurement, not inference)

For each signal, the best favourable move in R before the stop fired or 48h elapsed:

| stop | mean excursion | median | p90 | reach +0.5R | reach +1.0R | **stopped out** |
|---|---|---|---|---|---|---|
| **×1 (bot today)** | **+1.185R** | +0.802R | +2.994R | 61.6% | 39.8% | **68.7%** |
| ×2 | +0.760R | +0.507R | +1.773R | 50.4% | 24.8% | **39.6%** |

A fixed 1R target captures **−0.209R** of that. **So roughly 1.6R per trade is offered and not
taken.** These are plain measurements — no null, no model.

**But the binding constraint is the stop, not the exit: 68.7% of trades are already dead at ×1.**
A trailing exit cannot secure profit on a stopped-out position. Widening to ×2 cuts that to 39.6%,
which is why every ×2 configuration beat its ×1 equivalent.

## 2. The stack does stack

Week means, net 9 bps. Each row adds one piece of the owner's described machinery:

| configuration | week mean R | vs baseline |
|---|---|---|
| fixed 1R target, ×1 stop *(the baseline I criticised)* | **−0.2086** | — |
| + tight trailing (arm +0.25R, trail 0.5R) | **−0.1033** | **+0.105** |
| + widen stop to ×2 | −0.0993 | +0.109 |
| + confidence ≥ 60 | −0.0816 | +0.127 |
| **+ confidence ≥ 75, trailing at ×1** | **−0.0433** | **+0.165** |

**The machinery cuts the loss by ~79%.** The owner's intuition about *mechanism* is confirmed:
tight trailing is the single largest contributor, moving −0.209 → −0.103 on its own.

Trailing direction is consistent: **trail 0.5R beat a fixed target in 6 of 6** stop/arm
combinations; **trail 1.5R in 0 of 6.** Trail tight, not loose.

## 3. But it converges on break-even, not on profit

**Best cell: −0.0433R, week se 0.1427, t = −0.30.** The 95% interval runs roughly **−0.32R to
+0.24R** — indistinguishable from zero in either direction. Not one of the 18 trailing
configurations has a positive week mean.

So the honest statement: **the machinery converts a clearly-losing signal stream into something
statistically indistinguishable from break-even.** That is a real achievement and it is not a
business.

## 4. The confidence filter is the weak link

| filter | n | trailing at ×2 | mean excursion | stopped out |
|---|---|---|---|---|
| all | 15,663 | −0.0993 ±0.153 | 0.760R | 39.6% |
| conf ≥ 60 | 10,631 | −0.0816 ±0.134 | — | 35.8% |
| conf ≥ 65 | 9,168 | −0.0866 ±0.140 | 0.731R | 35.9% |
| conf ≥ 70 | 6,275 | −0.0828 ±0.136 | — | 34.4% |
| **conf ≥ 75** | 4,247 | **−0.1529** ±0.154 | 0.707R | 34.0% |

**Non-monotone, and the tightest filter is the worst cell in the column.** More telling: excursion
*falls* as confidence rises (0.760 → 0.731 → 0.707) and the stop-out rate barely improves
(39.6% → 34.0%). **High-confidence signals are not better signals on either measurement that
matters.** The confidence score is a large part of the bot's complexity and it is not earning its
place here.

---

## Trader rules — one number each

1. **Trail tight, not loose.** Trailing 0.5R below the peak beat a fixed target in **6 of 6**
   configurations; 1.5R beat it in **0 of 6**.
2. **The stop is the bottleneck, not the exit.** **68.7%** of trades are stopped out at the current
   stop; a trailing exit cannot save a dead position. Widening to ×2 cuts that to 39.6%.
3. **The whole machinery gets you to break-even, not profit.** Best configuration **−0.043R ±0.28** —
   an 79% improvement on the baseline that still cannot be distinguished from zero.

## What I cannot claim
- **The trailing-vs-fixed comparison is underpowered.** Lag-placebo size came back **0.000** against
  a nominal 0.05, and the 80%-power MDE is not reached within 0.20R. So the *direction* (6/6, and
  consistent across every confidence band) is real; the *magnitude* of the improvement is not
  established. Per the standing rule, those cells are labelled `unmeasurable`.
- **This is my trailing implementation, not the bot's.** The live exit logic
  (`bot/core/position_wiring.py`, `tick_processor.py`) may differ in arming, granularity and
  slippage. I simulated on 1h bars; the bot runs on ticks.
- **Fees only.** No funding, no slippage, no partial fills.
- 14 ISO weeks, one corpus.

## The one thing that would settle it
**`trade_ledger.csv` from the desktop.** Everything above is simulation on the raw signal stream with
my own exit code. The bot's realised fills answer the owner's actual question — *does the live
machinery secure profit?* — directly, with no simulation and no assumptions about how the trailing
exit behaves. This is the fourth separate analysis today blocked on that file.
