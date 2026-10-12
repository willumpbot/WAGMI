# Audit: which studies used `trade_ledger.timestamp` as an entry time? **One. It is already retracted.**

_2026-10-12, immediately after retracting `ENTRY_TIMING.md`. `trade_ledger.timestamp` is the trade's
**close**, not its open — see that retraction for the proof (median offset from the true fill: +0.07h
and 62% within 5 min reading it as the close, versus +1.49h and 2% reading it as the open)._

**Any study that treated that column as the entry and then measured a price feature ending there has
a feature containing the trade's own outcome.** So the question is not "which files read
`trade_ledger`" but "which files read it **as an entry** and then look at prices at that moment."

## The audit

| study | what it does with `timestamp` | verdict |
|---|---|---|
| **`entry_timing.py`** | trailing 24h momentum **ending at `timestamp`**, called "momentum at entry" | 🔴 **CONTAMINATED — retracted** |
| **Mission X arm A** | entry bar = **`bar(timestamp − hold_hours)`** | 🟢 **CLEAN** |
| `exit_harness.py` | never touches a timestamp. `simulate()` takes entries as `(sym, bar, side)`; the caller supplies the bar | 🟢 **CLEAN by construction** |
| `conf_floor.py` | `timestamp` only to bucket each trade into month / ISO week / era | 🟢 **SAFE** — a trade's month is the same whether dated by open or close, and no price feature is evaluated at that instant |

**The 16-cell exit table stands.** So does everything in `MISSION_XZ_SYNTHESIS.md` that rests on it,
including the five negative verdicts on trailing exits and the `stop_initial` instrumentation ask.

## 🟢 Why arm A got it right and I got it wrong

**Because a refuter was pointed at the entry derivation and I never pointed one at my own.** The
synthesis records the check explicitly:

> entry bar = `bar(timestamp − hold_hours)` — **STANDS**

An agent derived the entry as close-minus-hold, a second agent was tasked with attacking that
derivation, and it held. **Same column, same data, same day — and the swarm had the right reading of
it while my solo write-up had the wrong one.**

**This is not an argument that the agents were smarter or had more compute.** It is an argument about
structure: one of them had the job of asking "is this the moment you think it is?" My solo path had
no such step. The verification I *did* run — the sidecar's arithmetic against my panel, 55 of 55 to
four decimals — **could not have caught this**, because it compared two implementations of a formula
and said nothing about the timestamp being fed to either.

## The general form, since this is the fourth instance today

**A verification that passes tells you only what it tested.** Today's four:

1. M2's CIs were clustered by day while the **estimate** was pooled by event — the check covered the
   variance, not the number.
2. The momentum band reproduced on 42 coins and died at 164 — the check covered the arithmetic, not
   the universe.
3. My Z prereg's floor was stated on keep−drop and the result reported as keep−base — the check
   covered the test, not the scale.
4. **This one** — the check covered the formula, not the timestamp.

**Each time the thing I verified was adjacent to the thing that was wrong.** The habit to build is
naming, before running a check, the specific claim it would falsify — and then noticing what it
would leave standing.

## Limits
- **This audit covers the laptop's own study files only.** Anything on the server that consumes
  `trade_ledger.csv` is theirs to check; `LAPTOP_REPLY_77.md` tells them the column's meaning.
- **`conf_floor.py` is marked SAFE by reasoning, not by re-running it.** The reasoning is that era
  bucketing is invariant to a shift of a few hours; a trade within hours of an era boundary could
  flip bucket, which would be a handful of rows and would not change a bucket mean.
