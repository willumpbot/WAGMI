# Liquidation-Magnet Calibration — VERDICT: NULL (well-powered)

**Question.** Do liquidation-price *clusters* act as **magnets** — does price
subsequently gravitate toward a cluster of prior liquidations *more* than it
reaches a **distance-matched random level**? This decides whether `eye --deep`
may upgrade the "liquidation magnets (where stops sit)" framing from
attention/path-context to a "hint".

**Answer: NULL.** With a well-powered sample (n = 193 independent magnet
episodes, not underpowered), magnets are **not** reached more than
distance-and-side-matched control levels. The apparent "magnets get hit" is
the **proximity illusion** — nearby levels get hit regardless of whether a
liquidation cluster sits there.

## Numbers (main run, pre-registered params)
`K≥3` independent liq-episodes at a level, trailing window `W=12h`, distance
band `D=[0.30%, 3.00%]`, horizon `H=6h`, HL 5m candles, symbols BTC+SOL.

| metric | value |
|---|---|
| independent magnet episodes (n) | **193** (raw obs 701 → deduped) |
| placebo control candidates | 4062 |
| reach-rate MAGNET | **0.383** |
| reach-rate CONTROL (distance+side matched) | **0.410** |
| difference (magnet − control) | **−0.026** (magnets hit *less*, not more) |
| bootstrap 95% CI of diff | **[−0.096, +0.040]** (spans 0) |
| control also matched on realized-vol | 0.406 → diff −0.022 (spans 0) |
| two-proportion z p-value | 0.47 |

The magnet diff is not merely ~0 — it is slightly **negative**. Clusters carry
zero reach premium.

## Every moat guard (all load-bearing)
- **Distance-matched control (the crux).** Control reach-rate is the
  background "how often does price move distance D on side S within H" with
  **no** cluster there, reweighted to match the magnet (side, D-bin)
  histogram exactly. Removing proximity kills the effect → confirms it *was*
  proximity.
- **Vol-matched refinement.** Clusters form in high-vol bursts (→ more reach at
  any distance). Adding a realized-vol stratum to the match leaves the diff at
  −0.022, CI still spanning 0. Not a vol confound hiding a real effect either.
- **Independence dedup.** A standing cluster re-sampled every hour is not N
  independent episodes. Within (symbol, side, level-bin) episodes are kept ≥H
  apart so forward windows never overlap: 701 raw → **193 independent**.
- **Pseudoreplication.** Cluster *strength* counts independent liq-episodes
  (same-side events within 300s collapsed), not raw partial-fill rows — the
  lesson from `liq_hypothesis_harness.py`.
- **Entry-time-safe.** Clusters use only liqs with `ts < t`; reach outcome is
  strictly forward `(t, t+H]`. No look-ahead.
- **K sweep.** K∈{2,3,4}: diffs −0.042 / −0.026 / −0.003, every CI spans 0.
- **OOS (chronological split).** TRAIN diff −0.087, TEST diff **+0.048** — the
  sign **flips** between halves = pure noise, no held-out survival.
- **Per-symbol.** BTC diff −0.051, SOL diff +0.006 — neither symbol shows a
  consistent pull; not a single-symbol artifact.
- **Negative control (shuffled liq prices).** Mean diff **+0.043**. Note this
  is *not* exactly 0: the placebo construction (levels at D-bin centers vs
  magnets at actual cluster prices) carries a small ~+0.04 structural
  reach-bias unrelated to real clustering. The decisive point: the **real**
  data's diff (−0.026) sits *below* even this shuffled baseline — genuine
  clusters add nothing, so the true magnet premium is ≤ 0.

## Power / era honesty
Well-powered on episode count (n=193 ≫ 30). But it is **only ~5.6 days** of
feed (2026-08-01 → 08-06), so we cannot separate market *eras* — the OOS split
is early-week vs late-week, not distinct regimes. The verdict is "no effect in
this window", not "no effect ever". Thin symbols (FARTCOIN/WIF/kPEPE/…) were
excluded from the powered test; BTC+SOL carry the sample.

## Framing for `eye --deep` (use exactly this)
> Liquidation magnets show where stops are stacked — path context, not a
> prediction that price goes there. In-sample (BTC+SOL, ~5d) price reached
> clustered-liquidation levels no more often than distance-matched random
> levels (38% vs 41%, CI spans 0, sign flips out-of-sample). Read them as
> "where it could accelerate if tagged", not "where it's headed".

## Reproduce
```
python tools/copilot/liq_magnet_calibration.py          # SEED=1337, fixed
python tools/copilot/liq_magnet_calibration.py --no-net  # cache-only
```
`ast.parse` SYNTAX OK. READ-ONLY on all `data/`; the only writes are this repo
file, the `.py`, and an HL 5m-candle cache under the OS temp dir (never under
`data/`).
```
```
