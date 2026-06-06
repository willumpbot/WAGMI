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
