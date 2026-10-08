Mission 1: demote both "tested" directional flags. Median flagged trade earns exactly the fee.

22,518 coin-days, 24 HL perps, 2023-01-01 -> 2026-10-02, 9 bps round trip, excess
over the universe median on the same dates. Flag definitions lifted verbatim from
scanner.py:103-105; em replicated from volatility_forecast.json y1_beta/y1_smearing
and verified identical to volforecast.forecast() on 8 coin/cutoff pairs (BTC 2.0839
vs 2.08, SOL 3.2041 vs 3.20).

You pre-committed to demoting on screen if either is null after fees. BOTH ARE NULL.

NULL AS YOU SPECIFIED -- same coin, same number of firings, random dates, 2000 draws:
  ma50_pullback (long)   807 firings (3.6%)   1d p=0.231   5d p=0.492
  on_20d_low   (short) 1,317 firings (5.8%)   1d p=0.560   5d p=0.928
A p of 0.49 means random dates in the same coin did better half the time.

THE ONE NUMBER THAT SETTLES IT: the median excess return of a flagged trade is
-0.180% at every flag and every horizon, and the round-trip fee is exactly 0.180%.
So the median flagged trade earns EXACTLY ZERO before costs.

  flag                 hz     mean    MEDIAN  winsor1/99  win rate  panel win rate
  ma50_pullback        1d   +0.330   -0.180      +0.041     43.1%          43.4%
  ma50_pullback        5d   +1.333   -0.180      +0.908     45.5%          46.2%
  on_20d_low (short)   1d   -0.543   -0.180      -0.311     42.7%          43.5%
  on_20d_low (short)   5d   -8.402   -0.180      -4.486     47.5%          46.2%
Every win rate is within 1.1pp of the panel base rate. A flagged day behaves like
any other day for that coin.

WHY THE MEANS LOOK DRAMATIC AND MEAN NOTHING. The top 1% of on_20d_low firings --
13 of 1,317 rows -- carry 43.8% of all absolute excess. Drop them and the 5d figure
goes -8.402 -> -1.671. I also checked the INVERSION (buying the 20d low instead of
shorting it) because its mean is +8.0% at 5d: it is three rows, +1008%, +1009% and
+1173% excess. Median still -0.180%, win rate 47.1% vs the panel's 46.2%. It is a
lottery-ticket distribution, not an edge. DO NOT flip the flag's sense.

POWER, so the null means something:
  ma50_pullback detects from 0.10% per trade  -> its null is strong evidence of absence
  on_20d_low    detects only from 2.0%        -> its null is WEAKER
For on_20d_low please say "not measurably better than random" on screen, not "proven
to do nothing" -- an edge under 2% per trade would be invisible in my design. The
zero-injection arm resamples genuinely rather than pinning a sample mean to zero,
which was the error that invalidated geometry_v3.py's synthetic control.

TRADER RULES, one number each:
 1. A pullback to the 50-day average is not a buy signal. Win rate 43.1% vs 43.4%
    for the same coin on a random day -- a 0.3pp difference.
 2. Sitting on the 20-day low predicts nothing either way. Random dates in the same
    coin beat it 56% of the time at 1 day and 93% at 5 days.
 3. Both flags cost 0.18% a round trip and return nothing for it.

TWO NOTES ON THE OTHER FLAGS:
 * vol_expanding is also marked "tested" but an excess-return test is the WRONG test
   for it -- it predicts move SIZE, not direction. Its on-screen citation ("beat the
   naive forecast 22/22 periods") refers to the y5 walk-forward, which SURVIVES: HAR
   qlike 0.1565 vs naive5 0.2781. So the citation is sound but supports a volatility
   claim. Suggest relabelling "tested (move size, not direction)".
 * The LEVELS.md justification in the FLAGS dict ("the 50-day average held more often
   than a random line, 2,955 touches") is a LEVEL-HOLDING claim, not a RETURN claim.
   A level can hold more often than chance and still produce no tradeable excess --
   which is exactly what this shows. Both can be true; the on-screen text implies the
   second.

ALSO, A PRECISION FIX TO MY OWN VOLATILITY RETRACTION (VOLATILITY_V2.md, new note at
top). I had written that I "invented" the degenerate baseline. That was too strong and
inaccurate. It exists in the project, in a DIFFERENT artifact than the one I blamed:
  volatility_forecast.json -> y1_naive  "naive persistence"  qlike 4.1202 vs HAR 0.5126
  walkforward_vol.json     -> naive5    rolling(5).std()     qlike 0.2781 vs HAR 0.1565
So the correct statement is: the degenerate-baseline problem is REAL for the y1
calibration numbers and FALSE for the y5 walk-forward. I found it in the first
artifact, attributed it to the second, and generalised. The y5 walk-forward result
stands as originally reported. Still KEEP HAR -- the EWMA recommendation stays
withdrawn for the loss-specification and unfair-window reasons.

LIMITS: 24 perps with daily history from 2023, so coins outside my history/ set are
unmeasured (live scanner covers top-60). Daily closes only -- an intraday flag would
not show here. Entry is next open, exits are closes, so this measures the flag and not
a full strategy with stops. NOT YET RED-TEAMED: provisional until it is.

Missions 2-4 next, in your order.
