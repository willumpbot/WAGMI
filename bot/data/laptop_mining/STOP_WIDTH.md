# The bot's real stop is **1.66% of price**, not 5.00% — and **zero of its 294 live trades used a 5.00% stop.** The "42% sit at the 5.00% default" figure was shadow runs.

_2026-10-12. `stop_width.py`. Recovered from the 10,639 `TRADE_OPENED` events in `bulk_rows`
(j7 archive) matched against all 294 ledger trades. Validated against the one ledger row that
carries `stop_initial`._

---

## 1. The reconstruction works, and it is checkable

**294 of 294 ledger trades matched a `TRADE_OPENED` event** on symbol + side + entry price within
5 bp, nearest in time to the reconstructed open. **Median time offset: 15 seconds** (p90 321s).

**And the one row of ground truth agrees exactly:**

| | stop width |
|---|---|
| ledger `stop_initial` (the single populated row) | **2.512%** |
| that trade's `TRADE_OPENED` `sl` | **2.512%** |

**So the 293 rows whose ledger column is empty are recoverable, and the recovery is not an
assumption.** This is what the server pointed me at — the columns were added 2026-10-10, so the
1-of-294 was never a writer defect.

## 2. 🔴 The "42% at the 5.00% default" figure does not describe the bot

| population | n | median width | p10 | p90 | **exactly 5.00%** |
|---|---|---|---|---|---|
| **ledger-matched (live)** | **294** | **1.66%** | 0.91% | 3.84% | **0 (0%)** |
| all `TRADE_OPENED` | 10,639 | 3.33% | 1.19% | 5.00% | **4,458 (42%)** |

**The 42% is real in the pooled file and absent from the live bot.** Those 4,458 rows at a clean
5.00% are the backtests, replays and sims that share the writer — the server warned that
`PositionManager` writes from any process with `cwd=bot`, and the same contamination already
disqualified `trade_events` for j2's OI counter.

**So the pending question "is the 42%-at-5.00% default causing harm?" is answered by its premise
being false.** There is no 5.00% default in live trading to test. **I came within one query of
reporting a statistic about backtest parameters as a fact about the bot** — the only reason I did not
is that the filter was written before the numbers were looked at.

## 3. The exit grid was 3–20× too wide, now measured rather than inferred

| | stop as % of price |
|---|---|
| **the bot, actual** | **0.91% – 3.84%** (p10–p90), median **1.66%** |
| the Mission X grid swept | **5.2% – 20.7%** |
| the synthesis's inference from `realized_rr` | ~1.5% – 2.2% |

**The synthesis's indirect estimate was close** (it inferred ~1.5–2.2% from realized RR; the direct
measurement is 1.66% median) — but it is now measured, so a re-centred grid can be specified without
an `exp_move` convention. **That matters because three incompatible `exp_move` definitions exist in
this project and differ by ~2×**; expressing the width as percent of price is the same number for
everyone. The server has since named `volforecast.py` `forecast()["next_day_move_pct"]` as the
production definition, and that is what any eventual stop *recommendation* must use — but the
*description* above needs no convention at all.

## 4. A third independent confirmation of the close-timestamp

This matching reconstructed each open as `timestamp − hold_hours` and landed **15 seconds** from the
logged `TRADE_OPENED` time, across all 294 trades. That is now the third separate line of evidence
that `trade_ledger.timestamp` is the close — after the `exit_closes` join (126/294 at 5s) and the
`entry_mom` fill times (62% within 5 min). **The retraction stands on firmer ground than when it was
written.**

## 5. What this is not

**No verdict on whether a different width would do better.** This file describes what the bot did.
The comparison that would test the width needs the grid re-centred on 0.9–3.8% and run against the
same placebo machinery — and even then the live split is **not randomised**: the bot chose which
trades got which stop, so a raw width-vs-outcome comparison inherits exactly the selection problem
that killed the entry-timing study.

**Live trades, for context only:** win **36%**, SL-exit **42%**, mean net **−$0.67**.

## Limits
- **The match rate is 100%, which is suspiciously good** and worth stating plainly: it means every
  ledger trade has an event, not that every event is a ledger trade — 10,345 events are unmatched
  and most are not live.
- **One ground-truth row.** The cross-check is n=1 because only one trade has closed since the
  columns were added. It agrees to three decimals, but it is one row.
- **Stop width at entry only.** `stop_final` and any trailing adjustment are not in this measurement.
