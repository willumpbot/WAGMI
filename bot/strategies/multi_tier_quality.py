"""
Strategy 4: Multi-Tier Quality Signal Bot
Ported from the user's original profitable leverage bot (Bot 4).

Core logic:
- 1h EMA20/EMA50 crossover determines side
- Session VWAP alignment confirmation (from 1h data)
- 6h EMA trend for regime scoring
- ATR-based stop placement with swing detection
- Confidence scoring: regime + EMA alignment + VWAP + volatility fit
- Three signal tiers: PRIORITY (75%+), REGULAR (65%+), MANUAL (<65%)
- Adapted to 1h/6h for backtest compatibility (CoinGecko provides 30d of 1h data)
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
    # Use proper min_periods (= span) to avoid garbage EMAs on sparse data.
    # The strategy's len() guard requires 50+ bars, so EMA20/EMA50 will be valid.
    # EMA200 will have NaN for early bars — downstream code handles this.
    df["EMA20"] = df["close"].ewm(span=20, min_periods=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, min_periods=50, adjust=False).mean()
    df["EMA200"] = df["close"].ewm(span=200, min_periods=min(200, n), adjust=False).mean()
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
    Uses 1h for entry signals and 6h for regime confirmation.
    """

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("multi_tier_quality", symbols)

    def get_required_timeframes(self) -> List[str]:
        return ["1h", "6h"]

    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute ADX. Returns 0-100. ADX < 20 = ranging."""
        if len(df) < period + 1:
            return 25.0  # insufficient data, assume neutral
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        atr_val = tr.rolling(period, min_periods=1).mean()
        plus_di = (plus_dm.rolling(period, min_periods=1).mean() / atr_val.replace(0, 1e-9)) * 100
        minus_di = (minus_dm.rolling(period, min_periods=1).mean() / atr_val.replace(0, 1e-9)) * 100

        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)) * 100
        return float(dx.rolling(period, min_periods=1).mean().iloc[-1])

    def _ema_side_slope(self, df: pd.DataFrame) -> tuple:
        """Get EMA50 side (above/below) and slope (up/down)."""
        if df is None or "EMA50" not in df.columns or len(df) < 5:
            return "na", "na"
        side = "above" if df["close"].iloc[-1] > df["EMA50"].iloc[-1] else "below"
        slope = "up" if df["EMA50"].iloc[-1] > df["EMA50"].iloc[-5] else "down"
        return side, slope

    def _trend_score(self, df_6h: pd.DataFrame, df_1h: pd.DataFrame) -> int:
        """Score trend alignment across timeframes (6h + 1h)."""
        s = 0
        for df in [df_6h, df_1h]:
            side, slope = self._ema_side_slope(df)
            if side == "above" and slope == "up":
                s += 1
            elif side == "below" and slope == "down":
                s -= 1
        return s

    def _compute_vwap(self, df: pd.DataFrame) -> Optional[float]:
        """Compute session VWAP from 1h data."""
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

    def _one_hour_side(self, df_1h: pd.DataFrame) -> str:
        """Determine EMA20 vs EMA50 side on 1h chart."""
        if df_1h is None or df_1h.empty or "EMA20" not in df_1h.columns or "EMA50" not in df_1h.columns:
            return "na"
        return "above" if df_1h["EMA20"].iloc[-1] > df_1h["EMA50"].iloc[-1] else "below"

    def _detect_swing(self, df: pd.DataFrame, side: str) -> Optional[float]:
        """Detect recent swing high/low for stop placement."""
        if df is None or df.empty or len(df) < 3:
            return None
        h = df["high"]
        l = df["low"]
        swing_highs = h[(h > h.shift(1)) & (h > h.shift(-1))].dropna()
        swing_lows = l[(l < l.shift(1)) & (l < l.shift(-1))].dropna()
        if side == "SELL" and not swing_highs.empty:
            return float(swing_highs.iloc[-1])
        if side == "BUY" and not swing_lows.empty:
            return float(swing_lows.iloc[-1])
        return None

    def _ema_slope_bonus(self, df_1h: pd.DataFrame, side: str) -> int:
        """Bonus confidence if 1h EMA50 slope aligns with trade direction."""
        try:
            if df_1h is None or df_1h.empty or "EMA50" not in df_1h.columns:
                return 0
            e = df_1h["EMA50"].iloc[-5:]
            if len(e) < 5:
                return 0
            rising = e.iloc[-1] > e.iloc[0]
            return 3 if (rising and side == "BUY") or (not rising and side == "SELL") else 0
        except Exception:
            return 0

    def _compute_confidence(
        self, regime_score: int, ema1h_side: str, side: str,
        vwap_align: bool, stop_width: float, atr: Optional[float]
    ) -> int:
        """
        Confidence scoring:
        - Regime alignment (6h+1h): up to 30
        - 1h EMA alignment: up to 20
        - VWAP alignment: up to 10
        - ATR stop fit: up to 15
        """
        conf = 0
        if abs(regime_score) >= 2:
            conf += 30
        elif regime_score != 0:
            conf += 15

        ema_aligned = (
            (ema1h_side == "below" and side == "SELL") or
            (ema1h_side == "above" and side == "BUY")
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
        df_1h = data.get("1h")
        df_6h = data.get("6h")

        if df_1h is None or df_1h.empty or len(df_1h) < 50:
            return None
        if df_6h is None or df_6h.empty or len(df_6h) < 5:
            return None

        # Add indicators
        df_1h = _add_emas(df_1h)
        df_6h = _add_emas(df_6h)

        # ADX filter: skip signal generation in ranging/weak-trend markets
        # multi_tier_quality is the biggest PnL loser — most vulnerable to chop.
        # ADX 20-22 is the "maybe trending" zone with terrible WR. Raised to 22.
        adx_val = self._compute_adx(df_1h)
        # Use centralized ADX threshold from config
        try:
            from trading_config import TradingConfig as _TC
            _adx_thresh = _TC().adx_min_trending
        except Exception:
            _adx_thresh = 22.0
        if adx_val < _adx_thresh:
            return None

        # Squeeze detection: skip signals during volatility compression.
        # ATR compression (current ATR < 60% of 20-bar ATR average) = squeeze.
        # During squeeze, price direction is 50/50 — signals are coin flips.
        if "ATR14" in df_1h.columns and not df_1h["ATR14"].isna().all():
            _cur_atr = float(df_1h["ATR14"].iloc[-1])
            _avg_atr = float(df_1h["ATR14"].tail(20).mean())
            try:
                from trading_config import TradingConfig as _TC
                _squeeze_ratio = _TC().squeeze_atr_ratio
            except Exception:
                _squeeze_ratio = 0.65
            if _avg_atr > 0 and _cur_atr < _avg_atr * _squeeze_ratio:
                return None  # Volatility squeeze — skip

        # Determine side from 1h EMA crossover
        side_1h = self._one_hour_side(df_1h)
        if side_1h == "na":
            return None
        side = "BUY" if side_1h == "above" else "SELL"

        entry = float(df_1h["close"].iloc[-1])
        if pd.isna(entry):
            return None

        # VWAP check from 1h data
        vwap = self._compute_vwap(df_1h)
        vwap_align = bool(
            vwap and (
                (entry > vwap and side == "BUY") or
                (entry < vwap and side == "SELL")
            )
        )

        # Regime from 6h + 1h trend alignment
        ema1h_side, _ = self._ema_side_slope(df_1h)
        regime = self._trend_score(df_6h, df_1h)

        # Stop placement: prefer swing on 1h, fallback to ATR
        atr_val = float(df_1h["ATR14"].iloc[-1]) if "ATR14" in df_1h.columns and not df_1h["ATR14"].isna().all() else None
        swing = self._detect_swing(df_1h, side)

        # Use centralized ATR multiplier (was hardcoded 1.8, now from config for consistency)
        try:
            from trading_config import TradingConfig as _TC
            K = _TC().sl_atr_multiplier
        except Exception:
            K = 1.5
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
        tp1 = entry + 2.0 * stop_width if side == "BUY" else entry - 2.0 * stop_width
        tp2 = entry + 4.0 * stop_width if side == "BUY" else entry - 4.0 * stop_width

        # Confidence
        conf = self._compute_confidence(regime, ema1h_side, side, vwap_align, stop_width, atr_val)
        conf = min(100, max(0, conf + self._ema_slope_bonus(df_1h, side)))

        # Determine tier
        if conf >= 75:
            tier = "PRIORITY"
        elif conf >= 65:
            tier = "REGULAR"
        else:
            tier = "MANUAL"

        # Higher timeframe (6h) alignment gate for priority
        ema_6h_align = False
        if "EMA20" in df_6h.columns and "EMA50" in df_6h.columns:
            if side == "BUY":
                ema_6h_align = df_6h["EMA20"].iloc[-1] > df_6h["EMA50"].iloc[-1]
            else:
                ema_6h_align = df_6h["EMA20"].iloc[-1] < df_6h["EMA50"].iloc[-1]

        # 6h misalignment downgrades ANY tier (not just PRIORITY).
        # REGULAR/MANUAL signals with opposite 6h trend are net losers.
        if not ema_6h_align and conf < 80:
            if tier == "PRIORITY":
                tier = "REGULAR"
            elif tier == "REGULAR":
                tier = "MANUAL"
            elif tier == "MANUAL":
                return None  # No tier left — reject signal

        # Hard regime gate: neutral regime (no directional conviction) → reject.
        # Backtest data shows neutral-regime trades are net losers. The previous
        # soft-cap to 68% still allowed losing trades through.
        if abs(regime) == 0:
            return None  # No trend on any timeframe = no trade

        if conf < 55:
            return None

        rr = abs(entry - tp1) / stop_width if stop_width > 0 else 0
        ctx = (
            f"1h EMA20{'>' if ema1h_side == 'above' else '<'}EMA50, "
            f"VWAP {'aligned' if vwap_align else 'opposed'}, "
            f"6h EMA {'aligned' if ema_6h_align else 'opposed'}, "
            f"tier={tier}, R:R={rr:.1f}"
        )

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
            signal_context=ctx,
            metadata={
                "tier": tier,
                "regime_score": regime,
                "ema1h_side": ema1h_side,
                "vwap": vwap,
                "vwap_align": vwap_align,
                "ema_6h_align": ema_6h_align,
                "stop_width": stop_width,
                "swing_used": swing is not None,
                "adx": round(adx_val, 1),
                # Regime classification for system-wide regime detector
                "regime": (
                    "trend" if abs(regime) >= 2 else
                    "range" if regime == 0 else
                    "unknown"
                ),
            },
        )

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = data.get("1h")
        df_6h = data.get("6h")

        if df_1h is None or df_1h.empty:
            return {"symbol": symbol, "strategy": self.name, "status": "insufficient_data"}

        df_1h = _add_emas(df_1h)
        df_6h = _add_emas(df_6h) if df_6h is not None and not df_6h.empty else df_6h

        side_1h = self._one_hour_side(df_1h)
        side = "BUY" if side_1h == "above" else ("SELL" if side_1h == "below" else "NEUTRAL")
        ema1h_side, ema1h_slope = self._ema_side_slope(df_1h)
        regime = self._trend_score(df_6h, df_1h) if df_6h is not None else 0
        vwap = self._compute_vwap(df_1h)

        return {
            "symbol": symbol,
            "strategy": self.name,
            "price": float(df_1h["close"].iloc[-1]),
            "side": side,
            "ema1h_side": ema1h_side,
            "ema1h_slope": ema1h_slope,
            "regime_score": regime,
            "vwap": vwap,
            "atr": float(df_1h["ATR14"].iloc[-1]) if "ATR14" in df_1h.columns else None,
        }
