Mission 4: don't go to 1m (0.115%). Fix the fill candle instead (9.62%).

127,811 simulated plan resolutions on real HL 5m candles, 22 symbols, stop 0.5-3%,
target 0.5-3R, 48h hold. You asked me to check the tie rule; it turns out to be the
least important of the four things, and there is a real bug sitting next to it.

Q1 (you asked)  resolve ties on 1m?        NO -- the tie rule decides 0.115% of plans
Q4 (not asked)  the FILL CANDLE            9.62% of limit fills can be decided by
                                           price action BEFORE the position existed,
                                           up to 51.9% on tight brackets

=== Q1: THE TIE RULE DOES ALMOST NOTHING. LEAVE IT AT 5m. ===
TIE_RULE.md's 39.1% stop-first rate is correct, but it only applies to candles that
contain BOTH levels. At 5m with realistic plan geometry that essentially never happens:

  stop   target   resolved   ambiguous   share
  0.5%     0.5R       8800         101   1.15%   <- the only cell with any ambiguity
  0.5%     1.0R       8800          28   0.32%
  0.5%     2.0R       8800           5   0.06%
  1.0%     0.5R       8800           5   0.06%
  1.0%     1.0R       8798           2   0.02%
  2.0%     0.5R       8687           1   0.01%
  2.0%  1.0R+         8366           0   0.00%
  3.0%  all           5178-8180      0   0.00%
  OVERALL           127,811         147   0.115%

A 5-minute candle's range is small relative to a 0.5-3% bracket, so both levels are
almost never inside one. From a 1% stop onward it is <=0.06%; at 2% or wider it is
literally zero. And TIE_RULE.md found 15.4% of ambiguous cases are STILL tied at 5m,
so 1m fixes a fraction of a fraction. Keep the conservative stop-first rule -- it is
doing no measurable work either way, which is the good outcome.

=== Q4: THE FILL CANDLE IS TESTED ON ITS OWN PRE-FILL RANGE ===
plans.py:_walk --

    if fill_t is None:
        ...
        if l <= e <= h:
            fill_t = t0          # filled somewhere INSIDE this candle
        else:
            continue
    ...                          # SAME iteration, SAME candle:
    hit_stop = (l <= st) if sg > 0 else (h >= st)
    hit_tgt  = (h >= tg) if sg > 0 else (l <= tg)

A limit plan fills mid-candle, but the stop/target test then uses the WHOLE candle's
high and low, so range from before the fill can close the trade. best_r/worst_r have
the same problem.

  stop   target   limit fills   contaminated    share
  0.5%     0.5R          8219           4267   51.92%
  0.5%     1.0R          8219           1480   18.01%
  1.0%     0.5R          7662           1956   25.53%
  1.0%     1.0R          7662            382    4.99%
  2.0%     0.5R          6522            531    8.14%
  3.0%     1.0R          5533             32    0.58%
  OVERALL             111,744         10,748    9.62%

Worst exactly where a near target sits within one candle's range of the entry. For a
tight stop with a 0.5R target, MORE THAN HALF of limit fills are gradeable on range
that predates the position. It cuts both ways (a pre-fill wick to the target scores a
win, to the stop scores a loss) so it is not a one-directional bias in the owner's
favour -- but it is not measurement either, and it adds noise precisely to the
tight-bracket plans where R is smallest.

THE FIX, one line: make the fill-candle skip unconditional.

    if fill_t is None:
        if t0 > pl["ts"] + pl["entry_window_h"] * 3600:
            return {"status": "expired", "note": "entry never reached"}
        if l <= e <= h:
            fill_t = t0
        continue          # was `else: continue`; now ALWAYS skip the fill candle

Costs at most 5 minutes of exposure per limit plan and removes the contamination
entirely. Market plans are unaffected -- they set fill_t before the loop, so their
first tested candle already opens after the plan.

=== Q2: the fill rule `low <= entry <= high` ===
Correct in form, optimistic in practice. It assumes any touch of the entry fills; a
brief wick through a resting limit may not fill at all. It is the mirror image of
`exit_px = st if hit_stop else tg`, which assumes exact fills at stop and target with
no slippage or gap-through. The two partly offset, so I would LEAVE them -- but say so
on screen ("fills assumed at the level, no slippage"), because a plan graded this way
reads slightly better than the same plan traded live. The one genuinely optimistic
side is the STOP: a real stop gaps through and fills worse, while a target cannot fill
better than its limit.

=== Q3: skipping candles that opened before the plan ===
Correct, and the right conservative choice. `if t0 < pl["ts"] - 1: continue` with the
comment "its range may predate it" is exactly right. The 1-second tolerance is
harmless. No change needed.

=== ONE MINOR THING, flagged so it is not mistaken for a bug later ===
The timeout closes at the candle CLOSE of the first candle whose close is at or past
the deadline (t0 + 300 >= fill_t + max_hold_h*3600), so a "48h" plan can run to 48h
5m. Irrelevant at this scale.

=== THREE PLAIN RULES ===
 1. Leave the tie rule alone. It decides 0.115% of plans -- 147 of 127,811.
 2. Skip the fill candle. It can decide 9.62% of limit plans, 51.9% of tight ones.
 3. Label the fills. Grading assumes exact fills at entry, stop and target; a live
    stop will do worse than a graded one.

=== TWO NOTES ON THE PLANS PROMPT (lines 82-84), WHICH ALREADY CARRIES MY CORRECTIONS ===
Thank you for updating it. Two refinements from missions 1 and 2:
 * "the 50-day average holds from above more than chance" is TRUE but only for the
   SIMPLE 50-day average. levels.py:78 used c.rolling(50).mean(); scanner.py flags the
   EMA, and the EMA version shows -0.5 vs null (nothing) against the SMA's -5.1. If the
   prompt or the scanner means the EMA, the claim does not hold. Worth saying which.
 * "the 20-day low breaks MORE" is also true as a LEVEL claim, but SCANNER_FLAGS found
   no tradeable excess either way from it (median excess = -0.180% = exactly the fee,
   win rate 42.7% vs a 43.5% base rate). A level can break more often than chance and
   still return nothing. Suggest "breaks more often than chance, but shorting it has no
   measured edge after fees" so the LLM does not infer a trade from it.

LIMITS: 22 symbols with 5m history; the ambiguous rate depends on 5m range vs bracket
width, so a far more volatile regime would raise the 0.115%. Limit-entry geometry is
emulated as "entry 0.5 stop-distances from price", a guess at the owner's habit -- a
limit placed further away fills less often and contaminates less. I did not audit
_stats, the Opus review path, or OWNER_PLAN_EXEC. NOT RED-TEAMED: provisional.

All four missions are now done and pushed. Next from me unless you redirect: a red
team over missions 1-4, since every one of them is currently marked provisional and
this week's record says that matters.
