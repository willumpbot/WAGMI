# /add-agent — Full Agent Creation Workflow

## Description
Step-by-step guided workflow for adding a new specialist agent to the multi-agent LLM pipeline. Enforces all architectural constraints and generates boilerplate.

## Arguments
- `$ARGUMENTS` — Required: agent name and purpose (e.g., "Portfolio agent for cross-asset correlation")

## Workflow

### 1. Design Phase
Before writing any code, gather requirements:
- **Agent Name**: Extract from `$ARGUMENTS`
- **Purpose**: What unique capability does this agent add?
- **Pipeline Position**: Where in the chain? (after which existing agent?)
- **Model Tier**: Haiku ($0.0001), Sonnet ($0.003), or Opus ($0.015)?
- **Input Dependencies**: What upstream agent outputs does it need?
- **Output Contract**: What must it produce for downstream agents?

Ask the user to confirm these design decisions before proceeding.

### 2. Define Agent Role
Edit `bot/llm/agents/base.py`:
- Add new role to `AgentRole` enum
- Add default `AgentConfig` with:
  - `model`: default model tier
  - `max_tokens`: token budget (keep tight — Haiku=500, Sonnet=1000, Opus=2000)
  - `temperature`: 0.1-0.3 for trading decisions
  - `enabled`: True by default

### 3. Write Agent Prompt
Edit `bot/llm/agents/prompts.py`:
- Follow the **OBSERVE → RECALL → REASON → DECIDE → JUSTIFY** thought protocol
- Use the **shared vocabulary** exactly:
  - Regime names: `trend`, `range`, `panic`, `high_volatility`, `low_liquidity`, `news_dislocation`, `unknown`
  - Action names: `go`/`proceed`, `skip`/`flat`, `flip`/`reverse`
  - Confidence scale: 0-100 (integer)
- Output must be **valid JSON only** — no prose, no markdown
- Define the exact JSON schema the agent must return
- Include 2-3 few-shot examples in the prompt
- Stay under max_tokens budget

### 4. Wire into Coordinator
Edit `bot/llm/agents/coordinator.py`:
- Add `_build_<role>_input()` method — constructs agent's input from upstream outputs
- Add `_run_<role>_agent()` method — calls LLM client with prompt + input
- Add `_parse_<role>_output()` method — validates JSON response against schema
- Wire into the pipeline sequence in `run_pipeline()` method
- Handle failure gracefully (if agent fails, pipeline continues with degraded output)
- Update `_merge_outputs()` to include new agent's contribution

### 5. Add Environment Controls
- Add to `.env.example`:
  ```
  AGENT_<ROLE>_MODEL=           # Override model (haiku/sonnet/opus)
  AGENT_<ROLE>_ENABLED=true     # Enable/disable this agent
  ```
- Wire env vars in `bot/llm/agents/base.py` config loading

### 6. Wire Learning Integration
If the agent produces insights worth remembering:
- Edit `bot/llm/agents/learning_integration.py`
- Define what gets stored in deep memory vs short-term memory
- Add to hypothesis tracker if it generates testable hypotheses

### 7. Update Consistency Framework
- Edit `bot/llm/agents/shared_context.py` — add agent to shared context builder
- Edit `bot/llm/agents/consistency_checker.py` — add cross-validation rules for new agent
- Edit `bot/llm/agents/thought_protocol.py` — ensure protocol covers new agent's domain

### 8. Write Tests
Create tests in `bot/tests/test_multi_agent.py` (or new file if large enough):
- **Mock response test**: Agent returns valid JSON → pipeline proceeds
- **Invalid response test**: Agent returns garbage → pipeline degrades gracefully
- **Disabled test**: `AGENT_<ROLE>_ENABLED=false` → agent skipped, pipeline works
- **Consistency test**: New agent's output doesn't contradict upstream agents
- **Token budget test**: Verify prompt + response stays under max_tokens
- Run: `cd bot && pytest tests/ -k "agent or multi_agent" -v`

### 9. Update Documentation
- Update `CLAUDE.md` — add agent to Multi-Agent System section
- Update `.claude/rules/llm-agents.md` — add agent to architecture list
- Update `ROADMAP.md` if this was a planned item

### 10. Final Verification
- Run full test suite: `cd bot && pytest tests/ -x`
- Verify paper trading still works: `cd bot && python run.py signals`
- Check LLM cost estimate: new pipeline cost = old cost + agent cost per call
