Trailing exit: the biggest single lever. Takes the loss -0.21R -> ~-0.04R. Not to profit.

Owner-prompted, and his correction was right. ADX_GATE said "signals are
negative-expectancy at every trend strength" -- but that was a FIXED bracket, which
throws away exactly what a trailing stop captures. He named the trailing exit as the
likely mechanism.

THE GAP WAS REAL. The trailing exit had NEVER been tested at a bracket that binds:
  exits.py:30     STOP_MULT = 8.0  "the geometry plateau"
  geometry_v3     x8 binds on only 14.3% of trades
  exits_v2.py     grep -c trail -> 0
v1 tested trailing where the bracket almost never fires; v2 did not test it at all.

=== 1. THERE IS A LOT ON THE TABLE (measurement, not inference) ===
Best favourable move in R before the stop fired or 48h elapsed:
  stop   mean exc   median      p90   reach+0.5R  reach+1.0R   STOPPED OUT
  x1       1.185R   0.802R   2.994R        61.6%       39.8%         68.7%
  x2       0.760R   0.507R   1.773R        50.4%       24.8%         39.6%
A fixed 1R target captures -0.209R of that. So roughly 1.6R per trade is offered and
not taken. Plain measurements, no null, no model.

BUT THE BINDING CONSTRAINT IS THE STOP, NOT THE EXIT: 68.7% of trades are already dead
at x1. A trailing exit cannot secure profit on a stopped-out position. Widening to x2
cuts that to 39.6%, which is why every x2 configuration beat its x1 equivalent.

=== 2. THE STACK DOES STACK (week means, net 9bps) ===
  fixed 1R target, x1 stop (the baseline)            -0.2086
  + tight trailing (arm +0.25R, trail 0.5R)          -0.1033   +0.105
  + widen stop to x2                                 -0.0993   +0.109
  + confidence >= 60                                 -0.0816   +0.127
  + confidence >= 75, trailing at x1                 -0.0433   +0.165
The machinery cuts the loss by ~79%. Tight trailing is the single largest contributor
on its own (-0.209 -> -0.103).
Trailing direction is consistent: trail 0.5R beat a fixed target in 6 of 6 stop/arm
combinations; trail 1.5R in 0 of 6. TRAIL TIGHT, NOT LOOSE.

=== 3. BUT IT CONVERGES ON BREAK-EVEN, NOT PROFIT ===
Best cell -0.0433R, week se 0.1427, t -0.30. The 95% interval runs about -0.32R to
+0.24R -- indistinguishable from zero either way. NOT ONE of the 18 trailing
configurations has a positive week mean. The machinery converts a clearly-losing
signal stream into something statistically indistinguishable from break-even. Real
achievement; not a business.

=== 4. THE CONFIDENCE FILTER IS THE WEAK LINK -- this is the new finding ===
  filter        n       trail x2    mean exc   stopped
  all      15,663   -0.0993+-.153      0.760R     39.6%
  conf>=60 10,631   -0.0816+-.134           -     35.8%
  conf>=65  9,168   -0.0866+-.140      0.731R     35.9%
  conf>=70  6,275   -0.0828+-.136           -     34.4%
  conf>=75  4,247   -0.1529+-.154      0.707R     34.0%
Non-monotone, and the TIGHTEST filter is the WORST cell in the column. More telling:
excursion FALLS as confidence rises (0.760 -> 0.731 -> 0.707) and the stop-out rate
barely improves (39.6% -> 34.0%). High-confidence signals are not better signals on
either measurement that matters. The confidence score is a large part of the bot's
complexity and it is not earning its place here.

That is worth your attention independently of the trailing question: it bears on
AdaptiveConfidenceFloor, which is the live gate, and on whether raising any confidence
floor can help at all.

=== TRADER RULES, one number each ===
 1. Trail tight, not loose. 0.5R trail beat a fixed target 6 of 6; 1.5R beat it 0 of 6.
 2. The stop is the bottleneck, not the exit. 68.7% of trades are stopped out at the
    current stop; widening to x2 cuts that to 39.6%.
 3. The whole machinery gets you to break-even, not profit. Best configuration
    -0.043R +-0.28 -- a 79% improvement that still cannot be distinguished from zero.

=== WHAT I CANNOT CLAIM ===
 * The trailing-vs-fixed comparison is UNDERPOWERED. Lag-placebo size 0.000 against a
   nominal 0.05, 80%-power MDE not reached within 0.20R. So the DIRECTION (6/6, and
   consistent across every confidence band) is real; the MAGNITUDE of the improvement
   is not established. Those cells are labelled unmeasurable per the standing rule.
 * This is MY trailing implementation, not the bot's. The live exit logic
   (core/position_wiring.py, tick_processor.py) may differ in arming, granularity and
   slippage. I simulated on 1h bars; the bot runs on ticks. If your trailing logic
   arms or trails differently, tell me and I will match it.
 * Fees only -- no funding, no slippage, no partial fills. 14 ISO weeks, one corpus.

=== THE ONE THING THAT WOULD SETTLE IT ===
trade_ledger.csv. Everything above is simulation on the raw signal stream with my own
exit code. The bot's realised fills answer the question directly -- does the live
machinery secure profit? -- with no simulation and no assumptions about trailing
behaviour. This is the FOURTH separate analysis today blocked on that file. If you can
export it (plus owner_plans.jsonl for mission 7), both become straightforward.

Panel cached at trailing_exit_panel.csv.gz so any follow-up analysis is instant --
no re-simulation. Ask for any cut of it.

Mission 5 (plans needed to judge the owner) next, then 7, 9, 10.
