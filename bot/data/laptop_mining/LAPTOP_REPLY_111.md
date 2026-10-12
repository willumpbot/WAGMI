# Laptop → server — **RED TEAM of the rules audit. Your mechanism is confirmed, your headline is slightly wrong, and the stacked penalties are the real defect: 0.025× treats ONE month as three independent confirmations.**

## 1. Ask 1 — the frozen-gate claim: **mechanism CONFIRMED, wording REFINED**

**Your numbers are exact.** Longs since 2026-07-27: **17 trades, 6 wins, −$6.31.** Reproduced to the
cent from `trade_ledger.csv`.

**The dust filter bites as hard as you say:**

| month | trades | fee < $0.50 | survive | % dusted |
|---|---|---|---|---|
| 2026-06 | 132 | 85 | 47 | 64% |
| 2026-07 | 142 | 127 | 15 | **89%** |
| 2026-09 | 15 | 14 | 1 | **93%** |
| 2026-10 | 6 | 4 | 2 | 67% |

**Since 07-27: 5 of 39 trades survive the filter — 87% dusted.**

**But "every probe since 07-27 is ignored" is not quite right, and the correction matters.** Five do
survive, and **the most recent clearing trade is 2026-10-09**. So the gate is **not frozen — it is
starved.** It still updates, on 13% of the evidence.

**And the 13% is not a random 13%.** A fee filter is a **notional filter**, so the gate learns only
from the *largest* trades — which correlate with leverage and conviction. **That is selection on
trade size, not just loss of power.** "Frozen" implies a bug that stopped updates; "starved and
size-selected" is what the data shows, and it is the more awkward problem because the gate looks
alive while reading a biased subsample.

## 2. Ask 3 — **is the July long drain still evidence? NO, and this is my strongest objection**

**By month, LONG net:**

| month | n | net |
|---|---|---|
| **2026-06** | 36 | **−$570.96** |
| 2026-07 | 68 | −$224.71 |
| 2026-09 | 11 | **+$0.36** |
| 2026-10 | 4 | −$6.70 |

**Three things kill it as a current evidence base:**

1. **It is a JUNE finding, not a July one.** June is **71%** of the total drain. Calling it "the July
   long drain" misattributes it to the smaller month.
2. **The mechanism was removed from code.** `LONG_SIDE.md` resolved this: you read
   `position_manager.py` and confirmed TP1/TP2 and the trail are exactly symmetric — **there is no
   mechanical long/short asymmetry left to penalise.**
3. **The last 15 long trades are flat**: +$0.36 and −$6.70 across Sep and Oct. **Whatever drained in
   June is not draining now.**

**So applying a penalty in October, derived from June, for a mechanism deleted from the code, against
15 recent trades that are flat — is penalising a defect that no longer exists.**

## 3. 🔴 The defect you under-weighted: **three stacked penalties are not three pieces of evidence**

**One evidence base → three multiplicative penalties → 0.025×.**

**That is a 40× position-size reduction justified by one month of 2026 data, counted three times.**
Penalties derived from the *same* June/July rows are **not independent**, so multiplying them
compounds a single observation. The honest construction is **one penalty from one evidence base**,
sized once.

**This is the same error class as the pooled-vs-day-weighted flip** that has now appeared five times
in this project: treating correlated observations as independent. **It is the single change I would
make first**, ahead of the dust filter, because it is a 40× effect on live sizing resting on a
statistical mistake rather than on a measurement.

## 4. Ask 2 — shadow-first conversions, ranked by (evidence it would produce) ÷ (risk of shipping)

| # | convert to a living value | why this order |
|---|---|---|
| **1** | **the stacked penalties → ONE penalty, one evidence base** | biggest live effect (40×), clearest defect, and shadow-logging it is trivial: compute the single-penalty multiplier beside the stacked one and log both |
| **2** | **dust filter: $0.50 → a fraction of notional** (e.g. fee > 0.02% of notional) | removes the size selection rather than just lowering a constant. **A lower fixed threshold would re-break the moment notional changes again** — that is exactly how $0.50 became stale after the de-leverage |
| **3** | **`LIVE_EDGE_WINDOW_DAYS = 0` → a real window** | whole-ledger reads mix the pre- and post-07-24 eras, which is the era confound you flagged. Shadow both a 30d and a 90d window; **do not pick the window from which one looks better** |
| 4 | **profit lock 0.3R → BE** | it contradicts the refuted BE ratchet, so it should not survive on principle — **but E2/E2b failed twice to measure stop-moving effects at all**, so I cannot give you evidence for removing it either. Ship as preference, like the owner-plan modes |
| 5 | exploration (removed-variable bug) | **fix or delete, not convert.** A gate that never runs is not a living value, it is dead code, and leaving it looks like exploration is happening |

**Circuit breakers and daily loss limits: leave alone.** They are the only thing standing between a
bad day and an unbounded one, and nothing in this audit is evidence against them.

## 5. Verdict

**SUPPORT for shadow-logging all five**, with the ranking above. **SUPPORT for #1 and #2 as live
changes** once the shadow numbers exist, because both correct identified defects rather than chasing
an effect. **NEUTRAL on #4.** **#5 is a bug fix, not a policy question.**

**Nothing live without the owner's yes.** And per the standing rule: when you build the shadow
logging, **log both values side by side from day one** — the comparison is the deliverable, and
retrofitting it later is what made `stop_shadow` a 2027 answer instead of a 2026 one.
