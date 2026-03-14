"""
Strategy 6: Open Interest Delta

Core logic:
- Monitors changes in open interest (OI) alongside price movement
- OI expanding + price rising = new longs opening → trend confirmation (BUY)
- OI expanding + price falling = new shorts opening → trend confirmation (SELL)
- OI contracting + price rising = short squeeze / short covering → momentum BUY
- OI contracting + price falling = long liquidation → capitulation, potential reversal BUY
- OI flat + price moving = no new conviction → weak signal, skip

This strategy is unique because it measures market POSITIONING, not just price action.
It tells you whether moves have real money behind them.

Data requirements:
- 1h OHLCV for price/ATR context
- Open interest data from exchange metadata
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.oi_delta")


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


class OIDeltaStrategy(BaseStrategy):
    """
    Open Interest divergence/convergence strategy.

    OI tells you whether new money is entering (expanding) or exiting (contracting).
    Combined with price direction, this reveals the market's positioning:
    - Smart money accumulation vs retail FOMO
    - Squeeze setups vs genuine trend continuation
    - Capitulation bottoms vs further downside
    """

    # OI change thresholds (% change over lookback period)
    # Raised from 3% → 5%: audit found 3% catches noise on $500M+ markets
    OI_EXPANSION_PCT = 0.05   # 5% OI increase = meaningful new positions
    OI_CONTRACTION_PCT = -0.05  # 5% OI decrease = meaningful position closure
    OI_STRONG_PCT = 0.10      # 10% = very strong OI move (was 8%)

    # Price movement thresholds
    PRICE_MOVE_PCT = 0.015    # 1.5% price move = meaningful
    PRICE_STRONG_PCT = 0.03   # 3% = strong price move

    # Lookback for OI change calculation
    OI_LOOKBACK_BARS = 4      # 4h lookback on 1h data

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("oi_delta", symbols)

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def _classify_oi_regime(self, oi_change_pct: float, price_change_pct: float) -> Optional[Dict[str, Any]]:
        """Classify the OI+price regime into a trading signal type."""
        abs_oi = abs(oi_change_pct)
        abs_price = abs(price_change_pct)

        # Skip if neither OI nor price moved meaningfully
        if abs_oi < self.OI_EXPANSION_PCT * 0.5 and abs_price < self.PRICE_MOVE_PCT * 0.5:
            return None

        oi_expanding = oi_change_pct > self.OI_EXPANSION_PCT
        oi_contracting = oi_change_pct < self.OI_CONTRACTION_PCT
        oi_strong = abs_oi > self.OI_STRONG_PCT
        price_up = price_change_pct > self.PRICE_MOVE_PCT
        price_down = price_change_pct < -self.PRICE_MOVE_PCT
        price_strong = abs_price > self.PRICE_STRONG_PCT

        # Regime 1: OI expanding + price up = new longs (trend continuation)
        if oi_expanding and price_up:
            return {
                "type": "trend_continuation_long",
                "side": "BUY",
                "strength": "strong" if (oi_strong or price_strong) else "moderate",
                "description": "OI expanding + price rising = new longs entering",
                "base_confidence": 70.0 if oi_strong else 62.0,
            }

        # Regime 2: OI expanding + price down = new shorts (trend continuation)
        if oi_expanding and price_down:
            return {
                "type": "trend_continuation_short",
                "side": "SELL",
                "strength": "strong" if (oi_strong or price_strong) else "moderate",
                "description": "OI expanding + price falling = new shorts entering",
                "base_confidence": 70.0 if oi_strong else 62.0,
            }

        # Regime 3: OI contracting + price up = short squeeze
        if oi_contracting and price_up:
            return {
                "type": "short_squeeze",
                "side": "BUY",
                "strength": "strong" if (oi_strong and price_strong) else "moderate",
                "description": "OI contracting + price rising = short squeeze / covering",
                "base_confidence": 65.0 if oi_strong else 58.0,
            }

        # Regime 4: OI contracting + price down = long liquidation (potential reversal)
        if oi_contracting and price_down:
            # This is trickier: could be capitulation (reversal) or cascade (more down)
            if oi_strong and price_strong:
                # Extreme liquidation = likely near a bottom
                return {
                    "type": "capitulation_reversal",
                    "side": "BUY",
                    "strength": "moderate",  # Conservative: cascades can continue
                    "description": "Heavy liquidation cascade = potential capitulation bottom",
                    "base_confidence": 58.0,
                }
            # Moderate liquidation without extreme OI drop → likely more downside
            return None

        return None

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 20:
            return None

        # Get OI data from metadata
        oi_current = None
        oi_history = data.get("_oi_history")  # List/Series of recent OI values

        meta = data.get("_meta", {})
        if oi_history is None:
            oi_current = meta.get("open_interest")
            oi_previous = meta.get("open_interest_prev")
            if oi_current is None or oi_previous is None:
                return None
            oi_current = float(oi_current)
            oi_previous = float(oi_previous)
        else:
            if len(oi_history) < self.OI_LOOKBACK_BARS + 1:
                return None
            oi_current = float(oi_history[-1])
            oi_previous = float(oi_history[-(self.OI_LOOKBACK_BARS + 1)])

        if oi_previous <= 0:
            return None

        # Calculate OI change percentage
        oi_change_pct = (oi_current - oi_previous) / oi_previous

        # Calculate price change over same period
        close = df_1h["close"].astype(float)
        lookback = min(self.OI_LOOKBACK_BARS, len(close) - 1)
        price_current = float(close.iloc[-1])
        price_previous = float(close.iloc[-(lookback + 1)])

        if price_previous <= 0:
            return None

        price_change_pct = (price_current - price_previous) / price_previous

        # Classify the OI+price regime
        regime = self._classify_oi_regime(oi_change_pct, price_change_pct)
        if regime is None:
            return None

        price = price_current
        atr = float(_atr(df_1h).iloc[-1])
        if atr <= 0:
            return None

        side = regime["side"]
        confidence = regime["base_confidence"]

        # Volume confirmation
        vol = df_1h["volume"].astype(float)
        vol_avg = float(vol.rolling(20, min_periods=1).mean().iloc[-1])
        vol_current = float(vol.iloc[-1])
        vol_ratio = vol_current / max(vol_avg, 1e-12)

        if vol_ratio > 1.5:
            confidence += 8.0  # High volume confirms the move
        elif vol_ratio < 0.7:
            confidence -= 5.0  # Low volume = suspect

        # RSI confirmation
        rsi = float(_rsi(close).iloc[-1])
        if side == "BUY" and rsi < 40:
            confidence += 5.0  # Oversold + OI signal = stronger
        elif side == "SELL" and rsi > 60:
            confidence += 5.0  # Overbought + OI signal = stronger

        # EMA trend alignment
        ema20 = float(_ema(close, 20).iloc[-1])
        ema50 = float(_ema(close, 50).iloc[-1])
        trend_up = ema20 > ema50
        if (side == "BUY" and trend_up) or (side == "SELL" and not trend_up):
            confidence += 5.0  # Aligned with trend

        confidence = max(50.0, min(95.0, confidence))

        # TP/SL based on signal type
        if regime["type"] in ("trend_continuation_long", "trend_continuation_short"):
            sl_mult = 1.5
            tp1_mult = 2.0
            tp2_mult = 3.5
        elif regime["type"] == "short_squeeze":
            sl_mult = 1.2  # Tighter stop for squeeze
            tp1_mult = 1.8
            tp2_mult = 3.0
        else:  # capitulation_reversal
            sl_mult = 2.0  # Wider stop for reversal
            tp1_mult = 1.5
            tp2_mult = 2.5

        if side == "BUY":
            sl = price - atr * sl_mult
            tp1 = price + atr * tp1_mult
            tp2 = price + atr * tp2_mult
        else:
            sl = price + atr * sl_mult
            tp1 = price - atr * tp1_mult
            tp2 = price - atr * tp2_mult

        context_parts = [
            f"OI Δ: {oi_change_pct*100:+.2f}% ({regime['type']})",
            f"Price Δ: {price_change_pct*100:+.2f}%",
            regime["description"],
            f"Vol ratio: {vol_ratio:.2f}x avg",
            f"RSI={rsi:.1f}",
        ]

        sig = Signal(
            strategy="oi_delta",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "oi_change_pct": oi_change_pct,
                "price_change_pct": price_change_pct,
                "oi_regime_type": regime["type"],
                "oi_strength": regime["strength"],
                "volume_ratio": vol_ratio,
                "rsi": rsi,
                "regime": (
                    "panic" if regime["type"] == "capitulation_reversal" else
                    "high_volatility" if regime["type"] == "short_squeeze" else
                    "trend" if regime["type"] in ("oi_expansion", "oi_divergence") else
                    "range"
                ),
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(f"[{symbol}] OI Delta signal: {side} conf={confidence:.0f}% "
                     f"OI={oi_change_pct*100:+.2f}% price={price_change_pct*100:+.2f}% "
                     f"type={regime['type']}")
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        meta = data.get("_meta", {})
        oi = meta.get("open_interest", 0)
        return {
            "strategy": self.name,
            "symbol": symbol,
            "open_interest": float(oi) if oi else 0.0,
        }
