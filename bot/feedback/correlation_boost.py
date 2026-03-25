"""
Cross-Asset Correlation Boost — Adjusts signal win probability when
multiple symbols move in the same direction.

Evidence from paper trading session 2026-03-23:
When BTC, SOL, and HYPE all sell off together, SELL signals have higher
true win probability than the formula predicts. The EV formula treats each
symbol independently, ignoring correlated market-wide moves.

This component tracks recent price direction across all symbols and provides
a win_prob multiplier boost when the signal direction aligns with broad
market momentum.

Wiring:
    # In ensemble.py, before EV calculation:
    corr_boost = self._correlation_boost.get_boost(symbol, side)
    win_prob = raw_win_prob * deflation * corr_boost
"""

import logging
import time
from collections import deque
from typing import Dict, Optional

logger = logging.getLogger("bot.feedback.correlation_boost")


class CrossAssetCorrelationBoost:
    """Detects correlated cross-asset moves and boosts aligned signals.

    Maintains a rolling price history and computes directional agreement
    across tracked symbols. When 75%+ of symbols move in the same direction
    as the signal, apply a confidence boost.
    """

    def __init__(
        self,
        symbols: list = None,
        lookback_minutes: int = 60,
        min_move_pct: float = 0.3,
        strong_boost: float = 1.08,
        moderate_boost: float = 1.04,
    ):
        self.symbols = symbols or ["BTC", "SOL", "HYPE"]
        self.lookback_minutes = lookback_minutes
        self.min_move_pct = min_move_pct
        self.strong_boost = strong_boost
        self.moderate_boost = moderate_boost

        # Rolling price history: {symbol: deque of (timestamp, price)}
        self._prices: Dict[str, deque] = {
            sym: deque(maxlen=500) for sym in self.symbols
        }

        logger.info(
            f"[CORR-BOOST] Initialized: {len(self.symbols)} symbols, "
            f"lookback={lookback_minutes}min, strong={strong_boost}, moderate={moderate_boost}"
        )

    def update_price(self, symbol: str, price: float, timestamp: float = None) -> None:
        """Record a price observation."""
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=500)
        ts = timestamp or time.time()
        self._prices[symbol].append((ts, price))

    def update_prices(self, prices: Dict[str, float], timestamp: float = None) -> None:
        """Bulk update prices for all symbols."""
        ts = timestamp or time.time()
        for sym, price in prices.items():
            if price and price > 0:
                self.update_price(sym, price, ts)

    def get_boost(self, symbol: str, side: str) -> float:
        """Calculate win_prob boost based on cross-asset directional agreement.

        Args:
            symbol: The symbol being traded
            side: "BUY" or "SELL"

        Returns:
            Multiplier (1.0 = no boost, up to strong_boost for strong agreement)
        """
        now = time.time()
        cutoff = now - self.lookback_minutes * 60

        # Calculate direction for each symbol over lookback
        directions = {}
        for sym, history in self._prices.items():
            if len(history) < 2:
                continue

            # Find oldest price within lookback
            oldest_price = None
            for ts, price in history:
                if ts >= cutoff:
                    if oldest_price is None:
                        oldest_price = price
                    break
            if oldest_price is None and history:
                oldest_price = history[0][1]

            latest_price = history[-1][1] if history else None

            if oldest_price and latest_price and oldest_price > 0:
                change_pct = (latest_price - oldest_price) / oldest_price * 100
                if change_pct > self.min_move_pct:
                    directions[sym] = "UP"
                elif change_pct < -self.min_move_pct:
                    directions[sym] = "DOWN"
                else:
                    directions[sym] = "FLAT"

        if len(directions) < 2:
            return 1.0  # Not enough data

        # Count how many symbols agree with the signal direction
        expected_dir = "DOWN" if side == "SELL" else "UP"
        agreeing = sum(1 for d in directions.values() if d == expected_dir)
        total = len(directions)
        agreement_ratio = agreeing / total

        if agreement_ratio >= 0.75:
            boost = self.strong_boost
            logger.debug(
                f"[CORR-BOOST] {symbol} {side}: strong boost {boost} "
                f"({agreeing}/{total} symbols agree)"
            )
            return boost
        elif agreement_ratio >= 0.50:
            boost = self.moderate_boost
            logger.debug(
                f"[CORR-BOOST] {symbol} {side}: moderate boost {boost} "
                f"({agreeing}/{total} symbols agree)"
            )
            return boost
        else:
            return 1.0

    def get_market_direction(self) -> Dict[str, str]:
        """Get current direction assessment for all symbols."""
        now = time.time()
        cutoff = now - self.lookback_minutes * 60
        result = {}

        for sym, history in self._prices.items():
            if len(history) < 2:
                result[sym] = "UNKNOWN"
                continue

            oldest_price = None
            for ts, price in history:
                if ts >= cutoff:
                    if oldest_price is None:
                        oldest_price = price
                    break
            if oldest_price is None and history:
                oldest_price = history[0][1]

            latest_price = history[-1][1] if history else None

            if oldest_price and latest_price and oldest_price > 0:
                change_pct = (latest_price - oldest_price) / oldest_price * 100
                if change_pct > self.min_move_pct:
                    result[sym] = f"UP ({change_pct:+.2f}%)"
                elif change_pct < -self.min_move_pct:
                    result[sym] = f"DOWN ({change_pct:+.2f}%)"
                else:
                    result[sym] = f"FLAT ({change_pct:+.2f}%)"
            else:
                result[sym] = "UNKNOWN"

        return result
