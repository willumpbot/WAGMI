# /health-check — Bot Health and Anomaly Audit

## Description
Comprehensive health check of the trading bot — data freshness, memory state, error rates, position status, and anomaly detection. Quick diagnostic for "is everything OK?"

## Arguments
- `$ARGUMENTS` — Optional: "quick" (just status), "deep" (full audit), or specific area ("data", "llm", "positions", "memory")

## Workflow

### 1. System Status
Check if the bot process is running:
```bash
ps aux | grep "run.py\|multi_strategy_main" | grep -v grep
```
- Running → show PID, uptime, memory usage
- Not running → flag and show when it last ran

Check heartbeat:
- Read `bot/data/heartbeat.json` if it exists
- Last heartbeat age: <1min = healthy, 1-5min = warning, >5min = stale

### 2. Data Health
Check data freshness and integrity:
- Read latest entries from `bot/data/trades.csv` — when was last trade?
- Read latest entries from `bot/data/llm/decisions.jsonl` — when was last LLM decision?
- Check OHLCV data age: is the latest candle <5 minutes old?
- Check SQLite DB: `bot/data/db.py` — any corruption or lock issues?

Flag:
- Data gaps (missing candles)
- Stale data (>5min old)
- Growing backlog (decisions piling up without trades)

### 3. Position Status
Read current positions:
- Open positions: symbol, side, size, entry, current PnL, time held
- Position manager state: IDLE/OPEN/TP1_HIT/TRAILING/CLOSED
- Any stuck positions? (state hasn't changed in >24h)
- Any positions approaching liquidation?

### 4. Risk Gate Status
Check circuit breakers:
- Daily loss status: current drawdown vs daily limit
- Consecutive losses: current streak vs max allowed
- Is the bot in a "paused" state from circuit breaker activation?
- Any risk gate overrides active?

### 5. LLM Health (if enabled)
- Read `bot/llm/cost_tracker.py` data — today's spend, trend
- Last LLM call: when, which model, success/failure
- Error rate: last 24h API failures
- Token usage: are agents hitting max_tokens?
- Memory health: `bot/data/llm/llm_memory.json` — note count vs limit, oldest note age

### 6. Error Scan
Scan recent logs for issues:
- Read `bot/data/llm/operator_messages.json` for warnings/errors
- Check for repeated errors (same error >3 times = systemic issue)
- Check for new error types not seen before

### 7. Performance Snapshot
Quick performance metrics:
- Last 24h: trades, wins, losses, PnL
- Last 7d: trades, wins, losses, PnL, win rate, avg R
- Current regime classification
- Strategy agreement level (are strategies aligned or conflicted?)

### 8. Anomaly Detection
Run `bot/scripts/verify_csvs.py` checks:
- PnL math verification (entry/exit/size = correct PnL?)
- Trade classification consistency
- Any impossible values (negative size, future dates, etc.)

### 9. Health Report
```
BOT HEALTH CHECK — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Process:      Running (PID 12345, up 4h23m) ✓
Data:         Fresh (last candle 42s ago) ✓
Positions:    1 open (BTC LONG +$234) ✓
Risk Gates:   All active, 2/5 loss streak ⚠
LLM:          Connected, $0.42 spent today ✓
Memory:       47/100 notes, oldest 36h ✓
Errors:       0 in last 24h ✓
Performance:  7W/3L (70%), +$1,234 this week ✓

WARNINGS:
⚠ Loss streak at 2/5 — one more loss before cooldown
⚠ Memory nearing 50% capacity — consider pruning

OVERALL: HEALTHY
```

Severity levels:
- **HEALTHY**: All green, no action needed
- **WARNING**: Minor issues, monitor closely
- **DEGRADED**: Some systems impaired, investigate soon
- **CRITICAL**: Immediate action needed (data stale, positions at risk, etc.)
