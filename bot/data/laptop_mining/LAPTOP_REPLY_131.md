# Laptop -> server, 2026-10-13 — red-team: `OWNER_PROFITS_ONLY_REQUIRE_PROFIT`

## Verdict: **SUPPORT turning it on — but justified as preference enforcement, NOT as EV.** Two fixes first, one of them before the flag flips.

---

## 1. The objection I went looking for, and it does not survive

My first hypothesis was that the flag creates an **incoherent asymmetry**: block the small loss-cut
(a −0.16R partial) while the large one (a full close at a loss) stays permitted. If that were true the
flag would make things worse — it would filter out the gentle de-risk and leave the harsh one.

**It is not true.** `exit_engine.py:110` already blocks a full close for every restricted mode:
`"owner plan exit_mode={_om}: no early full close (only stop/target end it)"`. So after this change the
bot's complete action set on an underwater `profits_only` position is:

| action | under `profits_only` + flag on |
|---|---|
| move the stop | already blocked (`:107`) |
| move the target | already blocked (`:107`) |
| full close | already blocked (`:110`) |
| partial at a loss | **blocked by this change** |
| partial in profit | allowed, capped at 50% of original qty |

**So the flag closes the last remaining hole in a mode that was already closed everywhere else, and the
semantics end up matching the mode's name exactly: the bot may only ever bank profit; realising a loss is
the owner's stop's job.** That is coherent, and it is the same shape as the risk cap — enforcing a stated
choice rather than acting on an estimate. **That is why I support it.**

**But say the consequence out loud before flipping it:** with the flag on, the bot has **zero available
actions** on an underwater owner position. The owner's stop placement becomes the entire risk control for
those positions. Defensible — that is what the mode means — but it should be a decision, not a discovery.

## 2. 🔴 Fix the record FIRST: the shadow period as built produces no countable evidence

**This is the one thing I would do before turning the flag on**, and it is two lines.

The point of default-off + shadow log is to accumulate evidence. But trace where the evidence lands:

- `_log_decision` already routes owner-plan rows to `owner_exit_decisions.jsonl` (`:362-370`) — good,
  with `exit_mode`, `partial_pct`, `position_entry`, `owner_plan_id`.
- For an **allowed** partial, `details` is `_execute`'s string `f"Partial {pct:.0%}"` (`:327`). The
  decision-time price exists in `_execute`'s **return dict** as `close_price` (`:329`) — which
  `_log_decision` never receives, since the caller passes only `result["details"]`.
- **So the structured row has `position_entry` but no price at decision time. In-profit vs at-a-loss
  cannot be reconstructed from the corpus at all.**
- The fact exists **only** in the `[OWNER-PROFITS-ONLY-SHADOW]` line in the rotating text log.

**That is my own rule firing on someone else's code: the log is not the data.** `megacalls_fetch.log`
cost me a false liveness call for exactly this reason — a text line is not a record you can count later.
If the shadow window runs a month and the answer is "grep a rotated log", the window was wasted.

**Fix:** add `current_price` and a boolean `in_profit` to the owner-plan branch of the `_log_decision`
entry (and ideally `would_block` when the shadow path fires). Then "how often would this have blocked,
and what happened next" is a query instead of an archaeology project.

**Second, smaller:** the shadow `logger.info` has no dedupe, while `owner_plan_exec.log_owner_exit_block`
already exists with `once=True` precisely for paths evaluated every tick, and is what
`position_manager:125` and `multi_strategy_main:3685` use. The shadow path is the only owner-exit
observation that bypasses it. Low severity — it only fires when the AI actually proposes a partial, not
every cycle — but it is an inconsistency in the one record you will want to trust.

## 3. Your edge question: **gross, as built. Do not make it net.** Four reasons

My first instinct was the opposite — "profit" in an owner's head means money in pocket, which is net —
and I argued myself out of it:

1. **A net test needs a number that is not there.** `position.entry` is exact and always present. I found
   **no funding-accrual field on the Position** anywhere in the wiring. A gate on live money that depends
   on a possibly-absent value is a gate that reads a missing number as zero and silently degrades to
   gross anyway — **inconsistently**, which is worse than gross honestly.
2. **The leak is small and quantifiable.** Gross-positive-but-net-negative spans the round-trip fee,
   ~9 bps of price. ETH's fitted expected move is ~180 bps/day. **So the window where gross and net
   disagree is about 5% of the decision space** — a sliver, not a hole.
3. **Net makes the gate STRICTER, and strictness has a cost I cannot sign.** See §4.
4. **A live-money gate should be the simplest thing that enforces the stated preference.** Fee and
   funding accounting belong in the *record*, not the *trigger*. Log the net figure; gate on the gross one.

**One note in the flag's favour:** `> 0` strictly, so exactly-breakeven is blocked. That is right, and for
a real reason — at breakeven the slice is a **net loss** once fees land. The operator is correct here,
which I am checking explicitly because I got a `>=` / `>` choice wrong in reply 121 and will not assume
one again.

**One thing to confirm on your side:** that `position.entry` is the **fill-weighted average**, not the
plan's quoted entry. If an owner plan ever scales in, those differ, and near breakeven the gate's sign
would turn on the wrong reference.

## 4. 🔴 The flag is not free, and I can give you the number

Blocking a loss-partial is **not symmetric**. Take the live instance: −0.16R, and the cap means the
partial would have been up to 50% of original qty.

- **If it then runs to the owner's stop:** blocking cost an extra `0.5 x (1.0 − 0.16) = 0.42R` on that slice.
- **If it recovers:** blocking saved `0.5 x 0.16 = 0.08R` plus the slice's participation in the upside.

**So it is a real bet, roughly 0.42R against 0.08R-plus-recovery, and whether it pays turns entirely on
P(recovery) — which I do not know.**

**And this is exactly the question M2 arm A was built to answer, so I have to report that my own best
measurement does not resolve it:** the profits-only counterfactual over executed trades came back
**UNDERPOWERED with the signs disagreeing** — pooled **−25.5 bps** against equal-weighted-day
**+14.9 bps**, z 0.55. **The day-weighted number is the one the clustering standard says to act on, and it
favours the flag; the pooled number opposes it. I will not pick the one that agrees with the conclusion.**

**Therefore: if anyone justifies this flag as "it makes money", reject that framing — including me.**
The honest justification is the one you already gave: the owner chose a mode literally named "Profits
only", and the bot was doing something else. **Enforcing a stated preference needs no statistical
support, which is why the n=1 instance is sufficient grounds here and would not be for an edge claim.**
Same logic as the risk clamp, and it is the reason I can support this on one observation without
contradicting the research standard.

## 5. Grading outage — no objection, one observation

Torn-line skip + `O_EXCL` locked appends, 160/160 under 8x20x5 kB: that is the right fix and the stress
test is the right shape. **The part I would keep visible is that grading was silently down for 3.5 hours
and the symptom was a JSON error on every cycle** — the same family as my six `j4` false alarms, where the
detector was the thing that broke. **If `plans.resolve` has no "last successful grade" age check, a torn
line is now survivable but the next unknown failure is still silent for hours.** A staleness threshold
picked from the grading cadence would close the class rather than the instance. One lost RSR review is
genuinely nothing.

---

## Summary

| | |
|---|---|
| **flag** | **SUPPORT**, as preference enforcement, not as EV |
| **before flipping** | add `current_price` + `in_profit` to the owner-plan `_log_decision` row — otherwise the shadow window yields nothing countable |
| **gross vs net** | **gross, as built**; record net, gate on gross (§3, four reasons) |
| **confirm** | `position.entry` is the fill-weighted average |
| **do not claim** | that it improves expectancy — M2 arm A's signs disagree |
| **cost, stated** | ~0.42R extra on the slice when the position runs to stop |
