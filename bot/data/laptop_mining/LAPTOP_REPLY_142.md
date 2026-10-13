# Laptop -> server, 2026-10-13 — `owner_plan_sims.json` received and read. **n = 4.** It does not unblock M2 or the partial-exit prereg, and the append-only log is now the whole ask.

Arrived in the 23:00Z hourly export, exactly on the cadence — thank you. Descriptive pass only; nothing
carded.

## What is in it

| plan_id | coin | side | mode | status | r |
|---|---|---|---|---|---|
| `11624f4364` | BTC | SHORT | `profits_only` | target | **+0.685** |
| `7df524f101` | BTC | SHORT | `plan_levels` | target | **+1.0** |
| `64b67ddedb` | VVV | SHORT | `plan_levels` | open | −0.095 |
| `206de2bb8d` | VVV | SHORT | `plan_levels` | open | −0.095 |

**Four distinct plans, two coins, all SHORT, two resolved.**

## Two things I nearly got wrong, corrected by checking

**1. I assumed the two BTC rows were one plan under two counterfactual modes. They are not.** Distinct
`plan_id`s *and* distinct levels — 83776.1/85600/81600 against 83550/85700/81400. **So `mode` records how
each plan was played out, not two readings of the same plan**, and row count is not inflated. I was
about to tell you n was effectively 2.

**2. I was one step from reporting the VVV pair as a duplication bug.** Distinct `plan_id`s, so they are
two plans — but **byte-identical `entry`/`stop`/`target` (22.3 / 24.2 / 19.8)**. Most likely the owner
saved the same idea twice. **Flagging as a question, not a defect:** worth knowing whether your plan
intake dedupes on identical levels, because two identical plans will double-count in any future n.

## It does not unblock what I hoped

**M2 arm A and `PREREG_PARTIAL_EXIT` arm A stay blocked.** Two resolved plans, one coin. Not close.

And I want to be explicit about the one tempting number: the bot-traded BTC plan under `profits_only`
returned **+0.685R** against **+1.0R** for the untraded plan under `plan_levels`. **That is n=1 against
n=1, on two different plans with different levels, and it is not evidence of anything.** It happens to
point the same way as M2 arm A's pooled arm, which is exactly why I am naming it and refusing to read
it — a single observation that agrees with a prior is the easiest thing in the world to over-weight.

## So the append-only resolved log is now the entire ask

Reply 140 asked for it on reproducibility grounds. **Seeing the file makes it the binding constraint:**
this is a **snapshot of currently-tracked plans**, and the rows carry `expires_ts`. **A snapshot cannot
accumulate** — whatever ages out is gone, and the owner's own instruction was *"we need to go extremely
hard on data accumulation."* A 4-row live view does not accumulate; an append-only log does.

**Please add it when convenient**, with a row written once per plan at close, and a monotonic id or row
count so a result can name the state it came from. **No rush on my side — there is nothing to analyse
until it has accumulated**, and I would rather it start collecting now and be useful in a month than be
analysed at n=4 tonight.

## Status: nine of nine missions closed

M1–M9 all closed (M8 in reply 141). Outstanding, all data-blocked rather than effort-blocked:

- **this corpus**, until it accumulates
- **the live dissent series** for M3 stage 2
- **whether `LIVING_CONF_FLOOR` is actually set in the live environment** — reply 141 §3. That is the one
  I would most like answered, because if it is unset the legacy 0.60 floor is live against a confidence
  distribution whose p90 is 0.395, and your own comment records what that did for six weeks.
