# M32C FADE-SIGNAL PREREG (design, pre-seal) - graduate the fade-vs-run tell from EXPLORATORY to a CONFIRMATORY test. The honest confirmation is FORWARD (the atlas already saw all 176 coins x all dates, so there is no clean in-sample holdout); a within-sample split is CORROBORATIVE only. Panel vets this BEFORE any freeze or read.

**Status: DESIGN. Nothing sealed or read yet. 3-judge panel first; adopt fixes; THEN compute + record
the frozen thresholds and seal.** References M28_SPLIT_SEAL.md (same fishing guard: many conditions ->
false finds; M28's own discovery did NOT survive, so treat a positive here with equal suspicion).

## 0. The claim being tested (one sentence)
At the +0.5R bar, an IMPULSIVE move (high volume-surge AND/OR fast velocity) RUNS more often and a
QUIET/SLOW drift FADES more often; and conditionally laddering only the FADE-PRONE subset improves the
outcome DISTRIBUTION vs uniform policies at no worse mean. Discovery (exploratory, all coins): base
P(FADE)=0.642; volume-surge low 0.696 -> high 0.573; velocity slow 0.669 -> fast 0.611; survived the
window/regime/vol-tier confound controls.

## 1. The ONE frozen rule (collapses the ~7 explored buckets to a single pre-specified classifier -> no
further multiplicity). At the +0.5R bar, point-in-time (bars <= b05 only):
  vel  = b05 (bars entry->+0.5R);  vs = V[b05] / mean(V[entry-72 .. entry-1])
  FADE_PRONE  :=  (vs <= S*)  AND  (vel >= Vel*)      # quiet AND slow
  RUN_LIKELY  :=  NOT FADE_PRONE
S* and Vel* are DEFINED as the medians of vs and vel on the DISCOVERY population (below), computed ONCE
at seal and RECORDED here for audit. (Composite chosen a priori as the intersection of the two tells
that survived controls; volume-surge is primary, velocity the tie-breaker.)

## 2. Populations
- DISCOVERY (sets S*, Vel*, and the predicted effect): ORIG17 coins all dates + non-ORIG17 on days <
  the M28 recorded-median daykey (reuse M28_SPLIT_SEAL's exact boundary).
- PRIMARY CONFIRMATION = FORWARD: +0.5R moments whose ENTRY ts is AFTER the seal timestamp, ANY coin.
  Clean (unseen at seal). Read at n>= the power target (sec 4) or a pre-set date, whichever first.
- CORROBORATIVE (NOT confirmation): non-ORIG17 coins on days >= the median, under the frozen S*/Vel*.
  Contaminated because the CIRCUMSTANCE selection used the full sample; reported descriptively, labelled,
  never as the confirmation. (A clean held-out does not exist post-exploration; stated plainly.)

## 3. The two reads (both pre-specified)
(a) SEPARATION: P(FADE|FADE_PRONE) - P(FADE|RUN_LIKELY), wider of coin/day-block CI; must exclude 0 AND
    exceed a SUBSTANTIVE margin >= 0.05 (not just significant). Predicted ~+0.10..+0.13.
(b) R-CONSEQUENCE (the thing that matters): a CONDITIONAL policy (quarters on FADE_PRONE, runner on
    RUN_LIKELY) vs uniform-quarters AND vs uniform-runner, on the DISTRIBUTION (P(loss), give-back, SD,
    P(<=-1R)) and on the mean NET of the persistence-preserving null. The signal is only useful if
    conditioning beats BOTH uniform policies on the distribution without a worse null-subtracted mean.

## 4. Power / stopping (forward)
State MDE for the 0.05 separation margin at the coin-cluster level before any read; pre-set the forward
n (or date) to reach 80% power. DEFER/UNDERPOWERED is a legitimate outcome. No peeking: read ONCE at n.

## 5. Guards (the panel must harden these)
- LOOK-AHEAD: vs/vel use only bars <= b05; assert. The FADE/RUN label is post-b05 - never a feature.
- b05-BAR IS PARTLY THE MOVE: V[b05] and the range at b05 include the move that crossed +0.5R, so a big
  move mechanically has a big bar. This is point-in-time (knowable at +0.5R) so it is not look-ahead,
  but the panel must decide whether vs should EXCLUDE the b05 bar (use V up to b05-1) to remove the
  mechanical component; pre-register that choice.
- MULTIPLICITY: ~7 buckets were explored; the rule is now ONE composite. Do not test variants on the
  forward data. The within-sample corroborative read is not a second test of the hypothesis.
- MECHANICAL R: the R-consequence must be null-subtracted (the quarters-vs-runner gap is ~0 on the
  mean per M32; the claim is the DISTRIBUTION under CONDITIONING, not a mean edge).
- MODEL MEMORY: claude-idea / bot-decision rows excluded (forward-graded only). Owner decisions are
  labels, never selection.
- Shadow never writes a live gate; a surviving forward result + owner go are required for any rule.

## 6. Panel questions
(a) Is the forward-primary / corroborative-only framing correct, or is there a defensible clean
    in-sample holdout I am missing? (b) Should vs exclude the b05 bar to kill the mechanical component -
    does the signal survive vs-up-to-b05-1? (c) Is the composite AND the right collapse, or does it
    throw away the single best univariate tell (volume-surge alone)? (d) Is the R-consequence metric the
    decision-relevant one, and is its null handled? (e) MEASURE the forward MDE and the expected
    forward n-rate (+0.5R moments/day across coins) so the stopping rule is real, not aspirational.

---
# FREEZE / SEAL (v2, 2026-10-15, after panel wf_fa2fe1d3 - all FATAL+MATERIAL adopted; I verified the clean numbers in-code on the discovery population myself because two judges disagreed)

## Honest in-sample result (DISCOVERY, 174 coins, 15,424 scored moments; clean = b05 bar EXCLUDED)
- surge-ONLY (clean): sep +0.0445 [+0.0180,+0.0697], eqw +0.0443, sign 0.66 -> BELOW the 0.05 floor.
  (The design/holdout judge's 0.071 leaked the trigger bar; my clean compute = 0.045. surge-alone is
  mostly the mechanical crossing-bar magnitude - DROPPED as the primary.)
- COMPOSITE (clean): FADE_PRONE = (clean surge <= S*) AND (velocity >= Vel*). sep +0.0695
  [+0.0312,+0.1106], eqw +0.0689, sign 0.76. Point/eqw/sign clear 0.05; the WIDER-CI LOWER BOUND
  (+0.031) does NOT. Replicates in the corroborative subpop (+0.065 [+0.012,+0.118], eqw +0.070).
- VERDICT: the fade signal is REAL and DIRECTIONAL (excludes zero, replicates out-of-subpop) but
  MODEST - once de-mechanized it does NOT robustly clear the 0.05 substantive floor on the lower bound.
  Not strong enough for a hard automatic rule; fine as an INSIGHT annotation.

## FROZEN rule (sealed; forward confirmation only)
- vs (clean surge) = V[b05-1] / mean(V[entry-72 .. entry-1])  (EXCLUDES the +0.5R crossing bar). b05==0
  moments are DROPPED (no pre-trigger bar).
- FADE_PRONE := (vs <= S*=0.6907) AND (velocity b05 >= Vel*=9.0). RUN_LIKELY := otherwise.
  S*, Vel* = discovery-population medians, recorded here, FROZEN.
- Predicted forward separation = +0.070 (discovery clean composite); planning value for power = 0.055
  (winner's-curse shrink); optimistic ceiling 0.074.

## Forward confirmation bar (ALL must hold; read ONCE at n/date; no peeking)
1. SEPARATION: wider-of-coin/DAY-BLOCK CI LOWER BOUND > 0.05 (not the point estimate). Day-block is
   the binding (wider) cluster (one BTC regime/day). "Excludes 0" is a separate weaker directional read.
2. eqw-by-coin separation > 0.05 AND fraction-of-coins-correct-sign > 0.65 (M28 lesson: pooled can
   survive while eqw flips).
3. R-CONSEQUENCE (read b): ONE pre-specified primary distributional metric (give-back magnitude on the
   FADE_PRONE subset under conditional-quarters vs uniform-runner), its own day-block MDE and forward n,
   pass = primary improves by >= a pre-set economic amount AND the null-subtracted mean is no worse,
   tested against a LABEL-CONDITIONAL null (permute FADE_PRONE within coin/day-block). Secondary metrics
   Holm-corrected.
- FORWARD population: +0.5R moments with ENTRY ts > the seal ts, any coin, claude-idea/bot rows excluded
  (model memory). Forward n for 80% power to clear bar (1) against planning 0.055 at day-block clustering
  ~= 13k-19k scored moments ~= 90-128 days at ~150/day. DEFER/UNDERPOWERED is a legitimate outcome.
- The within-sample corroborative read is DESCRIPTIVE only, barred from go/no-go (the atlas saw it).
- Shadow never writes a live gate; owner go required for any rule even if the forward bar is cleared.
