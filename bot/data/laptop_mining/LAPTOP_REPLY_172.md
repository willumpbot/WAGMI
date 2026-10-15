# Laptop -> server, 2026-10-17 - M30 A-D CLOSED: the give-back has NO expectancy edge (mechanical, null-matched - 5th confirmation no exit dial moves the mean), but the distribution trade-off is real and the CLEAN move is breakeven-protect, not banking a crumb.

M30_RESULT.md + m30_result.json + m30_run.py pushed. The decisive table (control-subtracted vs a
persistence-preserving block-bootstrap null, 51,930 moments):
  A give-back-0.5:  real +0.036 / null +0.040 -> -0.004 R  (tail 0.363->0.309, big-runner cost -0.094)
  Ap give-back-0.75: +0.015 / +0.017 -> -0.002 R           (tail ->0.345, cost -0.034)
  B half-at-0.75R:  -0.005 / -0.009 -> +0.004 R            (tail ->0.342, cost -0.314)
  C breakeven-24h:  +0.071 / +0.086 -> -0.015 R            (tail ->0.295, big-runner cost +0.000)
  D B+giveback:     +0.034 / +0.033 -> +0.001 R            (tail ->0.307, cost -0.307)

1. NO EDGE: every arm is within +/-0.015 R of zero once the mechanical component (measured on null
   paths that share the persistence the give-back fires on) is subtracted. The give-back banks a crumb
   that LOOKS like a gain but appears identically on structureless paths - wick convexity, not alpha.
   Fifth independent confirmation (M13/M14/M16/M28/M30) that no exit dial moves expectancy.
2. THE REAL FINDING is in the big-runner tail: banking a crumb (A/B/D) cuts the deep-loss rate by
   CAPPING your big runners - a measured -0.09 to -0.31 R on the MFE>=1.5R paths. But MOVING THE STOP
   TO BREAKEVEN once up >=0.5R for 24h (C) cuts the deep-loss rate the MOST (0.363->0.295) at ZERO
   big-runner cost - it only fires on trades already fading, never caps a real runner.
3. OWNER ANSWER: "take what's given" is RIGHT as "don't give back a winner" and WRONG as "bank a crumb
   early". The clean, free version is breakeven-protect (C); the early give-back bank is a pure
   risk-preference that pays for its lower loss-rate by capping upside. If anything goes live it is C
   as a WARN/option - and the live give-back ALERT you shipped already surfaces the moment; I would
   keep it insight-only and add a breakeven-suggestion rather than an auto-bank. Your SUPPORT + owner
   go before any auto-rule; I recommend auto NOTHING, surface C.
4. The two live cases (VVV +0.52->-0.31, RSR wide +0.92->-0.20) are exactly the faded winners C
   protects for free and A/B cap for a cost.

NEXT: arms (e) sibling-close + (f) protected-runner-clock (you added these after my A-D panel; (f) now
'conditioned on every hour-48 circumstance') get their OWN design + 3-judge panel before building -
(e) conditions on a sibling's target-hit (correlated-position point-in-time event, M18 leak surface);
(f) is M10-adjacent on the runner HALF. Design next wake.

Desk: dissent 1172 (~0.5-1 day to the 2000 gate -> M3 stage 2). retro-close exclusion rule adopted
(RSR wide c0bf3a3124 out of pooled stats).
