"""
Strategy 4: Multi-Tier Quality Signal Bot
Ported from the user's original profitable leverage bot (Bot 4).

Core logic:
- 5m EMA20/EMA50 crossover determines side
- Session VWAP alignment confirmation
- 1h EMA trend for regime scoring
- ATR-based stop placement with swing detection
- Confidence scoring: regime + EMA alignment + VWAP + volatility fit
- Three signal tiers: PRIORITY (75%+), REGULAR (65%+), MANUAL (<65%)
- Adapted from 1m/5m/1h to 5m/30m/1h for CoinGecko data
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.multi_tier")


def _add_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA20, EMA50, EMA200 and ATR14 to a DataFrame."""
    if df is None or df.empty:
        return df
    df = df.copy()
    n = len(df)
    df["EMA20"] = df["close"].ewm(span=min(20, max(2, n)), adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=min(50, max(2, n)), adjust=False).mean()
    df["EMA200"] = df["close"].ewm(span=min(200, max(2, n)), adjust=False).mean()
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    df["ATR14"] = tr.rolling(window=min(14, max(1, n)), min_periods=1).mean()
    return df


class MultiTierQualityStrategy(BaseStrategy):
    """
    EMA crossover + VWAP + multi-timeframe regime.
    Produces tiered signals (priority/regular/manual) based on confidence.
    Originally used for leverage trading with 3-25x.
    """

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("multi_tier_quality", symbols)

    def get_required_timeframes(self) -> List[str]:
        return ["5m", "30m", "1h"]

    def _ema_side_slope(self, df: pd.DataFrame) -> tuple:
        """Get EMA50 side (above/below) and slope (up/down)."""
        if df is None or "EMA50" not in df.columns or len(df) < 5:
            return "na", "na"
        side = "above" if df["close"].iloc[-1] > df["EMA50"].iloc[-1] else "below"
        slope = "up" if df["EMA50"].iloc[-1] > df["EMA50"].iloc[-5] else "down"
        return side, slope

    def _trend_score(self, df_1h: pd.DataFrame, df_5m: pd.DataFrame) -> int:
        """Score trend alignment across timeframes."""
        s = 0
        for df in [df_1h, df_5m]:
            side, slope = self._ema_side_slope(df)
            if side == "above" and slope == "up":
                s += 1
            elif side == "below" and slope == "down":
                s -= 1
        return s

    def _compute_vwap(self, df: pd.DataFrame) -> Optional[float]:
        """Compute session VWAP from intraday data."""
        if df is None or df.empty:
            return None
        # Use last trading day's data
        last_dt = df["time"].iloc[-1]
        if pd.isna(last_dt):
            return None
        session_date = pd.to_datetime(last_dt).date()
        mask = df["time"].dt.date == session_date
        if not mask.any():
            return None
        part = df.loc[mask]
        tp = (part["high"] + part["low"] + part["close"]) / 3.0
        vol = part["volume"].clip(lower=1e-12)
        vwap = (tp * vol).cumsum() / vol.cumsum()
        return float(vwap.iloc[-1]) if not vwap.empty else None

    def _five_min_side(self, df_5m: pd.DataFrame) -> str:
        """Determine EMA20 vs EMA50 side on 5m chart."""
        if df_5m is None or df_5m.empty or "EMA20" not in df_5m.columns or "EMA50" not in df_5m.columns:
            return "na"
        return "above" if df_5m["EMA20"].iloc[-1] > df_5m["EMA50"].iloc[-1] else "below"

    def _detect_swing(self, df: pd.DataFrame, side: str) -> Optional[float]:
        """Detect recent swing high/low for stop placement."""
        if df is None or df.empty or len(df) < 3:
            return None
        h = df["high"]
        l = df["low"]
        # Find swing highs and swing lows
        swing_highs = h[(h > h.shift(1)) & (h > h.shift(-1))].dropna()
        swing_lows = l[(l < l.shift(1)) & (l < l.shift(-1))].dropna()
        if side == "SELL" and not swing_highs.empty:
            return float(swing_highs.iloc[-1])
        if side == "BUY" and not swing_lows.empty:
            return float(swing_lows.iloc[-1])
        return None

    def _ema_slope_bonus(self, df_5m: pd.DataFrame, side: str) -> int:
        """Bonus confidence if EMA50 slope aligns with trade direction."""
        try:
            if df_5m is None or df_5m.empty or "EMA50" not in df_5m.columns:
                return 0
            e = df_5m["EMA50"].iloc[-5:]
            if len(e) < 5:
                return 0
            rising = e.iloc[-1] > e.iloc[0]
            return 3 if (rising and side == "BUY") or (not rising and side == "SELL") else 0
        except Exception:
            return 0

    def _compute_confidence(
        self, regime_score: int, ema5m_side: str, side: str,
        vwap_align: bool, stop_width: float, atr: Optional[float]
    ) -> int:
        """
        Confidence scoring from the original bot:
        - Regime alignment: up to 30
        - 5m EMA alignment: up to 20
        - VWAP alignment: up to 10
        - ATR stop fit: up to 15
        """
        conf = 0
        if abs(regime_score) >= 2:
            conf += 30
        elif regime_score != 0:
            conf += 15

        ema_aligned = (
            (ema5m_side == "below" and side == "SELL") or
            (ema5m_side == "above" and side == "BUY")
        )
        if ema_aligned:
            conf += 20

        if vwap_align:
            conf += 10

        if atr and stop_width:
            if 1.2 * atr <= stop_width <= 3.0 * atr:
                conf += 15
            elif 0.8 * atr <= stop_width <= 3.5 * atr:
                conf += 8

        return min(100, conf)

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_5m = data.get("5m")
        df_30m = data.get("30m")
        df_1h = data.get("1h")

        if df_5m is None or df_5m.empty or len(df_5m) < 20:
            return None
        if df_1h is None or df_1h.empty or len(df_1h) < 10:
            return None

        # Add indicators
        df_5m = _add_emas(df_5m)
        df_30m = _add_emas(df_30m) if df_30m is not None and not df_30m.empty else df_30m
        df_1h = _add_emas(df_1h)

        # Determine side from 5m EMA crossover
        side_5m = self._five_min_side(df_5m)
        if side_5m == "na":
            return None
        side = "BUY" if side_5m == "above" else "SELL"

        entry = float(df_5m["close"].iloc[-1])
        if pd.isna(entry):
            return None

        # VWAP check
        vwap = self._compute_vwap(df_5m)
        vwap_align = bool(
            vwap and (
                (entry > vwap and side == "BUY") or
                (entry < vwap and side == "SELL")
            )
        )

        # Regime from 1h + 5m trend alignment
        ema5m_side, _ = self._ema_side_slope(df_5m)
        regime = self._trend_score(df_1h, df_5m)

        # Stop placement: prefer swing, fallback to ATR
        atr_val = float(df_5m["ATR14"].iloc[-1]) if "ATR14" in df_5m.columns and not df_5m["ATR14"].isna().all() else None
        swing = self._detect_swing(df_5m, side)

        K = 1.8
        if swing is None or pd.isna(swing):
            if atr_val is None:
                return None
            stop = entry - K * atr_val if side == "BUY" else entry + K * atr_val
        else:
            stop = float(swing)

        stop_width = abs(entry - stop)

        # ATR clamp: snap stops that are too tight or too wide
        if atr_val and atr_val > 0:
            lo = 1.0 * atr_val
            hi = 3.0 * atr_val
            if stop_width < lo:
                stop = entry - lo if side == "BUY" else entry + lo
            elif stop_width > hi:
                stop = entry - K * atr_val if side == "BUY" else entry + K * atr_val
            stop_width = abs(entry - stop)

        # TPs based on R-multiple
        tp1 = entry + 1.5 * stop_width if side == "BUY" else entry - 1.5 * stop_width
        tp2 = entry + 3.0 * stop_width if side == "BUY" else entry - 3.0 * stop_width

        # Confidence
        conf = self._compute_confidence(regime, ema5m_side, side, vwap_align, stop_width, atr_val)
        conf = min(100, max(0, conf + self._ema_slope_bonus(df_5m, side)))

        # Determine tier
        if conf >= 75:
            tier = "PRIORITY"
        elif conf >= 65:
            tier = "REGULAR"
        else:
            tier = "MANUAL"

        # Higher timeframe alignment gate for priority
        ema_1h_align = False
        if "EMA20" in df_1h.columns and "EMA50" in df_1h.columns:
            if side == "BUY":
                ema_1h_align = df_1h["EMA20"].iloc[-1] > df_1h["EMA50"].iloc[-1]
            else:
                ema_1h_align = df_1h["EMA20"].iloc[-1] < df_1h["EMA50"].iloc[-1]

        if tier == "PRIORITY" and not ema_1h_align and conf < 80:
            tier = "REGULAR"

        if conf < 50:
            return None  # Too low even for manual

        return Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=float(conf),
            entry=entry,
            sl=stop,
            tp1=tp1,
            tp2=tp2,
            atr=atr_val or 0,
            metadata={
                "tier": tier,
                "regime_score": regime,
                "ema5m_side": ema5m_side,
                "vwap": vwap,
                "vwap_align": vwap_align,
                "ema_1h_align": ema_1h_align,
                "stop_width": stop_width,
                "swing_used": swing is not None,
            },
        )

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_5m = data.get("5m")
        df_1h = data.get("1h")

        if df_5m is None or df_5m.empty:
            return {"symbol": symbol, "strategy": self.name, "status": "insufficient_data"}

        df_5m = _add_emas(df_5m)
        df_1h = _add_emas(df_1h) if df_1h is not None and not df_1h.empty else df_1h

        side_5m = self._five_min_side(df_5m)
        side = "BUY" if side_5m == "above" else ("SELL" if side_5m == "below" else "NEUTRAL")
        ema5m_side, ema5m_slope = self._ema_side_slope(df_5m)
        regime = self._trend_score(df_1h, df_5m) if df_1h is not None else 0
        vwap = self._compute_vwap(df_5m)

        return {
            "symbol": symbol,
            "strategy": self.name,
            "price": float(df_5m["close"].iloc[-1]),
            "side": side,
            "ema5m_side": ema5m_side,
            "ema5m_slope": ema5m_slope,
            "regime_score": regime,
            "vwap": vwap,
            "atr": float(df_5m["ATR14"].iloc[-1]) if "ATR14" in df_5m.columns else None,
        }
