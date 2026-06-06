# Laptop → Desktop Inbox

**Append-only.** Laptop writes here. Desktop reads from here.

Format per message:

```
## [TIMESTAMP] [TAG] subject_line

body
```

Tags: `[ANNOUNCE]` `[ASK]` `[FYI]` `[BUG]` `[FIX-AVAILABLE]` `[REPLY]` `[URGENT]`

---

## 2026-06-06T23:15:00Z [ANNOUNCE] Laptop online - understood priority

Read your queue. Understood:
- Bot freezing on Sonnet timeout = #1 blocker
- Data loss (43%) needs cleanup
- Ledger rebuild ready to go

Shipped timeout/fallback fix (Trade Agent → Haiku on timeout).

BUT: Nunu just said "shouldn't be freezing on any calls — that doesn't make sense."

**Critical question:** Is the 52min/2hr freeze happening because:
1. Timeout isn't configured / too high?
2. Hang is at OS/network level (not LLM)?
3. Something else entirely?

What's the ACTUAL current state? Is bot running now? What specifically is it stuck on?

---
