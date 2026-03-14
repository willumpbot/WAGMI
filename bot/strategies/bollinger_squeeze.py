"""
Strategy 7: Bollinger Band Squeeze / Expansion

Core logic:
- Detects Bollinger Band squeezes (BB inside Keltner Channel = volatility compression)
- When squeeze fires (BB exits Keltner), expect an explosive directional move
- Direction determined by: MACD histogram, momentum, and EMA alignment
- Confidence scales with squeeze duration and breakout momentum
- Also detects BB band-walks (price riding upper/lower band = strong trend)

The confidence_scorer already uses BB as ONE factor among many.
This is a DEDICATED squeeze-expansion strategy with deeper analysis:
- Squeeze duration tracking (longer squeeze = bigger breakout)
- Momentum histogram for direction determination
- Volume surge confirmation on breakout
- Band-walk continuation signals

Data requirements:
- 1h OHLCV for BB, Keltner, MACD, volume
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.bollinger_squeeze")


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


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def _bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    mid = _sma(close, period)
    std = close.rolling(period, min_periods=1).std().fillna(0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower, std


def _keltner_channels(df: pd.DataFrame, period: int = 20, atr_mult: float = 1.5):
    mid = _ema(df["close"], period)
    atr = _atr(df, period)
    upper = mid + atr_mult * atr
    lower = mid - atr_mult * atr
    return upper, mid, lower


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


class BollingerSqueezeStrategy(BaseStrategy):
    """
    Bollinger Band Squeeze detection with Keltner Channel confirmation.

    The "squeeze" occurs when Bollinger Bands contract inside Keltner Channels,
    indicating extremely low volatility. When the squeeze fires (BB expands
    outside KC), a large directional move typically follows.

    This is John Carter's TTM Squeeze adapted for crypto perpetual futures.
    """

    # Squeeze parameters
    BB_PERIOD = 20
    BB_STD_MULT = 2.0
    KC_PERIOD = 20
    KC_ATR_MULT = 1.5

    # Minimum squeeze duration to trigger (bars of compression before breakout)
    MIN_SQUEEZE_BARS = 3  # At least 3 bars in squeeze before breakout matters

    # Band-walk parameters
    BANDWALK_MIN_BARS = 3  # 3+ consecutive bars touching upper/lower band

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("bollinger_squeeze", symbols)
        # Track squeeze state per symbol
        self._squeeze_counters: Dict[str, int] = {}

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def _detect_squeeze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect squeeze state and duration."""
        close = df["close"].astype(float)

        bb_upper, bb_mid, bb_lower, bb_std = _bollinger_bands(close, self.BB_PERIOD, self.BB_STD_MULT)
        kc_upper, kc_mid, kc_lower = _keltner_channels(df, self.KC_PERIOD, self.KC_ATR_MULT)

        # Squeeze = BB inside KC
        is_squeeze = (bb_lower > kc_lower) & (bb_upper < kc_upper)

        # Count consecutive squeeze bars (from the end)
        squeeze_duration = 0
        for i in range(len(is_squeeze) - 1, -1, -1):
            if is_squeeze.iloc[i]:
                squeeze_duration += 1
            else:
                break

        # Current state
        currently_squeezed = bool(is_squeeze.iloc[-1]) if len(is_squeeze) > 0 else False

        # Squeeze just fired (was squeezed, now not)
        squeeze_fired = False
        if len(is_squeeze) >= 2:
            squeeze_fired = bool(is_squeeze.iloc[-2]) and not bool(is_squeeze.iloc[-1])

        # BB width (normalized)
        bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, 1e-12)

        return {
            "currently_squeezed": currently_squeezed,
            "squeeze_fired": squeeze_fired,
            "squeeze_duration": squeeze_duration,
            "bb_upper": bb_upper,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "bb_width": bb_width,
            "kc_upper": kc_upper,
            "kc_lower": kc_lower,
        }

    def _detect_bandwalk(self, df: pd.DataFrame, bb_upper: pd.Series, bb_lower: pd.Series) -> Optional[str]:
        """Detect band-walking (price riding the upper or lower band)."""
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        # Upper band walk: high touches or exceeds upper BB
        upper_touch = high >= bb_upper
        # Lower band walk: low touches or goes below lower BB
        lower_touch = low <= bb_lower

        # Count consecutive touches from the end
        upper_walk = 0
        for i in range(len(upper_touch) - 1, -1, -1):
            if upper_touch.iloc[i]:
                upper_walk += 1
            else:
                break

        lower_walk = 0
        for i in range(len(lower_touch) - 1, -1, -1):
            if lower_touch.iloc[i]:
                lower_walk += 1
            else:
                break

        if upper_walk >= self.BANDWALK_MIN_BARS:
            return "upper"
        if lower_walk >= self.BANDWALK_MIN_BARS:
            return "lower"
        return None

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 30:
            return None

        close = df_1h["close"].astype(float)
        price = float(close.iloc[-1])
        atr = float(_atr(df_1h).iloc[-1])

        if atr <= 0 or price <= 0:
            return None

        # Detect squeeze
        squeeze = self._detect_squeeze(df_1h)

        # MACD for direction
        macd_line, macd_signal, macd_hist = _macd(close)
        hist_current = float(macd_hist.iloc[-1])
        hist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else 0
        hist_accelerating = abs(hist_current) > abs(hist_prev)

        # Momentum direction from histogram
        momentum_up = hist_current > 0
        momentum_increasing = hist_current > hist_prev

        # RSI
        rsi = float(_rsi(close).iloc[-1])

        # Volume
        vol = df_1h["volume"].astype(float)
        vol_avg = float(vol.rolling(20, min_periods=1).mean().iloc[-1])
        vol_current = float(vol.iloc[-1])
        vol_ratio = vol_current / max(vol_avg, 1e-12)

        # EMA alignment
        ema20 = float(_ema(close, 20).iloc[-1])
        ema50 = float(_ema(close, 50).iloc[-1])

        signal_type = None
        side = None
        confidence = 50.0

        # SIGNAL TYPE 1: Squeeze fired (breakout from compression)
        if squeeze["squeeze_fired"]:
            prev_squeeze_duration = 0
            # Count how long the squeeze was BEFORE it fired
            is_squeeze_series = (squeeze["bb_lower"] > squeeze["kc_lower"]) & (squeeze["bb_upper"] < squeeze["kc_upper"])
            for i in range(len(is_squeeze_series) - 2, -1, -1):
                if is_squeeze_series.iloc[i]:
                    prev_squeeze_duration += 1
                else:
                    break

            # High-vol symbols: require longer squeeze (5 bars) to filter noise
            from trading_config import DEFAULT_SYMBOL_OVERRIDES
            _vp = getattr(DEFAULT_SYMBOL_OVERRIDES.get(symbol), "volatility_profile", "medium") if symbol else "medium"
            _min_bars = 5 if _vp == "high" else self.MIN_SQUEEZE_BARS
            if prev_squeeze_duration >= _min_bars:
                signal_type = "squeeze_breakout"

                # Direction from MACD histogram
                if momentum_up:
                    side = "BUY"
                else:
                    side = "SELL"

                confidence = 65.0

                # Longer squeeze = bigger expected breakout
                squeeze_bonus = min(15.0, prev_squeeze_duration * 2.5)
                confidence += squeeze_bonus

                # Volume surge on breakout
                if vol_ratio > 1.5:
                    confidence += 8.0
                elif vol_ratio > 1.2:
                    confidence += 4.0

                # Histogram acceleration
                if hist_accelerating:
                    confidence += 5.0

                # EMA alignment
                if (side == "BUY" and ema20 > ema50) or (side == "SELL" and ema20 < ema50):
                    confidence += 5.0

        # SIGNAL TYPE 2: Band-walk (trend continuation along BB band)
        if signal_type is None:
            bandwalk = self._detect_bandwalk(df_1h, squeeze["bb_upper"], squeeze["bb_lower"])
            if bandwalk:
                signal_type = "bandwalk"
                if bandwalk == "upper":
                    side = "BUY"
                    # RSI > 80 is natural during upper bandwalk — it confirms the trend.
                    # Only reject if RSI is DECLINING from extreme (exhaustion reversal).
                    confidence = 62.0
                    if rsi > 85:
                        confidence += 3.0  # Strong trend confirmation
                else:
                    side = "SELL"
                    confidence = 62.0
                    if rsi < 15:
                        confidence += 3.0  # Strong trend confirmation

                # Volume confirmation
                if vol_ratio > 1.2:
                    confidence += 5.0

                # MACD alignment
                if (side == "BUY" and momentum_up) or (side == "SELL" and not momentum_up):
                    confidence += 5.0

        if signal_type is None or side is None:
            return None

        confidence = max(50.0, min(95.0, confidence))

        # TP/SL — widened for crypto volatility. Old 1.2x bandwalk stops hit on
        # every wick, causing 100% SL loss rate in 7-day backtest. Fee drag at
        # tight stops (14.5% of distance) made trades structurally unprofitable.
        # High-vol symbols: wider TP2 (let breakouts run), slightly higher MIN_SQUEEZE_BARS
        from trading_config import DEFAULT_SYMBOL_OVERRIDES
        _vol_prof = getattr(DEFAULT_SYMBOL_OVERRIDES.get(symbol), "volatility_profile", "medium") if symbol else "medium"
        _high_vol = (_vol_prof == "high")

        if signal_type == "squeeze_breakout":
            sl_mult = 2.0   # was 1.5: wider stop, fee drag drops from 11.6% to 8.7%
            tp1_mult = 2.5   # was 2.0: proportional to maintain R:R
            tp2_mult = 6.0 if _high_vol else 5.0   # high-vol: let breakouts run further
        else:  # bandwalk
            sl_mult = 1.8   # was 1.2: #1 profit killer, way too tight for crypto
            tp1_mult = 2.2   # was 1.5: proportional to wider stop
            tp2_mult = 4.0 if _high_vol else 3.5   # high-vol: wider trailing target

        if side == "BUY":
            sl = price - atr * sl_mult
            tp1 = price + atr * tp1_mult
            tp2 = price + atr * tp2_mult
        else:
            sl = price + atr * sl_mult
            tp1 = price - atr * tp1_mult
            tp2 = price - atr * tp2_mult

        bb_width_current = float(squeeze["bb_width"].iloc[-1]) if len(squeeze["bb_width"]) > 0 else 0

        context_parts = [
            f"BB {signal_type.replace('_', ' ').title()}",
            f"MACD hist={hist_current:.4f} ({'accel' if hist_accelerating else 'decel'})",
            f"BB width={bb_width_current*100:.2f}%",
            f"Vol={vol_ratio:.2f}x avg",
            f"RSI={rsi:.1f}",
        ]
        if signal_type == "squeeze_breakout":
            context_parts.insert(1, f"Squeeze duration: {squeeze['squeeze_duration']} bars")

        sig = Signal(
            strategy="bollinger_squeeze",
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
                "squeeze_duration": squeeze["squeeze_duration"],
                "bb_width": bb_width_current,
                "macd_histogram": hist_current,
                "hist_accelerating": hist_accelerating,
                "volume_ratio": vol_ratio,
                "rsi": rsi,
                "regime": (
                    "range" if signal_type == "squeeze_breakout" else
                    "trend" if signal_type == "bandwalk" else
                    "high_volatility"
                ),
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(f"[{symbol}] BB Squeeze signal: {side} conf={confidence:.0f}% "
                     f"type={signal_type} width={bb_width_current*100:.2f}%")
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 30:
            return {"strategy": self.name, "symbol": symbol, "state": "insufficient_data"}

        squeeze = self._detect_squeeze(df_1h)
        return {
            "strategy": self.name,
            "symbol": symbol,
            "squeezed": squeeze["currently_squeezed"],
            "squeeze_duration": squeeze["squeeze_duration"],
            "bb_width": float(squeeze["bb_width"].iloc[-1]) if len(squeeze["bb_width"]) > 0 else 0,
        }
