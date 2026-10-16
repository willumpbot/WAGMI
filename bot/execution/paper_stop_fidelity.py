"""PAPER_STOP_INTRABAR: fill paper stops where a resting exchange stop would have filled.

Without it a paper stop is only checked when a scan reaches the symbol (~every 4-5 min) and fills at
THAT scan's price, so every crossed stop fills late and worse than a real resting stop-market order
(2026-10-16 owner ETH SHORT: stop 2472 crossed in the 11:10Z 5m bar, booked at 2483.45 at 11:24 ->
-1.26R instead of ~-1.0R).

ON (default OFF): PositionManager.update_price first asks for the 5m bars since the position was last
checked. The first bar whose range crosses the stop that was resting since then (high >= stop for a
short, low <= stop for a long) closes the position AT THE STOP, timestamped at that bar - or at the
bar's OPEN when the bar gapped through the stop (the worse of stop and open). Never a better-than-stop
fill. The bar that contains the previous check started before it, so only its range counts (fill at the
stop, never its pre-check open). Bars unavailable -> the old point-in-time check runs unchanged.

Bars come from the Hyperliquid public candleSnapshot (no wallet, short timeout, fresh - NOT the
fetcher's 15-minute OHLCV cache, which also drops the forming candle). Backtests never reach this: the
position manager only consults it when sim_now is None and a provider is wired (the live bot wires it
for paper mode only - a live account has real resting stops).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("bot.execution.paper_stop_fidelity")

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
BAR_S = 300                     # 5m
BARS_TTL_S = 20.0               # one candleSnapshot per symbol per ~tick
DEFAULT_MAX_LOOKBACK_S = 900.0  # first check in a process: never look further back than this

# Bar = (start_epoch_s, open, high, low, close)
Bar = Tuple[float, float, float, float, float]

_LOCK = threading.Lock()
_CACHE: Dict[str, Tuple[float, List[Bar]]] = {}

# bot symbol -> Hyperliquid coin name, where they differ (core coins; any-coin extras use owner_any_coin.hl_name)
_HL_NAMES = {"PEPE": "kPEPE", "KPEPE": "kPEPE"}


def enabled() -> bool:
    return os.getenv("PAPER_STOP_INTRABAR", "false").strip().lower() in ("1", "true", "yes", "on")


def max_lookback_s() -> float:
    try:
        return max(BAR_S, float(os.getenv("PAPER_STOP_INTRABAR_MAX_LOOKBACK_S", DEFAULT_MAX_LOOKBACK_S)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_LOOKBACK_S


def _hl_coin(symbol: str) -> str:
    sym = str(symbol or "").split("/")[0].upper()
    try:
        from core.owner_any_coin import hl_name, is_extra
        if is_extra(sym):
            return hl_name(sym)
    except Exception:
        pass
    return _HL_NAMES.get(sym, sym)


def hl_5m_bars(symbol: str, start_s: float, end_s: Optional[float] = None) -> Optional[List[Bar]]:
    """Hyperliquid 5m candles (forming bar included) covering [start_s, end_s]. None on any failure."""
    end_s = end_s or time.time()
    key = _hl_coin(symbol)
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
    if hit and now - hit[0] < BARS_TTL_S and hit[1] and hit[1][0][0] <= start_s:
        return [b for b in hit[1] if b[0] + BAR_S > start_s and b[0] <= end_s]
    try:
        import urllib.request
        body = {"type": "candleSnapshot", "req": {"coin": key, "interval": "5m",
                                                  "startTime": int((start_s - BAR_S) * 1000),
                                                  "endTime": int(end_s * 1000)}}
        req = urllib.request.Request(HL_INFO_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=4.0) as r:
            raw = json.loads(r.read()) or []
        bars = sorted(((float(b["t"]) / 1000.0, float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"]))
                       for b in raw), key=lambda b: b[0])
    except Exception as e:
        logger.warning(f"[PAPER-STOP-INTRABAR] {symbol}: 5m bars unavailable ({e}) - point-in-time stop check only")
        return None
    with _LOCK:
        _CACHE[key] = (now, bars)
    return [b for b in bars if b[0] + BAR_S > start_s and b[0] <= end_s]


def find_stop_cross(bars: Sequence[Bar], stop: float, is_long: bool,
                    since_s: float) -> Optional[Tuple[float, float]]:
    """First bar (in time order) after `since_s` whose range crosses `stop`.

    Returns (fill_price, bar_start_epoch_s) or None. fill = the stop, or the bar's open when the bar
    OPENED through the stop (worse of stop and open) - but only for a bar that started at/after
    `since_s`: the bar containing the previous check opened before it, so its open is not a fill.
    Never better than the stop.
    """
    if not stop or stop <= 0:
        return None
    for b in sorted(bars or (), key=lambda x: x[0]):
        t, o, h, lo = float(b[0]), float(b[1]), float(b[2]), float(b[3])
        if t + BAR_S <= since_s:
            continue            # wholly before the last check
        crossed = (lo <= stop) if is_long else (h >= stop)
        if not crossed:
            continue
        fill = stop
        if t >= since_s and o > 0:
            fill = min(stop, o) if is_long else max(stop, o)
        return fill, t
    return None


def now_s() -> float:
    """Wall clock (epoch s). A function so tests can replay a timeline."""
    return time.time()


def bar_dt(bar_start_s: float) -> datetime:
    return datetime.fromtimestamp(float(bar_start_s), tz=timezone.utc)


def _reset_for_tests() -> None:
    with _LOCK:
        _CACHE.clear()


BarsProvider = Callable[[str, float, Optional[float]], Optional[List[Bar]]]
