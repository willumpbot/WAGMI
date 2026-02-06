"""
Multi-strategy ensemble / voting system.
Combines signals from all 4 strategies into consensus decisions.

Modes:
- "voting": Require min_votes strategies to agree on side before trading.
  Confidence = average of agreeing strategies.
- "weighted": Weight each strategy by historical performance.
  Combined confidence = weighted average.
- "best": Take the highest-confidence signal.
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.ensemble")


class EnsembleStrategy:
    """
    Combines multiple strategies into a consensus signal.
    Not a BaseStrategy itself - it wraps multiple strategies.
    """

    def __init__(
        self,
        strategies: List[BaseStrategy],
        mode: str = "voting",
        min_votes: int = 2,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.strategies = strategies
        self.mode = mode
        self.min_votes = min_votes
        self.weights = weights or {s.name: 1.0 for s in strategies}

    def get_all_required_timeframes(self) -> List[str]:
        """Get the union of all timeframes needed by all strategies."""
        tfs = set()
        for s in self.strategies:
            tfs.update(s.get_required_timeframes())
        return list(tfs)

    def evaluate(
        self, symbol: str, data: Dict[str, pd.DataFrame]
    ) -> Optional[Signal]:
        """
        Run all strategies and combine their signals.
        Returns a single consensus Signal or None.
        """
        signals: List[Signal] = []

        for strategy in self.strategies:
            try:
                sig = strategy.evaluate(symbol, data)
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                logger.warning(f"[{symbol}] {strategy.name} error: {e}")

        if not signals:
            return None

        if self.mode == "voting":
            return self._voting(symbol, signals)
        elif self.mode == "weighted":
            return self._weighted(symbol, signals)
        elif self.mode == "best":
            return self._best(symbol, signals)
        else:
            return self._voting(symbol, signals)

    def _voting(self, symbol: str, signals: List[Signal]) -> Optional[Signal]:
        """Require min_votes strategies to agree on direction."""
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]

        if len(buy_signals) >= self.min_votes:
            chosen = buy_signals
        elif len(sell_signals) >= self.min_votes:
            chosen = sell_signals
        else:
            return None

        return self._merge_signals(symbol, chosen)

    def _weighted(self, symbol: str, signals: List[Signal]) -> Optional[Signal]:
        """Weight strategies by performance and combine."""
        buy_signals = [s for s in signals if s.side == "BUY"]
        sell_signals = [s for s in signals if s.side == "SELL"]

        buy_weight = sum(self.weights.get(s.strategy, 1.0) * s.confidence for s in buy_signals)
        sell_weight = sum(self.weights.get(s.strategy, 1.0) * s.confidence for s in sell_signals)

        if buy_weight > sell_weight and len(buy_signals) >= 1:
            chosen = buy_signals
        elif sell_weight > buy_weight and len(sell_signals) >= 1:
            chosen = sell_signals
        else:
            return None

        return self._merge_signals(symbol, chosen)

    def _best(self, symbol: str, signals: List[Signal]) -> Optional[Signal]:
        """Take the single highest-confidence signal."""
        best = max(signals, key=lambda s: s.confidence)
        return best

    def _merge_signals(self, symbol: str, signals: List[Signal]) -> Signal:
        """Merge multiple agreeing signals into one consensus signal."""
        side = signals[0].side
        avg_conf = sum(s.confidence for s in signals) / len(signals)
        # Consensus bonus: more strategies agree -> higher confidence
        consensus_bonus = (len(signals) - 1) * 3
        combined_conf = min(100, avg_conf + consensus_bonus)

        # Use the most conservative stop (widest) and most conservative TP
        if side == "BUY":
            best_sl = min(s.sl for s in signals)
            best_tp1 = min(s.tp1 for s in signals)
            best_tp2 = max(s.tp2 for s in signals)
            entry = sum(s.entry for s in signals) / len(signals)
        else:
            best_sl = max(s.sl for s in signals)
            best_tp1 = max(s.tp1 for s in signals)
            best_tp2 = min(s.tp2 for s in signals)
            entry = sum(s.entry for s in signals) / len(signals)

        atr = max((s.atr for s in signals), default=0)

        return Signal(
            strategy="ensemble",
            symbol=symbol,
            side=side,
            confidence=combined_conf,
            entry=entry,
            sl=best_sl,
            tp1=best_tp1,
            tp2=best_tp2,
            atr=atr,
            metadata={
                "strategies_agree": [s.strategy for s in signals],
                "num_agree": len(signals),
                "total_strategies": len(self.strategies),
                "individual_confidences": {s.strategy: s.confidence for s in signals},
                "mode": self.mode,
            },
        )

    def get_all_status(
        self, symbol: str, data: Dict[str, pd.DataFrame]
    ) -> List[Dict[str, Any]]:
        """Get status from all strategies for display."""
        statuses = []
        for strategy in self.strategies:
            try:
                status = strategy.get_status(symbol, data)
                statuses.append(status)
            except Exception as e:
                statuses.append({
                    "symbol": symbol,
                    "strategy": strategy.name,
                    "status": f"error: {e}",
                })
        return statuses

    def update_weights(self, performance: Dict[str, float]):
        """Update strategy weights based on observed performance."""
        for name, perf in performance.items():
            if name in self.weights:
                # Simple: weight = 0.5 + performance (bounded 0.1 to 2.0)
                self.weights[name] = max(0.1, min(2.0, 0.5 + perf))
        logger.info(f"Updated ensemble weights: {self.weights}")
