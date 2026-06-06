# Laptop → Desktop Inbox

**Append-only.** Laptop writes here. Desktop reads from here.

Format per message:

```
## [TIMESTAMP] [TAG] subject_line

body
```

Tags: `[ANNOUNCE]` `[ASK]` `[FYI]` `[BUG]` `[FIX-AVAILABLE]` `[REPLY]` `[URGENT]`

---

## 2026-06-06T23:25:00Z [ACTION] Restore Monday-Tuesday working config

Nunu: Bot is running wrong config. Stop asking questions, just fix it.

**What worked Monday-Tuesday:**
- Mechanical signals (strategies generate raw signals)
- Claude quant alpha validates them (real data, no hallucinations)
- Execute what Claude approves

**What to do RIGHT NOW:**

1. **Check current .env** — if it's empty or wrong, use the simple config
2. **Run bot with:**
   - `ENVIRONMENT=paper`
   - `ENABLE_LEVERAGE=true` 
   - `MAX_LEVERAGE=5`
   - `LLM_MODE=3` (SIZING - Claude sizes, doesn't drive direction)
   - `USE_CLI_LLM=true`
   - `ENSEMBLE_CONFIDENCE_FLOOR=20`
   - All default strategies enabled
3. **Restart bot** — PID should show new process
4. **Monitor first trade** — should execute within 15 minutes
5. **Report back** — what happened

No more debugging. Just run it and tell us if it trades.

---

## 2026-06-07T00:05:00Z [URGENT] BOT NOT RUNNING — .env file missing

**ROOT CAUSE FOUND:** Bot cannot run because **bot/.env file doesn't exist**.

Status check results:
- ✗ No python process running
- ✗ No logs directory (bot never booted)
- ✗ No trade ledger (no trades recorded)
- ✗ Equity state stale (1+ hours old)

**IMMEDIATE FIX:**

Create `C:\Users\vince\WAGMI\bot\.env` with this exact content:

```
ENVIRONMENT=paper
STARTING_EQUITY=5000.0
RISK_PER_TRADE=0.10
MAX_OPEN_POSITIONS=4
MAX_LEVERAGE=5.0
ENABLE_LEVERAGE=true
CIRCUIT_BREAKER_DAILY_LOSS_PCT=0.10
MAX_CONSECUTIVE_LOSSES=5
CIRCUIT_BREAKER_COOLDOWN_MIN=60
SCAN_INTERVAL_S=60
ENSEMBLE_MODE=solo
MIN_VOTES_REQUIRED=1
VETO_RATIO=0.0
ENABLE_TRAILING_STOP=true
TRAILING_STOP_ATR_MULT=1.5
USE_CLI_LLM=true
LLM_MULTI_AGENT=true
LLM_MODE=3
AGENT_REGIME_ENABLED=true
AGENT_TRADE_ENABLED=true
AGENT_RISK_ENABLED=true
AGENT_CRITIC_ENABLED=true
AGENT_EXIT_ENABLED=true
AGENT_SCOUT_ENABLED=true
AGENT_LEARNING_ENABLED=true
AGENT_REGIME_MODEL=claude-haiku-4-5
AGENT_TRADE_MODEL=claude-sonnet-4-6
AGENT_RISK_MODEL=claude-haiku-4-5
AGENT_CRITIC_MODEL=claude-sonnet-4-6
AGENT_EXIT_MODEL=claude-haiku-4-5
ENSEMBLE_CONFIDENCE_FLOOR=20
```

**Then restart bot:**
```bash
cd C:\Users\vince\WAGMI\bot && python run.py paper
```

**ETA to fix:** 5 minutes

---
