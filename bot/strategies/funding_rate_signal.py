"""
Funding Rate Signal — Mean-reversion signal based on perpetual funding rates.

Edge basis: Proven Sharpe > 1.5 on BTC in crypto quant literature.
Uncorrelated with technical signals — adds independent alpha.

Logic:
- Extreme positive funding (>0.10%/8h): Longs are overcrowded, fade long → go short
- Extreme negative funding (<-0.05%/8h): Shorts are overcrowded, fade short → go long
- Neutral funding: No signal

In trending regime: funding aligning with trend = confirmation.
In consolidation: pure mean-reversion fade.

Data source: Hyperliquid API (already connected). Pull every 8 hours. Free.
"""

import logging
from typing import Optional, Dict, Any

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.funding_rate")

# Funding rate thresholds (per 8h period)
FUNDING_EXTREME_LONG = 0.0010   # 0.10% — longs overcrowded, fade
FUNDING_EXTREME_SHORT = -0.0005 # -0.05% — shorts overcrowded, fade
FUNDING_STRONG_LONG = 0.0020    # 0.20% — very strong signal
FUNDING_STRONG_SHORT = -0.0010  # -0.10% — very strong signal


class FundingRateStrategy(BaseStrategy):
    """Funding rate mean-reversion strategy.

    Fades extreme funding rates on the assumption that overcrowded
    positioning self-corrects through funding payments and liquidations.
    """

    def __init__(self, symbols=None):
        super().__init__(name="funding_rate", symbols=symbols or {})

    def get_required_timeframes(self):
        return ["1h"]  # Needs recent candles for entry/SL/TP calculations

    def get_status(self, symbol, data):
        """Get current funding rate assessment."""
        funding_rate = None
        if isinstance(data, dict):
            funding_rate = data.get("funding_rate")
        return {
            "strategy": self.name,
            "symbol": symbol,
            "funding_rate": funding_rate,
            "signal_possible": funding_rate is not None and (
                funding_rate > FUNDING_EXTREME_LONG or funding_rate < FUNDING_EXTREME_SHORT
            ),
        }

    def evaluate(
        self, symbol: str, data: Dict[str, Any], **kwargs
    ) -> Optional[Signal]:
        """Evaluate funding rate signal.

        Expects data to contain 'funding_rate' key with current 8h funding rate,
        and '1h' DataFrame for price-level calculations.
        """
        funding_rate = None

        # Try to get funding rate from data dict
        if isinstance(data, dict):
            funding_rate = data.get("funding_rate")
            if funding_rate is None:
                # Try from metadata
                meta = data.get("metadata", {})
                if isinstance(meta, dict):
                    funding_rate = meta.get("funding_rate")

        if funding_rate is None:
            return None  # No funding data available

        funding_rate = float(funding_rate)

        # Determine signal direction and strength
        if funding_rate > FUNDING_EXTREME_LONG:
            side = "SELL"
            if funding_rate > FUNDING_STRONG_LONG:
                strength = min(1.0, (funding_rate - FUNDING_EXTREME_LONG) / 0.001)
                confidence = 70 + strength * 15  # 70-85
            else:
                strength = min(1.0, (funding_rate - FUNDING_EXTREME_LONG) / 0.0005)
                confidence = 60 + strength * 10  # 60-70
        elif funding_rate < FUNDING_EXTREME_SHORT:
            side = "BUY"
            if funding_rate < FUNDING_STRONG_SHORT:
                strength = min(1.0, abs(funding_rate - FUNDING_EXTREME_SHORT) / 0.0005)
                confidence = 70 + strength * 15  # 70-85
            else:
                strength = min(1.0, abs(funding_rate - FUNDING_EXTREME_SHORT) / 0.0003)
                confidence = 60 + strength * 10  # 60-70
        else:
            return None  # Neutral funding — no signal

        # Get price data for entry/SL/TP computation
        df = data.get("1h") if isinstance(data, dict) else None
        if df is None or df.empty:
            return None

        close = df["close"].iloc[-1]
        atr = self._compute_atr(df)
        if atr <= 0:
            return None

        # Entry at current price
        entry = close

        # SL/TP based on ATR — per-symbol atr_mult_sl from trading config if set
        try:
            from trading_config import TradingConfig as _TC, get_symbol_param
            _cfg = _TC()
            atr_mult_sl = get_symbol_param(symbol, "atr_mult_sl", _cfg) or 1.5
        except Exception:
            atr_mult_sl = 1.5
        atr_mult_tp1 = 1.5
        atr_mult_tp2 = 3.0

        if side == "BUY":
            sl = entry - atr * atr_mult_sl
            tp1 = entry + atr * atr_mult_tp1
            tp2 = entry + atr * atr_mult_tp2
        else:
            sl = entry + atr * atr_mult_sl
            tp1 = entry - atr * atr_mult_tp1
            tp2 = entry - atr * atr_mult_tp2

        return Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "funding_rate": funding_rate,
                "funding_strength": round(strength, 3),
                "signal_type": "funding_mean_reversion",
            },
        )

    def _compute_atr(self, df, period: int = 14) -> float:
        """Compute ATR from DataFrame."""
        if len(df) < period + 1:
            return 0.0

        try:
            high = df["high"].values
            low = df["low"].values
            close = df["close"].values

            tr_values = []
            for i in range(1, len(df)):
                tr = max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]),
                )
                tr_values.append(tr)

            if len(tr_values) < period:
                return sum(tr_values) / len(tr_values) if tr_values else 0.0

            return sum(tr_values[-period:]) / period
        except Exception:
            return 0.0
