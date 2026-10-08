Mission 3: remove the "~5% day / ~3.2% day" caption. The spread is real; consensus isn't why.

29,402 coin-days, 24 coins, 2020-09-10 -> 2026-10-07, split 2025-06-01.
You asked: does it survive controlling for the coin's own HAR forecast? If not, remove it.
IT DOES NOT. Controlling for the forecast AND the date leaves +0.9%, t=0.17,
CI [-0.095,+0.112]. Show the coin's expected move instead -- it already carries the
whole effect and it is already on screen.

THE CLAIM DOES REPRODUCE, which is the trap:
  bucket          n    mean |move|   median   mean em (HAR)
  <=1 dissent  5,700        5.28%     3.08%           4.32%
  2 dissent   10,676        4.52%     2.57%           3.96%
  >=3 dissent 13,026        4.47%     2.41%           3.93%
Raw spread +0.81 percentage points -- that IS the terminal's "~5% vs ~3.2%". It is a
real pattern. The question is only why.

FOUR TESTS. THREE CONTROL THE WRONG THING.
  controlled                          dissent effect                      reads as
  nothing (raw)                       +0.81 pp                            big
  the HAR forecast only (10 deciles)  +17.6%, 10/10 deciles, t=6.46       VERY convincing
  the date only (within-date perm)    +0.0283 of +0.1484 = 19%            mostly date
  BOTH date AND forecast              +0.9%, t=0.17, CI [-0.095,+0.112]   NOTHING

THE WITHIN-DECILE TEST NEARLY FOOLED ME, and that is the part worth your attention.
Low dissent produced bigger moves in 10 of 10 expected-move deciles, mean +0.1623
log, t=6.46. As persuasive as a result gets. It is wrong because `em` is a PER-COIN
forecast and cannot absorb MARKET-WIDE surprise: low-dissent coin-days cluster on
volatile market days. Controlling for the coin's forecast does not control for the day.

THE DECISIVE TEST -- same date, same em quintile. 1,699 matched (date x em-quintile)
cells over 1,234 dates:
  mean diff +0.0273 log, median +0.0928, cells positive 53.4% (a coin flip)
  week-clustered +0.0088, t 0.17, CI95 [-0.0947,+0.1124]
  level terms +0.9%
  PLACEBO centres on +0.0017, CI [-0.0680,+0.0750] -- so it CAN fail -- and
  p(null >= real) = 0.267.

WHY THE REGRESSION LOOKED SIGNIFICANT AND I DO NOT TRUST IT.
log|move| ~ a + b*log(em) + c*disagree gives a significantly negative disagree
coefficient in both halves (-0.0521 train, -0.0885 test, week-clustered CIs exclude
zero). BUT its log(em) coefficient is +0.8430 train and +0.2068 test -- a 4x swing.
When the control variable's own coefficient is that unstable, "controlling for it" is
not working and the leftover loads onto whatever else is in the model. The
nonparametric date x quintile matching has no such problem, so I am going with it.

TRADER RULES, one number each:
 1. Voice agreement tells you nothing about tomorrow's move size. Same day, same
    forecast: +0.9% difference between full agreement and heavy dissent.
 2. The expected-move number already contains it: HAR explains 48% of the raw spread
    directly, and the market-wide day explains most of the rest.
 3. Low dissent is a volatility SYMPTOM, not a signal. disagree is 70.6% determined
    by vote-activity and extremity (SQUEEZE_V2), corr(disagree,|RSI-50|/50) = -0.802.
    "Everyone agrees" mostly means "RSI and Bollinger are stretched" -- already in em.

WHAT TO SHOW INSTEAD: the coin's own expected move, which you already compute. Drop
the dissent caption, or if you want a consensus readout keep it labelled "agreement
(no tested effect on move size or direction)" -- consistent with SQUEEZE_V2, which
found no definition of dissent adds anything to squeeze probability either. Between
that and this, the consensus/hivemind framing has now failed on BOTH of its claims:
direction (squeeze) and size (this).

ALSO, A BUG I FIXED IN MY OWN FIRST PASS: I initially measured the residual as
move/em, which blew up to 229,859x when em is near zero -- the same division
pathology that made the QLIKE "naive" baseline useless, reproduced in my own code.
Switched to log(move) - log(em), which is bounded. Worth knowing if you ever score
forecasts as a plain ratio.

LIMITS: 24 coins including short-history listings, and the HAR coefficients were
fitted on 11 majors, so em is slightly out-of-domain for newer ones -- the date x
quintile matching is robust to that (it only compares coins in the same forecast bin
on the same day) but the raw bucket means are not. One split, not walk-forward.
Target is |next-day return| only. NOT RED-TEAMED: provisional, and this document
changed its own answer twice before settling.

Mission 4 next.
