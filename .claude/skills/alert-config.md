# /alert-config — Configure and Test Discord/Telegram Alerts

## Description
Set up, verify, and tune the alert routing system across Discord webhooks, Telegram alerts, and the Telegram command bot. Test delivery, check rate limits, and diagnose alert failures.

## Arguments
- `$ARGUMENTS` — Optional: "setup" (full configuration), "test" (send test alerts), "status" (check health), "tune" (adjust rate limits/filters)

## Workflow

### 1. Configuration Inventory
Read `.env` and assess all alert-related config:

**Telegram Alerts:**
- `TELEGRAM_TOKEN` — Bot token (set/missing?)
- `TELEGRAM_CHAT_ID` — Target chat (set/missing?)
- `TELEGRAM_ALLOWED_USER_ID` — Security filter (set/missing?)

**Telegram Signal Monitoring:**
- `TELEGRAM_SIGNAL_TOKEN` — Separate token for signal channels (set/missing?)
- `TELEGRAM_SIGNAL_CHANNELS` — Channel IDs being monitored (list)

**Discord:**
- `DISCORD_WEBHOOK` — Main webhook URL (set/missing?)
- `DISCORD_WEBHOOK_PRIORITY` — Priority channel webhook (set/missing?)

Show what's configured and what's missing.

### 2. Alert Router Analysis
Read `bot/alerts/router.py` — AlertRouter class:

**Current Settings:**
- Priority threshold: confidence >= 75%
- Priority cooldown: 90 seconds
- Regular cooldown: 45 seconds
- Burst protection: max 5 priority alerts per symbol in 10 minutes
- Dedup: by signal fingerprint
- State persistence: `bot/data/alert_state.json`

**Alert Types:**
- `send_signal()` — Trading signals (BUY/SELL with confidence)
- `send_trade_event()` — OPEN, TP1, TP2, SL, TRAILING_STOP events
- `send_heartbeat()` — Periodic bot status
- `send_circuit_breaker()` — Safety alert when circuit breaker trips

### 3. Telegram Command Bot Status
Read `bot/alerts/telegram_bot.py` — TelegramCommandBot:

**Available Commands (50+):**
- Runtime: `/status`, `/positions`, `/close`, `/pause`, `/resume`, `/kill`, `/unkill`
- LLM: `/llm`, `/mode`, `/health`, `/uplift`, `/growth`
- Signals: `/signals`, `/analyze`, `/accuracy`
- Knowledge: `/roadmap`, `/curriculum`, `/knowledge`, `/promote`, `/demote`
- Meta: `/performance`, `/ml`, `/telemetry`, `/proposals`, `/ops`

**Security:** Only responds to `TELEGRAM_ALLOWED_USER_ID`
**Logging:** Commands logged to `data/logs/telegram.csv`

### 4. Setup Mode (if "setup")
Guide through full alert configuration:

1. **Telegram Bot:**
   - Instructions for creating bot via @BotFather
   - Getting chat ID (forward to @userinfobot or /getUpdates)
   - Getting user ID for security filter
   - Setting env vars

2. **Discord Webhooks:**
   - How to create webhook in Discord server settings
   - Recommend separate channels: #signals (regular) and #priority-signals
   - Setting env vars

3. **Verify connections:**
   - Test Telegram: send a test message
   - Test Discord: send a test webhook
   - Test command bot: send /status

### 5. Test Mode (if "test")
Send test alerts through each channel:

```python
# Test Telegram alert
from alerts.enhanced_telegram import format_signal_telegram
# Build mock signal and send

# Test Discord webhook
import requests
requests.post(DISCORD_WEBHOOK, json={"content": "Test alert from nunuIRL"})

# Test priority routing
# Build high-confidence mock signal, verify it goes to both channels
```

Verify:
- Telegram message received with correct formatting
- Discord embed renders properly
- Priority routing sends to both channels
- Rate limiting doesn't block first test message
- Burst protection doesn't block single test

### 6. Tune Mode (if "tune")
Analyze alert patterns and adjust:

**Alert Volume:**
- Read `bot/data/alert_state.json` — how many alerts per day?
- By type: signals, trade events, heartbeats, circuit breakers
- By priority: how many hit the priority channel?

**Rate Limit Analysis:**
- Are legitimate alerts being suppressed by cooldowns?
- Are duplicate alerts getting through despite dedup?
- Is burst protection too aggressive or too lenient?

**Recommendations:**
- Adjust cooldowns based on trading frequency
- Adjust priority threshold based on signal quality
- Add/remove alert types (e.g., disable heartbeat alerts if too noisy)

### 7. Enhanced Telegram Formatting Check
Read `bot/alerts/enhanced_telegram.py`:
- Signal format: confidence bar, strategy consensus, sizing guidance
- Trade event format: entry/exit, PnL, R-multiple
- Heartbeat format: positions, equity, uptime
- Daily report format: summary stats

Check for formatting issues:
- Long messages getting truncated?
- Special characters breaking Markdown?
- Numeric formatting correct?

### 8. Report
```
ALERT SYSTEM STATUS — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TELEGRAM
  Bot Token:          [SET/MISSING]
  Chat ID:            [SET/MISSING]
  User Security:      [SET/MISSING]
  Command Bot:        [RUNNING/STOPPED]
  Signal Monitor:     [ACTIVE (N channels)/NOT CONFIGURED]

DISCORD
  Main Webhook:       [SET/MISSING]
  Priority Webhook:   [SET/MISSING]

ALERT ROUTING:
  Priority Threshold: conf >= 75%
  Cooldowns:          90s priority, 45s regular
  Burst Protection:   5 per symbol per 10min

RECENT ACTIVITY (24h):
  Signals Sent:       N (N priority, N regular)
  Trade Events:       N
  Heartbeats:         N
  Circuit Breakers:   N
  Suppressed:         N (rate limit), N (dedup)

ISSUES: [None / List]
```
