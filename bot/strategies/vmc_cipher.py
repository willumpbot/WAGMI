"""
Strategy 8: VMC (VuManChu Cipher) — Multi-Oscillator Confluence

Inspired by the popular TradingView VuManChu Cipher B indicator.
Combines multiple oscillators into a single confluence score:

1. WaveTrend oscillator (primary momentum)
2. RSI with divergence detection
3. Stochastic RSI for overbought/oversold
4. MACD histogram momentum
5. Money Flow Index (MFI) for volume-weighted momentum

Signal generation:
- BUY when WaveTrend crosses up in oversold zone AND >= 3 oscillators confirm
- SELL when WaveTrend crosses down in overbought zone AND >= 3 oscillators confirm
- Divergence detection: price makes new low but oscillator makes higher low = bullish divergence
- Confidence scales with number of confirming oscillators + divergence presence

This strategy excels at catching reversals with multi-indicator confirmation,
reducing false signals through oscillator agreement (similar to ensemble voting).

Data requirements:
- 1h OHLCV with volume
"""

import logging
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.vmc_cipher")


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=max(2, span), adjust=False).mean()


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def _wavetrend(src: pd.Series, ch_len: int = 9, avg_len: int = 12):
    """WaveTrend oscillator (LazyBear formulation)."""
    esa = _ema(src, ch_len)
    de = _ema((src - esa).abs(), ch_len).replace(0, 1e-12)
    ci = (src - esa) / (0.015 * de)
    wt1 = _ema(ci, avg_len)
    wt2 = _sma(wt1, 3)
    return wt1, wt2


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


def _stoch_rsi(close: pd.Series, rsi_period: int = 14, stoch_period: int = 14,
               smooth_k: int = 3, smooth_d: int = 3) -> Tuple[pd.Series, pd.Series]:
    """Stochastic RSI: applies stochastic formula to RSI values."""
    rsi = _rsi(close, rsi_period)
    rsi_min = rsi.rolling(stoch_period, min_periods=1).min()
    rsi_max = rsi.rolling(stoch_period, min_periods=1).max()
    stoch = 100 * (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, 1e-12)
    k = _sma(stoch, smooth_k)
    d = _sma(k, smooth_d)
    return k, d


def _mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money Flow Index — volume-weighted RSI."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mf = tp * df["volume"]
    up = (tp > tp.shift(1)).astype(float)
    dn = (tp < tp.shift(1)).astype(float)
    pos = mf.mul(up).rolling(period, min_periods=1).sum()
    neg = mf.mul(dn).rolling(period, min_periods=1).sum().replace(0, 1e-12)
    ratio = pos / neg
    return 100.0 - (100.0 / (1.0 + ratio))


def _macd_histogram(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, signal)
    return macd_line - signal_line


def _detect_divergence(price: pd.Series, oscillator: pd.Series,
                       lookback: int = 14) -> Optional[str]:
    """
    Detect bullish/bearish divergence between price and oscillator.

    Bullish: price makes lower low, oscillator makes higher low
    Bearish: price makes higher high, oscillator makes lower high
    """
    if len(price) < lookback + 2:
        return None

    recent = slice(-lookback, None)
    p = price.iloc[recent].values
    o = oscillator.iloc[recent].values

    # Find recent swing lows/highs
    # Simple approach: compare current extreme to previous extreme
    p_current = p[-1]
    o_current = o[-1]
    p_prev_low = np.min(p[:-3]) if len(p) > 3 else p[0]
    p_prev_high = np.max(p[:-3]) if len(p) > 3 else p[0]
    o_at_prev_low = o[np.argmin(p[:-3])] if len(p) > 3 else o[0]
    o_at_prev_high = o[np.argmax(p[:-3])] if len(p) > 3 else o[0]

    # Bullish divergence: price lower low, oscillator higher low
    if p_current <= p_prev_low * 1.002 and o_current > o_at_prev_low * 1.01:
        return "bullish"

    # Bearish divergence: price higher high, oscillator lower high
    if p_current >= p_prev_high * 0.998 and o_current < o_at_prev_high * 0.99:
        return "bearish"

    return None


class VMCCipherStrategy(BaseStrategy):
    """
    VuManChu Cipher-inspired multi-oscillator confluence strategy.

    Combines 5 oscillators: WaveTrend, RSI, Stochastic RSI, MACD, MFI.
    Requires >= 3 oscillator agreement for signal generation.
    Divergence detection provides high-probability reversal signals.
    """

    # WaveTrend zones
    WT_OVERBOUGHT = 60
    WT_OVERSOLD = -60
    WT_EXTREME_OB = 80
    WT_EXTREME_OS = -80

    # Minimum oscillator agreement
    MIN_OSCILLATOR_AGREE = 3  # Out of 5 oscillators

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("vmc_cipher", symbols)

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def _compute_oscillator_votes(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Compute all oscillator signals and their directional votes."""
        close = df["close"].astype(float)
        hlc3 = (df["high"] + df["low"] + df["close"]).astype(float) / 3.0

        # 1. WaveTrend
        wt1, wt2 = _wavetrend(hlc3)
        wt1_val = float(wt1.iloc[-1])
        wt2_val = float(wt2.iloc[-1])
        wt1_prev = float(wt1.iloc[-2]) if len(wt1) >= 2 else wt1_val
        wt2_prev = float(wt2.iloc[-2]) if len(wt2) >= 2 else wt2_val

        wt_cross_up = wt1_prev <= wt2_prev and wt1_val > wt2_val
        wt_cross_down = wt1_prev >= wt2_prev and wt1_val < wt2_val
        wt_oversold = wt1_val < self.WT_OVERSOLD
        wt_overbought = wt1_val > self.WT_OVERBOUGHT

        wt_vote = 0  # -1 = bearish, 0 = neutral, 1 = bullish
        if wt_cross_up and wt_oversold:
            wt_vote = 1
        elif wt_cross_down and wt_overbought:
            wt_vote = -1
        elif wt_cross_up:
            wt_vote = 0.5
        elif wt_cross_down:
            wt_vote = -0.5

        # 2. RSI
        rsi = _rsi(close)
        rsi_val = float(rsi.iloc[-1])
        rsi_prev = float(rsi.iloc[-2]) if len(rsi) >= 2 else rsi_val
        rsi_vote = 0
        if rsi_val < 30:
            rsi_vote = 1  # Oversold = bullish
        elif rsi_val > 70:
            rsi_vote = -1  # Overbought = bearish
        elif rsi_val < 40 and rsi_val > rsi_prev:
            rsi_vote = 0.5  # Rising from low
        elif rsi_val > 60 and rsi_val < rsi_prev:
            rsi_vote = -0.5  # Falling from high

        # 3. Stochastic RSI
        stoch_k, stoch_d = _stoch_rsi(close)
        k_val = float(stoch_k.iloc[-1])
        d_val = float(stoch_d.iloc[-1])
        k_prev = float(stoch_k.iloc[-2]) if len(stoch_k) >= 2 else k_val

        stoch_vote = 0
        if k_val < 20 and k_val > k_prev:
            stoch_vote = 1  # Oversold + turning up
        elif k_val > 80 and k_val < k_prev:
            stoch_vote = -1  # Overbought + turning down
        elif k_val < 30:
            stoch_vote = 0.5
        elif k_val > 70:
            stoch_vote = -0.5

        # 4. MACD histogram
        macd_hist = _macd_histogram(close)
        hist_val = float(macd_hist.iloc[-1])
        hist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else hist_val

        macd_vote = 0
        if hist_val > 0 and hist_val > hist_prev:
            macd_vote = 1  # Positive and increasing
        elif hist_val < 0 and hist_val < hist_prev:
            macd_vote = -1  # Negative and decreasing
        elif hist_val > 0:
            macd_vote = 0.5
        elif hist_val < 0:
            macd_vote = -0.5

        # 5. Money Flow Index
        mfi = _mfi(df)
        mfi_val = float(mfi.iloc[-1])

        mfi_vote = 0
        if mfi_val < 20:
            mfi_vote = 1  # Oversold on volume
        elif mfi_val > 80:
            mfi_vote = -1  # Overbought on volume
        elif mfi_val < 35:
            mfi_vote = 0.5
        elif mfi_val > 65:
            mfi_vote = -0.5

        # Divergence check (on WaveTrend and RSI)
        wt_divergence = _detect_divergence(close, wt1, lookback=14)
        rsi_divergence = _detect_divergence(close, rsi, lookback=14)

        votes = {
            "wavetrend": wt_vote,
            "rsi": rsi_vote,
            "stoch_rsi": stoch_vote,
            "macd": macd_vote,
            "mfi": mfi_vote,
        }

        return {
            "votes": votes,
            "wt1": wt1_val,
            "wt2": wt2_val,
            "wt_cross_up": wt_cross_up,
            "wt_cross_down": wt_cross_down,
            "rsi": rsi_val,
            "stoch_k": k_val,
            "stoch_d": d_val,
            "macd_hist": hist_val,
            "mfi": mfi_val,
            "wt_divergence": wt_divergence,
            "rsi_divergence": rsi_divergence,
        }

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 30:
            return None

        close = df_1h["close"].astype(float)
        price = float(close.iloc[-1])
        atr = float(_atr(df_1h).iloc[-1])

        if atr <= 0 or price <= 0:
            return None

        # Compute all oscillators
        osc = self._compute_oscillator_votes(df_1h)
        votes = osc["votes"]

        # Count bullish/bearish agreement
        bullish_score = sum(v for v in votes.values() if v > 0)
        bearish_score = sum(-v for v in votes.values() if v < 0)

        # Determine direction: need clear majority
        side = None
        agreement_score = 0

        if bullish_score >= self.MIN_OSCILLATOR_AGREE:
            side = "BUY"
            agreement_score = bullish_score
        elif bearish_score >= self.MIN_OSCILLATOR_AGREE:
            side = "SELL"
            agreement_score = bearish_score

        if side is None:
            return None

        # Base confidence from agreement level
        confidence = 55.0 + (agreement_score - self.MIN_OSCILLATOR_AGREE) * 8.0

        # WaveTrend cross in extreme zone = strong signal
        if side == "BUY" and osc["wt_cross_up"] and osc["wt1"] < self.WT_EXTREME_OS:
            confidence += 12.0
        elif side == "SELL" and osc["wt_cross_down"] and osc["wt1"] > self.WT_EXTREME_OB:
            confidence += 12.0
        elif side == "BUY" and osc["wt_cross_up"]:
            confidence += 5.0
        elif side == "SELL" and osc["wt_cross_down"]:
            confidence += 5.0

        # Divergence bonus (high-probability reversal signal)
        divergence = None
        if osc["wt_divergence"] or osc["rsi_divergence"]:
            if side == "BUY" and "bullish" in [osc["wt_divergence"], osc["rsi_divergence"]]:
                confidence += 10.0
                divergence = "bullish"
            elif side == "SELL" and "bearish" in [osc["wt_divergence"], osc["rsi_divergence"]]:
                confidence += 10.0
                divergence = "bearish"

        # Volume confirmation via MFI
        if (side == "BUY" and osc["mfi"] < 25) or (side == "SELL" and osc["mfi"] > 75):
            confidence += 5.0  # Extreme MFI confirms

        confidence = max(50.0, min(95.0, confidence))

        # TP/SL
        sl_mult = 1.5
        tp1_mult = 1.8
        tp2_mult = 3.0

        # Divergence signals tend to be stronger: wider targets
        if divergence:
            tp1_mult = 2.0
            tp2_mult = 3.5

        if side == "BUY":
            sl = price - atr * sl_mult
            tp1 = price + atr * tp1_mult
            tp2 = price + atr * tp2_mult
        else:
            sl = price + atr * sl_mult
            tp1 = price - atr * tp1_mult
            tp2 = price - atr * tp2_mult

        # Build context
        vote_summary = {k: ("bull" if v > 0 else "bear" if v < 0 else "neutral")
                        for k, v in votes.items()}
        confirming = sum(1 for v in votes.values() if (v > 0 if side == "BUY" else v < 0))

        context_parts = [
            f"VMC Cipher: {confirming}/5 oscillators confirm {side}",
            f"WT={osc['wt1']:.1f} RSI={osc['rsi']:.1f} StochRSI={osc['stoch_k']:.1f}",
            f"MFI={osc['mfi']:.1f} MACD_hist={osc['macd_hist']:.4f}",
        ]
        if divergence:
            context_parts.append(f"** {divergence.upper()} DIVERGENCE detected **")

        sig = Signal(
            strategy="vmc_cipher",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "oscillator_votes": vote_summary,
                "agreement_score": agreement_score,
                "wt1": osc["wt1"],
                "rsi": osc["rsi"],
                "stoch_k": osc["stoch_k"],
                "mfi": osc["mfi"],
                "macd_hist": osc["macd_hist"],
                "divergence": divergence,
                "regime": (
                    "trend" if agreement_score >= 4 else
                    "range" if agreement_score <= 2 else
                    "unknown"
                ),
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(f"[{symbol}] VMC Cipher signal: {side} conf={confidence:.0f}% "
                     f"agree={confirming}/5 div={divergence or 'none'}")
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 30:
            return {"strategy": self.name, "symbol": symbol, "state": "insufficient_data"}

        osc = self._compute_oscillator_votes(df_1h)
        return {
            "strategy": self.name,
            "symbol": symbol,
            "wt1": osc["wt1"],
            "rsi": osc["rsi"],
            "stoch_k": osc["stoch_k"],
            "mfi": osc["mfi"],
            "oscillator_votes": osc["votes"],
        }
