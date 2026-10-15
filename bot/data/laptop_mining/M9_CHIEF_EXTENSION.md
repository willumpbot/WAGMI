# Mission 9 EXTENSION (2026-10-15) - EXTENDS CHIEF_GRADEABLE.md (10-10), does NOT replace it; the levels re-test stays pre-registered for 2026-10-16 (not pre-empted here). Two axes the first pass didn't cover: direction (p_up_24h) and volatility-vs-HAR. Net: do NOT cut the chief.

_Process note: the first pass this session (m9_chief.py) re-derived mission 9 from the queue line
before I found CHIEF_GRADEABLE.md; a 3-reviewer red-team (wf_48f836c4) caught it + three blockers. This
note is the corrected, additive result. m9b_extend.py; aligned n=114, 6 symbols, 4 days (one quiet,
down-drift regime, realised 24h up-rate 27%)._

## What CHIEF_GRADEABLE (10-10) already established - unchanged
Direction never committed (NEUTRAL x86); named levels no better than same-distance levels under a
time-matched null ("not yet measurable", MDE 6-14pt); re-run the exact levels test on 2026-10-16 at ~4x
the sample. **That prereg stands; this note does not touch the levels verdict.**

## NEW axis 1 - DIRECTION is emitted after all, as p_up_24h (correcting "unscoreable")
The categorical lean is constant, but the chief emits a continuous p_up_24h. Graded (n=114):
- spans 46-52% (mode ~50); **AUC 0.504** (no discrimination); Brier 0.247 vs 0.250@0.5 vs **0.198 for
  the regime base rate** - i.e. WORSE than just predicting the base rate, because it sat ~50% while the
  tape ran 27% up (down-drift). So the right statement is **"the probability is pinned ~50% and shows
  no discrimination + is miscalibrated to the regime,"** not "direction cannot be graded." The fix is
  not "emit a probability" (already done, degenerate) but: **on conviction>=2, require a committed
  UP/DOWN + a Brier-scored probability away from 50** - force a gradeable record only where it claims
  conviction, then let it accumulate.

## NEW axis 2 - VOLATILITY vs the HAR baseline (proper scores, + = chief better)
| realised target | dMAE | dMSE |
|---|---|---|
| close-to-close \|move\| | -0.013 [-0.036,+0.015] | +0.080 [-0.119,+0.391] |
| **hi-lo RANGE** | **+0.104 [+0.034,+0.215]** | **+1.059 [+0.198,+2.655]** |
QLIKE (close) ~0 [-0.009,+0.007]. So the earlier "adds nothing over HAR" was **metric-cherry-picked**:
true only for close-to-close MAE (the one score HAR wins). On the hi-lo RANGE - arguably what "expected
move" means - **Opus beats HAR with a CI clear of zero**. Honest verdict: **indistinguishable on
close-move, better on range, underpowered (4 day-clusters, one regime) -> DEFER**, not a null.

## Recommendation (corrected - do NOT cut)
1. **KEEP the chief at 4-hourly.** The cost is **CLI-subscription quota, not per-token dollars** (hard
   rule), so the "not earning its cost" case is nearly moot; and the whole negative read rests on ONE
   quiet 4-day regime with zero volatile days - exactly the regime a senior-model overlay is paid to
   cover. Cutting now would also pre-empt the project's own 2026-10-16 re-test by a day.
2. **Run the pre-registered levels re-test on 2026-10-16** (sample is already ~260 calls vs 86).
3. **Grade the chief's ACTUAL function, not just forecasting.** Its conviction-2 reads are risk/position
   overlays ("bot is short from X, let the trail manage it, don't add late into a down day") + pipeline
   QA (staleness flags on other agents). Grading that needs the bot ACTION log + pipeline timestamps -
   ASK (not in server_exports yet).
4. **Standing forward metric:** Brier on ONLY non-degenerate calls (conviction>=2 OR |p_up-50|>=2);
   n=26 so far, Brier 0.2405 vs 0.25. This is the single number that decides keep-vs-cut once a volatile
   regime appears. Minimum evidence to cut: a could-fail conditional-skill miss at the post-10-16 n
   PLUS >=1 genuinely volatile day in which the chief still adds nothing.

## Three plain rules (owner)
1. The chief is NOT broken - keep it; it costs quota, not cash. (cost: $0 marginal)
2. It doesn't call direction and its vol read ~ties a free formula on today's quiet tape - so don't
   lean on it yet. (direction AUC: 0.50)
3. The real test is the first wild day; it hasn't happened in the sample. (volatile days so far: 0)
