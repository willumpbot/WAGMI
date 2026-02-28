"""
Feedback loop system: Continuously backtests, learns, and adapts trading parameters.

Components:
- adaptive_confidence: Dynamic confidence floors driven by realized performance
- continuous_backtest: Periodic backtesting that feeds results back into live params
- performance_tracker: Tracks per-strategy, per-symbol, per-regime realized metrics
- parameter_tuner: Auto-tunes leverage, sizing, thresholds from backtest results
"""
