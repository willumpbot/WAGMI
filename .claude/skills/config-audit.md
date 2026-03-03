# /config-audit — Audit Hardcoded Values and Configuration Tunability

## Description
Find every hardcoded value that affects profitability, check if it's configurable, and recommend changes based on actual trading performance data.

## Arguments
- `$ARGUMENTS` — Optional: "hardcoded" (find values stuck in code), "current" (show all settings), "recommend" (suggest changes based on data)

## Workflow

### 1. Configuration Inventory
Read `bot/trading_config.py` — extract ALL tunable parameters:
- Risk: risk_per_trade, max_positions, daily_loss_limit, consecutive_loss_limit
- Leverage: max_leverage, leverage tiers
- Strategy: ATR multipliers, confidence floors, min_votes, veto_ratio
- Timeframe weights: 5m, 1h, 6h, daily
- Feature flags: all Wave 1-4 features

Show current values for every parameter.

### 2. Hardcoded Value Scan
Scan codebase for values that SHOULD be in config but aren't:
```bash
cd bot && grep -rn "= 0\.\|= [0-9]" --include="*.py" strategies/ execution/ llm/ feedback/ | grep -v test | grep -v __pycache__
```

Flag magic numbers: ATR multipliers, timeout values, confidence thresholds, memory limits, cooldown periods, retry counts.

For each hardcoded value:
- File and line number
- What it controls
- What the default is
- Should it be configurable?
- Does changing it affect PnL?

### 3. Per-Symbol Config Check
Read per-symbol overrides in trading_config:
- Are high-volatility symbols (SOL, PEPE) using different parameters than BTC?
- Should they be? (different ATR, different leverage, different confidence floors)
- Cross-reference with edge-finder data: which symbols need special treatment?

### 4. Parameter Sensitivity Analysis
For the most impactful parameters (confidence floor, leverage, risk per trade):
- What's the current value?
- What does the backtest/optimizer suggest?
- What does the adaptive confidence system suggest?
- What does the parameter tuner suggest?
- Are they all aligned?

### 5. Recommend Changes
Based on trading data and analysis:

```
CONFIG RECOMMENDATIONS
━━━━━━━━━━━━━━━━━━━━━━
Parameter          Current   Recommended   Reason                    Impact
confidence_floor   60%       68%          50-68% trades lose money   +$XX/mo
max_leverage       10x       6x           High lev losing more       risk reduce
risk_per_trade     0.02      0.015        Reduce loss magnitude      -drawdown
min_votes          2         3            2-vote trades poor WR      +$XX/mo
```

### 6. Apply (with confirmation)
Edit `bot/trading_config.py` with approved changes.
Run tests, run backtest comparison.
