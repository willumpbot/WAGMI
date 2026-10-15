# Mission 7 (B, 1.0R) - the plan-grader's optimism on a LIMIT entry is ENTIRELY selection-on-touch (+0.49R per filled plan), NOT the fill price (~0). A limit only fills when price comes TO it (a selected local extreme), so a filled limit grades ~+0.49R better than a market entry with ZERO skill. The grader's skill-anchor for a limit plan is the random-limit baseline ~-0.02R - NOT zero, NOT a market entry.

_2026-10-15. m7_fillopt.py, 176 coins, m5 geometry (limit 0.52 ATR, stop 1 ATR = 1R, target 1.0R, 24h
fill window, 48h hold, 9bps), random both-sided entries (direction-NULL). EXPLORATORY; the number is a
grading ANCHOR, not a live change._

## The two components of the grader's optimism (R per FILLED plan; wider coin/day-block CI)
| component | value | meaning |
|---|---|---|
| **SELECTION credit** (limit-filled R - market-at-plan R) | **+0.492 R [+0.460,+0.523]** | the limit's mechanical better-entry from waiting for a pullback to a selected level - available with ZERO skill |
| FILL-TIMING (fill@exact-level - fill@tagging-bar-close) | -0.000 R [-0.010,+0.010] | grading the exact wicked level vs a realistic fill - negligible (maker fills AT the level) |

Context: graded limit-filled mean **-0.017 R** vs market-at-plan-time mean **-0.509 R**. The entire
+0.49R gap is the limit mechanic on a direction-null population.

## What this means for the grader (the anchor)
- The right NULL for a limit plan is the random-limit baseline **~-0.02 R per filled plan** (it already
  contains the +0.49R limit mechanic). The owner's DIRECTION skill = his filled-plan mean R minus
  (-0.02R). Grading against 0 over-credits him ~0.02R; grading against a market entry over-credits him
  ~+0.49R (it hands him the limit mechanic as if it were skill).
- This is the SAME -0.017R baseline M5 measured independently - the two missions reconcile exactly.
- Fill-price realism does NOT matter here (+/-0.01R); do NOT spend effort modeling slippage/maker-miss
  on these ~1-ATR-away limits. The selection is the whole story.
- Caveat: direction-null population; the +0.49R is the limit mechanic on NOISE, which is exactly the
  baseline a skill test must clear. The grader already keeps grader_view separate (PC 91523be3) - this
  is the number to anchor grader_view against.

## Rules for the owner (one number each)
1. A limit order gets you ~half an R better entry than buying now - but that's the ORDER TYPE, not you
   being right. (+0.49R per filled plan, with zero skill)
2. So "is my plan good" = beating about **-0.02R** per filled plan (what a coin-flip limit plan scores),
   NOT beating zero. (baseline -0.02R)
3. Exactly where you fill barely matters; the waiting-for-the-pullback is what moves the number.
   (fill-price effect ~0.00R)
