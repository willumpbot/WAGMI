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

    @property
    def stop_width(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def risk_reward_tp1(self) -> float:
        if self.stop_width == 0:
            return 0
        return abs(self.entry - self.tp1) / self.stop_width

    @property
    def risk_reward_tp2(self) -> float:
        if self.stop_width == 0:
            return 0
        return abs(self.entry - self.tp2) / self.stop_width


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
