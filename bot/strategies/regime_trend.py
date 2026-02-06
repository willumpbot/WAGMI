"""
Strategy 3: Regime Trend (1h/6h/16h)
Ported from the user's original profitable bot (best_1_6_16.py).

Core logic:
- WaveTrend oscillator on 1h for entry signals
- MACD + MFI on 6h and 16h for regime confirmation
- Multi-timeframe alignment required (all must agree)
- ATR-based TP/SL with 40%/60% partial exits
- Now includes trailing stop loss support
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.regime_trend")


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _macd(close: pd.Series):
    m = _ema(close, 12) - _ema(close, 26)
    sg = _ema(m, 9)
    return m, sg, m - sg


def _mfi_like(df: pd.DataFrame, period: int = 60) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mf = tp * df["volume"]
    up = (tp > tp.shift(1)).astype(float)
    dn = (tp < tp.shift(1)).astype(float)
    pos = mf.mul(up).rolling(period, min_periods=1).mean()
    neg = mf.mul(dn).rolling(period, min_periods=1).mean().replace(0, 1e-12)
    ratio = pos / neg
    return 100.0 - (100.0 / (1.0 + ratio))


def _wavetrend(src: pd.Series):
    esa = src.ewm(span=9, adjust=False).mean()
    de = (src - esa).abs().ewm(span=9, adjust=False).mean().replace(0, 1e-12)
    ci = (src - esa) / (0.015 * de)
    wt1 = ci.ewm(span=12, adjust=False).mean()
    wt2 = wt1.rolling(3, min_periods=1).mean()
    return wt1, wt2


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


class RegimeTrendStrategy(BaseStrategy):
    """
    Multi-timeframe regime trend strategy.
    1h WaveTrend crossovers filtered by 6h+16h MACD/MFI regime alignment.
    """

    def __init__(self, symbols: Dict[str, Any], htf_hours: int = 16):
        super().__init__("regime_trend", symbols)
        self.htf_hours = htf_hours

    def get_required_timeframes(self) -> List[str]:
        return ["1h", "6h"]

    def _check_regime(self, df: pd.DataFrame, min_bars: int = 10) -> Dict[str, Any]:
        """Check MACD + MFI regime on a higher timeframe."""
        if df.empty or len(df) < min_bars:
            return {"ok": False, "macd_h": 0, "mfi": 50}

        _, _, hist = _macd(df["close"])
        mfi = _mfi_like(df, period=min(60, len(df)))

        macd_h = float(hist.iloc[-1])
        mfi_val = float(mfi.iloc[-1])
        ok = macd_h > 0 and mfi_val > 50

        return {"ok": ok, "macd_h": macd_h, "mfi": mfi_val}

    def _build_htf_candles(self, df_1h: pd.DataFrame) -> pd.DataFrame:
        """Resample 1h data to HTF (e.g. 16h) candles."""
        if df_1h.empty:
            return df_1h
        d = df_1h.copy().set_index("time")
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        out = d.resample(f"{self.htf_hours}h").agg(agg).dropna().reset_index()
        return out

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_1h = data.get("1h")
        df_6h = data.get("6h")

        if df_1h is None or df_1h.empty or len(df_1h) < 50:
            return None
        if df_6h is None or df_6h.empty or len(df_6h) < 10:
            return None

        # Build HTF candles from 1h
        df_htf = self._build_htf_candles(df_1h)
        if df_htf.empty or len(df_htf) < 5:
            return None

        # 1h WaveTrend + MFI
        src_1h = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3.0
        wt1, wt2 = _wavetrend(src_1h)
        mfi_1h = _mfi_like(df_1h, period=min(60, len(df_1h)))
        cross_up = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
        cross_dn = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))

        cu = bool(cross_up.iloc[-1])
        cd = bool(cross_dn.iloc[-1])
        mfi_1h_val = float(mfi_1h.iloc[-1])

        # 6h regime
        regime_6h = self._check_regime(df_6h)
        # HTF regime
        regime_htf = self._check_regime(df_htf)

        multi_bull = regime_6h["ok"] and regime_htf["ok"]
        multi_bear = (not regime_6h["ok"]) and (not regime_htf["ok"])

        # ATR for TP/SL
        c = float(df_1h["close"].iloc[-1])
        A = float(_atr(df_1h, 14).iloc[-1])
        R = 1.5 * A

        # Alignment scoring
        align_long = int(cu) + int(mfi_1h_val > 50) + int(regime_6h["ok"]) + int(regime_htf["ok"])
        align_short = int(cd) + int(mfi_1h_val < 50) + int(not regime_6h["ok"]) + int(not regime_htf["ok"])

        buy = cu and (mfi_1h_val > 50) and multi_bull
        sell = cd and (mfi_1h_val < 50) and multi_bear

        if not buy and not sell:
            return None

        # Build confidence from alignment
        if buy:
            confidence = align_long * 25.0  # max 100 with 4/4
            side = "BUY"
            sl = c - R
            tp1 = c + 1.0 * R
            tp2 = c + 2.0 * R
        else:
            confidence = align_short * 25.0
            side = "SELL"
            sl = c + R
            tp1 = c - 1.0 * R
            tp2 = c - 2.0 * R

        # Cross recency check (penalize if cross is stale)
        try:
            if buy:
                last_cross_idx = cross_up[::-1].idxmax() if cross_up.any() else None
                if last_cross_idx is not None:
                    bars_since = len(cross_up) - 1 - last_cross_idx
                    if bars_since > 2:
                        confidence -= (bars_since - 2) * 3
            else:
                last_cross_idx = cross_dn[::-1].idxmax() if cross_dn.any() else None
                if last_cross_idx is not None:
                    bars_since = len(cross_dn) - 1 - last_cross_idx
                    if bars_since > 2:
                        confidence -= (bars_since - 2) * 3
        except Exception:
            pass

        confidence = max(0, min(100, confidence))

        if confidence < 60:
            return None

        return Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=c,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=A,
            metadata={
                "align_long": align_long,
                "align_short": align_short,
                "wt1": float(wt1.iloc[-1]),
                "wt2": float(wt2.iloc[-1]),
                "mfi_1h": mfi_1h_val,
                "regime_6h": regime_6h,
                "regime_htf": regime_htf,
                "atr_1h": A,
                "cross": "up" if cu else ("down" if cd else "none"),
            },
        )

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = data.get("1h")
        df_6h = data.get("6h")

        if df_1h is None or df_1h.empty or len(df_1h) < 50:
            return {"symbol": symbol, "strategy": self.name, "status": "insufficient_data"}

        src_1h = (df_1h["high"] + df_1h["low"] + df_1h["close"]) / 3.0
        wt1, wt2 = _wavetrend(src_1h)
        mfi_1h = _mfi_like(df_1h, period=min(60, len(df_1h)))
        cross_up = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
        cross_dn = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))
        cu = bool(cross_up.iloc[-1])
        cd = bool(cross_dn.iloc[-1])

        regime_6h = self._check_regime(df_6h) if df_6h is not None and not df_6h.empty else {"ok": False}
        df_htf = self._build_htf_candles(df_1h)
        regime_htf = self._check_regime(df_htf) if not df_htf.empty else {"ok": False}

        align_long = int(cu) + int(float(mfi_1h.iloc[-1]) > 50) + int(regime_6h["ok"]) + int(regime_htf["ok"])
        align_short = int(cd) + int(float(mfi_1h.iloc[-1]) < 50) + int(not regime_6h["ok"]) + int(not regime_htf["ok"])

        return {
            "symbol": symbol,
            "strategy": self.name,
            "price": float(df_1h["close"].iloc[-1]),
            "wt1": float(wt1.iloc[-1]),
            "wt2": float(wt2.iloc[-1]),
            "mfi_1h": float(mfi_1h.iloc[-1]),
            "cross": "up" if cu else ("down" if cd else "none"),
            "regime_6h": regime_6h,
            "regime_htf": regime_htf,
            "align_long": align_long,
            "align_short": align_short,
            "atr_1h": float(_atr(df_1h, 14).iloc[-1]),
        }
