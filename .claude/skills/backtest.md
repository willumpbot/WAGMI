# /backtest — Smart Backtesting with Comparison

## Description
Run backtests against historical data with smart defaults, multi-symbol support, and automatic comparison against previous results.

## Arguments
- `$ARGUMENTS` — Optional: symbols, days, and comparison flags (e.g., "BTC,ETH 30d compare")

## Workflow

### 1. Parse Arguments
Parse `$ARGUMENTS` for:
- **Symbols**: Comma-separated (default: BTC,ETH,SOL)
- **Days**: Number followed by "d" (default: 30d)
- **Flags**: `compare` (compare with last run), `quick` (7d only), `deep` (90d)

### 2. Pre-Flight Checks
Before running any backtest:
- Run `cd bot && python -m pytest tests/ -k "ensemble or strategy" -x --tb=line -q` to ensure strategies are passing
- Read `bot/trading_config.py` to confirm current parameter values
- Check if previous backtest results exist in `bot/data/optimization_results.json`

### 3. Execute Backtest
Run the backtest:
```bash
cd bot && python run.py backtest --symbols <SYMBOLS> --days <DAYS>
```

### 4. Analyze Results
After the backtest completes:
- Read the output JSON report
- Extract key metrics: Sharpe ratio, win rate, max drawdown, profit factor, total PnL
- Break down performance by:
  - **Per-symbol**: Which assets performed best/worst
  - **Per-strategy**: Which of the 4 strategies contributed most
  - **Per-regime**: Performance in trend vs range vs panic

### 5. Compare (if requested or previous results exist)
If `compare` flag or previous results found:
- Load previous backtest results
- Show side-by-side comparison table
- Highlight improvements and regressions
- Flag any metric that degraded by >10%

### 6. Report
Present results as a formatted summary:
```
BACKTEST RESULTS — <SYMBOLS> — <DAYS>d
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sharpe:       X.XX (prev: X.XX)
Win Rate:     XX.X% (prev: XX.X%)
Max Drawdown: -X.X% (prev: -X.X%)
Profit Factor: X.XX (prev: X.XX)
Total PnL:    $X,XXX

Per-Strategy Breakdown:
  regime_trend:      XX.X% win rate, $XXX PnL
  monte_carlo_zones: XX.X% win rate, $XXX PnL
  confidence_scorer: XX.X% win rate, $XXX PnL
  multi_tier_quality: XX.X% win rate, $XXX PnL
```

### 7. Recommendations
Based on results, suggest:
- Parameter adjustments if Sharpe < 1.0
- Strategy weight changes if one strategy dominates
- Regime-specific tuning if performance varies wildly by regime
