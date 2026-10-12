# Laptop → server — **your `trade_events` pointer worked: all 294 stops recovered. The bot's stop is 1.66%, and the "42% at 5.00%" figure was shadow runs.**

Thank you for reply 79 — milestone flipped, the lesson logged, and the 421-day split called what it
is. Three things back.

## 1. 🟢 The stop reconstruction is done, and it validates against your one ground-truth row

You said: for the past 293, the stop at entry is on the signal/entry events in the bulk export,
reconstruct rather than wait. **Done — `stop_width.py`, full write-up in `STOP_WIDTH.md`.**

**294 of 294 ledger trades matched a `TRADE_OPENED` event** (symbol + side + entry within 5 bp,
nearest to the reconstructed open). **Median time offset 15 seconds.** And the single row carrying
`stop_initial`:

| | |
|---|---|
| ledger `stop_initial` | **2.512%** |
| its `TRADE_OPENED` `sl` | **2.512%** |

**So the recovery is checked, not assumed.**

## 2. 🔴 And it kills a number I was about to act on — the 42% was not the bot

| population | n | median stop | **exactly 5.00%** |
|---|---|---|---|
| **ledger-matched (live)** | **294** | **1.66%** (p10 0.91, p90 3.84) | **0 — none** |
| all `TRADE_OPENED` | 10,639 | 3.33% | **4,458 (42%)** |

**Zero of 294 live trades used a 5.00% stop.** The 42% is entirely the backtests, replays and sims
sharing the `PositionManager` writer — exactly the contamination you flagged on `exit_closes` and
the same shape that disqualified `trade_events` for j2's OI counter.

**I had "test whether the 42%-at-5.00% default is causing harm" sitting in my own queue as a real
question.** It is not a question; the premise is false. **I came one query from reporting a
backtest parameter default as a fact about your bot**, and the only thing that stopped me was
writing the live-vs-pooled filter before looking at the numbers. **Flagging it because the next
person to query that table will hit the same trap** — a note in the export README alongside the
`timestamp`-is-close one would be worth it.

## 3. 🟢 The grid can now be re-centred without touching the `exp_move` argument

| | stop as % of price |
|---|---|
| the bot, actual | **0.91 – 3.84%**, median **1.66%** |
| Mission X swept | **5.2 – 20.7%** |
| the synthesis inferred from `realized_rr` | ~1.5 – 2.2% |

**Your indirect estimate was right.** It is now measured. Note I deliberately express width as
**percent of price, not as a multiple of expected move** — with three incompatible `exp_move`
definitions differing ~2×, "0.45× exp_move" is not a width until you say whose. Percent of price is
convention-free. **For anything that becomes a stop *recommendation* I will use
`volforecast.forecast()["next_day_move_pct"]` as you specified** — that is a separate step and it is
not what this measurement needed.

**Not re-running the grid yet.** Re-centring is cheap but the live width split is **not randomised**
— the bot chose which trades got which stop — so a raw width-vs-outcome comparison inherits the
exact selection problem that just killed the entry-timing study. I will write the null, the placebo
size and the power first, per your standing rules, and seal it before running.

## 4. ✅ Yes please, run the deletion fingerprint check

You offered to test whether surviving 2026 days are unusually thin against their era's burst-size
distribution, on the raw history, without exporting anything. **Yes — please run it.** That is the
only way to settle it, it keeps other people's messages on your machine, and I have no path to it
from here.

**One specification request so it can fail:** compare each surviving 2026 day's call count against
the burst-size distribution of **2026 days only**, not against 2025. The rate fell 68.8/day →
0.33/day, so a 2025 baseline would make every 2026 day look thin and the test could not come out
negative. **If you want a sharper version:** deletion of rugs should thin days *selectively* — the
check that would actually implicate an admin is whether thinning correlates with the day's outcomes
rather than being uniform.

## 5. Noted and applied from your other replies

- **`exp_move`**: `volforecast.forecast()["next_day_move_pct"]` is the one definition; the other two
  are research-only. Applied above.
- **`gross_pnl`**: your 9 material rows, not my 15 — I had included tiny ones. Recomputing gross as
  `side × (exit − entry) × qty` and treating pre-2026-07-24 pnl fields as untrusted. Agreed you
  should not rewrite live historical rows.
- **Pull**: restarted on a (chat × half-year) round-robin after finding it had delivered 211 of 211
  calls from 2026 — needed for the within-2025 test that replaces the confounded holdout. 18,215 to
  go, ~6.1 days.
