Missions revised after red team: 3 of 4 recommendations change. Only the fill-candle fix survives.

Red team wkqz8m3br, 8 reviewers + synthesiser, 1.01M tokens. Every claim below
re-derived by me before accepting. MISSIONS_REVISED.md + SCANNER_FLAGS_V2.md
supersede SCANNER_FLAGS.md, SOL_50D_SHORT.md, CONSENSUS_SIZE.md and the Q1 half of
PLANS_AUDIT.md.

  mission            I told you                      DO THIS INSTEAD
  1 scanner flags    demote both, both null          demote both, but on_20d_low is
                                                     UNMEASURABLE not null -> "untested"
  2 SMA vs EMA       "a bug, switch to the SMA"      RETRACTED. Do not change the code.
  3 consensus        remove the caption (+0.9%)      do not remove on my evidence; my
                                                     test had NO POWER. Effect +4.0%, t 0.97
  4 plan grader      no 1m; fix the fill candle      fill-candle fix CONFIRMED (go further);
                                                     "no 1m" WITHDRAWN

=== MISSION 1: three fatal defects, all mine. Rebuilt in SCANNER_FLAGS_V2.md ===
 F1 DATA. My filter was `not s.endswith("_wspot")` -- it excluded the wrapped
    duplicates but let the IDENTICAL *_spot files through. 7 of my "24 HL perps" were
    spot series with up to 70.5% STALE bars (o==h==l==c): BERA_spot 70.5%, TRUMP_spot
    68.0%, MON_spot 65.3%, PUMP 40.0%, vs <=0.3% for every real perp. A stale run makes
    px == min(low[-20:]) exactly, so on_20d_low fires EVERY day of it -- 63% of my
    firings came from those 7 series (1,317 -> 487 once removed). And all 13 rows in my
    "top 1% = 43.8% of absolute excess" were spot DENOMINATION JUMPS, not meme
    explosions: MON_spot 0.000543 -> 0.0069 -> 0.000565 (x12.2 then /12.2). TRUMP_spot
    even has 857 rows from 2024 at 0.000502, before the token existed.
 F2 MY POWER TABLE WAS AN IDENTITY. I "injected" an effect by adding a scalar to every
    row, which shifts each week mean by delta and leaves mus.std(ddof=1) EXACTLY
    unchanged. So DETECTED <=> delta > -ci_low. Verified: ma50 -ci_low=0.0435 -> "MDE
    0.1"; on_20d_low -ci_low=1.2700 -> "MDE 2.0". The grid points were just the first
    values above the CI bound. And the "zero arm (must NOT detect)" is the statement
    ci_low<0, which IS the null verdict -- it could not fail. This was in the script
    whose docstring boasts about avoiding geometry_v3's version of the same error.
 F3 THE "-0.180% = EXACTLY THE FEE" HEADLINE WAS FORCED. net = x - 0.18 and subtracting
    the per-date cross-sectional median makes median(x) == 0 identically (748 rows are
    exactly zero). True of the FULL PANEL too, so it said nothing about the flags.

REBUILT on 17 clean perps, 19,574 rows, with a LAG PLACEBO (shift each coin's firing
dates within that coin, preserving count and clustering) and the full criterion:
  ma50_pullback  724 firings  null p 0.815 (1d) / 0.975 (5d)  <- random dates BEAT it
                 size 0.058 (calibrated), 98% power at 0.5%/trade -> GENUINE NULL
  on_20d_low     487 firings  null p 0.201 / 0.059
                 size 0.000 -> DESIGN VOID. It cannot reject anything.
So: demote both, but please label on_20d_low "untested", NOT "no edge". An edge under
~2%/trade would be invisible and I cannot rule one out in either direction.

=== MISSION 2: I RETRACT THE BUG CLAIM. DO NOT CHANGE THE CODE. ===
levels.py:78 does use c.rolling(50).mean() (simple) while scanner.py uses _ema(c,50).
That part is fact. But "the EMA is broken and the SMA works" does not survive testing:
  era            SMA vs null   EMA vs null   difference    se       z
  2020-2026           -5.3          -0.5      -4.8 pts    2.5   -1.90
  pre-2024            -9.4          -2.8      -6.6 pts    3.7   -1.81
  2024 onward         -2.1          +1.4      -3.5 pts    3.4   -1.03
Two things kill it: (1) the SMA/EMA gap NEVER reaches significance in any era -- I
presented a difference-of-differences as established without ever testing the
difference; (2) the SMA's own effect has DECAYED, -9.4 pts pre-2024 to -2.1 since (CI
[30.9,40.2] against a 37.7 null, covers it). Switching the scanner to the SMA would
install a level whose effect is mostly gone.
WHAT STANDS: the DOCUMENTATION mismatch is real -- LEVELS.md's "the 50-day average
holds from above more than chance" was measured on the SIMPLE average, so the
on-screen citation should say which, or stop citing it. WHAT FALLS: any code change.
On the owner's setup, "no edge" at n=134 was also a no-power claim; the honest line is
"untested at the available sample size", plus the structural point that still holds
(he is shorting a level that historically held while conditioning on an uptrend that
makes support MORE likely to hold). "Price does neither 37% of the time" survives
everything and remains the most useful number in that mission.

=== MISSION 3: MY NULL HAD NO POWER. DO NOT REMOVE THE CAPTION ON MY EVIDENCE. ===
The reviewers caught this exactly and my own power curve reproduces their number:
  injected   matched-cell week t   result
    0%                      0.17   missed  (reproduces my published +0.0088 / t 0.17)
   +5%                      1.09   missed  <- their figure, reproduced
  +10%                      1.97   detected
  +20%                      3.62   detected
My "decisive test" had an MDE of ~+10% against a true effect of ~+4%. It could never
have found it. I discarded 94% of the data -- 1,699 matched cells out of 29,402 rows --
to get a clean control, and bought a test that could not fail.
POWERED VERSION (date x em-quintile FIXED EFFECTS, all 15,961 usable rows, week-clustered):
  effect +0.0393 log = +4.0%   se 0.0403   t 0.97   CI95 [-0.0460,+0.1134]
Not significant, but the point estimate is +4.0%, NOT +0.9%. The reviewers reported
+4.7% with t=2.29; the point estimate agrees, the t does not survive week clustering.
REVISED: do not remove the caption on the grounds that the effect is zero -- I cannot
establish that. But the caption implies +18% relative (+0.81pp on a 4.47% base) while
what survives controls is +4.0%, so it OVERSTATES BY ~4.5x. Restate the numbers, or
keep the readout and drop the causal claim. Do not cite my +0.9%.

=== MISSION 4: FILL-CANDLE FIX CONFIRMED AND SHOULD GO FURTHER. "NO 1m" WITHDRAWN. ===
CONFIRMED, with a refinement I missed: the fix should be ADVERSE-SIDE-ONLY, not a
blanket skip. Of the 10,748 contaminated fill candles, 99.7% have the candle open on
the far side of the limit (price descended into a long's entry). In that geometry the
candle LOW can only be reached at or after the first touch of the limit, so STOP hits
on the fill candle are GENUINE post-fill events, while the HIGH is reached on the
approach so TARGET hits are spurious. A blanket skip throws away real stop information.
Suppress only the favourable side on the fill candle.
WITHDRAWN: my 0.115% tie-rule figure was measured on MARKET fills at random bar closes,
which never examines a limit fill candle at all. On the script's own limit geometry the
tie rule fires on 0.65% of plans and 4.73% at 0.5% stops -- still small, but an order of
magnitude more than I reported, and concentrated exactly where the fill-candle bug
lives. 1m resolution is a judgement call, not a settled no.
ALSO HONEST: the 9.62% rests on an unanchored assumption (limit entry 0.5
stop-distances from price). Contamination swings 4.9%-28.2% across 0.1x-2.0x offsets.
owner_plans.jsonl does not exist on this machine, so ZERO REAL PLANS were examined by
anyone. Send me the real plans and I will anchor it.

=== ONE DISPUTE RESOLVED IN MY FAVOUR ===
Three reviewers concluded tools/hivemind/scanner.py "does not exist" and that my quoted
definitions were unauditable. It exists on origin/desktop-overdrive-2026-05-30 -- they
searched only the filesystem and HEAD. The synthesiser confirmed _ema at :48, e50 at
:79, d50 at :85 and the flag conditions at :102-105 exactly as I cited. My citation was
accurate; their arithmetic criticisms stand regardless.
STILL UNVERIFIABLE FROM HERE, and it matters: whether the live scanner passes stage-2
args to volforecast.forecast(), which would change em far more than anything above.
PLEASE CONFIRM it calls forecast(c) with one argument.

=== THE PATTERN, FIFTH TIME ===
  1  a "power" table that was the CI bound restated; a zero arm identical to the verdict
  2  a difference-of-differences asserted without testing the difference
  3  a control so aggressive it discarded 94% of the data and all the power
  4  a rate measured on a geometry the question does not apply to
Three of these are a NEW variant of the same error: I kept making controls stricter to
be rigorous, and strictness destroyed power. A null is only evidence of absence if you
state what it could have detected -- and that figure must come from a placebo that
resamples, not from arithmetic on the confidence interval.
NEW STANDING RULE: report SIZE and POWER for every null, from a placebo that can fail.
If size is not near 5%, the design is void and the result is "unmeasurable", not
"nothing".

NET FOR YOU TODAY: one code change (fill candle, adverse-side-only). Everything else is
label and wording. Nothing in the bot's trading behaviour changes.
