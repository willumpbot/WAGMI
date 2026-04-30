# Dormant Agents Audit — 2026-04-29

**Question:** the `AgentRole` enum defines 23 agent roles, but the live pipeline calls only 9. What state are the other 14 in — stubs, partial implementations, or done-but-unwired?

**Headline:** **all 13 of the surveyed dormant agents are *fully implemented* but have zero external call sites.** ~1,100 lines of agent code (strategic_agents.py, phase_4_agents.py, phase_4a_trading_agents.py) plus 13 prompts in prompts.py are written, integrated into the coordinator with `get_*` accessor methods, exposed via `AgentConfig` defaults — and **never invoked by the trading loop.**

This is the third major "writes-only, no read path" pattern in the codebase, after graduated_rules (§7.7) and SwarmFeedbackLoop (§08). Bigger in surface area than either.

---

## Inventory

### Active (9, called from coordinator pipeline)

| Role | Where called | Status |
|---|---|---|
| REGIME | coordinator.py:702 | ✅ |
| TRADE | coordinator.py:889 | ✅ |
| RISK | coordinator.py:912 | ✅ |
| CRITIC | coordinator.py:927 | ✅ |
| LEARNING | coordinator.py:1710 (post-trade) | ✅ |
| EXIT | coordinator.py via get_exit_intelligence | ✅ |
| SCOUT | coordinator.py:2076 (idle) | ✅ |
| OVERSEER | coordinator.py:2181 (periodic) | ✅ |
| QUANT | coordinator.py:784 (tier 3 only) | ✅ |

### Dormant (13, all complete but unwired)

| Role | Implementation | get_* method | External callers |
|---|---|---|---|
| PORTFOLIO | `strategic_agents.py:build_portfolio_aggregator` | `get_portfolio_intelligence` | **0** |
| FORECASTER | `strategic_agents.py:build_regime_forecaster` | `get_regime_forecast` | **0** |
| HYPOTHESIS | `strategic_agents.py:build_hypothesis_generator` | `get_novel_hypotheses` | **0** |
| CORRELATOR | `strategic_agents.py:build_correlator` | `get_correlator_analysis` | **0** |
| MICRO_TREND | `phase_4_agents.py:build_micro_trend_detector` | `get_micro_trend` | **0** |
| SCALPER | `phase_4_agents.py:build_scalper` | `get_scalp_signal` | **0** |
| CONVICTION | `phase_4_agents.py:build_conviction` | `get_conviction_analysis` | **0** |
| POSITION_SIZER | `phase_4a_trading_agents.py:build_position_sizer` | `get_position_size` | **0** |
| ENTRY_OPTIMIZER | `phase_4a_trading_agents.py:build_entry_optimizer` | `get_entry_optimization` | **0** |
| EXIT_ADVISOR | `phase_4a_trading_agents.py:build_exit_advisor` | `get_exit_advice` | **0** |
| RISK_GUARD | `phase_4a_trading_agents.py:build_risk_guard` | `get_risk_guard_check` | **0** |
| AGENT_ROUTER | `phase_4a_trading_agents.py:build_agent_router` | `get_routing_decision` | **0** |
| CONSENSUS_BUILDER | `phase_4a_trading_agents.py:build_consensus_builder` | `get_consensus` | **0** |
| OVERRIDE | (used internally by coordinator only) | — | — |

For each dormant role: prompt exists in prompts.py, AgentConfig in base.py, builder function imported in coordinator.py, get_* accessor method exposed... and zero callers from `multi_strategy_main.py`, `cli.py`, or anywhere else live.

Verified via:
```
$ grep -rn "\.get_portfolio_intelligence\b\|\.get_regime_forecast\b\|...all 13..." \
    bot/ --include="*.py" | grep -v test_ | grep -v coordinator.py
(empty for every one)
```

---

## What Each Was Designed To Do (per their prompts)

Reading the prompt headers in `prompts.py`:

| Agent | Role per prompt | Trigger frequency |
|---|---|---|
| Portfolio | "Holistic portfolio health, not individual trades" | Daily |
| Forecaster | "Predict regime TRANSITIONS before they happen" | Daily |
| Hypothesis | "Discover NEW trading patterns and edges NOT YET CODED" | Weekly |
| Correlator | "Cross-asset relationships and lead-lag patterns" | Daily |
| Micro-Trend | "5m candle context for the Scalper Agent" | Per 5m candle |
| Scalper | "1-3 minute trading opportunities" | Per 1m candle |
| Conviction | "Authorize 2.5x leverage trades when ALL agents align" | Per high-stakes signal |
| Position Sizer | "Determine the exact position size in USD" | Per trade entry |
| Entry Optimizer | "Decide HOW to enter (timing + method)" | Per trade entry |
| Exit Advisor | "Monitor and recommend exits" | Per open position |
| Risk Guard | "Prevent catastrophic losses" | Per trade entry |
| Agent Router | "Decide which specialist agents to call" | Per pipeline run |
| Consensus Builder | "Final arbiter merging specialist outputs into one decision" | Per pipeline run |

**These represent significant trading-system upgrades, not redundant duplicates of existing agents.** Examples:

- **Forecaster** would catch regime transitions early — directly addresses the "December 2025 chop killed us" failure pattern flagged in earlier blueprint analysis.
- **Position Sizer + Risk Guard + Conviction** form a 3-tier sizing/safety stack designed for high-leverage authorization.
- **Agent Router + Consensus Builder** would replace the hardcoded coordinator pipeline with a dynamic orchestrator.
- **Hypothesis** would generate net-new alpha proposals weekly.

The fact that none are wired means a substantial chunk of the project's design surface is sitting on the shelf.

---

## Why This Likely Happened (hypothesis)

Looking at file naming (`strategic_agents.py`, `phase_4_agents.py`, `phase_4a_trading_agents.py`), this is a phased architecture that was built ahead of the wiring. The pattern probably went:

1. Design the phase (e.g., Phase 4A: Core Trading Agents)
2. Write all 6 agent prompts + builders
3. Add `get_*` accessor methods to coordinator
4. Expose `AgentRole` enum entries
5. **Never close the loop by adding the runtime call sites**

Then onto the next phase. Each phase was 80% complete in code, 0% complete in wiring.

This is a different failure mode than §7.7/swarm: those write data nobody reads. **Dormant agents are functions nobody calls.** Same end state — dead code — but different fix.

---

## Recommended Wiring Plan

Don't wire them all at once. Pick the highest-EV one or two first, validate, then add more. Suggested order:

### Tier 1 (high EV, low risk to wire)

1. **Forecaster** (~2h) — runs daily, output is informational (no execution effect). Add to a daily cron in `multi_strategy_main.py` that calls `coordinator.get_regime_forecast()` and stores result. Display in `/live` calibration strip ("regime forecast 4h: trending 0.6").
2. **Portfolio Aggregator** (~2h) — same pattern, daily, output displayed in `/status` page as "Portfolio Health" section.
3. **Correlator** (~2h) — daily output, fed into BTC lead-lag inputs that the existing strategies already consume.

These are read-only / informational. Wiring them adds value without changing trading behavior. Total: ~6 hours.

### Tier 2 (touches sizing/entry — needs careful testing)

4. **Position Sizer** (~3h) — replaces the existing sizing math with LLM-suggested size. Needs A/B gate (try LLM size on 20% of trades, compare to baseline).
5. **Entry Optimizer** (~3h) — adjusts entry price/timing. Same A/B gate pattern.
6. **Risk Guard** (~3h) — final safety check before entry. Lower risk if it can only veto, never approve.

Total: ~9 hours. Each one needs paper-trading validation before touching live.

### Tier 3 (architectural changes — defer)

7. **Agent Router + Consensus Builder** — these would replace the hardcoded coordinator pipeline. Big architectural change. Defer until Tier 1+2 prove the agents earn their token cost.
8. **Scalper + Micro-Trend** — only valuable if you want to add a high-frequency strategy. Different time horizon than current bot. Defer unless you choose to add scalping as a new strategy direction.
9. **Conviction** — for high-leverage authorization. Defer until you have a real reason to take >2x leverage trades systematically.
10. **Hypothesis** — weekly novel-pattern generator. High-cost (Opus tier). Defer until budget supports it.

---

## What This Audit Doesn't Tell Us

- **Whether the prompts themselves are good.** I read the headers; the bodies could have issues. A separate prompt-quality pass is worth doing before wiring (`/prompt-calibrate` skill from CLAUDE.md is exactly this).
- **What dependencies each builder function expects.** Some may need new context fields in `snapshot_data` that aren't currently populated. Best discovered by trying to wire one (start with Forecaster).
- **Whether the get_* accessor signatures are stable.** If they need extra params to actually run, the wiring is more than just "call this method."

---

## Decision To Make Before Wiring

**Cost question.** With 13 dormant agents, fully wired and running at their designed frequencies, monthly LLM cost would jump significantly:

- Daily agents (Portfolio, Forecaster, Correlator): 4 calls/day × ~$0.005 each = ~$0.60/month total
- Weekly Hypothesis: 4 calls/month × ~$0.05 = $0.20/month
- Per-signal agents (Position Sizer, Entry Optimizer, Risk Guard): 3 × 100 signals/month × ~$0.005 = $1.50/month
- High-frequency (Scalper + Micro-Trend at 1m candles): 60 × 24 × 30 × $0.001 = ~$43/month
- Conviction (rare, ~10/month): negligible

Tier 1+2 (informational + entry/sizing): **~$3/month additional spend.** Easily justified if any of them adds even modest edge.

Tier 3 high-frequency: **~$45/month** for scalper alone. Probably not justified until paper-validated.

---

## Concrete Next Action

If you want one cheap, high-information win to start: **wire Forecaster**.

1. In `multi_strategy_main.py`, add a daily check (`if self._tick % (60 * 24) == 0`) that calls `self.coordinator.get_regime_forecast()`.
2. Save result to `data/llm/regime_forecast.json` with timestamp.
3. Add a new endpoint `/v1/regime/forecast` to `bot/api_server.py` that reads it.
4. Display in `/live` calibration strip: "regime forecast 4h: trending 0.6 / range 0.3 / panic 0.1".

Total: ~2 hours. Starts generating real data the moment the bot resumes. Zero impact on trading behavior. If the forecaster is accurate, it becomes the foundation for trend-flip early warnings.
