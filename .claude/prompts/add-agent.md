# Prompt: Add a New Specialist Agent

When adding a new agent to the multi-agent pipeline:

## Checklist
1. Define the agent's role in `bot/llm/agents/base.py`:
   - Add to `AgentRole` enum
   - Add default `AgentConfig` in `DEFAULT_AGENT_CONFIGS`

2. Write the agent's prompt in `bot/llm/agents/prompts.py`:
   - Follow the shared reasoning protocol: OBSERVE → RECALL → REASON → DECIDE → JUSTIFY
   - Use the shared vocabulary (regime names, action names)
   - Specify JSON-only output format
   - Keep within token budget (512 for Haiku agents, 1024 for Sonnet)
   - Add to `AGENT_PROMPTS` registry

3. Wire into coordinator (`bot/llm/agents/coordinator.py`):
   - Add `_build_<role>_input()` method
   - Add step in `get_trading_decision()` pipeline
   - Update `_merge_outputs()` if the agent produces decision-modifying output
   - Handle failure gracefully (required vs optional agent)

4. Add environment variable controls:
   - `AGENT_<ROLE>_MODEL` for model override
   - `AGENT_<ROLE>_ENABLED` for enable/disable
   - Update `_build_configs_from_env()`

5. Add to `.env.example`:
   - Document the new agent's env vars

6. Update learning integration (`bot/llm/agents/learning_integration.py`):
   - If the agent produces learning-relevant output, wire it to deep memory/hypotheses

7. Write tests:
   - Mock the agent's LLM response
   - Test pipeline with agent enabled and disabled
   - Test failure handling

8. Update documentation:
   - Update CLAUDE.md architecture section
   - Update ROADMAP.md agent inventory
   - Update `.claude/rules/llm-agents.md`
