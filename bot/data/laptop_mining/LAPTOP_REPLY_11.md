ADX_MIN_TRENDING: unmeasurable with 14 weeks of signals. Leave it at 10, close the item.

15,663 signals with ADX + outcome, 14 ISO weeks, 2026-02-11 -> 06-05. The last live,
never-examined knob from CONFIG_AUDIT.md.

THE TEST DECLARED ITS OWN DESIGN VOID BEFORE PRODUCING A VERDICT. Placebo size 0.000
against a nominal 0.05, and the 80%-power MDE is not reached even at 0.40R. Fourteen
weeks cannot resolve an ADX gate effect of any plausible size.

So: leave ADX_MIN_TRENDING at 10.0 and stop carrying the July swarm's ">60" as a
pending action. Not because raising it is wrong -- because nothing here can tell you
either way, and gating at 60 would discard 92.5% of signal flow on an unmeasurable
hypothesis.

This is the first finding today where the power check caught the problem BEFORE
publication instead of after. The discipline is starting to pay.

WHY THE ITEM EXISTED -- two rationales pointing opposite ways, never reconciled:
  trading_config.py:263 comment  lowered 15->10, "crypto ranges with ADX 10-15 very
                                 frequently", "ADX 15 was blocking too many"  -> LOWER
  July swarm                     gate >60                                     -> RAISE 6x
Unlike ENSEMBLE_CONFIDENCE_FLOOR this one really is live: regime_trend.py:271,
confidence_scorer.py:556, multi_tier_quality.py:226.

ADX replicated from the bot's own quant_regime.py:62 -- EMA smoothing of +DM/-DM/TR
(NOT Wilder's), period 14, on 1h candles. Matching the bot mattered more than matching
the textbook.

WHAT EACH GATE WOULD COST:
  ADX >= 10 (current)  ~100% of signals kept
  ADX >= 20             87.6%
  ADX >= 25             77.7%
  ADX >= 40             38.3%
  ADX >= 60 (swarm)      7.5%

THE POWER CHECK, run first (lag placebo: shift each coin's signal times within that
coin, preserving count and clustering, destroying any real ADX<->outcome link):
  injected    detection rate
    0.00R              0.000   <- SIZE, wanted ~0.05
    0.05R              0.007
    0.10R              0.007
    0.20R              0.113
    0.40R              0.440
Size 0.000 means the criterion never fires even when it should 5% of the time. At
0.40R -- larger than the entire geometry surface from tightest to widest stop --
detection is still only 44%.

THE NUMBERS, AS DESCRIPTION ONLY (informative about the BOT, not about the gate):
  ADX bucket      n   raw mean R   week mean   week se   week t
  10-15         190      -0.4201     -0.6196    0.2987    -2.07
  15-20       1,752      -0.6880     +0.1506    0.2973     0.51
  20-25       1,556      -0.3816     -0.1143    0.2225    -0.51
  25-40       6,162      -0.3321     -0.1995    0.1573    -1.27
  40+         6,003      -0.2604     -0.3153    0.1373    -2.30
Two things, neither supporting a gate:
 1. NO MONOTONE RELATIONSHIP. Week means run -0.62, +0.15, -0.11, -0.20, -0.32 -- the
    sign flips twice. If higher ADX meant better outcomes this column would trend.
 2. RAW AND WEEK-WEIGHTED MEANS DISAGREE VIOLENTLY. The 15-20 bucket is -0.6880 raw
    but +0.1506 week-weighted, a 0.84R swing from re-weighting alone. Same
    unequal-block problem that inflated my geometry headline by 62%.
Every gate comparison returned "unmeasurable": differences of +0.32R to -0.44R against
standard errors of 0.19-0.32.

THE THING THAT IS WORTH SAYING: every ADX bucket has NEGATIVE mean R. The bot's
signals lose at the bot's own bracket over 48h regardless of trend strength --
consistent with GEOMETRY_V3's -0.3477R for the default bracket. An ADX gate rearranges
which losses you take; it does not create a winner. If the signals are
negative-expectancy, filtering by trend strength is not the lever.

TRADER RULES, one number each:
 1. Leave the ADX gate at 10. Raising it to 60 discards 92.5% of signals to buy an
    effect this data cannot measure at any size.
 2. Signals lose at every trend strength: mean R negative in all five buckets,
    -0.26R to -0.69R.
 3. Fourteen weeks is not enough to tune a gate. Smallest detectable effect > 0.40R.

WHAT WOULD MAKE THIS ANSWERABLE: more weeks of signals, not more cleverness. At the
observed per-week dispersion, resolving a 0.10R gate effect at 80% power needs roughly
16x the weekly blocks -- about 4-5 years of logging at the current rate. Alternatively
test the gate on the bot's REALISED FILLS once trade_ledger.csv exists, where the
outcome is actual P&L rather than a simulated bracket. That is another reason to send
me that file.

LIMITS: one corpus, one bracket definition (bot's own entry/sl, tp1 where valid else
1R), 48h horizon. ADX is computed on the bar BEFORE entry so there is no lookahead,
but the live bot's ADX may come from a different candle source or a partially formed
bar. regime_trend is flagged in-code as losing (-$200, 18% WR, PF 0.15) and is one of
this knob's consumers, so a gate study pooled across strategies may be the wrong unit
entirely. THE DESIGN IS VOID BY ITS OWN TEST -- nothing here is a finding, it is a
statement that the question is out of reach with this sample.

That closes all three July-swarm knobs: ENSEMBLE_CONFIDENCE_FLOOR is backtest-only,
TIME_STOP_HOURS should be left alone, ADX_MIN_TRENDING is unmeasurable. None of the
three is a pending action any more.
