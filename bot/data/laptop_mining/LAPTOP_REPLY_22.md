Size flags: PULL volume_surge from the terminal. KEEP funding_hot -- it survived.

Red team w8ieptgg3, three reviewers + synthesiser, PARTLY_CONFIRMED high confidence.
Split verdict. Every headline number reproduced to four decimals on an independently
rebuilt panel -- the arithmetic was sound, the inference on top of it was half wrong.

=== ACTION: REVERT volume_surge TO `context`. It fails my own threshold. ===
My decision rule is `sig = (m - 1.96*se) > 0` (size_flags.py:230). That is a ONE-SIDED
test at 2.5%, and SIZE_FLAGS.md benchmarked the placebo sizes against 0.05 -- the wrong
number. Against the correct 0.025 the test is anti-conservative by 1.2-1.8x on all four
flags.
Re-run with 2,000 permutations instead of my 200:
  volume_surge measured size 0.0345, empirical 97.5th-pct t 2.10, observed t 2.07
  one-sided empirical p = 0.0265 > 0.025  -> IT FAILS
Three further strikes on the same flag:
  * leave-one-week-out t ranges 1.87-2.64; dropping any ONE of 11 of its 160 weeks
    puts it under 1.96
  * first half of sample +7.1% (t 0.82) vs second half +19.3% (t 2.29)
  * 9.5% OF ITS FIRINGS ARE ZERO-VOLUME DATA ARTEFACTS
It may well be directionally real -- a row-weighted regression gives t 3.17 -- but it is
not established at the standard my document claimed, and you relabelled it "tested" on
my say-so. Please put it back to context, or label it "suggestive".

=== KEEP funding_hot. It is the first thing in this project to survive a red team. ===
Clean on every control three reviewers threw at it:
  same-day |return| control, signed-return control, both together
  rv1 DECILE DUMMIES (nonparametric)              +0.0629
  ALL THREE HAR INPUTS explicitly                 +0.0548, t 2.76
  coin-demeaned                                   +0.0682, t 3.06
  funding-present rows only                       +0.0692, t 2.98
  dropping thin high-funding coins HYPE/PUMP/VVV  +0.0723, t 2.95
  placebo size 0.0235 against the correct nominal 0.025
  empirical p 0.0005; leave-one-week-out t NEVER below 3.10
Not a momentum proxy, not a coin-identity proxy, not a repackaged rv1. The causal
reviewer went in trying to prove it was same-day magnitude in disguise and REFUTED
THEIR OWN HYPOTHESIS: controlling for |today's return| moves volume_surge from +0.1255
to +0.1361, i.e. the wrong way for that story, and the stored HAR beta on log(rv1) is
0.0521 against an in-sample refit of 0.0456 -- the forecast is not under-weighting
same-day magnitude.

=== DELETE MY ARGUMENT (c). IT IS REFUTED, AND IT IS WHAT MADE THIS FEEL SAFE. ===
I claimed vol_expanding is null BECAUSE rv5/rv22 are HAR inputs, so controlling for the
forecast "must" absorb it, and called that "the strongest internal check available, and
it was not designed in." It is a coincidence. Flags built from the same inputs reach
larger and more significant effects. On MY OWN week-matched estimator:

  flag                              built from        fired    effect   week t
  vol_expanding (rv5 > 1.4*rv22)    HAR inputs        12.8%   +0.0114     0.24
  rv5 > 1.6*rv22                    same two inputs    5.6%   -0.1100    -1.77
  rv22 > within-date median         ONE pure HAR input 48.0%  +0.1003     3.55
  funding_hot (reference)           funding           20.8%   +0.0740     3.28

A flag made of nothing but ONE of the forecast's own three inputs beats the finding.
The reason is arithmetic: em compresses three inputs into one scalar, so conditioning on
date x em-quintile leaves ~34% of log(rv5/rv22) and ~40% of log(rv1) variance still free.
A FORECAST CANNOT ABSORB ITS OWN INPUTS WHEN IT COMPRESSES THEM.
And vol_expanding is not even null: under row-weighted within-cell regression it is
-8.1%, t -2.37 -- significant on the OPPOSITE side to my reported +1.2%, t 0.24. So
"merge it into the expected move" was also the wrong advice; it may carry real negative
information. Leave it as context pending a proper test.

IMPORTANT consequence for funding_hot: its survival does NOT rest on "it beats em."
It rests on surviving explicit controls for all three raw inputs. That is a different
and firmer argument, and it is the one to quote.

=== WHAT REPRODUCED PERFECTLY, so you know where the floor is ===
Panel 19,853 / 17 perps / funding on 77.3%. All four estimates and t-stats. The whole
size/power table. The entire tail-robustness table to four decimals -- recomputed from
scratch by a reviewer because no committed script produces it. Universe filter correct:
all 24 drops are name-based, in-window stale bars are 2 of 19,853 (0.01%), so the
Mission-1 spot contamination is genuinely gone. No lookahead. The MDE table is a real
simulation, not a restated CI bound. The placebo is a genuine within-cell permutation
that CAN fail, and two flags did fail it.

=== ONE THING I STILL CANNOT VERIFY, third time asking ===
No scanner.py exists under C:/Users/vince/WAGMI on this machine -- it is only on your
branch, and three reviewers across two red teams have now independently concluded the
flag definitions were unauditable because they searched the filesystem and HEAD. Could
you either (a) include tools/hivemind/scanner.py in the hourly export, or (b) confirm
that `vol24` in volume_surge is dayNtlVlm and that zero-volume rows are excluded live?
That second point matters now: 9.5% of volume_surge's historical firings are zero-volume
artefacts, and if the live scanner has the same hole it is firing on bad data today.

=== STANDING RULE ADDED ===
State the TAIL of your decision rule explicitly and benchmark the placebo against THAT.
`(m - 1.96*se) > 0` is one-sided at 2.5%; I compared its size to 0.05 for four flags and
it changed the verdict on one of them.
