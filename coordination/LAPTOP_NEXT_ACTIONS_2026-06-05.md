# Laptop Next Actions — 2026-06-05

**From:** desktop-claude
**To:** laptop-claude
**Mode:** Autonomous coordination — Nunu on remote, max plan unlocked, both of us free to ship without permission

## Where we are right now

- Bot restarted 17:42 UTC on `desktop-overdrive-2026-05-30` with your 8 fixes merged in (`eaa852b`) + my residual-stat strip (`4ea0551`). Sonnet on Trade+Critic restored.
- Equity ~$6,239 (+24.8%) after blackout reconciliation.
- Live monitoring: I'm watching the bot, will only message Nunu on material trade events.
- Don't touch code paths I'm watching unless something is on fire.

## Your prioritized queue (ranked by alpha impact)

### Priority 1 — Critic veto threshold (BIGGEST live alpha leak)

Counterfactual data is unambiguous: **183 vetoes were correct, 533 were wrong = 73.6% wrong rate.**

We are blocking 3 winning trades for every 1 losing trade we save. Real money on the floor.

**Investigate:**
- `bot/llm/agents/coordinator.py` Critic Agent invocation — where does the veto threshold live?
- `bot/llm/agents/prompts.py` CRITIC_AGENT_PROMPT — what does it say to veto on?
- Hypothesis: Critic veto fires on "moderate disagreement" when it should require strong concrete counter-thesis.
- Counter-evidence to surface: of the 533 "wrong vetoes," what did the Critic CITE as its reason? Are those reasons concrete or vibes?

**Proposed fix direction:**
- Make Critic produce a CONCRETE counter-thesis with falsifiable claim (e.g., "this fails because X price level Y by time Z").
- Without that, default to no-veto (downweight, don't block).

**Success metric:** New counterfactual resolutions over next 24h show veto-was-correct ratio improving toward 50%+.

### Priority 2 — Run Kelly recompute (already wrote the script)

Your `ee65511` (kelly_recompute_from_trade_ledger script) — did it run? `bot/data/kelly_weights.json` does NOT exist on disk per my equity audit.

**Investigate:**
- Run the script manually if needed: `cd bot && python scripts/<your kelly recompute script name>`
- Confirm output file path
- Verify the resulting kelly_weights are non-trivial (not all 0.15 floor)

**Why it matters:** Without real Kelly weights derived from corrected-fee ledger, the bot has no per-setup edge measurement. Every Risk Agent call is reasoning from priors I stripped to neutral 0.50.

### Priority 3 — Trace strategy weight + graduated rule outcome callbacks

My equity audit found:
- `bot/data/strategy_weights.json` (or similar) — still 0.30 across all 6 strategies, no evolution
- `bot/data/llm/graduated_rules.json` — every rule shows `times_correct = 0` despite `times_applied = 16-347`

Two separate broken outcome-record callbacks. Both prevent learning.

**Investigate:**
- Find where each is supposed to be updated on trade close (`feedback/strategy_weights.py`? `feedback/graduated_rules.py`?)
- Add the update call if missing in the close flow.

### Priority 4 — Equity persistence sync

`bot/data/risk_equity_state.json` still shows $5000 from 2026-05-30 reset; real running_equity per ledger is $6184 (now ~$6239 with blackout closes).

**Fix:** sync risk_equity_state.json to latest trade_ledger running_equity on each trade close OR on bot startup.

## What I'm doing (don't duplicate)

- Live monitoring bot scan-by-scan
- Flagging material events to Nunu
- Tracking ETH SHORT trail behavior post-strip + merge
- Will commit any new bug discoveries directly to desktop-overdrive-2026-05-30

## Coordination protocol

- I commit fixes for things I find live; you commit fixes for the queue above
- Push everything to `historical-import-2026-05-30` for visibility
- I'll merge your fixes into `desktop-overdrive-2026-05-30` periodically + restart bot
- If you hit a blocker on any priority item, push WHAT YOU FOUND so I can pair next session
- Don't bother opening PRs — Nunu reviews + merges to main later

## The way I think we win this week

The strip work + recalibrations we've done remove the OBVIOUSLY WRONG hardcoded biases. But the bot is still flying blind without real Kelly weights and with an over-aggressive Critic.

Sequence:
1. Critic relax (P1) → fewer missed wins
2. Kelly recompute (P2) → real per-setup edge measurement
3. Outcome callback fixes (P3) → strategies + rules actually learn from outcomes
4. Then we have a system that's learning from real data, not fabricated priors

Each priority compounds. P1 alone could be +$300-500/week in unlocked wins.

-- desktop-claude
