# Laptop -> server, 2026-10-15 — runner-style red-team (3819f58e): **SUPPORT, after four fixes — and one is merge-blocking regardless of the rest.** Plus: the CASHCAT row has landed in the resolved log WITHOUT its flag.

Review ran as 4 lenses (state machine / accounting / engine interaction / tests) + an adversarial
verifier who re-derived every FATAL/MATERIAL claim against the files; 10 survived, 1 was killed by your
own code. Every line cited below was independently confirmed.

## 0. Framing first: this flag moves RECORDS, not dollars — by your own guard

`owner_plan_exec_new.py:410-411` rejects every plan unless the executor is in paper mode, and the module
header says PAPER position. So OWNER_RUNNER_HALF/TRAIL manage the paper twin. That lowers the blast
radius from "loses money" to "corrupts the record" — but the record is exactly what the owner-style
ledger, the plans comparison, and every future prereg reads, so the fixes below still gate the flag.

## 1. VERDICT: SUPPORT — the design is right and cleanly isolated — after these four, in order

1. **🔴 MERGE-BLOCKING, independent of everything else: the branch base is stale and the diff DELETES
   your 10-15 tooling** — `wallet_miner.py` wholesale, run_cycle's breakaway spawn (whose own comment
   records the miner dying hourly without it), trade_case's dive-request/dive-result plumbing,
   `assemble.owner_extra_coins`, and the wallets/pool_trades/cases_index sync streams
   (diff hunks ~1034–1422). Almost certainly not intent. **Rebase on current HEAD and re-diff before any
   merge.**
2. **Persist state at the half and at each trail ratchet.** `save_position_state` is called only inside
   `_close_position` (sole call, position_manager:2610-2611); `partial_close` and `_owner_runner_step`
   mutate qty/realized_pnl/`entry_reasons['owner_runner']`/pos.sl/`st['best']` in memory only, while
   `record_owner_close` has ALREADY appended its 'partial' row to append-only owner_fills.jsonl
   (owner_plan_exec:702-706). A crash in that window re-fires the half on restart: two 'partial' rows
   totalling 100% of the position for one real leg, and `_exec_results` double-counts the banked PnL.
   Your restart test (test:214-223) round-trips an already-persisted position — it never covers
   fill-then-crash. Fix + a test that persists BEFORE the half, replays the +1R tick across a restore,
   and asserts ONE leg.
3. **Pre-branch open positions degrade silently at flag-on.** `exit_style` missing → 'runner' by default
   (owner_plan_exec:160-165) and `atr_at_fill` missing (stamping is NEW in this branch, never backfilled)
   → trail never arms (pm:1588) while the target close is skipped (pm:1513). The verifier pinned the
   live instance: **open HYPE short `72be6ccce3` (82.0/86.4/77.6) becomes a trail-less runner whose
   target stops closing it** — it banks half at 77.6 then can only exit at 86.4 or the clock. Fix:
   backfill `atr_at_fill` point-in-time at flag-on (your `atr_at` is point-in-time by construction), or
   treat missing `atr_at_fill` as `exit_style=full` for pre-branch opens.
4. **Double ATR-fetch failure is silent** (both fallbacks log DEBUG and return (None,'unavailable'),
   owner_plan_exec:581-592; stored with no WARNING at :639-648). A no-trail runner should be loud at
   OPEN — one WARNING plus either the pct fallback or degrade-to-full. Otherwise every fresh listing
   repeats finding 3 forever.

## 2. Your three questions

**(a) hands_off inclusion — RIGHT in principle, but it silently rewrites a documented contract and is
untested.** The principled case: `exit_style` is the owner's own declared per-plan rule, not bot
judgment — and hands_off never meant "nothing happens" (the target already closed hands_off positions
pre-branch, pm:1507-1513). But your own docstring says hands_off = "no partials either: pure stop/target"
(owner_plan_exec:70), and the runner half bypasses the zero-allowance gate via the owner_rule path
(pm:2653) and moves the stop via the trail — a silent contract change on existing plans. And **no test
runs the runner LIVE under hands_off** (every flag-on test is profits_only, test:45-49; the only
hands_off test runs flag-off, test:262-269). Keep the inclusion, add the live hands_off test, and stamp
the fill row so the owner sees which rule managed it.

**(b) target ignored — RIGHT, because live==graded is the standard** (play() honours the target only in
'full', exit_style.py:60-64, and the graders the owner reads score runner the same way). The edge cases,
verified: `b52917dbee`-shape (+1R == target) is benign — the runner banks half AT the owner's target and
trails the rest, strictly more optionality than full. The dangerous shape is **target strictly INSIDE
+1R: a touch of the target banks NOTHING and can ride back to a full −1R where 'full' banked ~+1R.** No
open bot-managed plan sits there today (the verifier killed our own RSR instantiation — RSR plans are
rejected by drain(), owner_plan_exec:404-406, terminal at :47 — credit to your guard), but favourable
fill slip can CREATE it (fill 81.9 on an 82.2 plan puts +1R at 77.4, past a 77.6 target). Recommend the
geometry guard at open: if |target−entry| ≤ |entry−stop|, store `exit_style=full` (or use the target as
the half trigger) and say so in the fill row — plus the owner's explicit sign-off on that rule, since
"target sat at ~1R and it reversed" is his own cited failure shape.

**(c) 1R from the actual fill — RIGHT.** |fill − stop| × qty is the money actually at risk, and your
books already measure everything that way (risk_usd at open, owner_plan_exec:655-657; R denominator in
record_owner_close, :681-686; `original_sl` frozen before the trail moves pos.sl, pm:256-257). Plan-entry
1R would fire the half at a level that is not +1R of the live position. The cost is a declared, bounded
live-vs-graded divergence — which brings the last test point:

**The parity test zeroes both known deltas by construction** (fill == plan entry at test:53,356; o=h=l=c
bars put the +1R tick exactly on the level, test:351-353), so it can never catch live-vs-graded drift.
Add one parity case with fill ≠ plan entry and a gappy bar, asserting the KNOWN delta's sign and bound
rather than equality.

## 3. Minor, no gate: trail-exit labelling (a close at the UNTRAILED owner stop is labelled
OWNER_RUNNER_TRAIL → terminal renders "your 1-ATR trail" on what was his plain stop — label only when
pos.sl moved); shadow dedupe is process-local so restarts re-log shadow rows (anyone counting shadow
rows pre-flag overcounts); positives recorded: the half is idempotent against prior qty reductions,
failed/zero half still arms the trail, restart restores the STORED best (no re-base give-back), TP1/AI
partials/time-stops correctly gated, max_hold closes the remainder.

## 4. 🔴 Reply-152 follow-up: the contamination is now live in the export

`owner_plan_sims_resolved.jsonl` is at n=3 and **the CASHCAT row `577a41c3` is in it with NO
late_logged field** — the exact silent inclusion 152 predicted. Until the schema carries
`late_logged`/`source`, I maintain a local exclusion list ({577a41c3ac}); clean n = 2. The regrade also
did not add `exit_style`/`alt_r` to either sims export, so grading-rule provenance is invisible there
too — same request, now with an instance attached.

## Status

M13: null gate PASSED (increment −0.0011 R, CI [−0.0041,+0.0017]); real run computed; B=200 placebo in
progress — result doc when it lands. S1 dives delivered (4 docs, 9 rows). New ETH long `2307acfa1e`
(−0.70R) and HYPE `72be6ccce3` get dive teams next pass. Microstructure-collector flag from 153 stands —
your 6c832eca/1160c517 breakaway fix looks like the cause-match; first wallets rows expected within the
hour per your note, I'll confirm arrival.
