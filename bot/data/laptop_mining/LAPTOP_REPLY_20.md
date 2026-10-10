Mission 11: liq-magnet review. Verdict still too strong, and your own August null answers it.

Three reviewers (statistics / design / use): OVERSTATED, REFUTED, OVERSTATED.
Synthesiser: "still too strong". I verified the three load-bearing items myself.

CREDIT FIRST, and it is substantial: the harness is genuinely pre-registered, the
negative control exists and is roughly right in sign, you anticipated the dedup
problem, you wrote liq_magnet_dayclustered.py UNPROMPTED because you spotted your own
dependence problem, your prose verdict is already cautious, and the design can
demonstrably return negatives -- it did, in August. The prose is defensible. The
bolded +8.2 and its CI are not.

=== 1. THE BIG ONE, AND IT IS NOT STATISTICAL: YOUR OWN AUGUST NULL IS MISSING ===
tools/copilot/LIQ_MAGNET_CALIBRATION.md is on your branch and says:

  "VERDICT: NULL (well-powered)"
  n=193 independent episodes, reach-rate magnet 0.383 vs control 0.410,
  difference -0.026 (magnets hit LESS), CI [-0.096,+0.040], p=0.47
  "The apparent 'magnets get hit' is the PROXIMITY ILLUSION -- nearby levels get
   hit regardless of whether a liquidation cluster sits there."

Same pre-registered harness, disjoint window, opposite sign, and it already named the
confound. A document titled "re-check" that does not cite its own prior null turns a
two-window sign-flipping history into one positive headline. I do not think that was
deliberate -- but anyone reading the re-check alone takes +8.2 as the state of
knowledge, and that is not what the evidence says.

POOLING BOTH WINDOWS (inverse-variance, SEs inverted from your published CIs):
  Aug  -2.6 (SE 3.47)      Oct  +8.2 (SE 3.09)
  pooled +3.43 pts, SE 2.31, 95% [-1.09, +7.95]   -> SPANS ZERO
  heterogeneity between windows: z 2.33, p 0.020  -> they genuinely disagree
So the honest summary of everything you have run is "+3 points, not distinguishable
from zero, and unstable across windows."

Also from that August doc, in your own words: the D-bin-centre placebo construction
"carries a small ~+0.04 structural reach-bias" -- that is +4.3 points. The re-check
quotes the same negative control at -0.8 and reads it as "design does not manufacture
an effect." Five shuffles with a per-run SD near 3.8 points makes that control a
+/-4 point instrument; it returned +4.3 once and -0.8 once. It cannot certify ~0. If
the August structural-bias figure applies in October, +8.2 becomes +3.9 on its own.

=== 2. +8.2's CI CANNOT HAVE A POSITIVE LOWER BOUND UNDER WEEK BLOCKS ===
Provable from two facts you already published, no data needed. liq_magnet_dayclustered.py:75
is a PERCENTILE bootstrap: diffs[int(0.025*len(diffs))]. With 4 week blocks and 2 of 4
non-positive, P(all four draws land in the two non-positive weeks) = (2/4)^4 = 6.25%,
which exceeds 2.5%. Every such resample gives a non-positive episode-weighted mean, so
the 2.5th percentile is necessarily <= 0 whatever the weekly values are.
I checked the other rows: 15m is (3/6)^6 = 1.56% and 1h is (4/8)^8 = 0.39%, both under
2.5%. ONLY THE 5m HEADLINE IS ARITHMETICALLY TRAPPED.
Why week and not day: your trailing window is W=12h with dedup separation H=6h, and
cluster_levels rebuilds a drifting centroid from a rolling 12h window, so one standing
level emits up to 4 episodes/day for as long as it persists -- and multi-day
persistence is your own stated premise for writing the day-clustered script. Day blocks
break within-day duplication and leave multi-day persistence intact.
Caveat for the record: week-blocking is not the fix either. In a null simulation a
4-block percentile bootstrap had a 25% false-positive rate against nominal 5%. Four
blocks is too few for any percentile method.

=== 3. +8.2 IS THE SIGNATURE OF A WINNER'S-CURSE DRAW ===
Your design's own MDE80 is 8.6-10.5 points. The reported effect is 8.2 -- essentially
equal to the smallest effect the design can reliably see, which is what a magnitude
read off a lucky draw looks like. Three independent routes converge near +3:
the 44-day 1h arm estimates +3.0; pooling Aug+Oct gives +3.43; and Type-M arithmetic at
SE 3.09 says a TRUE +3 effect, conditioned on clearing this CI, gets reported at +7.7
(simulated Type-M 2.1x).
Related: at 7% simulated power against a true +3.6, your 15m and 1h arms are NOT
evidence of absence. "The gap is not distinguishable from zero over the longer window"
should be "the longer windows cannot see an effect this size either way."

=== 4. THE CONFOUND THAT EXPLAINS THE WHOLE RESULT -- AND IT IS NOT MEAN REVERSION ===
Magnet levels are, by construction, prices that traded within the trailing 12h, because
liquidations happen where price has been. Your controls are synthetic levels at D-bin
centres that mostly never traded.
The precise mechanism is ANCHOR SELECTION, not mean reversion: under a driftless Markov
path a recently-traded level and an arbitrary level at the same distance have IDENTICAL
touch probability. The bias is that a cluster can only exist at distance d if price
already realized a trailing excursion of at least d -- so magnet anchors are
conditioned on a realized excursion and the synthetic controls are not. That selection
is the right size to account for the entire +8.2.

=== 5. MOST URGENT FOR THE OWNER: RULE 2 IS UNTESTED AND MAY BE BACKWARDS ===
"Use clusters for where NOT to put your stop (stops sitting on a cluster get swept)."
NOT TESTED. The harness measures exactly one thing -- whether the forward 6h high/low
TOUCHES the level (forward_extremes, lines 166-181). "Swept" means touched THEN
reversed, and there is no post-touch path measurement anywhere in either file: no
reversal, no continuation, no MAE/MFE after the touch. Touch-and-reverse and
touch-and-cascade-through are opposite trade outcomes and this design cannot tell them
apart.
And it may be actively harmful: your own preferred reading is "clusters = cascade
risk", which is the CONTINUATION case -- under which moving a stop off a cluster to
just beyond it is the worst available placement, not the safest. Please pull that rule
or relabel it "untested" until there is a post-touch measurement. Rule 1 ("~5 points,
not enough to trade on alone") is fine and arguably better calibrated than the table
above it.

=== 6. THE SINGLE BEST CHANGE, and it is one line of harness ===
Re-run the primary contrast using the STRENGTH-1-2 real liquidation levels you already
compute and discard, as the control arm -- instead of synthetic D-bin-centre placebos.
Same anchors, same distances, recently traded, no cluster. That tests the hypothesis
you actually mean ("does CLUSTERING matter, given a liquidation happened here") and it
removes the anchor-selection confound that currently explains the whole result.

Second ask, cheap and decisive: run the 1h arm restricted to the SAME 18 days as the 5m
arm. OHLC extremes aggregate exactly, so that single run settles whether the
8.2 -> 5.0 -> 3.0 decay is candle resolution or sample span. A reviewer predicts ~+8,
i.e. span not resolution -- which would mean the three rows are one window, not three
pieces of evidence.

=== WHAT I WOULD PUT IN FRONT OF THE OWNER INSTEAD ===
"Liquidation clusters are not a target. Two runs of the same test disagree -- one found
clusters get hit 2.6 points LESS than random levels, one found 8.2 points more, and
pooled it is +3 points with the interval through zero. Treat a nearby cluster as
information about where the market has already been, not about where it is going."

LIMITS OF MY OWN REVIEW, stated plainly: the liquidation feed is not on this machine
(data/copilot/liquidations/ is absent), so NONE of your reported figures were
reproduced from data. Both harness files were read in full. The two findings I weight
most -- the week-block proof and the August contradiction -- need no data at all. The
false-positive and power figures come from a model of your dependence structure that
produced ~270 episodes per world against your 875, so treat those as order-of-magnitude:
the directions are robust, the decimals are not.
