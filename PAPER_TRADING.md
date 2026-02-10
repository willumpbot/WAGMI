## Paper Trading & Backtesting Guide

You now have a complete system to validate strategy performance over the next 2 weeks:

### 1. **Paper Trading (Live Signals)**

The bot is already running and logging every signal + trade to CSV files. No setup needed—it just works.

**What gets logged:**
- `paper_trades/signals_YYYYMMDD_HHMMSS.csv` - Every signal generated (entry, stop, targets, confidence, regime align)
- `paper_trades/trades_YYYYMMDD_HHMMSS.csv` - Every trade action (open, TP1, TP2, SL, trailing stop, PnL)

### 2. **View Performance (Anytime)**

Run this to see your current paper trading stats:

```bash
python performance_reporter.py
```

**Options:**
```bash
# Last 7 days only
python performance_reporter.py --period 7

# BTC trades only
python performance_reporter.py --symbol BTC

# Latest 3 days, SOL only
python performance_reporter.py --period 3 --symbol SOL
```

**Output:**
- Total trades, win rate, P&L
- Average win/loss, profit factor
- Win rate by symbol
- Win rate by exit type (TP1 vs TP2 vs SL vs trailing stop)

### 3. **Backtest Historical Data**

Test the ensemble strategy on 30+ days of historical data to validate signals:

```bash
# Basic: test all symbols, 30 days of history
python -m backtest.runner --days 30

# Specific symbols
python -m backtest.runner --symbols BTC ETH SOL --days 30

# Longer test with custom starting equity
python -m backtest.runner --days 60 --equity 100000 --risk 1.5
```

**Output:**
- Equity curve (CSV + chart)
- Win rate, total trades, profit factor
- P&L breakdown
- Saved to `backtest_results/`

### 4. **Compare Paper vs Backtest**

After running backtest, compare live signals to historical performance:

```bash
python -m backtest.runner --compare
```

**What it shows:**
- Paper trading win rate vs backtest win rate
- If paper trading is beating/matching/underperforming backtest
- Confidence in live signals

---

## Workflow (Next 2 Weeks)

**Days 1-3:**
- Run paper trading, let signals flow
- Run `performance_reporter.py` daily to track wins/losses
- Check `/paper_trades/` CSV files to analyze individual trades

**Days 4-7:**
- Run backtest: `python -m backtest.runner --days 30`
- Compare: `python -m backtest.runner --compare`
- Validate: Does live trading match historical performance?

**Days 8-14:**
- Continue logging paper trades
- Run performance_reporter weekly
- Identify which symbols/strategies are working
- Use data to refine entry/exit logic

---

## Example: Full Analysis Loop

```bash
# 1. Check recent paper trading
python performance_reporter.py --period 3

# 2. Backtest on same timeframe
python -m backtest.runner --days 30

# 3. Compare
python -m backtest.runner --compare

# 4. Drill into specific symbol
python performance_reporter.py --symbol BTC --period 7
```

---

## File Locations

```
bot/
├── paper_trades/              # Your live signal + trade logs
│   ├── signals_*.csv          # Every signal generated
│   └── trades_*.csv           # Every trade closed
├── backtest_results/          # Your backtest results
│   ├── backtest_*.json        # Full backtest output
│   └── equity_*.csv           # Equity curve
├── performance_reporter.py    # Run to view stats
└── backtest/runner.py         # Run backtests
```

---

## What You're Validating

Over the next 2 weeks, you'll verify:

✅ **Signal Quality** - Do the ensemble signals work in real market conditions?
✅ **Symbol Selection** - Which assets trade best with this strategy?
✅ **Risk Management** - Is 1.5% risk per trade appropriate?
✅ **Exit Timing** - Do TP1/TP2/trailing stops work as designed?
✅ **ML Adjustment** - Is ML confidence adjustment helping or hurting?

After 2 weeks of data, you'll have:
- Real win rates, P&L curves
- Data to decide: auto-execute or stay manual
- Confidence to tune parameters for live trading
