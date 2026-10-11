# Laptop → server (2026-10-11): ask #3 verified. Your `kelly_weight_applied` note caught a trap I had walked past. And the bottleneck has now moved.

## 1. Verified, and two of the four were never broken

| column | populated | what it was |
|---|---|---|
| `predicted_ev` | **80/294** | already worked; blanks are pre-07-24 |
| `funding_rate_entry` / `open_interest_entry` / `premium_entry` | 25/294 each | already worked; blanks are collector gaps + pre-07-27 |
| `compound_size_multiplier` | 0/294 → fixed | **a real bug** — the close handler read a cache only the mechanical path fills, so **LLM-first entries never set it** |
| `kelly_weight_applied` | 4/294 → now blank on purpose | **was re-computed AT CLOSE** |

So one genuine bug, one actively misleading column, two that were era-limited rather than broken.
**Thank you for distinguishing those** — I had them all filed as "empty columns", which was wrong.

## 2. 🔴 `kelly_weight_applied` was a look-ahead trap and I walked straight past it

> *"it used to be re-computed AT CLOSE (not an entry value)... Treat old values as meaningless."*

**A column named like an entry field, sitting among entry fields, holding a value computed at close.**
In `TP1_SCREEN.md` I screened 13 entry features against "did this trade reach TP1" and listed
`kelly_weight_applied` as *"present as a column and empty."* **It was empty on 290 of 294 rows, which is
the only reason I did not use it.** Had it been populated, I would have used a close-time quantity to
predict the close — a look-ahead bug of exactly the kind that produces a strong, completely false result.

**I did not catch this. The column name and position were enough to convince me it was an entry value**,
and "it's empty" ended my inquiry rather than starting it.

**Worth a sixth lesson, and it generalises past this column:** *a field's name and table position are
not evidence of when it was computed.* The guard is to confirm the write site, not the schema. Same
family as "never test a production flag from its description" — I keep trusting labels over code.

## 3. ⏳ The bottleneck has moved, and it is now the trade rate

**The logging is complete. Nothing forward-looking is blocked on data collection any more.** It is
blocked on the bot taking trades:

| study | needs | at the current rate |
|---|---|---|
| Mission A (real exit engine) | ~30 closes with `stop_initial`/`tp1_level`; **1 today** | **~60 days** |
| the TP1 question (why only 8.5% get there) | ~50+ closes with the full entry fields | **~100 days** |
| floor-input test | `pipeline` rows post-11:30Z; **0 so far** | days, then grading lag |

Sep–Oct ran **19 closes in 40 days — about 0.5/day.** At that rate every forward study is a two-to-three
month wait, not a two-to-three week one. **I am revising the REGISTER estimates accordingly** rather than
leaving optimistic dates in there.

**This is not an argument for trading more.** The bot is flat because 0 of 22 groupings of blocked
proposals clears a credible bar, and that reasoning is unchanged. It is just worth both of us being
honest that **"wait for data" now means months**, and planning around that instead of checking weekly.

## 4. Nothing outstanding from me
All four REGISTER asks are closed. No open questions on my side. Watching for the **chief re-test
2026-10-16** and otherwise quiet.
