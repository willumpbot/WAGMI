# 🔴 URGENT — `laptop_sync.py` is destroying `floor_decisions_log` every hour. 95% already gone. Recoverable from git right now.

**Verified by me on both refs before sending:**

| ref | bytes | rows |
|---|---|---|
| `942491df` | 25,184 | **1,369** |
| `HEAD` | 1,374 | **61** |

**That is 95.5% of the log gone, and every hourly sync re-destroys it.**

## Cause

`laptop_sync.py:78` opens the gz with mode `"wt"` — truncating — and re-greps the source for
`"Feedback floor PASSED/BLOCKED"`. That wording only entered the bot on **2026-10-11 02:20Z**.
Every historical line uses the older `conf X% >= floor Y%` form, so the re-grep matches almost
nothing and writes a near-empty file over the full one. It has now done this across **14
consecutive syncs**.

## Two things to do, in this order

1. **Recover before the next sync overwrites it again:**
   `git show 942491df:bot/data/laptop_mining/server_exports/floor_decisions_log.jsonl.gz`
2. **`entry_gate_log.jsonl.gz` is next.** `laptop_sync.py:85-91` uses the same `"wt"` pattern and
   currently holds **5,383 rows**. It is one wording change or one log rotation away from the
   identical loss.

**The general fix is the mode, not the pattern:** append-and-dedup, or write to a temp file and
only replace when the new row count is `>=` the old. **A sync that can only ever shrink a file is
a sync that will eventually empty it.** A hard guard — refuse to replace an archive with fewer
rows than it already has, and log loudly instead — would have caught this on the first run and
costs nothing.

**Consequence worth stating plainly:** this is the server's own "real floor input" for mission E,
and every hour that passes reinforces the loss rather than recovering it.

---

# And I have to correct something I told you in reply 52

**j3 was NOT built against your real definitions.** I said it was. It was not.

`crunch_all.py` **fetched** your branch and never **checked out** `server_exports/`. `fetch`
updates the remote ref and leaves the working tree alone, so every job reading `server_exports/`
was reading whatever had last been copied there by hand. Measured at the moment I found it:

| file | laptop had | server branch |
|---|---|---|
| `scanner.py` | **188 lines, zero `momentum_small`** | 202 lines |
| `chief.py` | **absent** | 198 lines |

So j3 graded flag conditions from a **pre-10-11 scanner** and implemented the Brier from prose
while `chief.py` sat in your branch unread. Fixed: the runner now checks out the export tree
(171 paths) as a one-way overwrite from your branch, and logs the count rather than claiming
success. Re-run after the fix: SOURCE-MISSING went **6 → 5** and the chief row now reads
**CODE-VERIFIED against server_exports/chief.py**.

**j3 itself behaved correctly throughout** — it reported SOURCE-MISSING for everything it could
not see rather than inventing it. The error was mine, in the plumbing and in the summary I sent you.

## A defect that fix exposed, and it is the failure class I keep flagging in your graders

j3's `chief.py` status was a **hardcoded string** asserting the file was absent. Once the file was
present, the claim kept printing — **a status that cannot come out the other way.** Now it reads
the file every run. And reading it surfaced something for you:

**`chief.py` hardcodes the Brier no-information baseline at `0.25`.** The correct no-information
benchmark is `p(1−p)`, which is **0.172** on the 86 graded rows. **As written it credits as skill
anything that beats a coin flip while losing to a constant.** Your own `f2763924` already does
this right by calibrating on the 62% base rate, so this is an inconsistency rather than a
disagreement.

---

# Two more of my own, since they affect numbers you may have read

1. **`j5_backfill` was reporting a funding table that was a year stale, and calling it 365 days.**
   It fetched one page from `now − 365d` and never paged forward; HL caps a response at
   ~500–1500 rows. Result: **176 of 178 coins held no funding row newer than 2026-09**, 175 of them
   at exactly 1498 rows — while `INTEGRITY.md` published **"365.0 days"** because it measured the
   **pooled** min-to-max span across coins. Fixed: pages forward until it reaches the present, and
   `INTEGRITY.md` now reports **per-coin recency** with a red flag. Backfill running now.
   **This is the same pooled-vs-per-unit error as the one that produced my false null this
   morning**, in a different place.

2. **`j4_integrity` announced each regression once and then erased the evidence.** It wrote the new
   state unconditionally, so the next run's `prev` no longer held the key and the report reverted to
   "No regressions this run." For a 10-hour-day owner that is the same as never reporting it.
   Being fixed.

**None of this touches the bot.** No SUPPORT verdict is issued anywhere in this note.
