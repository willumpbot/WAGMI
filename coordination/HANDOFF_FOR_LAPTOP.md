# Handoff Brief for laptop-claude -- 2026-05-31 18:10 UTC

**From:** desktop-claude (after 9+ hours overnight monitoring)
**To:** laptop-claude
**Authorized by:** Nunu (specifically asked me to develop this brief before sending you to work)

This brief gives you the **specific items to investigate and fix today**, in priority order. Nunu's directive: **"truly working extremely hard and covering all bases today"** and **"feel like we have been a little lackluster on the data."**

---

## Context you have / context you need

You have:
- `coordination/MORNING_BRIEFING.md` -- the full overnight write-up
- `coordination/handshake.md` -- everything we coordinated on
- Your own Pilot 3 v2 results in `analysis/historical/layer2-pilot3-v2-results.md`

What I added since your last push:
- `4b2d4de` on `desktop-overdrive-2026-05-30`: **sizing math bug fixed**. Removed the `* leverage` multiplier on qty in `coordinator.py:1484`. The 14:58 GO would have been 0.24 BTC ($17.7k notional) instead of 0.74 BTC ($163k notional). Not yet live -- bot is still on previous code.

---

## Priority items (Nunu's direct asks)

### Item 1 -- **Bug #16: look-ahead bias in backtest agent snapshots**

You found this in Pilot 3 v2: agents cited live trading stats post-April-28 ("BTC LONG WR=19% n=16 hard-block") while running on April 23-28 data. The `_is_backtest` flag blocks `self_performance` injection but NOT graduated rules / quant intelligence injection.

**Investigation paths:**
1. `bot/llm/agents/comprehensive_snapshot.py` -- find where `_AGENT_SHADOW_EDGES`, `_load_recent_skip_stats()`, `_build_graduated_rules_context()` get injected. Are any gated by `is_backtest`?
2. `bot/llm/agents/coordinator.py` -- `get_entry_decision()` and `_build_entry_snapshot()`. Search for `is_backtest` and verify all data sources from the present are gated.
3. `bot/data/llm/graduated_rules.json` -- the actual file the agents read. Has timestamps on each rule. Could be filtered to "rules learned before backtest cutoff date."
4. `bot/llm/quant_brain.py` -- the "quant intelligence" you cited. Where does it pull stats from? Does it have a date filter?

**Fix pattern:**
- Add `as_of_date` parameter to snapshot builders. Filter `graduated_rules` to those with `created_at <= as_of_date`.
- Filter `shadow_edges` similarly.
- Filter `quant_brain` stats to trades closed before `as_of_date`.
- Default `as_of_date = now()` for live bot; explicit cutoff for backtest.

**Test plan:** re-run a tiny window (3 days of April 25-27) with strict cutoff, verify agents do NOT cite stats with post-cutoff trade counts.

---

### Item 2 -- **CLI model routing audit (Nunu: "see where our cli llms systems are and how useful they are")**

Tonight's 265 agent decisions broke down:
- **Opus: 204 (77%)**  -- the quota killer
- Haiku: 47 (18%)
- Sonnet: 14 (5%)

Hit two quota exhaustion windows: 09:42-13:02 UTC (3h 20m dead) and 15:54-18:00 UTC (2h 06m dead). Net: bot only had **~30 min productive operation per quota window**, then 2-3h dead.

**Per CLAUDE.md spec:**
- Regime should be Haiku
- Critic should be Sonnet
- Risk/Learning/Exit should be Haiku
- Only Opus on PRE_TRADE high-value triggers

**Reality (sampled tonight):**
- Critic approving a skip on BTC consolidation -> **Opus** (massive overkill)
- Regime classification -> **Opus** (Haiku territory)
- Quant brain calls -> **Opus** (should be rule-based or Haiku)

**Investigation:**
1. `bot/llm/usage_tiers.py` -- the `get_model_for_trigger()` function. What does it return for each agent role at `LLM_USAGE_TIER=AGGRESSIVE`?
2. `bot/llm/agents/coordinator.py` -- search for `model_for_trigger` and `cli_model`. Are agent role overrides being respected? Or does AGGRESSIVE force Opus everywhere?
3. `.env`'s `AGENT_REGIME_MODEL`, `AGENT_TRADE_MODEL`, etc. We don't have these set. Should we?

**Decision points (Nunu owns):**
- Should AGGRESSIVE tier route agents differently than CONSERVATIVE?
- Should we set per-agent model overrides in `.env`?
- Should Critic-approving-a-skip use Haiku instead of Opus? (My strong recommendation: yes.)

**Sample data for Nunu to look at:**
- Bot's `agent_performance.jsonl` has `model_used` field on every decision. Pull last 100 decisions, group by `(agent_role, model_used, decision_type)`. Look for "this role + this decision = always overkill model."

---

### Item 3 -- **Risk Agent equity-aware sizing prompt update**

The sizing math fix in `4b2d4de` solves the immediate bug (qty = risk_$ / stop_width, no leverage multiplier). But the Risk Agent's *prompt* still says things like "Start with sz=1.0" and gives sizing guidance for general accounts -- not the current $5k account.

**The deeper issue:** at $5k equity with 3x leverage, the agent's "correct" sizing (0.24 BTC = $17.7k notional) requires $5.9k margin. The account has $5k. **Margin shortfall.**

If the agent had picked 5x leverage instead of 3x: margin = $3.5k. Fits within $5k. Trade executes.

So the Risk Agent needs to **co-optimize leverage and risk_pct given equity**. Currently it picks them independently.

**Fix path (your call whether to do this now or queue for later):**
1. Update `RISK_AGENT_PROMPT` (`bot/llm/agents/prompts.py:226`) to add: "Validate that risk_pct × equity / stop_width × entry / leverage <= equity * 0.95 (must leave 5% buffer). If not, raise leverage OR lower risk_pct."
2. Better: have the coordinator validate post-decision and bump leverage if margin doesn't fit (let Risk Agent stay general).

**Nunu's preference (per his message):** "we can do this properly to not somehow try to bid 150k with money we dont have." Translation: no hard caps, smart math. The coordinator should *adjust* leverage to make the trade fit, not reject it.

---

### Item 4 -- **Pilot 3 v3: re-run with the live-bot config + Bug #16 fix**

Once Bug #16 is patched, re-run Pilot 3 on the April 23-28 cascade window. Specifically:
- `python run.py backtest --symbols BTC --days 5 --start-date 2026-04-23 --llm --budget 3 --raw`
- Confirm agent decisions do NOT cite post-April-28 data
- Confirm any GO decisions now properly account for the equity at that time (not current $5k -- whatever the backtest sim is using)
- Push to `analysis/historical/layer2-pilot3-v3-results.md`

Expected:
- More GO decisions than v2 (which was always-skip due to the look-ahead bias making everything look toxic)
- Some of those GOs will fail/win -- gives us real edge measurement on the LLM-first config

---

### Item 5 -- **Counterfactual veto resolution working -- analyze the corpus**

The live bot recorded its **first counterfactual veto resolution** at 16:12 UTC:
```
cf_1780242956_821b1ce2: HYPE BUY hit tp2, counterfactual PnL=-6.23% (veto was correct)
```

(That `-6.23%` is the loss the bot would have taken if it HAD entered. "Veto was correct" = the skip saved that loss.)

**Investigate:**
- `bot/data/counterfactuals/scenarios.json` -- find all resolved entries from tonight
- Compute: count of correct vetoes, incorrect vetoes, total saved/missed PnL
- For incorrect vetoes (where the skip cost us a winning trade), look at the agent's thesis. Were any "wrong-way bias" calls actually right? Where does the LLM systematically misjudge?

This is the foundation of the learning loop. Every skip is now a forward prediction with an outcome.

---

## What I'm doing right now (so you don't duplicate)

- `4b2d4de` sizing fix is **committed but not live** -- bot is on PID 2424 from 09:20 restart. I'll restart the bot to apply the sizing fix after we coordinate via handshake.
- Continuing live bot health monitoring via Monitor tool
- Did NOT touch model routing yet (Nunu's call)
- Did NOT touch Risk Agent prompt yet (your call -- queue this if you're going to also do Bug #16)

## Suggested division of labor today

Per Nunu's "covering all bases" directive:

**You (laptop):**
- Items 1, 4 (Bug #16 + Pilot 3 v3) -- you have the backtest infra and the look-ahead diagnosis
- Item 5 (counterfactual analysis) -- you have the analysis skills

**Me (desktop):**
- Items 2, 3 (model routing + Risk prompt) -- I'm on the live bot side
- Continued live monitoring + incident response

We synchronize via handshake every meaningful commit. Push every 30-60 min if active.

## Hard constraints (from handbook + tonight's lessons)

- DO NOT add `ANTHROPIC_API_KEY` to `.env`. CLI routing only.
- DO NOT push to `main`. Nunu reviews and merges.
- DO NOT modify `historical/old-bot-pre-2026-04-23/`.
- DO NOT silence circuit breakers. They saved us tonight (15x notional cap caught the bug).
- DO use "Nunu" not "Vince" in commits and docs.
- DO NOT apply autonomous model-routing changes -- Nunu decides cost/quality tradeoff.
- DO NOT use synthetic LLM smoke tests. Production traffic is enough signal.

## Important context Nunu told me directly tonight

> "i think giving us maxes and stuff like that to work with heavily limits us. i have had a lot of success personally with up to 25, there are potential use cases for all of them, and generally they impact our hold time. i truly believe we can do this properly to not somehow try to bid 150k with money we dont have."

Translation: **don't cap leverage. Fix the math.** Use 25x when the data supports it. The agents should be equity-aware in their sizing decisions, not blocked by artificial caps.

> "feel like we have been a little lackluster on the data, i would like to see where our cli llms systems are and how usefull there are."

Translation: assess agent quality + cost. Don't just count successful pipelines -- assess whether the calls are buying us decisions Haiku couldn't make for 1/10th the cost.

> "we need to start truly working extremely hard and covering all bases today"

Translation: this is a focused day. Both Claudes on. Multiple parallel investigations. Clean push/pull cycle.

---

**Acknowledge with a handshake entry when you've read this.** I'll wait for your push before I restart the bot with the sizing fix, so we don't lose your investigations to a log rotation.

-- desktop-claude
