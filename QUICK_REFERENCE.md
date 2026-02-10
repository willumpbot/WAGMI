# WAGMI Bot - Quick Reference Cheat Sheet

**Print this and keep by your desk during validation period**

---

## DAILY COMMANDS

```bash
# START BOT (paper trading)
cd ~/WAGMI\ PROJECT/WAGMI/bot
python run.py paper

# CHECK PERFORMANCE (anytime)
python performance_reporter.py              # Overall stats
python performance_reporter.py --symbol BTC  # Just BTC
python performance_reporter.py --period 7   # Last 7 days

# VIEW DASHBOARD (real-time)
python simple_dashboard.py
# Then open http://localhost:5000

# ANALYZE SIGNALS (weekly)
python -m execution.signal_validator

# BACKTEST HISTORICAL (after 1 week)
python -m backtest.runner --days 30

# COMPARE PAPER VS BACKTEST (after backtest)
python -m backtest.runner --compare

# CHECK LOGS
tail -f logs/bot_$(date +%Y%m%d).log        # Live log
grep -i error logs/bot_$(date +%Y%m%d).log # Errors only
```

---

## BOT STATUS AT A GLANCE

**How to know if bot is working:**

1. **Check Process**
   ```bash
   ps aux | grep python  # Should see run.py or multi_strategy_main.py
   ```

2. **Check Logs** (should see new entries every 60s)
   ```bash
   tail -1 logs/bot_$(date +%Y%m%d).log
   # Should show: [scan N] with timestamps
   ```

3. **Check Prices** (should be recent)
   ```bash
   ls -lt paper_trades/*.csv | head -3
   # trades_*.csv should have recent timestamps
   ```

4. **Check Positions** (via dashboard)
   ```bash
   python simple_dashboard.py  # Shows current open positions
   ```

---

## PERFORMANCE INTERPRETATION

**Win Rates by Range:**

| Win Rate | Status | Action |
|----------|--------|--------|
| 70%+ | Excellent | Can go live soon |
| 60-70% | Very Good | Ready for live with 25% size |
| 55-60% | Good | Run another week, validate backtest |
| 50-55% | Marginal | Review signal_validator, might need tuning |
| < 50% | Bad | Don't go live, debug signals |

**Profit Factor (Win Value / Loss Value):**

| Ratio | Status |
|-------|--------|
| > 2.0 | Excellent (strong winners) |
| 1.5-2.0 | Very Good |
| 1.2-1.5 | Good |
| 1.0-1.2 | Marginal |
| < 1.0 | Losing (red flag) |

---

## SIGNAL QUALITY QUICK CHECK

After `python -m execution.signal_validator`:

**Best Case Scenario:**
```
WIN RATE BY REGIME:
  ⭐⭐⭐⭐⭐: 75%+ (strong alignment = high confidence)
  ⭐⭐⭐: 50-60% (moderate)
  ⭐: 30-40% (weak)
  
→ Higher regime = higher win rate = GOOD
```

**Red Flag:**
```
All regimes have same 50% win rate
→ Regime strength doesn't matter = signals not using regime properly
→ Debug: regime_trend.py or ensemble logic
```

---

## WHAT TO WATCH FOR

### Good Signs ✅
- Win rate steady, not declining
- Closed trades every day
- Recent P&L positive or breakeven
- No error messages in logs
- Positions closing correctly (via TP1, TP2, SL)

### Warning Signs ⚠️
- Win rate declining each day
- No new trades for 2+ days
- Large positions stuck open > 24h
- Errors in logs (check grep error)
- Dashboard not updating (last data > 5 min ago)

### Stop-Everything Signs 🛑
- Memory usage > 500MB (`top` or task manager)
- Bot process crashed (check logs)
- All positions losing money (equity declining)
- Last data fetch > 10 minutes ago
- Exchange connection errors (403, 429)

---

## QUICK DEBUGGING

**If win rate is bad (< 50%):**
```bash
# 1. Check signal consensus
python -m execution.signal_validator
# Look at: WIN RATE BY STRATEGY CONSENSUS
# If 2/4 agree is 40%, but 4/4 agree is 80%, raise min_votes_required

# 2. Check which symbols work
python -m execution.signal_validator | grep "BY SYMBOL"
# If BTC: 70%, ETH: 40%, SOL: 30%
# → Focus on BTC, disable SOL

# 3. Check regime alignment
python -m execution.signal_validator | grep "BY REGIME"
# If ⭐⭐⭐⭐⭐: 75%, ⭐: 25%
# → Only trade high-regime signals, skip weak regime
```

**If positions aren't closing:**
```bash
# Check logs for TP/SL messages
grep "TP1\|TP2\|SL" logs/bot_$(date +%Y%m%d).log

# Check position_manager logic is running
grep "update_price\|trailing" logs/bot_YYYYMMDD.log

# Last resort: manually close (in production)
# [Create manual_close.py script in execution/]
```

**If no new signals being generated:**
```bash
# 1. Check data is fetching
grep "fetch_multi_timeframe\|latest_price" logs/bot_*.log

# 2. Check strategies are running
grep "Regime Trend\|Monte Carlo\|ensemble" logs/bot_*.log

# 3. Check ensemble is voting
grep "num_agree\|HOLD\|WEAK" logs/bot_*.log

# 4. Check filters (risk mgr might be blocking)
grep "can_open_position\|circuit_breaker" logs/bot_*.log
```

---

## FILE LOCATIONS (QUICK REFERENCE)

```
Logs:
  ~/WAGMI\ PROJECT/WAGMI/logs/bot_YYYYMMDD.log

Paper Trades:
  ~/WAGMI\ PROJECT/WAGMI/paper_trades/signals_*.csv
  ~/WAGMI\ PROJECT/WAGMI/paper_trades/trades_*.csv

Backtest Results:
  ~/WAGMI\ PROJECT/WAGMI/backtest_results/backtest_*.json
  ~/WAGMI\ PROJECT/WAGMI/backtest_results/equity_*.csv

Configuration:
  ~/WAGMI\ PROJECT/WAGMI/bot/trading_config.py
  ~/.env  (API keys)

Source Code:
  ~/WAGMI\ PROJECT/WAGMI/bot/multi_strategy_main.py (main loop)
  ~/WAGMI\ PROJECT/WAGMI/bot/strategies/ (4 strategies)
  ~/WAGMI\ PROJECT/WAGMI/bot/execution/ (position management)
```

---

## COMMAND REFERENCE

### View Performance Over Time
```bash
# Daily trend
for i in {1..7}; do
  python performance_reporter.py --period $i | grep "Win Rate"
done

# By symbol over time
python performance_reporter.py --symbol BTC --period 7
python performance_reporter.py --symbol ETH --period 7
python performance_reporter.py --symbol SOL --period 7
```

### Export Data for Analysis
```bash
# Convert trades to CSV with extra columns
python -c "
import pandas as pd
df = pd.read_csv('paper_trades/trades_*.csv')  # latest file
df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
df['day'] = pd.to_datetime(df['timestamp']).dt.day_name()
df.to_csv('paper_trades/trades_detailed.csv')
"
# Now open in Excel/Google Sheets for pivot tables
```

### Monitor in Real-Time (Linux)
```bash
watch -n 5 'python performance_reporter.py'
# Updates every 5 seconds
# Press Ctrl+C to stop
```

---

## DECISION MATRIX: SHOULD I RESTART?

| Issue | Restart? | Why |
|-------|----------|-----|
| Win rate < 50% | No | Let it run longer, analyze signals |
| Memory > 500MB | Yes | Avoid crash, restart gracefully |
| No data > 5 min | Yes | Exchange connection hung |
| 100+ errors in logs | Yes | Unrecoverable state |
| Process crashed | Yes | Obviously |
| Single bad trade | No | Normal variance |
| 5 bad trades in a row | No | Trend, not crash (analyze) |

**Graceful Restart:**
```bash
# 1. Stop bot (Ctrl+C)
#    → Closes all positions
#    → Writes final logs
#    → Cleanly exits

# 2. Check everything closed
python -c "
from bot.execution.position_manager import PositionManager
pm = PositionManager()
positions = pm.get_open_positions()
print(f'Open positions: {len(positions)}')
"
#    → Should show: Open positions: 0

# 3. Restart
python run.py paper
```

---

## WEEK-BY-WEEK TIMELINE

### WEEK 1: COLLECT DATA
Days 1-3: Let it run, don't touch it
Days 4-5: Check daily, verify not crashing
Days 6-7: Analyze signals
- **Target:** 20+ closed trades

### WEEK 2: VALIDATE & DECIDE
Days 8-9: Backtest, compare to paper
Days 10-12: Deep signal analysis
Days 13-14: Final decision
- **Target:** 50+ total trades, clear performance picture

### DECISION POINT (End of Week 2)

✅ Win rate ≥ 55% AND backtest ≤ ±5% → **GO LIVE**
⚠️ Win rate 50-55% OR backtest ±5-10% → **RUN WEEK 3**
❌ Win rate < 50% OR backtest ±10%+ → **ANALYZE & DEBUG**

---

## KEYBOARD SHORTCUTS

```
Ctrl+C         Stop bot (graceful shutdown)
Ctrl+Z         Pause (and fg to resume)
tail -f        Live log tail (Ctrl+C to stop)
grep -i error  Search for errors
```

---

## HAVE YOU TRIED...

**Bot slow / unresponsive?**
- Reduce scan_interval_s from 60 to 30? (might hit rate limits)

**Too many signals / positions?**
- Raise min_votes_required from 2 to 3? (more selective)

**Not enough signals?**
- Lower min_votes_required from 2 to 1? (more permissive)

**Specific symbol losing money?**
- Disable it in DEFAULT_SYMBOLS in trading_config.py

**Positions closing too fast?**
- Check TP1 and TP2 prices (maybe too close to entry?)

**Positions holding too long?**
- Check trailing stop is activating after TP1

**Risk too high / losses too big?**
- Lower risk_per_trade from 0.015 to 0.01? (1% instead of 1.5%)

**Want to go live soon?**
- Set auto_trade=True in trading_config.py
- Start with position_size_multiplier=0.25 (25% of backtest size)

---

## SUPPORT

| Question | Answer | Command |
|----------|--------|---------|
| Is bot running? | Check process | `ps aux \| grep python` |
| Are prices updating? | Check log timestamps | `tail logs/bot_*.log` |
| How many trades? | Check report | `python performance_reporter.py` |
| Which signals work? | Analyze quality | `python -m execution.signal_validator` |
| Past performance? | Run backtest | `python -m backtest.runner --days 30` |
| Live or paper? | Check config | `grep environment bot/trading_config.py` |

---

**Print This Page**  
**Keep By Your Monitor**  
**Refer Often**

**Last Updated:** 2026-02-10  
**Valid For:** Week 1-2 of paper trading phase
