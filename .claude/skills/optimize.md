# /optimize — Quick Parameter Optimization

## Description
Run parameter optimization with sensible defaults. Supports quick (7d), standard (30d), and deep (90d) modes. Automatically compares results with current config.

## Arguments
- `$ARGUMENTS` — Optional: mode and symbols (e.g., "quick BTC,ETH" or "deep" or "30d SOL")

## Workflow

### 1. Parse Arguments
- **Mode**: `quick` (7d, 25 trials), `standard`/default (30d, 100 trials), `deep` (90d, 500 trials)
- **Symbols**: Comma-separated (default: all configured symbols)
- **Metric**: Default to Sharpe ratio (can override with `--metric winrate|pnl|sharpe`)

### 2. Current Config Snapshot
Before optimizing, capture current parameters:
- Read `bot/trading_config.py` — extract all tunable parameters
- Read `bot/data/strategy_weights.py` — current strategy weights
- Document: ATR multipliers, confidence floors, veto ratios, min_votes, timeframe weights, leverage tiers

Present current config to user as baseline.

### 3. Pre-Flight
- Ensure tests pass: `cd bot && pytest tests/ -k "ensemble or strategy" -x --tb=line -q`
- Check data availability: verify OHLCV data exists for requested period
- Estimate runtime: ~N seconds per trial

### 4. Run Optimization
```bash
cd bot && python cli.py --mode optimize --symbols <SYMBOLS> --days <DAYS> --trials <TRIALS> --metric <METRIC>
```

### 5. Analyze Results
Read `bot/data/optimization_results.json` and extract:

**Phase 1 Results (Strategy Parameters):**
- Best ATR multiplier for SL/TP
- Best confidence floor
- Best veto ratio
- Best min_votes

**Phase 2 Results (Timeframe Weights):**
- Optimal 5m/1h/6h/daily weight distribution

**Phase 3 Results (Sensitivity Analysis):**
- Which parameters are most sensitive (small change → big impact)
- Which are robust (change doesn't matter much)

### 6. Compare with Current
Generate comparison table:
```
PARAMETER COMPARISON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Parameter          Current    Optimal    Delta
─────────────────────────────────────────────
atr_multiplier_sl  1.5        1.3        -13%
atr_multiplier_tp  2.5        2.8        +12%
confidence_floor   60         55         -8%
veto_ratio         0.5        0.45       -10%
...

PERFORMANCE COMPARISON
━━━━━━━━━━━━━━━━━━━━━━
Metric         Current    Optimal    Change
Sharpe         1.2        1.6        +33%
Win Rate       54%        58%        +4pp
Max Drawdown   -8%        -6%        improved
```

### 7. Recommend Actions
Based on results:
- **High confidence** (>20% improvement, robust in sensitivity): Recommend applying immediately
- **Medium confidence** (10-20% improvement): Recommend paper trading first
- **Low confidence** (small improvement, sensitive params): Recommend more data / longer backtest
- **Degraded**: Warn the user, do NOT auto-apply

### 8. Apply (with confirmation)
If user wants to apply optimal parameters:
- Edit `bot/trading_config.py` with new values
- Run full test suite to verify
- Run a comparison backtest with new params
- Commit: "tune: apply optimized parameters from <DAYS>d optimization"

NEVER auto-apply without explicit user confirmation.
