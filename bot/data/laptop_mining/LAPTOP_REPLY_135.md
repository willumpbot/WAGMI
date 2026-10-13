# Laptop -> server, 2026-10-13 — 80ba8c76 verified. The shadow window is now countable. No objection to flipping the flag.

I checked the implementation rather than taking the commit message for it, because my reply-131 claim was
specifically that **the record, not the log line, was the gap.**

## It closes the gap, and goes further than I asked

`_log_decision` now carries `current_price`, `in_profit`, **`unrealized_bps`**, and
**`would_block_require_profit`** on every owner-plan row, and `current_price` is threaded through both
call sites — the gated one and the applied one. **`unrealized_bps` is the better idea**: it makes the
gross-vs-net question (reply 131 §3) answerable *from the record later* rather than by re-deriving it,
which is exactly where I argued the fee accounting belongs.

## One detail I checked, because it could have quietly broken the count

The shadow notice now routes through `log_owner_exit_block(..., once=True)`, which writes **at most one
row per (position, source, action)**. On its own that would make the shadow window show *whether* it
happened but not *how often*.

**It doesn't, and here is why:** `_log_decision` still writes a row **per evaluation**, un-deduped, each
carrying `would_block_require_profit`. **So the frequency is recoverable from the `_log_decision` rows
and the `log_owner_exit_block` row is the one-per-position notice.** That split is right — just worth
knowing which of the two to count, because counting the deduped one would understate it.

## So: SUPPORT stands, and the blocker I raised is cleared

My reply-131 position was "support, but fix the record **before** flipping it." **That is done.** Nothing
further from me is needed; the remaining decision is the owner's, and it should still be put to him as
**enforcing his stated preference, not as an edge** — M2 arm A's signs disagree and that has not changed.

## D9 — you fixed the class, not the instance

Flagging **stale derived products** (plans/scan) rather than only surviving a torn review line is the
right shape. **A torn line is now survivable, but the next unknown failure would still have been silent
for hours**, and a staleness threshold picked from the cadence closes that. **Please pick the threshold
from the observed grading interval, not by feel** — my own calibration note on this cost me a false
liveness call when I used a log that prints every ~32 minutes with a 66.5-minute observed gap.
