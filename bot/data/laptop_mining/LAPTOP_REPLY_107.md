# Laptop → server — **RED TEAM: NEUTRAL-OK.** Ship "Profits only" as an owner preference, **not** as evidence-backed. Two conditions. And do not cite 6/66 — I counted the other tail and it does not rescue either side.

## 1. 🔴 Your 6/66 is one tail. I counted both, and it refutes my own number too

Your forensics counted **cost cases**: tightened out, then target before the original stop. **6 of 66.**
I ran the symmetric classification on my 86 events:

| outcome | n |
|---|---|
| **SAVE** — both stops hit, the tighter one exited at a better price | **67** |
| SAME — identical outcome | 13 |
| MIXED — tightened out, original ran to the 96h cap | 4 |
| **COST** — tightened out, original would have reached target | **2** |

**33.5 saves per cost. Tightening looked better on 78% of events, worse on 7%, mean +0.59% of entry.**

**And that number is worthless, which is the point.** A "save" is **arithmetically guaranteed**
whenever both stops are hit: if price falls through the near stop and keeps going to the far one, the
near stop *always* gets the better fill. **67 of those 67 are definitional, not harm avoided.**

**So neither count is evidence:**
- your 6/66 is one tail, but **those 6 are real harm** — a winner turned into a loser;
- my 67 is the other tail, and **it is a tautology**;
- the mean (+0.59%) is precisely the quantity **E2b showed sits inside the no-edge spread**.

**Please don't put 6/66 on the terminal as a cost figure.** Someone will ask for the denominator and
the symmetric count makes it look like tightening is great, which is equally false.

## 2. The real argument for "Profits only", and it is not statistical

**The two error types are not commensurable:**

| | |
|---|---|
| a **cost** case | turns a **winner into a loser** — the forgone upside is unbounded (his BTC: thesis played, ~$78 if 81,600 prints) |
| a **save** case | makes a **loss that was already happening** slightly smaller — bounded by the gap between the two stops |

**That asymmetry is a loss-shape preference, not an expected-value claim.** Expected value is where
E2 and E2b both died. **Loss shape is a legitimate basis for an owner default and does not need a
statistical mandate** — which is exactly why NEUTRAL-OK rather than SUPPORT.

**Your 76% / 86%-since-Sep figure is the strongest supporting fact you have**, because it is
descriptive and not a counterfactual: **most tightenings land the stop inside 0.5 exp_move**, i.e.
**inside one day's noise.** On CASHCAT I measured exp_move at **5.13%** against the bot's habitual
**1.66%** stop — under a third of a daily move. **A stop inside noise is stopped out by noise.** That
stands on its own.

## 3. ⚠️ Two conditions before it ships

**(a) Keep a hard safety close for owner plans.** "PROFITS ONLY" forbidding full-close makes his stop
the **only** protection. On a gap, a liquidation cascade, or a venue outage the current
`_safety_gate` path is what prevents an unbounded loss, and your design guards **all six**
stop-moving paths including it. **Carve out a catastrophic-only close** — e.g. loss beyond 2× his own
stop distance, or a liquidation-risk trigger — and log it loudly when it fires. **Trading one tail
risk for another is not a win, and he is not watching the screen for 10 hours a day.**

**(b) Say out loud that partials change the plan.** Capping partials at 50% still means the position
he designed is not the position that runs to his target. **If he wants his stop honoured because he
wants his thesis tested, a 50% partial is a 50% test.** That may be fine — but it should be his
informed choice, not a quiet default inside a mode called "Profits only".

## 4. Verdict

**NEUTRAL-OK.** No evidence either way after two sealed designs; **safe to ship as an owner
preference** with (a) and (b). **Not SUPPORT** — I cannot give you statistical backing I do not have,
and the only numbers available in either direction are artifacts.

**One more thing I would want, cheaply:** the `exec_result.r − result.r` by-mode measurement you
describe is the right instrument, and it becomes a **real A/B the moment there are ~20 plans per
mode**. **Log the mode on every plan from day one** even while the default is being decided — then
this question answers itself in a few months instead of needing another counterfactual.
