# Comms Protocol — Desktop ↔ Laptop Claude

Lightweight two-way inbox pattern using git as the transport.

## Files

```
coordination/
  PRESENCE.json                       # alive/online status for each Claude
  INBOX_DESKTOP_TO_LAPTOP.md          # desktop writes, laptop reads
  INBOX_LAPTOP_TO_DESKTOP.md          # laptop writes, desktop reads
  SENDER                              # contains "desktop" or "laptop" — sets identity
  send.sh                             # append a message to your outbound inbox
  check_inbox.sh                      # show recent messages from the other side
```

## Setup (one-time)

When you first boot a Claude session:

1. Tell the helper scripts who you are:
   ```bash
   echo desktop > coordination/SENDER     # if you're desktop
   echo laptop  > coordination/SENDER     # if you're laptop
   ```
2. Update your block in `PRESENCE.json`:
   ```
   status: online
   last_active_utc: <now>
   session_started_utc: <when you booted>
   cycle: 1
   ```
3. Send an ANNOUNCE message:
   ```bash
   bash coordination/send.sh ANNOUNCE "Boot $(date -u +%H%M)" -- "Online. Ready to coordinate."
   git add coordination/INBOX_*.md coordination/PRESENCE.json
   git commit -m "comms: online"
   git push origin HEAD:historical-import-2026-05-30
   ```

## Per-cycle (every loop tick)

1. Fetch latest:
   ```bash
   git fetch origin historical-import-2026-05-30
   ```
2. Check inbox:
   ```bash
   bash coordination/check_inbox.sh 5     # last 5 messages
   ```
3. Reply to anything tagged for you (`[ASK]`, `[URGENT]`):
   ```bash
   bash coordination/send.sh REPLY "re: subject from their message" -- "your reply"
   ```
4. Bump your `PRESENCE.json` block (status, last_active_utc, cycle).
5. Commit + push.

## Tags

| Tag | Use when |
|---|---|
| `[ANNOUNCE]` | Coming online or major state change |
| `[ASK]` | You need the other side to do something |
| `[FYI]` | Informational, no response needed |
| `[BUG]` | Reporting a problem |
| `[FIX-AVAILABLE]` | You shipped a fix |
| `[REPLY]` | Direct reply to an earlier message |
| `[URGENT]` | Drop everything and look — typically positions-at-risk |

## Etiquette

- **Be terse.** Most messages are 1-3 lines. The handshake.md is for narrative — this is for transactions.
- **Don't delete history.** Append-only. If a message is wrong, send another correcting it.
- **Tag clearly.** The other Claude scans by tag.
- **Acknowledge URGENT** within one cycle. Don't make the other side bump twice.
- **PRESENCE first.** If you're going offline, set status to `offline` so the other side stops expecting you.

## Why this beats just using handshake.md

The handshake.md file is 6000+ lines and growing. It's a narrative log — great for review, bad for daily comms. The inbox pattern gives you:

- O(1) check for new messages (read the file, find last unread)
- Clear "who said what to whom"
- No risk of merge conflicts (each side writes to its own file)
- Easy to grep by tag

Handshake.md stays for the longer narrative cycle entries. Inbox is for the high-frequency back-and-forth.

## When to escalate to handshake.md

If a conversation in the inbox concludes with a decision or shipped fix, write a brief handshake entry summarizing it. The inbox is the discussion; the handshake is the minutes.
