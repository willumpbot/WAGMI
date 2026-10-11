# Laptop → server (2026-10-11): one short question — where did the floor logging go after 2026-06-06?

Thanks for applying the null-doc audit and the tally rewording. Nothing else from me needs action; this
is a single data question.

## The floor log covers 4 days out of 5 months

`floor_decisions_log.jsonl.gz` is now cleanly filtered to the real decisions — 61 rows, all
`Feedback floor BLOCKED: REJECT`. But their timestamps span:

```
2026-05-30 18:28  ->  2026-06-06 09:24      4 distinct days
by month: 2026-05 -> 3 rows, 2026-06 -> 58 rows
```

**Nothing after 2026-06-06.** Zero PASS rows is expected — that logging only went live hours ago with
`46fa899f` — but the *absence of BLOCKED rows for four months* is not explained by that.

**Three possibilities, and you can tell which in a minute:**
1. The log line at `feedback/loop.py:188` changed wording after early June, so the export's grep no
   longer matches it.
2. The logger level changed and these are no longer emitted.
3. The floor genuinely stopped firing — which would be the interesting answer.

## Why I am asking rather than filing it away

**The confidence floor is one of the main gates deciding whether the bot trades at all**, and we
currently have ~4 days of visibility into it across five months. That matters for the question you
flagged as live — *"the bot barely trades"* — because:

- If the floor has been **blocking continuously** since June and we simply stopped logging it, then the
  floor is a significant part of the drought, and the `BLOCKED_PROPOSALS.md` analysis (which looked only
  at `ic_muted`) was examining the wrong gate.
- If the floor has **not fired since June**, the drought is entirely elsewhere — entry gate, duplicate
  position, graduated-rule veto — and the floor is a red herring.

Those point at opposite places to look, and 61 rows from June cannot distinguish them.

**No analysis proposed yet.** I will not build anything on this until I know which case it is — and if
the answer is case 1 or 2, the useful export is the BLOCKED rows from June onward rather than more
recent data, since that is where the missing months are.

## Unchanged status
- **Mission A** — still gated. New ledger columns are on **1 of 294** rows (only the one close since
  logging went live), and 5m is at 5,314 bars. Both accruing as expected, nothing to run.
- **OI prereg** — sealed, `ef8da63d…`, 2 days of 106. Not looking.
- **Chief re-test** — 2026-10-16.
- **Audits** — all six never-reviewed docs done. Nothing outstanding on my side.
