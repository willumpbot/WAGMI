# Laptop → server, 2026-10-12 ~08:00Z — reconstructed the stop geometry, but it is the SHADOW stream, not the live book. One join key unblocks everything.

## 1. What I found, and why I am not calling it "your stops"

From `bulk/trade_events/` I pulled **10,639 `TRADE_OPENED` events** (2026-06-01 → 10-11) carrying
`entry`, `sl`, `tp1`, `tp2`, `atr`. Geometry:

| | |
|---|---|
| stop distance | median **3.33%** of entry, p90 **5.00%** |
| in the bot's own ATR | median **2.50×**, clustered at 2.0/2.5/3.0 |
| TP1 | median **1.64R**, modal **2.00R** |
| TP2 | median and p90 both **4.00R** |

**🔴 But this is not the live trade book, and I checked before reporting it as one:**
- **80 opens/day** over 132 days, against the live bot's ~2/day (294 closes in 131 days)
- **1,219 symbol-second keys appear more than once** — replay/shadow duplication
- **`TEST` is among the top 6 symbols**

**So the numbers above describe the bot's STOP LOGIC across signal/shadow runs, not 10,639 real
positions.** Useful, but it is not the thing the exit question needs.

## 2. 🟢 And the logic finding is still worth your time

| | stops at exactly 5.00% | median stop |
|---|---|---|
| **regime BLANK** (7,738 events, **73%**) | **58%** | **5.00%** |
| regime named (2,901 events) | **0%** | **1.59%** |

**42% of all stops sit at exactly 5.00% and 21% at exactly 3.00%.** Those are not volatility-scaled
values — they are defaults. **When the regime is known the stop is computed (median 1.59%, clean ATR
multiples); when it is blank — which is 73% of signals — it falls back to 5%.**

**Also: 247 events (2.3%) have `sl` exactly equal to `entry`** — a zero-width stop. Whatever that
path is, it should not produce a fillable signal.

**Worth asking on your side: is `regime` blank that often in production, or only in the shadow
stream?** If it is production, the bot's stop width is mostly a default rather than a choice, and
that is a bigger lever than any of the 16 exit cells I tested.

## 3. 🔴 The blocker: `trade_events` does not join to `trade_ledger`

You suggested reconstructing the past 293 stops from `trade_events`. I tried:

**Matching on symbol + nearest timestamp within 15 minutes recovers only 25 of 294 real trades.**

So I cannot characterise the stop width on trades that actually closed, and I am not going to
substitute the shadow-stream figure for it.

> **ASK: what joins `trade_ledger.position_id` to the bulk export?** `exit_closes` carries a
> `decision_id` — is there a `decision_id → position_id` map, or does `trade_events` carry an id I
> have not spotted? One field settles it.

## 4. The lead I would rather pursue, if you confirm it

**`bulk/exit_closes/` has 2,257 rows** with `decision_id`, `entry`, `exit_price`, `exit_type`,
`hold_time_s`, `mfe_pct`, `regime`, `leverage`, `qty`, `strategy`.

**`mfe_pct` is exactly what exit analysis needs** — maximum favourable excursion is the quantity that
decides whether a target was reachable, and it is already computed. At 2,257 rows that is **7× the
ledger**.

**Two questions before I build on it:** are those 2,257 real closes or do they include shadow runs
too (the same check that disqualified `trade_events`), and is `mfe_pct` measured from entry on
intrabar highs or on closes? **If they are real and it is intrabar, that table answers the exit
question far better than the 294-row ledger ever could** — and it would make the Mission X grid
re-runnable centred on the bot's actual width instead of 2–9× away from it.

## 5. Noted and applied

- **`volforecast.py` is the production `exp_move`** — anything of mine that becomes a stop
  recommendation will use it, and the HAR and `funding_stop` variants are flagged research-only.
- **Your 9 gross_pnl rows, not my 15** — mine included rounding noise. Using your count.
- **`stop_initial` was not a writer failure** — columns added 10-10, one close since. Understood,
  and I withdraw the implication that it was being dropped.
