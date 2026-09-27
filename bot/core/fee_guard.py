"""Fee-aware exit guard (EXIT_FEE_GUARD) — blocks low-conviction, near-flat
discretionary exits (the LLM_EXIT_HIGH "dead capital → full_close" churn) that
realize only round-trip taker fees.

Built 2026-07-25 from the adversarially-verified fee-drag analysis. NOT wired
into any close path yet — this module is inert until a call site imports
`fee_guard_should_block`. Default flag state is OFF (zero behavior change).

Design corrections baked in from the verify pass:
- Round-trip fee is recomputed as 2 * taker_fee_bps directly (≈9bps). Do NOT use
  Position.fee_pct — that is the slippage-padded break-even value (~19bps).
- Mandatory escape: once |move| clears the hurdle the guard passes, so genuine
  adverse moves (real losers, |move| >> hurdle) and favorable moves are never
  blocked — only the ~flat breakeven closes are held.
- Critical urgency always bypasses (real invalidations still exit instantly).
- Fail-open: any error returns block=False, preserving current behavior.
"""
import os


def _fnum(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def fee_guard_mode() -> str:
    """'off' | 'shadow' | 'true' — parsed from EXIT_FEE_GUARD (default off)."""
    m = os.getenv("EXIT_FEE_GUARD", "false").strip().lower()
    if m in ("true", "1", "yes", "on"):
        return "true"
    if m == "shadow":
        return "shadow"
    return "off"


def fee_guard_should_block(
    *,
    taker_fee_bps: float,
    entry: float,
    current_price: float,
    side: str,
    urgency: str = "high",
    is_discretionary: bool = True,
) -> tuple:
    """Decide whether to BLOCK a discretionary near-flat exit to avoid pure fee bleed.

    Returns (block: bool, mode: str, detail: str).
      - off    -> (False, 'off', '')                      never blocks
      - shadow -> (False, 'shadow', 'WOULD_BLOCK ...'|'pass ...')  log-only, never blocks live
      - true   -> (would_block, 'true', 'BLOCK ...'|'pass ...')

    Blocks only when: mode is shadow/true AND is_discretionary AND urgency != critical
    AND |price move bps| < K * round_trip_fee_bps  (round_trip = 2*taker_fee_bps,
    K = EXIT_FEE_GUARD_K, default 1.5). Fail-open on any error.
    """
    try:
        mode = fee_guard_mode()
        if mode == "off":
            return (False, "off", "")
        if not is_discretionary:
            return (False, mode, "not-discretionary")
        if str(urgency).strip().lower() == "critical":
            return (False, mode, "critical-bypass")
        if not entry or entry <= 0:
            return (False, mode, "no-entry")
        rt_fee_bps = 2.0 * float(taker_fee_bps)
        k = _fnum("EXIT_FEE_GUARD_K", 1.5)
        hurdle = k * rt_fee_bps
        is_long = str(side).strip().upper() in ("LONG", "BUY")
        move = (current_price - entry) if is_long else (entry - current_price)
        move_bps = (move / entry) * 10000.0
        would_block = abs(move_bps) < hurdle
        detail = "move=%.1fbps hurdle=%.1fbps (K=%.2f x rt_fee=%.1fbps)" % (
            move_bps, hurdle, k, rt_fee_bps)
        if mode == "shadow":
            return (False, "shadow", ("WOULD_BLOCK " if would_block else "pass ") + detail)
        return (would_block, "true", ("BLOCK " if would_block else "pass ") + detail)
    except Exception as e:  # fail-open: never break a close on a guard error
        return (False, "error", "fail-open:%r" % (e,))
