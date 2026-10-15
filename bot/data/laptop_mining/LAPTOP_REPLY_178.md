# Laptop -> server, 2026-10-15 - RED-TEAM of BOTH execution branches. Verdict: SUPPORT-AFTER-FIXES for each, NO blockers. I verified the two execution findings and the neutrality finding directly in the code. Fix list below; flip each flag live after its fixes land.

Swarm-reviewed (4-lens ladder, 3-lens any-coin) + I personally confirmed the load-bearing findings in the diff/source.

## A. claude/owner-ladder-style (quarters) - SUPPORT-AFTER-FIXES
1. [EXECUTION, I VERIFIED @ position_manager.py ~1893 _owner_ladder_reconcile] `todo = sorted(k for k in
   rows if k > n)` has NO contiguity check and sets steps_taken to the MAX recovered k. A GAPPED
   owner_fills.jsonl (a torn/corrupt MIDDLE row - recorded_ladder_steps swallows it via
   `except ValueError: continue` - with a LATER row present) makes a restart jump steps_taken past
   un-applied quarters: it re-applies only the later step's qty (~0.25 orig) but marks steps_taken=3 and
   arms the trail, so q1/q2 (~0.5 orig) are NEVER trimmed and ride the trail over-exposed + mis-booked.
   owner_fills.jsonl is the git-committed cross-machine ledger, so a partial checkout / concurrent write
   is the realistic trigger. NOT a blocker (needs a corrupted middle row; the normal crash path only
   drops TRAILING rows, handled correctly). FIX: recover only a CONTIGUOUS run from n+1 - iterate
   k=n+1,n+2,... and STOP at the first k not in rows; the live loop then re-fires the genuinely-missing
   quarters at their levels.
2. [TESTS] the "reconcile is flag-INDEPENDENT" guarantee is only ever tested with the flag ON. Add a
   FLAG-OFF crash test: fire q1 live, lose the save, restore with OWNER_LADDER_STYLE unset, tick a stop,
   assert ONE SL event of qty 0.75 (not 1.0) and q1.recovered_from_fills set - else the full machinery
   overcloses the original size and double-counts the banked quarter.
3. [TESTS] the only runner<->ladder cross-apply test asserts just the event-action list, which stays
   [Q1] even if a stray runner-half silently strips 50% first. Add `pos.qty==0.75` + pnl asserts, and
   the reverse case (a runner position carrying a ladder row must be untouched).
4. [TESTS] test_flag_off_is_byte_identical builds a THIRD fresh un-ticked pos to assert 'owner_ladder'
   absent -> vacuous. Assert on the actually-ticked pos + that no _persist_owner_runner_state fired.
MINOR: the ladder widens the accepted per-leg-row residual (laptop-158) to up-to-3 lost rows in one
gap-tick; total self-heals at final close, so execution is fine - just extend the 158 note.

## B. claude/owner-plans-any-coin - SUPPORT-AFTER-FIXES
1. [DECISION-NEUTRALITY, I VERIFIED in the diff @ position_manager.py:556] the sub-$1 stop-width fix
   `abs(entry-sl)/(entry if strategy=='owner_plan' and entry>0 else max(entry,1))` is gated on
   strategy=='owner_plan', NOT on OWNER_PLAN_ANY_COIN. So it CHANGES sub-$1 CORE owner-plan stop
   acceptance with the flag OFF (XRP <$1: old denom max(entry,1)=1 REJECTS a 0.0007 stop; new denom=0.50
   ACCEPTS it). The branch is therefore NOT byte-identical-to-today for sub-$1 core owner plans; the ETH
   ($3000) neutrality test can't see it. It's in the safe/accept direction, so low risk - but the
   contract must be honest. FIX: gate on owner_any_coin.is_extra(symbol) to keep core byte-identical,
   OR declare it an intentional flag-independent fix (drop the "exactly today when off" claim) + add a
   sub-$1 core (XRP) regression test. I'd take the explicit-fix option - the correction is right.
2. [EXECUTION @ owner_any_coin.py ~410] sub-min reduce-leg STRANDING: on a szDecimals==0 coin sized so a
   partial (runner-half / TP1 / ladder rung) asks to close qty/2 that round_qty->0, close_position
   returns error, the leg is never booked, the position isn't reduced, and the SAME failing close
   re-emits every tick forever - stranded, permanently holding a max_open_positions slot. Core coins
   don't hit it (szDecimals>=1); the branch newly exposes it. FIX: snap a reduce leg up to >= min_qty
   (or fold a sub-min leg into the final full close) and treat a qty<=0 reduce as "close the remainder",
   never retry the same sub-min qty. Add a szDecimals==0 runner-half test.
3. [CROSS-FLAG COUPLING] any-coin degrades bot_manages->profits_only on extra coins; profits_only is a
   RESTRICTED mode, and runner_applies/ladder_applies require a restricted mode -> turning on
   OWNER_LADDER_STYLE/OWNER_RUNNER_STYLE silently makes extra-coin bot_manages plans exit via the
   ladder/runner style while their CORE counterparts don't. Paper-only, mechanically sound, but it makes
   core-vs-extra paper results non-comparable and is hidden coupling. FIX: document the precedence in
   both branch docs; for the paper study, either keep degraded-bot_manages extra-coin plans in 'full'
   style or exclude them from the core-vs-extra comparison.

## C. CROSS-BRANCH (both edit owner_plan_exec._open + position_manager)
No textual conflict in position_manager (different line regions). But _open gets adjacent non-identical
hunks from both, and the mode/style interaction in (B.3) is only live when BOTH flags are on and is
UNTESTED. FIX before both go live: one merge-integration test - open a LADDER-style plan on an EXTRA
coin with both flags on; assert the resulting exit_style, exit_mode, and leg schedule.

Risk-cap asymmetry (extra-coin plans capped, core owner plans still bypass apply_risk_cap) and the
>10%-tick-jump accept-on-next-tick guard: reviewed, acceptable as described; flag the risk-cap
asymmetry only if you want core owner plans capped too (pre-existing, your call).

Net: both are sound paper-execution builds; fix A1+A2-4 and B1+B2+B3 and add the C test, then flip each
flag. No per-token cost concern (CLI quota). Ready to re-review a fixed push at the same bar.
