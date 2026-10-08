Mission 2: the owner's 50d short has no edge -- and scanner.py flags the wrong average

418 touches, 17 HL perps, 2024-07-14 -> 2026-09-17. LEVELS.md touch/break/reject
definitions verbatim, LEVELS.md's own random-level null.

=== THE BUG, WHICH MATTERS MORE THAN THE SETUP ===
levels.py:78 validated the 50-day SIMPLE average. scanner.py flags the 50-day EMA.
Different levels, and only one works.

    levels.py:78    ma50 = c.rolling(50).mean().shift(1)     # SIMPLE
    scanner.py      e50  = _ema(c, 50)                       # EXPONENTIAL

Same 11 coins, same window, same definitions, LEVELS.md's null:
  level definition                  n   BREAK%          CI95   null%  vs null
  SMA  (what levels.py tested)    696     32.3   [28.9,35.8]    37.4    -5.1  <- real
  EMA  (what scanner.py flags)    749     37.0   [33.5,40.4]    37.5    -0.5  <- nothing

LEVELS.md reports n=701, 32.1% [28.8,35.8], -4.4. I reproduce that almost exactly on
the SMA, so LEVELS.md IS RIGHT. The scanner then cites it as evidence for a level it
does not compute.

FIX: either switch ma50_pullback to the simple 50-day average, or drop the LEVELS.md
citation. This is a SECOND, INDEPENDENT reason to demote the flag beyond Mission 1 --
and unlike Mission 1's result, this one is repairable. If you switch to the SMA the
flag may be worth re-testing; I have not tested the SMA version as a RETURN signal,
only as a level-holding one.

=== THE OWNER'S SETUP: NO EDGE IN ANY VARIANT ===
Break = closes >=0.5 em below the level within 2 days (short wins). Reject = >=1.0 em
back up (short loses).

  condition                         n  BREAK%          CI95  null%  vs null  reject%  neither%
  all ma50-from-above             418    36.4   [31.8,41.0]   38.8     -2.4     26.3      38.8
  + daily trend UP                172    42.4   [35.1,49.8]   39.0     +3.4     22.7      36.6
  + trend UP & 4h down  <- YOURS  134    41.0   [32.7,49.4]   39.1     +2.0     23.9      37.3
  + trend UP & 4h last-6 down     101    39.6   [30.1,49.1]   39.3     +0.4     24.8      36.6
  (contrast) trend DOWN & 4h down  69    43.5   [31.8,55.2]   38.7     +4.8     33.3      26.1

EVERY CI COVERS ITS NULL. And the 4h filter moves the break rate from +3.4 to +2.0 --
it makes the setup slightly WORSE, not better.

What the short pays (net 9 bps, signed short):
  condition                         n  1d mean  1d wk mean   wk t  5d mean  5d wk mean   wk t
  all touches                     418   -0.208      -0.055  -0.16   -1.210      -1.661  -1.42
  + trend UP                      172   +0.279      +0.204   0.42   -0.059      -1.175  -0.72
  + trend UP & 4h down  <- YOURS  134   +0.201      +0.114   0.22   -1.206      -2.215  -1.18
  (contrast) trend DOWN & 4h down  69   +0.500      -0.073  -0.11   -2.821      -2.308  -1.30
Not one week-t clears 1.96. The short is a coin flip at 1 day and loses at 5 days in
every variant.

=== THREE PLAIN ANSWERS, ONE NUMBER EACH ===
 1. How often does the 50d break when you short into it from above? 41% in the exact
    setup, against a random-line rate of 39%. Paying fees for a 2-point edge the CI
    cannot distinguish from zero.
 2. What does the short return? +0.20% at 1 day, -1.21% at 5 days. Holding longer
    makes it worse.
 3. The number worth keeping: price does NEITHER 37% of the time. It doesn't break
    and it doesn't reject -- it sits on the level. Any plan phrased "it breaks or it
    bounces" is wrong more than a third of the time, and that is the most reliable
    fact in this whole study.

=== THE STRUCTURAL PROBLEM WITH THE PLAN ===
The owner is shorting into the one level in the table that HOLDS better than chance
(-5.1 pts on the SMA, 2020-2026) while conditioning on DAILY TREND UP, which is the
condition that makes support more likely to hold. The two halves work against each
other. The contrast row shows the sense he probably wants -- trend DOWN gives the
highest break rate at 43.5% -- but its CI is [31.8,55.2] on n=69, so I cannot call
that real either.

=== LIMITS, READ BEFORE ACTING ===
 * 4h history binds the sample to 2024-07 onward, and that matters: the SMA support
   effect is concentrated BEFORE 2024 (pre-2024 -2.7 pts, 2024-onward +1.6). So in the
   only window where the 4h condition is testable, the underlying support effect is
   itself absent. Worth knowing independently of this mission.
 * Pooled across 17 coins, NOT SOL alone. 418 touches / 17 coins is about 25 each, and
   the owner's condition cuts that to roughly 8 per coin. SOL-only is far too thin to
   report. If the setup is SOL-specific rather than general, this does not test it.
 * LEVELS.md:68 had already flagged "ma50 from above, uptrend" as the ONE unstable
   cell in its structure table (train 29.9% / test 43.4%, stable: no). The owner's
   condition sits exactly there.
 * Daily closes for break/reject, next-day open for entry, no stops -- this measures
   the setup, not a managed trade.
 * NOT RED-TEAMED. Provisional.

Missions 3 and 4 next.
