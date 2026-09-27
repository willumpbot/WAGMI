# WAGMI Co-Pilot — Micro-Cap / Solana Meme Campaign Plan

**Created:** 2026-08-06. Status: PLAN ONLY — no test has been run under this
document, no code has been written against it, no Discord, no live/paper
trading changed. Read-only design, exactly like `tools/copilot/
CONFLUENCE_CAMPAIGN.md` before its batches were built. This document reuses
that campaign's OOS/FDR/refute-yourself discipline (Part A there) but is
**not a port** — Part A below is rebuilt from scratch around three facts
that don't exist in the Hyperliquid mid-cap corpus: (1) the population of
coins is not fixed or survivor-safe by default, (2) a large fraction of
observed volume is fabricated, and (3) a "backtest" on this data cannot use
its own historical fills — GeckoTerminal/DexScreener/Jupiter never recorded
what a real order would have paid.

**Why this campaign exists:** `CONFLUENCE_CAMPAIGN.md` tested confluence and
regime-conditioning on the 25-coin Hyperliquid longtail universe and found
it **null** — isolated and combined mechanical signals alike. That corpus is
already efficient enough (algo-covered, arbitraged, $1M+/day volume floor)
that mechanical technical patterns don't survive contact with test data.
The owner's actual arena — pump.fun/Raydium/PumpSwap Solana cat/meme
coins, $15k-$5M liquidity, days-to-months old — is a genuinely different
statistical environment: thinner, less-watched, more manipulable, and
subject to dynamics (bonding-curve graduation, organic-vs-wash flow,
holder-count mania, liquidity-add/rug cycles) that have no analogue in a
liquid perp market. This document designs the hypothesis space **native**
to that environment and locks a methodology strict enough that a finding
here means something, given how easy this specific data is to fool yourself
with (see `data/microcap/INTEGRITY_NOTES.md` — every caveat there is
load-bearing).

**Data on hand** (see `tools/copilot/MICROCAP_DATA_RECON.md` for full
recon): GeckoTerminal OHLCV (day/hour/minute, 30 req/min, 180-day rolling
cap, does not purge dead pools once an address is known), DexScreener
liquidity/volume/txn snapshots (4 rolling windows m5/h1/h6/h24, no history),
Jupiter organic-vs-total volume + holder count (live snapshot only, no
history). Collector (`tools/copilot/microcap_collector.py`) is running and
writing `data/microcap/{discovery_log,liquidity_snapshots,wash_signal}
.jsonl` plus `universe.json` (Tier A named, Tier B systematic
forward-discovered, Tier B established current-state-screened). As of this
writing: 397 discovery-log rows (mostly $0-liquidity newborns, per
`INTEGRITY_NOTES.md` §4b), 49 liquidity/wash snapshots (2 named coins,
Tier A only so far), Tier B established = 20 coins.

---

## Part A — Locked Methodology (the micro-cap integrity ceiling)

Every hypothesis in Part B, when eventually run, MUST be tested through
this exact procedure. This is stricter than `CONFLUENCE_CAMPAIGN.md`'s
Part A in four specific places (A1b survivorship-track split, A1c wash
filter, A1d slippage-honesty, A1e liquidity-at-time) because this data can
be fooled in ways HL OHLCV cannot.

### A0. Success criterion — small, spot, real-cost-positive, forward-honest

The target is the same accumulation-style bar as `CONFLUENCE_CAMPAIGN.md`
A0 (unlevered, small, consistent, positive-after-real-cost expectancy;
hit-rate; holding period), narrowed for this venue:

- **Position frame:** a spot buy on a DEX (Jupiter-routed swap), no
  leverage exists in this venue the way it does on Hyperliquid — so "risk
  of ruin from leverage" is not the threat model here; **execution cost
  and rug/wash risk are**. Score every hypothesis on (1) mean
  **net-of-realistic-DEX-cost** return, using the reference position size
  and cost table in A1d below (never a flat bps assumption), (2) hit-rate,
  (3) holding period, (4) worst-case single-episode loss (a rug can lose
  90%+ in one candle — this must be shown, not averaged away by a mean).
- **Reference position size, stated explicitly:** $200-$1,000 per
  position — anchored to the owner's own actual live-bot trade-size reality
  (median notional collapsed to ~$278 on the HL bot per prior project
  findings), not a hypothetical institutional size. A hypothesis's cost
  hurdle (A1d) and slippage estimate must be computed at THIS size, because
  price-impact on a thin pool is size-dependent — a hypothesis validated
  against a $50 test trade says nothing about a $500 one.
- **A survivor is a CANDIDATE for small forward paper/live sizing, never a
  claim of edge** — this carries even more force here than in
  `CONFLUENCE_CAMPAIGN.md` A7, because unlike HL OHLCV, this data cannot
  even in principle reconstruct a real fill price (A1d).

### A1a. Entry-time-safe, no look-ahead

- Every signal must be computable from data timestamped at or before the
  decision point. For GeckoTerminal OHLCV, use the last CLOSED bar at the
  chosen granularity (day/hour/minute) — never a still-forming bar, same
  discipline as `copilot.py`'s `settled_close` fix (the 2026-08-01
  correction in `PREREGISTRATION.md`).
- For DexScreener/Jupiter rolling-window fields (`volume.h1`,
  `buyOrganicRatio_24h`, `holderCount`, ...): these are **live snapshot
  fields with no historical API**. Any hypothesis using them can ONLY be
  computed at the moment a snapshot was actually polled — there is no way
  to reconstruct "what was `volume.h1` three weeks ago." This is the
  central reason most of Lenses 3/4/5's hypotheses in Part B are
  FORWARD-ONLY (Part C) rather than HISTORY-testable: the fields don't
  exist in the past, only from the moment the collector started polling
  them forward.
- Rolling/trailing indicators (liquidity growth rate, organic-ratio trend,
  holder-count velocity) must use only snapshots strictly before the
  decision timestamp, and must be computed against the coin's OWN trailing
  baseline (never a fixed absolute threshold — see A1c).

### A1b. Survivorship — HISTORY track vs FORWARD track, never blended

This is the single most important structural rule for this campaign,
tighter than anything in the HL confluence work because the underlying
population here is NOT fixed:

- **HISTORY track**: any hypothesis tested against GeckoTerminal's
  retroactive OHLCV is only valid if the coin population it's tested
  against was NOT assembled by searching for "what looks interesting/
  survived/pumped" after the fact. The only survivor-safe HISTORY
  population currently available is **Tier B established**
  (`universe.json`'s `tier_b_established`: found via CURRENT-state
  search/trending + screened to age >= 14 days, $50k-$5M liquidity) —
  per `INTEGRITY_NOTES.md` §4b, a coin alive and liquid for >=14 days is,
  by construction, still findable by a search done today; it isn't a
  bonding-curve newborn that could have died and vanished before
  discovery. **Tier A named coins** (POPCAT, KITTY) are also HISTORY-safe
  (hand-pinned, not survivor-selected by the research process).
  `tier_b_systematic` (the forward-discovery-log-only population) has, as
  of this writing, exactly zero coins with >=14 days of history above the
  liquidity floor (per `universe.json`'s own excluded_sample: 20/20 newest
  discoveries are $0-liquidity newborns) — it is not yet usable for
  HISTORY at all, only for FORWARD.
- **FORWARD track**: any hypothesis about brand-new (age < 14 days,
  especially bonding-curve-stage, <$50k liquidity) coins — which is where
  the sharpest version of the owner's thesis lives (Lens 7, the
  early-detection game) — can ONLY be tested on coins that entered
  `discovery_log.jsonl` via forward polling, evaluated forward from their
  own discovery timestamp. **Never** backfill this population by
  searching for "pump.fun coins that succeeded" after the fact — that
  silently re-injects the exact bias this split exists to prevent.
- **A hypothesis is either HISTORY or FORWARD, stated up front, never
  both blended into one N.** A "we found some HISTORY evidence AND some
  FORWARD evidence, pooled" report is not permitted — report them side by
  side, explicitly labeled, because they answer different questions
  (HISTORY: "does this pattern appear among coins that already proved
  survivable enough to still be searchable" — FORWARD: "does this pattern
  predict which of TODAY'S unproven launches will survive/pump"). Part C
  below fixes which track every hypothesis belongs to before any test is
  run.

### A1c. Wash-trading discount — relative, not absolute, and load-bearing on every result

- Jupiter's organic-vs-total volume split is the only quantitative wash
  measurement available. Per `INTEGRITY_NOTES.md` §3, POPCAT — a real,
  liquid, 2.5-year-old coin the owner actually trades — measured a 10.0%
  24h organic-buy ratio. **An absolute "require >50% organic" filter would
  exclude the owner's own coins.** Every hypothesis touching volume
  (Lenses 3, 5, and the early-detection lens) must therefore:
  1. Compute organic ratio as a **z-score against the coin's own trailing
     baseline** (rolling median of that coin's own organic ratio over
     its observed history so far), not an absolute cutoff.
  2. Where a peer-relative read is needed (e.g. ranking discovery-cohort
     coins), rank against the **cohort's own contemporaneous distribution**
     (coins discovered in the same week), not a fixed number — wash
     baselines likely drift with mania/bot-activity cycles market-wide.
  3. Report volume-based results TWICE: once using raw (`volume.h1`,
     `volume_24h`, etc.) and once using `*_organic` fields — any hypothesis
     whose effect disappears or flips sign once restricted to organic
     volume is flagged **WASH-DRIVEN**, not a candidate, regardless of how
     clean the raw-volume result looked.
  4. A "rising organic ratio" or "falling organic ratio" claim (Lens 3)
     must be measured as **a change in the coin's own ratio over time**,
     never a single snapshot compared to a universe-wide bar.

### A1d. Slippage/MEV honesty — every HISTORY number is an upper bound, stated every time

- None of GeckoTerminal/DexScreener/Jupiter's price fields reflect a real
  fill. A close-price backtest on a $30k-liquidity pool assumes execution
  at a price a real $200-$1,000 order (A0's reference size) would move
  straight through. **Every HISTORY-track result must be reported with
  the explicit tag `[SLIPPAGE-NAIVE UPPER BOUND]` — this is not
  boilerplate, it must appear in the same sentence as the headline number,
  every time it's cited anywhere (this doc, a future results file, a
  briefing note).**
- **Per-liquidity-bucket realistic round-trip cost table** (harsher than
  `CONFLUENCE_CAMPAIGN.md` A6's HL-alt table — this venue has no CEX-grade
  order book, only an AMM curve, at the $200-$1,000 reference size):

  | Liquidity bucket (at entry) | RT cost assumption | Basis |
  |---|---|---|
  | $15k-$50k (bonding-curve / newborn) | **250-400bps+** | AMM constant-product price-impact math at $200-$1,000 against a $15-50k pool moves price several percent one-way before any fee; add Solana priority-fee spikes during mania and MEV sandwich risk on public routing |
  | $50k-$200k | **150-250bps** | Still thin enough that a $500-1000 order is a meaningful fraction of one side of the pool |
  | $200k-$1M | **75-150bps** | Matches the mid-cap campaign's THIN bucket ceiling (75bps) as a FLOOR here, not a ceiling — this venue starts where that one's worst case ends |
  | $1M-$5M (Tier B established ceiling, e.g. arc/ZEREBRO/Ban) | **30-75bps** | Comparable to HL's thinnest tradeable alts |
  | POPCAT-scale ($2-3M+, Tier A) | **15-40bps** | Closest this venue gets to "liquid," still 2-3x a majors HL taker fee |

  These are defensible estimates, not measured fills — **stated explicitly
  so they can be argued with, not hidden.** Before any candidate is
  pre-registered (A2 Honesty Ceiling), it must be spot-checked against
  Jupiter's live `/quote` endpoint at the actual reference size, on the
  actual liquidity band involved — this recon deliberately did not probe
  `/quote` (a live-quote endpoint, not a data endpoint, per
  `MICROCAP_DATA_RECON.md` §4c), so no result in this campaign has been
  checked against it yet. That check is a precondition for A2's honesty
  ceiling, not optional polish.
- MEV/priority-fee risk is qualitative, not currently quantifiable from
  this data (no priority-fee time series collected) — flag every
  HISTORY-track hypothesis with a `[MEV/PRIORITY-FEE UNMODELED]` note
  alongside the slippage tag; do not fold an invented number into the
  cost table above to make it look precise.

### A1e. Liquidity-at-time — a signal only counts if the position was actually fillable then

- GeckoTerminal's OHLCV endpoint gives price/volume candles, **not**
  liquidity/reserve history — `reserve_in_usd` is a current-state field
  only (confirmed in recon §1, INTEGRITY_NOTES §4). There is currently
  **no retroactive liquidity time series** for any coin, including Tier A/
  Tier B established.
- **Mitigation for the HISTORY track (imperfect, disclosed):** Tier B
  established membership already required $50k-$5M liquidity AND age
  >=14 days **at the time of the screen** — this is evidence the coin
  probably wasn't at $0 liquidity for its recent history, but says
  nothing about liquidity at any specific past candle, and nothing at all
  about the coin's first hours/days (exactly the highest-signal, highest-
  risk window for Lens 1's lifecycle hypotheses). **Any HISTORY hypothesis
  touching a coin's first 14 days of life cannot be liquidity-verified at
  all and must be labeled `[LIQUIDITY-AT-TIME UNVERIFIED]`** — this
  specifically blocks trusting any HISTORY-track "early-life momentum"
  result at face value (see M1/M4 in Part B — they're included for
  hypothesis-generation value only, gated FORWARD for confirmation).
- **The FORWARD track fixes this going forward and only going forward:**
  `liquidity_snapshots.jsonl` gives point-in-time `liquidity_usd` at each
  poll — once dense enough (collector runs continuously), every FORWARD
  signal can be joined to the nearest preceding liquidity snapshot and
  gated on "was liquidity >= 3-5x the A0 reference position size at
  signal time" (a coin at $15k liquidity cannot honestly absorb a $1,000
  position without being the majority of one side of the pool). This gate
  is enforced in the FORWARD track only; it does not exist for HISTORY.

### A2. THE HONESTY CEILING (same shape as `CONFLUENCE_CAMPAIGN.md` A7, restated because it binds harder here)

**No hypothesis in this campaign may be described as "an edge," acted on,
sized into a real position, or shipped anywhere near the live/paper bot
until it has:** cleared A1a-e above, cleared OOS + BH-FDR (A3 below) on
its assigned track, been confirmed FORWARD (per A1b — a HISTORY-track
survivor is a hypothesis-generation lead, not a candidate, until it is
independently re-tested on FORWARD discovery-log data), and been
spot-checked against a live Jupiter `/quote` at the reference size (A1d).
A HISTORY-track "survivor" that has not cleared a FORWARD re-test is
reported as **ORIGIN, UNVALIDATED** — identical framing to how
`PREREGISTRATION.md` treats H4's origin peek. This corpus is smaller and
easier to overfit than the 25-coin/14-month HL corpus (a handful of
established meme coins, ~180 days each) — treat every clean-looking
HISTORY number with MORE suspicion than the HL campaign required, not
less.

### A3. OOS split, FDR, minimum sample — reuse the locked convention, adapted for staggered launches

- **Primary split is calendar-date, not per-coin percentile.** Micro-cap
  coins have wildly staggered launch dates (POPCAT Dec 2023, ANSEM Jun
  2026, NEEGY Jul 2026) — a per-coin 60/40 split (the HL campaign's
  convention) would leave some coins with only days of TEST data. Instead:
  fix ONE calendar cutoff date across the whole pooled panel (the midpoint
  of the combined observed calendar range at run time), TRAIN = all
  episodes (any coin) before it, TEST = all episodes after. This matches
  how `xs_backtest.py`-style cross-sectional work should generalize across
  assets with different histories, not the WALKFORWARD_SPLIT=0.60
  single-coin convention.
- **BH-FDR at q=0.10, Bonferroni reported alongside**, one family, exactly
  per `CONFLUENCE_CAMPAIGN.md` A3 — computed once across every hypothesis
  actually run in this campaign (HISTORY + FORWARD combined family size,
  disclosed before any result is read).
- **Minimum sample: n>=30 independent episodes per bucket**, same
  `SIGNIFICANCE_N` convention as `PREREGISTRATION.md`/the confluence
  campaign. Below that, print descriptive-only, labeled
  `[UNDERPOWERED, n=X]`, never a p-value.
- **Episode-collapse — TWO independent collapse rules needed here, not
  one:**
  1. Same-coin, same-signal, consecutive-day collapse (identical to
     `CONFLUENCE_CAMPAIGN.md` A5.1).
  2. **NEW — same-day serial-launch collapse.** Pump.fun launches run in
     waves; a single actor/template can spawn dozens of near-identical
     tokens in one day (visible in the discovery log's own excluded
     sample: `cat`, `Cat`, `CAT` appearing as 5+ distinct mints). Treating
     each as an independent N in an early-detection hypothesis (Lens 7)
     would overstate power. Mitigation (disclosed as imperfect — creator-
     wallet clustering isn't in this data): flag and separately report
     any day where >=5 discovery-log entries share a near-identical name
     pattern (case-insensitive/whitespace-normalized match), and run the
     early-detection hypotheses both with and without that day's cohort
     to check the finding isn't concentrated in one templated flood.

### A4. Refute-yourself checklist — the HL campaign's five checks, plus two micro-cap-specific ones

All five of `CONFLUENCE_CAMPAIGN.md` A5 (episode-collapse, single-coin
dominance, net-of-realistic-cost, minimum-sample, direction/regime
honesty) apply unchanged. Add:

6. **Wash-driven check (A1c formalized as a mandatory report field):** does
   the effect survive when raw volume/txn fields are replaced with their
   `*_organic` counterparts? If not, label `WASH-DRIVEN`.
7. **Rug/tail-loss check:** report the worst single-episode outcome
   alongside the mean — a mean built on 29 small wins and 1 rug (-90%) is
   a materially different claim than 29 small wins and no rugs, and this
   venue's tail risk is categorically worse than anything in the HL
   corpus (no circuit breaker, no liquidation-price floor — a pool can go
   to zero liquidity in one block).

### A5. Rate-limit and RAM discipline (this campaign's version of Part C's RAM rule)

- The binding constraint here is **API rate budget, not RAM** (GT: 30
  req/min hard-enforced 429; DexScreener ~60/min; Jupiter undisclosed,
  throttled conservatively) — the opposite emphasis from the HL campaign.
  Any batch script pulling GT OHLCV must run **sequentially, one pool at a
  time, >=2.2s between calls**, matching `microcap_collector.py`'s
  existing throttle, and must **never run concurrently with the live
  `microcap_collector.py` poller** (same rate budget, same IP) — check
  the collector's own log/PID before starting a batch pull.
- RAM is secondary but still real: GT OHLCV per pool is small (day bars:
  ~180 rows; minute bars at `aggregate=5`: up to 1000 rows/pool), so cache
  each pool's pull to its own CSV/parquet under `data/microcap/ohlcv/` and
  discard from memory before moving to the next pool, same discipline as
  `CONFLUENCE_CAMPAIGN.md` Batch 3's 1h-CSV handling.

---

## Part B — Prioritized Meme-Native Hypothesis Space

35 hypotheses (M1-M35) across 7 lenses. Each entry: rule → data field(s)
→ direction → track (HISTORY / FORWARD-ONLY / NEEDS-NEW-DATA, per Part
A1b's split, elaborated in Part C) → why native to micro-cap dynamics
(not a port of a mid-cap TA idea). Tiers: **A** = run first (plausible +
testable today), **B** = run after A / needs more collector runtime,
**C** = exploratory / high multiple-comparisons / needs new infra,
**NEW-DATA** = not testable on anything we currently collect, listed for
completeness per the mission's own ask.

### Lens 1 — Lifecycle / age dynamics

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M1 | B | Forward N-day return as a function of coin age-at-signal (bucketed: <24h, 1-3d, 3-7d, 7-14d, 14-30d, 30-90d, 90-180d), using GT daily OHLCV | `pool_created_at`, GT daily OHLCV | Direction depends on bucket (hypothesis: early = momentum/mania, later = mean-reversion/decay) | HISTORY (Tier B established only, `[LIQUIDITY-AT-TIME UNVERIFIED]` for the <14d buckets per A1e — those buckets are effectively FORWARD-only in practice) | Mid-cap TA has no "age since launch" concept — a coin's entire lifecycle (bonding-curve mania → graduation → distribution → long-tail chop) is compressed into weeks-to-months here, unlike an asset with years of trading history; age itself may be the single most information-dense feature this venue has that HL data structurally cannot have. |
| M2 | A | Event study: abnormal return in the 24-72h window around a coin's `dex_id` transition from `pump-fun`/bonding-curve to an AMM (`raydium`/`pumpswap`/`moonshot`) — "graduation" | Discovery log `dex_id` field over time (needs the collector to observe the SAME mint under two different dex_id values across polls) | Long (graduation = a real liquidity/demand threshold cleared) | FORWARD-ONLY (requires observing the transition live; HISTORY population — Tier B established — was captured post-graduation, transition timing unrecoverable) | Graduation is a genuine, discrete, mechanically-defined event unique to the pump.fun model (bonding curve fills → migrates to a real AMM pool) — nothing in HL/CEX markets has an analogous "this asset just became real" event with a hard mechanical trigger. |
| M3 | A | Survival-to-N-days as a forward-collectable base rate, conditioned on liquidity/age at discovery (does surviving to day 3 raise P(survive to day 30) vs a naive base rate) | Discovery log + periodic re-poll of same mints (liquidity_usd, still-listed) | N/A — base-rate/conditioning study, not a directional signal | FORWARD-ONLY (survival curve of NEW launches is exactly what A1b rules out reconstructing from HISTORY) | This IS the ~1.4%-graduation-rate reality (recon §2) turned into a usable filter — most launches die, so "still alive at day N" is itself strong Bayesian evidence, a dynamic with no equivalent in an HL alt that by definition already survived a $1M+/day liquidity screen to be in the universe at all. |
| M4 | A (methodology input, not a standalone signal) | First-24-72h realized volatility / wick range as a function of age, to set the minimum age floor below which ANY other signal in this campaign is noise | GT hourly/minute OHLCV, `reserve_in_usd` at time of query | N/A — calibration study | HISTORY for the shape (Tier B established coins' own first days, `[LIQUIDITY-AT-TIME UNVERIFIED]`), confirmed FORWARD once live density exists | Recon's own dead-pool example (candle range 2.34e-6 to 2.86e-5 within one hour on a $0-liquidity pool) shows the first hours/days here are categorically noisier than anything in the HL corpus — this hypothesis exists to produce a defensible age floor (e.g. "don't trust any signal before age >= X hours") for every other lens, not to trade on directly. |

### Lens 2 — Liquidity dynamics

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M5 | A | Rising trailing liquidity (24-72h % change in `liquidity_usd` > +X%, X calibrated on TRAIN) predicts positive forward N-day return | `liquidity_snapshots.jsonl` `liquidity_usd` trend | Long | FORWARD-ONLY (no historical liquidity series exists — A1e) | An HL alt's liquidity is ~fixed market structure (order book depth doesn't "grow" the way an AMM pool's TVL does); here, liquidity growth is a direct, observable proxy for new capital committing to the pool (LP adds, often correlated with team/community confidence) — a genuinely different causal mechanism than anything price-based. |
| M6 | A | Sharp negative liquidity change (>-X% in a short window) predicts negative forward return / flags rug-in-progress — used as an AVOID/EXIT gate, not an entry | `liquidity_snapshots.jsonl` | Avoid/exit (risk gate, not entry generator — same framing as the validated WAIT-knife gate in the HL campaign) | FORWARD-ONLY | LP-pull rugs are a category of risk with literally no equivalent on Hyperliquid (an order book cannot be "pulled" the way an AMM's liquidity can be withdrawn by whoever added it) — this is the single highest-value risk gate unique to this venue. |
| M7 | B | Liquidity-to-FDV (or liquidity-to-mcap) ratio as a structural fragility indicator — low ratio = thin LP relative to paper valuation = easily manipulated single-candle wicks; does a low-ratio cohort show worse forward risk-adjusted return | `liquidity_usd` / `fdv_usd` (both in DexScreener/GT snapshots) | Avoid at low ratio / risk-sizing input | HISTORY possible for Tier B established (ratio is knowable from a single current-state snapshot's `fdv_usd`, though the *trend* is FORWARD-only), FORWARD for the trend version | Mid-cap TA has no equivalent because HL alts don't have a "fully diluted valuation" divorced from tradeable float in the same way a low-liquidity, high-FDV meme coin can — the ratio itself is a meme-specific manipulability signal (POPCAT's own $2.9M liquidity / $43.6M mcap ≈ 6.7% is the established-coin reference point). |
| M8 | B | Liquidity surge COINCIDENT with a price pump (add-on-strength) vs. price pump with FLAT/falling liquidity (thin/wash pump) — does the former predict better forward continuation | `liquidity_snapshots.jsonl` liquidity trend joined to GT OHLCV price move | Long (confirmed) vs. avoid (unconfirmed) | FORWARD-ONLY | Distinguishes "real buyers + LPs committing capital together" from "price moved because the book is thin and a small buy walked it up" — a distinction meaningless in a $1M+/day HL alt where a single retail-sized buy cannot materially move liquidity-weighted price. |

### Lens 3 — Organic-volume signal (Jupiter)

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M9 | A | Rising organic-buy-ratio trend (own-baseline z-score rising across 5m→1h→6h→24h windows, per A1c) predicts positive forward return — "real interest emerging" | `wash_signal.jsonl` `buyOrganicRatio_{5m,1h,6h,24h}` | Long | FORWARD-ONLY (Jupiter has no historical organic-volume API) | This is a genuinely new instrument class — mid-cap TA has no concept of "fraction of volume that's real" because CEX/HL volume, while it can include wash on some venues, isn't structurally dominated by bot/MEV flow the way an on-chain AMM's raw volume is (POPCAT's own 10% organic baseline, recon §4b). |
| M10 | A | Falling organic-buy-ratio trend (own-baseline z-score falling) predicts negative forward return — "distribution/fade" | `wash_signal.jsonl` | Short/avoid | FORWARD-ONLY | Mirror of M9; distinct claim (a coin's wash composition changing over time, not its absolute level) — falling organic ratio while raw volume holds or rises is a specific, meme-native "insiders dumping into bot-generated volume" pattern. |
| M11 | A | Sudden organic-ratio DROP (>=2 std below the coin's own trailing mean, single-snapshot) as a real-time manipulation/dump alarm, distinct from the trend versions above | `wash_signal.jsonl`, own-coin rolling baseline | Avoid/exit (risk gate) | FORWARD-ONLY | Directly operationalizes `INTEGRITY_NOTES.md` §3's own recommended use ("watch for a sudden drop... as a live wash/manipulation alarm") rather than inventing a fresh idea — this is the campaign converting an already-identified measurement tool into a testable rule. |
| M12 | B | Organic buy/sell asymmetry: `buyOrganicRatio - sellOrganicRatio` (organic buying pressure net of organic selling pressure) as a directional tilt, distinct from the raw buy/sell volume ratio (Lens 4) | `wash_signal.jsonl` buy/sell organic ratio pair | Long when positive tilt | FORWARD-ONLY | Raw buy/sell imbalance (M17) can be entirely bot-generated in both directions; this variant asks the same directional question using only the flow Jupiter itself classifies as real — a strictly harder, more meme-specific bar than the raw version. |

### Lens 4 — Holder / on-chain dynamics

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M13 | B | Holder-count growth rate (trailing % change) predicts forward return — classic "grow or die" meme dynamic | `wash_signal.jsonl` `holder_count` trend (Jupiter) | Long | FORWARD-ONLY (only a live snapshot field, no history) | Holder count as a live, publicly visible number is a meme-specific social-proof mechanic (screenshotted, tweeted, watched obsessively by meme traders) with no analogue in HL's largely anonymous perp order flow. |
| M14 | NEW-DATA | Holder concentration (top-10 wallet % of supply) / whale accumulation trend | Not available from GT/DexScreener/Jupiter's documented endpoints — would need Solana RPC token-account enumeration or a paid indexer (Birdeye, Helius) | Avoid at high concentration / long on accumulation without dumping | NOT TESTABLE YET | Classic meme alpha (see recon's own flag) but genuinely requires new data acquisition — listed for completeness per the mission brief, not designed further here. Candidate follow-up: `GET /networks/solana/pools/{address}/trades` (recon §1, already reachable) gives wallet-level buy/sell records; a top-N-wallet net-flow reconstruction from raw trades is buildable without a new API, only new engineering — flag as the cheapest NEW-DATA path if this lens becomes a priority. |
| M15 | NEW-DATA | Dev/creator wallet holding % and dev-sell behavior (the single most-cited meme-coin risk factor) | Not available from current sources; pump.fun's undocumented API might expose creator address (recon flags it as reachable but explicitly out-of-scope to build on) | Avoid on high dev holding / dev-sell event | NOT TESTABLE YET | Same status as M14 — the highest-plausibility meme-native signal in this entire document by reputation, and the one most clearly blocked on data access rather than methodology. Do not build against the undocumented pump.fun API per the recon's own guardrail; the correct path is GT's `/trades` endpoint (documented, rate-limited) once the pool's first trades (which usually include the creator's own bonding-curve buys) are captured — feasible but not designed here, flagged for a future data-acquisition proposal. |
| M16 | A | Distinct-trader-count growth (`numTraders_{1h,6h,24h}` from Jupiter) as a proxy for holder growth, usable TODAY without new data since it's already being collected forward | `wash_signal.jsonl` `numTraders_*` | Long | FORWARD-ONLY | A pragmatic substitute for M13/holder-count history while true holder-count history doesn't exist — distinct-trader count and holder count measure related but not identical things (a trader can buy without becoming a new "holder" if buying more of an existing bag), worth testing as its own hypothesis rather than assumed equivalent. |

### Lens 5 — Volume / txn microstructure

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M17 | A | Buy/sell txn-count imbalance (`txns.h1.buys / (buys+sells)`) predicts short-horizon direction | `liquidity_snapshots.jsonl` `txns_h24_buys/sells` (and finer windows if polled) | Long when buy-skewed | FORWARD-ONLY (DexScreener exposes only rolling current-state windows, no historical txn-count series) | Txn-COUNT imbalance (distinct from $-volume imbalance) is a specific meme-microstructure tell — many small buys (retail FOMO) vs few large ones (whale accumulation) show up differently in count vs dollar terms in a way that's compressed/invisible in HL's larger, more homogeneous order sizes. |
| M18 | B | Total txn-count surge (buys+sells vs the coin's own trailing baseline) as an attention/momentum trigger, the meme-venue analogue of `S5` volume-surge (already null on HL, `signal_panel_test.py`) | `liquidity_snapshots.jsonl` | Long | FORWARD-ONLY | Re-tests a mechanism ALREADY FOUND NULL on HL (isolated volume surge) but on a structurally different signal (txn COUNT, not $-volume) in a venue where attention/virality (not $ flow) may be the real driver of continuation — a legitimate, pre-committed "does the same idea work when the underlying mechanism is different" follow-up, not a blind re-run of a dead HL signal. |
| M19 | A | Volume-to-liquidity ratio spike (`volume_h1 / liquidity_usd`, a normalized turnover measure) predicts forward move magnitude/direction | `liquidity_snapshots.jsonl` | Direction TBD by TRAIN (turnover spikes could be climactic-exhaustion OR breakout-confirmation) | HISTORY possible using GT's historical `volume` column ÷ Tier B established coins' current-snapshot `liquidity_usd` as an imperfect static denominator (flag `[LIQUIDITY-AT-TIME UNVERIFIED]` for the denominator); clean version is FORWARD | Volume-to-liquidity turnover is meaningless as a distinguishing signal on a $1M+/day HL alt (turnover is structurally low and stable) but potentially very informative on a $20-50k pool where a single day's turnover can be 10-50x the pool's own depth — the ratio itself only becomes interesting at micro-cap scale. |
| M20 | B | Average trade size trend (`volume / txn_count`) — rising avg size = fewer/larger (whale) participants vs falling = many/smaller (retail swarm); does either regime predict forward direction differently | Derived from `liquidity_snapshots.jsonl` volume + txn counts | Direction TBD by TRAIN | FORWARD-ONLY | A compositional signal (who's trading, not how much) with no clean equivalent in HL's largely algo/market-maker-dominated flow — meme coins visibly alternate between "whale accumulation" and "retail swarm" phases that are locally observable here. |

### Lens 6 — Cross-sectional rotation (within the cat/meme universe)

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M21 | A | Top-quintile relative-strength rotation within Tier B established universe (20-coin panel), analogous to `xs_backtest.py`'s HL momentum book but on meme peers only | GT daily OHLCV across `tier_b_established` | Long top-quintile | HISTORY (Tier B established, survivor-safe per A1b) | The HL cross-sectional momentum book was weak/marginal even on a liquid, algo-covered 25-alt universe (`CONFLUENCE_CAMPAIGN.md` C27/C41 origin) — meme coins may show STRONGER cross-sectional momentum because meme attention is itself a rotating, narrative-driven phenomenon (this week's "cat" narrative vs last week's "dog" narrative) rather than a diversified-portfolio-flow effect. |
| M22 | A | Meme-sector breadth (% of Tier B established universe posting positive 24h/7d return) as a market-wide "meme mania heat" regime gate, the meme-venue analogue of `weather.py`'s `breadth20` | GT daily OHLCV across `tier_b_established` | Regime gate (condition other signals, not standalone direction) | HISTORY (Tier B established) | Meme-coin cycles are famously synchronized (a broad "alt/meme season" lifts nearly everything, a "meme winter" kills nearly everything) even more visibly than majors-driven altcoin beta — worth building as a first-class regime variable for this venue specifically, not borrowed unchanged from `weather.py`'s BTC-centric definition. |
| M23 | C | Correlated-peer-cluster laggard convergence: within a pairwise-correlated cluster (e.g., all "cat" or "dog" themed coins), does one coin dipping while its cluster is NOT dipping predict short-horizon catch-up | GT daily OHLCV, correlation matrix built across `tier_b_established` (+ any Tier A) | Long laggard | HISTORY (Tier B established), flagged Tier C — new infra (cluster definition) needed, same caution as the HL campaign's analogous C28 | Direct meme-native analogue of C28 in `CONFLUENCE_CAMPAIGN.md`, but plausibly stronger here: meme "sub-narratives" (cat coins, dog coins, AI-agent coins) rotate capital within-theme in a way that's anecdotally well known in this market and has no clean equivalent in HL's asset-class-agnostic 25-alt universe. |
| M24 | B | New-launch cohort intensity (count of new discovery-log entries per day, market-wide) as a "mania heat" gauge — gates position sizing/aggressiveness down when launch intensity is extreme (froth) or up when quiet (less noise, more selective survivors) | `discovery_log.jsonl` daily counts | Regime gate | FORWARD-ONLY (discovery log only exists from collector start) | A pure sentiment/froth gauge unique to this venue — nothing in HL data measures "how many new assets are being created right now" as a market-wide mania proxy; pump.fun's reported 10-20k launches/day (recon §2) makes this a genuinely observable, high-frequency signal once the collector has enough history. |

### Lens 7 — THE EARLY-DETECTION GAME (forward-collectable, highest-value)

This is the core meme game per the mission brief: among newly-discovered
coins, which criteria predict the ones that survive/pump. **Every
hypothesis in this lens is FORWARD-ONLY by construction** (A1b) — this is
the cleanest, least-overfittable lens in the whole campaign precisely
because it cannot be run on old data at all, only accrued going forward,
same epistemic status as `PREREGISTRATION.md`'s H3/H5 liquidation work.

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M25 | A | Composite early-survival score at T+24h (liquidity growth positive AND organic-ratio not falling AND trader-count growing AND no liquidity drain event) predicts survival to T+7d / T+30d, vs a naive base rate | `discovery_log.jsonl` + repeated re-poll of same mints (`liquidity_snapshots.jsonl`, `wash_signal.jsonl`) | Composite screen (not a single-factor direction) | FORWARD-ONLY | This is the mission's explicit "highest-value forward angle" — a multi-factor confluence screen built FOR this venue's actual failure mode (98%+ die), not adapted from a mid-cap idea. The success metric (survival, not return) is itself venue-specific: for a bonding-curve-stage coin, "did not die" is the primary question, "how much did it return" is secondary and conditional on survival. |
| M26 | A | Baseline filter calibration: at what liquidity-floor + age-floor combination (calibrated on TRAIN cohort only) does the discovery-log population separate into a "worth watching" cohort with materially better forward survival than the unfiltered population | `discovery_log.jsonl`, liquidity at discovery | Screen calibration (methodology, feeds M25) | FORWARD-ONLY | Directly extends the collector's own existing `min_liquidity_usd=$30k` Tier-B-systematic floor (currently ad hoc/recon-derived) into a DATA-DERIVED floor, matching this project's own "living values, not hardcoded" standing mandate (memory: LIVING VALUES mandate 2026-07-14) applied to a brand-new domain. |
| M27 | A | Early (first-48h) organic-ratio floor, measured RELATIVE to the discovery cohort's own contemporaneous distribution (per A1c — never an absolute cutoff), predicts non-rug survival | `wash_signal.jsonl` for newly-discovered mints, cohort-relative | Long/watch-list inclusion | FORWARD-ONLY | Operationalizes the mission's own framing ("rising organic-volume ratio = real interest emerging") specifically for the discovery cohort rather than the already-established Tier A/B coins — a coin with peer-relatively-high organic ratio in its first 48h is a plausible "this isn't just bots" early tell. |
| M28 | B | Graduation-within-N-days (bonding-curve `pump-fun` dex_id transitioning to an AMM dex_id) as a leading indicator of subsequent liquidity stability / non-rug status | `discovery_log.jsonl` dex_id observed over repeated polls | Long/watch-list inclusion | FORWARD-ONLY | Same mechanism as M2 (Lens 1) but framed as an early-detection SCREENING criterion (has X graduated yet) rather than an event-study return question (what happens AROUND graduation) — distinct question, same underlying event, worth stating separately since the two answers could differ (e.g., graduation could predict survival without predicting excess return). |
| M29 | A | First-6h buy/sell txn-count imbalance + trader-count velocity (both available from the FIRST poll after discovery) predicts 24h/72h liquidity trajectory (growing vs draining) | `discovery_log.jsonl` timestamp + earliest `liquidity_snapshots.jsonl`/`wash_signal.jsonl` polls for that mint | Composite leading screen | FORWARD-ONLY | The earliest-available-signal version of the early-detection game — tests whether the very first few hours of on-chain activity (before liquidity/organic-ratio trends even have enough history to compute a trend) already carry predictive content, which would let the screen fire faster than M25/M27's trend-based versions. |
| M30 | B | Holder-count (or trader-count, per M16's substitute) velocity in the first 24h among the discovery cohort predicts 7-day survival, tested as its OWN hypothesis rather than folded into M25's composite | `wash_signal.jsonl` `holder_count`/`numTraders_24h` for discovery-cohort mints | Long/watch-list inclusion | FORWARD-ONLY | Isolates the specific "holder growth" mechanism from the mission brief as a standalone test (not just a component of M25's composite) so that if M25's composite works, this campaign can say WHICH ingredient is doing the work, mirroring `CONFLUENCE_CAMPAIGN.md`'s own discipline of testing components alongside composites (e.g. C1 vs the isolated S1/S4). |

### Cross-lens combinations / Tier C exploratory

| # | Tier | Rule | Data | Direction | Track | Why native |
|---|---|---|---|---|---|---|
| M31 | B | Confluence check: liquidity growth (M5) AND rising organic ratio (M9) together vs. either alone — does requiring both beat either single-factor version | `liquidity_snapshots.jsonl` + `wash_signal.jsonl` | Long | FORWARD-ONLY | Direct meme-native analogue of the HL campaign's core confluence logic (Lens 1 there) — two independently-plausible-but-noisy signals from DIFFERENT underlying mechanisms (capital commitment vs. real trader interest) might jointly clear noise that neither clears alone. |
| M32 | B | Age-conditioned liquidity growth: restrict M5 to the 3-14 day age window specifically (past the worst of the first-72h chaos per M4, still early enough to matter) | `pool_created_at` + `liquidity_snapshots.jsonl` | Long | FORWARD-ONLY | Tests whether M5's signal (if any) is being diluted by including either too-young (pure noise, M4) or too-old (already-established, thesis doesn't apply) coins in one pooled test — a direct regime-conditioning move, same logic as the HL campaign's Lens 2. |
| M33 | A | Liquidity-to-mcap ratio (M7) DECLINING over time (not just low in absolute level) combined with any negative liquidity change (M6) as a compound rug-precursor exit gate | `liquidity_usd`, `fdv_usd`/`mcap_usd` trend | Avoid/exit (risk gate) | FORWARD-ONLY | Compounds two independently-plausible risk signals into a single actionable gate — the meme-venue analogue of the HL campaign's WAIT-knife-gate-refinement items (C32/C34), aimed at the single most catastrophic and most venue-specific failure mode (the rug) rather than at return generation. |
| M34 | B | Event-study abnormal volume/organic-ratio pattern in the hours immediately preceding a graduation event (does organic interest visibly build before the mechanical bonding-curve threshold is crossed, i.e. is graduation "earned" or "surprising") | `discovery_log.jsonl` dex_id transitions + `wash_signal.jsonl` in the preceding window | Descriptive / leading-indicator refinement of M2 | FORWARD-ONLY | A mechanistic decomposition of M2 — if graduation is usually PRECEDED by rising organic interest (not just a coincident liquidity threshold), that's a stronger, earlier-firing version of the graduation signal than M2/M28 alone provide. |
| M35 | C | Wash-adjusted liquidity growth: does M5's liquidity-growth signal survive when discounted by concurrent organic-ratio decline (i.e., is some "liquidity growth" actually a wash-trading-correlated fake-volume artifact rather than real LP capital committing) | `liquidity_snapshots.jsonl` + `wash_signal.jsonl` jointly | Long (net of wash discount) | FORWARD-ONLY | The single most paranoid, most anti-self-deception hypothesis in the document — explicitly designed to try to KILL M5 rather than confirm it, matching this campaign's stated moat ("design so we cannot fool ourselves"); flagged Tier C because the wash-liquidity link is speculative and its own mechanism isn't independently established yet. |

**Summary count for A3 (multiple-comparisons family):** 35 hypotheses
(M1-M35) enumerated; M14/M15 are NOT TESTABLE YET (excluded from any
family until new data is acquired) → **scored family = 33** once both
tracks are run. At raw p<0.05, expected false positives ≈33×0.05≈1.65 —
even fewer excuses than the HL campaign for treating a single raw-p<0.05
hit as meaningful.

---

## Part C — HISTORY vs FORWARD-ONLY, explicitly

Per A1b, this split must be fixed before any test is run, not discovered
after looking at results.

**Testable on HISTORY today (slippage-naive upper bound, Tier A + Tier B
established only, survivor-safe per A1b):**
- M1 (age-bucket forward return) — `[LIQUIDITY-AT-TIME UNVERIFIED]` for
  buckets <14 days
- M4 (volatility-vs-age calibration study)
- M7 (liquidity-to-FDV ratio, static-snapshot version only)
- M19 (volume-to-liquidity turnover, static-liquidity-denominator version)
- M21 (cross-sectional rotation within Tier B established)
- M22 (meme-sector breadth regime gate)
- M23 (correlated-peer-cluster convergence, Tier C / new infra)

Every one of these is bounded to the 20-coin Tier B established universe
(+2 Tier A) — a small N of COINS even though each has up to ~180 days of
daily bars; the A5.2 single-coin/single-cluster dominance check is
unusually important here given how few independent names exist in this
universe compared to HL's 25-alt panel.

**FORWARD-ONLY (cannot be tested on any existing data, must accrue from
the collector going forward, per A1b/A1c/A1e — no historical API exists
for these fields at all):**
- M2, M3, M5, M6, M8, M9, M10, M11, M12, M13, M16, M17, M18, M20, M24,
  M25, M26, M27, M28, M29, M30, M31, M32, M33, M34, M35 (26 of 33 scored
  hypotheses — the large majority of this campaign, and specifically the
  entire Lens 7 early-detection game and most of Lenses 2-5)

**NOT TESTABLE YET (need data acquisition beyond current collector
scope):**
- M14 (holder concentration/whale tracking) — buildable from GT's
  documented `/trades` endpoint without a new API key; flagged as the
  cheapest follow-up if this lens becomes a priority
- M15 (dev wallet holdings/dev-sell) — same `/trades`-based path,
  contingent on identifying the creator address from early trades;
  otherwise blocked

**The practical consequence:** this campaign is disproportionately a
FORWARD campaign, unlike `CONFLUENCE_CAMPAIGN.md` which was almost
entirely HISTORY (14 months of HL OHLCV already existed). That's a
structural fact about this data, not a design choice — the venue's own
core mechanics (liquidity growth, organic volume, holder count) are
simply not retroactively knowable. **The 7 HISTORY-testable hypotheses
should be run first** (cheap, immediate, hypothesis-generating, but every
result stays `ORIGIN, UNVALIDATED` per A2 until forward-confirmed) while
the collector accrues the density needed for the 26 FORWARD hypotheses.

---

## Part D — Batching Plan (RAM/rate-lean test engine)

Mirrors `CONFLUENCE_CAMPAIGN.md` Part C's structure but reordered around
this campaign's actual constraint (API rate budget, per A5) rather than
RAM, and around the HISTORY/FORWARD split (Part C) rather than lens
number alone.

### Batch 0 — HISTORY precompute (run once, cheap)

Pull GT daily OHLCV for all `tier_a_named` (2) + `tier_b_established` (20)
pool addresses, one pool at a time, >=2.2s gap (A5), cache each to
`data/microcap/ohlcv/{symbol}_{pool_address}_daily.csv`. ~22 pools × ~1
request each (or a handful more for pagination past 180 days where
needed) — comfortably a few minutes of wall time at the rate limit, not a
RAM concern. Spot-check 2-3 pools' cached data against a fresh live pull
to confirm no staleness before trusting the cache for Batch 1.

### Batch 1 — Lens 1 HISTORY items (M1, M4) + Lens 6 HISTORY items (M21, M22, M23)

Reuses Batch 0's cache exclusively, no new API calls. Small compute (20-22
coins × ~180 daily rows). Run M22 (breadth regime) and M21 (rotation)
first — cheapest, most direct meme-native analogues of already-attempted
HL work, good sanity checks that the panel and calendar-date OOS split
(A3) are wired correctly. M23 (correlation clustering) last within this
batch — new infra (correlation matrix), same "build once, cache, don't
recompute per test" discipline as `CONFLUENCE_CAMPAIGN.md` Batch 5.

### Batch 2 — Lens 2/5 static-snapshot HISTORY items (M7, M19)

Also reuses Batch 0's OHLCV cache for the volume side; liquidity/FDV
denominators come from a single fresh `universe.json`-style snapshot pull
(already cached in `universe.json` itself — no new calls needed for a
first pass). Flag every result `[LIQUIDITY-AT-TIME UNVERIFIED]` per A1e
in the batch output itself, not just in this document.

### Batch 3 — Forward-collector maturity gate (infrastructure, not a hypothesis batch)

Before ANY FORWARD hypothesis (the 26-item majority of this campaign) can
be scored to a p-value, build a small maturity-check script (mirrors
`oi_hypothesis_harness.py`/`liq_hypothesis_harness.py`'s own maturity
guards) that reports, per FORWARD hypothesis's required data source:
independent-episode count so far (after both A3 collapse rules), span in
days, and whether `SIGNIFICANCE_N=30` + a `MIN_SPAN_DAYS_FOR_TRUST`
(propose 30 days, i.e. long enough to see more than one launch-mania
cycle — set exactly, not guessed, once the collector's own launch-rate
variability is visible) are cleared. As of this writing (397 discovery-log
rows, mostly $0-liquidity newborns, 49 liquidity/wash snapshots covering
only the 2 Tier A coins), **every FORWARD hypothesis is far below this
bar today** — this batch's job is to make that visible and re-run
periodically, exactly like the OI/liquidation harnesses do, not to
produce a result now.

### Batch 4 — FORWARD Lens 7 (early-detection, M25-M30) — the priority once data matures

Requires `microcap_collector.py`'s Tier-B-systematic discovery flow to
start capturing coins that ALSO clear a minimal liquidity floor (currently
0/397 non-excluded per `universe.json`'s own excluded_sample) — i.e., this
batch is gated on either (a) more collection time (some fraction of
launches eventually clear $15-30k liquidity and stay listed), or (b) a
deliberate widening of what gets tracked post-discovery (track a mint's
liquidity/organic/trader trajectory for N days regardless of whether it
currently clears the Tier-B floor, so death/survival itself becomes
observable — this is closer to what M3/M25/M26 actually need than the
current floor-gated Tier B systematic list). **Recommend building this as
a design change to the collector before Batch 4 can run at all** — flagged
here as a design-only note per this document's scope, not built.

### Batch 5 — FORWARD Lenses 2-5 (M5, M6, M8-M13, M16-M20, M24)

Runs once Batch 3's maturity gate clears for each hypothesis's specific
data dependency (liquidity_snapshots density for Lens 2/5, wash_signal
density for Lens 3/4). Group by shared data source, not by lens number,
to avoid re-joining the same snapshot files repeatedly — one join of
`liquidity_snapshots.jsonl` + `wash_signal.jsonl` per mint, reused across
every hypothesis that needs it.

### Batch 6 — Cross-lens combinations (M31-M35)

Deliberately sequenced last — needs Batch 4/5's individual-factor effect
sizes as inputs (same "can't start until the parents have results" logic
as `CONFLUENCE_CAMPAIGN.md`'s Batch 7/C37). M35 (wash-adjusted liquidity
growth, the self-refutation hypothesis) should be read immediately after
M31, not deferred, since it's specifically designed to stress-test M31's
result rather than stand alone.

### Final step — pooled FDR summary, run only once meaningful FORWARD data exists

One script ingests every batch's TEST-fold p-values (HISTORY batches'
results carried forward as `ORIGIN, UNVALIDATED` per A2, never treated as
final even if they clear BH-FDR on their own), computes BH-FDR/Bonferroni
across the disclosed family size (33, per Part B's summary, minus any
hypothesis still below `SIGNIFICANCE_N` at run time — those are excluded
from the scored family that run, not force-scored underpowered), and
reports exactly the same fields as `CONFLUENCE_CAMPAIGN.md`'s final step
(sign agreement, era-stability where enough span exists, A4 checklist
including the two new micro-cap-specific items, net-of-realistic-DEX-cost
expectancy per A1d's bucket table, and — critically — whether each
survivor has been spot-checked against a live Jupiter `/quote`). **Any
survivor becomes a candidate for a new `Hn` in `data/copilot/
PREREGISTRATION.md`, gated on FORWARD confirmation per A2 — not a claim,
not a ship, not a trade.**

---

## Closing note — what makes this venue's moat different from the HL campaign's

`CONFLUENCE_CAMPAIGN.md` was fighting efficiency: enough algo coverage and
liquidity that mechanical technical confluence had nowhere to hide an
edge, and the campaign's job was mostly to prove that null result
rigorously. This venue is fighting the opposite problem: **so little
structure and so much noise/manipulation that almost anything will look
like a pattern on a small sample**, and the campaign's job is to build
enough survivorship/wash/slippage/liquidity-at-time discipline that a
"finding" here isn't just the researcher's own confirmation bias meeting
a $20k pool's random wick. The two documents' hypothesis spaces look
similar in shape (lenses, tiers, OOS/FDR) deliberately — the discipline
travels — but almost nothing in Part B here is a literal port, because
the mechanisms that make a mid-cap TA rule fail (arbitrage, algo
front-running, deep books) are exactly the mechanisms this venue lacks,
and the mechanisms unique to this venue (bonding curves, wash bots, LP
rugs, holder-count virality) have no HL equivalent to port FROM in the
first place.
