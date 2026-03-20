# Phase 3: Operational Runbook

**Purpose:** Quick reference for Phase 3 operators
**Format:** Decision trees, troubleshooting guides, quick commands
**Audience:** DevOps, trading operations team

---

## Quick Decision Trees

### Scenario 1: Memory Usage Exceeds 100 MB

```
Memory > 100 MB detected
    ↓
Is memory still growing?
    ├─ YES → Likely TTL pruning not running
    │         FIX: Verify cron job: crontab -l
    │         OR: Manually run: python PHASE_3A_STAGING_MONITOR.py
    │
    └─ NO → Memory stable, acceptable (Phase 2 showed bounded growth)
            DECISION: Continue monitoring

Next step: Check memory growth rate
    ├─ >2 MB/hour → ALERT: Investigate leak
    └─ <1 MB/hour → OK: Expected behavior
```

### Scenario 2: No Trades Executed After 4 Hours

```
0 trades after 4 hours
    ↓
Check signal generation
    ├─ Signals being evaluated? → YES: Ensemble rejecting them
    │                               Check: tail -20 bot/data/logs/*.log | grep "ensemble"
    │
    └─ Signals not evaluated? → NO: Market data stale or signal pipeline broken
                                Check: curl https://api.hyperliquid.xyz/info (market data)
                                Check: grep "ERROR" bot/data/logs/*.log

DECISION:
    ├─ Ensemble bottleneck → Lower MIN_VOTES or increase confidence floor
    ├─ Market data stale → Check exchange API connectivity
    └─ Signal pipeline error → Check logs for exceptions
```

### Scenario 3: Circuit Breaker Keeps Tripping

```
CB tripped, recovered, tripped again
    ↓
Is it immediate re-trip after cooldown?
    ├─ YES → Peak equity reset bug (should be fixed)
    │         Verify: grep "peak_equity" bot/data/logs/*.log
    │         Check: Peak reset to current equity or old value?
    │
    └─ NO → Legitimate losses, system working correctly
            DECISION: Continue monitoring

If re-trips are legitimate:
    ├─ Increase daily loss limit (if small equity)
    ├─ Or: Reduce position size
    └─ Or: Tighten stop losses (reduce risk per trade)
```

### Scenario 4: Database Growing Faster Than Expected

```
Database > 20 MB after 12 hours
    ↓
Check if archival is running
    ├─ Is periodic_maintenance() running? YES → DB should be bounded
    │   If still growing, check: Is archival actually moving records?
    │   Test: sqlite3 bot/data/trades.db "SELECT COUNT(*) FROM signals_archive"
    │
    └─ Is periodic_maintenance() running? NO → Not scheduled
        FIX: Check cron job or schedule manually: crontab -e

If archival is running but DB still growing:
    ├─ Check signals table: SELECT COUNT(*) FROM signals
    └─ Compare to archive: SELECT COUNT(*) FROM signals_archive
        → If archive is empty, archival not working properly
```

### Scenario 5: LLM Responses Timing Out

```
LLM timeout detected
    ↓
Is LLM service available?
    ├─ YES → Likely high latency from Anthropic
    │         Check Anthropic status page
    │         Current timeout: 20 seconds
    │         Action: Can increase to 30s if needed
    │
    └─ NO → API key invalid or network blocked
            Check: Can you curl https://api.anthropic.com ?
            Fix: Verify ANTHROPIC_API_KEY in environment

If intermittent timeouts:
    └─ Expected during high load
        System falls back to mechanical-only
        Monitor: LLM failure rate should be <5%
```

---

## Common Commands Reference

### Health Checks

```bash
# Memory usage (should be <100 MB)
ps aux | grep 'python.*run.py' | grep -v grep | awk '{print $6 " MB"}'

# Database size (should be <20 MB)
du -m bot/data/trades.db

# Trade count
sqlite3 bot/data/trades.db "SELECT COUNT(*) FROM trades"

# Signal count
sqlite3 bot/data/trades.db "SELECT COUNT(*) FROM signals"

# Error count in last hour
grep ERROR bot/data/logs/*.log | tail -20

# Circuit breaker status
grep "Circuit breaker\|tripped\|cooldown" bot/data/logs/*.log | tail -10

# Last trade timestamp
tail -1 bot/data/trades.csv | awk -F, '{print $1}'

# LLM decision rate
wc -l bot/data/llm/decisions.jsonl

# Current PnL
tail -100 bot/data/trades.csv | awk -F, '{sum+=$NF} END {print "Total PnL: $" sum}'
```

### Monitoring Snapshots

```bash
# Take hourly snapshot (can be in cron)
python PHASE_3A_STAGING_MONITOR.py

# View metrics report
cat PHASE_3A_METRICS.json | python -m json.tool | head -50

# Watch memory in real-time
watch -n 5 'ps aux | grep python | grep run.py | awk "{print $6}"'

# Watch database in real-time
watch -n 5 'du -m bot/data/trades.db && sqlite3 bot/data/trades.db "SELECT COUNT(*) FROM trades"'

# Real-time error monitoring
tail -f bot/data/logs/*.log | grep ERROR
```

### Troubleshooting

```bash
# Check all critical files exist
ls -lh bot/execution/risk.py bot/llm/deep_memory.py bot/core/signal_pipeline.py bot/data/db.py

# Verify Phase 2 fixes are in code
grep -n "peak_equity reset\|prune_by_ttl\|slippage.*40\|validate_stop_vs_liquidation\|archive_old_records" bot/execution/risk.py bot/llm/deep_memory.py bot/core/signal_pipeline.py bot/data/db.py

# Check for recent errors
grep -i "error\|exception\|fail" bot/data/logs/*.log | tail -50

# Database integrity check
sqlite3 bot/data/trades.db "PRAGMA integrity_check"

# Verify exchange connectivity
python -c "from data.fetcher import ExchangeFetcher; print(ExchangeFetcher().get_balance())"

# Verify LLM connectivity
python -c "from llm.client import get_anthropic_client; print('LLM OK')"
```

### Emergency Procedures

```bash
# Stop bot immediately
killall python
# or: kill -9 $(pgrep -f "python.*run.py")

# Backup database before anything else
cp bot/data/trades.db bot/data/trades.db.backup.$(date +%s)

# Backup logs
tar czf logs_backup_$(date +%s).tar.gz bot/data/logs/

# Clear problematic logs (if disk full)
rm bot/data/logs/*.log

# Reset circuit breaker (manual override - use with caution)
sqlite3 bot/data/trades.db "DELETE FROM circuit_breaker_state"

# Force reconciliation on next start
rm bot/data/.reconciliation_complete

# Start in paper mode (safe)
ENVIRONMENT=paper python run.py paper
```

---

## Alert Thresholds & Actions

| Alert | Threshold | Action |
|-------|-----------|--------|
| Memory exceeds 100 MB | RAM > 100 MB | Check TTL pruning, verify no leak |
| Database exceeds 20 MB | DB > 20 MB | Verify archival running |
| No trades in 4h | trades=0 @ T+4h | Check signal pipeline, ensemble |
| CB false re-trips | CB trips >3x/hour | Verify peak equity reset logic |
| LLM timeouts >5% | timeout_rate > 5% | Check Anthropic API, increase timeout |
| Database errors | DB unavailable | Check disk space, permissions, corruption |
| Zero ERROR logs | errors=0 (good!) | Normal, keep monitoring |
| High error rate | errors>10/hour | Investigate log, likely API issue |

---

## Daily Operational Checklist

### Every Hour (Automated)
- [ ] Memory usage snapshot (auto via monitor script)
- [ ] Database size check (auto)
- [ ] Trade count check (auto)
- [ ] Error log scan (auto)

### Every 4 Hours (Manual Check)
- [ ] Verify at least 1 trade executed
- [ ] Review error logs for patterns
- [ ] Check LLM response times
- [ ] Verify circuit breaker not stuck

### Every 12 Hours (Deep Review)
- [ ] PnL summary (profitable/losing trades)
- [ ] Position analysis (symbols, leverage distribution)
- [ ] Database archival check (old records moved)
- [ ] Memory growth rate analysis

### Daily (End of Day)
- [ ] Generate daily report
- [ ] Compare metrics to Phase 3A baseline
- [ ] Document any anomalies
- [ ] Verify all success criteria met

---

## Phase 3A → Phase 3B-1 Transition

### At T+24h (Phase 3A Complete)

**Success Criteria Check:**
```bash
# Run final verification
python PHASE_3A_STAGING_MONITOR.py

# Check all 12 success criteria met
sqlite3 bot/data/trades.db "
  SELECT
    COUNT(*) as trade_count,
    (SELECT COUNT(*) FROM signals) as signal_count,
    (SELECT COUNT(*) FROM signals_archive) as archive_count
"

# Verify memory and DB bounded
du -m bot/data/trades.db
ps aux | grep python | grep run.py | awk '{print $6}'
```

**If ALL criteria passed:**
1. Generate Phase 3A report
2. Create backup: `tar czf phase3a_complete_$(date +%s).tar.gz bot/data/`
3. Proceed to Phase 3B-1 (production)

**If ANY criteria failed:**
1. Investigate failure
2. Document issue
3. Apply fix
4. Retry Phase 3A

---

## Phase 3B-1 → Phase 3B-2 Transition

### At T+48h (Phase 3B-1 Complete)

**Additional Production Checks:**
```bash
# Verify exchange trading
sqlite3 bot/data/trades.db "SELECT symbol, COUNT(*), SUM(pnl) FROM trades GROUP BY symbol"

# Check slippage metrics
tail -50 bot/data/trades.csv | awk -F, '{slippage+=$8} END {print "Avg slippage: " slippage/NR " bps"}'

# Verify liquidation checks prevented unsafe positions
grep "liquidation\|SL.*beyond" bot/data/logs/*.log | wc -l

# Check leverage distribution
sqlite3 bot/data/trades.db "SELECT symbol, MAX(leverage) FROM trades GROUP BY symbol"
```

**If stable:**
1. Approve Phase 3B-2 (full scale)
2. Gradually add symbols
3. Monitor portfolio effects

**If issues:**
1. Stay on 1-2 symbols
2. Investigate
3. Fix before scaling

---

## Handoff Documentation

### For Next Shift
Create daily handoff document:

```markdown
## Phase 3 Operations Handoff

**Date:** YYYY-MM-DD
**Previous Status:** [Phase 3A/3B-1/3B-2]
**Current Time:** T+XX hours

### Metrics Summary
- Memory: XX MB (trend: ↑/→/↓)
- Database: XX MB (trend: ↑/→/↓)
- Trades: XX executed (win rate: XX%)
- Errors: XX error logs (critical: 0)

### Alerts Triggered
- [ ] Memory exceeded
- [ ] Database exceeded
- [ ] CB re-tripping
- [ ] LLM timeout
- [ ] Trade failed

### Actions Taken
1. ...
2. ...
3. ...

### Recommendations for Next Shift
- Continue monitoring [metric]
- Investigate [issue]
- Apply [fix] if ready
- Proceed to [next phase] when ready

### Contact Info
- On-call: [name]
- Escalation: [email/phone]
- Runbook: /home/user/WAGMI/PHASE_3_OPERATIONAL_RUNBOOK.md
```

---

## Summary

**This runbook provides:**
- ✅ Quick decision trees for common scenarios
- ✅ Essential health check commands
- ✅ Alert thresholds and actions
- ✅ Emergency procedures
- ✅ Daily operation checklists
- ✅ Transition guidelines between phases
- ✅ Handoff documentation template

**Use this as reference during Phase 3A, 3B-1, 3B-2 execution.**

---

**Created:** 2026-03-20 23:50 UTC
**For:** Phase 3 Operations Team
