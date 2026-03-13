"""
Open Interest Divergence Signal — Directional signal from OI/price divergence.

The four OI scenarios:
  Price Rising  + OI Falling  = Short covering rally (not real demand) → FADE / short
  Price Falling + OI Rising   = New shorts building → Confirm short
  Price Rising  + OI Rising   = Real momentum (genuine demand) → Confirm long
  Price Falling + OI Falling  = Long liquidation (trend ending) → Reversal watch

Expected impact: +8-12% directional accuracy (crypto quant literature).
Data source: Exchange API or Coinalyze free tier.
"""

import logging
import math
from typing import Optional, Dict, Any

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.oi_divergence")

# Thresholds for OI change significance
OI_CHANGE_THRESHOLD = 0.02    # 2% OI change minimum to generate signal
PRICE_CHANGE_THRESHOLD = 0.005 # 0.5% price change minimum
OI_LOOKBACK_PERIODS = 12       # 12h lookback for OI trend on 1h candles


class OIDivergenceStrategy(BaseStrategy):
    """Open Interest divergence strategy.

    Detects divergence between price action and open interest changes
    to identify whether moves are driven by genuine positioning or
    short covering / liquidation cascades.
    """

    def __init__(self, symbols=None):
        super().__init__(name="oi_divergence", symbols=symbols or {})

    def get_required_timeframes(self):
        return ["1h"]

    def get_status(self, symbol, data):
        """Get current OI divergence assessment."""
        return {
            "strategy": self.name,
            "symbol": symbol,
            "has_oi_data": isinstance(data, dict) and (
                "open_interest" in data or "oi" in data
            ),
        }

    def evaluate(
        self, symbol: str, data: Dict[str, Any], **kwargs
    ) -> Optional[Signal]:
        """Evaluate OI divergence signal.

        Expects data to contain:
        - '1h' DataFrame with OHLCV
        - 'open_interest' or 'oi' key with OI data (list of floats or in DataFrame)
        """
        df = data.get("1h") if isinstance(data, dict) else None
        if df is None or len(df) < OI_LOOKBACK_PERIODS + 1:
            return None

        # Get OI data — try multiple sources
        oi_data = None
        if isinstance(data, dict):
            oi_data = data.get("open_interest") or data.get("oi")
            if oi_data is None and "oi" in df.columns:
                oi_data = df["oi"].tolist()

        if oi_data is None or len(oi_data) < OI_LOOKBACK_PERIODS:
            return None  # No OI data available

        # Compute price and OI changes over lookback window
        current_price = df["close"].iloc[-1]
        past_price = df["close"].iloc[-OI_LOOKBACK_PERIODS]
        price_change_pct = (current_price - past_price) / past_price if past_price > 0 else 0

        current_oi = float(oi_data[-1])
        past_oi = float(oi_data[-OI_LOOKBACK_PERIODS])
        oi_change_pct = (current_oi - past_oi) / past_oi if past_oi > 0 else 0

        # Filter: need meaningful changes to generate signal
        if abs(price_change_pct) < PRICE_CHANGE_THRESHOLD and abs(oi_change_pct) < OI_CHANGE_THRESHOLD:
            return None  # No significant divergence

        # Classify OI scenario
        price_up = price_change_pct > PRICE_CHANGE_THRESHOLD
        price_down = price_change_pct < -PRICE_CHANGE_THRESHOLD
        oi_up = oi_change_pct > OI_CHANGE_THRESHOLD
        oi_down = oi_change_pct < -OI_CHANGE_THRESHOLD

        side = None
        confidence = 60  # Base confidence
        signal_type = ""

        if price_up and oi_down:
            # Short covering rally — not real demand → fade
            side = "SELL"
            signal_type = "short_covering_fade"
            confidence = 65 + min(15, abs(oi_change_pct) / 0.01 * 5)
        elif price_down and oi_up:
            # New shorts building — continuation
            side = "SELL"
            signal_type = "new_shorts_confirm"
            confidence = 65 + min(15, abs(oi_change_pct) / 0.01 * 5)
        elif price_up and oi_up:
            # Real momentum — genuine demand
            side = "BUY"
            signal_type = "real_momentum_confirm"
            confidence = 70 + min(15, min(abs(price_change_pct), abs(oi_change_pct)) / 0.02 * 5)
        elif price_down and oi_down:
            # Long liquidation — trend may be ending → reversal watch
            # Lower confidence: this is a "watch" signal, not a strong entry
            side = "BUY"
            signal_type = "liquidation_reversal"
            confidence = 55 + min(10, abs(oi_change_pct) / 0.01 * 3)
        else:
            return None  # Ambiguous

        if side is None:
            return None

        # Compute entry/SL/TP from ATR
        atr = self._compute_atr(df)
        if atr <= 0:
            return None

        entry = current_price
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
                "signal_type": signal_type,
                "price_change_pct": round(price_change_pct, 4),
                "oi_change_pct": round(oi_change_pct, 4),
                "oi_lookback": OI_LOOKBACK_PERIODS,
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
