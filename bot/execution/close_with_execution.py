"""``close_with_execution`` -- the ONE sanctioned close entry point (Phase
0.4-B3, spec04.md section (2) ``execution/close_with_execution.py``).

WHAT THIS FIXES: four live money-losing bug classes, all rooted in the same
mistake -- a close site doing PositionManager bookkeeping (``force_close`` /
``partial_close``) BEFORE, or without ever, confirming the exchange order
actually filled:

  1. **MFE book-then-maybe-fill** (multi_strategy_main.py:3714-3719 /
     :3722-3727): ``force_close()`` runs FIRST, the exchange order is
     submitted SECOND with its fill result never even inspected, and
     ``_exchange_submitted`` is stamped ``True`` unconditionally. A rejected
     order still gets booked as a real, exchange-confirmed close.
  2. **qty=0** (same site): the exchange order's qty comes from
     ``_mfe_pos.qty`` -- the SAME ``Position`` object ``force_close()`` just
     mutated to ``pos.qty = 0`` (position_manager.py:1905, inside
     ``_close_position``). By the time the order is submitted, the qty read
     off the live position is already zeroed.
  3. **failed-close continue-drop** (multi_strategy_main.py:3789-3795): the
     one call site that DOES check the fill result only reaches that check
     AFTER the mechanical PM-internal event (SL/TP/TRAILING, produced by
     ``pos_mgr.update_price()``) already transitioned the position to
     CLOSED in memory. On a failed order it ``continue``s (skips equity/
     log_trade for that iteration) but the position is already booked
     CLOSED internally while still open on the exchange -- a state fork
     that only reconciliation can fix, silently, later.
  4. **Telegram / LLM-exit no-order** (alerts/telegram_bot.py:508/523,
     core/llm_integration.py:1229): submit NO exchange order and do NO
     accounting at all -- a `/close` command or an LLM_EXIT_HIGH/CRITICAL
     verdict is pure theater today.

THE FIX, as one reusable helper: ORDER FIRST, check the fill, and only on a
confirmed fill do any PositionManager bookkeeping. Modeled on the ALREADY-
correct pattern used by the LIQUIDATION_AVOID (multi_strategy_main.py:
4969-4989), LIQUIDATION_PROXIMITY (:3628-3640), and FUNDING_AVOIDANCE
(:3677-3689) call sites: submit -> check ``getattr(result, "filled", False)``
-> only then call ``force_close``/``partial_close`` -> stamp
``_exchange_submitted`` -> hand the event off. This module generalizes that
exact shape into one injectable, unit-testable function so the remaining 10
sites (Phase D, NOT this phase) can all route through it instead of
hand-rolling the same order-first dance (or skipping it entirely).

QTY CAPTURE: ``pre_close_qty`` is read off ``pos_mgr.positions[symbol].qty``
(or the caller-supplied ``qty``) BEFORE either the exchange order or the PM
booking call runs -- so it can never observe a qty that a same-tick
``force_close``/``partial_close`` call already zeroed out (bug class #2).

ABORT CONTRACT (bug classes #1 and #3): if the exchange order is submitted
and does NOT fill, this function returns ``None`` having called NEITHER
``force_close`` NOR ``partial_close`` NOR ``close_bus.publish`` -- the
position is left exactly as it was (still OPEN, still on the exchange),
nothing is booked, nothing is published, and a CRITICAL log line is the only
side effect (matching the god-block's own "reconciliation will handle"
convention).

GHOST-CLOSE (``no_exchange=True``): today's HOLD_LIMIT semantics
(wiring.py:1125, owner-gated -- exchange submission for HOLD_LIMIT is
deliberately disabled pending explicit sign-off) are reproduced verbatim:
book the PM close WITHOUT ever calling the exchange, stamp
``exchange_submitted=False``, and log a GHOST-CLOSE warning so this
deliberately-desynced state is loud in the logs rather than silent.

COLLABORATORS: ``pos_mgr`` (execution/position_manager.py's
``PositionManager`` -- needs ``.positions`` dict + ``.force_close()`` /
``.partial_close()``), ``order_executor`` (execution/order_executor.py's
``OrderExecutor`` -- needs ``.close_position()`` returning something with a
``.filled`` bool and an ``.error`` str, matching ``OrderResult``),
``bus`` (``core.close_pipeline.close_bus.CloseBus``, or ``None`` -- the
documented backtest/no-op contract, see ``close_bus.maybe_publish``), and
``ctx`` (``core.close_pipeline.close_context.CloseCtx``, optional). All four
are explicit keyword-only parameters (not read off ``self``) precisely so
this function is trivially callable with plain mocks in tests -- no partial
bot bootstrap required. ``ctx`` is accepted for call-site API stability with
the Phase D/E accounting-tier wiring (close_subscribers.py's six subscribers
are the ones that actually consume a ``CloseCtx``) but is NOT read by this
function today -- see the module docstring of close_context.py for what it
threads through once that wiring lands. Passing it now costs callers
nothing and means a future flip never needs a second signature change.

SNAPSHOT KWARGS: the five field-gaps ``TradeClosed``/``from_trade_event``
cannot derive from a bare ``TradeEvent`` + ``Position`` alone --
``compound_mult``, ``close_volatility``, ``candidate_ref``, ``equity_after``,
``session_dd_pct`` (see trade_closed.py's module docstring) -- are accepted
here via ``**snapshot_kwargs`` and passed straight through to
``TradeClosed.from_trade_event(...)``. A caller that has one of these values
on hand (e.g. rotation_manager has a ``candidate_ref``, the risk manager can
report ``equity_after``) passes it as a keyword; omitted ones default to
``None`` exactly as ``from_trade_event`` already documents. Passing any
other keyword raises ``TypeError`` (delegated to ``from_trade_event``'s own
explicit parameter list -- no separate allowlist to maintain here).

THREAD SAFETY: this function holds no module-level or instance-level mutable
state of its own -- it only calls into its injected collaborators and
returns. It is therefore safe to call concurrently from multiple threads
(e.g. the Telegram poll thread firing a ``TELEGRAM_CLOSE`` alongside the
main tick loop firing an ``MFE_TAKE_PROFIT``) PROVIDED the injected
``pos_mgr``/``order_executor``/``bus`` are themselves safe for concurrent
use -- a pre-existing property of those collaborators this helper neither
improves nor worsens. ``CloseBus.publish`` isolates each subscriber in its
own try/except and consults a lock-protected ``AppliedStore`` for its
exactly-once seam (see close_bus.py); this helper adds no additional shared
mutable state on top of that.

NOT YET WIRED: nothing calls this function from any live code path yet.
Built + unit-tested in isolation (Phase B) -- the god-block in
multi_strategy_main.py remains the authoritative live close path until the
13 caller sites are migrated one at a time (Phase D, spec04.md section (5)).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from core import close_types
from core.close_pipeline.close_bus import CloseBus, maybe_publish
from core.close_pipeline.trade_closed import TradeClosed

if TYPE_CHECKING:  # pragma: no cover - import-cycle avoidance only
    from core.close_pipeline.close_context import CloseCtx

logger = logging.getLogger("bot.execution.close_with_execution")


def validate_close_type(close_type: str) -> None:
    """Raise ``ValueError`` if ``close_type`` is not a name registered in
    ``core.close_types.CLOSE_TYPES``. Called FIRST, before any exchange
    order or PositionManager call, so an unregistered/typo'd close reason
    fails loudly in paper/backtest rather than silently falling through
    ``close_taxonomy``'s permissive blocklist (see close_types.py's module
    docstring for why that registry is deliberately NOT the "is this a
    close" authority -- this function only guards THIS helper's dispatch,
    it does not replace ``close_taxonomy.is_close_action``)."""
    if close_types.get(close_type) is None:
        raise ValueError(
            f"close_with_execution: unknown close_type {close_type!r} -- not "
            f"registered in core.close_types.CLOSE_TYPES. Register it there "
            f"first (leaf module, safe to extend) rather than routing an "
            f"ad-hoc reason string through the sanctioned close entry point."
        )


def close_with_execution(
    symbol: str,
    price: float,
    close_type: str,
    *,
    qty: Optional[float] = None,
    partial: bool = False,
    partial_pct: float = 0.5,
    no_exchange: bool = False,
    pos_mgr: Any,
    order_executor: Any,
    bus: Optional[CloseBus],
    ctx: Optional["CloseCtx"] = None,
    sim: bool = False,
    **snapshot_kwargs: Any,
) -> Optional[TradeClosed]:
    """Close (fully or partially) the open position on ``symbol`` through
    the exchange, THEN book it via ``PositionManager``, THEN publish the
    resulting ``TradeClosed`` to ``bus``. See module docstring for the full
    contract and the bug classes this fixes.

    Args:
        symbol: our internal symbol name (matches ``pos_mgr.positions`` key).
        price: the price to close at (expected fill price for the exchange
            order; also the booking price passed to ``force_close``/
            ``partial_close``).
        close_type: the close reason -- must be a name registered in
            ``core.close_types.CLOSE_TYPES`` (validated first).
        qty: exact quantity to close. When omitted, the FULL pre-close
            position quantity is used (``pos_mgr.positions[symbol].qty``,
            read BEFORE any booking call -- see module docstring's qty=0
            bug-class note). For ``partial=True``, pass the exact leg qty;
            it overrides ``partial_pct`` for the booked amount, mirroring
            ``PositionManager.partial_close``'s own ``qty`` override
            semantics.
        partial: routes to ``pos_mgr.partial_close`` (leg_kind=PARTIAL)
            instead of ``pos_mgr.force_close`` (leg_kind=TERMINAL). A
            partial close never enters full-close bookkeeping.
        partial_pct: fraction of the position to close when ``partial=True``
            and ``qty`` is not supplied (or supplied only informationally --
            ``qty`` still wins for the booked amount, see above).
        no_exchange: HOLD_LIMIT's owner-gated ghost-close path -- skip the
            exchange order entirely, book anyway, stamp
            ``exchange_submitted=False``, and log a GHOST-CLOSE warning.
            Reproduces today's HOLD_LIMIT semantics (wiring.py:1125)
            verbatim; do not set this for any other close_type without
            explicit owner sign-off (spec04.md caller-migration site #13).
        pos_mgr: a ``PositionManager``-shaped collaborator (``.positions``
            dict, ``.force_close()``, ``.partial_close()``).
        order_executor: an ``OrderExecutor``-shaped collaborator
            (``.close_position()`` returning an ``OrderResult``-shaped
            object with ``.filled`` / ``.error``).
        bus: a ``CloseBus`` to publish the resulting event to, or ``None``
            (documented no-op contract -- see ``close_bus.maybe_publish``).
        ctx: optional ``CloseCtx`` -- accepted for forward API stability
            with the accounting-tier subscriber wiring; unused by this
            function today (see module docstring).
        sim: stamped onto the returned ``TradeClosed``. Real (live/paper)
            callers must never set this ``True`` -- it exists so tests can
            exercise the ``sim=True`` / no-publish path without a second
            code path. Real backtest closes are booked by the backtest
            engine directly, never through this helper.
        **snapshot_kwargs: any of ``compound_mult``, ``close_volatility``,
            ``candidate_ref``, ``equity_after``, ``session_dd_pct`` --
            forwarded verbatim to ``TradeClosed.from_trade_event``. Any
            other keyword raises ``TypeError`` there.

    Returns:
        The published ``TradeClosed`` on success, or ``None`` if the close
        was aborted (unfilled exchange order, no open position, or a PM
        booking race) -- in every ``None`` case, NOTHING was booked and
        NOTHING was published.
    """
    validate_close_type(close_type)

    pos = pos_mgr.positions.get(symbol)
    if pos is None:
        logger.error(
            "close_with_execution: no open position for %s (close_type=%s) "
            "-- nothing to close, returning None",
            symbol, close_type,
        )
        return None

    # Capture qty BEFORE either the exchange order or the PM booking call
    # runs -- this is THE fix for the MFE qty=0 bug class (module docstring
    # #2): the old code read `_mfe_pos.qty` for the exchange order AFTER
    # `force_close()` had already zeroed that same Position object's qty
    # in place (position_manager.py:1905).
    pre_close_qty = qty if (qty is not None and qty > 0) else pos.qty
    if pre_close_qty is None or pre_close_qty <= 0:
        logger.error(
            "close_with_execution: pre-close qty <= 0 for %s (close_type=%s, "
            "qty=%r, pos.qty=%r) -- refusing to close, returning None",
            symbol, close_type, qty, getattr(pos, "qty", None),
        )
        return None

    close_side = "SELL" if pos.side == "LONG" else "BUY"

    exchange_submitted = False
    if not no_exchange:
        # ORDER FIRST (module docstring bug classes #1/#3): submit the
        # exchange close order and INSPECT the fill result before doing
        # anything else. Modeled on the LIQUIDATION_AVOID /
        # LIQUIDATION_PROXIMITY / FUNDING_AVOIDANCE call sites
        # (multi_strategy_main.py:4986-4989 / :3628-3630 / :3677-3679).
        order_result = order_executor.close_position(
            symbol=symbol,
            side=close_side,
            qty=pre_close_qty,
            price=price,
            reason=close_type,
        )
        filled = bool(order_result is not None and getattr(order_result, "filled", False))
        if not filled:
            # ABORT: leave the position OPEN, book NOTHING, publish
            # NOTHING. This is the core fix -- the old MFE site booked the
            # close via force_close() regardless of what the (later,
            # unchecked) exchange order did; the old L1 dispatch loop's
            # `continue` (multi_strategy_main.py:3789-3795) only reached
            # this check AFTER the PM state had already flipped to CLOSED
            # for mechanical SL/TP/TRAILING events. Neither problem exists
            # here: force_close/partial_close have not been called yet.
            logger.critical(
                "close_with_execution: CLOSE ORDER FAILED for %s %s "
                "qty=%.8f @ %.8f -- position stays OPEN, nothing booked, "
                "nothing published. Reconciliation will handle. error=%s",
                symbol, close_type, pre_close_qty, price,
                getattr(order_result, "error", "<no order_result>"),
            )
            return None
        exchange_submitted = True
    else:
        # GHOST-CLOSE: HOLD_LIMIT's owner-gated path (wiring.py:1125) --
        # book without ever touching the exchange. Loud by design.
        logger.warning(
            "close_with_execution: GHOST-CLOSE -- no_exchange=True for %s "
            "%s qty=%.8f @ %.8f -- booking WITHOUT submitting an exchange "
            "order.",
            symbol, close_type, pre_close_qty, price,
        )

    if partial:
        event = pos_mgr.partial_close(
            symbol, partial_pct, price, action=close_type, qty=pre_close_qty,
        )
    else:
        event = pos_mgr.force_close(symbol, price, close_type)

    if event is None:
        # The exchange order (if any) already happened, but PM booking
        # came back empty (e.g. a race -- position already CLOSED by
        # something else between the .positions.get() lookup above and
        # this call). Nothing to publish; reconciliation must resolve the
        # exchange-vs-PM state divergence.
        logger.critical(
            "close_with_execution: PM booking returned None for %s %s "
            "(exchange_submitted=%s) -- nothing published. Reconciliation "
            "will handle.",
            symbol, close_type, exchange_submitted,
        )
        return None

    trade_closed = TradeClosed.from_trade_event(
        event,
        position=pos,
        sim=sim,
        exchange_submitted=exchange_submitted,
        **snapshot_kwargs,
    )

    maybe_publish(bus, trade_closed)

    return trade_closed
