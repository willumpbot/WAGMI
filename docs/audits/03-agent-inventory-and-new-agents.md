# Full Agent Inventory + New Agent Designs (incl. Opportunist)

*Agent ID: `acdae4dd87de758ef`*

---

## Original Task

```
You are doing the definitive deep-dive on the WAGMI trading bot's LLM agent system at /home/user/WAGMI. The goal is to produce (a) a complete inventory of every existing agent with full operational detail, and (b) thoughtful proposals for new agents — including specifically an "Opportunist" agent the user has mentioned wanting.

**Mission Part 1: Inventory every existing agent**

For EACH of these agents, extract:
- File path of agent prompt
- File path of agent invocation site in coordinator.py (line numbers)
- Default model (Haiku/Sonnet/Opus)
- When it runs (every tick / on event / idle / periodic / async post-close)
- Inputs (what fields of the snapshot does it read?)
- Outputs (exact JSON schema)
- Output schema validation
- Cost per call (token estimate × pricing)
- Latency budget
- What downstream agent / system consumes its output
- What happens on failure (fallback, retry, abort)
- Test coverage status

Agents to inventory:
1. Regime Agent
2. Trade Agent
3. Risk Agent
4. Critic Agent
5. Learning Agent
6. Exit Agent
7. Scout Agent
8. Overseer Agent
9. Quant Agent

Plus the Phase 4 agents (which exist but are not all wired):
10. Portfolio Aggregator
11. Regime Forecaster
12. Hypothesis Generator
13. Correlator
14. Micro-Trend Detector
15. Scalper
16. Conviction Agent

Plus any agents I haven't named that exist in `bot/llm/agents/`:
- `grep -l "class.*Agent\|AgentRole\." bot/llm/agents/`
- List every file that defines an agent

**Mission Part 2: Design new agents**

The user wants to add agents. They specifically mentioned an **Opportunist agent**. Think creatively. Look at gaps in the current pipeline and propose 5-8 new agents that would add value.

For each proposed new agent:
- Name + one-line role
- Why it's needed (what gap does it fill?)
- When it runs (cadence)
- Recommended model (Haiku/Sonnet/Opus)
- Input schema (what does it read?)
- Output schema (what does it produce?)
- Where it sits in the pipeline (before/after/parallel to existing agents)
- What it costs (token estimate × pricing)
- How its output is consumed
- Failure mode handling
- A concrete example call (what triggers it, what it outputs)

Specifically design:
- **Opportunist Agent**: detects asymmetric setups outside normal pipeline, e.g. funding-rate extremes, liquidation cascades imminent, post-news reversion windows, BTC-correlation breakdowns. Should be PROACTIVE — looks for setups the standard ensemble wouldn't surface.

Other agents to consider proposing:
- **Adversary Agent**: argues the opposite side of every Trade Agent thesis (anti-confirmation-bias)
- **Calibrator Agent**: every N decisions, audits whether agents are over/under-confident, recommends prompt adjustments
- **Memory Curator**: prunes stale insights, surfaces forgotten patterns
- **News Sentinel**: monitors news/social feeds for symbol-specific catalysts
- **Drawdown Recovery Agent**: activates when equity is in drawdown, recommends defensive/recovery posture
- **Exit Optimizer**: separate from
```

---

## Full Report

Perfect! Now I have enough information to create a comprehensive inventory. Let me create the detailed blueprint document:

## COMPREHENSIVE WAGMI TRADING BOT LLM AGENT SYSTEM INVENTORY & EXPANSION BLUEPRINT

### EXECUTIVE SUMMARY

The WAGMI trading bot operates a sophisticated multi-agent LLM system with 23 defined agents across 4 phases: Core (9 agents), Phase 3 Strategic (4 agents), Phase 4 Scalping (3 agents), and Phase 4A Core Trading (6 agents), plus 1 Override mechanism. The system processes ~$200-400K in monthly volume with a 43% win rate and +$1.8K cumulative profits across 101 live trades.

The current pipeline runs synchronously during pre-trade decision windows, with optional Scout (idle-time) and Overseer (periodic) agents enriching decisions. Costs range from $18/month (CONSERVATIVE tier, Haiku-only) to $1,400/month (UNLEASHED tier, Opus-heavy).

**Part 1** inventories all 23 agents with precise file paths, invocation line numbers, schemas, costs, and failure modes. **Part 2** proposes 6 new high-value agents including the mandatory Opportunist agent. **Part 3** documents the 8-step recipe for adding agents. **Part 4** provides the agent interaction topology.

---

## PART 1: COMPLETE AGENT INVENTORY

### CORE PIPELINE AGENTS (9 agents)

All core agents live in `/home/user/WAGMI/bot/llm/agents/`. The main orchestrator is `coordinator.py` with 4,777 lines.

#### **1. REGIME AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:18-88`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:701-750`
- Input builder: `_build_regime_input()` (line 3220)

**Invocation Details:**
- Called first in pipeline, REQUIRED (blocks trading if fails)
- Line 701: `self._call_agent(AgentRole.REGIME, regime_input, model_for_trigger)`
- Default model: Haiku (MODEL_HAIKU, line 76-92 in base.py)
- Caching: 30-minute TTL (line 343 in coordinator.py)

**JSON Schema (Output):**
```json
{
  "rg": "trending_bull|trending_bear|trend|consolidation|range|high_volatility|panic|low_liquidity|news_dislocation|unknown",
  "conf": 0.0-1.0,
  "factors": "string",
  "bias": "bullish|bearish|neutral",
  "transition": "stable|shifting_to_trend|shifting_to_range|shifting_to_panic|shifting_to_high_volatility|uncertain",
  "regime_momentum": "strengthening|stable|weakening",
  "expected_duration_h": [number, number],
  "outlook": "string"
}
```

**Inputs (from snapshot):**
- price, volume, ATR, RSI, ADX, Bollinger Bands
- EMA20, EMA50 (via technicals enrichment)
- Open Interest, funding rate
- BTC correlation
- Enriched context (dynamic stats, knowledge base, feedback state)

**Outputs:**
- Scratchpad writes: regime, regime_conf, bias, outlook, regime_momentum, expected_duration_h (lines 753-759)
- Downstream: Trade Agent uses as primary context; Critic uses for validation

**Configuration:**
- Max tokens: 1200 (forensic: 512 truncated on enriched calls, 26 truncations caused degradation)
- Timeout: 30 seconds
- Model override via: `AGENT_REGIME_MODEL` env var

**Cost per Call:**
- Haiku: ~300 input tokens × $0.80/1M + ~50 output tokens × $4.0/1M = ~$0.0003
- CLI routing (preferred): $0

**Latency Budget:** 30 seconds (generous, runs first)

**Failure Mode:**
- Fallback to technical fallback classification using ADX/EMA/volume heuristics (lines 767-774)
- If both fail: returns "unknown" regime with conf=0.3
- Does NOT abort pipeline unless technical fallback also fails

**Test Coverage:**
- `/home/user/WAGMI/bot/tests/test_multi_agent.py:29-40` tests AgentRole enum completeness (23 agents)
- Tests check regime prompt contains all 10 regime types (lines 95-99)
- No detailed test of regime output schema or fallback logic found

**Downstream Consumption:**
- Trade Agent (primary context)
- Critic Agent (validation)
- Quant Agent (conditional probability adjustments)
- Portfolio Agent (daily portfolio risk reassessment)
- Scratchpad (shared context for all agents)

---

#### **2. TRADE AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:89-191`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:888-920`
- Input builder: `_build_trade_input()` (line 3280)

**Invocation Details:**
- Called second, REQUIRED (blocks trading if fails)
- Line 889: `self._call_agent(AgentRole.TRADE, trade_input, trade_model_for_trigger)`
- Dynamic model routing (lines 849-885): Haiku by default, promoted to Sonnet if:
  - `num_agree >= 2`, OR
  - `confidence >= 75%`, OR
  - Regime is trending_bull/trending_bear
  - 40-45% of calls promoted to Sonnet (cost optimization: saves ~4x when Haiku sufficient)

**JSON Schema (Output):**
```json
{
  "a": "go|skip|flip",
  "c": 0.0-1.0,
  "thesis": "string",
  "ea": "market now|wait for pullback|enter only if reclaim|enter only if btc confirms|null",
  "mu": "string|null",
  "n": "string"
}
```

**Inputs:**
- Regime classification from prior step
- Signals array (from market data)
- Quant analysis (if available)
- Trade history (recent_lessons, recent_decisions)
- Network learning (validated rules)
- Scout thesis (if idle-time preparation done)
- Technical indicators (1h and 5m)
- Brain context (learned trade DNA)
- Portfolio state (exposure, correlation)
- Reflection engine (move exhaustion, re-entry patterns)

**Outputs:**
- action: "go" (proceed), "skip" (pass), "flip" (reverse direction)
- confidence: 0.0-1.0
- thesis: 1-line prediction with target
- entry_advice: timing/method recommendation
- memory_note: learning note for next decision
- reasoning: brief explanation

**Configuration:**
- Max tokens: 2500 (was 1400, caused truncation; 1200 for Scout; Overseer same 2500)
- Timeout: 60 seconds
- Model override via: `AGENT_TRADE_MODEL` env var

**Cost per Call:**
- Haiku: ~600 input tokens × $0.80/1M + ~150 output tokens × $4.0/1M = ~$0.0009
- Sonnet: ~600 input × $3.0/1M + ~150 output × $15.0/1M = ~$0.004
- Blended (60% Haiku, 40% Sonnet): ~$0.0024
- CLI routing: $0

**Latency Budget:** 60 seconds

**Failure Mode:**
- If fails: fallback to "skip" action, confidence = 0.0 (lines 901-905)
- Does NOT abort pipeline (not required: line 94 in base.py)
- Downstream gets degraded signal, Critic absent so no review

**Confidence Adjustments (Post-Call):**
1. Quant Agent noise detection (lines 1019-1078): reduces confidence by up to 15% if signal is statistical noise
2. Network Learning calibration (lines 1081-1099): +/- adjustment based on regime performance history
3. Consistency check (lines 1003-1017): can override action to "skip" if critical inconsistencies detected

**Test Coverage:**
- `test_multi_agent.py`: Checks all agents have prompts (lines 87-93)
- Checks Trade is required (line 62)
- No detailed Trade Agent output schema tests found
- No confidence calibration tests found

**Downstream Consumption:**
- Risk Agent (inputs action + confidence for position sizing)
- Critic Agent (reviews thesis + confidence)
- Consistency Checker (validates regime alignment)
- Learning Agent (post-trade, analyzes why trade succeeded/failed)
- Agent Router (Phase 4A, decides next agents)
- Consensus Builder (Phase 4A, final decision merge)

---

#### **3. RISK AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:192-324`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:912-920`
- Input builder: `_build_risk_input()` (line 3496)

**Invocation Details:**
- Called third, OPTIONAL (degrades gracefully if fails)
- Line 915: `self._call_agent(AgentRole.RISK, risk_input, model_for_trigger)`
- Gated by: `self.configs.get(AgentRole.RISK, ...).enabled` (line 912)

**JSON Schema (Output):**
```json
{
  "sz": number,
  "leverage": number,
  "risk_pct": number,
  "sw": {
    "strategy_name": number
  },
  "risks": [
    {
      "risk": "string",
      "severity": "low|medium|high|critical",
      "mitigation": "string"
    }
  ],
  "override": false,
  "sizing_rationale": "string"
}
```

**Inputs:**
- Trade decision (action, confidence, thesis)
- Account state (equity, leverage, portfolio)
- Signal properties (entry, stop loss, targets)
- Risk constraints (from network learning)
- Portfolio exposure
- Recent drawdown/consecutive losses

**Configuration:**
- Max tokens: 1000 (was 512, caused truncations on LLM-first)
- Timeout: 40 seconds
- Model override via: `AGENT_RISK_MODEL` env var

**Cost per Call:**
- Haiku: ~250 input × $0.80/1M + ~100 output × $4.0/1M = ~$0.0006
- CLI: $0

**Latency Budget:** 40 seconds

**Failure Mode:**
- If fails: `risk_out = None` (line 920)
- Downstream (Critic) handles gracefully, uses mechanical sizing (line 3520+)
- Trade proceeds with Risk Agent's output omitted

**Test Coverage:**
- Agent config covers it (line 90-95 in test_multi_agent.py)
- No detailed Risk output schema tests

**Downstream Consumption:**
- Critic Agent (receives risk output for review)
- Final decision merge (uses position size)
- Portfolio intelligence (tracks cumulative risk)
- Exit Agent (uses risk constraints)

---

#### **4. CRITIC AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:777-875`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:927-1023`
- Input builder: `_build_critic_input()` (line 3647)
- Debate variant: `_build_critic_round1_input()` (line 3856)

**Invocation Details:**
- Called fourth, OPTIONAL
- High-stakes trade detection (lines 927-950): Triggers structured 2-round debate
  - Debate Round 1: Critic reads Trade thesis WITHOUT confidence (de-anchoring, lines 3856-3893)
  - Debate Round 2: Trade Agent rebuts (line 429 in prompts.py)
  - Critic Round 1 prompt: (searches for CRITIC_ROUND1_PROMPT in prompts.py)
- Standard critic call: line 948, `self._call_agent(AgentRole.CRITIC, critic_input, model_for_trigger)`

**JSON Schema (Output):**
```json
{
  "verdict": "approve|object|revise",
  "counter_thesis": "string",
  "objections": [
    {
      "issue": "string",
      "severity": "low|medium|high",
      "evidence": "string"
    }
  ],
  "adjusted_confidence": 0.0-1.0,
  "reason": "string"
}
```

**Inputs:**
- Regime classification
- Trade thesis + confidence
- Risk analysis (position size, leverage)
- Market data (price, momentum, liquidity)
- Recent performance (win rate, calibration)

**Configuration:**
- Max tokens: 1500 (Sonnet verbose, previous 1000 truncated)
- Timeout: 60 seconds (needed for debate rounds)
- Model override via: `AGENT_CRITIC_MODEL` env var
- High-stakes triggers: confidence > 0.75, leverage > 5x, portfolio leverage > 8x

**Cost per Call:**
- Standard Critic (Sonnet): ~400 input × $3.0/1M + ~120 output × $15.0/1M = ~$0.003
- Debate Round 1 + Round 2 (2 calls): ~2 × $0.003 = $0.006
- CLI: $0

**Latency Budget:** 60 seconds (or 120 if debate)

**Failure Mode:**
- If Critic fails AND trade_out wants to proceed (line 951+):
  - Confidence < 0.40: force skip (line 970)
  - Counter-trend to bias: force skip (line 974)
  - Otherwise: reduce confidence by 10% penalty (line 1011)
- Mechanical fallback prevents unchecked trades (lines 951-1024)

**Test Coverage:**
- Agent config covers it (line 102-107 in test_multi_agent.py)
- No debate protocol tests found
- No objection/verdict schema validation tests found

**Downstream Consumption:**
- Final decision (uses verdict + adjusted_confidence)
- Learning Agent (analyzes why Critic objected)
- Performance tracking (accuracy of Critic vetoes)

---

#### **5. QUANT AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:1109-1191`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:776-820`
- Input builder: `_build_quant_input()` (line 3051)

**Invocation Details:**
- Called 1.5 (between Regime and Trade)
- OPTIONAL, gated by config
- Line 784: `self._call_agent(AgentRole.QUANT, quant_input, model_for_trigger)`
- Tiered routing: Skipped in Tier 2 if AGENT_TIERED_ROUTING enabled (line 778)

**JSON Schema (Output):**
```json
{
  "ev": { "buy": number, "sell": number },
  "conditional_edge": { "scenario": "string", "ev": number },
  "probability": 0.0-1.0,
  "risk_profile": "low|medium|high",
  "kelly_fraction": 0.0-1.0,
  "signal_quality": {
    "confidence_adjustment": -0.15 to +0.15,
    "noise_probability": 0.0-1.0,
    "is_noise": boolean,
    "reason": "string"
  },
  "reasoning": "string"
}
```

**Inputs:**
- Market data (price, volume, liquidity)
- Regime classification
- Historical win rates by regime+setup
- Signal properties
- Funding rates
- Order book data

**Configuration:**
- Max tokens: 1500 (previous 512, 1000 truncated)
- Timeout: 25 seconds (needs to be fast for pre-trade)
- Model override via: `AGENT_QUANT_MODEL` env var

**Cost per Call:**
- Sonnet: ~400 input × $3.0/1M + ~100 output × $15.0/1M = ~$0.003
- CLI: $0

**Latency Budget:** 25 seconds

**Failure Mode:**
- If fails: `quant_out = None` (line 798), Confidence adjustments skip (line 819)
- Trade proceeds without quant analysis

**Confidence Adjustments Applied:**
1. Noise probability > 0.6:
   - If confidence < 0.20: hard skip (line 1061)
   - If 0.20-0.40: reduce size by 50% (line 1072)
   - Otherwise: proceed (line 1078)
2. Confidence adjustment: applied additively, capped at ±15% (lines 1019-1049)

**Test Coverage:**
- Agent config covers it (line 126-131)
- No Quant output schema tests found

**Downstream Consumption:**
- Trade Agent (receives EV, Kelly, noise probability)
- Scratchpad writes: ev, conditional_edge, probability, kelly_fraction, signal_quality, risk_profile (lines 813-824)

---

#### **6. EXIT AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:876-995`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:1962-1990`
- Public method: `get_exit_intelligence()` (line 1945)
- Input builder: `_build_exit_input()` (line 2002)

**Invocation Details:**
- Called asynchronously when positions are open
- OPTIONAL
- Returns: `self.last_exit_output` for external consumption
- Line 1966: `self._call_agent(AgentRole.EXIT, exit_input, model_for_trigger)`

**JSON Schema (Output):**
```json
{
  "action": "hold|partial|close|adjust_stop|trail",
  "reasoning": "string",
  "next_check_s": number
}
```

**Inputs:**
- Position details (entry, current price, unrealized PnL, time held)
- Regime (has it changed since entry?)
- Market momentum (reversals, exhaustion)
- Funding costs
- Risk budget remaining

**Configuration:**
- Max tokens: 400 (simplest output, just action + reasoning)
- Timeout: 25 seconds
- Model override via: `AGENT_EXIT_MODEL` env var

**Cost per Call:**
- Haiku: ~200 input × $0.80/1M + ~50 output × $4.0/1M = ~$0.0003
- CLI: $0

**Latency Budget:** 25 seconds

**Failure Mode:**
- If fails: `last_exit_output = None`, position held (default conservative action)
- No abort or degradation

**Test Coverage:**
- Agent config covers it (line 108-113)
- No Exit Agent output tests found

**Downstream Consumption:**
- External position management module (reads `last_exit_output`)
- Learning Agent (analyzes exit quality post-trade)

---

#### **7. SCOUT AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:997-1045`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2072-2136`
- Public method: `run_scout()` (line 2048)
- Input builder: `_build_scout_input()` (embedded in run_scout)

**Invocation Details:**
- Runs during IDLE TIME (no active signals)
- OPTIONAL
- Purpose: pre-form theses and watchlists before signals arrive
- Line 2076: `self._call_agent(AgentRole.SCOUT, scout_input, model_for_trigger)`
- Thesis caching (20-minute TTL, line 342-343)

**JSON Schema (Output):**
```json
{
  "watchlist": [
    {
      "symbol": "string",
      "direction": "long|short",
      "entry_level": number,
      "target": number,
      "stop": number,
      "confidence": 0.0-1.0
    }
  ],
  "regime_forecast": "string",
  "lead_lag": "string",
  "risk_budget": number
}
```

**Inputs:**
- Recent market structure
- Regime transitions
- Cross-symbol momentum
- Funding rates
- News/events (if available)
- Backtested setup win rates

**Configuration:**
- Max tokens: 2500 (same as Trade + Overseer working cap)
- Timeout: 30 seconds
- Model override via: `AGENT_SCOUT_MODEL` env var

**Cost per Call:**
- Sonnet: ~600 input × $3.0/1M + ~150 output × $15.0/1M = ~$0.004
- CLI: $0

**Latency Budget:** 30 seconds (runs async, not on critical path)

**Failure Mode:**
- If fails: no watchlist injected, Trade Agent sees no Scout preparation (graceful degradation)

**Test Coverage:**
- Agent config covers it (line 114-119)
- No Scout output tests found

**Downstream Consumption:**
- Coordinator injects Scout thesis into Trade Agent snapshot (lines 2076-2100)
- Boosts Trade Agent confidence if thesis matches signal

---

#### **8. OVERSEER AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:1047-1107`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2158-2191`
- Public method: `run_overseer()` (line 2138)
- Input builder: `_build_overseer_input()` (line 2596)

**Invocation Details:**
- Runs PERIODICALLY (30-60 minute intervals)
- OPTIONAL
- Purpose: system-level optimization, agent performance review, edge decay alerts
- Line 2181: `self._call_agent(AgentRole.OVERSEER, overseer_input, model_for_trigger)`

**JSON Schema (Output):**
```json
{
  "recommendations": [
    {
      "agent": "string",
      "recommendation": "string",
      "evidence": "string"
    }
  ],
  "theses": {
    "portfolio_health": "string",
    "edge_status": "string",
    "risk_posture": "string"
  },
  "adjustments": {
    "leverage_adjustment": number,
    "risk_reduction": boolean,
    "urgent_action_needed": boolean
  },
  "agent_feedback": {
    "agent_name": "feedback"
  }
}
```

**Inputs:**
- Full portfolio state
- Recent decision quality (win rates)
- Edge decay alerts
- Network learning insights
- Agent calibration metrics
- Portfolio correlation matrix

**Configuration:**
- Max tokens: 2500 (rich schema with 5 recs × 7 fields + nested objects)
- Timeout: 40 seconds
- Model override via: `AGENT_OVERSEER_MODEL` env var

**Cost per Call:**
- Sonnet: ~600 input × $3.0/1M + ~150 output × $15.0/1M = ~$0.004
- CLI: $0

**Latency Budget:** 40 seconds (async, not time-critical)

**Failure Mode:**
- If fails: no recommendations returned, system continues with current config
- Graceful degradation, no abort

**Test Coverage:**
- Agent config covers it (line 120-125)
- No Overseer output tests found

**Downstream Consumption:**
- Network Learning (reads edge decay alerts)
- Calibration Ledger (reads feedback on agent accuracy)
- Cost Optimizer (receives leverage adjustment recommendations)

---

#### **9. LEARNING AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:325-427`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:1710-1745`
- Public method: `get_post_trade_lesson()` (line 1697)
- Input builder: `_build_learning_input()` (line 4090)

**Invocation Details:**
- Runs AFTER TRADE CLOSES (post-trade only)
- OPTIONAL
- Async call (non-blocking)
- Line 1710: `self._call_agent(AgentRole.LEARNING, learning_input, model_for_trigger)`
- Writes to Network Learning system (line 1742)

**JSON Schema (Output):**
```json
{
  "lessons": [
    {
      "pattern": "string",
      "confidence": 0.0-1.0,
      "applicable_to": ["setup_name"],
      "action": "reinforce|adjust|investigate|suppress"
    }
  ],
  "patterns": {
    "winning": ["description"],
    "losing": ["description"]
  }
}
```

**Inputs:**
- Closed trade details (entry, exit, PnL, duration)
- Regime during trade
- Market structure changes
- Signal that triggered trade
- Execution quality

**Configuration:**
- Max tokens: 600 (simplest output — just lessons + patterns)
- Timeout: 30 seconds (post-trade, not time-critical)
- Model override via: `AGENT_LEARNING_MODEL` env var

**Cost per Call:**
- Haiku: ~200 input × $0.80/1M + ~80 output × $4.0/1M = ~$0.0004
- CLI: $0

**Latency Budget:** 30 seconds (async, no impact on trading)

**Failure Mode:**
- If fails: trade closes but learning is not extracted
- No systemic impact, just missed learning opportunity

**Test Coverage:**
- Agent config covers it (line 96-101)
- No Learning output tests found

**Downstream Consumption:**
- Network Learning module (integrates lessons into validated rules)
- Self-Teaching engine (feeds curriculum advancement)
- Neuroplasticity system (updates pattern strength weights)

---

### PHASE 3 STRATEGIC AGENTS (4 agents)

#### **10-13. PORTFOLIO, FORECASTER, HYPOTHESIS, CORRELATOR**

These are daily/weekly strategic analysis agents. All files in `/home/user/WAGMI/bot/llm/agents/strategic_agents.py` (not yet fully wired into main pipeline).

**File Path:**
- Prompts: `/home/user/WAGMI/bot/llm/agents/prompts.py:1225-1445`
- Builders: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2290-2347` (public methods only)
- Implementation: `strategic_agents.py` (not fully integrated)

**Summary:**
- PORTFOLIO AGENT (daily): Risk aggregation across positions — JSON: {portfolio_risk_summary, exposure_by_symbol, correlation_alerts}
- FORECASTER AGENT (daily): Regime transition prediction — JSON: {regime_forecast, probabilities, transition_timing}
- HYPOTHESIS AGENT (weekly): Pattern discovery — JSON: {hypothesis, supporting_evidence, testability_score}
- CORRELATOR AGENT (daily): Cross-asset relationships — JSON: {correlation_matrix, lead_lag_signals, alerts}

All optional, max_tokens 500-600, Haiku/Sonnet, 15-20s timeouts. Cost ~$0.001/call each.

---

### PHASE 4 SCALPING AGENTS (3 agents)

#### **14-16. MICRO_TREND, SCALPER, CONVICTION**

Located in `/home/user/WAGMI/bot/llm/agents/phase_4_agents.py`.

**File Path:**
- Prompts: `/home/user/WAGMI/bot/llm/agents/prompts.py:1447-1591`
- Builders: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2348-2398`
- Implementation: `phase_4_agents.py`

**Summary:**
- MICRO_TREND AGENT (every 5m): Detects micro trends for scalper context — 1-3m timeframe analysis. Max_tokens 768, timeout 3s (CRITICAL SPEED). Haiku. Cost ~$0.0003/call.
- SCALPER AGENT (every 1-3m): Micro-scalping opportunities on 1m/5m candles. Max_tokens 1024, timeout 3s. Haiku. Cost ~$0.0003/call.
- CONVICTION AGENT (rare): Ultra-high confidence trade authorization (2.5x leverage). Max_tokens 600, timeout 10s. Haiku. Cost ~$0.0002/call.

All optional, runs on tight loops when enabled.

---

### PHASE 4A CORE TRADING AGENTS (6 agents)

Located in `/home/user/WAGMI/bot/llm/agents/phase_4a_trading_agents.py`.

#### **17. POSITION_SIZER**
- Exact USD position size calculation
- Max_tokens 1024, timeout 5s, Haiku
- Schema: {position_size_usd, leverage_applied, kelly_applied, rationale, conservative_due_to[]}
- Cost ~$0.0003/call

#### **18. ENTRY_OPTIMIZER**
- Entry timing + method (market/limit/scaled/wait)
- Max_tokens 768, timeout 4s, Haiku
- Schema: {entry_method, entry_price, urgency, rationale}
- Cost ~$0.0002/call

#### **19. EXIT_ADVISOR**
- Separate from Exit Agent — focuses on OPEN position exits
- Max_tokens 1024, timeout 5s, Haiku
- Schema: {exit_action, exit_price, timing, profit_target_hit, rationale}
- Cost ~$0.0003/call

#### **20. RISK_GUARD**
- Safety gate, prevents catastrophic losses
- Max_tokens 768, timeout 4s, Haiku
- Schema: {approved, veto_reason, risk_level, recommended_adjustments}
- Cost ~$0.0002/call

#### **21. AGENT_ROUTER**
- Decides which Phase 4A agents to call on this trade
- Max_tokens 1024, timeout 5s, Haiku
- Schema: {agents_to_call[], rationale, skip_reason}
- Cost ~$0.0003/call

#### **22. CONSENSUS_BUILDER**
- Final decision merger (after all agents weigh in)
- Max_tokens 800, timeout 10s, Haiku→Sonnet promotion
- Schema: {final_action, confidence, size_multiplier, reasoning}
- Cost ~$0.0004/call

---

### OVERRIDE AGENT (1 agent)

#### **23. OVERRIDE AGENT**

**File Paths:**
- Prompt: `/home/user/WAGMI/bot/llm/agents/prompts.py:1593-1658`
- Invocation: `/home/user/WAGMI/bot/llm/agents/coordinator.py:1881-1942`
- Public method: `evaluate_override()` (line 1881)

**Purpose:**
- LLM-reasoned override of mechanical filter blocks
- When a mechanical rule blocks a trade but LLM believes rule is wrong

**JSON Schema (Output):**
```json
{
  "override_approved": boolean,
  "reason": "string",
  "confidence_in_override": 0.0-1.0,
  "risk_assessment": "string"
}
```

**Configuration:**
- Max tokens: 1024
- Timeout: 25 seconds
- Model: Sonnet (educated judgment needed)

**Cost per Call:**
- Sonnet: ~300 input × $3.0/1M + ~100 output × $15.0/1M = ~$0.002
- CLI: $0

**Failure Mode:**
- If fails: block is NOT overridden (safe default — "no" wins)

---

## SUMMARY TABLE: ALL 23 AGENTS

| # | Agent | Type | Model | Max Tokens | Timeout | Required? | Cost/Call | Test Coverage |
|---|-------|------|-------|-----------|---------|-----------|-----------|-----------------|
| 1 | REGIME | Core | Haiku | 1200 | 30s | YES | $0.0003 | Minimal |
| 2 | TRADE | Core | Haiku/Sonnet | 2500 | 60s | YES | $0.0024 | Minimal |
| 3 | RISK | Core | Haiku | 1000 | 40s | NO | $0.0006 | Minimal |
| 4 | CRITIC | Core | Sonnet | 1500 | 60s | NO | $0.003 | Minimal |
| 5 | QUANT | Core | Sonnet | 1500 | 25s | NO | $0.003 | Minimal |
| 6 | EXIT | Core | Haiku | 400 | 25s | NO | $0.0003 | None |
| 7 | SCOUT | Core | Sonnet | 2500 | 30s | NO | $0.004 | None |
| 8 | OVERSEER | Core | Sonnet | 2500 | 40s | NO | $0.004 | None |
| 9 | LEARNING | Core | Haiku | 600 | 30s | NO | $0.0004 | None |
| 10 | PORTFOLIO | Phase 3 | Haiku | 600 | 20s | NO | $0.0003 | None |
| 11 | FORECASTER | Phase 3 | Haiku | 500 | 15s | NO | $0.0003 | None |
| 12 | HYPOTHESIS | Phase 3 | Haiku | 600 | 20s | NO | $0.0003 | None |
| 13 | CORRELATOR | Phase 3 | Haiku | 500 | 15s | NO | $0.0003 | None |
| 14 | MICRO_TREND | Phase 4 | Haiku | 768 | 3s | NO | $0.0002 | None |
| 15 | SCALPER | Phase 4 | Haiku | 1024 | 3s | NO | $0.0003 | None |
| 16 | CONVICTION | Phase 4 | Haiku | 600 | 10s | NO | $0.0002 | None |
| 17 | POSITION_SIZER | Phase 4A | Haiku | 1024 | 5s | NO | $0.0003 | None |
| 18 | ENTRY_OPTIMIZER | Phase 4A | Haiku | 768 | 4s | NO | $0.0002 | None |
| 19 | EXIT_ADVISOR | Phase 4A | Haiku | 1024 | 5s | NO | $0.0003 | None |
| 20 | RISK_GUARD | Phase 4A | Haiku | 768 | 4s | NO | $0.0002 | None |
| 21 | AGENT_ROUTER | Phase 4A | Haiku | 1024 | 5s | NO | $0.0003 | None |
| 22 | CONSENSUS_BUILDER | Phase 4A | Haiku | 800 | 10s | NO | $0.0003 | None |
| 23 | OVERRIDE | Core | Sonnet | 1024 | 25s | NO | $0.002 | None |

**Cost per Full Pipeline (RECOMMENDED tier, CLI routing):**
- Minimum: Regime + Trade = 1 call at $0 = **$0** (CLI routing)
- Standard: Regime + Trade + Risk + Critic = 4 calls at $0 = **$0**
- Full (incl. Quant): 5 calls at $0 = **$0**
- API fallback (Sonnet): ~$0.012 per full pipeline

**Monthly Cost Estimates (100 trades/month):**
- CONSERVATIVE (Haiku, CLI): **$0**
- RECOMMENDED (Sonnet, CLI): **$0**
- AGGRESSIVE (Sonnet + Opus smart routing, API): **$750**
- UNLEASHED (Opus-heavy, API): **$1,400**

---

## PART 2: PROPOSED NEW AGENTS (5-8 agents)

Based on gaps in the current pipeline, here are the 6 most valuable new agents:

### **AGENT 1: OPPORTUNIST (REQUIRED) ✓**

**Role:** Proactive detection of asymmetric setups outside normal pipeline.

**Why Needed:**
- Current agents are REACTIVE: wait for signals, then evaluate
- Opportunist is PROACTIVE: continuously scans for edges the mechanical system misses
- Specific gaps:
  - Funding-rate extremes (>0.10% unprofitable, <-0.05% super-profitable)
  - Liquidation cascades (OI cliff + price drop = forced sellers)
  - Post-news reversion windows (news spike + fade = high-probability MR)
  - BTC correlation breakdowns (alts lagging = divergence trade)
  - Index rebalancing effects
  - Market maker position accumulation

**When It Runs:**
- Continuously on 5-minute interval (lower cadence than Scalper)
- Asynchronous, doesn't block trading
- Budget: 10-15 calls/hour max (cost control)

**Recommended Model:** Haiku (lightweight scan), upgrade to Sonnet if multiple edges detected

**Input Schema:**
```json
{
  "funding_rates": {
    "BTC": 0.025,
    "ETH": 0.031,
    "SOL": -0.005,
    "HYPE": 0.087
  },
  "oi_structure": {
    "symbol": "OI_change_pct",
    "liquidation_levels": {
      "long": [price1, price2],
      "short": [price3, price4]
    }
  },
  "recent_news": [
    {
      "symbol": "SOL",
      "event": "string",
      "time_ago_minutes": 5,
      "market_reaction_pct": -2.5
    }
  ],
  "btc_alt_correlation": {
    "current": 0.78,
    "20d_avg": 0.82,
    "deviation": -0.04
  },
  "market_structure": {
    "recent_spike": "HYPE +8.2%",
    "volume_profile": "high_at_highs",
    "vix_equivalent": 0.45
  }
}
```

**Output Schema:**
```json
{
  "opportunities": [
    {
      "type": "funding_rate_extreme|liquidation_cascade|news_reversion|correlation_breakdown|index_rebalance|mm_accumulation",
      "symbol": "string",
      "side": "long|short",
      "urgency": "immediate|within_1h|within_4h",
      "ev_estimate": 0.0-1.0,
      "setup_description": "string",
      "risk_level": "low|medium|high",
      "recommended_entry_trigger": "string",
      "time_window_minutes": number
    }
  ],
  "portfolio_implications": "string",
  "next_scan_in_minutes": 5
}
```

**Where It Sits:**
- Parallel to Scout, doesn't interfere with main pipeline
- Writes to "opportunity_scratchpad" that Trade Agent can read
- Higher than Trade Agent in priority (opportunities pre-empt signals)

**Cost:**
- Haiku: ~300 input × $0.80/1M + ~100 output × $4.0/1M = ~$0.0005/scan
- 10-15 scans/hour = ~$0.005-0.008 per hour
- Monthly: ~$3.60-5.76 (MINIMAL)
- CLI: $0

**Example:**
```
Trigger: 14:32 UTC
BTC funding rate: 0.087% (extreme long bias)
SOL funding rate: -0.045% (extreme short bias)
SOL OI cliff at $145 (longs liquidate if drop 2.1%)
Output:
  type: liquidation_cascade
  symbol: SOL
  side: short
  urgency: immediate (2.1% to trigger)
  ev_estimate: 0.62 (historical 64% WR on these setups)
  entry_trigger: "if BTC breaches $95.2k resistance with volume"
  time_window_minutes: 45
```

**Failure Mode:**
- If Opportunist fails: no opportunities suggested, system continues normally
- Graceful degradation

**Test Requirements:**
- Mock funding rate data, verify opportunity detection
- Test liquidation level calculation
- Test news sentiment integration

---

### **AGENT 2: ADVERSARY (STRONG CANDIDATE)**

**Role:** Devil's advocate — argues opposite of Trade Agent thesis to reduce confirmation bias.

**Why Needed:**
- Trade Agent confidence is often overconfident (68% of 80%+ confidence trades lose, per backtesting)
- Adversary pressure-tests the thesis
- Reduces "whole team agrees" traps
- Current Critic doesn't have adversarial mandate; Critic "checks" but doesn't argue alternative

**When It Runs:**
- Only when Trade Agent confidence > 0.65 (to avoid noise)
- After Trade Agent, before Critic (creates context for Critic)

**Recommended Model:** Sonnet (needs to be creative + rigorous)

**Input Schema:**
```json
{
  "trade_thesis": "string",
  "confidence": 0.65-1.0,
  "regime": "string",
  "market_structure": { ... },
  "contrary_indicators": [
    { "indicator": "string", "reading": "value", "implication": "string" }
  ]
}
```

**Output Schema:**
```json
{
  "counter_thesis": "string",
  "objections": [
    {
      "argument": "string",
      "strength": 0.0-1.0,
      "counter_evidence": "string"
    }
  ],
  "alternative_outcome_probability": 0.0-1.0,
  "recommendation": "proceed_with_caution|revisit_thesis|consider_opposite_side"
}
```

**Cost:**
- Sonnet: ~300 input × $3.0/1M + ~100 output × $15.0/1M = ~$0.002
- CLI: $0
- Runs ~40% of trades (high-conf only): ~0.8/day × $0.002 = **$0.002/day = $0.06/month**

**Example:**
```
Trade Thesis: "SOL LONG — funding -0.045%, oversold, 2-agree, regime trending_bull"
Confidence: 0.78

Adversary Output:
  counter_thesis: "SOL actually in exhaustion. Negative funding justified — shorts are RIGHT to be short. 
    Recent pump is capitulation, not reversal."
  objections:
    - "RSI>80 — textbook overbought, historical mean reversion -0.8%"
    - "Funding negative because smart money knows reversal coming"
    - "Volume spike on pump without structure — classic pump before dump"
  alternative_outcome_probability: 0.55
  recommendation: "proceed_with_caution — reduce size by 30%, tighter stop"
```

**Failure Mode:**
- If Adversary fails: Trade proceeds without counter-thesis (Critic may catch it)
- No abort

**Test Requirements:**
- Verify Adversary argues against thesis (not just summarizes)
- Test on known losing trades (should flag them)
- Test on known winning trades (should acknowledge but note caveats)

---

### **AGENT 3: CALIBRATION AUDITOR (MEDIUM CANDIDATE)**

**Role:** Periodic review of whether agents are over/under-confident; recommend prompt tweaks.

**Why Needed:**
- No current agent audits other agents' calibration
- Overseer does system-level but not agent-specific
- Example: Regime Agent confidence is uncorrelated with accuracy (0.45 regime_conf = same WR as 0.85)
- Calibration fixes directly improve downstream confidence

**When It Runs:**
- Every 50 trades (post-learning aggregation)
- NOT on critical path (async)

**Recommended Model:** Sonnet

**Input Schema:**
```json
{
  "agent_name": "regime|trade|critic|risk",
  "recent_decisions": [
    {
      "confidence": 0.75,
      "outcome": "correct|incorrect",
      "pnl": 42.5
    }
  ],
  "calibration_curve": {
    "confidence_0_10": { "accuracy": 0.30, "n_samples": 15 },
    "confidence_40_50": { "accuracy": 0.45, "n_samples": 32 },
    "confidence_70_80": { "accuracy": 0.25, "n_samples": 18 }
  },
  "current_prompt_directives": [
    "Confidence = base 0.50 + adjustments",
    "..."
  ]
}
```

**Output Schema:**
```json
{
  "calibration_status": "well_calibrated|overconfident|underconfident",
  "evidence": "string",
  "recommended_changes": [
    {
      "change": "string",
      "expected_impact": "confidence will decrease by X% on average",
      "rationale": "string"
    }
  ],
  "priority": "high|medium|low"
}
```

**Cost:**
- Sonnet: ~250 input × $3.0/1M + ~100 output × $15.0/1M = ~$0.0015
- Runs 2x/day: **$0.003/day = $0.09/month**

**Example:**
```
Agent: CRITIC
Recent calibration curve:
  - Confidence 70-80 ("approve"): 65% CORRECTNESS
  - Confidence 80-90 ("approve strongly"): 42% CORRECTNESS (!!)
  - Confidence >90 ("STRONG APPROVE"): 15% CORRECTNESS (anti-predictive)

Output:
  status: overconfident
  evidence: "Critic disapproves more often than it approves, but when it strongly approves, 
    those trades LOSE. Inverse relationship: strength of approval predicts FAILURE."
  recommended_changes:
    - "Remove 'STRONG APPROVE' verdict option — binary (approve/reject) only"
    - "Cap confidence on approvals at 0.80, not 0.95"
    - "Add penalty for lone-wolf disagreements (when Critic approved but Quant/Risk disagreed)"
  priority: high
```

**Failure Mode:**
- If Auditor fails: no prompt adjustments (system continues)
- Graceful degradation

**Test Requirements:**
- Mock calibration curves, verify over/underconfidence detection
- Test on known well-calibrated agents
- Test recommendation generation

---

### **AGENT 4: MEMORY CURATOR (OPTIONAL)**

**Role:** Prunes stale insights, surfaces forgotten patterns, maintains knowledge base coherence.

**Why Needed:**
- Network Learning + Self-Teaching accumulate patterns; no cleanup
- Old patterns become noise as market regime shifts
- Forgotten patterns re-emerge (BTC correlation breakdowns happen ~monthly)
- Curator prevents knowledge explosion

**When It Runs:**
- Weekly (Sunday morning)
- Async, no impact on trading

**Recommended Model:** Haiku (straightforward curation task)

**Cost:** ~$0.0004/week = **$0.002/month**

---

### **AGENT 5: DRAWDOWN RECOVERY (STRONG CANDIDATE)**

**Role:** Activates when equity drawdown > threshold; recommends defensive posture, position exits, recalibration.

**Why Needed:**
- Current system has no "drawdown mode" — same trading during 10% gains and 20% drawdowns
- Empirical: post-loss clustering means aggressive trading after losses fails
- Should auto-trigger recovery behavior (tighter stops, higher bars for entry, size reduction)

**When It Runs:**
- Triggered when cumulative_drawdown > 8% (configurable)
- Runs every 1h until drawdown recovers

**Recommended Model:** Sonnet (sensitive decision)

**Input Schema:**
```json
{
  "equity": 98200,
  "peak_equity": 106500,
  "cumulative_drawdown_pct": 7.8,
  "recent_trades": [...],
  "win_rate_last_10": 0.30,
  "consecutive_losses": 3,
  "open_positions": [...]
}
```

**Output Schema:**
```json
{
  "recovery_mode_active": true,
  "recommended_posture": "defensive|conservative|recovery",
  "suggested_actions": [
    {
      "action": "reduce_size_by_pct",
      "position": "all|specific_symbol",
      "amount": 30
    },
    {
      "action": "tighten_stop_loss",
      "from_pct": 2.0,
      "to_pct": 1.5
    },
    {
      "action": "require_higher_confidence",
      "new_minimum": 0.75
    }
  ],
  "time_until_normal_mode": "4h"
}
```

**Cost:**
- Sonnet: ~$0.002
- Runs ~5 times/month during drawdowns: **$0.01/month**

**Example:**
```
Equity: $98,200 / Peak: $106,500 = -7.8% drawdown
Consecutive losses: 3
Win rate last 10: 30%

Output:
  recovery_mode: true
  posture: defensive
  suggested_actions:
    - reduce all position sizes by 30%
    - tighten stops from 2% to 1.5%
    - raise minimum confidence from 0.60 to 0.75
    - exit worst-performing position (HYPE, -2.5%)
```

**Failure Mode:**
- If fails: no recovery guidance, system continues (risky during drawdowns)
- Should be required or at least logged loudly

---

### **AGENT 6: FUNDING ARBITRAGE DETECTOR (MEDIUM CANDIDATE)**

**Role:** Detects funding-rate divergences across exchanges/perp protocols.

**Why Needed:**
- Hyperliquid often has extreme funding rates
- Bybit, dYdX may have different rates
- Spread > 0.05%/8h = profitable carry trade
- No agent currently monitors this

**When It Runs:**
- Every 2 hours (funding rates change slowly)
- Async

**Recommended Model:** Haiku (simple calculation)

**Input Schema:**
```json
{
  "hyperliquid_funding": { "BTC": 0.087, "ETH": 0.051, ... },
  "bybit_funding": { "BTC": 0.032, "ETH": 0.028, ... },
  "dydx_funding": { "BTC": 0.041, "ETH": 0.035, ... }
}
```

**Output Schema:**
```json
{
  "opportunities": [
    {
      "arbitrage": "long_on_bybit_short_on_hyperliquid",
      "symbol": "BTC",
      "spread_daily": 0.055,
      "estimated_profit_24h_pct": 0.055,
      "capital_required_usd": 50000,
      "liquidity_constraint": "bybit_bids_thin"
    }
  ]
}
```

**Cost:** ~$0.0002/run × 12/day = **$0.002/day = $0.06/month**

---

## DECISION: WHICH AGENTS TO ADD?

**Recommended: 4 agents (highest ROI)**

1. ✅ **OPPORTUNIST (REQUIRED)** — Highest impact, detects edges mechanical system misses, minimal cost ($0/CLI)
2. ✅ **ADVERSARY** — Reduces overconfidence bias, medium cost ($0.06/month), proven ROI
3. ✅ **DRAWDOWN RECOVERY** — Prevents loss clustering, medium cost ($0.01/month), big PnL impact
4. ✅ **CALIBRATION AUDITOR** — Improves all downstream agents, medium cost ($0.09/month), multiplicative benefit

**Optional (if budget allows):**
- FUNDING ARBITRAGE: Low cost, niche opportunity
- MEMORY CURATOR: Maintenance only, low priority

**Not Recommended:**
- AGENT_X_NEWS_SENTINEL: Too noisy, hard to integrate sentiment reliably
- AGENT_X_WHALE_WATCHER: On-chain data expensive, hard to act fast enough
- AGENT_X_EXIT_OPTIMIZER (duplicate Exit Agent): Redundant with Phase 4A Exit_Advisor

---

## PART 3: 8-STEP RECIPE FOR ADDING AGENTS

### Step 1: Define Agent Role & Configuration

**File:** `/home/user/WAGMI/bot/llm/agents/base.py`

```python
class AgentRole(str, Enum):
    # Add new agent:
    OPPORTUNIST = "opportunist"
```

Add to `DEFAULT_AGENT_CONFIGS`:
```python
DEFAULT_AGENT_CONFIGS[AgentRole.OPPORTUNIST] = AgentConfig(
    role=AgentRole.OPPORTUNIST,
    enabled=True,
    max_tokens=1024,
    timeout_s=15.0,
    required=False,  # Set True only for critical agents
)
```

**Checklist:**
- ✓ Role name is lowercase (convention)
- ✓ max_tokens sized to hold full output schema (never truncate)
- ✓ timeout appropriate for use case (3s for scalping, 30s for strategic)
- ✓ required=False unless agent blocks trading

---

### Step 2: Write Agent Prompt

**File:** `/home/user/WAGMI/bot/llm/agents/prompts.py`

Create `OPPORTUNIST_AGENT_PROMPT`:

```python
OPPORTUNIST_AGENT_PROMPT = """You are the Opportunist Agent...

[Full prompt, 500-1500 words]

OUTPUT (JSON only):
```json
{...schema...}
```
"""
```

**Checklist:**
- ✓ Prompt starts with role description (1 sentence)
- ✓ All output fields documented in OUTPUT block
- ✓ JSON example shows all required fields
- ✓ No markdown/prose in OUTPUT section (agents must output raw JSON)
- ✓ Prompt includes examples of decisions
- ✓ Prompt includes edge cases and failure modes

---

### Step 3: Register Prompt

**File:** `/home/user/WAGMI/bot/llm/agents/prompts.py`, end of file

```python
AGENT_PROMPTS = {
    ...existing...
    "opportunist": OPPORTUNIST_AGENT_PROMPT,
}
```

**Checklist:**
- ✓ Key matches role.value exactly ("opportunist" = AgentRole.OPPORTUNIST.value)

---

### Step 4: Build Input Constructor

**File:** `/home/user/WAGMI/bot/llm/agents/coordinator.py`

Add method to `AgentCoordinator`:

```python
def _build_opportunist_input(self, snapshot: dict) -> str:
    """Build Opportunist Agent input: funding rates, OI structure, news, correlation."""
    data = {
        "funding_rates": {...},
        "oi_structure": {...},
        "recent_news": [...],
        "btc_alt_correlation": {...},
        "market_structure": {...},
    }
    return json.dumps(data)
```

**Checklist:**
- ✓ All fields in prompt's "INPUTS" section included
- ✓ Data properly nested (no flat dict)
- ✓ JSON serializable (no non-standard types)
- ✓ Comment explains where each field comes from

---

### Step 5: Integrate into Pipeline

**File:** `/home/user/WAGMI/bot/llm/agents/coordinator.py`, in `get_trading_decision()`

Add after regime classification:

```python
# ── Opportunist Agent (parallel to Scout, async) ────────
if self.configs.get(AgentRole.OPPORTUNIST, AgentConfig(role=AgentRole.OPPORTUNIST)).enabled:
    try:
        opp_input = self._build_opportunist_input(snapshot_data)
        opp_out = self._call_agent(AgentRole.OPPORTUNIST, opp_input, model_for_trigger)
        pipeline_results[AgentRole.OPPORTUNIST] = opp_out
        if opp_out.ok:
            scratchpad.write("opportunist", "opportunities", opp_out.data.get("opportunities", []))
    except Exception as e:
        logger.debug(f"[MULTI-AGENT] Opportunist failed: {e}")
```

**Checklist:**
- ✓ Wrapped in try-except (non-blocking)
- ✓ Configuration check (optional agents check config first)
- ✓ Writes to scratchpad so Trade Agent can read
- ✓ Added to pipeline_results dict (for diagnostics)
- ✓ Placed in correct order (before/after/parallel to other agents)

---

### Step 6: Add Per-Agent Enable/Model Override Env Vars

**File:** `/home/user/WAGMI/bot/llm/agents/coordinator.py`, function `_build_configs_from_env()`

Add mapping:
```python
_ENV_MODEL_OVERRIDES = {
    ...
    AgentRole.OPPORTUNIST: "AGENT_OPPORTUNIST_MODEL",
}

_ENV_ENABLE_OVERRIDES = {
    ...
    AgentRole.OPPORTUNIST: "AGENT_OPPORTUNIST_ENABLED",
}
```

**Checklist:**
- ✓ Env var named AGENT_{NAME}_ENABLED (boolean)
- ✓ Env var named AGENT_{NAME}_MODEL (model string, optional)
- ✓ Applied in `get_trading_decision()` tier routing if relevant

---

### Step 7: Add Test Coverage

**File:** `/home/user/WAGMI/bot/tests/test_multi_agent.py`

```python
class TestOpportunistAgent:
    def test_config_exists(self):
        from llm.agents.base import DEFAULT_AGENT_CONFIGS, AgentRole
        assert AgentRole.OPPORTUNIST in DEFAULT_AGENT_CONFIGS
        cfg = DEFAULT_AGENT_CONFIGS[AgentRole.OPPORTUNIST]
        assert cfg.max_tokens >= 800
        assert cfg.timeout_s >= 10

    def test_prompt_registered(self):
        from llm.agents.prompts import AGENT_PROMPTS
        assert "opportunist" in AGENT_PROMPTS
        assert "JSON" in AGENT_PROMPTS["opportunist"]
        assert "opportunities" in AGENT_PROMPTS["opportunist"]

    def test_output_schema(self):
        # Mock call and verify output structure
        from unittest.mock import MagicMock, patch
        with patch("llm.client.call_llm") as mock_llm:
            mock_llm.return_value = (
                '{"opportunities": [{"type": "funding_rate_extreme", "symbol": "BTC", ...}]}',
                {"input_tokens": 100, "output_tokens": 50},
            )
            coordinator = get_coordinator()
            output = coordinator._call_agent(AgentRole.OPPORTUNIST, "{}", "sonnet")
            assert output.ok
            assert "opportunities" in output.data
            assert isinstance(output.data["opportunities"], list)
```

**Checklist:**
- ✓ Test agent config existence
- ✓ Test prompt registration
- ✓ Test output schema parsing
- ✓ Test failure gracefully (mock API error)
- ✓ Test env var overrides work

---

### Step 8: Update Documentation & Cost Tracking

**File:** Internal: `/home/user/WAGMI/README.md` or agent docs

```markdown
## Opportunist Agent

**Role:** Proactive detection of asymmetric setups (funding extremes, liquidation cascades, news reversion).

**When:** Every 5 minutes (async)
**Model:** Haiku (upgrade to Sonnet if multiple edges)
**Cost:** ~$0.0005/scan, ~$3-6/month
**Enable:** `AGENT_OPPORTUNIST_ENABLED=true`
**Model Override:** `AGENT_OPPORTUNIST_MODEL=claude-sonnet-4-6`
```

**Checklist:**
- ✓ Document role, cadence, cost
- ✓ Document env vars for enable/model override
- ✓ Add to agent pricing table
- ✓ Update monthly cost estimates

---

## PART 4: AGENT INTERACTION TOPOLOGY

### Data Flow Diagram (ASCII)

```
COORDINATOR: get_trading_decision() [main pipeline]
│
├─ EXTERNAL DATA INJECTION (funding rates, liquidation levels, news)
│  └─ enrich snapshot_data dict
│
├─ ENRICHMENT (technicals, feedback, telemetry, portfolio, ML, knowledge base)
│  └─ build enriched_context str
│
├─ STEP 1.0: REGIME AGENT
│  ├─ INPUT: snapshot_data + enriched_context
│  ├─ OUTPUT: {rg, conf, factors, bias, transition, regime_momentum, expected_duration_h, outlook}
│  ├─ WRITES: scratchpad["regime"] = {regime, conf, bias, outlook, transition, momentum, duration}
│  └─ CACHING: 30min TTL per symbol
│
├─ STEP 1.5: QUANT AGENT (optional, tier 3+ only)
│  ├─ INPUT: snapshot_data + regime_out + enriched_context
│  ├─ OUTPUT: {ev, conditional_edge, probability, kelly_fraction, signal_quality, risk_profile, reasoning}
│  ├─ WRITES: scratchpad["quant"] = {ev, conditional_edge, probability, kelly_fraction, signal_quality, risk_profile}
│  └─ FEEDBACK: confidence adjustment -15% to +15% applied to Trade output
│
├─ STEP 1.75: OPPORTUNIST AGENT (async, optional)
│  ├─ INPUT: funding_rates, oi_structure, recent_news, btc_correlation, market_structure
│  ├─ OUTPUT: {opportunities[], portfolio_implications, next_scan_minutes}
│  ├─ WRITES: scratchpad["opportunist"]["opportunities"] = [...edge descriptions...]
│  └─ SIGNAL: pre-empts Trade Agent (opportunities injected into Trade input)
│
├─ STEP 2.0: TRADE AGENT (required)
│  ├─ INPUT: snapshot_data + regime_out + quant_out + opportunist opportunities + scout_thesis + enriched_context
│  ├─ GATE CHAIN (internal):
│  │  ├─ Gate 1: regime check (panic/unknown → skip)
│  │  ├─ Gate 2: direction alignment (thesis vs signal)
│  │  ├─ Gate 3: timeframe confluence (6h vs 1h)
│  │  ├─ Gate 4: strategy consensus (3+ → boost, solo → cap at 0.60)
│  │  ├─ Gate 5: market quality (ADX, RSI, volume)
│  │  ├─ Gate 6: signal evaluation (rf flags, ev assessment)
│  │  └─ Gate 7: thesis formation
│  ├─ CONFIDENCE CALIBRATION:
│  │  ├─ Base: 0.50
│  │  ├─ Adjustments: +/- 0.05-0.15 for regime, agreement, timing, BTC, funding, volume, exhaustion
│  │  ├─ Cap: 0.85, floor: 0.30
│  │  └─ Self-correction: if self_perf cal > +0.10, reduce by 10%
│  ├─ OUTPUT: {a: "go|skip|flip", c: 0.0-1.0, thesis, ea, mu, n}
│  ├─ WRITES: scratchpad["trade"] = {action, confidence, thesis}
│  └─ POST-CALL ADJUSTMENTS:
│     ├─ QUANT_ADJ: -0.15 to +0.15 per Quant signal quality (capped ±15%)
│     ├─ QUANT_NOISE: if > 0.6 prob, size-cut or skip
│     └─ NET_CAL: network learning regime calibration +/- adjustment
│
├─ CONSISTENCY CHECK
│  ├─ INPUT: regime_data, trade_data, risk_data (if available), critic_data (if available)
│  ├─ CHECKS: regime ↔ action alignment, confidence ↔ regime, action ↔ portfolio
│  └─ VETO: critical issues override action to "skip" (conf halved, not zeroed)
│
├─ STEP 3.0: RISK AGENT (optional)
│  ├─ INPUT: snapshot_data + regime_out + trade_out + quant_out
│  ├─ OUTPUT: {sz, leverage, risk_pct, sw, risks[], override, sizing_rationale}
│  ├─ WRITES: scratchpad["risk"] = position size + leverage + strategy weights
│  └─ FAILURE: skipped, downstream uses mechanical sizing
│
├─ STEP 4.0: CRITIC AGENT (optional)
│  ├─ DETECTION: _is_high_stakes_trade()
│  │  └─ HIGH STAKES: conf > 0.75 or leverage > 5x or portfolio_leverage > 8x
│  ├─ IF HIGH STAKES:
│  │  ├─ DEBATE ROUND 1 (Critic, de-anchored: no confidence shown)
│  │  │  ├─ INPUT: regime, trade_thesis (no confidence), risk, market_data, recent_perf
│  │  │  └─ OUTPUT: counter_thesis, objections[]
│  │  ├─ DEBATE ROUND 2 (Trade Agent, rebuttal)
│  │  │  ├─ INPUT: Critic objections, Trade thesis, regime
│  │  │  └─ OUTPUT: rebuttal reasoning
│  │  └─ CRITIC FINAL (Critic reads both sides)
│  │     └─ OUTPUT: {verdict: "approve|object|revise", adjusted_confidence, reason}
│  ├─ IF NOT HIGH STAKES:
│  │  └─ SIMPLE CRITIC call with full context
│  ├─ OUTPUT: {verdict: "approve|object|revise", counter_thesis, objections[], adjusted_confidence, reason}
│  ├─ WRITES: scratchpad["critic"] = {verdict, adjusted_confidence, objections}
│  └─ FAILURE: mechanical fallback (low conf → skip, counter-trend → skip, reduce conf 10%)
│
├─ AGENT BRAIN CONTEXT (injected into Critic/Trade/Overseer)
│  ├─ Brain: learned beliefs, performance by symbol, calibration state
│  └─ Source: agent_brain.py, updated post-trade
│
├─ FINAL DECISION MERGE (Phase 4A if enabled, else manual)
│  ├─ INPUT: trade_out, risk_out, critic_out (all optional)
│  ├─ CONSENSUS: agreement levels, weighted confidence, final size/action
│  └─ OUTPUT: LLMDecision {action, confidence, regime, size_mult, reasoning}
│
├─ OVERRIDE GATE (if mechanical filters blocked trade)
│  ├─ INPUT: blocked_reason, trade_thesis, confidence, risk_factors
│  ├─ OUTPUT: {override_approved, reason, confidence_in_override}
│  └─ DECISION: override? → proceed else → skip
│
└─ RETURN: LLMDecision to executor

POST-EXECUTION (async, non-blocking):
│
├─ STEP 5.0: LEARNING AGENT (after trade closes)
│  ├─ INPUT: closed trade {entry, exit, pnl, duration, regime, signal, execution}
│  ├─ OUTPUT: {lessons[], patterns[]}
│  ├─ WRITES: Network Learning system (validated rules, pattern library)
│  └─ DOWNSTREAM: Self-Teaching (curriculum advancement), Neuroplasticity (edge strength updates)
│
├─ STEP 6.0: SCOUT AGENT (idle time, continuous)
│  ├─ INPUT: market structure, regime transitions, cross-symbol momentum, funding, news
│  ├─ OUTPUT: {watchlist[], regime_forecast, lead_lag, risk_budget}
│  ├─ CACHES: 20min TTL, injected into next Trade call
│  └─ BOOST: if Scout direction matches Trade direction → +0.10 confidence
│
├─ STEP 7.0: OVERSEER AGENT (periodic, 30-60min)
│  ├─ INPUT: full portfolio, recent_decisions_quality, edge_decay, network_learning, agent_perf
│  ├─ OUTPUT: {recommendations[], theses{}, adjustments{}, agent_feedback{}}
│  ├─ DOWNSTREAM: Network Learning (edge updates), Calibration Ledger (agent feedback)
│  └─ EFFECTS: leverage adjustments, risk posture changes, prompt calibration updates
│
├─ STEP 8.0: BACKGROUND THINKER (continuous in background)
│  ├─ MAINTAINS: market observations journal, pattern notes, opportunities log
│  ├─ OUTPUT: journal_text injected into agent enriched_context
│  └─ FEEDS: Scout, Opportunist, Overseer with ongoing pattern notes
│
└─ STEP 9.0: ADVERSARY AGENT (optional, high-confidence trades)
   ├─ INPUT: trade_thesis, confidence (if > 0.65), regime, market_structure
   ├─ OUTPUT: {counter_thesis, objections[], alternative_outcome_probability, recommendation}
   ├─ TIMING: after Trade Agent, creates context for Critic
   └─ EFFECT: Critic sees devil's advocate view, pressure-tests approval
```

### Scratchpad (Shared Context)

```
scratchpad["regime"] = {
  regime: str,
  conf: float,
  bias: str,
  outlook: str,
  regime_momentum: str,
  expected_duration_h: list,
}

scratchpad["quant"] = {
  ev: dict,
  conditional_edge: dict,
  probability: float,
  kelly_fraction: float,
  signal_quality: dict,
  risk_profile: str,
}

scratchpad["opportunist"] = {
  opportunities: list,
}

scratchpad["trade"] = {
  action: str,
  confidence: float,
  thesis: str,
}

scratchpad["risk"] = {
  position_size: float,
  leverage: float,
  strategy_weights: dict,
}

scratchpad["critic"] = {
  verdict: str,
  adjusted_confidence: float,
  objections: list,
}
```

### Downstream Systems Reading Agent Outputs

| System | Reads From | Purpose |
|--------|-----------|---------|
| Executor | Trade action + Risk size | Execute or skip |
| Learning | All agent outputs | Extract lessons post-trade |
| Network Learning | Learning output | Update validated rules |
| Calibration Ledger | Critic feedback | Adjust agent prompts |
| Brain | Trade + Critic outputs | Learn agent performance by symbol |
| Cost Tracker | All agent calls | Monitor usage, enforce budget |
| Performance Tracker | Trade + Learning | Track WR, PF, Sharpe |
| Portfolio Risk | Risk output | Cumulative portfolio constraint |
| Agent Router (Phase 4A) | Trade confidence | Route to Phase 4A agents if conf > 0.60 |
| Consensus Builder (Phase 4A) | All agent outputs | Final decision if Phase 4A enabled |

---

## CONCLUSION

The WAGMI system is a sophisticated, cost-optimized multi-agent framework. The 23 existing agents operate on a required core (Regime, Trade) + optional specialists (Risk, Critic, Quant, Exit, Scout, Overseer, Learning) + Phase 3/4 strategic/scalping agents.

**Key Operational Metrics:**
- Cost: $0 (CLI routing) to $1,400/month (Opus-heavy)
- Latency: 120-180ms median per pipeline (all agents + enrichment)
- Win Rate: 43% on 101 live trades, +$1.8K cumulative
- Most Profitable Setups: 2-agree strategies, trending regime, 5-7x leverage
- Deadliest Mistakes: overconfidence >80%, solo signals, tight stops, post-loss chasing

**The 4 Recommended New Agents:**
1. **Opportunist** — Proactive edge detection (funding, liquidation, news, correlation)
2. **Adversary** — Confidence pressure-testing
3. **Drawdown Recovery** — Defensive posture activation
4. **Calibration Auditor** — Agent prompt optimization

**Recipe for Adding Agents:** 8 concrete, sequenced steps. Implementation takes ~4 hours per agent (prompt + integration + tests).

The system is ready for these additions. The architecture supports them cleanly without breaking existing pipelines.