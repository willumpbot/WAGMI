"""Single source of truth for what counts as a "close" in trade logs.

ROOT CAUSE (see project notes): db.trades.action / pos_mgr.trade_log[].action /
TradeLogger.trades[].action all derive from the same TradeEvent.action field,
whose only non-close value is the literal string "OPEN". force_close(reason=...)
accepts arbitrary free text (TELEGRAM_CLOSE, LLM_EXIT_<urgency>,
LIQUIDATION_PROXIMITY, FUNDING_AVOIDANCE, MFE_TAKE_PROFIT, EXIT_NOW,
LIQUIDATION_AVOID, HOLD_LIMIT, CIRCUIT_BREAKER, EMERGENCY, BACKTEST_END,
TIME_STOP, ...) so a finite allowlist can never stay correct. Use a blocklist
instead: anything that isn't "OPEN" is a close.

Separately, trade_events.jsonl's `event` field IS exhaustive by construction
(position_manager.py's SL/TRAILING_STOP->SL_HIT, TP2/TP1_FULL->TP_HIT,
else->TRADE_CLOSED if/elif/else) so that one is a small closed allowlist of
exactly 3 strings, kept as such deliberately.
"""

from __future__ import annotations

OPEN_ACTIONS = frozenset({"OPEN"})


def is_close_action(action) -> bool:
    """True if `action` represents a closing trade-log action (blocklist, not allowlist)."""
    return bool(action) and action not in OPEN_ACTIONS


CLOSE_EVENT_TYPES = frozenset({"SL_HIT", "TP_HIT", "TRADE_CLOSED"})


def is_close_event(event_type) -> bool:
    """True if `event_type` is one of the exhaustive trade_events.jsonl close buckets."""
    return event_type in CLOSE_EVENT_TYPES
