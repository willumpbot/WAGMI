# M22 - DEFERRED, measured by the panel before any harness ran: the unfreeze question is n~=1 on this history, and the frozen gate was never recorded per-trade for 87% of it. Plus a forward fix the server can start now.

_2026-10-16. The design pre-authorized DEFER/UNDERPOWERED; the 3-judge panel measured the subset and
it fires. No harness built; no gate ever touched._

## Why deferred (measured, not estimated)
- THE UNFREEZE QUESTION IS n~=1. Point-in-time, SERVER_EXPLORE A's living long-block UNBLOCKS vs the
  frozen block-ON exactly 1/119 times once n_eff>=13; the block survives the living formula just as A
  found. Of 27 raw block-flips, ~26 are the early n_eff<13 all-time-fallback decisions, not
  evidence-based unblocks. "Would unfreezing the block have helped" has ~one differing trade to learn
  from - UNDERPOWERED by construction.
- THE FROZEN STATE IS NOT A LIVE RECORD for the bulk. The side gate (long block / 0.25x-1.5x size /
  solo) first appears in entry_gate_log on 2026-07-27; 258/295 trades (104/119 longs) opened BEFORE
  that, and conf_floor_decisions (Sep-13 on, 21 trades) is a DIFFERENT gate (confidence floor). So a
  frozen-vs-living P&L over the bulk would be formula-vs-formula, not live-vs-counterfactual - the
  "what the gate actually was" framing is unsupported pre-Sep.
- Secondary confounds the panel measured (each alone enough to caveat, together decisive): the ledger
  timestamp is CLOSE not open (75/295 would leak a later-opened trade's outcome if walked naively -
  fixable but telling of how thin the margin is); 64% concurrency means the live gate saw in-flight
  positions the point-in-time window cannot; all 81 realized_rr rows are post-2026-07-15 so recency
  weighting (45d half-life) feeds the living m almost entirely from reconstructed R on the old side
  and realized R on the recent side; and the frozen fee-filter universe (22 longs) vs the living
  no-filter universe (119) is a 5x mismatch.

## What CAN be said (labeled, not the unfreeze verdict)
The size-reweight delta (frozen 0.25 -> living ~0.81 long) is computable on the genuine-gate window
(2026-07-27 on) - but it answers "should size scale with recent R", not "should the block unfreeze",
and it is dominated by continuous re-weighting, not block flips. If the server wants that number it is
a separate, clearly-non-unfreeze read; I did not run it unprompted because the backlog's M22 question
is the BLOCK unfreeze, and that is the n~=1 cell.

## 🔴 The forward fix (the useful output)
The unfreeze question is answerable PROSPECTIVELY, not retrospectively: start recording the live side
gate's block/size decision PER TRADE now (the way conf_floor_decisions already logs the confidence
floor). Then the frozen-vs-living shadow becomes a clean forward comparison, and M22 re-opens when
block-flips reach n >= ~15. Re-open trigger: n_block_flips >= 15 on genuinely-recorded live gate state.

---
**What matters:** the unfreeze decision cannot be backtested on this history (n~=1 block flips, frozen
state unrecorded for 87%); keep the live shadow accruing.
**What would change it:** the server logging the live side-gate decision per trade from now, so a
forward shadow accumulates recorded flips.
**Confidence:** high - every number was measured by the panel on the real exports before any harness
was written; this deferral spent no compute on a doomed P&L.
