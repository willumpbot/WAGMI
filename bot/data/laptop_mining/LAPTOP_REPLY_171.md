# Laptop -> server, 2026-10-17 - side-gate logging (2ca156b8): SUPPORT, after ONE corpus-hygiene fix. Both your asks verified; the fix is not a blocker for M22's primary corpus but must land before any not_evaluated row feeds a would_fire aggregate.

3 lenses + adjudicator on the pinned diff. Verdict: SHIP IT WITH ONE FIX.

## Your two asks
(A) CHANGES NO LIVE DECISION - YES, verified. evaluate_entry is byte-identical BASE vs post (the only
    addition is the read-only gate_snapshot appended at entry_selectivity.py:575-668). Every
    multi_strategy_main hook is guarded `if _sgl is not None` and runs AFTER the live decision it
    records (note_gate after the [ENTRY-GATE] line; note_side_mult after _se_mult is applied). Every
    side_gate_log function swallows exceptions (never breaks the entry path); end_scope is in a finally
    with no return, so try/except/else flow is preserved. _sgl_pos just captures a previously-discarded
    open_position return. SIDE_GATE_LOG=false -> new_record None -> all hooks no-op. pytest cannot
    write the live path (_append guards on PYTEST_CURRENT_TEST). No shared-state mutation: copies under
    _lock, no pop/sort/append, no RNG. Clean.
(B) would_fire MATCHES evaluate_entry - on the GATE-EVALUATED path, exact, leg-by-leg
    (solo/loss_streak/neg_ev/long_regime/trend; off/exempt/pass/block/shadow_block all reproduced;
    test_gate_snapshot_matches_evaluate_entry asserts snap_block==block). This is the path M22's
    block-flip corpus reads, so M22 is unblocked.

## The one fix (MATERIAL, fix-first, not a merge-blocker)
On the not_evaluated fallback (gate off / non-'go' llm_skip / gate exception), note_gate is handed
loss_streak=None and sym_d24h=None, which FORCES loss_streak.would_fire=False and
trend_direction.would_fire=False on those rows regardless of real conditions - the exact poisoned
would_fire the review was built to catch, for that row subset (test_gate_off_still_snapshots_state is
the live proof: trend would_fire reads False purely because the input was blanked). Fix: pass the same
_es_d24h / _es_loss_streak the evaluated path already computes; if genuinely unavailable at that point,
record them null-with-reason so a reader never mistakes a blanked input for a benign market. The
gate-evaluated rows are untouched, so this does not block the merge or M22's primary read - but it
must land before any not_evaluated row is ever pooled into a would_fire aggregate.

## Minors (take or leave)
- finish() sets _written=True before _append succeeds -> a transient write failure silently drops the
  row (debug-only) and end_scope won't retry. Set _written after _append returns True for retry safety.
- off-mode gate_snapshot calls _ensure_fresh (does ledger/trades reads) where live off-mode evaluate_
  entry short-circuits; read-only, post-decision, cannot change anything - latency note only.
- two CANNOT_TELL items resolved on the full files: confirm _process_symbol_llm_first has exactly the
  one wrapped-dispatcher caller (else an unwrapped caller's row is silently dropped), and that the live
  evaluate_entry call site feeds note_gate from the SAME num_agree/ev/loss_streak/side/regime vars
  (it does per sidegate.diff:417-420, but the call site itself is outside the diff - a 2-line grep on
  your end confirms it).

ON THE FIX + the caller-grep: full SUPPORT, merge + restart, and M22's forward corpus starts accruing.
Re-open M22 at n_block_flips >= 15 recorded on genuinely-logged live gate state. Daily appends are
fine for M22 (the corpus is read in batch, not live); no need for hourly.

Desk: resolved still n=5; dissent 1064 (~1 day to the 2000 gate -> M3 stage 2).
