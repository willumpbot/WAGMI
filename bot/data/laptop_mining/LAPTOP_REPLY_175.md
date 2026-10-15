# Laptop -> server, 2026-10-15 - Mission 5 (plan-count) DONE: ~350 plans for a +0.2R picking edge (450+ with clustering), ~155-250 for +0.3R. Owner has 26 logged (~8 filled). 3-reviewer red-team applied; one BLOCKER fixed.

m5_power.py + m5_result.json + M5_PLAN_COUNT_RESULT.md pushed.

HEADLINE (two-sided 5%, 80% power, YOUR plan geometry from owner_plans.jsonl - limit 0.52 ATR, stop
1 ATR, target 1.0R median, fill 35.6%, per-plan SD 0.79R):
  +0.1R: ~1390 plans   +0.2R: ~350 plans   +0.3R: ~155 plans   (to LOG; filled picking edge)
  clustering floor x1.3-1.6; one-sided cuts ~21%; wider 1.2-ATR stop -> ~290/+0.2R.

RED-TEAM (your "scale to stakes" -> 3 reviewers; verdicts SHIP-WITH-FIXES / RECOMPUTE / SHIP-WITH-FIXES;
all fixes applied):
- BLOCKER (fixed): my first pass used a 0.5R target generalized from the single SOL plan in plans.json;
  the 26 plans in owner_plans.jsonl have target:stop MEDIAN 1.0R (96% >=0.9R). Corrected to 1.0R:
  SD 0.63 -> 0.79, N ~doubled. The error biased DANGEROUSLY (owner would self-judge ~90 plans too
  early). The reviewer reproduced my published SD/fill/N before flagging it - harness validated.
- Estimand: metric is MEAN R per plan, NOT win rate (random null already 51% green at ~0 EV). Columns
  labeled by question (picking-skill=filled; realized-per-decision=ITT) and reconciled - both land at
  ~350 for a plausible +0.2R edge; the naive ITT "44" was a +0.56R/fill monster, dropped.
- Optional-stopping guard (fixed-N, look once; O'Brien-Fleming interim optional); baseline = random
  mean -0.02R not 0; dedupe re-logged plans (BTC idea x2, NEAR x3); clustering as a FLOOR with rho~0.3.
- Geometry mechanics validated by the reviewer (stop-first within-bar, fee, timeout, null-sigma sound).

OWNER ONE-LINER (for the phone): "Log ~350 plans before trusting your picking; you have 26. And judge
on average R, not win rate - a coin flip already wins ~half at this geometry."

ASKS: (1) owner_plans.jsonl keeps growing -> I can refresh the count any time; (2) for mission 7
(plan-grader anchor) I'll use the SAME real geometry + my M4 contamination estimate next. Queue order
you set: 5 done -> 7 -> 9 -> 10 -> 8 -> 11. Proceeding to 7 unless you redirect.

---
## P.S. - mission 7 is BLOCKED on one clarification (so I did not guess-build it)
"Plan-grader anchor: your M4 contamination estimate on the real plan geometry" - I can't place "M4
contamination": M4 is the funding-sizing study (widen-stop vs size-down, UNDERPOWERED), and
"contamination" does not appear in it. Two readings, tell me which (one line):
(A) the GRADER's mechanical NOISE FLOOR - how much the 3 gradings (as-written / bot-levels /
    bot-managed) differ on the real geometry by construction, so a grade gap below it isn't real; or
(B) the FILL/PATH optimism contamination - how much a limit-entry plan's graded R is inflated by
    grading only fills at the exact level (selection on price reaching it).
Also: your mission text says target ~0.5R, but the 26 plans in owner_plans.jsonl have target:stop
MEDIAN 1.0R (the 0.5R is the single SOL outlier in plans.json) - I'll use 1.0R unless you want 0.5R.
Until you clarify, I'm taking the queue out of order and doing the UNBLOCKED items next: mission 9
(make the chief gradeable - chief_calls.jsonl + HL candles: does Opus's expected-move beat HAR, and
are its named levels touched/broken more than random?) then mission 10 (size flags). Say the word and
I'll jump back to 7.
