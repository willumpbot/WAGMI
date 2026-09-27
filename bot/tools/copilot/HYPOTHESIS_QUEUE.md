# WAGMI Co-Pilot — Hypothesis Queue (idea-generation + exhaustion review)

**Written:** 2026-08-06 · **Scope:** hypothesis GENERATION only — this file
proposes what SHOULD be tested next; it runs no data test and fishes no data.
Read `STATE.md`, `SIGNAL_SCORECARD.md`, `PREREGISTRATION.md`,
`MICROCAP_CAMPAIGN.md`, `MICROCAP_HISTORY_RESULTS.md`, and
`LIVEBOT_RISK_AUDIT.md` first — this is the review layer on top of them.

## The filter every candidate had to pass

1. Not already calibrated-null (scorecard) and not on the KILL list.
2. Not directional-entry fishing on the exhausted 14-mo HL majors OHLCV.
3. Moat-satisfiable: a real entry-time-safe / OOS / significance / refute path.
4. Testable-NOW at n≥30 independent episodes on data on hand, OR a genuinely
   NEW forward instrument worth standing up (state which + time-to-power).
5. Additive to the co-pilot's actual job (calibrate a signal it SHOWS,
   validate an automatable RISK mechanic, or improve forward-evidence coverage).

## Data actually on hand (power check, verified 2026-08-06)

| Source | Size | Span | Status for testing |
|---|---|---|---|
| `funding_oi_history.jsonl` | 20.9k rows | ~58d majors / ~5d memes | funding=null (done), OI=H4 forward-gated, depth-flow=null (done) |
| `market_depth_history.jsonl` | 21.7k rows | ~35d majors | depth/taker-flow calibrated **null** (done) |
| `liq_events.jsonl` | 5.8k events | ~6d | H3/H5 forward-gated (need 14d span; partial-fill pseudoreplication) |
| `call_ledger.jsonl` | 58 rows | forward | H1/H2 forward-gated (need n≥30/bucket, months) |
| `owner_call_ledger.jsonl` | **MISSING** | — | owner hasn't fired `call` yet → owner-edge H has ZERO data |
| microcap forward (`liquidity_snapshots`/`wash_signal`/`flow_signal`) | ~1.3k rows each | **~1 day** (started 2026-08-06) | far below any bar → forward-gated |
| microcap OHLCV history (Tier A/B) | 22 coins, ≤180d | history | 7 HISTORY hypotheses RAN 2026-08-06 → **0 survivors** (done) |

---

## RANKED QUEUE — surviving hypotheses

### H-COST-1 (the only strong survivor) — Calibrate the micro-cap DEX execution-cost / size-vs-liquidity model against reality

- **One-line:** the slippage/cost the co-pilot SHOWS for DEX-spot memes
  (`owner_call.py`) and the cost table every forward micro-cap hypothesis is
  scored against (`MICROCAP_CAMPAIGN.md` A1d) are BOTH unverified heuristics —
  measure realized AMM price-impact (live Jupiter `/quote` and/or exact
  constant-product `xy=k` from `reserve_in_usd`) at the $200–$1,000 reference
  size across the ~22 Tier A/B coins' liquidity bands and check the model.
- **Lens:** RISK-MANAGEMENT + SEMI-AUTO EXECUTION (the automatable side).
- **Data source:** live Jupiter `/quote` endpoint (not yet probed — the recon
  deliberately skipped it) + `reserve_in_usd` / `liquidity_usd` snapshots
  already collected + the cached Tier A/B pool set.
- **Testable-now vs forward:** **TESTABLE NOW.** Time-to-power: hours. AMM
  impact is deterministic given reserves, so it needs a measurement, not a
  60-day wait. Independent unit = pool (~22 coins) across 3 sizes ≈ 66
  quote points spanning every liquidity bucket — enough to catch an
  order-of-magnitude model error. This is a **calibration**, not an edge
  claim, so it does not need an n≥30-for-significance p-value (same status as
  M4 volatility calibration — descriptive, not in any FDR family).
- **Moat / refute plan:** report predicted-vs-realized impact per coin/size;
  refute-yourself = if quoted impact ≪ the A1d table, the cost model is too
  HARSH → the whole forward campaign risks manufacturing FALSE NULLS (killing
  real edges under an invented cost hurdle); if quoted ≫ the shown caveat, the
  co-pilot is UNDERSTATING the owner's real cost today. Entry-time-safe is
  trivial (a current quote is current-state). Guard: quote at mania-time too
  (priority-fee/MEV spikes), disclose that MEV stays qualitatively unmodeled.
- **Honest prior:** the model is almost certainly WRONG, and specifically the
  co-pilot's *shown* caveat is too loose. `owner_call.py` warns only when a
  position is ≥2% of the pool and calls ≤2% "manageable"; but `xy=k` says a
  $500 order into a $30k pool (~1.7% of pool) already moves price ~3%+ one-way
  — i.e. "manageable" at 1.7% contradicts the campaign's own 250–400bps
  newborn estimate by a large factor. So this is not fishing for a null; it is
  almost certainly a live risk-honesty gap in a number the co-pilot shows the
  owner right now.
- **Value to the co-pilot:** HIGH and structural. This is a **precondition for
  every forward micro-cap conclusion being honest** (A1d calls it "a
  precondition for A2's honesty ceiling, not optional polish") AND it fixes a
  currently-shown, likely-understated risk number — both of the co-pilot's
  proven lanes (protect the trade + keep forward evidence clean). It is the one
  place where doing work now changes what the forward clocks will be able to
  conclude later, rather than just waiting.

**That is the entire surviving queue: one item.** It is deliberately not
padded. Everything else below was considered and rejected with a specific
filter reason — that short list is the evidence for the exhaustion verdict.

---

## CONSIDERED AND REJECTED (the audit trail behind the verdict)

**Directional / entry (filter 1 & 2 — the exhausted arena):**
- Any new entry model / signal on HL 14-mo OHLCV — filter 2, p-hacking; ~23
  variants already null (entry-panel, Bollinger, ADD, breakout, vol-surge,
  trend, rel-strength, fib).
- Funding-crowding (majors or memes) — calibrated **null** (scorecard, hard
  OOS 2026-08-06); meme funding history ~5d → forward-gated even if retried.
- Order-book depth / taker-flow directional — calibrated **null**. Conditioning
  it on session/regime = re-mining a null on a context (filter 1), not new.
- Liquidation magnets (`eye --deep`) — calibrated **null**, distance-matched
  control killed the apparent pull (filter 1).
- Micro-cap mechanical HISTORY (M1/M4/M7/M19/M21/M22/M23) — RAN 2026-08-06,
  **0/15 survivors**, negative-control-verified; early-life buckets are
  structurally forward-only (GT window predates every survivor). Filter 1.

**Forward-gated (real, pre-registered, just need TIME — not new):**
- H1/H2 (ADD>WAIT, weather regime) — call ledger 58 rows, months to n≥30.
- H3/H5 (liq clustering / session-timing) — ~6d span, need 14d; partial-fill
  pseudoreplication caveat locked. ~1.5wk.
- H4 (OI→cascade risk) — 58d span, need 60d + 2nd regime; vol-tercile control
  can't be evaluated yet (0/3 terciles at n≥30). Weeks.
- H6 (2d-drop reversion near-miss, test p=0.053) — forward tracker live, 0
  triggers logged, need n≥30 post-2026-08-05. The ONLY forward edge candidate.
- Owner-call edge (n≥20) — **owner_call_ledger.jsonl does not exist yet**; the
  owner has not fired `call` once. Zero data; the single highest-leverage
  instrument is gated on ADOPTION, not on a test.
- Micro-cap FORWARD M-hypotheses (M2,M3,M5,M6,M8–M13,M16–M20,M24–M35, 26 of
  them) — all pre-designed in `MICROCAP_CAMPAIGN.md`, collector at ~1 day of
  data, every one far below Batch-3's maturity gate. Not new (already
  enumerated), not testable-now. This is the real growth frontier, but it is a
  CLOCK, not a queue item.

**Blue-sky intertwining (considered, don't clear the bar):**
- OI + liq-cascade timing joint study — joint window ≈ liq collector age (~6d),
  span<14d YOUNG-SAMPLE, partial-fill pseudoreplication; underpowered forward
  variant of H3/H4. Forward-gated, not additive beyond them.
- Depth-imbalance/thinning → liq-cascade prediction (both majors, on hand) —
  the QUESTION differs from the depth null (risk-timing, not return), but
  joint overlap ~6d, autocorrelated 15-min ticks, and the "cascade" side
  carries the same partial-fill trap. Below n≥30 independent + span<14d.
  Revisit only if it beats H3/H4 after those mature — not now.
- Meme-bag-to-BTC correlation for `book.py` (extend the correlated-exposure
  view to the owner's DEX spot memes, measured on Tier A/B microcap OHLCV vs
  BTC) — genuinely new and additive in principle, BUT independent N = number
  of coins ≈ 20 < 30 (one corr number per coin); rolling-window corrs are the
  exact autocorrelation pseudoreplication trap seen 5× in this project;
  microcap history is survivorship-tinted over a broad meme-up era. Underpowered
  now. Becomes testable if the forward Tier-B universe grows past ~30
  independent live names — file as a FORWARD candidate, not testable-now.
- Holder-growth / organic-ratio / trader-velocity vs price-path (M9–M13/M16/
  M27/M30) — forward-only by construction (no historical API for these
  fields); collector ~1 day in. Gated.

**New-data (not testable on anything we collect):**
- M14/M15 (holder concentration, dev-wallet holdings/dev-sell) — GT `/trades`
  endpoint is reachable without a new key, but recent-trades-only in practice
  → a forward accumulation tracker + new engineering; not testable-now. The
  highest-reputation meme signal, blocked on data acquisition, not methodology.

**Live-bot risk mechanics (audited, now owner-decisions not hypotheses):**
- Kelly sizing, circuit-breaker, drawdown-tilt, liq-distance, shadow-ledger
  reactivation, decision-ledger — all tested/consolidated in
  `LIVEBOT_RISK_AUDIT.md`; findings are owner-gated CHANGES (exchange-side
  stops, notional cap on anti-predictive confidence, wire-or-delete 5 dead
  subsystems), not new testable hypotheses. Measurement-integrity audit closed
  clean. Exhausted.
- Maker-vs-taker execution — tested, confounded/era-unstable, verdict "don't
  build." Done.

---

## VERDICT

**The testable-NOW space is honestly exhausted except for ONE item** — the
micro-cap DEX execution-cost / size-vs-liquidity calibration (H-COST-1), which
is a RISK-mechanic / forward-evidence-integrity precondition, not a new edge.
It is worth running now precisely because it is the only work whose result
changes what the forward campaign can conclude later, and because it likely
fixes an understated risk number the co-pilot shows the owner today.

Everything with an "edge" flavour is either calibrated-null, on the kill list,
or forward-gated. **The real lever is not another swarm — it is letting the
forward clocks run** (H1–H6, the owner-call ledger once the owner actually uses
`call`, and the 26 forward micro-cap M-hypotheses as the collector matures).
The single most valuable non-test action right now is not on this queue at all:
**get the owner to fire `call` on his real trades** — that instrument has zero
data and is the highest-leverage forward evidence the project can accrue.
