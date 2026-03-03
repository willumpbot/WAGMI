# Strategy Development Rules

## Architecture
The bot uses 4 independent trading strategies that vote through a weighted-veto ensemble:
1. `regime_trend.py` — Regime-based trend following (needs 1h+6h data)
2. `monte_carlo_zones.py` — Monte Carlo support/resistance (needs daily data)
3. `confidence_scorer.py` — Multi-factor confidence scoring
4. `multi_tier_quality.py` — Multi-timeframe signal quality (needs 5m+1h data)

Ensemble voting happens in `bot/strategies/ensemble.py` (weighted_veto mode).

## Signal Contract
All strategies MUST return `Optional[Signal]` from their `evaluate()` method.

The `Signal` dataclass (`bot/strategies/base.py`) requires:
- `strategy`: str — strategy name
- `symbol`: str — trading pair
- `side`: str — "BUY" or "SELL"
- `confidence`: float — 0-100 scale
- `entry`: float — entry price
- `sl`: float — stop loss price
- `tp1`, `tp2`: float — take profit targets
- `atr`: float — current ATR value

Signal validation (`Signal.is_valid`):
- Stop width must be >= 0.3% of entry
- SL must be on correct side of entry
- TP1, TP2 must be on correct side of entry
- R:R ratio must be >= 1.0

## Rules for Strategy Changes
- NEVER modify the Signal dataclass without updating ALL strategies and the ensemble
- NEVER remove the `is_valid` checks — they prevent nonsensical trades
- Every strategy MUST handle missing data gracefully (return None, not crash)
- Ensemble MIN_VOTES and VETO_RATIO are in `trading_config.py` — don't hardcode
- Strategy weights are managed by `bot/data/strategy_weights.py` — don't override manually
- Timeframe weights: 5m=0.5, 1h=1.0, 6h=1.5, daily=2.0 (in `trading_config.py`)

## Testing
- Run `cd bot && pytest tests/ -k "ensemble or strategy"` after any strategy change
- Verify signal validity with: `assert signal.is_valid` in tests
