"""
Pure-quant regime detector — no LLM needed.

Classifies market regime from OHLCV data using:
- EMA20/50/200 alignment (trend direction)
- ADX (trend strength)
- ATR percentile (volatility regime)
- Price position relative to EMAs (bull/bear structure)

Returns one of the standard regime labels used by the agent system:
  trend, trending_bull, trending_bear, consolidation, range,
  high_volatility, panic, low_liquidity, unknown

This replaces the LLM regime agent when LLM_MODE=0 so that all
regime-conditional sizing, gating, and TP/SL logic works correctly.

Usage:
    from core.quant_regime import detect_regime
    regime = detect_regime(candles_1h)  # list of {open, high, low, close}
"""

import logging
import math
from typing import Dict, List, Optional

logger = logging.getLogger("bot.core.quant_regime")


def _ema(values: List[float], period: int) -> List[float]:
    """Compute EMA from a list of values."""
    if not values or period < 1:
        return []
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def _true_range(candles: List[Dict]) -> List[float]:
    """Compute true range from OHLCV candles."""
    tr = []
    for i, c in enumerate(candles):
        h, l, cl = c["high"], c["low"], c["close"]
        if i == 0:
            tr.append(h - l)
        else:
            prev_c = candles[i - 1]["close"]
            tr.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return tr


def _atr(candles: List[Dict], period: int = 14) -> float:
    """Compute current ATR."""
    tr = _true_range(candles)
    if len(tr) < period:
        return sum(tr) / max(len(tr), 1)
    ema = _ema(tr, period)
    return ema[-1] if ema else 0


def _adx(candles: List[Dict], period: int = 14) -> float:
    """Compute approximate ADX from candles."""
    if len(candles) < period * 2:
        return 20.0  # Default neutral

    plus_dm = []
    minus_dm = []
    tr = _true_range(candles)

    for i in range(1, len(candles)):
        up = candles[i]["high"] - candles[i - 1]["high"]
        down = candles[i - 1]["low"] - candles[i]["low"]

        if up > down and up > 0:
            plus_dm.append(up)
        else:
            plus_dm.append(0)

        if down > up and down > 0:
            minus_dm.append(down)
        else:
            minus_dm.append(0)

    if len(plus_dm) < period or len(tr) < period + 1:
        return 20.0

    # Smoothed +DM, -DM, TR
    sm_plus = _ema(plus_dm, period)
    sm_minus = _ema(minus_dm, period)
    sm_tr = _ema(tr[1:], period)  # Skip first TR (no previous close)

    if not sm_plus or not sm_minus or not sm_tr:
        return 20.0

    # +DI and -DI
    tr_val = sm_tr[-1]
    if tr_val == 0:
        return 20.0

    plus_di = sm_plus[-1] / tr_val * 100
    minus_di = sm_minus[-1] / tr_val * 100

    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 20.0

    dx = abs(plus_di - minus_di) / di_sum * 100

    # ── TRUE ADX (2026-07-13 toxicity-audit fix B-T1) ──────────────────────
    # The legacy path returned the INSTANTANEOUS single-bar DX, not ADX (which
    # is DX smoothed over `period`). Raw DX collapses to ~0 on every trend pause
    # and spikes on any one directional bar → corr(quant, real ADX) ≈ 0.34, ~24%
    # of hours in the wrong trend/range bucket, gating every decision. Fix:
    # smooth the DX SERIES. Validated vs mech_regime's Wilder ADX (corr 1.00) and
    # now the DEFAULT for every process. Revert: QUANT_REGIME_TRUE_ADX=false
    # (explicit opt-out that restores the legacy single-bar DX below).
    import os as _os
    if _os.getenv("QUANT_REGIME_TRUE_ADX", "true").lower() in ("1", "true", "yes"):
        # Delegate to the ALREADY-VALIDATED Wilder ADX in mech_regime (RQ10 spec)
        # rather than re-deriving smoothing math here — reuse over reinvention.
        # Lazy import avoids any circular-import at module load; fall back to the
        # legacy last-bar DX on any failure so this can never break detect_regime.
        try:
            from llm.agents.mech_regime import compute_mech_regime
            _rows = [[0, c["open"], c["high"], c["low"], c["close"], 0] for c in candles]
            _mech = compute_mech_regime(_rows, period)
            if _mech and _mech.get("adx") is not None:
                return float(_mech["adx"])
        except Exception:
            pass

    # Legacy (buggy) single-bar-DX path — only reached via explicit
    # QUANT_REGIME_TRUE_ADX=false revert or if the Wilder-ADX delegation above fails.
    return dx


def detect_regime(
    candles: List[Dict],
    symbol: str = "",
) -> str:
    """
    Detect market regime from 1h OHLCV candles.

    Args:
        candles: List of dicts with {open, high, low, close} keys.
                 Newest candle last. Need at least 50 candles.
        symbol: Optional symbol name for logging.

    Returns:
        Regime string: one of the standard labels.
    """
    if not candles or len(candles) < 20:
        return "unknown"

    closes = [c["close"] for c in candles]
    current_price = closes[-1]

    # Compute indicators
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else None
    ema200 = _ema(closes, 200) if len(closes) >= 200 else None

    atr_val = _atr(candles, 14)
    atr_pct = atr_val / current_price * 100 if current_price > 0 else 0

    adx_val = _adx(candles, 14)

    # ATR percentile (is current vol high or low?)
    atr_history = []
    for i in range(max(0, len(candles) - 50), len(candles)):
        sub = candles[max(0, i - 14):i + 1]
        if len(sub) >= 5:
            atr_history.append(_atr(sub, min(14, len(sub))))
    atr_history.sort()
    if atr_history:
        rank = sum(1 for a in atr_history if a <= atr_val)
        atr_percentile = rank / len(atr_history) * 100
    else:
        atr_percentile = 50

    # EMA alignment
    above_ema20 = current_price > ema20[-1] if ema20 else True
    above_ema50 = current_price > ema50[-1] if ema50 else True
    above_ema200 = current_price > ema200[-1] if ema200 else True

    # EMA20 slope (5-bar rate of change)
    if len(ema20) >= 6:
        ema20_slope = (ema20[-1] - ema20[-6]) / ema20[-6] * 100
    else:
        ema20_slope = 0

    # EMA50 slope
    if ema50 and len(ema50) >= 6:
        ema50_slope = (ema50[-1] - ema50[-6]) / ema50[-6] * 100
    else:
        ema50_slope = 0

    # Bull/bear EMA stack
    ema_bullish = above_ema20 and above_ema50
    ema_bearish = not above_ema20 and not above_ema50

    # ── CLASSIFICATION ──
    regime = "unknown"

    # Panic: extreme volatility (ATR > 95th percentile) + fast move
    if atr_percentile > 95 and abs(ema20_slope) > 1.0:
        regime = "panic"

    # High volatility: ATR above 80th percentile
    elif atr_percentile > 80:
        regime = "high_volatility"

    # Strong trend: ADX > 25 + EMA alignment
    elif adx_val > 25:
        if ema20_slope > 0.2 and ema_bullish:
            regime = "trending_bull"
        elif ema20_slope < -0.2 and ema_bearish:
            regime = "trending_bear"
        else:
            regime = "trend"  # Trending but mixed signals

    # Weak trend / consolidation
    elif adx_val > 18:
        if abs(ema20_slope) < 0.1:
            regime = "consolidation"
        elif ema20_slope > 0:
            regime = "trend"
        else:
            regime = "trend"

    # Low ADX: ranging
    elif adx_val <= 18:
        if atr_percentile < 20:
            regime = "consolidation"  # Tight range, low vol
        else:
            regime = "range"

    logger.info(
        f"[REGIME] {symbol or '?'}: {regime} | "
        f"ADX={adx_val:.1f} ATR%={atr_pct:.3f} ATR_pctl={atr_percentile:.0f} "
        f"EMA20_slope={ema20_slope:+.3f} "
        f"price {'>' if above_ema20 else '<'} EMA20 "
        f"{'>' if above_ema50 else '<'} EMA50"
    )

    return regime


def detect_all_regimes(
    candles_by_symbol: Dict[str, List[Dict]],
) -> Dict[str, str]:
    """Detect regime for multiple symbols at once."""
    return {
        sym: detect_regime(candles, symbol=sym)
        for sym, candles in candles_by_symbol.items()
    }
