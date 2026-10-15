# Mission 5 - "how many plans before I can judge myself?" ANSWER: ~350 plans for a solid +0.2R picking edge (realistically 450+ if they cluster), ~155-250 for a strong +0.3R. You have 26 logged (~8 filled). You are at the very start - do NOT grade your picking yet.

_2026-10-15. m5_power.py on 176 coins, real hourly candles, YOUR plan geometry (from the 26 plans in
owner_plans.jsonl): limit entry ~0.52 ATR off spot, 24h to fill, stop ~1 ATR, target ~1.0R (your
median), 48h hold, 9bps. 3-reviewer red-team applied (one BLOCKER fixed: an earlier version used a
0.5R target from a single outlier plan and understated the count by ~50%)._

## The three rules (one number each)
1. **Don't judge your plan-picking yet.** To confirm even a solid +0.2R-per-plan edge you need to LOG
   about **350 plans** (two-sided, 80% power); you've logged **26**. A very strong +0.3R edge still
   needs ~155. You are ~7% of the way there.
2. **Judge on average R, NOT win rate.** A zero-skill random version of your exact setup already closes
   **~51%** green (small target, wider stop -> many small wins, few full losses). A green-heavy record
   proves nothing; only the average R per plan, vs a coin-flip baseline of about **-0.02R**, answers
   "am I good."
3. **When you do test, look ONCE.** Decide the number up front and check significance a single time at
   that N. If you re-check after every plan and stop at the first good p-value, your false-positive rate
   runs toward **~100%**. (If you must peek, one interim look at the halfway mark costs only ~10-15%
   more plans.)

## The number, in detail (filled-edge = your picking skill, expressed as plans to LOG)
Per-plan R dispersion from the sim: SD **0.79R** (filled), fill rate **35.6%**. N = 7.85 x SD^2 / Delta^2.

| edge you want to detect | plans to LOG (stop 1 ATR) | with clustering (x1.3-1.6) | one-sided 5% |
|---|---|---|---|
| +0.1 R / plan (small) | ~1,390 | ~1,800-2,200 | ~1,100 |
| **+0.2 R / plan (solid)** | **~350** | **~450-555** | **~274** |
| +0.3 R / plan (strong) | ~155 | ~200-250 | ~122 |

Wider stop (1.2 ATR, the bot's suggestion) shrinks dispersion a little -> ~290 / ~129 for +0.2/+0.3R.

## Why "350", and the two honest framings (they agree)
- **Picking skill** (the question you mean): "when my limit fills, do I land in +EV spots?" Dispersion
  of a filled plan is 0.79R, and only ~36% of your plans fill, so you must LOG ~350 to get the ~124
  fills needed for +0.2R.
- **Realized per-decision** (the other legit question): "what does my average logged plan net,
  counting the no-fills as zero?" This needs ~350 logged plans too for the SAME +0.2R picking edge
  (the no-fills dilute a +0.2R fill-edge to a +0.07R per-logged-plan shift). The two framings reconcile
  at ~350 - so the number is robust to which one you prefer.

## Caveats carried (reviewer-required)
- Baseline is the random-entry mean (~-0.02R), which already pays your 9bps; "edge" = your mean minus
  that, not minus zero.
- SD assumes your picked setups disperse like random entries; if you systematically pick higher-vol
  coins, treat the counts as a FLOOR.
- Your 26 logged plans contain re-logs (two BTC rows are the same Claude idea minutes apart; NEAR
  recurs 3x) - dedupe before counting; your effective unique count is lower than 26.
- Clustering: plans resolving in the same market stretch are correlated (crypto beta). The headline
  holds only if you SPACE plans across distinct regimes; several in one trend-week multiply the count
  by ~1.3-1.6. Spacing them out is the cheapest way to need fewer plans.
