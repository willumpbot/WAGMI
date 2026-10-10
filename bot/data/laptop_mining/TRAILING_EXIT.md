> # 🔴 REFUTED by red team `wxoc7han2` (high confidence). Do not act on this document.
>
> **The trailing exit is NOT better than a fixed target.** Under neutral intra-bar ordering and
> gap-aware fills the paired gain is **−0.0218R (t −0.45)** at ×1 and **−0.0391R (t −0.77)** at ×2.
> Three defects, two of them outright bugs in my own code:
>
> 1. **The hard 1R stop was disabled once the trail armed** — `if adv >= 1.0 and not armed`. A
>    position armed at +0.25R with a 1.5R trail had its trigger at **−1.25R**, i.e. it was allowed to
>    lose more than the stop permits. This penalises loose trails and leaves tight ones untouched, so
>    it **manufactured the "trail tight, 6 of 6" result.**
> 2. **The trail was tested against the previous bars' best**, before `best` updated — the most
>    favourable intra-bar ordering available. Flip only that and the headline cell goes
>    **−0.1033 → −0.2164** and 6-of-6 becomes **0 of 6**. A neutral coin-flip ordering gives −0.1598,
>    so **54% of the claimed gain was ordering convention.**
> 3. **Exits booked the trail level exactly.** 74.5% of trades exited by trail, and on the exit bar
>    price travelled a mean of **0.2874R through** the level (max 5.393R; 36.4% more than 0.25R
>    through). Filling at the bar low gives **−0.4593R**. The published −0.1033 was the extreme
>    optimistic end of a [−0.4593, −0.1033] band.
>
> **"1.6R per trade is left on the table" is inflated ~14×.** Excursion is the *ex-post supremum* of
> the price path — no causal rule can harvest it. My own best cell captured 7% of it, and under honest
> fills, none. Calling it "plain measurement — no null, no model" was the error: it is a difference
> against a perfect-foresight benchmark, which is both a model and an infeasible one.
>
> **Two more defects.** The −0.0433R headline was the **argmax of 90 cells** (median −0.1401, and the
> selection gap is smaller than one standard error). And my standard error was **inflated 4.0×** —
> I added two SEs in quadrature for the *same* 15,663 trades (0.1551 vs the correct paired 0.0392),
> which manufactured every "unmeasurable" label in the document.
>
> **The confidence-filter claim is also wrong as presented.** I printed 3 of 5 excursion values
> (0.760 / 0.731 / 0.707) and called it a monotone fall. The full column is
> **0.7602, 0.7514, 0.7311, 0.7448, 0.7070 — non-monotone.** The three I happened to print were the
> only falling subset.
>
> **What survives:** `exc` and `stopped` as raw measurements (reproduced exactly: +1.1854R mean
> excursion, 68.67% stopped out at ×1), and the cached panel itself (verified bit-identical).
> Nothing built on top of them in this document stands.

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
