# M30 (e)/(f) DESIGN - the two arms the PC added AFTER the A-D panel: (e) sibling-close (close when a same-coin plan exits at target) and (f) protected-runner-clock (a time-cap on the runner half, "conditioned on every hour-48 circumstance - mine it extremely"). SEPARATE study, own panel, before any build.

**Status: DESIGN. EXPLORATORY, HYPOTHESIS cap.** These were explicitly carved out of the A-D read
(a4cbdffd, 072ac408, 2c23f5da) because each opens a leak surface the A-D panel never vetted. Panel
first; an automatic rule ships only on my SUPPORT + the owner's go. A-D's verdict stands as the prior:
on 51,930 moments every give-back arm's raw mean was MATCHED by its persistence-preserving null
(edge ~0), so the deliverable here is again the TRADE-OFF, and the null/control gate decides what is
real vs mechanical.

## 0. Why these two are a DIFFERENT object than A-D
A-D conditioned only on THIS position's own path (its own MFE/give-back). (e) and (f) condition on
information A-D never touched:
- **(e) conditions on a SIBLING position's outcome** - a different open plan on the SAME coin hitting
  its target. That is a correlated-position event = the M18 co-stop leak surface. If the sibling's
  target-hit is read at or before this position's decision bar, fine; if it is read from a bar LATER
  than the decision, (e) is look-ahead and the whole arm is an artifact.
- **(f) conditions on the runner HALF having been protected and then times it out** - M10-adjacent
  (time-stop) on a path already selected by "reached +1R, took half, trailing". Selecting on "already
  a winner at hour k" and then measuring the remainder is a conditioning-on-the-outcome trap unless the
  clock is applied to EVERY qualifying runner at a FIXED wall-clock age, not to the ones that later
  faded.

## 1. Arms (runner = control, same m28 moment machinery, point-in-time em/ATR, leg fees, carry)
- **CONTROL = runner** (half @ +1R, 1-ATR point-in-time trail, 48h) - the live default, as in A-D.
- **(e) sibling-close**: a position is closed at the bar a DIFFERENT same-coin plan first reaches its
  own +1R target, IF that target-hit bar is <= this position's current bar (point-in-time; a sibling
  cannot close me on information from my future). On the random-both-sided grid a "sibling" is the
  nearest other entry on the same coin whose window overlaps; the close price is this position's price
  at that shared bar. Reported vs the runner on the subset where a qualifying sibling exists (n stated;
  the rest of the grid is unaffected and excluded from (e)'s contrast).
- **(f) protected-runner-clock**: among moments where the runner took its half at +1R and the remainder
  is still open (= "protected runner"), close the remainder at a FIXED age T after the half-fill, for
  T in {12h, 18h, 24h, 30h} swept. The clock applies to EVERY protected runner at age T regardless of
  whether it later ran or faded (no outcome selection). "Mine it extremely" = report the full T sweep
  plus the conditional slices the owner means by "every hour-48 circumstance": by hour-of-fill bucket,
  by whether MFE-since-half is positive at T, by funding sign on the remainder - all DESCRIPTIVE, each
  with its own n, none a verdict.

## 2. The leak guards that are THIS study's whole risk
- (e): the sibling target-hit index must be strictly <= the decision index. Build the sibling map from
  entry/target times only; assert max(sibling_hit_idx - decision_idx) <= 0 before any read. A sibling
  that hits AFTER is not an event yet - it cannot act. Fire the arm on null paths too (a sibling
  "target hit" on a structureless wick must be reproducible) - the null gate catches "(e) harvested
  the sibling's wick".
- (f): the clock age T is measured from the half-fill bar, a point-in-time event; the remainder's
  outcome from T onward is the only thing read. The positive control: inject a known decay into the
  post-T remainder and recover it; the null gate: the SAME fixed-age close on persistence-preserving
  null remainders must show the mechanical component, which is then subtracted (exactly as A-D showed
  the give-back's apparent +0.036R was mechanical).

## 3. Metrics - the trade-off, control-subtracted, never the raw mean
Per A-D's lesson: report (arm - runner) in R AND (arm - null) in R; the headline is the
CONTROL-SUBTRACTED number with the wider of coin/day-block CI. Plus, for each arm:
- (e): P(<=-0.5R) shift and big-runner (runner MFE>=1.5R) cost - does closing on a sibling's win cap
  your own runner? Expectation from A-D + M18: mean ~null, tail cut paid for in the big-runner subset.
- (f): the T-sweep curve of control-subtracted mean and big-runner cost vs T; the owner's question is
  "is there a T where the remainder's forward expectancy past T is <=0 so the clock is free?" - which
  is exactly the breakeven-protect (C) finding generalized to a clock. If every T is null once the
  null is subtracted, the verdict is "the protected runner's remaining expectancy is flat - a clock
  neither helps nor hurts on mean, and here is the variance it removes."

## 4. Seal + govern
Reference the m28 ORIG17/held-out boundary; HYPOTHESIS cap; auto rule needs SUPPORT + owner go; the
live give-back ALERT stays insight-only. The owner's "mine it extremely" is a request for DESCRIPTIVE
depth on (f), not a lower evidence bar - the null/control gate and MDE-before-verdict still govern.

## 5. Panel questions (the 3 judges must measure, not opine)
(a) LEAK JUDGE: is (e)'s sibling event strictly point-in-time on the random grid, or does "nearest
    overlapping entry" smuggle a future bar? Define "sibling" so it cannot. And is (f)'s fixed-age
    clock genuinely outcome-blind, or does "protected runner" already select survivors?
(b) STATS/POWER JUDGE: MEASURE how often (e)'s qualifying-sibling subset even exists on the grid
    (same-coin overlapping entries at 24-bar spacing may be rare -> UNDERPOWERED is the likely honest
    verdict); size (f)'s T-sweep MDE per T before any verdict.
(c) NULL/CONTROL JUDGE: specify the persistence-preserving null for BOTH arms (sibling wick for (e),
    fixed-age remainder for (f)) and the positive control for (f); confirm the reported number is
    arm-minus-null, and that a by-construction slice (e.g. "runners that were up at T") is flagged
    descriptive, not tested - the A-D trap that killed P(banked>0) and the runner-realized subset.
