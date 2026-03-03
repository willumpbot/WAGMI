# LLM Agent Development Rules

## Architecture Awareness
You are working on a **multi-agent LLM trading system** with 5 specialist agents:
1. **Regime Agent** (Haiku) — classifies market regime
2. **Trade Agent** (Sonnet) — decides go/skip/flip
3. **Risk Agent** (Haiku) — sizes positions, flags risks
4. **Critic Agent** (Sonnet) — reviews decisions, approves/challenges
5. **Learning Agent** (Haiku) — extracts lessons from closed trades

These agents are orchestrated by `bot/llm/agents/coordinator.py` in a sequential pipeline.

## Key Files
- `bot/llm/agents/base.py` — AgentRole, AgentOutput, AgentConfig types
- `bot/llm/agents/coordinator.py` — Pipeline orchestration and output merging
- `bot/llm/agents/prompts.py` — All 5 agent prompts (REGIME/TRADE/RISK/LEARNING/CRITIC)
- `bot/llm/agents/learning_integration.py` — Wires agent output to deep memory, hypotheses, knowledge
- `bot/llm/agents/shared_context.py` — Shared reasoning framework (if exists)
- `bot/llm/agents/thought_protocol.py` — Structured reasoning template (if exists)
- `bot/llm/agents/consistency_checker.py` — Cross-agent coherence validation (if exists)
- `bot/llm/decision_engine.py` — Monolithic fallback pipeline
- `bot/llm/usage_tiers.py` — Model routing (Haiku/Sonnet/Opus per trigger)
- `bot/llm/client.py` — Raw Anthropic API wrapper

## Rules for Agent Modifications

### Prompt Changes
- ALL agents must use the **same vocabulary** for regime names: `trend`, `range`, `panic`, `high_volatility`, `low_liquidity`, `news_dislocation`, `unknown`
- ALL agents must use the **same action vocabulary**: `go`/`proceed`, `skip`/`flat`, `flip`/`reverse`
- ALL agents must output **valid JSON only** — no prose, no markdown outside code fences
- Keep prompts **token-efficient** — each agent should stay under its max_tokens budget
- When modifying one agent's prompt, check if the change affects downstream agents' expectations

### Consistency Requirements
- Regime Agent's output format MUST match what Trade Agent expects in `regime_analysis`
- Trade Agent's output format MUST match what Risk Agent expects in `trade_decision`
- Risk Agent's output format MUST match what Critic Agent expects in `risk_assessment`
- The merger in `coordinator.py:_merge_outputs()` must handle all possible output variations

### Shared Reasoning Protocol
All agents should follow this reasoning chain (when applicable):
1. **OBSERVE**: What does the data say? (cite specific numbers)
2. **RECALL**: What does memory/history say about similar situations?
3. **REASON**: Given observation + recall, what's the logical conclusion?
4. **DECIDE**: What action follows from the reasoning?
5. **JUSTIFY**: Why this action and not the alternatives?

### Safety Rules
- NEVER remove risk gating from the pipeline
- NEVER allow agents to bypass circuit breakers
- NEVER hardcode API keys or secrets in prompts
- The Critic Agent's veto power must always be respected
- Learning Agent must NEVER modify trading behavior directly — only through memory/knowledge updates

### Testing
- After modifying agent prompts, run: `cd bot && pytest tests/ -k "agent or multi_agent"`
- After modifying coordinator logic, run the full test suite
- Mock LLM responses for deterministic testing (use `bot/llm/test_harness.py`)

## Cost Awareness
- Haiku agents: ~$0.0001/call — can run frequently
- Sonnet agents: ~$0.003/call — moderate frequency
- Opus agents: ~$0.015/call — use sparingly
- Total multi-agent pipeline: ~$0.007/decision cycle
- Monitor via `bot/llm/cost_tracker.py`
