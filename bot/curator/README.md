# Signal Curator & Execution Tracker

A system for ranking daily trading signals and measuring real alpha on ask/receive execution basis.

## Purpose

Transform the 10 signals/day your bot generates into **consistent manual trading process** with quantified execution quality:

1. **Signal Curator**: Ranks daily signals by confidence, setup type historical WR, and multi-strategy agreement
2. **Execution Tracker**: Records manual fills and measures execution alpha decomposition
3. **Daily Reports**: Shows execution quality, by-symbol metrics, by-setup metrics

## Architecture

```
Bot generates signals → Curator ranks them → You execute manually → Tracker measures alpha
     (9.6/day)         (top 3-5)              (10 fills/month)      (real alpha on ask/rcv)
```

### Signal Ranker (`signal_ranker.py`)

**Input**: `bot/data/llm/decisions.jsonl` (all signals)

**Processing**:
- Scores each signal by:
  - Base confidence (0-100)
  - Time-of-day edge (+15% boost for 6-12 UTC morning edge)
  - Multi-strategy agreement (+15% per agreeing strategy, up to +60% for 4-agree)
  - Regime alignment (confidence boosted in matching regimes)
  - Historical win rate by setup type (from backtest feedback)
- Final score = 60% adjusted confidence + 40% historical WR

**Output**: `CURATOR_DAILY_SIGNALS.json`

```json
{
  "generated_at": "2026-04-28T22:45:00+00:00",
  "total_signals_ranked": 24,
  "top_signals": [
    {
      "rank": 1,
      "symbol": "BTC",
      "side": "SELL",
      "confidence": 72.4,
      "entry_price": 45632.50,
      "stop_loss": 46200.00,
      "target_1": 44800.00,
      "target_2": 44000.00,
      "atr": 298.45,
      "setup_type": "trend_follow",
      "strategy": "regime_trend",
      "regime": "trend",
      "num_agree": 2,
      "risk_reward_ratio": 1.85,
      "historical_wr": 0.67,
      "suggested_lev": 1.5,
      "reasoning": "Setup: trend_follow in trend regime | Confidence: 72% (base 65%, +15% time, +15% agreement) | Historical WR: 67% on this setup | Agreement: 2 strategies agree"
    }
  ]
}
```

### Execution Tracker (`execution_tracker.py`)

**Workflow**:
1. Curator generates signal → `SignalRecord` created
2. You execute manually → `log_execution(signal_id, entry_price, size)`
3. Position closes → `log_close(signal_id, exit_price)`
4. Metrics calculated:
   - **Execution Alpha**: (Actual fill - Signal entry) / Entry (slippage quality)
   - **Exit Alpha**: How close actual exit vs TP1/TP2
   - **Total P&L**: Realized gain/loss
   - **Total P&L %**: Return on entry price

**Output**: `EXECUTION_TRACKER.jsonl` (append-only)

Each line:
```json
{
  "signal_id": "sig_20260428_001",
  "symbol": "BTC",
  "side": "SELL",
  "status": "closed",
  "signal_entry": 45632.50,
  "actual_entry": 45625.00,
  "actual_exit": 44850.00,
  "execution_alpha_pct": 0.017,
  "total_pnl": 1152.50,
  "total_pnl_pct": 1.68
}
```

## Usage

### 1. Show Today's Top Signals

```bash
cd bot
python -c "from curator.cli import main; main()" show-signals
```

Output:
```
🎯 **DAILY SIGNAL CURATOR** — Top Ranked Signals for Manual Execution
Generated: 2026-04-28 22:45 UTC
================================================================================

#1 | BTC SELL
  Confidence: 72% | Historical WR: 67%
  Entry: $45632.50 | SL: $46200.00 | TP1: $44800.00
  R:R: 1.85x | ATR: 298.45
  Setup: trend_follow | Regime: trend | 2-agree
  Suggested Leverage: 1.5x
  💡 Setup: trend_follow in trend regime | Confidence: 72% (base 65%, +15% time, +15% agreement)

#2 | ETH BUY
  Confidence: 68% | Historical WR: 62%
  Entry: $2845.30 | SL: $2800.00 | TP1: $2920.00
  R:R: 2.72x | ATR: 18.50
  Setup: regime_trend | Regime: trend | 1-agree
  Suggested Leverage: 1.2x
```

### 2. Execute Manually & Log Fill

```bash
python -c "from curator.cli import main; main()" \
  log-execution sig_20260428_001 45625.00 0.01 46200.00 "Morning edge scalp"
```

Output:
```
✅ Logged execution: sig_20260428_001 @ 45625.0 (0.01 contracts)
```

### 3. Record Close

```bash
python -c "from curator.cli import main; main()" \
  log-close sig_20260428_001 44850.75 "Hit TP1, took profit"
```

Output:
```
✅ Logged close: sig_20260428_001 @ 44850.75
```

### 4. View Daily Execution Report

```bash
python -c "from curator.cli import main; main()" report
```

Output:
```
📊 **DAILY EXECUTION REPORT** — 2026-04-28
================================================================================
Signals Generated: 12
Execution Rate: 41.7%
Total P&L: $425.32 | Win Rate: 60.0%
Avg Execution Alpha: +0.04% (slippage)

By Symbol:
  BTC: 3 trades, 66% WR, $325.16 P&L
  ETH: 2 trades, 50% WR, $100.16 P&L
  SOL: 0 trades

By Setup Type:
  trend_follow: 2 trades, 100% WR, $425.32 P&L
  regime_trend: 1 trade, 0% WR, $0.00 P&L
```

### 5. Check Pending Signals & Active Positions

```bash
python -c "from curator.cli import main; main()" status
```

Output:
```
📊 **SIGNAL & POSITION STATUS**
================================================================================

⏳ Pending Signals (8):
  sig_20260428_002: BTC BUY @ 45000.00 (71% conf)
  sig_20260428_003: ETH SELL @ 2850.00 (65% conf)
  sig_20260428_004: SOL BUY @ 142.50 (58% conf)

📈 Active Positions (3):
  sig_20260428_001: BTC SELL @ 45625.00 (P&L: +$782.50)
  sig_20260428_005: ETH BUY @ 2820.00 (P&L: N/A)
```

## Metrics & Scoring

### Signal Confidence Calculation

```
adjusted_confidence = base_confidence 
  × time_of_day_boost (1.0-1.15x)
  × multi_agree_boost (1.0-1.6x)
  × regime_alignment (1.0-1.15x)
```

**Time-of-Day Edge**:
- 6-12 UTC (morning): +15% boost (documented 75% WR)
- 18-23 UTC (US session): +5% boost
- Other hours: baseline 1.0

**Multi-Agreement Boost**:
- 1 strategy: 1.0x (baseline)
- 2 strategies: 1.15x
- 3 strategies: 1.35x
- 4 strategies: 1.60x (rare)

**Historical Win Rates** (per symbol + setup type + regime):
- BTC SELL / trend_follow / trend: 67%
- BTC BUY / regime_trend / low_vol: 52%
- ETH BUY / regime_trend / trend: 62%
- SOL BUY / multi_tier_quality / trend: 55%
- HYPE BUY / regime_trend / high_vol: 59%
- (Defaults to 50% if setup not in history)

### Suggested Leverage

Uses Kelly fractional (1/4 Kelly for safety):

```
f* = (payoff_ratio × WR - (1 - WR)) / payoff_ratio
Kelly = f* × 0.25  (1/4 Kelly for safety)
leverage = Kelly × 10 (0.5x to 3.0x capped)
```

Assuming 1.5x payoff ratio (R:R), 50% base WR:
- 50% confidence → 0.5x suggested leverage
- 65% confidence → 1.2x suggested leverage
- 75% confidence → 1.8x suggested leverage

## Integration with Paper Trading

The curator **reads from decisions.jsonl** that the paper trading bot writes. Setup:

1. **Paper trading running**:
   ```bash
   cd bot && python run.py paper > logs/paper_trading.log 2>&1 &
   ```

2. **Curator polls signals** every hour/day:
   ```bash
   python -c "from curator.cli import main; main()" show-signals
   ```

3. **Manual execution**:
   - You see top 3-5 ranked signals
   - Execute on Hyperliquid manually
   - Record fills with `log-execution`
   - Record closes with `log-close`

4. **Daily measurement**:
   ```bash
   python -c "from curator.cli import main; main()" report
   ```

## Files Generated

- `CURATOR_DAILY_SIGNALS.json` — Top signals for today
- `EXECUTION_TRACKER.jsonl` — All signal records (append-only)
- `EXECUTION_REPORT_YYYYMMDD.json` — Daily execution quality
- `DAILY_EXECUTION_REPORT.json` — Latest report

## Next Steps

1. **Backtest your manual execution**: Run paper trading, curator shows signals, you execute manually for 7-14 days
2. **Measure execution alpha**: Daily reports show slippage quality, by-symbol edge, by-setup consistency
3. **Iterate**: If execution alpha is positive (you're beating signal entry), you have a consistent process
4. **Scale**: Once process is consistent, increase size or let bot auto-execute best setups

## Philosophy

> "10 high-quality signals/day for consistent manual execution beats automated bot with 2-4 trades/month. Measure real alpha on ask/receive basis."

The curator's job: **Surface the best signal → Measure your execution quality → Build consistent process.**
