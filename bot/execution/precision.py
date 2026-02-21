"""
Per-symbol precision rounding for prices and quantities.

Uses Decimal for exact math -- no more 0.000000 TP/SL on microcaps.
Config loaded from config/symbol_precision.json.
"""

import json
import logging
import os
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Dict, Optional

logger = logging.getLogger("bot.execution.precision")

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "symbol_precision.json"
)

# Default precision if symbol not in config
_DEFAULT = {"price": 2, "qty": 4, "min_qty": 0.01, "tick_size": 0.01, "max_leverage": 25}

_precision_cache: Dict[str, dict] = {}


def _load_config() -> Dict[str, dict]:
    """Load precision config (cached after first call)."""
    global _precision_cache
    if _precision_cache:
        return _precision_cache
    try:
        with open(_CONFIG_PATH) as f:
            _precision_cache = json.load(f)
        logger.info(f"Loaded precision config for {len(_precision_cache)} symbols")
    except FileNotFoundError:
        logger.warning(f"Precision config not found at {_CONFIG_PATH}, using defaults")
        _precision_cache = {}
    return _precision_cache


def _get_precision(symbol: str) -> dict:
    cfg = _load_config()
    return cfg.get(symbol, _DEFAULT)


def round_price(symbol: str, price: float) -> float:
    """Round a price to the correct decimal places for a symbol."""
    prec = _get_precision(symbol)["price"]
    d = Decimal(str(price)).quantize(
        Decimal(10) ** -prec, rounding=ROUND_HALF_UP
    )
    return float(d)


def round_qty(symbol: str, qty: float) -> float:
    """Round a quantity to the correct decimal places for a symbol."""
    prec = _get_precision(symbol)["qty"]
    d = Decimal(str(qty)).quantize(
        Decimal(10) ** -prec, rounding=ROUND_DOWN  # always round qty down (safer)
    )
    return float(d)


def format_price(symbol: str, price: float) -> str:
    """Format a price with correct precision for display."""
    prec = _get_precision(symbol)["price"]
    return f"{price:.{prec}f}"


def get_min_qty(symbol: str) -> float:
    """Return minimum order size for a symbol."""
    return _get_precision(symbol).get("min_qty", _DEFAULT["min_qty"])


def get_tick_size(symbol: str) -> float:
    """Return minimum price increment for a symbol."""
    return _get_precision(symbol).get("tick_size", _DEFAULT["tick_size"])


def get_max_leverage(symbol: str) -> float:
    """Return max leverage cap for a symbol."""
    return _get_precision(symbol).get("max_leverage", _DEFAULT["max_leverage"])


def get_all_symbol_specs() -> Dict[str, dict]:
    """Return the full precision config dict (for health checks)."""
    return dict(_load_config())


def validate_fill_price(
    symbol: str, fill_price: float, last_price: float, atr: float = 0.0
) -> Optional[str]:
    """Validate that a fill price is sane. Returns error string or None.

    Rejects fills that deviate more than 10x ATR or 10% from last price
    (whichever is more permissive). Prevents off-scale prices from
    polluting trades.csv.
    """
    if last_price <= 0 or fill_price <= 0:
        return f"zero/negative price: fill={fill_price} last={last_price}"

    pct_dev = abs(fill_price - last_price) / last_price
    max_pct = 0.10  # 10% max deviation from last price

    if atr > 0:
        atr_dev = abs(fill_price - last_price) / atr
        if atr_dev > 10.0 and pct_dev > max_pct:
            return (
                f"off-scale fill: {fill_price} vs last {last_price} "
                f"({pct_dev:.1%} deviation, {atr_dev:.1f}x ATR)"
            )
    elif pct_dev > max_pct:
        return (
            f"off-scale fill: {fill_price} vs last {last_price} "
            f"({pct_dev:.1%} deviation)"
        )

    return None
