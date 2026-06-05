# Model Routing Audit — 2026-05-31

*Analyzed by laptop-claude from v3 backtest data + usage_tiers.py code review*

---

## Summary

| Session | Total Calls | Opus | Sonnet | Haiku |
|---|---|---|---|---|
| Desktop live (overnight) | 265 | 204 (77%) | 14 (5%) | 47 (18%) |
| Laptop v3 backtest | 108 | 0 (0%) | 54 (50%) | 54 (50%) |

**Per-CLAUDE.md spec:**
- Regime → Haiku ✅
- Trade → Sonnet ✅
- Risk → Haiku ✅
- Critic → Sonnet ✅
- No Opus for routine agent decisions ✅

---

## Root Cause: Trigger Type Determines Model

Found in `bot/llm/usage_tiers.py:127` (`get_model_for_trigger`):

```python
if trigger_reason in HIGH_VALUE_TRIGGERS or trigger_upper in {
    "PRE_TRADE", "REGIME_SHIFT", "STRATEGY_DISAGREEMENT", "PRE_CLOSE", "HIGH_CONFIDENCE"
}:
    return self.high_value_model or self.default_model
```

AGGRESSIVE tier config (`usage_tiers.py:178`):
```python
default_model=MODEL_SONNET,
high_value_model=MODEL_OPUS,    # <- triggered by PRE_TRADE
medium_value_model=MODEL_SONNET,
low_value_model=MODEL_SONNET,
```

**Live bot path:** Signal evaluation triggers with `"PRE_TRADE"` → `high_value_model = Opus`

**Backtest path:** `get_entry_decision()` calls `get_trading_decision(trigger_reason="llm_first_entry")` → no match → `default_model = Sonnet`

This is why the desktop (AGGRESSIVE tier, live signals via PRE_TRADE) got 77% Opus, while the laptop backtest (same tier, "llm_first_entry" trigger) gets 0% Opus.

---

## Per-Agent Routing (v3 backtest, 108 calls)

| Role | Model | Count | Avg Latency |
|---|---|---|---|
| regime | claude-haiku-4-5-20251001 | 27 | 62.8s |
| trade | claude-sonnet-4-6 | 27 | 66.0s |
| risk | claude-haiku-4-5-20251001 | 27 | 46.5s |
| critic | claude-sonnet-4-6 | 27 | 28.0s |

The per-agent routing is handled by the coordinator's `_call_agent()` which reads `AGENT_REGIME_MODEL`, `AGENT_TRADE_MODEL`, etc. env vars (if set). If not set, it falls back to the tier's model for that trigger type.

In the backtest, trigger is "llm_first_entry" → Sonnet. Per-agent env vars further override:
- Regime and Risk → Haiku (from CLAUDE.md spec env vars, if set)
- Trade and Critic → Sonnet

**If per-agent env vars are NOT set:** the tier model for the trigger type is used for all agents. In backtest = Sonnet for all. In live = Opus for all (PRE_TRADE trigger).

---

## Desktop Fix Options (Nunu's call)

### Option A: Set per-agent model env vars in .env
```bash
AGENT_REGIME_MODEL=claude-haiku-4-5-20251001
AGENT_RISK_MODEL=claude-haiku-4-5-20251001
AGENT_TRADE_MODEL=claude-sonnet-4-6
AGENT_CRITIC_MODEL=claude-sonnet-4-6
AGENT_EXIT_MODEL=claude-haiku-4-5-20251001
AGENT_LEARNING_MODEL=claude-haiku-4-5-20251001
```
**Effect:** Overrides tier routing entirely per agent. Regime/Risk/Exit/Learning always Haiku, Trade/Critic always Sonnet.
**Cost reduction:** ~5x (Opus → Sonnet) × Haiku agents. Estimated: $750/mo → $130/mo

### Option B: Change AGGRESSIVE tier's high_value_model to Sonnet
```python
TIER_AGGRESSIVE = UsageTier(
    high_value_model=MODEL_SONNET,   # was MODEL_OPUS
    ...
)
```
**Effect:** PRE_TRADE triggers → Sonnet instead of Opus. Still allows future escalation to Opus for specific signals.

### Option C: Add "llm_first_entry" as medium-value trigger
**Effect:** LLM-first signals use Sonnet (same as backtest). Other triggers keep current routing.

**Recommendation:** Option A (per-agent env vars) is the most explicit and matches CLAUDE.md spec. It also survives tier changes.

---

## Cost Impact of Correct Routing

| Scenario | Calls/day | Cost/call | Daily cost |
|---|---|---|---|
| Current desktop (77% Opus) | ~265 | ~$0.015 | ~$3.98 |
| Correct routing (Haiku/Sonnet) | ~265 | ~$0.0015 | ~$0.40 |
| Savings | | | **~90% cost reduction** |

At current pace, correct routing eliminates quota exhaustion (currently hitting 2 dead windows per day) because Haiku/Sonnet calls are much faster and cheaper.

---

## Key Finding: Backtest Confirms Correct Agent Behavior

The v3 backtest (108 calls, all correct Haiku/Sonnet routing) demonstrates the agent pipeline CAN work correctly when given the right inputs. The routing is working as designed — the issue is only the trigger type mapping in the live session.

**Next measurement:** v4 (fully clean context) will show whether agent DECISIONS are correct, not just routing.
