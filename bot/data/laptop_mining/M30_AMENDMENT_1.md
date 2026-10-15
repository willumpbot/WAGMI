# M30 AMENDMENT 1 - panel (2 FATAL / several MATERIAL, all measured on the grid): two metrics were by-construction traps, the null was mis-specified, and the arms are now quantitatively pinned. Adopted before any code. The panel's preview already shows the real answer shape - a measured left-tail-for-mean trade, not an edge and not a null.

Measured foundations (panel, on the m28 grid, N=51,930 moment-sides / 176 coins / 149 days): A's
give-back fires on 33.0% of ALL entries, 56.6% of the MFE>=0.5R subset; 1R = 0.805 ATR median so A's
give-back distance is ~0.20-0.30 ATR (M12's WORST/noise-bound band); A and B are largely DISJOINT
(co-fire 1500 of ~5200 - keep both); **mean(A-runner) = -0.065R** (day-block SE 0.018 = 3.6x the
coin-week SE; act on day-block), and **A cuts P(<=-0.5R) from 0.664 to 0.492**. The real-vs-IID-control
residual and the two by-construction metrics are the fixes.

## FATALs closed
1. **P(banked anything > 0) DROPPED as a finding** - it is positive by construction (the give-back arm
   banks a strict superset of runner-banked moments). Replaced by metrics that CAN fail: the full
   net-R CDF arm-vs-runner (does A first-order stochastically dominate, or only trade left tail for
   right?), P(<=-0.5R) and median (the panel's measured tail shift), and P(net-positive AFTER the
   forgone-tail cost). The owner's "banked nothing" complaint is re-expressed as the deep-loss-rate
   P(<=-0.5R), which the give-back can fail to improve.
2. **NULL re-specified to preserve persistence.** The give-back trigger fires on PATH PERSISTENCE
   (MFE>=0.5R then retrace); the m14 IID martingale destroys persistence (real lag-1 |ret| autocorr
   ~0.25 vs ~0), so p_fire_real > p_fire_ctrl and a residual ~(p_real-p_ctrl)*m survives on a
   direction-null population - wick convexity reading as edge. Fix: the control is a CIRCULAR-BLOCK /
   stationary bootstrap (block length from the measured autocorrelation half-life) that preserves
   within-path persistence, plus the M14 vol_ratio diagnostic (post-trigger realized vol real/ctrl)
   printed per arm; any mean claim attaches to the persistence-preserving contrast, and the residual
   is bounded by |p_real-p_ctrl|*m and shown.

## Arm spec fixed
- **Arm A = DYNAMIC 50%-of-running-MFE give-back** (drop the "(to <=0.25R)" gloss - it was only the
  value at MFE=0.5R and made A ambiguous). Detection on the bar LOW (long) / HIGH (short), within-bar
  stop-first. A' = same at MFE>=0.75R.
- **B (half-at-0.75R) is the ATTRIBUTION CONTROL only** (trigger-vs-earlier-target); it is an
  interpolation inside M1's partial family M1 predicts is within-noise - never reported as a standalone
  "0.75R beats 1R" discovery (M1 closed that). **A' vs B** is the cleanest give-back-vs-immediate-take
  contrast (both condition on reaching 0.75R) - foregrounded.
- **A's remainder re-arms and re-banks at +1R** (stated; the +0.018R interpretation), then runs the
  1-ATR trail. **D precedence** specified: 0.75R partial first, then give-back on the remainder, then
  +1R bank, then trail - each leg's fraction stated.
- A is NOT M12's trail (the runner's trail is dormant below +1R - resolve_vec arms only at fav>=sf);
  but M12's 0.25-0.43 ATR noise band is A's binding quantitative prior and is cited.

## Metrics fixed
- **big-runner cost = subset by PATH MFE>=1.5R** (a property of the shared path), NOT runner-realized
  R (which selects on the comparator's exit). It is a DESCRIPTIVE COST figure (mechanically negative,
  ~-1.32R - "this is what capping the CASHCAT tail costs"), explicitly NOT a test (cannot come out
  positive - CLAUDE.md standard).
- Headline = net-R distribution contrast (mean with the WIDER day-block CI acting; CDF; P(<=-0.5R);
  median), family-adjusted across the arms actually carded. Null gate + positive control (persistence-
  preserving) first.

## Arms (e) + (f) - added by the server AFTER this panel; NOT reviewed here
(e) sibling-close (close/half other same-coin same-side in-profit plans when one hits target; +
cross-coin corr>=0.5) and (f) the clock on a PROTECTED runner (runner half after +1R, trail armed:
48h vs no-clock vs 72h; M10 measured WHOLE positions, M14 says re-open doesn't pay). Both get their
OWN focused panel pass before any build - (e) conditions on a sibling's target-hit (a point-in-time
event on a correlated position, M18 leak surface); (f) is a clean M10-adjacent question. Not folded
into the A-D build.

## Population + govern
retro=true closes join late_logged in the EXCLUDE-from-every-prereg list (RSR wide c0bf3a3124 retro
+0.785R is out of pooled stats; it stays the motivating case via its point-in-time MFE path). Seal the
confirmation split (m28 boundary). HYPOTHESIS cap; automatic rule needs SUPPORT + owner go; the live
give-back ALERT stays insight-only.
