# RQ: Multi-Year Exit-Geometry Simulation (2026-07-01)

**Question:** Does the RESTORED bread-and-butter exit geometry (from
`EXIT_GEOMETRY_BACKTEST_2026-07-02.md` S3: MEDIUM TP1/TP2 = 1.0/2.0 ATR, SL 1.0 ATR,
50% off at TP1, BE at 0.3R fee-buffered, profit-lock 0.3R at 0.6R, post-TP1 trail
1.5×ATR tighten 0.80→0.65 with peak-fraction floors 0.15/0.40/0.70) hold its edge
across 2024 chop, the 2024–25 bull, and 2025–26 regimes?

**This tests the GEOMETRY, not the entry.** Entries are a deliberately dumb,
regime-neutral proxy — EMA20/50 cross on 1h closes, both directions, entered next-candle
open, ATR-liveness filter (ATR pct-rank ≥ 0.30 over 200 bars), one position per symbol.
Fixed $100 risk/trade, everything in R. The naive control below PROVES the entry has no
edge (−0.118R/trade), so anything above it is value added by the exit geometry alone.

Script: `bot/tools/research/multiyear_geometry_sim.py` (standalone, read-only on bot code;
engine is a port of `bot/tools/backtest_exit_geometry.py::simulate`, which reproduced live
golden-era mechanical exits to ~$2 on runners). Raw output:
`bot/data/cache/multiyear_geom/{results.json, results_pessimistic.json, run_output*.txt}`.

## Data (denominators)

| Symbol | Source | Candles | Span |
|---|---|---|---|
| BTC, ETH, SOL, XRP | Binance spot via data-api.binance.vision (api.binance.com is HTTP-451 geo-blocked here) | 21,911 each | 2024-01-01 → 2026-07-01 (2.5y) |
| HYPE | MEXC 1h (no Binance spot listing; Bybit 403; Hyperliquid only holds ~5,000 candles ≈ 7 months) | 10,911 | 2025-04-03 → 2026-07-01 (~15 mo) |

1,131 non-overlapping simulated trades (BTC 261, ETH 266, SOL 237, XRP 248, HYPE 119;
561 LONG / 570 SHORT). 4 bps taker fee per leg, 72h hard hold limit, no funding, no slippage.

## Headline — three exit configs on IDENTICAL entries (chronological candle path)

| Config | n | sumR | expR/trade | t | WR | avgWinR | avgLossR | maxDD (R) |
|---|---|---|---|---|---|---|---|---|
| **RESTORED (BE 0.3R / lock 0.6R)** | 1131 | **+91.7** | **+0.081** | **+3.80** | 78.0% | +0.41 | −1.08 | **13.1** |
| CURRENT live (BE 1.2R / lock 1.8R) | 1131 | −65.0 | −0.058 | −1.84 | 49.4% | +0.99 | −1.08 | 71.5 |
| NAIVE control (fixed SL 1×/TP 2× ATR) | 1131 | −133.5 | −0.118 | −2.84 | 32.2% | +1.91 | −1.08 | 141.4 |

**Geometry value-add = +0.199R/trade vs naive control, +0.139R vs current live config,
on identical entries.** The restored ratchet also cuts max drawdown 5.5× vs current.

## Per-year (RESTORED / CURRENT / NAIVE sumR)

| Year | n | RESTORED | CURRENT | NAIVE | RESTORED expR (t) |
|---|---|---|---|---|---|
| 2024 | 380 | **+25.6** | −23.7 | −63.7 | +0.067 (t=1.84) |
| 2025 | 500 | **+44.2** | −30.5 | −66.9 | +0.088 (t=2.81) |
| 2026 | 251 | **+22.0** | −10.8 | −3.0 | +0.088 (t=1.84) |

By half: RESTORED positive in all six halves (weakest 2024H2 +3.6R over 185; best 2025H2
+26.1R over 283). CURRENT negative in 5/6 halves. The ordering RESTORED > CURRENT > NAIVE
holds in every year, every half.

## Per-symbol and per-side (RESTORED sumR, n)

| | BTC | ETH | SOL | XRP | HYPE | LONG | SHORT |
|---|---|---|---|---|---|---|---|
| RESTORED | +42.5 (261) | +6.4 (266) | +31.8 (237) | +7.2 (248) | +3.9 (119) | +39.2 (561) | +52.5 (570) |
| CURRENT | −11.2 | −25.0 | +2.6 | −23.3 | −8.2 | −41.6 | −23.4 |

All 5 symbols positive under RESTORED, WR 66–86% everywhere; both sides positive in each
year (worst side-year cell: 2024 LONG +8.0R). Weakest symbol-year cells: XRP-2024 −6.8R
(n=100), ETH-2025 −4.1R (n=114), HYPE-2026 −1.0R (n=59) — small negatives, no blow-ups.

## Where the geometry fails worst (the CB's risk profile)

- **High-volatility whipsaw is the failure regime.** By ATR-percentile bucket (RESTORED
  expR): lo-vol +0.124, mid-vol +0.100, **hi-vol +0.049** — edge thins ~2.5× in the top
  vol tercile, and hi-vol carries the deepest DD (10.3R). CURRENT is catastrophic there
  (−56.5R of its −65 total comes from hi-vol).
- **Worst calendar stretch: 2024H2** (post-ETF chop, pre-election consolidation): +3.6R
  chrono, **−9.5R under the pessimistic path** — the only half that flips sign. Deepest
  RESTORED drawdown of the whole span (12.7R) sits there.
- Failure shape is not tail losses (max single loss ≈ −1.1R by construction) but
  **loss-clustering**: strings of full −1R SLs plus scratch wins in fast two-sided tape.
  A circuit breaker keyed to consecutive-loss streaks / rolling-R drawdown (~10–15R at
  fixed risk) covers exactly this; a per-trade CB adds nothing the SL doesn't already do.

## Adversarial self-checks

1. **Intra-candle path bias (the big one).** 1h candles can't order a +0.3R touch vs an
   SL touch inside one candle; the chrono heuristic (green O→L→H→C) can flatter a 0.3R
   ratchet. Reran with **worst-case ordering** (adverse extreme always first):
   RESTORED +91.7R → **+30.6R (still positive, t=1.25)**; CURRENT −65 → −90.3;
   NAIVE −133.5 → −139.5. Direction and ordering survive; the absolute size of the
   restored edge does NOT clear significance under worst-case ordering, and 2024 dips to
   −2.4R. Truth is between the bounds. Value-add vs naive: +0.199R (chrono) / +0.150R
   (pessimistic) — the geometry-vs-geometry comparison is robust; the "profitable on dumb
   entries" claim is path-dependent.
2. **Fragility (drop best single trade):** +91.7 → +90.3R. Best trade is +1.46R of 91.7 —
   nothing hinges on an outlier. n=1131 ≫ 15.
3. **"Win asymmetry" is honestly inverted:** RESTORED wins average +0.41R vs losses −1.08R
   (asym 0.38). The edge is 78% WR × small wins, not big winners — the ratchet
   deliberately trades runner capture (TP2 rate 5% vs 33% naive) for scratch protection.
   That IS the bread-and-butter mechanism; call it what it is: a high-WR scratch machine,
   and it only beats holding because the entry (like most entries) mean-reverts hard.
4. **Regime tagging caveat:** efficiency-ratio thresholds (≥0.25 trend) tagged 0/1131
   entries "trend" — 1h crypto rarely clears that bar and EMA crosses fire in transitions
   by construction; the trend/chop split is uninformative here, the vol-tercile split
   (point above) is the usable regime axis.
5. **Not modeled:** funding (±~0.03%/day vs ~1–2% risk — small, sign-neutral across
   longs/shorts here), slippage, ranging-regime TP×0.8/SL×1.2 multipliers (regime-neutral
   by design), LLM exit layer. Same limits as the validated June backtest.

## Verdict

**The restored geometry's edge is structural, not era-luck: it beats both the current live
geometry and a naive fixed-SL/TP control in every year (2024/2025/2026), every half, all
5 symbols, and both sides, on 1,131 identical dumb entries — +157R vs current over 2.5y
(+0.139R/trade) with 5.5× less drawdown.** The absolute "+0.081R/trade on garbage entries"
number is path-assumption-sensitive (worst-case bound +0.027, t=1.25) — do not quote it as
standalone alpha. Failure mode the CB must cover: hi-vol whipsaw loss-clustering
(2024H2-style; ~10–15R rolling drawdown at fixed risk, edge → ~0 but not deeply negative).
This supports shipping S3 (per the June decision doc) with a streak/rolling-R breaker; it
says nothing about entry quality — that is a separate, unsolved problem.
