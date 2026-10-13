"""Hard per-trade risk cap (RISK_CAP_HARD_CLAMP).

WHY (2026-10-13): MAX_RISK_PCT_CEILING reached the Risk Agent only as prompt
text (coordinator._build_risk_input -> risk_data["sizing_constraint"]). Nothing
clamped the risk_pct the agent RETURNED, and the LIVING-EDGE side multiplier
(up to 1.5x) is applied to qty AFTER sizing, so realized risk-at-stop could
exceed the ceiling. Ledger evidence: XRP SHORT 2026-10-02 -- agent returned
risk=1.0% against a 0.5% ceiling, then x1.5 side mult -> 1.51% of equity at
stop; NEAR SHORT 2026-09-21 / 2026-10-08 -- agent 0.5% x1.5 -> 0.75%.

This module bounds the REALIZED risk fraction
    |entry - stop| * qty / equity  <=  MAX_RISK_PCT_CEILING
by scaling qty DOWN (never up).

Flag RISK_CAP_HARD_CLAMP:
  false (default) -> qty returned unchanged (byte-identical behavior), but a
                     "[RISK-CLAMP-SHADOW] would clamp X -> Y" line is logged
                     whenever the clamp would bind (shadow evidence).
  true            -> qty scaled down to the ceiling; "[RISK-CLAMP]" logged.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_CEILING = 0.02  # matches coordinator's MAX_RISK_PCT_CEILING default


def clamp_enabled() -> bool:
    return os.getenv("RISK_CAP_HARD_CLAMP", "false").strip().lower() in ("1", "true", "yes")


def risk_ceiling() -> float:
    """MAX_RISK_PCT_CEILING as a fraction of equity (0.005 = 0.5%)."""
    try:
        c = float(os.getenv("MAX_RISK_PCT_CEILING", str(_DEFAULT_CEILING)))
    except (TypeError, ValueError):
        c = _DEFAULT_CEILING
    return c if c > 0 else _DEFAULT_CEILING


def realized_risk_frac(qty: float, entry: float, stop: float, equity: float) -> float:
    """Fraction of equity lost if the stop is hit (fees/slippage excluded)."""
    try:
        if equity <= 0 or qty <= 0 or entry <= 0 or stop <= 0:
            return 0.0
        return abs(entry - stop) * qty / equity
    except (TypeError, ValueError):
        return 0.0


def apply_risk_cap(qty: float, entry: float, stop: float, equity: float,
                   context: str = "") -> float:
    """Return qty with realized risk-at-stop bounded by MAX_RISK_PCT_CEILING.

    Never increases qty. Fail-neutral: any bad input or error returns qty
    unchanged. When RISK_CAP_HARD_CLAMP is off the qty is always returned
    unchanged and a shadow line is logged if the clamp would have bound.
    """
    try:
        ceiling = risk_ceiling()
        risk = realized_risk_frac(qty, entry, stop, equity)
        if risk <= ceiling or risk <= 0:
            return qty
        capped = qty * (ceiling / risk)
        if capped >= qty:  # defensive: never increase size
            return qty
        if clamp_enabled():
            logger.warning(
                "[RISK-CLAMP] %s risk %.4f%% > ceiling %.4f%%: qty %.6f -> %.6f",
                context, risk * 100, ceiling * 100, qty, capped)
            return capped
        logger.info(
            "[RISK-CLAMP-SHADOW] %s would clamp %.6f -> %.6f "
            "(risk %.4f%% > ceiling %.4f%%; RISK_CAP_HARD_CLAMP=false, not applied)",
            context, qty, capped, risk * 100, ceiling * 100)
        return qty
    except Exception as e:  # never break the entry path
        logger.debug(f"[RISK-CLAMP] error (qty unchanged): {e}")
        return qty
