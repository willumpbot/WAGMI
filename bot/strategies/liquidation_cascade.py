"""
Strategy 10: Liquidation Cascade

Core logic:
- Tracks liquidation events and clusters on Hyperliquid
- Price tends to "hunt" liquidation clusters (market maker behavior)
- After a liquidation cascade completes, price often reverses (capitulation)

Signal types:
1. LIQUIDATION MAGNET: Large liquidation cluster above/below → trade TOWARD it
   (price hunts stops/liquidations)
2. POST-CASCADE REVERSAL: After a large cascade (many liquidations in short time),
   fade the move (capitulation signal)
3. CASCADE MOMENTUM: During an active cascade, ride the momentum until it exhausts

Data requirements:
- 1h OHLCV for price/ATR
- Liquidation data from exchange (_liquidations in data dict)
- Can also infer from volume spikes + OI drops (liquidation proxy)
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.liquidation_cascade")


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


class LiquidationCascadeStrategy(BaseStrategy):
    """
    Trade around liquidation events and cascades.

    In crypto perps, liquidations create forced selling/buying that moves price
    significantly. This strategy detects:
    - Liquidation cascades (volume + OI drop proxy)
    - Post-cascade reversals (capitulation = bottom/top)
    - Pre-cascade setups (price approaching known liquidation zones)

    When explicit liquidation data isn't available, uses proxy detection:
    - Volume spike (>3x average) + OI contracting = likely liquidation cascade
    - Large wicks (>60% of candle range) = stop hunts / liquidation zones
    """

    # Proxy detection thresholds
    VOLUME_SPIKE_MULT = 3.0      # 3x average volume = cascade-level spike
    VOLUME_HIGH_MULT = 2.0       # 2x = elevated, possible cascade
    OI_DROP_PCT = -0.05          # 5% OI drop in short period = positions liquidated
    WICK_RATIO_THRESHOLD = 0.60  # Wick > 60% of candle range = stop hunt

    # Price move thresholds for cascade detection
    CASCADE_MOVE_PCT = 0.03      # 3% move with volume spike = cascade
    STRONG_CASCADE_PCT = 0.05    # 5% = severe cascade

    # Post-cascade reversal timing
    MIN_CASCADE_BARS_AGO = 1     # At least 1 bar since cascade before reversal signal
    MAX_CASCADE_BARS_AGO = 4     # Reversal signal window: 1-4 bars after cascade

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("liquidation_cascade", symbols)
        self._cascade_history: Dict[str, List[Dict]] = {}

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def _detect_cascade_proxy(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Detect liquidation cascades using volume + price + wick analysis."""
        cascades = []
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        vol = df["volume"].astype(float)

        vol_avg = vol.rolling(20, min_periods=1).mean()
        vol_ratio = vol / vol_avg.replace(0, 1e-12)

        # Candle analysis
        candle_range = high - low
        body = (close - df["open"].astype(float)).abs()
        upper_wick = high - pd.concat([close, df["open"].astype(float)], axis=1).max(axis=1)
        lower_wick = pd.concat([close, df["open"].astype(float)], axis=1).min(axis=1) - low

        for i in range(max(1, len(df) - 8), len(df)):
            vr = float(vol_ratio.iloc[i])
            cr = float(candle_range.iloc[i])
            price_change = float(close.iloc[i] - close.iloc[i-1]) / float(close.iloc[i-1]) if float(close.iloc[i-1]) > 0 else 0

            if cr > 0:
                wick_up_ratio = float(upper_wick.iloc[i]) / cr
                wick_down_ratio = float(lower_wick.iloc[i]) / cr
            else:
                wick_up_ratio = 0
                wick_down_ratio = 0

            is_cascade = False
            cascade_type = None
            severity = "normal"

            # Volume spike + significant move = cascade
            if vr >= self.VOLUME_SPIKE_MULT and abs(price_change) >= self.CASCADE_MOVE_PCT:
                is_cascade = True
                cascade_type = "long_liquidation" if price_change < 0 else "short_liquidation"
                severity = "severe" if abs(price_change) >= self.STRONG_CASCADE_PCT else "moderate"

            # Volume spike + large wick = stop hunt / liquidation zone
            elif vr >= self.VOLUME_HIGH_MULT:
                if wick_down_ratio > self.WICK_RATIO_THRESHOLD:
                    is_cascade = True
                    cascade_type = "long_liquidation"  # Wicked down = longs stopped out
                    severity = "moderate"
                elif wick_up_ratio > self.WICK_RATIO_THRESHOLD:
                    is_cascade = True
                    cascade_type = "short_liquidation"  # Wicked up = shorts stopped out
                    severity = "moderate"

            if is_cascade:
                cascades.append({
                    "bar_index": i,
                    "bars_ago": len(df) - 1 - i,
                    "type": cascade_type,
                    "severity": severity,
                    "vol_ratio": vr,
                    "price_change_pct": price_change,
                    "wick_up_ratio": wick_up_ratio,
                    "wick_down_ratio": wick_down_ratio,
                })

        return cascades

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 25:
            return None

        close = df_1h["close"].astype(float)
        price = float(close.iloc[-1])
        atr = float(_atr(df_1h).iloc[-1])

        if atr <= 0 or price <= 0:
            return None

        # Check for explicit liquidation data first
        liquidations = data.get("_liquidations")  # List of recent liquidation events
        meta = data.get("_meta", {})

        # Detect cascades (explicit data or proxy)
        cascades = self._detect_cascade_proxy(df_1h)

        if not cascades:
            return None

        # Find the most recent cascade
        recent_cascade = None
        for c in reversed(cascades):
            if c["bars_ago"] <= self.MAX_CASCADE_BARS_AGO:
                recent_cascade = c
                break

        if recent_cascade is None:
            return None

        # RSI and momentum
        rsi = float(_rsi(close).iloc[-1])
        ema20 = float(_ema(close, 20).iloc[-1])
        ema50 = float(_ema(close, 50).iloc[-1])

        side = None
        signal_type = None
        confidence = 55.0

        # SIGNAL: Post-cascade reversal (capitulation trade)
        if recent_cascade["bars_ago"] >= self.MIN_CASCADE_BARS_AGO:
            if recent_cascade["type"] == "long_liquidation":
                # Longs got liquidated (price crashed) → reversal BUY
                side = "BUY"
                signal_type = "post_cascade_reversal"

                # RSI confirmation: should be oversold (crypto-calibrated 25/75)
                if rsi < 25:
                    confidence += 12.0
                elif rsi < 40:
                    confidence += 5.0
                elif rsi > 50:
                    confidence -= 10.0  # Not oversold enough for reversal

            elif recent_cascade["type"] == "short_liquidation":
                # Shorts got liquidated (price pumped) → reversal SELL
                side = "SELL"
                signal_type = "post_cascade_reversal"

                if rsi > 75:
                    confidence += 12.0
                elif rsi > 60:
                    confidence += 5.0
                elif rsi < 50:
                    confidence -= 10.0

            # Severity bonus
            if recent_cascade["severity"] == "severe":
                confidence += 10.0  # Severe cascades = stronger reversals
            else:
                confidence += 5.0

            # Volume spike magnitude
            if recent_cascade["vol_ratio"] > 4.0:
                confidence += 5.0

            # Price recovery check: is price starting to recover?
            if recent_cascade["bars_ago"] >= 2:
                prev_close = float(close.iloc[-2])
                recovery = (price - prev_close) / prev_close if prev_close > 0 else 0
                if side == "BUY" and recovery > 0.005:
                    confidence += 5.0  # Price recovering
                elif side == "SELL" and recovery < -0.005:
                    confidence += 5.0

        if side is None:
            return None

        confidence = max(50.0, min(95.0, confidence))

        # TP/SL for reversal trades
        sl_mult = 2.0   # Wider stop for reversal (volatile post-cascade)
        tp1_mult = 1.5   # Modest TP1 (catch the bounce)
        tp2_mult = 3.0   # Extended TP2 (full reversal)

        if recent_cascade["severity"] == "severe":
            tp2_mult = 4.0  # Severe cascades often produce V-reversals

        if side == "BUY":
            sl = price - atr * sl_mult
            tp1 = price + atr * tp1_mult
            tp2 = price + atr * tp2_mult
        else:
            sl = price + atr * sl_mult
            tp1 = price - atr * tp1_mult
            tp2 = price - atr * tp2_mult

        context_parts = [
            f"Liquidation cascade {signal_type}: {recent_cascade['type']}",
            f"Severity: {recent_cascade['severity']} ({recent_cascade['bars_ago']}h ago)",
            f"Vol spike: {recent_cascade['vol_ratio']:.1f}x avg",
            f"Price move: {recent_cascade['price_change_pct']*100:+.2f}%",
            f"RSI={rsi:.1f}",
        ]

        sig = Signal(
            strategy="liquidation_cascade",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "signal_type": signal_type,
                "cascade_type": recent_cascade["type"],
                "cascade_severity": recent_cascade["severity"],
                "cascade_bars_ago": recent_cascade["bars_ago"],
                "vol_ratio": recent_cascade["vol_ratio"],
                "cascade_price_change": recent_cascade["price_change_pct"],
                "rsi": rsi,
                "regime": (
                    "panic" if recent_cascade["severity"] == "severe" else
                    "high_volatility"
                ),
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(f"[{symbol}] Liquidation Cascade signal: {side} conf={confidence:.0f}% "
                     f"type={recent_cascade['type']} severity={recent_cascade['severity']}")
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 25:
            return {"strategy": self.name, "symbol": symbol, "state": "insufficient_data"}

        cascades = self._detect_cascade_proxy(df_1h)
        recent = cascades[-1] if cascades else None
        return {
            "strategy": self.name,
            "symbol": symbol,
            "recent_cascades": len(cascades),
            "last_cascade_bars_ago": recent["bars_ago"] if recent else None,
            "last_cascade_type": recent["type"] if recent else None,
        }
