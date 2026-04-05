"""Technical indicator computation for LLM agent context.

Computes RSI, ADX, MACD, Bollinger Bands, ATR, EMAs, MFI, VWAP from OHLCV data.
Uses numpy only (no TA-lib). All functions accept numpy arrays and handle edge cases.
"""

import numpy as np
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_array(data) -> np.ndarray:
    """Convert list/array to float64 numpy array."""
    return np.asarray(data, dtype=np.float64)


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average (full array).

    Formula: EMA_t = alpha * x_t + (1 - alpha) * EMA_{t-1}
    where alpha = 2 / (period + 1).
    """
    alpha = 2.0 / (period + 1)
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average using cumsum trick."""
    cs = np.cumsum(values)
    cs[period:] = cs[period:] - cs[:-period]
    out = np.full_like(values, np.nan)
    out[period - 1:] = cs[period - 1:] / period
    return out


def _true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """True Range = max(H-L, |H-Cprev|, |L-Cprev|)."""
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0]
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
    return tr


# ---------------------------------------------------------------------------
# Indicator Functions
# ---------------------------------------------------------------------------

def compute_rsi(closes, period: int = 14) -> Optional[float]:
    """Relative Strength Index (Wilder's smoothed).

    RSI = 100 - 100 / (1 + RS)
    RS = avg_gain / avg_loss over *period* bars (Wilder smoothing).

    Returns float 0-100 or None if insufficient data.
    """
    c = _to_array(closes)
    if len(c) < period + 1:
        return None

    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 1)


def compute_adx(highs, lows, closes, period: int = 14) -> Optional[float]:
    """Average Directional Index.

    Measures trend strength (0-100). >25 = trending, >50 = strong trend.
    Uses Wilder smoothing for +DI/-DI and ADX.

    Returns float 0-100 or None if insufficient data.
    """
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    n = len(h)
    if n < 2 * period + 1:
        return None

    tr = _true_range(h, l, c)

    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder smoothing (first value = sum of first *period* values)
    atr_s = np.sum(tr[1:period + 1])
    pdm_s = np.sum(plus_dm[:period])
    mdm_s = np.sum(minus_dm[:period])

    dx_values = []
    for i in range(period, len(plus_dm)):
        atr_s = atr_s - atr_s / period + tr[i + 1]
        pdm_s = pdm_s - pdm_s / period + plus_dm[i]
        mdm_s = mdm_s - mdm_s / period + minus_dm[i]

        if atr_s == 0:
            continue
        plus_di = 100.0 * pdm_s / atr_s
        minus_di = 100.0 * mdm_s / atr_s
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(100.0 * abs(plus_di - minus_di) / di_sum)

    if len(dx_values) < period:
        return None

    adx = np.mean(dx_values[:period])
    for i in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[i]) / period

    return round(float(adx), 1)


def compute_macd(closes, fast: int = 12, slow: int = 26, signal_period: int = 9) -> Optional[Dict[str, float]]:
    """MACD (Moving Average Convergence Divergence).

    MACD line = EMA(fast) - EMA(slow)
    Signal line = EMA(MACD line, signal_period)
    Histogram = MACD - Signal

    Returns dict {macd, signal, histogram} or None.
    """
    c = _to_array(closes)
    if len(c) < slow + signal_period:
        return None

    ema_fast = _ema(c, fast)
    ema_slow = _ema(c, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal_period)
    histogram = macd_line - signal_line

    return {
        "macd": round(float(macd_line[-1]), 2),
        "signal": round(float(signal_line[-1]), 2),
        "histogram": round(float(histogram[-1]), 2),
    }


def compute_bollinger(closes, period: int = 20, std: float = 2.0) -> Optional[Dict[str, Any]]:
    """Bollinger Bands.

    Middle = SMA(period)
    Upper = Middle + std * StdDev(period)
    Lower = Middle - std * StdDev(period)
    Width% = (Upper - Lower) / Middle * 100
    Position = above / inside / below

    Returns dict or None.
    """
    c = _to_array(closes)
    if len(c) < period:
        return None

    window = c[-period:]
    middle = float(np.mean(window))
    sd = float(np.std(window, ddof=1)) if period > 1 else 0.0
    upper = middle + std * sd
    lower = middle - std * sd
    last = float(c[-1])

    width_pct = round((upper - lower) / middle * 100, 2) if middle != 0 else 0.0

    if last > upper:
        position = "above"
    elif last < lower:
        position = "below"
    else:
        position = "inside"

    return {
        "upper": round(upper, 2),
        "lower": round(lower, 2),
        "width_pct": width_pct,
        "position": position,
    }


def compute_atr(highs, lows, closes, period: int = 14) -> Optional[float]:
    """Average True Range (Wilder smoothed).

    ATR = Wilder-smooth(True Range, period).

    Returns float or None.
    """
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    if len(h) < period + 1:
        return None

    tr = _true_range(h, l, c)
    atr = float(np.mean(tr[1:period + 1]))
    for i in range(period + 1, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period

    return round(atr, 2)


def compute_emas(closes) -> Optional[Dict[str, Any]]:
    """EMA 9/20/50 and alignment info.

    Returns dict {ema9, ema20, ema50, ema9_20_gap_pct, alignment} or None.
    alignment: bull_aligned / bear_aligned / mixed
    """
    c = _to_array(closes)
    if len(c) < 50:
        return None

    e9 = float(_ema(c, 9)[-1])
    e20 = float(_ema(c, 20)[-1])
    e50 = float(_ema(c, 50)[-1])

    gap_pct = round((e9 - e20) / e20 * 100, 2) if e20 != 0 else 0.0

    if e9 > e20 > e50:
        alignment = "bull_aligned"
    elif e9 < e20 < e50:
        alignment = "bear_aligned"
    else:
        alignment = "mixed"

    return {
        "ema9": round(e9, 2),
        "ema20": round(e20, 2),
        "ema50": round(e50, 2),
        "ema9_20_gap_pct": gap_pct,
        "alignment": alignment,
    }


def compute_mfi(highs, lows, closes, volumes, period: int = 14) -> Optional[float]:
    """Money Flow Index.

    Typical Price = (H + L + C) / 3
    Raw MF = TP * Volume
    MFI = 100 - 100 / (1 + positive_flow / negative_flow)

    Returns float 0-100 or None.
    """
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    v = _to_array(volumes)
    if len(h) < period + 1:
        return None

    tp = (h + l + c) / 3.0
    raw_mf = tp * v

    pos_flow = 0.0
    neg_flow = 0.0
    # Use last (period+1) bars to get *period* comparisons
    start = len(tp) - period - 1
    for i in range(start + 1, len(tp)):
        if tp[i] > tp[i - 1]:
            pos_flow += raw_mf[i]
        elif tp[i] < tp[i - 1]:
            neg_flow += raw_mf[i]

    if neg_flow == 0:
        return 100.0
    mfr = pos_flow / neg_flow
    return round(100.0 - 100.0 / (1.0 + mfr), 1)


def compute_vwap(highs, lows, closes, volumes) -> Optional[float]:
    """Volume Weighted Average Price (session / full array).

    VWAP = sum(TP * Vol) / sum(Vol)

    Returns float or None.
    """
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    v = _to_array(volumes)
    if len(h) == 0:
        return None

    total_vol = np.sum(v)
    if total_vol == 0:
        return None

    tp = (h + l + c) / 3.0
    vwap = float(np.sum(tp * v) / total_vol)
    return round(vwap, 2)


# ---------------------------------------------------------------------------
# Master Functions
# ---------------------------------------------------------------------------

def compute_all_technicals(ohlcv_1h: list) -> Optional[Dict[str, Any]]:
    """Compute all indicators from 1h OHLCV data.

    Args:
        ohlcv_1h: List of [timestamp, open, high, low, close, volume] candles.
                  Needs at least 60 candles for all indicators.

    Returns:
        Dict with all indicator values, ready for agent context.
        None if data is insufficient.
    """
    if not ohlcv_1h or len(ohlcv_1h) < 30:
        return None

    try:
        arr = np.array(ohlcv_1h, dtype=np.float64)
    except (ValueError, TypeError):
        return None

    if arr.ndim != 2 or arr.shape[1] < 6:
        return None

    highs = arr[:, 2]
    lows = arr[:, 3]
    closes = arr[:, 4]
    volumes = arr[:, 5]
    last_price = float(closes[-1])

    result: Dict[str, Any] = {"price": last_price}

    rsi = compute_rsi(closes)
    if rsi is not None:
        result["rsi"] = rsi

    adx = compute_adx(highs, lows, closes)
    if adx is not None:
        result["adx"] = adx
        if adx >= 50:
            result["adx_label"] = "STRONG_TREND"
        elif adx >= 25:
            result["adx_label"] = "TRENDING"
        else:
            result["adx_label"] = "WEAK/RANGE"

    macd = compute_macd(closes)
    if macd is not None:
        result["macd"] = macd["macd"]
        result["macd_signal"] = macd["signal"]
        result["macd_histogram"] = macd["histogram"]
        result["macd_bias"] = "bull" if macd["histogram"] > 0 else "bear"

    bb = compute_bollinger(closes)
    if bb is not None:
        result["bb_upper"] = bb["upper"]
        result["bb_lower"] = bb["lower"]
        result["bb_width_pct"] = bb["width_pct"]
        result["bb_position"] = bb["position"]

    atr = compute_atr(highs, lows, closes)
    if atr is not None:
        result["atr"] = atr
        result["atr_pct"] = round(atr / last_price * 100, 2) if last_price else 0.0

    emas = compute_emas(closes)
    if emas is not None:
        result["ema9"] = emas["ema9"]
        result["ema20"] = emas["ema20"]
        result["ema50"] = emas["ema50"]
        result["ema_gap_pct"] = emas["ema9_20_gap_pct"]
        result["ema_alignment"] = emas["alignment"]

    mfi = compute_mfi(highs, lows, closes, volumes)
    if mfi is not None:
        result["mfi"] = mfi

    vwap = compute_vwap(highs, lows, closes, volumes)
    if vwap is not None:
        result["vwap"] = vwap
        result["vwap_position"] = "above" if last_price > vwap else "below"

    return result


def _fmt_price(val: float) -> str:
    """Format price compactly: 66800 -> $66.8k, 3.42 -> $3.42."""
    if val >= 10000:
        return f"${val / 1000:.1f}k"
    elif val >= 1:
        return f"${val:.2f}"
    else:
        return f"${val:.4f}"


def format_technicals_for_agent(technicals: Dict[str, Any], symbol: str = "") -> str:
    """Format technicals as compact text for agent context (~100 tokens).

    Example output:
    TECH BTC: RSI=47 ADX=64(STRONG_TREND) MACD=+42(bull) BB=inside(w=1.2%)
    ATR=315(0.47%) EMA9>EMA20>EMA50(bull_aligned) MFI=52 VWAP=$66.8k(below)
    """
    if not technicals:
        return ""

    parts = []

    # Header
    label = symbol.replace("/USDT:USDT", "").replace("/USDT", "").replace("USDT", "") if symbol else ""
    header = f"TECH {label}:" if label else "TECH:"
    parts.append(header)

    # RSI
    if "rsi" in technicals:
        parts.append(f"RSI={technicals['rsi']:.0f}")

    # ADX
    if "adx" in technicals:
        lbl = technicals.get("adx_label", "")
        parts.append(f"ADX={technicals['adx']:.0f}({lbl})")

    # MACD
    if "macd" in technicals:
        sign = "+" if technicals["macd"] >= 0 else ""
        bias = technicals.get("macd_bias", "")
        parts.append(f"MACD={sign}{technicals['macd']}({bias})")

    # Bollinger
    if "bb_position" in technicals:
        w = technicals.get("bb_width_pct", 0)
        parts.append(f"BB={technicals['bb_position']}(w={w}%)")

    # ATR
    if "atr" in technicals:
        atr_pct = technicals.get("atr_pct", 0)
        parts.append(f"ATR={technicals['atr']}({atr_pct}%)")

    # EMA alignment
    if "ema_alignment" in technicals:
        alignment = technicals["ema_alignment"]
        gap = technicals.get("ema_gap_pct", 0)
        if alignment == "bull_aligned":
            parts.append(f"EMA9>20>50(bull,gap={gap}%)")
        elif alignment == "bear_aligned":
            parts.append(f"EMA9<20<50(bear,gap={gap}%)")
        else:
            parts.append(f"EMAs=mixed(gap={gap}%)")

    # MFI
    if "mfi" in technicals:
        parts.append(f"MFI={technicals['mfi']:.0f}")

    # VWAP
    if "vwap" in technicals:
        pos = technicals.get("vwap_position", "")
        parts.append(f"VWAP={_fmt_price(technicals['vwap'])}({pos})")

    return " ".join(parts)
