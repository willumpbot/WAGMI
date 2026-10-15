# M15 — DEFERRED by its own pre-authorized rule, and the panel found something better than the study: Bybit liquidation prints are BANKRUPTCY prices, displaced 0.3–1.4% beyond the traded range.

_2026-10-16. The design (896020c8) pre-authorized DEFER if the measured population was too small; the
3-judge panel measured it and it is. No harness was built; nothing was read. 5 FATALs apiece from the
construction and leaks judges, all adopted into this deferral._

## Why deferred (measured, not estimated)
- **262 eligible entry-sides over the ENTIRE feed → 107 chains** after the design's own dedupe, across
  13 coins with only 5 having ≥ 10 chains. Scaling M14's measured MDE: **~0.27 R per cell at n≈107**,
  vs a plausible stop-placement effect ≤ 0.1 R, before the z ≥ 3 family penalty. Anything that "cleared"
  would be ~3× winner's-cursed.
- **Accrual: ~10 chains/week measured.** Target for MDE ≤ 0.1 R ≈ M14-scale n ≈ **~2 years of feed** at
  current coverage — or much sooner if the liq feed widens beyond Bybit's 13 symbols. Re-open trigger:
  ≥ 1,500 chains, recomputed from the then-current accrual.

## Design defects the deferral also absorbs (so the future version starts right)
1. My mechanism gate **could not pass by construction** (hit rates are monotone in stop distance under
   any price process; the arms are distance-ordered). The correct mechanism test is the calibration
   study's own matched-random method: excess sweeps at C vs a same-side, distance-matched random level.
2. **S1 "inside" was degenerate**: a 0.25 × DAILY-ATR offset vs a median cluster distance of 0.73% puts
   the stop BEHIND entry for 86.3% of entries. Offsets must live on the engine's bar scale or be a
   fraction of the cluster distance itself, with a pre-stated sf floor.
3. **S0 is always the widest and always beyond C** (100% of eligible entries) — S_i−S0 contrasts are
   width contrasts, not placement contrasts; the rule's claim lives in S3−S2, which must be in the
   pre-registered family.

## 🔴 The transferable finding: the bankruptcy-price displacement (reported to the PC)
Measured on 45,103 Bybit prints matched to HL 5m candles: **76–90% of liquidation prints fall entirely
OUTSIDE the containing candle's high–low range**, side-signed — liquidated longs print 0.19–0.51%
BELOW the HL low, shorts the mirror ABOVE the high (BTC −0.233/+0.236, SOL −0.321/+0.343; memecoins up
to ~1.4%). That is the bankruptcy-price signature, and it displaces every cluster level AWAY from entry
in exactly the stop direction. Consequences beyond M15: **any absolute use of liq_events price levels —
including the live hivemind liq-magnet chips — shows levels ~0.3–1.4% beyond where the market actually
traded.** The prior magnet calibration stays valid (it was internally consistent: displaced levels vs
distance-matched randoms in the same space); absolute placement semantics are not. Fix available and
point-in-time computable: de-bias per symbol per side against HL candle extremes, or define cluster
levels from the HL traded extreme within each episode's window.

---
**What matters:** M15 cannot be answered yet (107 chains vs ~1,500 needed), and the attempt surfaced a
0.3–1.4% systematic in the liquidation feed that affects live displays today.
**What would change things:** the PC de-biasing magnet levels (one measurable offset per symbol/side),
and the feed widening past Bybit.
**Confidence:** high — every number above was measured by the panel on the real data, not estimated.
