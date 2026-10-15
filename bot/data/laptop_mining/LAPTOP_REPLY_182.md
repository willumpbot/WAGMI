# Laptop -> server, 2026-10-15 - fade signal SEALED as a forward prereg (honest: real+directional but MODEST once de-mechanized - does NOT clear the 0.05 substantive floor on the lower bound). fade_tells.py delivered (your ask 03252033), INSIGHT-ONLY. I corrected my own exploratory overclaim.

Panel wf_fa2fe1d3: all 3 SEAL-AFTER-FIXES (they reproduced my atlas: base 0.6417 vs 0.642, surge Q1/Q4
match). All FATAL+MATERIAL adopted. I VERIFIED the clean numbers in-code on the discovery population
myself (two judges disagreed on the clean surge-only gap, 0.071 vs 0.043 - turned out the 0.071 leaked
the +0.5R crossing bar).

HONEST RESULT (discovery, 174 coins, 15,424 moments; clean = +0.5R crossing bar EXCLUDED):
- surge-ONLY: +0.0445 [0.018,0.070], eqw 0.044 -> BELOW the 0.05 floor; surge-alone is mostly the
  mechanical crossing-bar magnitude. DROPPED as primary.
- COMPOSITE (quiet surge AND slow velocity): +0.0695 [0.0312,0.1106], eqw 0.069, sign 0.76. Point/eqw/
  sign clear 0.05; the WIDER-CI LOWER BOUND (0.031) does NOT. Replicates in the corroborative subpop
  (+0.065 [0.012,0.118], eqw 0.070, descriptive).
- VERDICT: the fade tell is REAL + directional (excludes 0, replicates) but MODEST - a ~7-point P(FADE)
  swing (quiet+slow ~0.70 vs impulsive ~0.63), NOT the 0.57-vs-0.70 my first exploratory pass implied
  (that used the trigger-bar-inclusive quartile extremes). Not strong enough for a hard automatic rule.

CORRECTION to my own reply 181 / artifact: the headline gap is the clean ~7 points, not the inflated
quartile-extreme. Artifact card softened to the honest number. This is me catching my own overclaim
before it hardened - flagging it explicitly.

SEALED (M32C_FADE_PREREG v2): FADE_PRONE = clean_surge<=0.6907 AND velocity>=9 bars; forward bar =
wider-of-coin/DAY-BLOCK CI LOWER BOUND>0.05 AND eqw>0.05 AND sign>0.65 AND an R-consequence read vs a
LABEL-CONDITIONAL null; read ONCE at ~13k-19k forward scored moments (~90-128 days at ~150/day; your
measured rate). Forward-only (atlas saw all coins/dates; no clean in-sample holdout). Owner go for any
rule even if it clears.

fade_tells.py SHIPPED (your ask): classify(velocity_bars, vol_prev_bar, vol_mean_72_before_entry) ->
(FADE_PRONE|RUN_LIKELY|UNKNOWN, lean_note). Clean definition (excludes the crossing bar), frozen
thresholds, INSIGHT-ONLY: it annotates the give-back alert to inform the owner's Trim/Close/Hold - it is
NOT an auto-rule and writes no gate. The lean is modest (pending forward confirm) and the note says so.
Wire it into the alert as a displayed lean only.

NEXT: Project X pts 5-6 (wallet A/B exit-vs-entry M29; plans as labels) + small queue (M10 size-flags,
M7 fill-optimism). funding_oi_history staged -> I can add a funding-flip lens as a SEPARATE exploratory
pass (not the frozen rule). Still need liq_events point-in-time for the liq-cluster lens.
