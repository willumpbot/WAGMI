# Mission 8 — start logging open interest today. One endpoint, four streams, three of them unrecoverable.

_2026-10-10. Ranked by days-to-a-resolvable-answer using dispersions measured in this project, not by
how interesting the source sounds. Answering `SERVER_REPLY.md` mission 8 — proposal only, nothing built._

---

## 🔴 The recommendation

**Add one collector: `metaAndAssetCtxs`, all perps, every 15 minutes.** It returns, per coin, in a
single call:

| field | what it is | has history? |
|---|---|---|
| **`openInterest`** | positioning | **NO — snapshot only** |
| **`premium`** | perp vs oracle | **NO — snapshot only** |
| **`impactPxs`** | order-book impact prices | **NO — snapshot only** |
| `dayNtlVlm` | 24h volume | yes (in candles) |
| `funding` | current funding | yes (`fundingHistory`) |

Verified: `openInterestHistory`, `oiHistory` and `historicalOpenInterest` all return HTTP 422, while
`fundingHistory` returns rows normally. **Three of those five streams cannot be backfilled. Every day
not logged is permanently gone.**

---

## Why open interest specifically, and not something more exotic

Mission 10 produced the project's first clean positive, and it came with a selection rule:

| flag | effect on next-day move | built from |
|---|---|---|
| `volume_surge` | **+12.5%**, t 2.07 | **volume — outside the forecast's features** |
| `funding_hot` | **+7.7%**, t 3.28 | **funding — outside the forecast's features** |
| `vol_expanding` | +1.2%, t 0.24 | `rv5`/`rv22` — **two of the three HAR inputs** |

**The two that carry information the forecast structurally cannot have both worked. The one built from
the forecast's own ingredients did nothing.** Open interest, premium and impact prices are all in the
first category — positioning and liquidity, not price history. That is the evidence-based reason to
pick them over another candle-derived indicator.

## The ranking

| rank | source | obs/day | days to a resolvable answer | status |
|---|---|---|---|---|
| **1** | **open interest + premium + impact pxs** | 60 | **70** | **not collected — and unrecoverable** |
| 2 | chief named levels | 86 | **16** | already emitting (165 so far) |
| 3 | funding + volume, top-60 | 60 | **hours** | **backfillable — fetch, don't wait** |
| 4 | scanner flag firings | 12 | 87 | running; `n≥300` floor now set |
| 5 | liquidation events (5m) | 60 | 100 | server archiving since 10-09 |
| 6 | full `l2Book` depth | 60 | 100 | not collected; heavier than #1 for less |
| 7 | owner trade plans | 0.43 | 191 | irreplaceable, but slow (`PLANS_NEEDED.md`) |

Days-to-answer uses the dispersions measured here: a +10% move effect on a log-ratio with the
cross-sectional sd from Mission 10, a 10-point rate gap against LEVELS.md's 37% null, +0.2R per plan
from `PLANS_NEEDED.md`, and the design effect `1+(m−1)ρ` with **ρ = 0.205**.

### Two items on that list are not actually waits

**#3 is a fetch, not a wait.** Funding and volume already have years of history, which is how Mission
10 got an answer today — on 17 coins. Widening to top-60 is one backfill run, not 70 days. **Do that
first; it costs an afternoon and roughly triples the sample behind the only positive finding in the
project.**

**#2 needs one column, not more time.** The chief already emits 86 levels/day. Part (a) of Mission 9 —
*does Opus add anything over HAR?* — is blocked purely because the expected move lives inside the
`read` prose instead of a numeric field. Export it and that test runs immediately.

## What I would not add
- **`l2Book` full depth (#6).** More bandwidth and storage than #1, slower to a conclusion, and
  `impactPxs` from the same call as open interest already gives the liquidity signal that matters at
  the owner's size.
- **Anything off-exchange** (social, news, on-chain flows). All of it needs a mapping layer to HL
  symbols, none of it is free at useful frequency, and the two things that have actually worked here
  came from the exchange's own non-price fields. Exhaust those first.
- **More candle-derived indicators.** `vol_expanding` is the cautionary case: +1.2% because it is
  built from the forecast's own inputs. Any new indicator computed from OHLC is at risk of the same
  redundancy.

## Trader rules — one number each
1. **Open interest is the next real data source, and it expires.** No history endpoint — **70 days**
   of logging gets an answer, and every unlogged day is lost forever.
2. **Non-price data is where the edge has been.** The two flags built from volume and funding moved
   the needle **+12.5%** and **+7.7%**; the one built from price history moved it **+1.2%**.
3. **One call covers it.** `metaAndAssetCtxs` returns all five streams for every perp — a single
   15-minute collector, not five integrations.

## Limits
- Days-to-answer assumes effects of the size Mission 10 found (+8% to +12%). A smaller true effect
  scales the days up by the square of the ratio — halve the effect, quadruple the wait.
- ρ = 0.205 is measured on the bot's signal panel, not on an OI cross-section. If OI is more
  synchronised across coins than returns are, the design effect is worse and #1 takes longer.
- I have not verified that `impactPxs` is populated for thin coins; worth a one-day check before
  building the collector around it.
- Nothing here is built, per the mission. The collector is ~20 lines and the storage is trivial
  (60 coins × 96 snapshots/day ≈ 5,760 rows/day).
