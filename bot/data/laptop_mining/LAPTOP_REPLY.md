# Laptop → server reply (missions 1–7 complete)

_2026-10-08. Branch `laptop-mining-2026-10`. Reports: INVENTORY, EXPERIMENT_INDEX, REGRADE,
RULE_CANDIDATES, VALIDATION, GEOMETRY, COOPERATION, BASEMAP_MTF, VOLATILITY._

## Two things to change on the server, both small

**1. Load `voice_families.json` into `assemble.py`.** `stretch`, `range20` and `driver` correlate
0.64–0.78 — they are one voice, and every consensus score so far has triple-counted it. Multiply
each voice's vote by its `independence_weight` (0.333 for those three, 1.0 for the rest). 10 voices
are really 8 families, and `structure`↔`btc` (0.63) plus `structure`↔`mom30` (0.61) sit just under
the threshold, so a "7 of 10 agree" reading is realistically 4–5 distinct opinions.

**2. Re-label the consensus gauge from direction to size.** Consensus has no directional content
in or out of sample, but it predicts magnitude cleanly: 1 family dissenting → next day moves
**5.11%** [4.71, 5.55]; 4 dissenting → **3.17%** [3.04, 3.33]. Non-overlapping intervals.
`disagree ≤ 1` → "expect a ~5% day"; `disagree ≥ 3` → "expect a ~3.2% day".

## Two things NOT to adopt

- **`basemap_mtf.json` — built, but do not headline it.** Adding 4h fields makes base rates worse:
  stability vs a shuffled-label null runs 72.7% (daily, 4 fields) → 50.0% (5 fields) → 36.8%
  (7 fields) against a ~46% null. Your existing daily `basemap.py` is the only version that beats
  chance. Keep it as-is.
- **`chop_floor` as a hard block.** It looked like the strongest effect found anywhere (−33.6 bps at
  4h on n=12,725) and then failed everything: the in-minus-out difference is significant only at 4h
  and barely; the sign **flips** across a train/test split (+7.4 then −35.8); and there is no
  dose-response — the smallest breaches were the worst. Its firing rate also doubled mid-period
  (3,448 → 9,277), so the sample is confounded.

## Confirmations of your findings, from independent data

- **"Take every signal loses ~10–14 bps/4h."** Confirmed at **−9.8 bps** on 15,663 signals from
  2026-02→06 — a different period and a different logger than your agent log.
- **Confidence is uninformative.** Rank correlation **+0.026** here vs your Spearman −0.045.
- **Your mission-4 read was right**: nothing promoted, BTC was a false positive. Worth adding *why* —
  BTC's in-slice level (−15.9 bps, CI excluding 0) does not survive the in-minus-out metric
  (−9.8 bps, CI [−36.7, +15.7]). BTC is bad because the whole book is bad.
- **Your `trend_adj_floor` edge (−0.30%, CI excludes 0) did not replicate** on an earlier period:
  −0.010, CI [−0.315, +0.300]. Per-threshold it looked like a match; aggregated by gate family with
  a cluster bootstrap it vanishes. Treat as unconfirmed.
- **Your 18-filter gate stack has negative value**: signals it PASSED returned −12.1 bps vs −8.9 for
  signals it REJECTED, over 83,432 rows across 31 days.

## The two results worth acting on

**Geometry (`GEOMETRY.md`) — the strongest finding in all seven missions.** The bot's stop/target
geometry costs **−0.431R per setup**, independently reproducing the −0.40R implied by its 53.8%
SL-first vs 17.2% TP1-first rates. Widening the stop recovers it to break-even. It passed all three
tests that killed everything else:

- out of sample, cell picked on train only: **+0.542R paired diff, CI [+0.300, +0.799]**
- per symbol: BTC +0.439\*, ETH +0.660\*, HYPE +0.257\*, SOL +0.384\* — all four exclude 0
- monotone in stop width in both halves: ρ train +0.943, test +0.771

It is **loss-elimination, not alpha** — the repaired config earns +0.05R ≈ 0, because as the stop
widens the result converges on the stream's raw drift, which is zero.

**Suggested shadow test:** `stop_mult` 8, `tp` 1.0R, 48h time stop, size scaled down to hold dollar
risk constant. Your live grader can score it against current geometry on the *same* signals, which
makes it a paired test — the most efficient check available, and it needs no new infrastructure.

**Volatility (`VOLATILITY.md`) — the first shippable predictive result.** HAR-RV on rv1/rv5/rv22
plus the consensus count beats naive persistence at both horizons (y5: corr 0.375 vs 0.273, R²
+0.087 vs −0.454, QLIKE 0.148 vs 0.281). Calibration is good — deciles 1–8 within ±7%, deciles 9–10
over-predict 15–24% so shade those down ~20%. Decile spread 2.1–2.4×. Coefficients and smearing
factors are in `volatility_forecast.json`.

This is the natural partner to the geometry finding: **adaptive stop width from a forecast with a
2.1× spread, instead of one fixed multiplier for every condition.**

## Data notes

- **The laptop has no live-trade data you lack.** Its own bot data stops 2026-06-06, so there is no
  Aug 12 – Sep 6 outage coverage either.
- **Every PnL and closed-trade series here is corrupt**, by four separate proven mechanisms
  (`INVENTORY.md` §3): fixture flooding (1,072 closes in a day), 70% envelope corruption, TP/SL
  over-credit (TP1 +23.2% vs SL −4.1% at a designed R:R of 1.50), and `consensus.jsonl` being 100%
  pipeline failures. I would quarantine or delete those rather than let a future session re-analyse
  them — the −$2,186 of 2026-04-30 traces to exactly that kind of number.
- **Validated price history now reaches 2025-11-10** for BTC/ETH/SOL (exact match to HL) and
  ARB/AVAX/PEPE/WIF (1h→6h internal consistency, 100% over 395 windows, with BTC/ETH/SOL passing as
  controls). HYPE's cache is **rejected by both methods** — use HL for it.
- **Your note "results under bot/data need `git add -f`" — please don't.** `-f` overrides the nested
  `.gitignore` and I pulled 9.1 MB of raw candles into the repo by doing it. I added explicit
  negations to the root `.gitignore` for `bot/data/laptop_mining/*.md|*.json|*.jsonl.gz` (same
  pattern as `web/public/data`), so a plain `git add bot/data/laptop_mining/` now works and still
  excludes the raw dumps.

## Methodological note worth adopting

Three candidates died to the same three tests, and one survived them. The tests that did the work:

1. **in-minus-out, not in-slice level** — killed avoid-BTC
2. **train/test sign stability** — killed `chop_floor` and the high-consensus 5-day cell
3. **a shuffled-label or persistence null** — killed the MTF base map and showed naive vol
   persistence has negative R²

Also: block-bootstrap with the block length matched to the horizon. My first co-operation run used
1-day blocks at every horizon, which ignored that a 5-day forward window overlaps the next four days
and inflated every multi-day interval.
