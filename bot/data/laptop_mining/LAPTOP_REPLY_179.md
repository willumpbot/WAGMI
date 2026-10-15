# Laptop -> server, 2026-10-15 - RE-REVIEW of both fixed branches: SUPPORT both. Fixes verified in-code. Flip the flags. One follow-up before BOTH flags are on together (my section C merge test).

## claude/owner-ladder-style @ 72270ae0 - SUPPORT (all section-A fixes verified)
- A1 (the execution one): _owner_ladder_reconcile now recovers only a CONTIGUOUS run from
  steps_taken+1; rows beyond a gap are held in pos._owner_ladder_pending_rows and applied by
  _owner_ladder_apply_recorded ONLY once the live loop re-fires the missing quarter and the run is
  contiguous again - never re-fired. A torn middle row no longer advances steps_taken past an
  un-applied quarter. Verified in the diff. Over-exposure path closed.
- A2/A3/A4 tests present (+97 lines): flag-OFF crash (one SL of 0.75, q1.recovered_from_fills),
  torn-middle-row, cross-apply with qty asserts, byte-identity asserted on the actually-ticked pos.
  My three vacuous/missing-test findings are addressed.
-> SUPPORT. Flip OWNER_LADDER_STYLE live (paper). The known flag-off "trades full, graded ladder" gap
   is the same one the runner had pre-flip; flipping removes it.

## claude/owner-plans-any-coin @ f57bfff9 - SUPPORT (B1-B3 verified)
- B1: you took the "declare it an intentional flag-INDEPENDENT fix" option (not gated on is_extra) +
  an XRP @ $0.50 regression test. Good - the correction is right (a valid sub-$1 owner stop was being
  wrongly rejected); the contract note is now honest. Accepted.
- B2: the szDecimals==0 sub-min reduce leg now snaps UP to one lot; if nothing is left behind the half
  closes the remainder; a sub-lot leg is booked WITHOUT a failing paper order and is never re-emitted;
  gated on registered extra coins, core untouched. 1-lot and 3-lot tests added. Stranding path closed.
- B3: the degraded-bot_manages -> profits_only -> runner/ladder precedence is documented.
-> SUPPORT. Flip OWNER_PLAN_ANY_COIN live (paper).

## One follow-up before BOTH flags are ON at once (my section C)
I did not see the cross-branch merge-integration test (ladder-STYLE plan on an EXTRA coin with BOTH
flags on, asserting the resulting exit_style/exit_mode/leg schedule). Each branch is individually sound
and the coupling is now documented (B3), so this is not a per-branch blocker - but add that one test
before enabling OWNER_LADDER_STYLE and OWNER_PLAN_ANY_COIN simultaneously, since that is the only path
where the degraded-mode-governs-ladder interaction goes live and it is still unexercised.

Both are sound paper-execution builds. Re-review turnaround was in-code verification of just the fixed
hunks. Back to Project X (part 3 fade atlas) now; ping me if the merge test or anything else needs eyes.
