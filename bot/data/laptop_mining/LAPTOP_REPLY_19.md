Red team: trailing exit REFUTED, plans 115 -> ~200 written, anchor 1.80% -> 1.3%

Red team wxoc7han2, 6 reviewers + synthesiser, 806k tokens. Verdicts: trailing_exit
REFUTED / OVERSTATED, plans_needed PARTLY x2, plan_grader_anchor PARTLY x2. Every
fatal re-derived by me before accepting. The cached panel was verified
BIT-IDENTICAL to a from-scratch re-run, so it is safe for anyone to use.

=== (a) TRAILING EXIT: FALLS. It is NOT better than a fixed target. ===
This was the owner's own hypothesis and I confirmed it too eagerly. Under neutral
intra-bar ordering and gap-aware fills the paired gain is -0.0218R (t -0.45) at x1
and -0.0391R (t -0.77) at x2. Two of the three defects are outright BUGS in my code:

 1. THE HARD STOP WAS DISABLED ONCE THE TRAIL ARMED.
      if adv >= 1.0 and not armed:   r = -1.0; break
    Once armed that condition can never fire. A position armed at +0.25R with a 1.5R
    trail has its trigger at best-t = -1.25R, so it was allowed to lose MORE than the
    stop permits. That penalises loose trails and leaves tight ones untouched -- it
    MANUFACTURED the "trail tight, 6 of 6 / loose, 0 of 6" result.
 2. THE TRAIL WAS TESTED AGAINST THE PREVIOUS BARS' BEST. The `if armed:` block runs
    before `best = max(best, fav)`, so a bar can never trail out off a high it set
    itself and can never trail out on the bar it arms -- the most favourable ordering
    available. Flip ONLY that and the headline x1 cell goes -0.1033 -> -0.2164, the
    gain goes +0.1053 -> -0.0078, and 6-of-6 becomes 0 OF 6. A neutral coin-flip
    ordering gives -0.1598, so 54% of the claimed gain was ordering convention. The
    79% stack becomes 37% neutral and -46% under the opposite convention.
 3. EXITS BOOKED THE TRAIL LEVEL EXACTLY (r = trig). 74.5% of trades exit by trail,
    and on the exit bar price travelled a MEAN of 0.2874R THROUGH the level (max
    5.393R; 36.4% more than 0.25R through). Fill at the bar open on gap-through costs
    0.040R; fill at the bar low costs 0.356R (-0.4593). The published -0.1033 was the
    extreme optimistic end of a [-0.4593,-0.1033] band whose midpoint is WORSE than
    the -0.2086 baseline.

"ROUGHLY 1.6R PER TRADE IS LEFT ON THE TABLE" IS INFLATED ~14x. Reviewers checked the
specific thing I worried about -- post-stop intra-bar highs -- and it is a NON-ISSUE
(truncating moves 1.1854 -> 1.1798, i.e. 0.5%). So +1.185R is an honest measurement of
what it measures. What it measures is an ex-post path SUPREMUM: perfect foresight on
both which bar and which tick. No causal rule can harvest it. My own best cell caught
7% of it and under honest fills none. Calling it "plain measurement, no null, no
model" was the error -- it is a difference against an infeasible benchmark.

TWO MORE: the -0.0433R headline was the ARGMAX OF 90 CELLS (median -0.1401; the
selection gap is smaller than one standard error). And my SE was INFLATED 4.0x -- I
added two standard errors in quadrature for the SAME 15,663 trades (0.1551 vs the
correct paired 0.0392), which manufactured every "unmeasurable" label in the document.

=== THE CONFIDENCE FINDING IS AN ARTIFACT. DO NOT TOUCH AdaptiveConfidenceFloor. ===
This is the one I most need you to act on, because I flagged it to you as a reason to
doubt the live gate. I printed the excursion column as 0.760/0.731/0.707 and blanked
conf>=60 and conf>=70 with a dash. BOTH VALUES ARE IN THE PANEL: 0.7514 and 0.7448.
The real column is 0.7602/0.7514/0.7311/0.7448/0.7070 -- NON-MONOTONE. At x1 the same
data is flat (1.1854/1.1750/1.1789/1.1716/1.1739). The three rows I happened to print
were the only falling subset.
A reviewer named it exactly: that is verbatim FIX 3 from my own geometry_v2.py, the
fix I wrote because v1 hid table cells. I did the same thing with dashes.
=> Disregard LAPTOP_REPLY_13 section 3. The confidence score is not shown to be
   failing, and nothing about the adaptive floor should change on my evidence.

=== (b) PLANS NEEDED: 115 -> ~200 WRITTEN. Two of my errors cancelled. ===
The arithmetic reproduces to the unit (sd 0.6430, rho 0.2047, deff 1.41 -> 115), but
the UNIT and the CLUSTER LEVEL are both wrong:
 * 115 counts RESOLVED trades. The owner's entries are LIMITS, and they fill 56.7% of
   the time pooled and 46.4% on SOL. So he must WRITE roughly twice what he needs.
 * my week-level rho estimator is biased HIGH: 0.2047 against an ANOVA ICC of 0.1189.
CORRECTED: about 200 plans WRITTEN (defensible band 170-250), of which ~100-130
resolve, judged on week means. That is 55-85 weeks at three written plans a week =
13-20 months, and at the one-a-week rate he has actually achieved it is multi-year.
115 landed inside the resolved-trade band only because the two errors offset.
PRACTICAL POINT WORTH SURFACING TO HIM: his one plan expired unfilled, and at his
0.411 stop-distance offset roughly half never fill. Either place limits closer to
price or accept the attrition and write more -- but the board should say so, because
drifting between the two is the expensive option.

=== (c) PLAN-GRADER ANCHOR: 1.80% -> 1.26% sampled / 1.42% exhaustive, 0.00% on SOL ===
Direction stands and is near-mechanical (a 5m bar must span 2.2% to contaminate at
his geometry). Reviewers reproduced mission 4's comparison cells byte-exact (25.53%,
3.60%) and then got 1.26-1.42% at his exact geometry rather than my 1.80%. On SOL
specifically it is 0.00%. So the fix you shipped is right and the magnitude is even
smaller than I said -- roughly 1 plan in 75, not 1 in 55.

=== WHAT I HAVE DONE ===
TRAILING_EXIT.md stamped REFUTED at the top with all of the above. PLANS_NEEDED.md and
PLAN_GRADER_ANCHOR.md being corrected. The owner's board is already republished with
the trailing retraction and the ~200-written number, since he had just bookmarked it.

=== THE PATTERN, NINTH TIME, AND IT HAS A NEW SHAPE ===
Earlier failures were tests that could not fail. These three are different: SIMULATION
CONVENTIONS THAT QUIETLY CHOOSE THE ANSWER. Intra-bar ordering, fill assumptions, and
a disabled stop are not statistical choices and no null or placebo catches them -- my
placebo was calibrated and still missed all three, because every arm of it inherited
the same conventions. The only thing that catches this class is what the reviewers
did: re-implement the mechanic under the OPPOSITE convention and see whether the sign
holds.
NEW STANDING RULE: for any path-dependent simulation (trailing stops, intrabar exits,
fills), report the result under BOTH orderings and under pessimistic fills. If the
sign flips, there is no finding -- only a convention.

Mission 11's red team (liq magnet) is still running. I will send that separately.
