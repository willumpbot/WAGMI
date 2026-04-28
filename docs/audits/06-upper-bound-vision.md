# Forward-Looking Potential & Upper-Bound Vision

*Agent ID: `a7be1a7edfea063d0`*

---

## Original Task

```
You are designing the **upper-bound vision** for the WAGMI trading bot at /home/user/WAGMI. The user said: "True understanding of potential is necessary." They want to know what this could become at its ceiling — not just the next bug fix.

Take what's been built and think 10x forward. What does WAGMI look like in 6 months? In 2 years? What are the architectural moves that compound?

Read for context:
- `ROADMAP.md`
- `CLAUDE.md`
- `bot/llm/agents/coordinator.py:1-50` (architectural intent)
- `bot/llm/claude_cli_client.py:1-15` (CLI vision)
- `bot/llm/swarm_master.py` (if exists — 6-agent offline optimizer)
- `bot/llm/strategy_discovery/` (if exists — strategy genesis)
- `bot/llm/autonomy_router.py`
- `bot/social/` (the social/content module — currently bypasses CLI)

**Mission Part 1: The current ceiling**
Given what exists today (9 agents + 11 strategies + CLI network + perpetual improvement infra), what's the realistic upper bound on:
- Profit factor
- Win rate
- Capital scale (what equity ceiling makes sense before microstructure issues?)
- Symbol breadth (how many concurrent symbols?)
- Trade frequency
- Cost per decision
- Latency per cycle

Be quantitative. Where are the diminishing returns?

**Mission Part 2: The 5 architectural multipliers**
Identify 5 things that, if added, would 10x the bot's effectiveness. For each:
- What it is
- Why it's a 10x not 1.1x
- What it requires (effort, data, infra)
- What it depends on (must come after X)
- Risk

Candidates to evaluate (pick 5):
- Fully local model (Ollama/llama.cpp) for $0 cost AND $0 vendor risk
- Multi-exchange routing (Binance + Hyperliquid + dYdX simultaneously)
- On-chain data integration (whale tx, DEX flow, mempool)
- Options layer (delta-hedged trades, vol harvesting)
- Multi-account / sub-account isolation (paper alongside live, A/B different configs)
- Real-time microstructure (order-book imbalance, footprint charts)
- Cross-asset correlation engine (BTC-ETH-SOL beta, equity-crypto)
- News/social sentiment (Twitter/Discord/Telegram event detection)
- Counterparty risk monitoring (exchange health, reserves)
- Strategy genesis (LLM-generated strategies validated in sandbox)
- Tournament-style agent evolution (genetic optimization on prompts)
- Multi-timeframe agent specialization (separate agents per TF)
- Market-making layer (passive maker rebates as alpha)
- Funding-rate arbitrage (cross-exchange perp funding deltas)
- DeFi yield layer (idle capital → lending while waiting)

**Mission Part 3: The Opportunist agent** (user-requested)
Design this in extreme detail.
- What is it FOR? (asymmetric opportunities the standard pipeline misses)
- Triggering conditions (idle time? specific signals? continuous?)
- Inputs (what does it scan?)
- Outputs (the schema)
- How it fits in the 9-agent pipeline (parallel? series? gating?)
- Trade volume implication (how many trades/day does it add?)
- Risk profile (how does sizing differ?)
- Long-term value (why bother?)
- Cost (token estimate × pr
```

---

## Full Report

I have sufficient context to deliver the upper-bound vision. I'll respond directly as text per system instructions (no report .md files; final output is the assistant message itself).

---

# WAGMI Upper-Bound Vision — "True Understanding of Potential"

This is the **ceiling appendix** to the permanent blueprint. Today WAGMI is a 9-agent + 11-strategy + CLI-routed perpetuals bot with 1310+ tests and walk-forward validation through 150 days. The question isn't "what bug is next?" — it's **"what does this become if we don't blink for 24 months?"** I'll answer that with numbers, sequencing, and conviction.

---

## Mission Part 1 — The Current Ceiling (with today's architecture)

The current architecture is a **single-machine, single-exchange (Hyperliquid), perp-only, LLM-mediated, 11-strategy ensemble**. Within that envelope, here's where diminishing returns kick in:

**Profit factor (PF) ceiling: 2.2 – 2.6 net of fees, sustained 90+ days.**
The 150d BTC backtest at PF 2.47 already touches this. Above 2.6, you're either over-fit, in a benevolent regime, or sized so small that fees stop dominating. The 11-strategy ensemble's confluence math (3-agree gate) caps you here because the marginal strategy adds variance reduction, not edge — past 5–7 strategies you're rediscovering the same factor in different costumes (trend-momentum-OI all correlate ~0.6 in trending regimes).

**Win rate ceiling: 56–60%** with 1.6–1.8 R:R. Pushing WR higher requires shrinking R:R, which is fee-suicide on Hyperliquid's 3.5 bps taker. The actual profit lever above 55% WR is **payoff ratio**, not WR — every bp of payoff > every percentage point of WR after the 50% mark.

**Capital scale ceiling: ~$1.5M – $4M deployed equity** before Hyperliquid microstructure starts eating you. The bot trades majors (BTC/ETH/SOL/HYPE) — at $4M, a 2x leveraged BTC entry is $8M notional, which is still inside Hyperliquid's BBO depth most hours but bleeds 4–8 bps slippage on aggressive entries. Below $1M you're under-utilizing Kelly; above $4M you're moving the book. Alts (HYPE) cap closer to $500k notional per entry before market impact dominates.

**Symbol breadth ceiling: 8–12 concurrent symbols.** Beyond that, the pre-trade pipeline (regime → trade → risk → critic) takes >6 seconds per scan cycle, you blow through Anthropic rate limits, and your portfolio correlation matrix collapses to one factor (BTC beta). The bot's "edge" is regime + LLM thesis discipline, not breadth — and 80% of the alpha is in the top 5 symbols.

**Trade frequency ceiling: 3–6 trades/day at the portfolio level**, ~0.5–1 per symbol. The 90d backtest shows 0.74/day — already near the ceiling under the 3-agree gate. Pushing to 10+/day requires loosening confluence, which collapses the edge (2-agree PF was negative).

**Cost per decision ceiling (Anthropic API path): $0.012 – $0.025 per pre-trade pipeline** (regime+trade+risk+critic on Haiku/Sonnet mix). At 6 trades/day × 30 days, that's $2.16 – $4.50/month — trivial. The CLI-subscription path (`claude_cli_client.py` at `/home/user/WAGMI/bot/llm/claude_cli_client.py`) drops this to **~$0** but adds 2–4s latency per call.

**Latency ceiling per cycle: 4–8 seconds end-to-end** (data fetch ~1s, strategy ensemble ~0.2s, 4-agent pipeline ~3–6s, execution ~0.5s). This is fine for swing/scalp on 5m+ candles but useless for sub-minute flow trading. The hard floor with API calls is ~2s; with local models it's ~0.4s.

**Where diminishing returns kick in**: more agents past 9, more strategies past 12, more symbols past 10, more LLM elaboration past Critic-level depth. The architecture is now **edge-bound by data inputs and regime variety**, not by the brain. Adding intelligence to the same data pool pays sub-linearly.

---

## Mission Part 2 — The 5 Architectural Multipliers (true 10x, not 1.1x)

Out of the candidate list, these are the five that compound:

### Multiplier 1: **Multi-exchange routing (Hyperliquid + Binance + Bybit + dYdX)**
- **What**: One bot, four exchanges, decisions routed to the venue with best (price, fee, funding, depth) per signal. Funding-rate arbitrage falls out for free.
- **Why 10x**: (a) Edge multiplied by ~3 because cross-exchange basis trades and funding deltas are alpha that's invisible single-venue. (b) Cuts Hyperliquid concentration risk to zero. (c) Doubles capital ceiling — $4M → $10M+ because you're not market-impacting any single book. (d) Unlocks **counterparty diversification** which is existential, not nice-to-have.
- **Requires**: CCXT abstraction layer (already there), per-venue order_executor, unified position state, cross-venue reconciliation, per-venue fee/depth/funding feed normalization.
- **Depends on**: `multi_strategy_main.py` breakup (currently 6,028 lines — the hardest blocker). Position reconciliation must be venue-aware.
- **Risk**: Complexity explosion. Cross-venue inventory drift. Different liquidation engines mean a unified "risk" layer is non-trivial.
- **Effort**: 4–6 weeks of senior engineering.

### Multiplier 2: **Local model integration (Ollama / llama.cpp running Llama-3.3-70B or Qwen-2.5-72B)**
- **What**: A local LLM backend behind the existing `LLMBackend ABC` pattern, used for the 70% of calls that are reformatting/calibrating/enriching (Regime, Risk, Exit, Scout, Quant, Learning). Anthropic Sonnet/Opus only for Trade + Critic on high-stakes triggers.
- **Why 10x**: (a) Cost goes from $0.27/month to literally $0 + electricity, but more importantly, **(b) the bot becomes a 24/7 always-on perpetual thinker** because there's no per-call price tag to discipline. The Background Thinker, Scout, Self-Analyst can run continuously instead of on triggers. That's an order-of-magnitude more reasoning per dollar. (c) Eliminates Anthropic vendor risk (the April-17 audit shows 62.7% `credit balance too low` errors — system was effectively dark). (d) Enables fine-tuning on your own trade history, which Anthropic can't do.
- **Requires**: GPU (one A6000 or 2x 4090), `LLMBackend` abstract base class, model versioning, prompt-compatibility shim (Llama doesn't follow Sonnet system prompts identically), local eval harness to benchmark each agent.
- **Depends on**: Calibration ledger (already exists at `bot/llm/agents/calibration_ledger.py`) so you can prove Llama-Regime ≥ Haiku-Regime accuracy before swapping.
- **Risk**: Llama doesn't follow JSON schemas as crisply as Claude — needs structured-output enforcement (vLLM grammar mode or Outlines). Reasoning on edge cases is weaker; keep Critic on Sonnet.
- **Effort**: 3 weeks for backend + prompt shim + per-agent A/B; 2 weeks for fine-tune dataset prep.

### Multiplier 3: **Strategy genesis (LLM-generated strategies validated in sandbox)**
- **What**: Wire `bot/llm/strategy_discovery/` (already 944 lines built — `research_agent.py`, `proposals.py`, `sandbox.py`) into a continuous loop: LLM proposes a hypothesis from observed market patterns + literature, sandbox backtests it on out-of-sample data, walk-forward gates it, deployment-gate auto-promotes survivors to live ensemble (with a probationary 5% weight).
- **Why 10x**: All 11 current strategies were human-written. The bot's edge ceiling is bounded by the **strategy author's imagination**. A self-generating strategy loop turns strategy count from a fixed asset into a compounding asset. After 12 months, you have 30 strategies, 18 of which are LLM-discovered, 6 of which beat the human-written ones. Edge isn't 1.1x'd; the **edge generation function itself is multiplied**.
- **Requires**: The plumbing already exists. Need: ensemble auto-registration, probationary weighting, automatic demotion (already exists at `bot/llm/auto_demotion.py`), regime-fit auto-mapping, and a strict deployment gate.
- **Depends on**: Walk-forward framework (have it), deployment gate (have it), strategy regime-fit dictionary (have it). Also depends on **counterfactual learner** so the bot knows what "missed" looks like when proposing new strategies.
- **Risk**: Overfitting paradise. Without ruthless gates, the LLM proposes 1000 strategies and 50 pass by chance. Mitigate with bonferroni correction on selection, mandatory 90d out-of-sample, and live shadow trading before any capital allocation.
- **Effort**: 2 weeks to wire what exists; 4 weeks to harden the gates.

### Multiplier 4: **Real-time microstructure layer (order-book imbalance, footprint, trade tape)**
- **What**: A separate microstructure feed (Hyperliquid L2 book + trade prints, sub-second), with an "Order Flow Agent" that produces a continuously-updated micro-edge score per symbol. Used to **time entries** within the LLM-approved trade window (when the regime+thesis+critic say "long SOL", microstructure picks the candle to fire).
- **Why 10x**: Today the bot pays full taker fee and crosses spread on every entry. Microstructure-timed entries can capture 30–50% of round-trip fees back via post-only / better fills, which is +15 bps per round-trip. Over 800 trades/year that's a Sharpe lift of ~0.4 — bigger than any new strategy. Also unlocks: liquidation-cascade detection in real-time (not 1m-after-the-fact), aggressive flow detection (whale market orders), spoofing-aware execution.
- **Requires**: WebSocket book reconstruction, sub-second latency path, separate execution engine for limit-laddering, in-memory state (Redis or pure Python), distinct logging.
- **Depends on**: Multi-machine deployment (microstructure can't share an event loop with 6-second LLM cycles), event bus.
- **Risk**: It's a different engineering culture (low-latency Python is a discipline). Easy to half-build and degrade overall reliability.
- **Effort**: 6–8 weeks; needs a dedicated module, not a bolt-on.

### Multiplier 5: **Multi-account / sub-account isolation (paper-alongside-live + A/B configs)**
- **What**: Run N parallel sub-accounts: live-conservative, live-aggressive, paper-shadow (always running the next-version config), canary (1% of capital running an experimental config). Same code, same data, different parameter sets, with a daily PnL diff that drives **automatic config promotion**.
- **Why 10x**: Currently every config change is a leap of faith. With canary + paper-shadow, the bot **continuously self-validates its own evolution**. Strategy genesis (multiplier 3) is unsafe without this; A/B prompt evolution is unsafe without this. This is the **substrate that makes all other improvements safe to deploy**. Without it you're shipping prayers; with it, every improvement is empirically gated by 14 days of parallel-track equity.
- **Requires**: Per-account state isolation, shared market data pipeline, per-account ledger, diff-reporting, automatic-promotion gate (only promote canary → main if it beats main on Sharpe over 30 days at p<0.10).
- **Depends on**: Distributed state (Redis or Postgres), event bus.
- **Risk**: Account drift bugs. Live paper data accidentally mixing into live execution. Wallet/key isolation must be airtight.
- **Effort**: 3–4 weeks.

**Did NOT make the top 5 (and why)**:
- *Options layer*: 10x potential but premature — Hyperliquid options are illiquid; Deribit integration is a separate project of similar scope.
- *On-chain data*: Powerful but its 10x lives 18+ months out and requires a different data stack.
- *News/social sentiment*: Easy to add, but lower than 2x — sentiment signal-to-noise is brutal in 2026.
- *DeFi yield on idle capital*: 1.1x at best (5% APY on 30% idle), not architecturally significant.
- *Tournament agent evolution*: Premium feature, but requires multipliers 2 and 5 first.

---

## Mission Part 3 — The Opportunist Agent (extreme detail)

**Purpose**: To capture **asymmetric, time-bounded, regime-defying opportunities** that the standard regime → trade → risk → critic pipeline categorically misses because that pipeline is optimized for **modal** market conditions. The Opportunist is for **tail events** where the modal pipeline says "no clear thesis" but the structure of the event itself IS the thesis (funding spikes, cascades, breaks of long-term levels, OI dislocations).

**Triggering conditions** (continuous, low-cost screen + episodic high-cost evaluation):
- Continuous: a cheap heuristic screener runs every 30s on Haiku ($0.0005/call) over a fixed list of "opportunity vectors":
  1. Funding rate beyond ±2σ of 30d distribution (per symbol)
  2. OI change >25% in 1h while price flat (<0.5%)
  3. Liquidation flow (long or short side) >$50M / 1h on majors
  4. Cross-pair ratios breaking 30/60/90-day extremes (ETH/BTC, SOL/ETH)
  5. Realized vol cratering (BB width <10th percentile) — squeeze setup
  6. Cross-exchange basis >5 bps (perp-perp or perp-spot)
- Episodic: when a screener fires, escalate to Sonnet for a full Opportunist evaluation (~$0.008/call).
- Idle integration: if the regular pipeline is idle (no signals from ensemble), Opportunist gets cycle priority.

**Inputs** (what it scans):
- Funding rates, last 30 days, all symbols (Hyperliquid + cross-venue if multiplier 1 is live)
- OI series, 1h granularity
- Liquidation feed (Hyperliquid public)
- Cross-pair ratio matrix (ETH/BTC, SOL/ETH, HYPE/SOL)
- Realized vol percentile rank
- Cross-venue basis (when multi-exchange is live)
- The deep memory of "what worked last time this fired" — Opportunist has its own slice of `deep_memory.py`

**Outputs (schema)**:
```json
{
  "opportunity_type": "funding_extreme|oi_dislocation|liquidation_cascade|ratio_break|vol_squeeze|basis_arb",
  "symbol": "BTC-USD",
  "venue": "hyperliquid",
  "thesis": "string, 2 sentences max",
  "direction": "long|short|pair_trade|mean_revert",
  "size_multiplier": 0.0-2.0,  // relative to standard sizing; opportunist can DOUBLE
  "time_horizon_minutes": 15-720,
  "invalidation": "explicit price/time/event that kills the trade",
  "confidence": 0-100,
  "asymmetry_score": 0-10,  // how lopsided is risk:reward
  "expected_R": 1.0-5.0,
  "novelty_flag": bool  // is this a setup we haven't seen in 30d?
}
```

**Pipeline placement**: **Parallel + late-gate**, not series. The Opportunist runs in parallel to the main pipeline. When it finds something, it pushes a candidate signal into the same stream the strategies push into. The standard ensemble + critic still review it (so it can't bypass risk), but with two modifications: (a) the 3-agree confluence gate is replaced by an **asymmetry_score ≥ 7** gate; (b) if Critic vetoes, Opportunist gets one rebuttal turn (it can append a counter-counter-thesis that Critic must address — this is a cheap A/B with `interactive_debate.py` which already exists).

**Trade volume implication**: +1 to +3 trades/day on average, but heavily clustered (5 in a single day during a cascade, zero for a week in summer chop). Annualized: ~400 additional trades, of which ~120 fire (Critic vetoes ~70%). Of those 120, expected WR is 50–55% but **R:R is 2.5–3.0** because asymmetry is the entry criterion. Net: +$8k–$30k/year on a $200k account, larger if multi-exchange is live.

**Risk profile**: Sizing differs in two ways. (1) Default size = 0.7x standard (because thesis is event-driven, has higher variance). (2) For `asymmetry_score ≥ 9` and `novelty_flag=false` (proven setup), size scales to 1.4x. Critic enforces that no Opportunist trade can exceed 2x normal portfolio risk regardless of asymmetry. Stop is **always time-bounded** (max horizon = `time_horizon_minutes`) — Opportunist trades that don't work in their window auto-close.

**Long-term value**: This is the **alpha that doesn't decay**. Funding extremes, cascades, ratio breaks — these are structural features of markets, not crowded factor trades. The 11 modal strategies will decay 5–15%/year as alpha gets arbitraged. Opportunist trades won't, because they fire on rare events whose alpha comes from forced-seller / forced-buyer dynamics, not from a discoverable rule. **In 24 months, Opportunist will be 30–50% of total PnL.**

**Cost estimate**:
- Screener: 30s cadence × 24h = 2,880 Haiku calls/day @ $0.0005 = $1.44/day = **$43/month**
- Escalations: ~8/day @ $0.008 = $0.064/day = **$1.92/month**
- Total: **~$45/month**, justifies itself with one trade/month.

**Five concrete example calls**:

1. **BTC funding crosses -0.01%** (extreme negative): Opportunist evaluates: shorts are paying longs heavily, indicates panic shorting. Cross-checks 30d distribution (this is a 3σ event). Checks OI: did OI spike (capitulation short squeeze setup) or fall (pure deleveraging)? If OI rose with negative funding → **long signal, asymmetry 8**, target = funding-mean-reversion + price recovery, time horizon 4h, size 1.2x. Invalidation: price breaks below pre-event low.

2. **SOL drops 8% in 5min on no news**: Opportunist evaluates: cross-checks ETH/BTC for correlation move (no), checks liquidation tape (large clustered longs liquidated). Diagnoses: **liquidation cascade, no fundamental driver**. Outputs: long signal, asymmetry 9, expected_R 3.0, time horizon 30 min – 2h, size 1.0x. Invalidation: failure to reclaim 50% retracement in 90 min. **This is the highest-value Opportunist setup** — asymmetric snap-backs on cascades have ~70% WR historically.

3. **ETH/BTC ratio breaks below 30-day low**: Opportunist evaluates: regime context (is BTC dominance trend or chop?), looks at funding on both legs. Outputs: **pair trade — long ETH / short BTC**, asymmetry 6 (lower because it's trend continuation, not asymmetry), confidence 55, size 0.6x. Time horizon 24-72h. Invalidation: ratio reclaims breakdown level. *Or* if asymmetry is too low, output `skip` — Opportunist skips more than it fires.

4. **Hyperliquid liquidations exceed $100M in 1hr**: Opportunist evaluates: side breakdown (longs vs shorts), affected symbols, correlation contagion to BTC majors. If long-side cascade on alts but BTC stable → **fade the cascade on the most-impacted alt**, asymmetry 8, size 1.0x. If both-sided liquidation spike → **stand down, regime-shift event**, output `risk_off_signal` to coordinator. The Opportunist can also output non-trade signals to **influence portfolio risk** (this is its second job).

5. **A specific symbol's open interest spikes 50% with price flat**: Opportunist evaluates: someone is positioning silently. Checks funding direction (which side is paying). If new OI is on long side at neutral funding → **sophisticated long accumulation**, output: long signal, asymmetry 6, time horizon 24-48h, size 0.8x. If OI rising with funding flipping negative → **short squeeze being prepared**, output: long signal, asymmetry 7, time horizon 12h, size 1.0x. If can't disambiguate → `watch` only, no trade.

---

## Mission Part 4 — The Long-Tail Agent Ideas (10 more, opinionated ranking)

| # | Agent | Role | Value | Cost/mo |
|---|---|---|---|---|
| 1 | **Adversary Agent** | Plays "what would I do if I wanted to liquidate this position?" before every entry. Generates the killing scenario. | Reduces avg drawdown 15-25% by forcing mental rehearsal of failure. | $20 |
| 2 | **Macro Context Agent** | Monitors FOMC dates, CPI, options expiry, BTC halving anniversaries; raises/lowers risk multiplier. | Avoids 3-4 disaster trades/year on event days. | $5 |
| 3 | **Correlation Sentinel** | Watches portfolio-level correlation; if 4 positions all = BTC-beta, downsizes them. | Caps tail drawdown 20-40%. | $10 |
| 4 | **Counterparty Health Agent** | Watches exchange reserves, withdrawal latency, social signals re: solvency. | Existential — saves the whole account once per 3-5 years. | $8 |
| 5 | **Postmortem Agent** | Already partial via Learning Agent. Upgrade: writes a short narrative postmortem per closed trade, fed back into deep memory. | Improves thesis quality 10-15% via richer memory. | $15 |
| 6 | **Devil's Advocate / Red Team Agent** | Once per week, reviews the bot's own track record adversarially. "What's the bull case that this whole bot is just lucky?" | Surfaces calibration drift, regime over-fit. | $5 |
| 7 | **News Distillation Agent** | Reads top crypto news + Twitter every 30 min, distills into 3-line context. | Ambient awareness — small but real edge on event days. | $25 |
| 8 | **Funding Curve Agent** | Models the funding term structure across symbols; outputs cross-section ranks. | Powers funding-arb trades; standalone alpha. | $12 |
| 9 | **Microstructure Agent** | (See Multiplier 4.) Real-time order flow scoring. | Massive. | $50 |
| 10 | **Self-Doubt Agent / Calibration Auditor** | Compares predicted confidence vs realized accuracy daily; pings Critic to re-weight when drift detected. | Keeps the bot honest as model versions change. | $5 |

**Highest-leverage 3 (in order)**:
1. **Adversary Agent** — biggest drawdown-reducer per dollar. Trivial to build, immediate impact.
2. **Counterparty Health Agent** — once-in-5-years value but that one event is account-saving.
3. **Microstructure Agent** — biggest pure-alpha contribution; gates deep into multiplier 4.

The Calibration Auditor is the sleeper pick — without it, every other agent quietly drifts.

---

## Mission Part 5 — Infrastructure Roadmap (priority order)

1. **Break up `multi_strategy_main.py` (6,028 lines)** — this is the single biggest blocker to ALL infrastructure work. Until this is decomposed into `tick_processor`, `llm_integration`, `position_wiring`, `analytics`, every multiplier above is gated by it. ROADMAP.md item 4.1.

2. **Distributed state — Redis first, then Postgres** — Redis for the hot path (current positions, regime cache, scratchpad bus), Postgres for historical + auditable (decisions, trades, calibration ledger). Today these are JSON/SQLite which won't survive multi-process.

3. **Event bus — start with Redis Streams, graduate to Redpanda only if needed** — Kafka/Redpanda is overkill until you have >5 services. Redis Streams gives you pub/sub + replay + consumer groups for free, and 90% of crypto bots never outgrow it.

4. **Multi-machine deployment**: one process per *concern*, not per asset. Pattern:
   - `bot-execution` (one per exchange)
   - `bot-llm-pipeline` (one or two, share work)
   - `bot-microstructure` (one per exchange, low-latency)
   - `bot-research` (strategy genesis, swarm, postmortems — batch tier)
   - `bot-monitor` (Telegram, Discord, dashboard)

5. **Observability — Prometheus + Grafana + a single AlertManager rule set**. The bot already has structured snapshots; expose them as `/metrics` endpoints. PnL, latency per agent, veto rate, calibration error, decision cost — all dashboards. This pays for itself in the first 60-day live run.

6. **Time-travel replay** — ability to re-run any historical day with current code. Already partially exists (`bot/llm/replay_engine.py`). Critical for regression testing prompt changes. Should be a CI job.

7. **A/B + canary framework** — Multiplier 5. Parallel sub-accounts.

8. **Cold-storage data lake** — S3 (or local NVMe + hourly tarball to S3). Every tick, every order book snapshot, every LLM call (request + response). At ~5GB/day this is trivial. Backtest fidelity goes from 91% → 99% when you can replay against actual book state.

9. **Secret management — move from env vars to AWS Secrets Manager / HashiCorp Vault** when you cross **three** of: multi-machine, multi-account, multi-team. Today env vars are fine. Breaks at scale 10x.

10. **Backup + DR** — today, `position_backup.json` is the entire DR story (per ROADMAP.md known issue: "RECONCILE warn on every startup"). At scale, you need: hourly state snapshot to S3, automated restore drill weekly, secondary box on standby. The realistic disaster is "the box dies during an open position" — current MTTR is hours; target is <60 seconds.

---

## Mission Part 6 — Decision-Theoretic Ceiling

Edge decomposition for a regime-aware, ensemble-confluent, LLM-vetted, perp-only bot:

- **Crypto majors (BTC/ETH/SOL) market efficiency**: ~70%. Therefore raw alpha headroom is ~30% (in some hand-wavy decomposition). Of that 30%, **systematic ensembles can capture 8–12%** in strong regimes; the rest is short-window edge that requires HFT or info advantage.
- **Crypto alts (HYPE, midcaps)**: ~40% efficient → raw headroom ~60%. Systematic capture ceiling ~15–20%, but capacity is tiny ($500k notional ceiling per entry).
- **Regime classification accuracy ceiling**: academic literature on HMM/ML regime models tops out around **80–85%** out-of-sample on liquid majors. The bot's current implementation (volatility proxy + ADX + LLM) probably achieves ~65%. There's room to push to ~78% with better classifier + LLM ensemble.
- **Multi-strategy ensemble vs single-strategy**: well-constructed 8-strategy ensemble lifts Sharpe ~1.4x – 1.8x over the best single strategy via variance reduction (correlation between strategies = ~0.4 in trending, ~0.6 in chop). The 11-strategy ensemble probably already captures 90% of available variance reduction.
- **LLM thesis validation contribution**: the empirical contribution observed is **~20% trade rejection rate, with rejected trades having ~10–15% lower realized expectancy** than accepted. That works out to a Sharpe lift of ~0.2 – 0.4 on top of the ensemble. **Bigger when prompts are well-calibrated; can be negative when miscalibrated** (April-17 audit found Critic confidence stuck at 0.5, Quant outputting "unknown" — that's a Sharpe leak).

**Realistic envelope (everything-works case)**:
- **Sharpe ceiling: 2.4 – 2.8** in a representative crypto year (2021/2024-style mixed regime).
- **Sharpe in a benevolent year (2017/2020): 4.0+** (and you should distrust it — that's regime luck).
- **Sharpe in a malicious chop year (2018/2022 ranges): 0.6 – 1.0**, sometimes worse, even with everything working — discipline gets paid by survival, not by gains.
- **Max drawdown ceiling under graduated risk**: 12–18% running peak-to-trough, larger if you turn off circuit breakers.
- **Annualized return at $1M capital, full multipliers live: 35–60% net of fees**, with the *honest* expected return centered closer to 30–40%.
- **Capacity-adjusted Sharpe at $5M**: 1.8 – 2.2 (some Sharpe is given back to slippage at scale).

The honest framing: **the bot's edge is regime-aware execution discipline + LLM thesis validation** — that's a real, persistent edge of roughly **0.8 – 1.4 Sharpe units** on top of a passive long-BTC baseline. Everything else is cherry on top.

---

## Mission Part 7 — Dangerous Failure Modes at Scale

1. **Memory inflation** — `deep_memory` grows unbounded; LLM context bloats; cost ramps; relevance dilutes. **Solution**: Memory has to be hierarchical (hot/warm/cold) with active forgetting. Today there's a 7-day TTL on short-term but deep memory has no decay function. Build one before crossing 5,000 stored notes.

2. **Decision latency** — every new agent adds 0.5-2s to the cycle. Beyond 9 agents you risk missing trades on 5m candles. **Solution**: parallelize within the pipeline (Regime, Risk can run in parallel; Trade and Critic must be serial). Move to local model for non-critical agents.

3. **Cost ramp** — current $0.27/month is misleading; that's at LLM_MODE=2 (veto only). At full autonomy with continuous Scout + Background Thinker + Strategy Genesis: $200-800/month easily, more if multi-account. **Solution**: Multiplier 2 (local models). Without it, costs scale super-linearly with capability.

4. **Anthropic rate limits** — already biting (April-17: 62.7% credit-balance errors leaving the system "dark"). At higher cadence + multi-account this is fatal. **Solution**: budgeted call queue + local fallback + observable alerting on every API failure (currently silent).

5. **Model drift** — Anthropic releases new Sonnet versions every 4-6 months; old prompts subtly change behavior. The bot has a calibration ledger but no automated drift alarm. **Solution**: every minor model update triggers a forced re-calibration sprint on shadow account before promotion.

6. **Strategy decay** — published edges erode 10-30%/year as flows arbitrage them. Funding-rate strategies are particularly exposed. **Solution**: Strategy genesis (Multiplier 3), and aggressive demotion of any strategy whose 90d PF drops below 1.3.

7. **Confidence calibration drift** — agents become systematically over- or under-confident as data distribution shifts. Current calibrator handles this slowly. **Solution**: Adversary + Self-Doubt agents, weekly forced recalibration.

8. **Regulatory** — Hyperliquid is an offshore perp DEX; perp regulation is volatile in 2026. CEX listing rules can pull the rug on a symbol mid-position. **Solution**: counterparty agent + multi-venue + don't trade fresh listings.

9. **Subscription path failure mode** (specific to CLI client) — `claude_cli_client.py` runs through user's Claude Code subscription. If usage limits hit, the bot falls back to heuristics silently. **Solution**: explicit alerting on every subprocess failure; fallback to API-tier with budget cap.

10. **The social/content module bypassing CLI** — `bot/social/daily_grind.py` and `content_engine.py` use the Anthropic API directly (not CLI). At scale this means social-content costs are uncapped while trading is subscription-bound. **Solution**: route social through the same `LLMBackend ABC` (which doesn't exist yet — that's why this is escaping).

---

## Mission Part 8 — The "Next Big Thing" Candidates

Things in the 2026 trading landscape WAGMI should be ready to absorb:

- **AI-on-AI arbitrage** — by mid-2026, half the volume on perp DEXes is bot-driven, and many bots use similar LLM stacks. Their patterns become predictable. WAGMI's edge could include a "bot detector" that fades or front-runs other bots' patterns. Real, but requires multi-second microstructure (Multiplier 4).
- **DeFi → CeFi flow / perp-spot basis** — basis trades remain the cleanest carry in crypto. Once multi-exchange (Multiplier 1) is live, this is one extra strategy module.
- **LSD basis (stETH-ETH, jitoSOL-SOL)** — yield-bearing collateral pairs trade with predictable spreads. Stable strategy, modest size.
- **L2-emerging perps markets** (Aerodrome, Jupiter Perps, GMX v3, Synthetix) — first-mover edge on smaller venues; venues come and go but rotating into them is a recurring 30-50% APY play.
- **RWA tokens hitting perps** — when tokenized treasuries / commodities get perp markets, classic macro pairs (gold-equity, dollar-DXY) become tradeable on-chain. Long-tail but real.
- **Event types**: FOMC, CPI, options expiry (3rd Friday), exchange outages, CZ-tier news. Build a calendar-aware Macro Agent (long-tail #2 above) and treat these as opportunity windows.

---

## Mission Part 9 — What NOT to Build (opinionated)

- **HFT / sub-second latency** — not winnable from a Python bot. Don't even try.
- **Black-box ML models (deep RL replacing the Q-table)** — interpretability matters more than 1-2% lift. The bot's value is that *you can audit every decision*.
- **Spot trading** — perps are the edge (funding, leverage, shorts, no custody). Spot is a distraction unless you build a crypto fund.
- **More CEX integrations beyond the top 4** (Hyperliquid + Binance + Bybit + dYdX) — each new venue has a 10x integration cost vs marginal alpha contribution. Stop at 4.
- **More strategies before the existing 11 are validated post-paper** — six of eleven aren't firing per the April audit. Fix that before adding strategy 12.
- **A custom in-house LLM trained from scratch** — you don't have the data, compute, or talent. Use Llama / Qwen + fine-tune.
- **A blockchain layer / on-chain execution beyond DEX trading** — every team that builds "the on-chain protocol" and "the bot" together fails the bot. Stay in your lane.
- **A consumer product / copy-trading service** before you have 12 months of live track record. Nobody copies a bot they can't audit, and you can't audit until paper validation finishes.
- **A crypto news scraper from scratch** — use existing aggregators (Cryptopanic, Tree of Alpha). Don't reinvent.
- **A web frontend rebuild for the third time** — frontend already got rewritten April 17. Stop. The dashboard is for your eyes only; ship features, not pixels.

---

## Mission Part 10 — The 6-Month Roadmap (concrete)

**Month 1 (May 2026): Stabilization + LLMBackend ABC + CLI hardening**
- *Done*: All April-17 critical bugs resolved (stop-bug F1, dedup P6, sniper leverage cap).
- *Build*: `LLMBackend` abstract base class. Every LLM call route through it. Social module migrated. CLI client failure alerting. Critic prompt re-calibration. Quant agent fix.
- *Verify*: 7-day paper run with full pipeline, regime classification working, all 9 agents producing valid output. Cost <$10. Zero silent fallbacks.
- *Unlocks*: Local model swap; multi-backend A/B.

**Month 2 (June 2026): Opportunist + Adversary + Microstructure-lite**
- *Build*: Opportunist agent (full spec above). Adversary agent (cheaper, ships first). Light L2 microstructure feed (book imbalance only, no full footprint).
- *Verify*: Opportunist generates 40-100 candidates over 14 days, ~25-30% pass Critic, paper PnL +5-15% vs control. Adversary cuts realized drawdown by ≥10%.
- *Unlocks*: Confidence in agent pipeline extension; data for further agent additions.

**Month 3 (July 2026): Local model integration (Ollama + Llama 3.3 70B)**
- *Build*: Ollama deployment, prompt-compatibility shim, per-agent A/B benchmark vs Anthropic. Move Regime/Risk/Exit/Scout to local first; keep Trade/Critic on Sonnet.
- *Verify*: Per-agent calibration ≥ 95% of Anthropic baseline on 30-day shadow account. Cost drops ~70%. Latency drops ~40%.
- *Unlocks*: Continuous reasoning (no per-call cost discipline). Strategy Genesis becomes affordable.

**Month 4 (August 2026): Multi-exchange (Binance + Hyperliquid)**
- *Build*: Per-venue executor, unified position state, cross-venue reconciliation, funding-arb strategy module. Start with read-only on Binance, gate live trading until 30-day shadow validation.
- *Verify*: Paper Binance trades match expected fills. Funding-arb positions held 3+ days without state-drift bugs. Capital scaling test at $1M notional.
- *Unlocks*: $4M+ capital ceiling. Funding alpha. Counterparty diversification.

**Month 5 (September 2026): Strategy genesis (LLM-generated strategies)**
- *Build*: Wire `strategy_discovery/` corpus + research_agent + sandbox + auto-promotion. Probationary 5% weight gate. Bonferroni-corrected selection.
- *Verify*: 20+ proposals/week, 1-2 promotions/month, all surviving 90d walk-forward. Live shadow trading on promoted strategies for 30 days before any capital.
- *Unlocks*: Compounding strategy count. Self-evolving alpha.

**Month 6 (October 2026): Scale + observability + multi-account**
- *Build*: Prometheus + Grafana + AlertManager. Multi-account framework (live-conservative, live-aggressive, paper-shadow, canary). Automatic config promotion gate.
- *Verify*: 30-day parallel-track equity diff converges with backtest expectations. Canary promotion happens at least once. Full system observable.
- *Unlocks*: Confidence to scale capital 5-10x. Continuous safe evolution.

**At end of Month 6**: WAGMI is a multi-exchange, multi-account, locally-LLM'd, self-evolving, observability-instrumented perp trading system with 10+ agents, 15+ strategies (11 human + 4 LLM-discovered), running 24/7 at sub-$50/month operating cost, with $1-3M deployable capital and a credible Sharpe of 1.8-2.4 net of fees.

---

## Closing — The Compounding View

The single idea worth holding: **the multipliers compound, the agents don't.** Adding agent #11, #12, #13 yields decreasing returns. But the multipliers — multi-exchange, local LLM, strategy genesis, microstructure, multi-account — each multiply the *value of every agent already built*. Adversary on a single-venue bot is a 1.05x. Adversary on a multi-venue, locally-running, strategy-evolving, multi-account bot is a 1.4x because every saved drawdown compounds across N venues × M strategies × K accounts.

The strategic order is therefore: **infrastructure first (months 1-2), capability multipliers next (months 3-4), generative engines last (months 5-6).** Build the substrate. Then the multiplier. Then let it grow.

What WAGMI becomes in 2 years if this sequencing holds: a self-improving, multi-venue, regime-aware perpetuals trader with a strategy library that grows monthly, agents that audit each other, costs near zero, latency under a second, and a track record that's *legible* — every decision auditable to the sentence. That bot is not novel because of any single feature. It's novel because **every part is closing the loop on every other part**, continuously, at zero marginal cost.

That's the upper bound.

### Critical Files for Implementation
- /home/user/WAGMI/bot/multi_strategy_main.py (must be decomposed first — gates everything)
- /home/user/WAGMI/bot/llm/agents/coordinator.py (where Opportunist + Adversary plug in)
- /home/user/WAGMI/bot/llm/claude_cli_client.py (where the LLMBackend ABC slots in alongside Ollama backend)
- /home/user/WAGMI/bot/llm/strategy_discovery/research_agent.py (strategy genesis activation)
- /home/user/WAGMI/bot/execution/order_executor.py (multi-exchange routing extension point)