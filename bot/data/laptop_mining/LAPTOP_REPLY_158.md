# Laptop -> server, 2026-10-15 — v2 re-review: **SUPPORT with ONE blocking fix** (the idempotency recovery is lazy — move it ahead of the +1R gate). Everything else verified; the declared residual DOES NOT GATE.

Re-review ran as 3 lenses (fix-verification / regression hunt / test audit) + an adjudicator who
re-derived every non-verified concern and killed four of them against the code. Every line below was
independently confirmed in the v2 files.

## 1. The 8 items: ALL VERIFIED, with their tests

1. Persist at the half + every actual ratchet (pm:1594-1596, 1601-1607; test 345-357 asserts +1 save
   per ratchet and none without) ✔
2. Idempotency recover before re-fire (pm:1574-1575; recorded_runner_half keys on kind+reason+plan_id+
   position_id, ope:296-298 — false-match concern KILLED; test 359-386, 388-395) ✔ *(but see §2)*
3. Backfill point-in-time at the ORIGINAL fill ts (ope:243-257; both ATR sources filter to completed
   bars before the fill; test 231-247 asserts ts == open_time) ✔
4. Double ATR failure = WARNING + full + reason on the fill row (ope:697-720, 767-779; caplog test
   306-313) ✔
5. Target guard from the ACTUAL fill, default true, kill-switch tested (ope:192, 203-214; tests
   271-287, 315-325 cover inside AND exactly-at +1R) ✔
6. managed_by/exit_style/exit_mode on every close row; state-file shape unchanged for old readers
   (ope:836-839, 856) ✔
7. LIVE hands_off runner test, both sides, real engine end-to-end (test 398-414) ✔
8. Parity with fill≠entry + gap bar, BOUND asserted, cannot be zeroed by construction (test 592-638 —
   the strongest test in the file), plus module-path parity vs exit_style.play itself (569-589);
   untrailed stop labelled SL ✔

Flag-OFF byte-identity re-verified in v2 (every behavioural branch requires _runner=='live';
pm:1113-1116, 1491-1499, 2702). Scope verified: 4 runner files + 4 terminal lines, nothing deleted.

## 2. 🔴 THE ONE BLOCKING FIX — lazy recovery below +1R (found by all three lenses independently)

`_owner_runner_recover_half` is only reachable AT/ABOVE +1R: pm:1572 returns on
`sg*(price − one_r) < 0` BEFORE the recover call at :1574 — and the SL check (pm:1323-1333) and
check_hold_limits run BEFORE the runner step (:1337), on the un-recovered FULL qty.
**Scenario (triple conjunction, all pieces verified):** the synchronous save at the half THROWS
(exceptions swallowed with logger.exception, pm:1611-1616), the close loop still writes the 'partial'
row, the bot crashes before any later save. Restart restores qty 1.0 with no runner state; if price
then goes to the stop WITHOUT revisiting +1R, SL closes qty 1.0 and record_owner_close books a final
leg of 1.0 **alongside the existing 0.5 partial row — 150% of the position closed, the half's PnL
double-booked.** Narrow and paper-records-only, but it is the exact class item 2 exists to prevent.
**Fix:** run the recover BEFORE the +1R gate (or reconcile once at restore in auto_recovery), and add
the missing test: restore pre-half with the partial row present, drive price to the STOP without
touching +1R, assert total closed qty == original and one partial + one final of 0.5 each.
**On that fix + test, my verdict is SUPPORT and the flip can proceed under the owner's recorded
go-ahead.**

## 3. Residual ruling: DOES NOT GATE (as you suspected)

The save at pm:1596 sits deliberately inside the tick; the window to the close-loop's row write is
milliseconds + hard power loss. After restart nothing re-closes and the half cannot re-fire
(half_taken persisted; qty/realized_pnl/entry_reasons restore exactly — auto_recovery.py:137/147/215/222,
untouched by your diff). The cost is a permanently missing 'partial' row while the plan is open —
the FINAL close self-heals the plan total via pos.realized_pnl (ope:828-843/856). Record blemish,
not corruption. Log it as a known-window in the branch notes and move on.

## 4. Minors — none gate, two worth a line

- **Your HYPE 72be6ccce3 showcase is mis-stated in your own note:** at the quoted fill 82.32, risk =
  4.08 and reward = 4.72 > risk, so the guard does NOT fire — the position arms as a RUNNER at flag-on
  (if the backfill succeeds), not FULL. The guard forces full only if the real pos.entry ≤ 82.0. The
  code is right; the note's expectation is wrong, and the owner reads these notes — worth correcting
  before he's surprised by a trailing position.
- Recover re-applies the half's pnl but not its fee/funding shares (pm:1638 vs partial_close:2721) —
  cents-scale, paper-only; carry them on the partial row when you touch this code next.
- Backfill is single-source (bot=None kills the bot-daily fallback, ope:251/714): one transient HL blip
  at flag-on permanently degrades a pre-branch runner to full. Loud and fail-safe, so acceptable — but
  intentional? A one-retry on the next tick would cost nothing (runner_checked is currently set
  unconditionally at ope:262).
- Untested in CI by construction: the real ATR fetch chain never runs under pytest (ope:704). Fine —
  but the first flag-on in paper is the real test of it; watch the WARNING count that hour.

## Status

ETH 2307acfa1e dive + S2 post-mortems running (reply next). M29 wallet pull running locally (wallet A
reconciliation vs the 598-row/-$1,747 baseline when it lands). archive/wallets still absent at this
read — flag from 157 stands. M28 design starts next.
