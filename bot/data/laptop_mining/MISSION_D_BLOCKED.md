# Mission D cannot be done on historical trades. ⏳ And the data needed is being lost every day — start archiving today.

_2026-10-10. Verified blocker report, not an excuse. Two independent causes, both tested with controls._

---

## 🔴 The blocker

Mission D is "port the bot's real exit engine and replay it." The real engine
**"runs on the bot's price updates each scan (~3 min cadence, last trade price)"**
(`README_DATA_RESPONSE.md` §2). To replay that faithfully I need sub-hourly candles and the position's
original stop and targets. **Neither exists for the trades that matter.**

### Cause 1 — 5m candle history expires after ~17 days. Verified with a control.

I requested BTC 5m for five narrow windows. Same request shape, only the date changes:

| requested window | 5m result | 1h result (control) |
|---|---|---|
| 2026-06-10 *(the trail era)* | **EMPTY** | 25 bars ✓ |
| 2026-07-10 | **EMPTY** | — |
| 2026-08-10 | **EMPTY** | — |
| 2026-09-10 | **EMPTY** | — |
| 2026-09-25 | 289 bars ✓ | 25 bars ✓ |

**The API serves 1h back to May and 5m only ~17 days.** A paginated fetch from 2026-06-01 returned
4,744 bars starting 2026-09-23 — it silently ignores an older `startTime`. Consequence:

- **23 of the 24 trailing positions have no 5m candles, and never will.** One is inside the window.
- **8 of 235 trades (3%) are replayable at 5m.** The other **227 are permanently out of reach.**

This is the **second** instance of the "data that expires" class, after the open-interest finding —
same shape, same fix.

### Cause 2 — the stop and target levels were never logged.

`README_DATA_RESPONSE.md` already says so: *"stop_px_initial / stop_px_final are NOT logged as columns
(honest gap)."* I checked every export for a recoverable substitute:

| source | stop/target fields | usable for the 24? |
|---|---|---|
| `trades.csv` | entry, exit only | no |
| `trade_ledger.csv` | **none** | no |
| `position_journal.jsonl` (3,102 legs) | **none** | no |
| `exit_decisions.jsonl` | `position_sl` (the *current* stop), `position_tp2` | **0 of 24 positions match** |

**`tp1` does not appear in any export.** It is the single most important level for this engine, since the
trail arms only after TP1. And the trailing positions appear in `exit_decisions.jsonl` **zero** times, so
even the mutated-stop path is unavailable for them.

Your new `stop_initial` / `stop_final` columns fix this **from the next close on** — which is exactly right,
and it is why the recommendation below is about *forward* capture, not recovery.

---

## ⏳ Urgent: three things to start capturing today. The cost of waiting is irreversible.

Every day that passes, one more day of 5m candles is **gone permanently**. This is the rare
recommendation where delay has a hard cost, so it is worth doing before anything else on my list.

1. **Archive 5m candles continuously for the traded symbols** — a ~15-min cron appending to disk, same
   shape as the OI collector you already built. At 6 symbols × 288 bars/day this is trivial in size
   (~2 MB/month) and it is the only way Mission D ever becomes possible. **17 days is the whole buffer.**
2. **Log `tp1` alongside the new `stop_initial`/`stop_final`.** The trail arms only after TP1; without it
   the engine cannot be driven at all. One field.
3. **Add `position_id` to `exit_decisions.jsonl`** — still asking. `llm_exits_resolved.jsonl` has the field
   but it is the empty string on all 29 rows, so identity is still (symbol, rounded entry).

With those three running, **Mission D becomes answerable in ~3–4 weeks** on forward trades, at a fidelity
(5m, real levels, real stop paths) that would make it the first exit result in this project not resting on
a resolution convention. Without them it stays impossible indefinitely.

## What I am NOT going to do

**I am not running it on 1h bars and reporting a number.** The refuted trailing study died because a
resolution convention quietly chose the answer, and a 3-minute engine simulated on 60-minute bars is that
same error with better paperwork. I would rather hand you a blocked mission than a twelfth reversal.

I am also **not** inventing the missing TP1 from a tp1/tp2 ratio. That would make the arming time — the one
thing the whole engine hinges on — a parameter I chose.

## What I can do meanwhile, and will
- **Write the engine now, with the three fixes baked in** (hard stop always live, trail evaluated against
  the current bar's own extreme under neutral ordering, gap-aware fills), plus self-tests that prove the
  tighten curve and profit-lock floor match §2 of your spec. It then runs the day the data exists.
- Because the spec says the engine sees **last trade price per scan, "bar-close-like, not ticks"**, the
  faithful evaluation is **close-only**, not high/low. That is a convention I can justify *from your spec*
  rather than choosing — and I will still report the high/low orderings as the pessimistic and optimistic
  edges of the band, as you asked.
