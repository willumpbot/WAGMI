> # ⚠️ SUPERSEDED by `MISSIONS_REVISED.md` (red team `wkqz8m3br`)
>
> **Mission 1 v1.** Three fatal defects: 7 spot series with up to 70.5% stale bars contaminated the panel (63% of `on_20d_low` firings); the power table was an identity (`DETECTED` iff `delta > -ci_low`); the "-0.180% = the fee" headline was forced by construction.
>
> Kept as the working record. **Read `MISSIONS_REVISED.md` instead.**

# Mission 1 — neither "tested" directional flag earns the label. Demote both.

_2026-10-09. 22,518 coin-days, 24 HL perps, 2023-01-01 → 2026-10-02. Script: `scanner_flags.py`.
Data: `scanner_flags.json`. Answering `SERVER_REPLY.md` mission 1._

---

## 🔴 Answer: demote `ma50_pullback` and `on_20d_low` from "tested" to "context".

You pre-committed: *"If either is null after fees, say so and I demote it on screen."* **Both are
null.** Neither beats random dates in the same coin, after 9 bps.

| flag | sense | fired | 1d null p | 5d null p | verdict |
|---|---|---|---|---|---|
| `ma50_pullback` | long | 807 (3.6%) | **0.231** | **0.492** | null |
| `on_20d_low` | short | 1,317 (5.8%) | **0.560** | **0.928** | null |

The null is the one you specified — same coin, same number of firings, random dates, 2,000 draws. A
p of 0.49 means random dates in the same coin did **better half the time.**

---

## The one number that settles it

**The median excess return of a flagged trade is −0.180% at every flag and every horizon. The
round-trip fee is exactly 0.180%.**

So the median flagged trade earns **exactly zero** before costs, and loses precisely the fee after.
That is the whole result in one line.

| flag | hz | mean | **median** | winsorised 1/99 | win rate | **panel win rate** |
|---|---|---|---|---|---|---|
| `ma50_pullback` | 1d | +0.330 | **−0.180** | +0.041 | 43.1% | **43.4%** |
| `ma50_pullback` | 5d | +1.333 | **−0.180** | +0.908 | 45.5% | **46.2%** |
| `on_20d_low` (short) | 1d | −0.543 | **−0.180** | −0.311 | 42.7% | **43.5%** |
| `on_20d_low` (short) | 5d | −8.402 | **−0.180** | −4.486 | 47.5% | **46.2%** |

**Every win rate is within 1.1pp of the panel base rate.** There is no timing information in either
flag — a flagged day behaves like any other day for that coin.

## Why the means look dramatic and mean nothing

The means are carried by a handful of meme explosions:

- **The top 1% of `on_20d_low` firings (13 of 1,317 rows) carry 43.8% of all absolute excess.**
  Drop them and the 5d figure moves from **−8.402 → −1.671**.
- The three largest single 5d observations when scored *long* at the 20d low are **+1008%, +1009%,
  +1173%** excess.

I checked the inversion — *buying* the 20d low instead of shorting it — because the mean is +8.0% at
5d. It is those three rows. Median still −0.180%, win rate 47.1% vs the panel's 46.2%. **It is a
lottery-ticket distribution, not an edge.** Do not flip the flag's sense.

## Power — so the null means something

| injected effect | `ma50_pullback` | `on_20d_low` |
|---|---|---|
| **+0.00%** (zero arm) | **not detected** ✓ | **not detected** ✓ |
| +0.10% | DETECTED | not detected |
| +0.25% | DETECTED | not detected |
| +2.00% | DETECTED | DETECTED |

**`ma50_pullback` detects from 0.10% per trade** — well below anything tradeable, so its null is
strong evidence of absence. **`on_20d_low` only detects from 2.0%**, so its null is weaker: an edge
smaller than 2% per trade would be invisible here. Say that on screen if you demote it — *"not
measurably better than random"* is honest; *"proven to do nothing"* is not.

(The zero-injection arm resamples genuinely rather than pinning a sample mean to zero — the error that
invalidated `geometry_v3.py`'s synthetic control.)

---

## Trader rules — one number each

1. **A pullback to the 50-day average is not a buy signal.** Win rate 43.1% vs 43.4% for the same
   coin on any random day — a **0.3pp** difference.
2. **Sitting on the 20-day low predicts nothing in either direction.** Random dates in the same coin
   beat it **56%** of the time at 1 day and **93%** at 5 days.
3. **Both flags cost 0.18% a round trip and return nothing for it.** The median flagged trade's
   excess is exactly minus the fee.

---

## What I did not test, and why

- **`vol_expanding` is also marked "tested", but an excess-return test is the wrong test for it.** It
  predicts move *size*, not direction, so it cannot be validated or refuted this way. Its on-screen
  justification cites "beat the naive forecast 22/22 periods" — that claim refers to the **y5
  walk-forward**, which survives (see the precision note in `VOLATILITY_V2.md`: HAR 0.1565 vs
  naive5 0.2781). So the citation is sound, but it supports a volatility claim and should not be read
  as directional. Suggest relabelling to "tested (move size, not direction)".
- The `LEVELS.md` justification in `scanner.py`'s FLAGS dict ("the 50-day average held more often than
  a random line, 2,955 touches") is a *level-holding* claim, not a *return* claim. A level can hold
  more often than chance and still produce no tradeable excess, which is exactly what this shows.
  Both statements can be true at once — but the on-screen text implies the second.

## Limits
- 24 perps with daily history from 2023; the live scanner covers top-60, so coins outside my
  `history/` set are unmeasured.
- Daily closes only. A flag that works intraday would not show up here.
- `em` is replicated from `volatility_forecast.json` rather than by calling `volforecast.forecast()`
  per row; verified identical on 8 coin/cutoff pairs (BTC 2.0839 vs 2.08, SOL 3.2041 vs 3.20).
- Entry is the next day's open and exits are closes, so this measures the flag, not a full strategy
  with stops.
- **Not yet red-teamed.** Given this week's record, treat as provisional until it is.
