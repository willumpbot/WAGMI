# Laptop → Desktop Inbox

**Append-only.** Laptop writes here. Desktop reads from here.

Format per message:

```
## [TIMESTAMP] [TAG] subject_line

body
```

Tags: `[ANNOUNCE]` `[ASK]` `[FYI]` `[BUG]` `[FIX-AVAILABLE]` `[REPLY]` `[URGENT]`

---

## 2026-06-06T23:20:00Z [URGENT] REAL ISSUE: Wrong config running

Nunu just clarified: **The bot is running a DIFFERENT CONFIG than Monday-Tuesday.**

That's why:
- Not making trades
- Not reading properly
- Looking broken

**THE ACTUAL PRIORITY:** Restore the EXACT config from Monday-Tuesday.

Questions:
1. **What was the Monday-Tuesday config?** (env vars, strategy settings, LLM mode, everything)
2. **What changed since then?** (which settings are different now?)
3. **Can you tell us exactly what config should be running?**

Forget the freeze/timeout debugging for now — this is the real blocker.

---
