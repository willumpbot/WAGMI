"""
Base strategy interface. All strategies implement this.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import pandas as pd


@dataclass
class Signal:
    """A trading signal produced by a strategy."""

    strategy: str           # which strategy generated it
    symbol: str             # e.g. "BTC"
    side: str               # "BUY" or "SELL"
    confidence: float       # 0-100
    entry: float            # entry price
    sl: float               # stop loss price
    tp1: float              # take profit 1
    tp2: float              # take profit 2
    atr: float = 0.0        # ATR at signal time
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Minimum stop width as fraction of entry price (0.3%).
    # Prevents near-zero stops from creating infinite R:R and giant positions.
    MIN_STOP_WIDTH_PCT = 0.003

    @property
    def stop_width(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def stop_width_pct(self) -> float:
        """Stop width as a percentage of entry price."""
        if self.entry <= 0:
            return 0.0
        return self.stop_width / self.entry

    @property
    def has_valid_stop(self) -> bool:
        """Check if stop width is large enough to be meaningful."""
        return self.stop_width_pct >= self.MIN_STOP_WIDTH_PCT

    @property
    def risk_reward_tp1(self) -> float:
        if not self.has_valid_stop:
            return 0.0
        return abs(self.entry - self.tp1) / self.stop_width

    @property
    def risk_reward_tp2(self) -> float:
        if not self.has_valid_stop:
            return 0.0
        return abs(self.entry - self.tp2) / self.stop_width

    @property
    def is_valid(self) -> bool:
        """Comprehensive signal validation.

        Checks:
        - Stop width is meaningful (>= 0.3% of entry)
        - SL is on the correct side of entry
        - TP1 is on the correct side of entry
        - R:R >= 1.0 for TP1 (worth taking after fees)
        """
        if self.entry <= 0:
            return False
        if not self.has_valid_stop:
            return False
        if self.side == "BUY":
            if self.sl >= self.entry or self.tp1 <= self.entry:
                return False
        elif self.side == "SELL":
            if self.sl <= self.entry or self.tp1 >= self.entry:
                return False
        if self.risk_reward_tp1 < 1.0:
            return False
        return True


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, name: str, symbols: Dict[str, Any]):
        self.name = name
        self.symbols = symbols

    @abstractmethod
    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        """
        Evaluate market data and optionally produce a signal.

        Args:
            symbol: The symbol being evaluated (e.g. "BTC")
            data: Dict of timeframe -> DataFrame with OHLCV data
                  e.g. {"1h": df_1h, "6h": df_6h, "1d": df_1d}

        Returns:
            Signal if a trade setup is detected, None otherwise.
        """
        pass

    @abstractmethod
    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Get current market assessment without generating a signal.
        Used for logging and display.
        """
        pass

    def get_required_timeframes(self) -> List[str]:
        """Return list of timeframe keys this strategy needs (e.g. ['1h', '6h', '16h'])."""
        return ["1h"]
