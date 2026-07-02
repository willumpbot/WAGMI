"""Mechanical regime classifier — RQ10 hybrid overlay (additive INPUT only).

Validated in coordination/RQ10_REGIME_ACCURACY.md: an ATR%-percentile / ADX(14)
hybrid nowcast is era-stable and lifts regime accuracy .600 -> .652 when
combined with the agent (agent alone misses 90% of high-vol regimes and its
"trending" label is below base rate). Per THE_STANDARD v1.3 the mechanical
read is INJECTED into the Regime agent's input as labeled context — the agent
still decides; nothing is overridden.

Method (identical to bot/tools/research/rq10_regime_accuracy.py, no lookahead;
uses only closed bars handed to it):
  - ATR%-percentile >= 0.90 over trailing 336 bars (14d of 1h)  -> high_volatility
  - else ADX(14) >= 25                                          -> trending
        (direction by DI+ vs DI-: trending_bull / trending_bear)
  - else                                                        -> ranging

Env gate: MECH_REGIME_OVERLAY=true (wired in coordinator.py).
"""
from typing import Any, Dict, List, Optional

# Trailing window for the ATR% percentile (336 x 1h = 14 days, per RQ10)
_PTILE_WINDOW = 336
# Minimum trailing samples before the percentile is trusted (per RQ10)
_PTILE_MIN_SAMPLES = 100
# RQ10 thresholds
_HIGH_VOL_PTILE = 0.90
_TRENDING_ADX = 25.0


def _wilder(vals: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(vals)
    if len(vals) < n:
        return out
    s = sum(vals[:n]) / n
    out[n - 1] = s
    for i in range(n, len(vals)):
        s = (s * (n - 1) + vals[i]) / n
        out[i] = s
    return out


def _extract_hlc(ohlcv_1h) -> Optional[Dict[str, List[float]]]:
    """Accept list of [ts, o, h, l, c, v] rows or a pandas DataFrame."""
    try:
        if ohlcv_1h is None:
            return None
        # pandas DataFrame path (live loop hands DataFrames around)
        if hasattr(ohlcv_1h, "columns"):
            cols = {c.lower(): c for c in ohlcv_1h.columns}
            if not all(k in cols for k in ("high", "low", "close")):
                return None
            return {
                "H": [float(x) for x in ohlcv_1h[cols["high"]].tolist()],
                "L": [float(x) for x in ohlcv_1h[cols["low"]].tolist()],
                "C": [float(x) for x in ohlcv_1h[cols["close"]].tolist()],
            }
        rows = list(ohlcv_1h)
        if not rows or len(rows[0]) < 6:
            return None
        return {
            "H": [float(r[2]) for r in rows],
            "L": [float(r[3]) for r in rows],
            "C": [float(r[4]) for r in rows],
        }
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def compute_mech_regime(ohlcv_1h, n: int = 14) -> Optional[Dict[str, Any]]:
    """Classify the current bar mechanically. Returns None on insufficient data.

    Returns dict: label, adx, di_plus, di_minus, atr_pct, atr_ptile (may be
    None when trailing history < _PTILE_MIN_SAMPLES), n_bars.
    """
    hlc = _extract_hlc(ohlcv_1h)
    if not hlc:
        return None
    H, L, C = hlc["H"], hlc["L"], hlc["C"]
    m = len(C)
    if m < 2 * n + 2:  # need enough bars for Wilder ADX
        return None

    tr: List[float] = []
    pdm: List[float] = []
    ndm: List[float] = []
    for i in range(1, m):
        tr.append(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])))
        up, dn = H[i] - H[i - 1], L[i - 1] - L[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        ndm.append(dn if (dn > up and dn > 0) else 0.0)

    atr = _wilder(tr, n)
    spdm = _wilder(pdm, n)
    sndm = _wilder(ndm, n)

    k = len(tr)  # = m - 1
    dx: List[Optional[float]] = [None] * k
    dip: List[Optional[float]] = [None] * k
    dim: List[Optional[float]] = [None] * k
    for i in range(k):
        a, p, q = atr[i], spdm[i], sndm[i]
        if a and a > 0 and p is not None and q is not None:
            dip[i] = 100.0 * p / a
            dim[i] = 100.0 * q / a
            den = dip[i] + dim[i]
            dx[i] = 100.0 * abs(dip[i] - dim[i]) / den if den > 0 else 0.0

    first = next((i for i in range(k) if dx[i] is not None), None)
    if first is None or k - first < n:
        return None
    adx_val = sum(dx[first:first + n]) / n  # type: ignore[arg-type]
    for i in range(first + n, k):
        adx_val = (adx_val * (n - 1) + dx[i]) / n  # type: ignore[operator]

    # ATR% series (ATR of the PRIOR closed bars over current close, per RQ10)
    atr_pct: List[Optional[float]] = [None] * m
    for i in range(1, m):
        a = atr[i - 1] if i - 1 < len(atr) else None
        if a and C[i] > 0:
            atr_pct[i] = a / C[i]
    cur = atr_pct[m - 1]
    if cur is None:
        return None
    lo = max(0, (m - 1) - _PTILE_WINDOW)
    past = [atr_pct[j] for j in range(lo, m - 1) if atr_pct[j] is not None]
    atr_ptile = (
        sum(1 for p in past if p <= cur) / len(past)
        if len(past) >= _PTILE_MIN_SAMPLES else None
    )

    di_p = dip[k - 1] if dip[k - 1] is not None else 0.0
    di_m = dim[k - 1] if dim[k - 1] is not None else 0.0

    if atr_ptile is not None and atr_ptile >= _HIGH_VOL_PTILE:
        label = "high_volatility"
    elif adx_val >= _TRENDING_ADX:
        label = "trending_bull" if di_p >= di_m else "trending_bear"
    else:
        label = "ranging"

    return {
        "label": label,
        "adx": round(float(adx_val), 1),
        "di_plus": round(float(di_p), 1),
        "di_minus": round(float(di_m), 1),
        "atr_pct": round(float(cur) * 100, 3),
        "atr_ptile": round(float(atr_ptile), 2) if atr_ptile is not None else None,
        "n_bars": m,
    }


def format_mech_regime(mech: Dict[str, Any]) -> str:
    """Labeled context string for the Regime agent's input (additive, not an override)."""
    ptile = mech.get("atr_ptile")
    ptile_s = f"{ptile:.2f}" if ptile is not None else "n/a(short history)"
    return (
        f"mechanical classifier reads: {mech.get('label')} "
        f"(ADX={mech.get('adx')}, DI+={mech.get('di_plus')}, DI-={mech.get('di_minus')}, "
        f"ATR%={mech.get('atr_pct')}, ATR ptile={ptile_s}, n_bars={mech.get('n_bars')}). "
        "Method: ATR-ptile>=0.90 -> high_volatility, else ADX14>=25 -> trending, else ranging "
        "(era-stable, RQ10). This is context, not an override — you still decide."
    )
