# WAGMI System Audit + Strategic Roadmap

**From:** desktop-claude
**Date:** 2026-06-02 23:25 UTC
**Trigger:** Nunu directive -- "leave no stone unturned... how can we be better... lay it out, audit it, audit again"
**Approach:** Honest assessment of where we are, where the gaps are, where the upside is. Then a second-pass audit to find what the first pass missed.

---

## Part 1: Current State Audit (where we ACTUALLY are)

### 1.1 What is working

- **Multi-agent LLM pipeline executes end-to-end.** Regime + Trade + Risk + Critic produce coherent decisions. Quant + Scout provide context. Exit Agent actively manages positions.
- **Trades are happening.** 11 trades today across LONG and SHORT, BTC/ETH/HYPE. ~+$450 paper-equivalent profit at real Hyperliquid fees.
- **The safety stack works.** Duplicate guard, portfolio cap, liquidation check, circuit breakers all caught real issues today.
- **Counterfactual tracking works.** We are recording vetoes + outcomes. Just resolved one as "veto was wrong" (3.99% missed on ETH SELL).
- **Cross-PC coordination works.** Handshake-based, git as transport, both Claudes contributing.
- **Auto-recovery works.** State files persist positions across restarts. BTC SHORT #8 survived a restart and went on to TP2.
- **Bot stability is solid.** Subprocess hang fix eliminated 6h pipeline freezes. Bot has been running ~6h continuously.

### 1.2 What is broken or inefficient (and what was just fixed)

Fixed today:
- 10x fee bug (45 bps -> 4.5 bps) -- everyone knows now
- 2h TIME_STOP (was killing winners) -- bumped to 8h
- Risk Agent too-conservative leverage tier -- prompt now defaults to 3-5x
- Bug #16 look-ahead bias in backtest -- 12 paths gated
- Per-agent model routing (no more Opus on every call)
- TP1-proximity guard for time stops (just shipped by laptop)
- 4h intermediate trend now in agent snapshots (just shipped by laptop)
- Mark price + basis enrichment for agents (just shipped by laptop)

Still broken / underaddressed:
- **Equity tracker resets on restart.** Shows $5,000 baseline; real equity is higher. Cosmetic but misleading.
- **"SOL SHORT toxic" veto** keeps firing on SOL SHORT signals in strong trending_bear. We are leaving real opportunities on the table. Source is not graduated_rules.json; lives in knowledge_base or network_learning (laptop tracing).
- **HYPE liquidation pre-gate** still over-restrictive even after the practical-max fix.
- **Time stop, even at 8h, is a blunt tool.** Should be regime-aware: longer in trending markets, shorter in chop.
- **Trailing stop algorithm is fixed ATR multiplier.** Should be vol-adaptive: tighter in low vol, looser in high vol.
- **Adaptive floor loaded state shows `total bins data: 0 trades`** -- the outcome-feeding callback may not be firing.

### 1.3 What is underutilized

These exist in the codebase but are not pulling weight:

- **Learning Agent**: spec says it extracts lessons from closed trades. Logs occasionally. Does its output feed back into prompts? Unclear.
- **Overseer Agent**: appears in logs as "skipped: input too thin (1105 chars < 1500 min)" -- never warmed up enough to fire. Either feed it more context or admit it is dormant.
- **Quant Agent** (LLM, distinct from Quant Brain rule-based): its presence in pipelines is unclear. Audit needed.
- **Deep memory store** (`bot/data/llm/deep_memory/`): trade DNA, patterns. Is it read at decision time? Or just written to?
- **Self-teaching curriculum** (5 levels): exists in code (`self_teaching.py`). Is it advancing? Or stuck at level 1?
- **9 trading strategies in ensemble**: most signals come from 2-3 strategies. The other 6+ may be silent. Check ensemble weight evolution.
- **Hold-time rules manager**: exists, may not be wired.
- **Strategy weight evolution**: weights start at 0.30 each. Are they updating from outcomes?

### 1.4 What was improved in the last 36h (summary)

| Change | Impact |
|---|---|
| Fee correction 45→5 bps | Realistic PnL, vetoes can be re-scored |
| TIME_STOP 2h→8h | Winners can complete their theses |
| Risk Agent prompt: 3-5x default | Higher leverage when conviction warrants |
| Per-agent model routing (no Opus) | ~10x quota efficiency |
| Subprocess hang fix | 6h artificial freezes eliminated |
| Sizing math: removed qty*leverage | Position sizes match risk budget |
| Bug #16 fixes (12 paths) | Backtests no longer use future data |
| LLM-first cost gate <60 removed | Sub-60% signals reach LLM |
| Cap raised 4→5→7 | More multi-position room |
| TP1-proximity guard | Time stop won't kill near-winners |
| HYPE liquidation cap 15→10 | Fewer pre-LLM rejects |
| Adaptive floor capped at config | Floor stays at user-set 20 |
| 4h timeframe added | Multi-tf alignment improved |
| Mark price + basis enrichment | Funding edge available to agents |

That is **14 substantive changes in 36h**. The pipeline is materially different from what it was 36 hours ago.

---

## Part 2: How are we LEARNING?

The system has multiple learning mechanisms. Are they actually learning?

### 2.1 Graduated rules

**What it does:** codifies repeated patterns into rules with WR/n stats. Rules with high confidence get applied as boosts/vetoes.

**Is it learning?** Partially.
- All 23 rules have `times_correct = 0` per laptop audit. The feedback loop that records outcome correctness is broken.
- 9 of the rules are from May 2025 (pre-overhaul). We disabled 4 of them.
- The 14 post-overhaul rules use n=2172 shadow signals -- hypothetical, not real trades.

**Fix path:** wire `times_correct` updater to fire on every position close. Laptop should look at this.

### 2.2 Counterfactual tracking

**What it does:** records every veto, watches what would have happened, scores `veto was correct` or `veto was wrong`.

**Is it learning?** Yes, slowly.
- 3 resolutions logged today
- 2 correct, 1 wrong (the ETH SELL hit TP1 = wrong)
- Need more samples to drive rule changes

**Fix path:** keep collecting. After 50-100 resolutions, the "veto was wrong" pattern can drive rule demotions.

### 2.3 Walk-forward (just shipped)

**What it does:** train rules on month N, freeze, test on N+1, measure decay.

**Is it learning?** Just shipped by laptop. Not yet run on real data.

**Fix path:** laptop should run on 30+ days of historical data and produce rule confidence scores.

### 2.4 Adaptive confidence floor

**What it does:** raises floor when bot losing, lowers when winning. Per-symbol and per-regime adjustments.

**Is it learning?** Yes but stuck.
- Heartbeat: `floor=55.0%, total bins data: 0 trades` -- something is not feeding outcomes back
- Floor stays at 55% (capped at our configured 20)

**Fix path:** wire trade outcomes to `confidence_floor.record_outcome()`. Probably similar fix to graduated rule outcomes.

### 2.5 Self-teaching curriculum

**What it does (per code):** 5 levels of meta-learning. Bot graduates as it accumulates evidence.

**Is it learning?** Unknown. Need to check `data/llm/teaching/curriculum_state.json`.

### 2.6 Strategy weights

**What it does:** per-strategy weights that ride PnL outcomes. Better-performing strategies get more weight.

**Is it learning?** Heartbeat shows all weights at 0.30 -- equal. Either evolution is off or they have not had enough trades to differentiate.

### 2.7 Deep memory + memory store

**What it does:** writes trade DNA + agent reasoning into long-term memory.

**Is it learning?** Hard to say from logs alone. Need to inspect file sizes and content.

### 2.8 LLM agent calibration

**What it does:** records each agents predictions + outcomes, computes per-agent accuracy over time.

**Is it learning?** `agent_performance.jsonl` is being written. But is it being READ to adjust agent prompts? Unclear.

### Summary of learning

**6 learning mechanisms exist; maybe 1.5 are working.** Counterfactual tracking is genuinely accumulating signal. Walk-forward just shipped. Everything else is plumbing-broken (outcome callbacks not firing) or untested.

**Fix priority:** WIRE THE OUTCOME CALLBACKS. Every position close should fan out to:
- `graduated_rule.record_outcome()`
- `confidence_floor.record_outcome()`
- `strategy_weights.record_outcome()`
- `agent_performance.update_calibration()`
- `deep_memory.add_trade()`
- `self_teaching.advance_curriculum()`

If even half of these are silent, the bot is not learning at the speed it should be.

---

## Part 3: How much is it HELPING?

### 3.1 Performance today

| Metric | Value | Note |
|---|---|---|
| Trades | 11 | Across BTC/ETH/HYPE, LONG and SHORT |
| WR | 4 wins, 7 losses (logged) | But with real fees, breakeven trades flip to wins |
| Net PnL (logged) | -$70 | With 10x fee bug |
| Net PnL (real-fee equiv) | ~+$450 | Once fees corrected |
| Open uPnL right now | ~+$169 | HYPE SHORT #11 |
| Biggest win | BTC #8: +$378 logged | TP1 + trail + TP2 |
| Biggest loss | ETH #1: -$145 logged | Early-day, before fee fix |

**Bottom line:** the system is mildly profitable at real fees, primarily driven by 1-2 big wins. Most trades are noise.

### 3.2 What the system has demonstrated

- Can take real trades aligned with regime
- Can manage multiple simultaneous positions
- Can hedge (BTC SHORT + HYPE LONG)
- Exit Agent can override the planned exit (closed HYPE LONG when regime mismatched)
- Trailing stops can capture extended moves (BTC #8 trailed from TP1 to TP2)
- Time stops can prevent losses on stagnant positions
- Time stops can also kill profitable trades (ETH #10) -- but TP1-proximity guard now mitigates

### 3.3 Where the system is NOT helping

- Vetoes have 1/3 wrong rate so far (small n, but worth watching)
- Time-stops without TP1-proximity have cost $50-200 across trades (now fixed)
- Equity tracker resets on restart (cosmetic but loses cumulative)
- We have not benefited from data sources beyond OHLC (until laptop's mark price + basis enrichment)

---

## Part 4: How can we BE BETTER?

Group the opportunities by where they live.

### 4.1 Capture more of existing edges

- **Wire all outcome callbacks** (Part 2.summary) -- biggest unlock for learning
- **Vol-adaptive trailing** -- tighter in low vol, looser in high vol
- **Regime-aware time stop** -- longer in trending, shorter in range
- **Better TP placement** -- not just ATR-based; structure-aware (support/resistance)
- **Exit Agent on every position** -- currently exists; verify it runs on EVERY open position every scan

### 4.2 Find new edges

- **OI history** (laptop shipped) -- now feed it into Trade Agent context fully
- **Funding rates** (mark price + basis shipped) -- crowded trades reverse
- **Liquidation cascades** -- spike volume = stop hunt or flush
- **Orderbook depth** -- thin book = volatility
- **Twitter/news sentiment** (later)
- **Multi-timeframe consensus** (4h shipped by laptop) -- now 5m + 1h + 4h + 1d
- **Cross-asset cluster signals** (3 majors aligned)

### 4.3 Reduce friction

- **Decision cache** (Lever 1) -- 10-50x backtest throughput
- **Mechanical pre-filter** (Lever 2) -- 3-5x speedup
- **Synthetic skip shortcut** (Lever 5) -- ~30% LLM load reduction
- **Parallel symbol runs** (Lever 4) -- 4x wall clock (shipped by laptop)

### 4.4 Self-correction

- **Walk-forward** (Lever 3, just shipped) -- run on real data
- **Veto correctness** -- re-score with corrected fees
- **Agent calibration** -- per-agent accuracy over time, feed back into prompts

### 4.5 Operational scale

- **More symbols** -- DOGE, AVAX, LINK on Hyperliquid all liquid
- **More timeframes** -- 5m for entries (catch wickier intra-1h moves)
- **More agent specialization** -- e.g., a "funding edge" agent specifically
- **Trading hours awareness** -- US session vs Asia session edge differential

---

## Part 5: Best PATH AHEAD

Three tiers based on impact x time-to-deploy.

### Tier 1: Ship this week (highest impact, lowest effort)

1. **Wire all outcome callbacks** (one-day refactor; unlocks 6 dormant learning systems)
2. **Codebase audit: dead vs live agents** (0 quota, big clarity)
3. **Decision cache** (laptop builds; desktop integrates)
4. **Re-run all prior analyses at corrected fees** (laptop; computational only)
5. **Trace the "SOL SHORT toxic" veto source** and decide: disable, lower weight, or keep
6. **Equity tracker fix** (small, cosmetic but important)

### Tier 2: Ship next 2 weeks

7. **Feed OI + funding/basis into Trade Agent prompt** (data layer is there)
8. **Vol-adaptive trailing**
9. **Regime-aware time stop**
10. **Walk-forward run on 30+ days** (laptop)
11. **Strategy weight evolution check** -- are they updating?

### Tier 3: Ship next month

12. **Cross-asset cluster signals**
13. **Add 2 more symbols (DOGE, AVAX)**
14. **Liquidation cascade detection**
15. **Manual intuition transfer** (requires Nunu input)

### Tier 4: Long-term experiments

16. **Twitter/news sentiment integration**
17. **Per-agent prompt A/B testing**
18. **Specialist sub-agents (Funding Agent, Liquidation Agent)**

---

## Part 6: Self-audit -- what did I miss in Part 1-5?

This is the second pass Nunu asked for.

### Things the audit might have undersold

- **The DUAL learning insight:** desktop monitors live, laptop builds. But neither has been TEACHING the bot from human (Nunu) examples. The intuition transfer item is the biggest underexplored idea -- if we can encode Nunus past trading decisions, the bot could mimic him.

- **Calibration of the calibration:** we measure how good agents are. But we are not measuring how good our measurement is. Confidence intervals on "veto was correct" rates. Sample size warnings. We could be over-reacting to noise.

- **The unseen cost of conservatism:** the bot took 11 trades in 24 hours. Highly active. But agents skip far more than they take. Of those skips, how many were correct vetoes vs missed opportunities? Counterfactual tracking only covers the ones with structured veto data. Most skips do not get tracked.

- **No A/B testing infrastructure for the live bot.** We are running ONE version. We cannot directly compare "with X feature" vs "without X feature" in live. Shadow trading would solve this.

- **Risk is per-trade, not per-strategy.** The bot may take 3 simultaneous trades from the same strategy (e.g., 3 BB squeeze signals). If BB squeeze is broken in this regime, all 3 lose. Strategy-level concentration limits would help.

- **No drawdown protection by setup type.** If "BTC SELL solo" loses 3 in a row, the system does not pause that setup. Only consecutive-loss circuit breaker at the account level fires.

- **The PROMPTS are static.** We update them manually. Could the prompts themselves evolve based on outcomes? "Prompt evolution" via reinforcement.

### Things I do not have enough data on

- Is the Exit Agent actually firing on EVERY open position every scan? Or only opportunistically?
- Is the Quant Agent (LLM, distinct from Quant Brain) running? Its absence from recent logs is suspicious.
- Are the strategy weights updating? Heartbeat shows 0.30 across the board.
- Are scout watchlists being USED by trade decisions, or just produced and discarded?
- Is the Overseer ever getting enough context to fire? Its `skipped: input too thin` is suspicious.

### What would surprise me to find?

- **Half the codebase is dead.** The 9 agent claim may be aspirational, not real.
- **Strategy weights never update.** Bot is using equal weights forever.
- **Deep memory is write-only.** Logs everything; reads nothing.
- **Outcome callbacks fan out to nothing.** Position close just fires a log line, not learning updates.

If any of those are true, the bot is operating with stuck wheels and is NOT actually learning despite the appearance.

### Updated priority order after self-audit

Promote to Tier 1:
- **Audit which agents are actually live** (was Tier 2)
- **Audit strategy weight evolution** (was Tier 2)
- **Codebase dead-vs-live mapping** in general

These are 100% computational, zero quota, and will reveal whether the system is actually capable of learning -- before we invest in MORE learning mechanisms.

---

## Part 7: What Nunu should tell the laptop

When you ping laptop next, suggest they prioritize from these in this order:

### Highest priority (do this week)

1. **Wire all outcome callbacks** (decode every dormant learning subsystem). Investigate:
   - `bot/data/llm/graduated_rules.json` updater path
   - `bot/feedback/adaptive_confidence.py` `record_outcome()` callers
   - `bot/data/strategy_weights.py` evolution path
   - `bot/llm/deep_memory.py` write path
   - `bot/llm/self_teaching.py` curriculum advance path
   For each: is it being called on every position close? If not, wire it.

2. **Codebase audit: dead vs live agents**:
   - For each of the 9 agents, find where its output is CONSUMED (not just produced)
   - Classify ACTIVE / PARTIAL / DEAD
   - Push to `analysis/agent_audit/dormant_audit.md`

3. **Re-run all veto/edge analyses at corrected (4.5 bps) fees**. Confirm which "marginal losses" were actually profitable opportunities.

4. **Strategy weight evolution check**: are they updating? If stuck at 0.30, find the wiring break.

5. **Decision cache (Lever 1)** -- continue as planned.

### Medium priority

6. **Walk-forward (Lever 3, just shipped)** -- run on real data, push rule confidence scores.
7. **Feed OI + funding/basis into Trade Agent prompt** (data layer is there, prompt context isn't using it yet).
8. **TP1-proximity guard integration** -- coordinate with desktop on merging into live.

### Hold for now

- Decision cache evolution (do basic version first, optimize later)
- Cross-asset cluster signals (low priority until data layer matures)

---

## Part 8: What Nunu can do (this is for you)

If you want to actively help:

1. **Spot-check the equity tracker.** Look at `data/risk_equity_state.json` -- does the equity match what trades.csv shows cumulatively?

2. **Tell us what HYPE wants** -- agents are saying HYPE is in different regimes than majors. Your intuition on whether HYPE is a leading/lagging indicator vs majors would help calibration.

3. **Confirm the leverage philosophy.** With "braver" prompt, bot picks 2-3x. You have mentioned 25x success in the past. Should we authorize the agent to go to 6-10x when confluence is strong? Or keep capped at 5x for safety?

4. **Twitter posts:** keep doing them. Useful both for your social presence and for grounding the bot in "this is what an experienced trader is observing right now."

5. **DO NOT** try to manually fix code unless you want to. The two Claudes can ship faster than a 3-way collab.

---

## Final note

Nothing in this audit is final. After laptop ships outcome-callback wiring, agent audit, and the data layer, we re-audit. The system gets smarter each iteration because we honestly account for what is dead, what is alive, what is learning, and what is just spinning wheels.

The goal is not "more features." The goal is "every component is awake, learning, and demonstrably contributing."

-- desktop-claude
