"""Registry of canonical position-close types (Phase 0.4-A3).

WHAT THIS IS: dispatch METADATA for the 27 known production close reasons
(the strings passed as the `reason`/`action` argument to `force_close(...)`,
`partial_close(...)`, and `_close_position(...)` in execution/
position_manager.py). Each entry records what kind of close it is (full vs.
partial leg), whether it's live/backtest-only/vestigial, whether it's one of
the "mechanical" PM-internal SL/TP/TRAILING events the god-block special-
cases, and who is responsible for submitting the exchange order under the
0.4 close-handler rebuild (`execution/close_with_execution.py`, not yet
built in this phase).

WHAT THIS IS NOT: this module is NOT the authority on "is this string a
close action" -- that stays core/close_taxonomy.py's blocklist
(`is_close_action`), which is deliberately permissive (anything that isn't
"OPEN" is a close, because force_close(reason=...) accepts arbitrary free
text and a finite allowlist can never stay correct). This registry exists
one layer up: once something IS known to be a close, what do we know about
it for dispatch/routing purposes? Never use CLOSE_TYPES / `get()` /
`is_full()` / `is_partial()` as a substitute for
`close_taxonomy.is_close_action()` -- an unregistered close type is still a
close (see T-TAX below), it's just metadata-less until someone adds it here.

LEAF MODULE INVARIANT: this file must import nothing from
execution/position_manager.py, multi_strategy_main.py, or any other
module that could pull in exchange/LLM/state machinery -- stdlib +
dataclasses/enum only. Downstream close-pipeline consumers (Phase B) import
this freely without dragging in the world.

Source of truth for the table below: spec04.md section (1) "FINAL CANONICAL
CLOSE_TYPES -- 27 prod types" (hardened 2026-07-21 build-ready spec for the
0.4 close-handler rebuild).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, Optional


class CloseKind(str, Enum):
    """Whether a close type terminates the position's lifecycle (FULL) or
    just closes one leg while the position stays open (PARTIAL)."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"


# Exchange-order routing under the 0.4 close-handler rebuild:
#   HELPER                -- must go through execution/close_with_execution.py
#                             (the sanctioned close entry point; order-first)
#   GOD_BLOCK_PM_INTERNAL -- PositionManager's own SL/TP/TRAILING checks
#                             submit no exchange order themselves; the
#                             god-block in multi_strategy_main.py owns
#                             the exchange call for these today
#   NONE_OWNER_GATED      -- exchange order submission is currently disabled
#                             pending explicit owner sign-off (HOLD_LIMIT)
_EXCHANGE_ORDER_VALUES = frozenset({
    "HELPER", "GOD_BLOCK_PM_INTERNAL", "NONE_OWNER_GATED",
})


@dataclass(frozen=True)
class CloseType:
    """One row of the close-type registry. Immutable -- this is reference
    data, never mutated at runtime."""

    name: str
    kind: CloseKind
    live: bool
    backtest_only: bool
    vestigial: bool
    mechanical: bool
    exchange_order: str  # one of _EXCHANGE_ORDER_VALUES
    tel_bucket: str

    def __post_init__(self) -> None:
        if self.exchange_order not in _EXCHANGE_ORDER_VALUES:
            raise ValueError(
                f"CloseType {self.name!r}: exchange_order={self.exchange_order!r} "
                f"not in {sorted(_EXCHANGE_ORDER_VALUES)}"
            )


def _ct(
    name: str,
    kind: CloseKind,
    exchange_order: str,
    tel_bucket: str,
    *,
    live: bool = True,
    backtest_only: bool = False,
    vestigial: bool = False,
    mechanical: bool = False,
) -> CloseType:
    return CloseType(
        name=name,
        kind=kind,
        live=live,
        backtest_only=backtest_only,
        vestigial=vestigial,
        mechanical=mechanical,
        exchange_order=exchange_order,
        tel_bucket=tel_bucket,
    )


# ---------------------------------------------------------------------------
# LIVE FULL (17) -- spec04.md section (1), "LIVE FULL" table
# ---------------------------------------------------------------------------
_LIVE_FULL: Dict[str, CloseType] = {
    ct.name: ct
    for ct in [
        _ct("SL", CloseKind.FULL, "GOD_BLOCK_PM_INTERNAL", "SL_HIT", mechanical=True),
        _ct("TRAILING_STOP", CloseKind.FULL, "GOD_BLOCK_PM_INTERNAL", "SL_HIT", mechanical=True),
        _ct("TP2", CloseKind.FULL, "GOD_BLOCK_PM_INTERNAL", "TP_HIT", mechanical=True),
        _ct("TP1_FULL", CloseKind.FULL, "GOD_BLOCK_PM_INTERNAL", "TP_HIT", mechanical=True),
        # HOLD_LIMIT: today a ghost close on live -- owner-gated no_exchange
        # flag (wiring.py:1125). Real exchange order requires owner sign-off
        # (Phase D, caller-migration site #13).
        _ct("HOLD_LIMIT", CloseKind.FULL, "NONE_OWNER_GATED", "TRADE_CLOSED"),
        _ct("LIQUIDATION_AVOID", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("LIQUIDATION_PROXIMITY", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("FUNDING_AVOIDANCE", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("ROTATE_PROFIT", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("ROTATE_LOSS_AVOIDANCE", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("MFE_TAKE_PROFIT", CloseKind.FULL, "HELPER", "TP_HIT"),
        _ct("MFE_EXIT_NOW", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("LLM_EXIT_AGENT", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("LLM_EXIT_ENGINE", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        # Phase 0.4-A2: was DEAD (NameError at llm_integration.py:1227,
        # fixed this phase). Not yet routed through the helper (Phase D
        # site #12) -- still calls PositionManager.force_close() directly.
        _ct("LLM_EXIT_HIGH", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        _ct("LLM_EXIT_CRITICAL", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
        # TELEGRAM_CLOSE: today zero exchange order + zero booking
        # (telegram_bot.py:508/523). Helper must be thread-safe (Telegram
        # poll thread).
        _ct("TELEGRAM_CLOSE", CloseKind.FULL, "HELPER", "TRADE_CLOSED"),
    ]
}
assert len(_LIVE_FULL) == 17, f"expected 17 LIVE FULL close types, got {len(_LIVE_FULL)}"

# ---------------------------------------------------------------------------
# LIVE PARTIAL (3) -- never enter _FULL_CLOSE bookkeeping;
# is_position_close=False on the TradeEvent (position_manager.py TradeEvent).
# ---------------------------------------------------------------------------
_LIVE_PARTIAL: Dict[str, CloseType] = {
    ct.name: ct
    for ct in [
        _ct("TP1", CloseKind.PARTIAL, "GOD_BLOCK_PM_INTERNAL", "TP_HIT", mechanical=True),
        _ct("LLM_EXIT_PARTIAL", CloseKind.PARTIAL, "HELPER", "TRADE_CLOSED"),
        _ct("EXIT_ENGINE_PARTIAL", CloseKind.PARTIAL, "HELPER", "TRADE_CLOSED"),
    ]
}
assert len(_LIVE_PARTIAL) == 3, f"expected 3 LIVE PARTIAL close types, got {len(_LIVE_PARTIAL)}"

# ---------------------------------------------------------------------------
# BACKTEST-ONLY (3) -- the backtest engine books these itself; must never
# write the live outbox.
# ---------------------------------------------------------------------------
_BACKTEST_ONLY: Dict[str, CloseType] = {
    ct.name: ct
    for ct in [
        _ct(
            "CIRCUIT_BREAKER", CloseKind.FULL, "NONE_OWNER_GATED", "TRADE_CLOSED",
            live=False, backtest_only=True,
        ),
        _ct(
            "BACKTEST_END", CloseKind.FULL, "NONE_OWNER_GATED", "TRADE_CLOSED",
            live=False, backtest_only=True,
        ),
        _ct(
            "LLM_EXIT", CloseKind.FULL, "NONE_OWNER_GATED", "TRADE_CLOSED",
            live=False, backtest_only=True,
        ),
    ]
}
assert len(_BACKTEST_ONLY) == 3, f"expected 3 BACKTEST-ONLY close types, got {len(_BACKTEST_ONLY)}"

# ---------------------------------------------------------------------------
# VESTIGIAL (4) -- no producers today (EARLY_EXIT, TIME_STOP) or default-arg
# only (EMERGENCY is force_close()'s default reason, PARTIAL_CLOSE is
# partial_close()'s default action) -- position_manager.py:2130/2139. Kept
# registered (not deleted) so existing hand-lists can be retired against
# this map without losing coverage; do NOT add new producers for these.
# ---------------------------------------------------------------------------
_VESTIGIAL: Dict[str, CloseType] = {
    ct.name: ct
    for ct in [
        _ct(
            "EARLY_EXIT", CloseKind.FULL, "GOD_BLOCK_PM_INTERNAL", "TRADE_CLOSED",
            vestigial=True,
        ),
        _ct(
            "TIME_STOP", CloseKind.FULL, "GOD_BLOCK_PM_INTERNAL", "TRADE_CLOSED",
            vestigial=True,
        ),
        _ct(
            "EMERGENCY", CloseKind.FULL, "HELPER", "TRADE_CLOSED",
            vestigial=True,
        ),
        _ct(
            "PARTIAL_CLOSE", CloseKind.PARTIAL, "HELPER", "TRADE_CLOSED",
            vestigial=True,
        ),
    ]
}
assert len(_VESTIGIAL) == 4, f"expected 4 VESTIGIAL close types, got {len(_VESTIGIAL)}"


CLOSE_TYPES: Dict[str, CloseType] = {
    **_LIVE_FULL,
    **_LIVE_PARTIAL,
    **_BACKTEST_ONLY,
    **_VESTIGIAL,
}
assert len(CLOSE_TYPES) == 27, f"expected 27 total close types, got {len(CLOSE_TYPES)}"


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def get(name: str) -> Optional[CloseType]:
    """Look up a close type by name. Returns None if unregistered -- callers
    must NOT treat that as "not a close"; see module docstring."""
    return CLOSE_TYPES.get(name)


def is_full(name: str) -> bool:
    """True if `name` is a registered FULL close type."""
    ct = CLOSE_TYPES.get(name)
    return ct is not None and ct.kind == CloseKind.FULL


def is_partial(name: str) -> bool:
    """True if `name` is a registered PARTIAL close type."""
    ct = CLOSE_TYPES.get(name)
    return ct is not None and ct.kind == CloseKind.PARTIAL


def mechanical() -> FrozenSet[str]:
    """The set of PM-internal close types the god-block treats specially:
    SL / TRAILING_STOP / TP2 / TP1_FULL / TP1 (mechanical SL/TP/TRAILING
    events, PM-internal, no helper routing). Re-derives what
    llm/regime_priors.py:50 previously hand-maintained as a static subset."""
    return frozenset(name for name, ct in CLOSE_TYPES.items() if ct.mechanical)


def live_types() -> FrozenSet[str]:
    """The set of registered close type names actually reachable in live
    (non-backtest, non-vestigial) trading today."""
    return frozenset(
        name for name, ct in CLOSE_TYPES.items()
        if ct.live and not ct.backtest_only and not ct.vestigial
    )


def all_names() -> FrozenSet[str]:
    """Every registered close type name (all 27)."""
    return frozenset(CLOSE_TYPES.keys())
