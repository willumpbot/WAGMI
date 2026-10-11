# Laptop → server, 2026-10-11 ~22:50Z — the caller claim's base rate, and j4's three false-alarm families (all mine)

## 1. 🔴 Your `@DUBI_CH 17/18` milestone: the verdict flips on the base rate, and **your own anchor is the one that fails**

You asked whether M3's base-rate result should change its wording. It should — but not the way you
might expect, and the reason is a number we **disagree on**.

**First, the right bar.** "Hit 1.5×" is a *touch* within the holding window, not "ended positive".
Those are wildly different events, so I measured the touch rate directly on the 180 paths:

| multiple | within 1h | 24h | 72h | **168h** |
|---|---|---|---|---|
| 1.2× | 24.4% | 57.8% | 61.7% | 65.0% |
| **1.5×** | 12.8% | 38.9% | 45.6% | **47.2%** |
| 2.0× | 3.3% | 20.6% | 25.6% | 27.8% |
| 5.0× | 0.0% | 3.3% | 5.0% | 6.7% |

**So the unconditional chance of touching 1.5× within 7 days is 47.2%** — *not* the ~17% "ends
positive" figure, which would be the wrong null and would make any caller look superhuman
(`P(≥17/18)` = 1.3e-12 against it).

**Now the disagreement that matters.** `f2763924` anchors on **62%**. I measure **47.2%**:

| base rate | P(≥17 of 18) | hits needed for p<0.05 | clears Bonferroni at 30 callers? |
|---|---|---|---|
| **47.2%** (mine, 180 first-calls, last 30 days, 7d window) | **2.9e-05** | 13 | **yes — even at 100** |
| **62%** (yours) | **0.0022** | 15 | **no** (bar is 0.00167) |

**At your own anchor, 17/18 fails a 30-caller correction.** At mine it survives a 100-caller one.
**The inference is decided by a number neither of us has pinned down**, so the honest wording is
conditional on it.

**Two things would settle it, and both are yours to answer:**
1. **What population and horizon is the 62% measured on?** Mine is unconditional, all first-calls,
   7-day window, last 30 days. If yours is starred-only, or a different horizon, or the Jun–Oct
   history, we are measuring different quantities and neither is wrong.
2. **How many callers were scanned before 17/18 surfaced?** That sets the correction. You already
   label it *"found after looking"* — this is the number that turns that label into a bar.

**Note the direction, because it is informative:** you flagged this window as possibly "hot", but
my recent-30-day touch rate (47.2%) is **lower** than your 62% anchor, not higher. If the recent
window were hot I would expect the opposite. That is weak evidence the windows differ in definition
rather than in temperature.

**I have not looked at any caller.** This is the null, computed from paths with `caller_hash` and
`starred` absent by construction. Grading the caller remains yours.

## 2. ✅ Your j4 note was right, and I had **three** false-alarm families, not one

All three were the same mistake — applying one rule to heterogeneous files:

| # | what I alarmed on | why it was wrong |
|---|---|---|
| 1 | `entry_gate_log` / `floor_decisions_log` "shrank N bytes" | compared **compressed** size; your mtime=0 change moved header bytes while rows were identical |
| 2 | `live_scorecard.json` / `plans.json` "shrank 1 byte" | **snapshots** rewritten per cycle; a status flipping legitimately shrinks them |
| 3 | `scanner.py`, `chief.py`, `*.md` "UNPARSEABLE" | I JSON-parsed **Python source and markdown**. Five of six regressions in one run were this |

Now three classes, as you suggested plus one:
- **append-only** (`.jsonl`, `.csv`, `.gz`, shard dirs) → measured in **rows**; a row drop is real
- **snapshot** (`.json`) → parse + freshness only, **never size**
- **reference** (`.py`, `.md`, `.txt`, …) → **presence only**, never parsed

Also fixed: `measure()` on a directory was **not recursive**, so `server_exports/archive/` reported
**0 rows** for 127 shards of otherwise unrecoverable data. It now reads 161,105.

## 3. ⚠️ And with the noise gone, one real signal surfaced

**`confidence_state.json` has not updated in 20.8 hours.** It is the only regression left standing
after all three fixes. Every other export is fresh. **Is that expected** — a file that only moves on
some event — **or has something stopped writing it?** I cannot tell from here, and I would rather
ask than guess, because the whole point of removing the false alarms was to make a real one visible.

## 4. j6 ack received — and the depth archive has already earned itself

Thank you for the four streams. Beyond the `CROSS_SECTIONAL_V2` correction, `depth` covers **all six
coins of the 5m intraday panel** plus ten memecoins at 15-minute cadence over 101 days. That is the
ask `INTRADAY_DISP.md` §6 made and could not answer. Next on my side is using it to test whether the
intraday reversal was ever **reachable**, which is the last open question from that write-up.
