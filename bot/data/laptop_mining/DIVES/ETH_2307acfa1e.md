# DIVE — ETH LONG 2490 / stop 2385 / target 2598 (plan `2307acfa1e`, conviction hold: expiry ~367 DAYS)

_2026-10-15. 3 miners + adversarial verifier; every number below survived independent re-derivation
(two claims were killed and do not appear; both anchors — export mark 2416.85 / last close 2411.10 —
stated where they differ). Paper position. Engine: runner (half at +1R, 1-ATR trail, floor at stop)._

## State (verified)
- **r = −0.697** at the export mark (engine sim −0.698 at the bar close — pure mark timing, zero
  divergence). +1R (2595) never printed: MFE +0.45R (high 2537.4), **MAE −0.85R (low 2401 — within 16
  points of the stop)**. ~51.5h in trade.
- **The stop is 0.30–0.36 ATR away** (1.08% from last close / 1.32% from mark); +1R is 2.1 ATR (7.6%)
  above. ATR14 87.94, 59th pctile, **rising**.
- **The 367-day clock is irrelevant: time is not the binding constraint, the 1.3% stop gap is.** M10's
  48h findings do NOT apply to this plan (every other plan defaults 48h; this one's time-limit leg is
  unreachable in practice). Under runner the target (2598) is decorative — exits are the stop or the trail.

## The decision number (verifier-rebuilt from scratch, exact match)
From today's distance, over all 212d of ETH history (n=1,271 4h starts, 1,268 resolved, eqw-by-day
beside pooled): **84.5% of unlimited-time paths hit the stop before +1R; 15.5% (15.4% eqw) survive to
+1R.** From the fresher close the odds are slightly worse. For contrast, the ORIGINAL entry race
(4.22% down vs 4.34% up) was roughly fair at 14–30d horizons (stop-first ~45%, target-first ~50–53%) —
**the race was lost inside the trade, not at entry.** (A claimed 48h stop-edge was killed in
verification: dead heat; the implementation sensitivity exceeded the claimed edge.)

## Carry — the opponent in the branch where the trade survives
- At the **90d-mean** funding this long pays ~2.45 bps/day ≈ **8.9%/yr ≈ 2.1× the entire net target**
  over the hold window; at the 7d mean ~1.0× the target.
- BUT funding just flipped: current print is **negative (7.5th pctile of 368d)** — the long presently
  EARNS ~6%/yr. 7d mean is 58% below the prior 30d. If the negative regime persists, the long is paid
  to wait; if funding mean-reverts, carry consumes the thesis. (Convention inferred from cadence + the
  HL baseline magnitude — flagged, not confirmed from collector source.)
- Backdrop (weak-evidence windows, stated): whale cohort net short −$455M (5L/11S, 6-day window, ~60
  wallets); Bybit long-side liq flushes 2.4–3.2× the (7-day) median three days running; book
  near-balanced with a mild bid tilt (depth_all, 3 day-shards). BTC beta 1.24, R² 0.79 — the 4.22% stop
  is a ~3.4% BTC down-move.

## Forward geometry (engine-verified)
A +1R print instantly locks ≥ **+0.625R**: the trail arms at best−ATR = 2516.34, already above entry
(sim fills at the trail level — a real gap fills worse; caveat carried). Trail reaches
breakeven-on-the-runner at best 2568.66. Below +1R the full position rides the 2385 stop.

---
**What matters:** the trade lives on top of its stop — 0.3 ATR away after a −0.85R excursion, with
84.5% of history-shaped paths stopping before +1R from here; the year-long clock changes nothing, and
carry only matters in the 15% branch (currently a small tailwind, structurally a 2× headwind).
**What would change the plan:** nothing mechanical — but the owner should know this plan's exit is
almost certainly the stop or a +1R-then-lock, not the 2598 target, and that a conviction hold at 3×
with a 1.3% stop gap is a coin-flip-weighted-against geometry, not a patience trade.
**Confidence:** high on geometry/race/sim (verifier-rebuilt exactly); medium on flow (short windows,
inferred funding convention — both stated).
