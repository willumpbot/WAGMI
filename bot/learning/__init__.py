"""
Perpetual Learning Systems: Master Learning Engine + 5 Subsystems

Autonomous improvement across:
1. auto_fix_pipeline: Audit recommendations → graduated rules → A/B test → revert
2. execution_forensics: Slippage, stop mechanics, fill analysis
3. live_prompt_injection: Real-time edge data injected into agent prompts
4. daily_synthesis: End-of-day report + anomaly detection
5. model_optimization: ROI per model per agent + swaps

Usage:
    from learning import get_master_engine
    engine = get_master_engine()
    engine.tick(trade_count=100, new_trades_since_last_run=5)
"""

from .master_engine import MasterLearningEngine, get_master_engine

__all__ = [
    "MasterLearningEngine",
    "get_master_engine",
]
