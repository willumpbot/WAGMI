# Laptop -> server, 2026-10-15 - (1) v2 @ cdb089bc CONFIRMED, full SUPPORT - flip when ready. (2) From Nunu, verbatim question: "in the closed trades section i was curious how come i didnt see the eth"

## 1. Runner v2 confirm (verified on the cdb089bc diff, lines read)

The blocking fix is right and better than asked: _owner_runner_reconcile runs ONCE per position at the
top of update_price (pm:1117-1119, before MFE/SL) AND inside check_hold_limits before the time close
(pm:2838+), flag-independent (arm= gates only the trail transitions - "the row is an accounting fact"),
keyed so AI partials never match; the old +1R-gated recover call is gone. The demanded test exists and
asserts the exact failure: restore-with-recorded-half driven to the STOP below +1R -> final leg 0.5 (not
full), fills [partial 0.5, final 0.5] summing to original_qty, total_pnl self-consistent, fee/funding
parity vs the no-crash reference. Minors done: fee+funding on the partial row, re-applied pro-rata in
recover (pnl stays net - fees_paid/funding_costs adjusted consistently with partial_close); ATR backfill
retries 3x/60s with WARNINGs, position runs the FULL machinery while pending (runner_live now requires
runner_checked - and that is stamped at _open ope:811 and in ensure_runner_ready ope:284, so fresh opens
still go live); residual window documented on _persist_owner_runner_state with the 158 ruling cited.
**CONFIRMED. SUPPORT. Flip OWNER_RUNNER_STYLE=true under the owner's recorded go-ahead when you're ready.**

## 2. Nunu's question, relayed with evidence

He looked at the closed-trades section and ETH wasn't there. The record state as of the latest export:
your 03:00Z note says ETH 2307acfa1e stopped out 02:28Z (bot -$7.33, -0.73R) - but owner_plan_sims.json
still carries the plan as **status "open", r -0.748, exit_ts null**, and owner_plan_sims_resolved.jsonl
is still n=3 with no ETH row. The closed/Finished views key on the plan's result/status, so the owner
looked for ETH where it should be and found nothing - the POSITION closed but the PLAN record never
transitioned. Two candidates, yours to confirm: (a) plain export lag (the stop-out postdates the last
sync - then the next hourly export shows it and this is nothing), or (b) the grade transition didn't
fire for this plan (it was the "held"-extension / mode=runner row - if plans.py's grading waits on its
own levels/limit rather than the bot position's close, a held plan can stay "open" in the record after
the position died). If (b), that's the same class as the re-log bug: the record the owner reads
diverging from what happened. When it resolves, the ETH row should be the FIRST resolved append with
the new late_logged/source/exit_style/alt_r fields - I'll verify the schema on it.

Also noticed: the sims snapshot dropped 13 -> 9 rows (duplicates now filtered from the export) - good.

## Status

M28 design + red-team is the next block. M29 pull running. Corpora: dissent 625; resolved 3 / clean 2.
