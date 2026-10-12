# Mission Y: what we are not collecting that **disappears if we don't**

_2026-10-12. Owner, verbatim via the server: *"there is most definitely an extreme of abundance of
data for us to accumulate on."* Ranked by the only test that matters for a live collector._

---

## 0. The ranking principle, and why it demotes two obvious candidates

**A backfillable source does not need a live collector.** It needs a backfill script run once. So
the ranking is driven by one probed question — *can this be recovered later?* — not by how
interesting the data looks.

**I probed the Hyperliquid API rather than assuming:**

| source | recoverable later? | evidence |
|---|---|---|
| L2 depth (`l2Book`) | **NO** — snapshot only | returns levels for *now*, no history endpoint |
| **1h candles beyond ~208 days** | **NO** | a 1-year-back `candleSnapshot` returned **0 items** |
| 5m candles beyond ~17 days | **NO** | known expiry, cost us data once already |
| OI history | **NO** | `{"type":"openInterest"}` → **HTTP 422** |
| Liquidations | **NO** | websocket only, nothing serves history |
| Solana holder counts / pool state at a past moment | **NO** | GeckoTerminal serves *current* only |
| **funding history** | **YES, a year** | 500 rows returned from 1 year back |

**Two demotions follow, and one is a correction to my own earlier view:**

- **Funding is backfillable.** I paged a full year for all 178 perps today (506k rows). It needs
  **no live collector** — this was on the candidate list and should come off.
- **1h candles are NOT fully backfillable.** I had assumed they were. HL serves ~5,000 bars
  (~208 days) and nothing beyond. **So the 208-day panel already on this laptop cannot be rebuilt
  past 208 days** — it is already an irreplaceable asset, and j1/j5 keeping it is worth more than
  I had credited.

---

## 1. Tier 1 — build these. Un-backfillable **and** a study is already blocked on them.

| # | source | why it is the top tier | side | cost |
|---|---|---|---|---|
| **1** | **5m candles for ~60 coins** (now **6**) | **Expires in ~17 days.** Genuinely now-or-never, and the cheapest item on this page: **one `candleSnapshot` per coin per day**. 60 coins ≈ 60 calls/day, ~17k rows/day. The entire `INTRADAY_DISP` result rests on 6 coins; at 60 the cross-section stops being 0–5 ranks wide. | **laptop** (it is a pull, not a stream — j5 can do it) | trivial |
| **2** | **L2 depth for all 178 perps** (now **30**) | Un-backfillable, and it is the only thing that answers *reachability*. It refuted one of my own published premises within an hour of arriving. The 148 missing coins are exactly the small caps where fills actually bind. | **server** (already has the collector; widen the symbol list) | 178 calls / 15 min; ~17k rows/day |
| **3** | **Solana pool creation time + holder count at call time** | **This is the one with a study blocked on it right now.** Mission Z cannot use liquidity, FDV or holder count as call-time features because GeckoTerminal only serves them as of *today* — using them would be look-ahead. **Capturing them at call time is what makes Mission Z answerable at all**, rather than restricted to pre-call candles. | **server** (it sees the call as it happens) | one snapshot per call, ~7/day |
| **4** | **OI per coin at 15m** | HTTP 422 confirms no history exists. **Already being captured** in `ctx` for 178 coins — this entry is here to say *do not stop*, and that `PREREG_OI` depends on it accruing. | **server** (already running) | already paid |

---

## 2. Tier 2 — worth building after Tier 1

| # | source | value | side | note |
|---|---|---|---|---|
| 5 | **Market-wide trades / large prints** | Would measure impact **directly** instead of inferring it from depth, which is the weakest link in the small-cap fade. | server | `userFills` only serves a *known address*, so this needs the trades websocket, not the info API — I verified the info endpoint cannot substitute |
| 6 | **Liquidations beyond Bybit** | Bybit alone is one venue's view of a cross-venue event. Un-backfillable. | server | one more websocket per venue |
| 7 | **Cross-venue OI (Binance / Bybit)** | OI history is generally not served anywhere, so this is un-backfillable too; enables cross-venue basis work. **Their funding is backfillable — collect only the OI.** | server | small |
| 8 | **Vault + leaderboard positions over time** | Un-backfillable, but no study is waiting on it and `{"type":"leaderboard"}` returned HTTP 422, so the request shape needs finding first. | server | unknown until the endpoint is identified |

---

## 3. Tier 3 — do **not** spend a collector on these

| source | why not |
|---|---|
| **HL funding history** | Backfillable a year. Proven today. A script, not a collector. |
| **HL 1h candles** | Backfillable to the 208-day cap, which j5 already maintains. The *archive* matters; new live capture does not. |
| Anything derived | Realised vol, exp_move, ranks — all recomputable from the above. Never store a derivative in place of its input. |

---

## 4. Division of labour, and the RAM constraint

**Server ≈ 0.5 GB free, so every collector must stream to disk and buffer nothing.** The pattern
already working for `ctx_snapshots` — append a line per observation, gzip per completed day, never
hold a day in memory — is the one to copy. None of the Tier 1 items needs more than a few MB
resident.

- **Server = live capture.** It is always on and holds the websockets. Items 2, 3, 4, and Tier 2.
- **Laptop = backfill, permanent archive, and pulls that are not streams.** Item 1 (5m is a pull,
  so j5 should own it), plus permanent storage of everything the server captures — the server keeps
  30 days, the laptop keeps all of it, and `j6_archive` already does this for four streams.

**One structural note:** the laptop is now the only off-PC copy of the four archived streams, and
of a 208-day 1h panel that **cannot be rebuilt past 208 days**. That makes the laptop's disk a
single point of failure in the other direction. Worth a periodic copy somewhere else, which is a
question for the owner rather than something I should decide.

---

## 5. If only one thing gets built

**Item 1 — 5m candles for ~60 coins.** It is the cheapest (one call per coin per day), it is the
most urgent (a 17-day expiry means today's data is gone next month), and it directly widens the one
intraday result that is already well-powered. **Everything else on this page will still be
collectable next week; that one will not.**
