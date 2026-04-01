"""
Time-aware position sizing multipliers.

Data-driven session sizing from 500-candle / 20-day analysis (updated 2026-03-29):
- PRIME hours (UTC): 00, 11, 13, 14, 15, 22 — highest volatility & directional moves
- GOOD hours: 12, 16, 18, 20, 23
- QUIET hours: 01, 02, 07, 08, 19, 21
- DEAD hours: 03, 04, 05, 06, 09, 10, 17

Directional biases:
- 18:00 UTC: long bias (80% WR)
- 13:00-15:00 UTC: short bias (US open)

Day-of-week:
- Monday best (1.15x), Thursday worst (0.85x), weekends reduced (0.8x)

These are multiplicative on top of normal sizing, NOT replacements.
All multipliers are env-configurable for tuning.

Configuration (in trading_config.py):
- ENABLE_TIME_SIZING: master switch (default: True)
- TIME_SIZING_ALLOW_BOOST: also boost sizing in PRIME hours (default: True)
- TIME_SIZING_MAX_BOOST: cap on combined boost multiplier (default: 1.4)
- TIME_SIZING_DIRECTIONAL_BOOST: extra boost when side matches hour bias (default: 1.15)
- TIME_SIZING_DIRECTIONAL_PENALTY: penalty when side opposes hour bias (default: 0.85)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Union

logger = logging.getLogger("bot.execution.time_sizing")

# Env-configurable multipliers
WEEKEND_SIZE_MULTIPLIER = float(os.getenv("WEEKEND_SIZE_MULTIPLIER", "0.8"))

# ── Hour-of-day session multipliers (UTC) ────────────────────────────
# From 500-candle / 20-day volatility & directional-move analysis.
# PRIME=1.2, GOOD=1.0, QUIET=0.7, DEAD=0.5

_SESSION_MULTIPLIERS = {
    # PRIME hours — highest volatility & directional moves
    0:  1.2,
    11: 1.2,
    13: 1.2,
    14: 1.2,
    15: 1.2,
    22: 1.2,
    # GOOD hours — normal opportunity
    12: 1.0,
    16: 1.0,
    18: 1.0,
    20: 1.0,
    23: 1.0,
    # QUIET hours — reduced opportunity
    1:  0.7,
    2:  0.7,
    7:  0.7,
    8:  0.7,
    19: 0.7,
    21: 0.7,
    # DEAD hours — minimal opportunity
    3:  0.5,
    4:  0.5,
    5:  0.5,
    6:  0.5,
    9:  0.5,
    10: 0.5,
    17: 0.5,  # worst hour: -$1,977, 20% WR over 5 trades
}

# ── Day-of-week multipliers ──────────────────────────────────────────
# Monday=0, Tuesday=1, ... Sunday=6
_DAY_MULTIPLIERS = {
    0: 1.15,   # Monday — best day
    1: 1.0,    # Tuesday
    2: 1.0,    # Wednesday
    3: 0.85,   # Thursday — worst day
    4: 0.95,   # Friday
    5: 0.8,    # Saturday
    6: 0.8,    # Sunday
}

# ── Directional bias by hour ─────────────────────────────────────────
# Based on historical win-rate skew at specific hours.
_HOUR_BIAS = {
    13: "short",
    14: "short",
    15: "short",
    18: "long",    # 80% WR on longs
}

# Low-liquidity hours (QUIET + DEAD) for external checks
_LOW_LIQ_HOURS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 19, 21}


def get_time_multiplier(now: datetime = None) -> float:
    """Return the combined time-based sizing multiplier.

    Combines session (hour) and day-of-week multipliers.

    Returns a float in (0.0, 2.0] that should be multiplied into
    the position quantity before opening.

    Args:
        now: Override for testing. Defaults to current UTC time.

    Returns:
        Combined multiplier (day-of-week * session).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    reasons = []

    # Day-of-week multiplier
    day_mult = _DAY_MULTIPLIERS.get(now.weekday(), 1.0)
    if day_mult != 1.0:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        reasons.append(f"{day_names[now.weekday()]}({day_mult:.2f}x)")

    # Session-aware hour multiplier
    session_mult = _SESSION_MULTIPLIERS.get(now.hour, 1.0)
    if session_mult != 1.0:
        reasons.append(f"session_h{now.hour}({session_mult:.2f}x)")

    multiplier = day_mult * session_mult

    if reasons:
        logger.info(
            f"[TIME-SIZE] Applying time multiplier: {multiplier:.3f}x "
            f"({', '.join(reasons)})"
        )

    return round(multiplier, 4)


def get_directional_multiplier(
    side: str,
    now: datetime = None,
    boost: float = 1.15,
    penalty: float = 0.85,
) -> float:
    """Return a directional bias multiplier based on hour-of-day edge.

    If the trade direction matches the proven bias for this hour,
    boost the sizing. If it opposes, apply a penalty. Neutral hours
    return 1.0.

    Args:
        side: "BUY" or "SELL" — the trade direction.
        now: Override for testing. Defaults to current UTC time.
        boost: Multiplier when direction matches bias (default 1.15).
        penalty: Multiplier when direction opposes bias (default 0.85).

    Returns:
        Directional multiplier (boost, penalty, or 1.0).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    bias = _HOUR_BIAS.get(now.hour, "neutral")
    if bias == "neutral":
        return 1.0

    trade_dir = "long" if side.upper() == "BUY" else "short"

    if trade_dir == bias:
        logger.info(
            f"[TIME-SIZE] Directional boost: {side} matches h{now.hour} "
            f"{bias} bias → {boost:.2f}x"
        )
        return boost
    else:
        logger.info(
            f"[TIME-SIZE] Directional penalty: {side} opposes h{now.hour} "
            f"{bias} bias → {penalty:.2f}x"
        )
        return penalty


def get_full_time_multiplier(
    side: str = None,
    now: datetime = None,
    allow_boost: bool = True,
    max_boost: float = 1.4,
    directional_boost: float = 1.15,
    directional_penalty: float = 0.85,
) -> Dict[str, Union[float, str]]:
    """Return the complete time-based sizing adjustment.

    Combines:
    1. Hour-of-day session multiplier (PRIME/GOOD/QUIET/DEAD)
    2. Day-of-week multiplier (Mon boost, Thu penalty, weekend reduction)
    3. Directional bias multiplier (if side is provided)

    The combined multiplier is capped at max_boost to prevent runaway sizing.
    When allow_boost=False, the multiplier is capped at 1.0 (reductions only).

    Args:
        side: "BUY" or "SELL" for directional bias. None to skip.
        now: Override for testing. Defaults to current UTC time.
        allow_boost: If False, cap multiplier at 1.0 (reduce-only mode).
        max_boost: Maximum combined multiplier (default 1.4).
        directional_boost: Boost when side matches hour bias.
        directional_penalty: Penalty when side opposes hour bias.

    Returns:
        {
            "multiplier": float,  # Combined multiplier
            "base_multiplier": float,  # Hour * day multiplier (no directional)
            "directional_multiplier": float,  # Directional bias component
            "bias": "long"|"short"|"neutral",
            "session": "PRIME"|"GOOD"|"QUIET"|"DEAD",
            "reasons": [str],  # Human-readable reasons
        }
    """
    if now is None:
        now = datetime.now(timezone.utc)

    reasons = []

    # Base time multiplier (hour * day)
    base_mult = get_time_multiplier(now)

    # Classify session for metadata
    session_mult = _SESSION_MULTIPLIERS.get(now.hour, 1.0)
    if session_mult >= 1.2:
        session = "PRIME"
    elif session_mult >= 1.0:
        session = "GOOD"
    elif session_mult >= 0.7:
        session = "QUIET"
    else:
        session = "DEAD"

    bias = _HOUR_BIAS.get(now.hour, "neutral")

    # Directional bias
    dir_mult = 1.0
    if side is not None:
        dir_mult = get_directional_multiplier(
            side=side,
            now=now,
            boost=directional_boost,
            penalty=directional_penalty,
        )
        if dir_mult != 1.0:
            trade_dir = "long" if side.upper() == "BUY" else "short"
            action = "aligned" if trade_dir == bias else "opposed"
            reasons.append(f"dir_{action}({dir_mult:.2f}x)")

    combined = base_mult * dir_mult

    # Cap boost if not allowed
    if not allow_boost and combined > 1.0:
        combined = 1.0
        reasons.append("boost_capped_at_1.0")

    # Cap at max boost
    if combined > max_boost:
        reasons.append(f"capped_{combined:.2f}→{max_boost:.2f}")
        combined = max_boost

    combined = round(combined, 4)

    if base_mult != 1.0:
        reasons.insert(0, f"base({base_mult:.3f}x)")

    return {
        "multiplier": combined,
        "base_multiplier": base_mult,
        "directional_multiplier": dir_mult,
        "bias": bias,
        "session": session,
        "reasons": reasons,
    }


def get_time_sizing_info(now: datetime = None) -> Dict[str, Union[float, str]]:
    """Return multiplier AND directional bias for the current time.

    This is the rich version of get_time_multiplier() that also
    provides a directional bias hint for strategies that can use it.

    Args:
        now: Override for testing. Defaults to current UTC time.

    Returns:
        {"multiplier": float, "bias": "long"|"short"|"neutral"}
    """
    if now is None:
        now = datetime.now(timezone.utc)

    multiplier = get_time_multiplier(now)
    bias = _HOUR_BIAS.get(now.hour, "neutral")

    return {"multiplier": multiplier, "bias": bias}


def is_weekend(now: datetime = None) -> bool:
    """Check if current time is weekend (Saturday or Sunday UTC)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.weekday() in (5, 6)


def is_low_liquidity_hours(now: datetime = None) -> bool:
    """Check if current time is in low-liquidity window (QUIET + DEAD hours)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.hour in _LOW_LIQ_HOURS
