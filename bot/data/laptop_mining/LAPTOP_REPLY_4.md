FINAL: all four of my recommendations held. Keep HAR. Change nothing in the bot.

Red team wp73ppfxp (5 agents, 546k tokens) returned HOLD on both live changes. Every
fatal finding re-derived by me in verify_v3.py before acceptance. Net result: the
correct action on the live bot is NOTHING. Four recommendations, four killed.

  1 stop x1 -> x2            HOLD   only surviving number is an algebraic identity
  2 target 1.5R -> 0.5R      DROP   never tested at x2; week-weighted it is NEGATIVE
  3 volforecast HAR -> EWMA  HOLD   I refuted the original against a baseline I invented
  4 TIME_STOP_HOURS unchanged  THIS ONE HOLDS

=== ERROR A: THE VOLATILITY SWAP WAS A STRAW MAN I BUILT ===
PC: DO NOT apply the EWMA swap from LAPTOP_REPLY_3 section 3. I withdraw it.

I claimed the original compared HAR against a degenerate |yesterday| baseline with
QLIKE 4.79. It did not. Verified directly:
  walkforward_vol.py:50   "naive5": ret.rolling(5).std()      <- a 5-day stdev
  walkforward_vol.py:117  s_n = score(te["y5"], te["naive5"])
  walkforward_vol.json    mean_har_qlike 0.1565 / mean_naive_qlike 0.2781
That is a 1.78x gap, NOT the 36x I reported. I substituted rv1 (|yesterday|) myself,
produced the blow-up, and attributed the pathology to the original work.

My evidence line was void too: "grep -o y1 walkforward_vol.json returns 0" is true,
but grep -o y5 ALSO returns 0 -- the JSON stores no horizon label at all. Claim 1
(y1 was never walk-forwarded) is still correct, but on the three fit(tr,"y5") call
sites at lines 114/159/168, not on that grep.

And "HAR earns nothing over EWMA" holds ONLY under QLIKE-on-level, where I capped
HAR at 22 days while ewma_pred recursed over 120 returns -- an unfair comparison.
  MSE-on-variance at y5:    HAR beats EWMA 19/22, p = 0.0008
  QLIKE-on-variance:        favours HAR at BOTH horizons
  stop-exceedance at a nominal 5% stop (the axis the live code uses):
                            HAR 6.30% vs EWMA 7.25%
and the swap would move over half of all coin-days into a different leverage decile.
My verdict gate could not fire either: beats = (w==n and tmean < -1.96) averages 22
per-fold t-statistics, which is not a test statistic; a wild cluster bootstrap puts
the true 5% critical value at -0.34 to -0.73, so -1.96 was 2.7-5.7x too strict.

KEEP HAR. Still delete the stage-2 correction -- RETRACTION #5 (test-set leakage,
gain 0.06%, p=0.746) is unaffected by any of this.

=== ERROR B: THE STOP CHANGE -- A TEST THAT COULD NOT FAIL, INVERTED ===
 * THE FEE SAVING IS ARITHMETIC. feeR(m) = feeR(1)/m exactly, so it is positive on
   every trade on any data INCLUDING A DRIFTLESS RANDOM WALK. "Positive in all 14
   weeks, t = +8.84" is a property of division, not evidence. My figures were also
   off base: the simulation's MEAN feeR is 0.1483R at x1 and 0.0741R at x2; I used
   the median stop width (0.1272/0.0636). Fee share is 62% at x2, not 54% -- which
   destroys my "46% comes from somewhere else" argument.
 * MY SYNTHETIC CONTROL'S ZERO ARM COULD NOT FAIL. h0 = ds - ds.mean() pins the
   sample mean to exactly zero, then boot_ci builds a percentile CI around that same
   mean. 0 of 400 seeds reject. "No false positive at zero" was guaranteed by
   construction. The power curve also ran only at 8.0|0.5 -- a cell the document says
   must not be read -- and the recommended effect sits BELOW its own 0.08R floor.
 * BIND_FLOOR = 0.50 CHOSE THE ANSWER. sym_adv is monotone in stop width, so the
   floor IS the recommendation: <=0.143 -> x8, 0.143-0.443 -> x4, 0.443-0.791 -> x2,
   >0.791 -> NOTHING QUALIFIES. And my stated reason for rejecting x4 -- "the bracket
   never binds" -- IS FALSE. It binds on 44.3% of trades. saturated_cells was just
   the floor relabelled.
 * THE NON-FEE REMAINDER IS NOT SIGNIFICANT: +0.0445R, week CI [-0.0308,+0.0935].
   Significant in exactly one of 24 cells (8.0|0.5), which I reject for not binding.
 * A DRIFTLESS-GBM PLACEBO REPRODUCES ~95% OF THE SURFACE (+0.1131R at 2.0|0.5 vs
   +0.1187R measured). The effect is mechanical; there is no edge content.
 * MY TIE_RULE ARGUMENT WAS WRONG THREE WAYS and it was my only support for the
   non-fee half: (1) the tie rule applies only to bars touching BOTH levels, which is
   0 of 15,663 trades at 2.0|0.5 -- literally no effect on the comparison; (2) wrong
   sign, TIE_RULE.md concludes correcting it would SHRINK the advantage and I cited it
   as understating; (3) wrong sample, the 75-81% figures are from 2026-09-21..10-08,
   which TIE_RULE.md itself flags as untested travel. I wrote both documents.

So the only real item is OPERATIONAL, not a finding: fees per unit of risk halve if
the stop doubles AND position size halves to hold dollar risk constant. Hold notional
constant and the dollar fee is unchanged while dollar risk doubles -- then the
"saving" is just a change of units. That is the owner's sizing preference to decide.

=== WHAT SURVIVED THE WHOLE DAY ===
 * v2's refutation of the geometry work was itself wrong (null = (geometry)-(direction),
   verified to 5.6e-17). STANDS.
 * Tightening the stop below current is harmful, -0.13R to -0.20R at x0.5. STANDS.
 * Target-only changes at the current stop are null. STANDS.
 * No time stop in 4-72h beats having none. STANDS (unreviewed).
 * The Squeeze column works but measures overbought/oversold, not agreement --
   disagree adds -0.0024/-0.0012, permutation p 0.965/0.890, and NO definition of
   dissent adds anything. STANDS (unreviewed). This also finally answers your
   dissent_families question: the definition does not matter.
 * ENSEMBLE_CONFIDENCE_FLOOR is a backtest-only knob; the live floor is
   AdaptiveConfidenceFloor, bounded [20,80], starting 30. STANDS (CONFIG_AUDIT.md).
Two are practically useful -- don't tighten the stop, relabel the Squeeze column.
Neither is an edge. No directional edge was found anywhere today.

=== THE LESSON, NOW THREE TIMES OVER ===
v1 validated on data that had already chosen the answer. v2 used a null that was zero
whenever geometry matched direction. v3 (mine) pinned a mean to zero and then tested
that mean, and shipped an algebraic identity as a headline. Vol v2 (mine) substituted
its own baseline and then refuted it. Adding a synthetic control was the right
instinct and I implemented it WRONGLY -- the correct form resamples or simulates NEW
data under the null, which is what the reviewer's GBM placebo did.

Three rules I am adopting, each earned today:
 1. Put the equal-weighted block mean next to every pooled figure. Having the right
    clustering standard is not the same as applying it to the number you act on.
 2. Before refuting prior work, read the baseline it actually used -- do not
    re-derive it from the write-up's description.
 3. Ask whether a positive result could ever have come out negative. A quantity
    positive by construction will be positive in all 14 weeks with arbitrarily large t.

CORRECTIONS.md is the single page for all of this. GEOMETRY_V3.md and VOLATILITY_V2.md
now carry withdrawal boxes at the top; their bodies are kept as the working record.
COMMAND_CENTER.md tells the owner to change nothing.

HIGHEST-VALUE REMAINING TARGET: ADX_MIN_TRENDING (trading_config.py:263, now 10.0) is
the only July-swarm knob both live and never examined. And please send
bot/data/trade_ledger.csv -- the adaptive-floor argument rests on it and it does not
exist on this machine.
