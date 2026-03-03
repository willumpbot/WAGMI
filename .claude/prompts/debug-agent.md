# Prompt: Debug an Agent Decision

When investigating why an agent made a bad decision:

## Investigation Steps

1. **Check the audit log**: `bot/data/llm/decisions.jsonl`
   - Find the decision by timestamp
   - Look at: action, confidence, regime, notes
   - Check if `[MA]` prefix is present (multi-agent) or not (monolithic)

2. **Check what the agent received**:
   - The coordinator builds input via `_build_<role>_input()` methods
   - Add temporary logging to see the exact JSON sent to each agent
   - Verify the snapshot data was accurate at decision time

3. **Check agent-specific issues**:
   - **Regime Agent wrong**: Was the data sufficient? Check volume, OI, funding data presence
   - **Trade Agent wrong**: Did it ignore regime_analysis? Check if memory contradicted the setup
   - **Risk Agent wrong**: Were portfolio stats accurate? Check corr_risk, port_lev values
   - **Critic missed it**: Did it have self_perf data? Check recent_dec for consistency context
   - **Learning Agent shallow**: Was trade_data complete? Check prior_lessons for duplicates

4. **Check the merge**:
   - `_merge_outputs()` has a priority chain: Critic > Risk > Trade > Regime
   - A Critic challenge can override the Trade Agent's action
   - Risk override="skip" forces flat
   - Verify the merge produced the expected result

5. **Check cost/model routing**:
   - Was the right model used? Haiku for routine, Sonnet for decisions
   - Did cost_tracker downgrade the model?
   - Was the agent within its token budget?

6. **Common failure modes**:
   - JSON parse failure → agent returned prose instead of JSON
   - Timeout → agent took too long (check config.timeout_s)
   - Conflicting signals → regime says panic, trade says go
   - Stale data → snapshot built from old candles
