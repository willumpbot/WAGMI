# Micro-Cap / Solana Meme Data Recon

**Date:** 2026-08-06. **Status:** read-only recon, no live-bot changes, no Discord, no trading. Companion script: `tools/copilot/microcap_recon.py` (re-runnable, prints live probe results; see it for the exact evidence behind every claim below).

**Mission:** scope whether we can acquire usable micro-cap / Solana meme data to test — and eventually trade — the thesis that edge lives in the thin, less-efficient tail that Hyperliquid mid-cap data can't reach (owner trades $KITTY, $POPCAT; pointed at DexScreener + "the FOMO app").

**Headline verdict:** DexScreener is confirmed reachable but is **snapshot-only** — it is not the historical-data source. **GeckoTerminal's free on-chain API is the real find**: genuine OHLCV candles, no key required, down to 1-minute bars — but hard-capped at a rolling **180-day** window. For the owner's actual coins (POPCAT, WIF-style memes that are >180 days old) that means partial history only; for the freshly-launched micro-caps the thesis is actually about, 180 days covers their *entire life*, so real backtesting — not just forward-collection — is possible for the target universe. The FOMO app is a walled-garden consumer app with no public API; don't touch it.

---

## 1. What's reachable, and what each API actually gives you

| Source | Reachable? | Auth | Historical candles? | Rate limit (confirmed) |
|---|---|---|---|---|
| **DexScreener** `api.dexscreener.com` | Yes, live-tested | None | **No.** Snapshot + 4 rolling windows only (m5/h1/h6/h24) | 60 req/min (per docs.dexscreener.com/api/reference, all 13 documented endpoints) |
| **GeckoTerminal** `api.geckoterminal.com/api/v2` | Yes, live-tested | None | **Yes — real OHLCV**, day/hour/minute, `aggregate` param for custom bar sizes | 30 req/min (documented + reproduced live: hit HTTP 429 after ~7-8 rapid calls) |
| **Jupiter Token API v2** `lite-api.jup.ag` | Yes, live-tested | None | No — live snapshot + rolling stats only | Not disclosed via headers; no 429 hit in light testing |
| **Birdeye** `public-api.birdeye.so` | Reachable, but 401 on every endpoint without a key | **Required** (not tested further — out of scope for anonymous recon) | Unknown from this probe (Birdeye's docs claim deep OHLCV, but this wasn't verified live since it needs signup) | N/A |
| **pump.fun** `frontend-api-v3.pump.fun` | Reachable (HTTP 200) | None enforced, but **undocumented internal API** | Presumably yes (bonding-curve trade data), not investigated further | Unknown — no public docs exist, so no stated ToS or limit to respect |
| **FOMO app** `fomo.family` | Homepage reachable; `docs.fomo.family` / `api.fomo.family` **do not resolve** | N/A | N/A | N/A — no public API found |
| Bitquery / Moralis | Not tested | Requires a key | N/A | Out of scope — no free-anonymous path, deprioritized |

### DexScreener detail

Confirmed working endpoints: `/latest/dex/search?q=`, `/tokens/v1/{chain}/{address}`, `/token-boosts/latest/v1`, `/token-boosts/top/v1`. A live POPCAT pull returns: `priceUsd`, `priceNative`, `liquidity.usd`, `volume.{m5,h1,h6,h24}`, `txns.{m5,h1,h6,h24}.{buys,sells}`, `priceChange.{m5,h1,h6,h24}`, `fdv`, `marketCap`, `pairCreatedAt` (pair-age timestamp — useful), and socials/links. Fetched `docs.dexscreener.com/api/reference` directly and confirmed: **"the documented API does not expose a dedicated historical OHLC/candle endpoint."** DexScreener's website *shows* a chart, but that chart is not served by the public API — it's an internal endpoint DexScreener doesn't document or support for third parties. Do not reverse-engineer it; that's the "sketchy scraping of a walled feature" the mission explicitly ruled out.

**Verdict on DexScreener: best used as a live snapshot/monitoring/universe-discovery layer (liquidity, volume, age, socials), never as a candle source.**

### GeckoTerminal detail — the actual find

`api.geckoterminal.com/api/v2` is CoinGecko's on-chain-data API, free, no key, and it is a *real* OHLCV provider:

- `GET /networks/solana/pools/{address}/ohlcv/{day|hour|minute}?aggregate=N&limit=1000` returns arrays of `[timestamp, open, high, low, close, volume]`. Tested `aggregate=1` on day/hour and `aggregate=5` on minute — all worked, real distinct OHLC values, not just repeated last-price snapshots.
- **Hard cap confirmed live, not assumed**: paginating backward via `before_timestamp` on POPCAT's pool (created Dec 2023) returned 181 candles, then 184 more, then **HTTP 401**: `"You can only access data from the past 180 days with Public API. To access data beyond 180 days, please upgrade to the Analyst plan or above."` So today (2026-08-06) the free tier gives POPCAT's daily candles back to ~2026-02-08 — a rolling window, not a fixed start date. Anything older requires CoinGecko's paid Analyst plan.
- `GET /search/pools?query=X&network=solana` resolves a symbol/name to its pool address (needed since OHLCV is keyed by pool address, not symbol).
- `GET /networks/solana/trending_pools`, `/networks/solana/new_pools`, and — critically — `GET /networks/solana/dexes/{dex_id}/pools` (dex ids include `pump-fun`, `pumpswap`, `raydium`, `moonshot`, `bags-fm`, `boop-fun`, and ~25 others) enumerate current pools per venue, including bonding-curve-stage pump.fun tokens that haven't graduated to an AMM yet.
- `GET /networks/solana/pools/{address}/trades` returns individual recent trades (buyer/seller wallet, side, USD size, tx hash) — useful for wash-trade forensics (see §4).
- Rate limit: publicly documented at 30 requests/minute (confirmed via CoinGecko's own support article) and reproduced live — a burst of rapid pagination calls 429'd almost immediately; a ~2.5s gap between calls stayed under it in later tests.

**Critical positive finding on survivorship (see §4a for full discussion): a pool that is already dead right now (found one live with `reserve_in_usd: 0.0`, launched ~18 hours prior) still returns its full OHLCV history.** GeckoTerminal indexes at the on-chain pool level; death does not erase history. The only thing that's perishable is *discovery* — `new_pools`/`dexes/{id}/pools` are rolling "what's out there right now" listings, not a historical launch log, so a coin that launched and died before we ever queried is not retroactively discoverable by name/search (unless it's well-known enough to still be findable, like an ex-hyped rug).

### Jupiter Token API v2 detail

`lite-api.jup.ag` (the old `price.jup.ag` v4/v6 hostnames are dead — DNS doesn't resolve, so any historical guide referencing those URLs is stale):

- `GET /price/v3?ids={mint}` — live price, 24h change, liquidity, `createdAt`. No history.
- `GET /tokens/v2/search?query=` — rich live snapshot: `holderCount`, `mcap`, `fdv`, `liquidity`, and per-window (`stats5m/1h/6h/24h`) `buyVolume`/`sellVolume` **alongside** `buyOrganicVolume`/`sellOrganicVolume`, `numBuys`/`numSells`, `numTraders`, `numOrganicBuyers`. This organic/total split is Jupiter's own anti-wash-trading classification, exposed as raw numbers.
- `GET /tokens/v2/toporganicscore/{interval}` — ranks tokens by that same organic signal; a ready-made low-wash universe filter.
- `GET /tokens/v2/recent` — literally the newest tokens on Jupiter's radar, some with `holderCount: 1`, seconds old. Good for catching a launch cohort before it's even indexed by DexScreener/GeckoTerminal's "new pools" (Jupiter routes through Solana RPC directly and picks things up fast).
- **No historical OHLC anywhere in v2.** Jupiter is a live-price/liquidity-routing API, not a data warehouse.
- Live data point worth internalizing: **POPCAT's own 24h organic-buy ratio came back at 10.0%** (`buyOrganicVolume $14.4k / buyVolume $144.8k`) — i.e. even an established, liquid, 2.5-year-old meme coin shows ~90% of Jupiter-classified "non-organic" (bot/wash/MEV-adjacent) buy flow by this metric. Take that as the realistic baseline, not an alarming outlier — see §4b.

### Birdeye, pump.fun, FOMO app

- **Birdeye**: every endpoint tested (`defi/price`, `defi/history_price`) returned `401 Unauthorized` with no key. Birdeye's own marketing claims the deepest Solana OHLCV history of any of these, but that's unverified here — getting one would mean creating an account (a step beyond "anonymous read-only recon"), and it's a gate the report should flag rather than quietly cross. Worth doing as a **follow-up** task if GeckoTerminal's 180-day cap becomes the binding constraint.
- **pump.fun** `frontend-api-v3.pump.fun/coins` returned HTTP 200 with real live coin data on a plain unauthenticated GET. This is real but it is **not a documented public API** — no ToS, no rate-limit guidance, no stability guarantee, and it's the backend for pump.fun's own frontend. Per the mission's own guardrail ("no sketchy scraping of walled apps"), this should not be built on directly. The good news is it's largely redundant: GeckoTerminal's `dexes/pump-fun/pools` endpoint above already surfaces the same bonding-curve-stage tokens through a documented, public, rate-limited API.
- **"The FOMO app"** (fomo.family) is a consumer/social memecoin trading app — mobile-first, Solana + Base, $17M Series A (Benchmark, Nov 2025), ~120k users, reported $20-40M/day volume, feed-style "see what your friends are buying" UX. `docs.fomo.family` and `api.fomo.family` do not resolve — there is no discoverable public API. It almost certainly routes trades through Jupiter's aggregator under the hood (as most Solana consumer trading apps do), meaning the market data FOMO's users see is, functionally, the same on-chain liquidity we can already reach directly via GeckoTerminal/Jupiter. **Verdict: don't scrape or reverse-engineer FOMO's app; there's nothing there we don't already have a documented path to.**

---

## 2. Real history vs. forward-collect

This is not a binary answer — it depends on which coins:

- **Coins younger than 180 days at query time** (i.e., most of the actual "thin tail" micro-cap universe the thesis targets — fresh launches): GeckoTerminal's free tier gives their **entire life's OHLCV history**, for free, right now, at day/hour/minute granularity. This is real, retroactive, high-fidelity history — not forward-collection. A backtest over "coins that launched in the last 6 months" is buildable **today** with no waiting period.
- **Coins older than 180 days** (POPCAT since Dec 2023, most established cat coins the owner already holds): free tier gives only the trailing 180-day window. Full multi-year history would need CoinGecko's paid Analyst plan, or Birdeye with a registered key (unverified depth), or accepting a shorter lookback.
- **Universe discovery for coins that already died before we started watching**: NOT retroactively possible through any of these APIs. `new_pools`/`dexes/{id}/pools`/DexScreener's boosted lists are rolling, current-state windows — there is no "give me every pump.fun token that ever launched, including the 98%+ that died on the bonding curve" endpoint. This is the one piece that is genuinely un-backfillable and matches the `liq_collector.py` precedent: **the clock starts when we start polling.**

**Practical framing**: this is *better* than the liquidation-collector case, not equivalent to it. There, the event itself vanishes forever if not captured live. Here, once we've captured a pool *address* (via any discovery pass, even a single one), its full price history is retroactively available and durable — confirmed live on an already-dead pool. So the actual forward-collection burden is narrow and well-defined: **run address discovery frequently enough to catch launches before they're gone from the rolling "new"/"trending" lists** (pump.fun alone launches on the order of 10-20k tokens/day per third-party reporting — Odaily/Bitget's "1.4% graduation rate" writeups). Once an address is on file, OHLCV backfill is a solved, retroactive problem.

---

## 3. Defining a tradeable micro-cap universe

A concrete, buildable definition, tiered by intent:

**Tier A — "cat coins the owner actually holds/watches"**: hand-maintained mint-address list (POPCAT confirmed: `7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr`; $KITTY and others to be added the same way — resolve via DexScreener `/latest/dex/search?q=SYMBOL`, cross-check the resolved mint against the coin's own socials/website before trusting it, since symbol collisions on Solana are common and a wrong mint = wrong data silently). This tier needs no discovery machinery — GeckoTerminal history + DexScreener/Jupiter live snapshot is sufficient today.

**Tier B — "systematic thin-tail universe" (the actual research target)**: define membership by *simultaneous* thresholds, not any single stat (single-metric filters are exactly how dust/rugs slip through):
- Chain: Solana only (matches owner's stated focus and avoids fragmenting effort across chains with different liquidity/MEV dynamics).
- Liquidity: `$15k – $2M` in `liquidity.usd` (DexScreener) / `reserve_in_usd` (GeckoTerminal). Floor excludes pure dust where a single $50 buy moves price 10%; ceiling roughly separates "still-thin" from "already-a-mid-cap" (POPCAT itself sits at ~$2.9M liquidity, useful as an upper anchor of what "thin" is not).
- Age: pool created `>= 24h` ago (skip the first day's pure noise/rug-detection window) and `<= 180d` ago (keeps it inside GeckoTerminal's free history window end-to-end — no partial-history coins in the study set).
- Volume: `24h volume >= $10k` and `volume/liquidity` ratio within a sane band (e.g. 0.2x–20x) — both too little (dead) and too much relative to liquidity (likely wash, see §4b) should exclude a candidate.
- Organic filter: Jupiter `buyOrganicVolume/buyVolume >= some_floor` (needs calibration against a labeled set — see §4b; POPCAT's own 10% is the realistic baseline for an established meme, so the floor should be tuned relative to peers, not to an absolute "should be >50%" assumption that nothing here would pass).
- Holder count floor: `holderCount >= 200-500` (Jupiter) as a crude anti-single-wallet-pump filter.

**Enumeration mechanism**: poll GeckoTerminal `new_pools` + `dexes/{pump-fun,pumpswap,raydium,moonshot,bags-fm,boop-fun}/pools` + Jupiter `tokens/v2/recent` on a schedule (e.g. every 15-30 min, well under the 30/min GT cap when batched sensibly), log every discovered `(mint, pool_address, dex, first_seen_liquidity, first_seen_ts)` — this is the "start the clock" list. Membership in Tier B is then evaluated retroactively against that log using GeckoTerminal OHLCV, which — per §2 — works even for pools that have since died.

---

## 4. The brutal-honest integrity assessment

**(a) Survivorship bias — real, but partially mitigable, and asymmetric by question.**
If the question is "what's the historical performance of a broad micro-cap universe assembled by searching for coins *today*," the answer is severely survivor-biased: search/trending endpoints surface what's currently alive or was hyped enough to still be findable — the ~98.6% of pump.fun launches that died on the bonding curve without graduating (Odaily/Bitget reporting a 1.4% graduation rate) are essentially invisible to a name-based search done after the fact. **But** this project confirmed live that GeckoTerminal does NOT purge dead pools from its own index once a pool address is known (a `$0`-liquidity, day-old bonding-curve pool still returned its OHLCV). So the bias is specifically in *discovery*, not in *retention*. Verdict: **a backtest built from coins discovered via retrospective search is survivor-poisoned and should not be trusted for edge claims; a backtest built from a forward-running discovery log (even a short one) is not survivor-biased for the population it actually observed.** This is the load-bearing reason forward address-discovery has to start now regardless of what else gets built.

**(b) Wash trading / fake volume — real, and this API surface gives an actual measurement tool, not just a warning.**
Jupiter's organic-vs-total volume split is a genuine, live, per-token signal, not something that needs to be built from scratch. The concerning part is the calibration baseline: POPCAT — an established, real, liquid meme with a 2.5-year track record — showed a 10% organic-buy ratio *by Jupiter's own classification*. If a mature, "real" coin scores that low, a naive "require >50% organic" filter would exclude nearly everything, including the coins the owner already trades. This means the useful signal is **relative** (rank candidates against a peer baseline, or watch for *sudden drops* in organic ratio as a live wash/manipulation alarm) rather than absolute. Secondary check: GeckoTerminal's raw `/trades` endpoint (wallet-level buy/sell records) lets you compute classic wash-trading tells directly — same wallet buying and selling itself, unusually round trade sizes, trade clustering in sub-second bursts — but that's meaningful forensic work, not a quick filter, and hasn't been built here.

**(c) Slippage / MEV / priority fees — not measured by any of these APIs, and this is the sharpest edge-eraser risk.**
None of DexScreener/GeckoTerminal/Jupiter's *price* endpoints reflect what a real market order would actually fill at on a $20k-liquidity pool. Jupiter's own `/quote` endpoint (not probed here — it's a live quote for a hypothetical trade, not a data endpoint, and calling it repeatedly to reconstruct historical slippage isn't meaningfully possible after the fact) is the only source that would show realistic fill prices, and only for trades happening *now*. A backtest driven by close-price OHLCV on a thin pool is systematically optimistic: it assumes fills at a price that a real order of any meaningful size would move through. On a $15-50k liquidity pool (the low end of the Tier B band above), a $500-1000 order is plausibly a 2-5%+ round-trip cost before counting Solana priority fees (which spike hard during meme-coin mania — this is well documented network behavior, not tested here) and MEV sandwich risk on public mempool-adjacent routing. **This is the single biggest reason a backtested "edge" on this data should be treated as a hypothesis, not a result**, until it's checked against Jupiter's live quote API for realistic size-vs-slippage curves on the actual liquidity bands being traded.

**(d) Price manipulation / thin-book artifacts.**
Directly observed in this recon: candle wicks on the freshly-launched dead pool tested in §1 swung from a low of `2.34e-6` to a high of `2.86e-5` within a single hour bar (>10x range) on a pool that had already gone to $0 liquidity — i.e., the "high" of that candle is likely one manipulated/panic trade against an already-drained book, not a tradeable price. Any strategy back-tested against raw OHLCV highs/lows on thin pools without a liquidity-at-time-of-candle sanity check will be trading fantasy prices. Cross-referencing `reserve_in_usd` (GeckoTerminal) or `liquidity.usd` (DexScreener) *at the time of each candle*, not just at query time, is a hard requirement for any backtest — and note that liquidity history itself is not directly given by an OHLCV endpoint, so this needs its own reconstruction (e.g., from `/trades` records, or forward-collected snapshots).

**(e) "FOMO app."** Covered in §1: consumer walled garden, no public API, not scraped, likely just a Jupiter-routed front-end anyway. Not a data source; not a concern beyond "don't try."

**Bottom line on trustworthiness**: a backtest restricted to (i) coins discovered via a forward-running address log (not retrospective search), (ii) within GeckoTerminal's 180-day real-history window, (iii) with liquidity-at-candle-time cross-checked against the price series, and (iv) treated as a *slippage-naive upper bound* rather than an achievable P&L — is honest and buildable. A backtest that skips any of those four qualifiers is not trustworthy for an edge claim, however good the headline numbers look. **Forward-collection is not the only honest path here** (unlike the liquidation case) **because retroactive history genuinely exists for the target age band** — but forward-collection of *discovery* is still mandatory to avoid survivorship, and slippage/wash checks are still mandatory to avoid a fantasy-fill backtest.

---

## 5. Recommended collection plan

1. **Discovery log (start now, cheap, forward-only-because-it-must-be)**: a lightweight poller (new module, same isolation contract as `liq_collector.py` — read-only, writes only under `data/copilot/microcap/`) hitting GeckoTerminal `new_pools` + `dexes/{pump-fun,pumpswap,raydium,moonshot,bags-fm,boop-fun}/pools` and Jupiter `tokens/v2/recent` every 15-30 min, appending `(mint, pool_address, dex, discovered_at, liquidity_at_discovery)` to a jsonl log. This is the entire fix for §4a's survivorship problem, and it's cheap (well under both APIs' rate limits at that cadence).
2. **Retroactive OHLCV backfill**: for every address in the discovery log (and for the owner's Tier A hand-list), pull GeckoTerminal daily+hourly OHLCV once, then top up periodically. Respect the 30/min cap (a ~2.5s gap between calls, as used in `microcap_recon.py`, stays comfortably under it).
3. **Liquidity-at-candle-time reconstruction**: alongside OHLCV, log `reserve_in_usd`/`liquidity.usd` on the same poll cadence as step 1 for every tracked pool, so every historical candle can be tagged with contemporaneous liquidity — this is what makes §4d's thin-book-artifact check possible after the fact instead of only in hindsight commentary.
4. **Wash/organic tagging**: pull Jupiter `tokens/v2/search` per tracked mint on the same cadence, log the organic-vs-total volume fields, and build the peer-relative baseline described in §4b before using it as a hard filter.
5. **Fields to log per pool per snapshot**: `mint, pool_address, dex_id, price_usd, liquidity_usd, fdv, mcap, volume_{m5,h1,h6,h24}, buys/sells counts, holder_count, buyVolume/buyOrganicVolume, sellVolume/sellOrganicVolume, pool_created_at, snapshot_ts`.
6. **Explicitly deferred / not recommended yet**: Birdeye key registration (only worth it if the 180-day GT cap becomes binding for a specific analysis); pump.fun's undocumented API (redundant with GT's `pump-fun` dex listing); any FOMO app access (no path exists); actual trading (needs a funded Solana wallet + Jupiter swap integration — pure scope note, not built, not requested).
7. **Gate before anything trades**: no backtest result from this data should move toward live/paper trading without (a) the slippage-naive-upper-bound caveat explicitly attached, and (b) a spot-check against Jupiter's live `/quote` endpoint for realistic fill cost at the position sizes actually being considered — this project's own "backtest before adding" and "validate each new symbol" precedents apply at full force here, arguably more so given how much thinner and more manipulable this data is than the Hyperliquid mid-caps already in use.
