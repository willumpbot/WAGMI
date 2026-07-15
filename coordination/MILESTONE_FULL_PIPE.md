# MILESTONE: THE FULL PIPE — every signal now reaches the brain

**2026-07-02 · wave-2b landed (L1+L2+L5 + finisher) · one page for the owner**

## What "full pipe" means

Since the June rebuild, the bot's LLM brain (9-agent coordinator) was nominally in charge —
but a stack of hardcoded routers, confidence gates, and mechanical vetoes sat in front of it,
silently deciding which signals were "worth" an LLM call. The brain judged only the traffic
the plumbing allowed through. That is the silent-gate pattern that kept the bot generating
signals without trading, and it made every learning loop miscalibrated: the ledger recorded
what the *gates* liked, not what the *brain* decided.

As of tonight, **every non-None ensemble signal dispatches to the LLM coordinator.** No
confidence pre-screen, no proven-solo whitelist, no quant pre-veto, no tier router deciding a
signal doesn't deserve judgment. Mechanical opinion still exists — but only as *labeled
context* the brain reads, and as *shadow logs* we can dollar-score later. Every removed gate
kept a kill-switch env var (ROUTER_SOLO_CONF_ENFORCE, TIME_SIZING_ENFORCE, CRITIC_ENFORCE, …)
so any of this is reversible in one restart if the data says the cage was load-bearing.

## Before → after (what actually changed)

| Layer | Before (caged) | After (full pipe) |
|---|---|---|
| Dispatch (L1) | R3: solo signals needed conf≥60 to earn an LLM call; R7: low-conf diverted to mechanical path; _PROVEN_SOLOS whitelist; QB pre-filter vetoed/mutated signals pre-LLM | Every signal → coordinator. Would-have diverts logged as [SHADOW-ROUTER]; mech opinion passed to the brain as labeled context |
| Coordinator (L2) | R12 tier router auto-flatted "low quality" signals with zero LLM calls; failed Critic call enforced a harsher penalty than a successful one; unproven pre-filter rules vetoed silently | Tier router deleted; Critic failure = one retry then loud degraded flag; pre-filter vetoes require §2b provenance (dollar-scored, current-ledger) or they run shadow-only |
| Fallback path (L5) | Time-of-day sizing (0.4x–1.38x) from ONE April week; LLM-first could silently lapse into mechanical trading | Time sizing neutralized to 1.0x with [SHADOW-TIME-SIZE] would-have logging; Gate 0 stand-down: if LLM-first degrades, the bot stops entering instead of quietly trading mechanically (loud alert + heartbeat flag) |
| Honesty | Silent drops (cooldowns, diverts) left no ledger trace | Every drop records a labeled rejection + counterfactual price-track, so the *policy of not trading* is itself dollar-scored |

## Signal flow, measured (same day, same market)

- Old pipe (2026-07-02 06:00→22:25 UTC): **~9 coordinator pipelines/hour** (147 in 16.4h)
- Post-dechoke new pipe (22:25 UTC→): **~280/hour** (123 in first 26 min) — ~**30x** more of the
  bot's own signals actually reaching the brain, with shadow lines ([SHADOW-GATE/QUANT/CRITIC/
  TIME-SIZE/ROUTER]) recording what every removed gate *would have* done
- Post-restart watch (wave-2b code, fresh process): see final section of this doc

Selectivity is unchanged as a *target* (~2 trades/day): the brain still skips most of what it
sees — but now it's the brain skipping, with a written thesis, not a threshold.

## What the A/B answers

The C1–C6 replay campaign (old pipe, six historical weeks: trend-up, dead market, trend-down,
chop, panic, bear-drift) is the baseline: C1 +$16.18, C2 +$0.05, C3 $0.00 (sat out a −13%
downtrend — never shorted), C4 +$0.44, C5 $0.00 (panic, sat out), C6 running now. The A/B
re-runs the SAME weeks, SAME candles (SHA-stamped seed reuse), SAME entry-event filter through
the NEW pipe (C1'–C6'). Pre-registered verdict criteria (FULL_PIPE_BUILD_MAP §4):

1. **More LLM-approved closes at equal-or-better expectancy** — did uncaging add trades without degrading quality?
2. **Zero losing windows preserved** — did the cage's protection survive its removal?
3. **The C3 question**: does the new pipe SHORT the trend-down week the old pipe sat out — and if not, is it the filter starving shorts or the brain declining them (theses on record)?
4. **Guardrail**: chop-week skip-rate must stay highest — if C4' churns, the removed gates were load-bearing and it goes back to the owner before any live change.

**Status**: A/B armed, not yet launched — C6 baseline still consuming the quota window, and
the launch tooling (L6 prime-arm: seed-SHA stamping, 6s sleeps, 3-window parallel driver)
lands next; the engine cron fires C1'–C5' when quota clears. Nothing about the live bot waits
on this: the full pipe is live in paper now, invariants ALL CLEAR, with every old gate still
watching from the shadows and writing down what it would have blocked.
