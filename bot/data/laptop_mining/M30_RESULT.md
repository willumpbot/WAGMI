# M30 - "take what's given": the give-back has NO expectancy edge (its apparent gain is mechanical - matched on persistence-preserving null paths), but the distribution trade-off is real and separates the arms. The clean move is BREAKEVEN-PROTECT, not banking a crumb.

_2026-10-17. m30_run.py to M30_AMENDMENT_1. EXPLORATORY, HYPOTHESIS cap. 51,930 moments / 176 coins.
Null = persistence-preserving circular-block bootstrap (block 6) - NOT IID, because the give-back
fires on persistence. Metrics per Amendment 1 (P(banked>0) and runner-realized-subset dropped as
by-construction). Automatic rule needs SUPPORT + owner go; the live give-back ALERT stays insight-only._

## 1. The null gate caught it: the give-back's "gain" is mechanical
Raw paired (arm - runner) vs the SAME arms on persistence-preserving null paths:

| arm | raw mean | null mean | CONTROL-SUBTRACTED (real-null) | big-runner(MFE>=1.5R) cost |
|---|---|---|---|---|
| A give-back-0.5 | +0.036 | +0.040 | **-0.004** | -0.094 R |
| Ap give-back-0.75 | +0.015 | +0.017 | **-0.002** | -0.034 R |
| B half-at-0.75R | -0.005 | -0.009 | **+0.004** | -0.314 R |
| C breakeven-after-24h | +0.071 | +0.086 | **-0.015** | **+0.000 R** |
| D B+give-back | +0.034 | +0.033 | **+0.001** | -0.307 R |

**Every arm is within +/-0.015 R of zero once the mechanical component is subtracted.** The give-back
trigger banks a crumb that LOOKS like a gain but appears identically on structureless null paths -
it is wick-convexity, not edge. This is the FIFTH independent confirmation (after M13/M14/M16/M28) that
no exit dial moves expectancy. "Take what's given" as banking an early partial does NOT beat the runner
on mean R.

## 2. But the distribution trade-off is real - and it is NOT the same for every arm
All arms cut the deep-loss rate P(<=-0.5R) from the runner's 0.363, but the PRICE in the big-runner
tail (path MFE>=1.5R, the CASHCAT paths) differs by an order of magnitude:
- **C (move stop to breakeven after 24h up >=0.5R): P(<=-0.5R) 0.363 -> 0.295 at ZERO big-runner cost
  (+0.000 R).** It only ever triggers on trades already drifting back to flat, so it never caps a real
  runner. This is the Pareto-best reshaping.
- A (give-back-0.5): 0.363 -> 0.309, but costs -0.094 R on the big runners (it banks half on some
  trades that would have run).
- B / D (half at 0.75R): cut the tail similarly but cost -0.31 R on the big runners - they cap hard.

## 3. The owner-facing answer
"Take what's given" done as BANKING A CRUMB (A/B/D) buys a lower deep-loss rate by capping your big
runners - a real, measured cost (-0.09 to -0.31 R on the paths that would have run). It does NOT add
expectancy. Done as REFUSING TO GIVE BACK A WINNER - move the stop to breakeven once you're up (C) -
it cuts the deep-loss rate the MOST and costs essentially NOTHING on the big runners, because it only
fires on trades already fading. If anything from M30 goes live, it is the breakeven-protect, as a
WARN/option; the early give-back bank is a pure risk-preference with a measured upside cost and no
expectancy gain. The two live cases (VVV +0.52R->-0.31R, RSR wide +0.92R->-0.20R) are exactly the
"faded winner" C protects and A/B cap - but on 51,930 moments the protection is free and the banking
is not.

## Limits
Direction-null population (M28 closed direction); fills at levels (optimistic); C's breakeven approx
floors the runner outcome at 0 on the drift-back subset (stated); the control-subtracted means carry
the wider of coin/day-block CI (all cover or nearly cover 0); HYPOTHESIS cap; arms (e) sibling-close
and (f) protected-runner-clock are a SEPARATE study (own panel) - not in this A-D read.
