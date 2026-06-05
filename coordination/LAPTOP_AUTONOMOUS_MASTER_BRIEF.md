# Laptop Autonomous Master Brief

**From:** desktop-claude
**To:** laptop-claude
**Date:** 2026-06-02 21:30 UTC
**Mode:** Extended autonomous operation -- you work without human guidance until further notice

## Why this brief exists

Nunu wants the system to improve while he and I focus on:
- **Desktop:** monitoring live trades + small surgical fixes + market reads
- **Laptop:** all the deeper work below

This brief is YOUR mission for the next many hours / days. Work through it methodically. Push small, push often. When in doubt, document your reasoning and keep moving.

## Goal

Become the way to an alpha consistent profitable engine.

Operationally: produce code, analyses, and architectural improvements that compound the bots edge over time. The bot is already taking real trades (11 today, ~$450 paper-equivalent profit). Your job is to make trades 12 through 1000 each better than the last.

---

## Hard Constraints

1. **No new `ANTHROPIC_API_KEY`.** CLI subscription only.
2. **Do not modify live bot config (`.env`, `multi_strategy_main.py` runtime path, etc.).** Desktop owns live operations.
3. **Push to `historical-import-2026-05-30` only.** Do not push to `main` or `desktop-overdrive-2026-05-30`.
4. **Quota: yours to manage.** If you run a heavy backtest, expect a 2-3h dead window after. Plan accordingly.
5. **Computational work first, LLM calls second.** Many analyses are pandas/numpy not LLM. Do those before burning quota.
6. **Push small commits with clear messages.** A 1000-line uncommitted change is a liability.
7. **Update `coordination/handshake.md` on every meaningful action.** Use the existing format and tags.
8. **Do not delete or rewrite existing analyses.** Add new ones; reference old.

---

## What you have access to

- The codebase (`bot/` directory)
- Years of OHLC data (cached + fetchable via CCXT)
- All prior analyses (`analysis/historical/`, `analysis/desktop-session/`)
- The Bug #16 fix infrastructure (12 injection paths blocked)
- Per-agent model routing (Haiku/Sonnet) so quota goes further
- The corrected fee config (4.5 bps, not 45)
- The new "braver leverage" Risk Agent prompt (3-5x default tier)
- The 8h TIME_STOP (up from 2h)

---

## The 5-Lever Continuous Learning Brief

See `coordination/CONTINUOUS_LEARNING_BRIEF.md` for full detail. Quick version:

1. **Signal-fingerprint decision cache** (10-50x backtest speedup)
2. **Two-stage mechanical pre-filter** (3-5x speedup)
3. **Walk-forward validation** (catches rule decay + overfit)
4. **Parallel symbol processing** (4x wall-clock)
5. **Synthetic skip shortcuts** (-30% LLM load)

Build #1 first. It is the highest-leverage immediate win.

---

## Beyond the 5 Levers -- The Full Improvement Space

Continuous learning is a throughput multiplier on what we already do. The bigger questions are about WHAT we do.

### A) Data Sources Beyond OHLC

The agents currently see 1h+6h candles + a few derived metrics. Hyperliquid exposes WAY more:

- **Funding rates** (per-symbol, 8h periodicity). Extreme funding = crowded trade = reversal risk.
- **Open Interest** changes. Rising OI + rising price = strong trend. Rising OI + falling price = capitulation.
- **Liquidation cascades**. Spikes in liquidation volume = stop-hunt or genuine flush.
- **Orderbook depth + imbalance**. Thin book = volatile move ahead. Heavy bid wall = support.

**Why this matters:** the genuine edges in crypto often live in flow data, not price data. Two traders looking at the same chart see the same thing; one looking at funding sees a different setup.

**What you can do:**
- Audit `bot/data/fetchers/` -- which of these does the bot already pull?
- Identify which agents would benefit from each data source
- Propose a "data layer" that feeds richer context to agents
- Push to `analysis/data_layer/design.md`

This is a multi-day investigation. Worth it.

### B) Better Exit Logic

We have lost ~$50-200 across recent trades to premature time stops + suboptimal trailing. Specific issues:

- BTC #4 time-stopped at 5h with +$77 win when TP1 was just minutes away (would have been +$150)
- ETH #10 time-stopped at 2h with +$9 when ETH continued down (would have been +$40)
- Trailing distance is currently ATR-based fixed-multiplier. Should be vol-adaptive (tighter in low vol, looser in high vol).

**What you can do:**
- Analyze closed trades by exit type: TP1 / TP2 / SL / TIME_STOP / Exit Agent
- Compute "lost alpha" -- what would have happened if held to TP1/TP2 vs time-stopped
- Recommend a vol-adaptive trailing algorithm
- Recommend regime-adaptive time stop (longer in trending_bear, shorter in range)
- Push to `analysis/exit_optimization/`

### C) Multi-Timeframe Alignment

Bot uses 1h + 6h. Missing:
- 5m for entry timing (catch the first 5m candle of a reversal)
- 15m for trade-execution rhythm
- 4h for context (does 4h structure support the 1h thesis?)
- 1d for "what is the macro regime"

**What you can do:**
- Audit `bot/data/fetcher.py` -- can it pull these timeframes?
- Design a "timeframe consensus" feature: trade only when N timeframes agree
- Propose how to add this to Trade Agent context without bloating prompts
- Push to `analysis/multi_timeframe/design.md`

### D) Codebase Audit -- Dormant Agents

The codebase claims 9 specialist agents:
1. Regime
2. Trade
3. Risk
4. Critic
5. Learning (post-close)
6. Exit
7. Scout
8. Overseer
9. Quant

We see Regime/Trade/Risk/Critic actively in pipelines. Scout and Overseer appear in logs sometimes. **What about Learning, Exit, Quant? Are they properly wired? Producing useful output? Or are they dead code?**

**What you can do:**
- For each agent: read its prompt, find where it is invoked, find where its output is consumed
- For each agent: classify as ACTIVE / PARTIAL / DEAD
- For DEAD or PARTIAL: write a "wire it up" proposal
- Push to `analysis/agent_audit/dormant_agents.md`

This is high-impact and low-quota. Pure code reading.

### E) Manual Intuition Transfer

Nunu has years of trading experience. He says he has had success up to 25x leverage. The bot is mostly conservative (1-3x).

**Idea:** label a small set of historical trades as "this is what Nunu would have done" -- ENTRY, EXIT, SIZE, REGIME. Train a classifier on his judgment (could be as simple as decision tree). Compare to agent decisions to find systematic disagreements -- those are signals about where the bot is over/under-conservative.

This is an experimental idea. Discuss with Nunu before investing time. But the IDEA is documented.

---

## Operational Cadence

### Daily-ish rhythm (when working autonomously)

1. **Pull `historical-import-2026-05-30`**. Check `handshake.md` for any new desktop entries.
2. **Quick computational analysis** (pandas/numpy, no quota). E.g., aggregate latest closed trades, find patterns.
3. **One focused build**. Pick one item from the 5 levers OR the broader improvement space. Build it. Push it.
4. **Optional backtest** (if quota allows). Use new fee config + braver leverage prompt. Validate the build.
5. **Update handshake** with what you did, what you found, what you propose next.

### When to ping desktop via handshake

- You shipped something major (cache, walk-forward, etc.) -- desktop should consider integrating into live
- You found a bug in the LIVE PATH (something desktop should fix)
- You hit a confusion point and need second opinion
- You finished a 5-Lever item and have results

### When NOT to ping desktop

- Routine progress
- Computational analysis without code change
- "Ive been thinking..."

Just keep moving. Document; do not request approval for every step.

### Quota management

- Plan computational work for after a backtest (during the dead window)
- Plan backtests for AFTER quota reset (every ~5h)
- Run heavy backtests overnight UTC when neither human is active
- If you hit 429 mid-task, save state and switch to computational work

---

## Suggested Build Order (if you have unlimited time)

Week 1 (this week):
1. Decision cache (Lever 1) -- 2-3 days
2. Codebase audit (item D above) -- 1 day
3. Trade outcome analysis (request from earlier handshake) -- 1 day

Week 2:
4. Walk-forward (Lever 3) -- 3-4 days
5. Exit optimization analysis (item B) -- 1-2 days

Week 3:
6. Data layer design (item A) -- multi-day
7. Multi-timeframe (item C) -- 2-3 days
8. Pre-filter (Lever 2) -- 1-2 days

Beyond:
9. Parallel symbol runs (Lever 4)
10. Synthetic skip shortcuts (Lever 5)
11. Manual intuition transfer (item E) -- requires Nunu input

---

## Three Things Desktop Wants You to Verify First

Before any of the above, do these three quick checks. They are sanity checks that affect everything else:

### Check 1: Verify fee correction propagated through ALL analyses

Your earlier work used 45 bps. Now 4.5 bps is canonical. Re-aggregate:
- All counterfactual veto-correctness scores (some "marginal loss" vetoes may actually have been profitable opportunities at correct fees)
- All graduated_rule WR/PnL calculations
- All historical edge-finder outputs

Push: `analysis/fee_corrected_summary.md` with what changed.

### Check 2: Confirm Bug #16 fixes did not over-block

You fixed 12 injection paths. Confirm:
- Did any of the legitimately-needed live data also get gated?
- Specifically: graduated_rules from POST-overhaul (April 23+) should still be available to agents in BOTH live and backtest
- If you over-gated, propose a more surgical fix

Push: `analysis/bug_16_validation.md`

### Check 3: Latest trade outcomes vs counterfactual predictions

Take today's 11 trades:
- For each, what did Trade Agent thesis predict?
- What actually happened?
- Score: thesis-accuracy independent of trade-outcome (a correct thesis can still lose money to timing)

Push: `analysis/today_trade_thesis_accuracy.md`

---

## How to know you are on the right track

Good signals:
- Cache hit rate > 30% after first backtest with cache (proves repeats exist)
- Walk-forward eval cleanly separates "real edges" from "in-sample-only edges"
- Codebase audit finds AT LEAST one piece of dead infrastructure
- Trade outcome analysis identifies AT LEAST one systematic agent bias

Bad signals:
- "I refactored a lot but cannot show what improved"
- "I added X without testing it"
- "I am waiting for human direction"

When in doubt: ship code or analysis. Do not wait.

---

## What I (desktop) will be doing

- Monitor live trades, handle Exit Agent triggers, react to events
- Apply surgical config fixes Nunu approves
- Sample market reads + status updates for Nunu
- Codebase audit (item D) IF I have spare cycles
- React to your handshake pings when you push something major

I will NOT:
- Run backtests (you own that)
- Build the 5 levers (you own that)
- Touch your branch

---

## Final Note

This is a long brief. Pin it. Refer back. The five levers + the broader improvement space cover months of work. Pick what you can ship today; queue the rest.

Nunu's goal is alpha consistent profitable engine. Every commit you push should be answerable to: does this make the bot smarter, faster, or more profitable?

If yes, ship it.

-- desktop-claude
