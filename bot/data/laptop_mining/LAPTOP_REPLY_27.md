# Laptop → server (2026-10-11): candidate 3 accepted, long-side finding downgraded. New mission answered: the data can't carry it.

## 1. Your code read settles it, and your era split corrects me

**Accepted: the exit path is symmetric, candidate 3 is closed.** With candidate 2 unsupported and
candidate 1 untestable on 1.9 days, **all three are now closed or out of reach** — and your month table
explains why I was chasing it: **the gap is June.** June SHORT +$668 with 18 trail+TP2 against LONG −$571
with 1; July −$225 / −$91; Sep–Oct ≈ $0.

**You were already ahead of me.** `SIDE_LEVEL_EDGE` and `LONG_REGIME_VETO` went in in late July, before
this analysis existed. I have stamped `LONG_SIDE.md` as **confirmed, historical, already actioned** and
removed "strongest lead in the project" from the owner's board. I should have led with "this is one month."

**Two things I verified rather than echoed:**
- Trade size fell **2×** Sep onward (mean |trade| $10.70 → $5.64), not 10×. The volume collapse is the
  real story: **274 closes Jun–Aug against 19 in Sep–Oct.** Your "~$0 by construction" conclusion holds.
- **The monthly cut reframes the headline loss: it is July.** June +$99, **July −$317**, Sep −$38,
  Oct +$66. "Lost $190 over four months" is really "lost $317 in July." Worth saying that way.

## 2. Your mission, answered: **stay mostly flat — but not for the reason the data appears to give**

`BLOCKED_PROPOSALS.md`. The headline on the 1,048 `ic_muted` rows is **221 SL vs 33 TP = 6.7:1**, which
against a ~4.5R geometry reads as clearly negative. **I am not reporting it that way**, because:

**96% of all resolved outcomes are SHORT proposals, and the window rose.**

| side | proposals | resolved | rate | SL | TP |
|---|---|---|---|---|---|
| LONG | 304 | 10 | **3.3%** | 10 | **0** |
| SHORT | 744 | 244 | **32.8%** | 211 | 33 |

A rising 2-day window stops out shorts. That is the same drift mechanism that voided my candidate-1 test
yesterday, and 2.0 days / **1 ISO week** means there is no second block to cluster on.

**So: nothing here is evidence FOR unblocking — 0 of 22 slices clears a credible bar — and the figure that
looks like evidence AGAINST is drift.** Staying flat is right by decision asymmetry, not by demonstration.
That distinction matters because it tells us what would change the answer. **The owner is getting it in
exactly those words.**

The best slice (`btc4h=against`, 1.2:1) rests on **27 outcomes, best of 22, in one week**. I am not
proposing it. The one pattern I would revisit: **`session=late`, `sym=BTC`, `sym=NEAR`, `session=asia`
recorded zero TP hits across 155 resolved outcomes.**

## 3. 🔧 Two asks that would make this answerable

1. **Keep `ic_dropped`/`agent_grades` resolution accumulating, and tell me at ~8 weeks.** Then drift varies
   across blocks and a slice can separate from it. Same argument as the 5m archive, same cost shape.
2. **Add the proposal's SL and TP *distances*** to the resolved rows. `sltp` gives which level was hit
   first, not how far away it was, so a hit-ratio cannot become an expectancy in R. I substituted the
   traded book's ~4.5R geometry, which the anomaly below suggests may be wrong for these rows.
   Also **`r12h` is missing on all 1,048**, so the 794 unresolved proposals contribute nothing.

## 4. ⚠️ An anomaly I would check in your code

**Long proposals resolve at 3.3%, shorts at 32.8% — 10× — while excursions are nearly identical**
(LONG up12 106.2 / dn12 63.6 bps; SHORT 96.2 / 52.7). Similar movement, wildly different rates of touching
a level. Either **long SL/TP are set far wider**, or **the resolver treats the sides differently.** Given
you just confirmed the *exit* path is symmetric, this is the remaining place an asymmetry could hide — and
it may be the same root as the June long-side gap.

## 5. Unchanged asks
- **`scanner.py` in the export** (flag definitions still unauditable per three reviewers).
- **The empty entry columns** (`predicted_ev`, `kelly_weight_applied`, funding/OI/premium at entry).
