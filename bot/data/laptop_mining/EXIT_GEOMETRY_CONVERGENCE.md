# CONVERGENCE (laptop -> server, 2026-10-15): 7 independent exit-geometry studies are now ALL NULL on expectancy. The edge is NOT in how we exit. Stop commissioning exit-rule missions; the one exception is breakeven-protect. Redirect to entry/selection + the two live warn-only levers.

This is a steering note, not a new result - it consolidates a completed thread so the relay doesn't keep
sending exit-tweak missions (the last three - give-back, protected-runner-clock, sibling-close - were all
exit tweaks, all null).

## The 7 nulls (each control-subtracted vs its own persistence-preserving null; MDE stated; gates passed)
1. M13 conditional-exit dials - NULL (no at-entry/entry-mechanic dial moved expectancy).
2. M14 re-entry - NULL.
3. M16 entry-mechanic exit variants - NULL.
4. M28 direction/exit on the moment grid - direction is noise; exit geometry NULL.
5. M30 A-D give-back ("take what's given") - raw +0.036R matched by null; control-subtracted ~0.
6. M30 (f) protected-runner-clock - PRECISE null at every age 12-30h; forward expectancy past the
   half-fill is flat.
7. M30 (e) sibling-close - main contrast NULL; the one positive cell was an entirely SAME-SIDE
   by-construction artifact (opposite-side, the clean contrast, was strongly NEGATIVE -0.28R).

## The ONE exception (and why it is not a contradiction)
BREAKEVEN-PROTECT (M30 A-D arm C): move the stop to breakeven once a trade is up >=0.5R and holding.
It cut the deep-loss rate the MOST at ZERO big-runner cost - because it fires ONLY on trades already
fading, so it never caps a real runner. It is not an expectancy edge either; it is a FREE distribution
reshaping (lower deep-loss rate, no upside given up). Everything else that reshapes the distribution
pays for it by capping runners (-0.09 to -0.31R).

## Why exits can't move the mean here (the mechanism, so this isn't just an empirical coincidence)
Once a position is open, the remaining path is (to our measurement) a martingale in R: MFE convexity
that any trigger harvests is reproduced on persistence-preserving null paths, so it is mechanical, not
edge. Banking early, clocking, or closing-on-a-sibling all just move mass around a fixed mean - they
trade tail for upside at ~zero net. The only free lunch is protecting a stop on trades that have
ALREADY told you they are fading (breakeven-protect), because that conditions on realized weakness, not
on a guess about the future.

## Where the levers actually are (already shipped / open)
- ENTRY / SELECTION: this is where expectancy lives (M28 showed direction-at-entry is the hard part;
  the preregs PREREG_PARTIAL_EXIT / PREREG_CALLER_FORM are the open forward tests, gated by n).
- M17 CARRY atlas - LIVE warn-only lever (carry is forecastable via trailing-24h mean).
- M18 CONCURRENT RISK - LIVE warn-only lever (same-direction corr>=0.5 positions stop together ~1.7x
  pairs / ~3.3x triples). NOTE: M30 (e)'s same-side big-cell "edge" is THIS phenomenon re-seen, not a
  new one - a correlated same-coin peak. It is already covered by the M18 warning.
- The next confirmatory study in the queue is M3 stage 2 (dissent x funding), gated at dissent_log
  >=2000 rows - a SELECTION-side model, correctly not an exit study.

## Ask of the relay
Before sending an exit-rule mission, check it against this note - if it is "exit the runner differently"
it is very likely another null and the laptop will say so after a full panel + run. Missions that move
the needle: better ENTRY selection, or refinements to the M17/M18 live warnings. The live give-back
ALERT stays insight-only; no automatic exit rule ships without my SUPPORT + the owner's go, and none is
currently supported except (optionally) surfacing breakeven-protect as a suggestion.
