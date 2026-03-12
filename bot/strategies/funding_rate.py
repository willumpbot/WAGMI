"""
Strategy 5: Funding Rate Mean-Reversion

Core logic:
- Monitors perpetual funding rates on Hyperliquid
- When funding is extremely positive (>0.03%), the market is overleveraged long
  → Counter-trade: SELL (expect mean-reversion)
- When funding is extremely negative (<-0.03%), the market is overleveraged short
  → Counter-trade: BUY (expect short squeeze)
- Confidence scales with funding extremity
- ATR-based TP/SL: tight stops, small targets (high win-rate scalp)
- Works best in range/high_volatility regimes where crowded trades unwind

Data requirements:
- 1h OHLCV for ATR, trend context
- Funding rate from exchange metadata (passed via data dict)
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.funding_rate")


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=max(2, span), adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


class FundingRateStrategy(BaseStrategy):
    """
    Counter-trade extreme funding rates.

    Funding rate is the cost of holding a perpetual position. When funding is
    very positive, longs pay shorts → market is overcrowded long → expect
    mean-reversion downward. Vice versa for negative funding.

    This is a high win-rate, low reward-per-trade strategy that adds
    uncorrelated alpha to the ensemble.
    """

    # Funding thresholds (8h rate, annualized ~100%+ when >0.03%)
    FUNDING_EXTREME_THRESHOLD = 0.0003  # 0.03% per 8h = extreme
    FUNDING_HIGH_THRESHOLD = 0.0002     # 0.02% per 8h = elevated
    FUNDING_NEUTRAL_BAND = 0.0001       # ±0.01% = normal, no signal

    # Trend guard: don't fade funding if strong trend agrees with funding direction
    ADX_TREND_OVERRIDE = 30.0  # ADX above this = strong trend, skip counter-trade

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("funding_rate", symbols)

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute ADX for trend strength check."""
        if len(df) < period + 1:
            return 25.0
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        atr_vals = _atr(df, period).replace(0, 1e-12)
        plus_di = 100 * _ema(plus_dm, period) / atr_vals
        minus_di = 100 * _ema(minus_dm, period) / atr_vals
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
        adx = _ema(dx, period)
        return float(adx.iloc[-1]) if len(adx) > 0 else 25.0

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 20:
            return None

        # Get funding rate from metadata (passed by data fetcher)
        funding_rate = data.get("_funding_rate")
        if funding_rate is None:
            # Try extracting from DataFrame metadata
            meta = data.get("_meta", {})
            funding_rate = meta.get("funding_rate")

        if funding_rate is None:
            return None

        funding = float(funding_rate)
        abs_funding = abs(funding)

        # Skip if funding is in neutral band
        if abs_funding < self.FUNDING_HIGH_THRESHOLD:
            return None

        # Determine direction: counter-trade the funding
        if funding > 0:
            side = "SELL"  # Longs are paying → overcrowded → fade long
            funding_signal = "positive"
        else:
            side = "BUY"   # Shorts are paying → overcrowded → fade short
            funding_signal = "negative"

        price = float(df_1h["close"].iloc[-1])
        atr = float(_atr(df_1h).iloc[-1])

        if atr <= 0 or price <= 0:
            return None

        # ADX trend guard: don't counter-trade if strong trend aligns with funding
        adx = self._compute_adx(df_1h)
        ema20 = float(_ema(df_1h["close"], 20).iloc[-1])
        trend_up = price > ema20
        trend_down = price < ema20

        # If strong trend and funding aligns (longs paying in uptrend = normal), skip
        if adx > self.ADX_TREND_OVERRIDE:
            if funding > 0 and trend_up:
                logger.debug(f"[{symbol}] Funding positive but strong uptrend (ADX={adx:.1f}), skip")
                return None
            if funding < 0 and trend_down:
                logger.debug(f"[{symbol}] Funding negative but strong downtrend (ADX={adx:.1f}), skip")
                return None

        # RSI confirmation: prefer counter-trade when RSI confirms extended
        rsi = float(_rsi(df_1h["close"]).iloc[-1])
        rsi_confirms = (funding > 0 and rsi > 65) or (funding < 0 and rsi < 35)

        # Confidence scoring
        confidence = 55.0  # Base

        # Scale by funding extremity
        if abs_funding >= self.FUNDING_EXTREME_THRESHOLD:
            confidence += 20.0  # Extreme funding = strong signal
        elif abs_funding >= self.FUNDING_HIGH_THRESHOLD:
            confidence += 10.0  # Elevated funding = moderate signal

        # RSI confirmation bonus
        if rsi_confirms:
            confidence += 10.0

        # ADX bonus: counter-trading in range/weak trend is better
        if adx < 20:
            confidence += 5.0  # Ranging market = funding reversion more likely
        elif adx > 25:
            confidence -= 5.0  # Some trend = funding may be justified

        # Funding rate magnitude bonus (linear scaling above threshold)
        funding_excess = abs_funding - self.FUNDING_HIGH_THRESHOLD
        funding_max_excess = 0.001  # 0.1% is extreme
        funding_bonus = min(10.0, 10.0 * (funding_excess / funding_max_excess))
        confidence += funding_bonus

        confidence = max(50.0, min(95.0, confidence))

        # TP/SL: tight since this is a mean-reversion scalp
        sl_dist = atr * 1.2  # Tight stop
        tp1_dist = atr * 1.5  # Modest TP1
        tp2_dist = atr * 2.5  # Extended TP2

        if side == "BUY":
            sl = price - sl_dist
            tp1 = price + tp1_dist
            tp2 = price + tp2_dist
        else:
            sl = price + sl_dist
            tp1 = price - tp1_dist
            tp2 = price - tp2_dist

        context_parts = [
            f"Funding rate {funding_signal}: {funding*100:.4f}%/8h",
            f"Counter-trade {'longs' if funding > 0 else 'shorts'}",
            f"RSI={rsi:.1f} {'confirms' if rsi_confirms else 'neutral'}",
            f"ADX={adx:.1f}",
        ]

        sig = Signal(
            strategy="funding_rate",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "funding_rate": funding,
                "funding_signal": funding_signal,
                "rsi": rsi,
                "adx": adx,
                "rsi_confirms": rsi_confirms,
                "regime": (
                    "high_volatility" if abs(funding) > 0.0005 else
                    "trend" if adx > 25 else
                    "range" if adx < 20 else
                    "unknown"
                ),
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(f"[{symbol}] Funding rate signal: {side} conf={confidence:.0f}% "
                     f"funding={funding*100:.4f}%/8h RSI={rsi:.1f}")
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        funding_rate = data.get("_funding_rate")
        if funding_rate is None:
            meta = data.get("_meta", {})
            funding_rate = meta.get("funding_rate", 0.0)
        return {
            "strategy": self.name,
            "symbol": symbol,
            "funding_rate": float(funding_rate) if funding_rate else 0.0,
            "signal": "counter-long" if (funding_rate or 0) > 0 else "counter-short" if (funding_rate or 0) < 0 else "neutral",
        }
