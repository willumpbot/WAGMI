# 🔴 Laptop → server — **the `archive/` export stopped 26h ago (liq_events, market_depth, whales, voices) while `bulk/` and `ctx` kept flowing.** Export or collectors? If collectors, `whales` is losing days it can never get back.

## 1. What I can see, and what I cannot

| stream | latest row I hold | age |
|---|---|---|
| `ctx` (OI panel) | 2026-10-12 21:51 | **0.4 h — live** |
| `liq_events` | 2026-10-11 23:53 | **22.3 h — stale** |
| `depth` | 2026-10-11 23:52 | **22.4 h — stale** |
| `whales` | 2026-10-11 23:50 | **22.4 h — stale** |

**All three stopped within three minutes of each other**, which is one shared failure rather than three.

**And the source side localises it:** `server_exports/archive/{liq_events, market_depth, whales, voices}`
were all last written **2026-10-11 20:08**, while `server_exports/bulk/` wrote at 22:10 and `ctx` is
current. **So the `archive/` export path specifically stopped; `bulk/` and `ctx` did not.**

**What I cannot tell from here is whether your collectors are still running and only the export
broke.** If it is just the export, nothing is lost and it will catch up. **If the collectors are
down, this is permanent** — and per my own rule I am not calling a gap a failure without checking,
so this is a question, not an accusation.

## 2. 🔴 Why it is urgent for two of the four

**`whales` has four days of history, total** (2026-10-08 → 10-11). **`depth` and `liq_events` both
show a prior 24-day hole** (2026-08-13 → 09-05) where `candles_1h` is complete — so these collectors
have gone down before and nobody noticed for weeks.

**26 hours on a four-day-old stream is a quarter of everything we have of it.** Your `stop_shadow`
and the OI panel are proof that starting a logger pays; a logger that dies silently is the same loss
in reverse.

**Suggestion, cheap:** the `listener_heartbeat.json` pattern you built for the Telegram listener,
applied to the archive collectors — `{stream, last_write, rows_today}` — so staleness is visible
without someone running a query.

## 3. Sweep finding while I am here: `liq_events` is weaker than its row count suggests

The first agent came back. **71,816 rows is 46 day-clusters.**

| | |
|---|---|
| **`venue` is constant = `bybit`** | **so every question off this stream is a cross-venue claim** (Bybit liqs → HL moves), not same-venue. This was not obvious and changes how any prereg must be worded. |
| distinct days / cells | **46 days**, 425 (symbol, day) cells — but BTC+SOL are 76% of rows and 93% of notional, and the 9 alts co-move, so the honest figure is **~46** |
| missing days | **26 of 72**, incl. a contiguous 24-day hole where candles are complete |
| instrumentation break | **2026-10-08**: 9 symbols → 13. Counts are not comparable across it |
| within-day truncation | BTC median worst intra-day gap **105 min**; 6 of 46 days have under 12 hours of BTC coverage. **Raw daily counts partly measure collector uptime**, so everything needs per-covered-hour normalisation |
| `ctx` overlap | **2 of 46 days** — liq × OI is not testable yet, it needs the OI panel to age |
| clean joins | `depth` **46/46** and `funding_hist` **46/46** (the latter with a year of history) |

**So I am not proposing a liq-based study as a priority.** 46 clusters resolves less than the 83-cluster
studies that already came back underpowered. **The best thing in this stream is its join to `depth`**
(46/46, direct symbol match) for a *market-structure* question — does a liquidation burst predict
next-day spread/depth deterioration — which is a sizing input the bot could actually use, and not a
direction claim.

Three more agents are still characterising `whales`, `depth` and the `ctx`/OI panel. **Full ranked
sweep follows when they land**; I am not going to seal anything off one stream.
