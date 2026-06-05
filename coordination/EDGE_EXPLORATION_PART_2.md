# WAGMI Edge Exploration — Part 2

**From:** desktop-claude
**Date:** 2026-06-02 23:40 UTC
**Trigger:** Nunu — "Is that truly all? We have limitless opportunity. Continue to refine our thinking."
**Approach:** Part 1 was an audit (where we are, what's broken). Part 2 is expansive edge discovery — what edges EXIST in this market that we are not yet capturing, and how we make ourselves systematically better at finding more.

---

## Part 9: Edges we have not even started exploring

Grouped by category. Each is a real, capturable edge for a sub-$10k account on perp DEXs.

### 9.1 Microstructure / Order Flow

- **Large prints / sweeps** — single trades >$500k or rapid sequence eating a side of the book. Often precede continuation OR mark exhaustion. Distinguish by location (in trend vs counter-trend).
- **Bid/ask imbalance over time** — sustained 70/30 bid weighting in BTC perps = building pressure. Not just a snapshot; the RATE OF CHANGE matters more.
- **Book depth thinning before moves** — market makers pull liquidity 30-60s before a big move. Visible in 1-minute orderbook snapshots.
- **Spoofing / layering detection** — large orders that appear and vanish on one side = manipulation signal, often fade.
- **Trade size distribution shifts** — when median trade size suddenly doubles, institutions are participating.

**How to capture:** Hyperliquid has an L2 orderbook API. We'd need to snapshot it every 5-10s, compute imbalance metrics, expose them to the Trade Agent.

### 9.2 Cross-venue / Cross-asset

- **Hyperliquid vs Binance basis** — if BTC perp on HL trades $30 below Binance for >2 min, arb pressure says HL will catch up. Free signal.
- **Spot vs perp basis (funding-implied)** — funding rate plus contango/backwardation tells you positioning bias.
- **BTC dominance moves** — when BTC.D spikes, alts bleed. When BTC.D drops in a green tape, alts pump.
- **Correlation breakdown** — usually BTC/ETH r=0.9. When it drops to 0.5 in a day = regime shift incoming.
- **SOL/AVAX/HYPE as leading indicators** — sometimes alts move first; majors follow.
- **DXY moves** — dollar strength is inversely correlated to crypto. Underused.
- **Equities pre-market / overnight** — SPY futures during Asia session predict crypto direction surprisingly often.

**How to capture:** add a Binance ticker subscription for basis. Add a CoinGecko/CMC pull for BTC.D. Add a Stooq/Yahoo pull for DXY + SPY.

### 9.3 Derivative / On-chain

- **Open interest distribution** — not just total OI but where it's concentrated. OI build at $100k BTC = stop hunt incoming.
- **Funding rate momentum** — not just current funding, but its rate of change. Funding flipping from neg to positive in 4h = aggressive longs piling in.
- **Liquidation cascades** — when liquidations >$50M/hour, expect reversal within 1-2h.
- **Premium index** — Hyperliquid publishes premium vs index price. Sustained premium = euphoria.
- **Whale wallet movements** — large transfers TO exchanges = sell pressure. FROM exchanges = accumulation.
- **Stablecoin mint events** — USDT/USDC mints >$500M = buying ammo.
- **Long/short ratios on Binance** — public data. When 90% are long, fade. (Underused contrarian signal.)

**How to capture:** Coinglass API for OI/funding/liq. Glassnode for on-chain. CoinGecko for stable supplies.

### 9.4 Time-of-day / Calendar

- **Asia open (00:00 UTC)** — Tokyo/Singapore session. Often trending, lower vol.
- **London open (08:00 UTC)** — biggest liquidity event of the day. Reversals common.
- **NY open (13:30 UTC)** — equities open. Often trend continuation OR reversal of overnight move.
- **NY close (20:00 UTC)** — institutional rebalancing. Frequent fades.
- **Friday close (Friday 20:00 UTC)** — derisking into weekend. Long bias bleeds.
- **Sunday open (Sunday 22:00 UTC)** — thin book, gap moves possible.
- **Monthly close (last day 23:59 UTC)** — institutional repositioning. Distinct from weekly.
- **CPI / FOMC / NFP days** — econ events at 12:30/14:00/18:00 UTC. Vol spikes guaranteed.

**How to capture:** time-of-day features in agent context. Econ calendar pull (TradingEconomics or ForexFactory).

### 9.5 Volatility regime

- **Implied vs realized vol spread** — when implied (options) > realized (historical), market expects a move. When realized > implied, current move is "overdone."
- **Vol-of-vol** — volatility of volatility. Rising vol-of-vol = chop regime. Stable vol-of-vol = trend regime.
- **Vol expansion after compression** — Bollinger band width contracting for hours then expanding = breakout setup.
- **Cross-asset vol divergence** — BTC vol low, ETH vol high = ETH-specific event.

**How to capture:** compute realized vol on rolling windows. Pull Deribit options data for implied vol. Compute spread.

### 9.6 Behavioral / Sentiment

- **Twitter sentiment shifts** — sudden uptick in "long" mentions / fear language.
- **Funding-implied positioning** — when funding goes deeply negative, shorts are crowded. Long bias.
- **Retail buying spikes** — Robinhood-style apps' top-buy lists.
- **Coinbase app rank** — when CB hits #1 on App Store, tops are near.
- **Google Trends "bitcoin"** — leading indicator of retail attention.
- **Reddit /r/cryptomarkets sentiment** — quantifiable via NLP.

**How to capture:** Twitter API (cost), Google Trends API (free), AlternativeMe Fear & Greed (free).

### 9.7 Pattern recognition / Memory

- **Setup memorization** — "this BTC chart looks like Feb 14 2025 setup that did 8R." Vector embedding of recent chart vs historical winners.
- **Adversarial replay** — "what would I have done if I was an attacker who wanted to stop-hunt my position?"
- **Historical regime matching** — current regime fingerprint vs past 3-year data — find closest match, look at what happened next.
- **Successful trade DNA** — feature vector of every win. New signals scored on similarity to past wins.

**How to capture:** vector DB (FAISS local, or just numpy cosine sim). Embed chart features. Cosine match.

### 9.8 Meta / Self-referential

- **Agent disagreement signals** — when Trade Agent and Critic disagree strongly AND Regime Agent shifts, that's a "regime in transition" marker.
- **Agent confidence calibration** — when our agents say 80% confident, are they actually right 80% of the time? Track calibration curves per agent.
- **Past-self correctness** — every decision we made yesterday, was it right? Replay tomorrow and grade.
- **Counterfactual veto pattern mining** — across 100+ vetoes, are there patterns of "we always veto X situation but X is actually a win"?
- **Bot's own behavioral biases** — does the bot over-trade after losses (revenge trading)? Under-trade after wins (complacency)? Track our own emotional analogues.

**How to capture:** these are FREE to add. Just instrumentation on existing decision flow.

### 9.9 Capital structure / Portfolio

- **Capital efficiency** — fraction of capital actually deployed vs idle. If we use 40% of capital and idle 60%, we're under-trading.
- **Reentry logic** — when stopped out, if thesis still valid, reenter (with tighter risk). Currently bot does not reenter aggressively.
- **Pyramiding** — adding to winners. If BTC SHORT #8 is +$200 with thesis intact, add 0.5R more. Currently zero pyramiding.
- **Cross-position correlation** — hedge ratio. If 3 positions are correlated 0.9, that's actually 1 position with 3x leverage.
- **Volatility budget** — total portfolio vol, not just sum of position sizes.

**How to capture:** mostly in execution layer; add a `portfolio_state` aggregate and have agents consume it.

### 9.10 Adversarial thinking

For every signal, ask: "if I were on the OTHER side of this trade, what would I be planning?"
- If we're long BTC at $100k stop $98k — where would the smart money set up a stop hunt? At $97800-98200. That's predictable; we can place stops differently.
- If we're short ETH at $4k stop $4100 — where is liquidity above $4100? Map it.
- The "stop hunt zone" is where retail crowds. Avoid placing OUR stops in those zones.

**How to capture:** an "adversarial" pre-trade check that maps stop clusters before stop placement.

---

## Part 10: Edges that exist in our SYSTEM but we're not pulling on

These are already-built things we just don't fully USE.

### 10.1 The Scout Agent

Scout generates watchlists and pre-formed theses during idle time. But:
- Are scout outputs actually consumed by Trade Agent at decision time?
- If Scout said "BTC sets up for a long at $99500 with confluence A/B/C" two hours ago, and price hits $99500 now, does Trade Agent reference it?
- This could be a massive efficiency win — pre-warmed conviction.

### 10.2 The Overseer Agent

Currently skipped because "input too thin." What if we fed it the full handshake.md + recent decision history? It might catch patterns the per-decision agents miss.

### 10.3 Deep memory

We write trade DNA but probably don't read it at decision time. If new BTC SHORT signal has feature vector similar to past wins, that's a massive boost.

### 10.4 Quant Brain (mechanical)

We disabled the LLM-bypass gate. But Quant Brain's mechanical signals still produce useful metadata (EV, RR, win prob). These should be CONTEXT for the LLM, not gates.

### 10.5 The 9 strategies

We have 4 strategies in the documented ensemble but 9 in the codebase. Of the 5 less-mentioned ones — are they running? Disabled? Disabled because they were bad, or because no one wired them?

### 10.6 Knowledge base

`data/llm/knowledge_base.json` and rule files. We saw the "SOL SHORT toxic" rule firing — meaning the KB is consulted. Good. But is it being UPDATED based on outcomes? When the SOL SHORT veto turns out wrong (counterfactual), does the KB entry get demoted?

### 10.7 Hold-time rules

There's a hold-time rules manager. Spec says it tunes max-hold dynamically per setup. Probably dormant.

### 10.8 Network learning

`bot/llm/network_learning.py` — graph-based learning across symbols/regimes. Probably dormant.

---

## Part 11: How do we systematically find MORE edges?

The above is what one human plus one Claude could brainstorm in 20 minutes. The real edge is BUILDING A MACHINE THAT BRAINSTORMS THIS CONTINUOUSLY.

### 11.1 An Edge Hypothesis Pipeline

Build a perpetual edge discovery loop:

1. **Hypothesis generator** — every day, propose 3-5 new "if X then Y" hypotheses based on (a) the previous day's surprising moves, (b) counterfactual veto patterns, (c) cross-asset divergences, (d) random combinations of features
2. **Hypothesis tester** — backtest each hypothesis on 30 days of historical data with synthetic skip + decision cache speedups
3. **Hypothesis grader** — sharpe, max DD, win rate, statistical significance
4. **Hypothesis promoter** — if hypothesis passes threshold, promote to live shadow tracking (Decision happens but doesn't execute; outcomes logged for 14 days)
5. **Hypothesis graduator** — if shadow validates, promote to live trading rule
6. **Hypothesis demoter** — if rule degrades, demote
7. **Hypothesis pruner** — retire old hypotheses; archive but disable

This is a Darwinian system. Run it daily. Every week, the bot has been exposed to 30+ new ideas, 5 tested, 1-2 promoted.

### 11.2 An Agent Self-Critique Pipeline

Every day:
- Pull all decisions from the last 24h
- For each WIN: would Critic Agent today still veto it? Why or why not?
- For each LOSS: would Critic Agent today still APPROVE it? Why or why not?
- For each VETO that turned out wrong: would Critic Agent today still veto?
- Compile a "lessons" document
- Feed it back into the next day's agent prompts

This is meta-learning: the agents reflecting on their own past behavior.

### 11.3 Adversarial Red Team Mode

A second LLM agent that ONLY tries to break the bot's thesis:
- Trade Agent says "BTC LONG conf=70%"
- Red Team Agent says "here are 5 reasons this fails: 1, 2, 3, 4, 5"
- Critic uses Red Team's output as context

This is different from Critic — Critic stress-tests softly. Red Team is adversarial-by-design.

### 11.4 Curiosity-driven exploration

Sometimes, take a trade JUST to learn. Even if EV is borderline. Tag it as "exploration." Track exploration trades separately. Discount them in PnL but treat their lessons as high-value.

This is RL "epsilon-greedy" — explore vs exploit balance.

### 11.5 Bayesian belief updating

Every position close updates a belief about every relevant feature. Over 100s of trades, the bot has explicit probability distributions on:
- "BTC SHORT in trending_bear with ADX>50 wins X% of the time at Y RR"
- These distributions are not point estimates; they're full posteriors with uncertainty
- High-uncertainty setups = "explore more"; low-uncertainty winners = "exploit"

This is a serious upgrade from binary rules.

### 11.6 Counterfactual world simulation

For each historical decision, simulate the COUNTERFACTUAL world where the bot acted differently. What if we'd sized 2x bigger? Held 4h longer? Closed on TP1 only? Generates synthetic data without taking real risk.

### 11.7 Continuous improvement cadence

- **Daily:** review last 24h trades, what surprised us
- **Weekly:** hypothesis test results, rule promotions/demotions
- **Monthly:** strategy weight evolution, agent calibration check
- **Quarterly:** architectural review — are agents still right composition? Are there missing roles?

---

## Part 12: How do we make our THINKING better?

Meta-meta level: how does Nunu + 2 Claudes stay sharp?

### 12.1 Daily structured prompts

Each morning, one of the Claudes runs a structured check:
- What did yesterday's bot do that was surprising?
- What did yesterday's bot NOT do that it should have?
- What's the one biggest improvement opportunity today?
- What's the one biggest risk today?

This forces us out of reactive mode.

### 12.2 The "What would surprise me?" exercise

Once a week, write down: "If I came back to this codebase in 30 days, what's the most surprising thing I'd find?" Then GO LOOK for that thing. Often the answer is something we've been avoiding.

### 12.3 First-principles audit

Once a month, throw out all assumptions and re-derive. "Why do we use weighted_veto ensemble? Could it be wrong? What if we used pure-LLM dispatch only?"

### 12.4 Adversarial peer review

Each Claude reviews the OTHER Claude's work weekly. Not collaboratively — adversarially. Find what's wrong with the other's plan.

### 12.5 Track decision quality, not just outcomes

A bad outcome from a good decision is fine. A good outcome from a bad decision is luck. Differentiate. Track decision quality (process) separately from outcome (luck).

### 12.6 Read more about what the smart money does

Hedge funds, prop shops, market makers. What edges do they exploit? Most are inaccessible (HFT) but some (basis trades, vol arb, calendar spreads) are absolutely available on Hyperliquid.

### 12.7 Surface OUR OWN biases

The two Claudes have biases. They probably:
- Over-fit to recent trades (recency bias)
- Over-trust well-formatted JSON outputs
- Under-weight outlier scenarios
- Anchor on the previous decision

We should explicitly check for these.

---

## Part 13: Highest-impact additions, ranked

If I could only add 5 things this month, in this order:

### 1. Outcome callback wiring (Part 1 finding, but central)
Without this, the bot is not LEARNING. Everything else is at most "more inputs to a frozen brain."

### 2. Funding rate + OI features in Trade Agent prompt
We just shipped the data layer. Now USE it. Expected impact: catching crowded trades before they unwind.

### 3. Time-of-day / session features
FREE to add (clock arithmetic). Many edges are session-specific. We should be aware of which session we're in.

### 4. Hypothesis pipeline (Part 11.1)
Build the perpetual edge-discovery engine. This is the highest-leverage thing we can build because it generates 30+ future ideas/month while we sleep.

### 5. Setup memorization via vector similarity (Part 9.7)
"This BTC chart looks like Feb 14" — a vector search over historical winners. Massive boost to conviction calibration.

These five together would represent a different bot in 30 days.

---

## Part 14: What I want to confirm with Nunu

1. **Vector DB / on-chain data subscriptions** — adding Coinglass or Glassnode or Deribit costs $20-100/month each. Do we have budget for paid data, or constraint to free-only?
2. **Twitter integration** — paid API is now $100/month minimum. Worth it?
3. **Exploration trades** (Part 11.4) — willing to accept some "learning" trades that may underperform but increase data quality?
4. **Frequency of architectural reviews** — monthly enough, or more often?
5. **Symbol expansion** — comfortable with adding DOGE, AVAX, LINK to the active universe?

---

## Part 15: Updated priority message for laptop

After this expansion, here's the consolidated priority message:

### Tier 1 (this week)
1. Wire all outcome callbacks (Part 1 + 2 both agree this is #1)
2. Codebase audit: dead vs live agents (Part 1)
3. Re-run veto/edge analyses at corrected fees (Part 1)
4. Strategy weight evolution check (Part 1)
5. Time-of-day / session features in agent context (Part 2.9.4) — FREE add
6. Funding rate + OI integration into Trade Agent prompt (Part 2.9.3 + 10.1)

### Tier 2 (next 2 weeks)
7. Decision cache (Lever 1)
8. Hypothesis pipeline skeleton (Part 11.1) — start with daily hypothesis generation, no testing yet
9. Adversarial pre-trade check (Part 9.10) — map stop clusters before placing stops
10. Scout output consumption (Part 10.1) — wire scout watchlists to Trade Agent context
11. Vol-adaptive trailing
12. Regime-aware time stop

### Tier 3 (next month)
13. Cross-venue basis (Binance vs HL)
14. BTC dominance + DXY features
15. Setup memorization (vector similarity)
16. Bayesian belief updating
17. Add DOGE + AVAX symbols

### Tier 4 (long-term)
18. Twitter sentiment (if budget)
19. On-chain whale tracking (if budget)
20. Red team agent
21. Curiosity-driven exploration trades

---

## Final final note

The biggest danger right now is not lack of ideas. It's **building 20 more features on top of a brain that isn't learning from the outcomes.** That's why outcome callbacks remain #1.

Once the brain is learning, every feature we add multiplies the rate of improvement. Until then, we're stacking inputs to a frozen black box.

Edge exploration is unbounded. But edge CAPTURE requires a learning loop. Wire that first, then go wild.

-- desktop-claude
