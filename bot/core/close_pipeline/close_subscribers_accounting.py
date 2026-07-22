"""ACCOUNTING-TIER (T0 + T1) close_bus subscribers (Phase 0.4-B, part 2).

CORRECTNESS-CRITICAL: these six subscribers move money and write the
canonical ledger. This is a faithful RE-EXPRESSION of six god-block bodies
in ``multi_strategy_main.py``'s ``_process_symbol`` close-handling block
(~lines 3744-4887), not a blind copy -- every value read here comes off the
frozen ``TradeClosed`` event (``ev``) or the injected ``CloseCtx`` (``ctx``),
NEVER from ``pos_mgr.positions``, a live ``pos`` refetch, or a
``risk_mgr.equity`` READ used to derive a value. See the grep/AST guard in
``bot/tests/test_close_subscribers_accounting.py`` for the mechanically
enforced version of that invariant.

NOT YET WIRED: nothing calls ``register_accounting`` from any live code
path. The god-block remains the sole authoritative close path until Phase
D/E (see spec04.md section (3)). This file is built + unit-tested in
isolation (Phase B).

THE SIX SUBSCRIBERS (tier, god-block source range):
  T0-a equity            on_close_equity            multi_strategy_main.py:3797-3805
  T0-b circuit_breaker   on_close_circuit_breaker    execution/risk.py:794-802 (fused
                         into RiskManager.update_equity -- see that function's docstring
                         below for why this subscriber does not itself mutate anything)
  T0-c log_trade         on_close_log_trade          multi_strategy_main.py:3807-3819
  T1-a ledger            on_close_ledger             multi_strategy_main.py:4113-4195
  T1-b trades_csv        on_close_trades_csv         multi_strategy_main.py:4714-4764
  T1-c trade_logger      on_close_trade_logger       multi_strategy_main.py:3953-3956

WHY PER-LEG ``ev.pnl``, NOT ``ev.total_pnl``, FOR T0 (equity/CB/log_trade):
  The god-block's T0 block runs for EVERY event in the per-symbol close loop
  (partial TP1 legs AND the terminal close), unconditionally -- see
  multi_strategy_main.py:3765 (`for event in events:`) vs. the `_FULL_CLOSE`
  gate that only appears later, at :3844, guarding T1-a/T1-b. Equity is a
  running accumulator: booking each leg's OWN incremental
  ``event.pnl - event.fee (- funding, if enabled)`` delta and letting them
  sum naturally across a position's life is correct (TP1 leg's delta once,
  the terminal leg's delta once, total adds up exactly). ``ev.total_pnl`` on
  the other hand is the POSITION's CUMULATIVE realized pnl at the moment
  each event was built (``pos.realized_pnl``, which already INCLUDES any
  prior TP1 leg's contribution -- see position_manager.py's
  PNL_SEMANTICS_FIX comments around :1893-1904). Booking ``ev.total_pnl`` on
  every event would DOUBLE-COUNT the TP1 leg's contribution at the terminal
  event -- this is the EXACT incident class trade_closed.py's module
  docstring warns about ("summing event.pnl across a TP1 leg + the terminal
  close event used to double count the TP1 leg's contribution"), just
  mirrored onto ``total_pnl`` instead of ``pnl``. So: T0 (equity/CB/
  log_trade) intentionally uses ``ev.pnl``/``ev.fee`` (per-leg, additive);
  T1 (ledger/trades_csv/trade_logger) intentionally uses ``ev.total_pnl``
  (the position's one authoritative cumulative total, and only fires on
  TERMINAL events via the ``kind=(CloseKind.FULL,)`` subscribe filter, so
  there is no double-counting risk there either). See the grep/AST guard
  test for the precise per-function allowlist this design produces.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict

from core.close_pipeline.close_bus import CloseBus, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import TradeClosed
from core.close_types import CloseKind

logger = logging.getLogger("bot.core.close_pipeline.close_subscribers_accounting")


# ---------------------------------------------------------------------------
# Lazy default resolvers -- importing this module must never eagerly import
# data.db / data.learning / data.trade_log (keeps this leaf-ish and avoids
# dragging in sqlite/CSV machinery just to unit-test with a mock ctx).
# ---------------------------------------------------------------------------
def _default_log_trade(**kwargs: Any) -> None:
    from data.db import log_trade as _fn
    _fn(**kwargs)


def _default_record_trade_outcome(**kwargs: Any) -> None:
    from data.learning import record_trade_outcome as _fn
    _fn(**kwargs)


def _default_log_closed_trade(**kwargs: Any) -> None:
    from data.trade_log import log_closed_trade as _fn
    _fn(**kwargs)


def _default_journal_booked(*args: Any, **kwargs: Any) -> None:
    from core.position_journal import journal_booked as _fn
    _fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# T0-a -- equity
# god-block source: multi_strategy_main.py:3797-3805
#   _eq_funding = float(event.metadata.get("funding_costs", 0) or 0) if
#       EQUITY_DEDUCT_FUNDING else 0.0
#   self.risk_mgr.update_equity(event.pnl - event.fee - _eq_funding)
# ---------------------------------------------------------------------------
def on_close_equity(ev: TradeClosed, ctx: CloseCtx) -> None:
    """Book this event's PER-LEG net pnl into equity. See module docstring
    "WHY PER-LEG ev.pnl, NOT ev.total_pnl" for why this is ``ev.pnl``, not
    ``ev.total_pnl``. ``ctx.risk_mgr.update_equity`` also performs the
    circuit-breaker update as an inseparable side effect today -- see
    ``on_close_circuit_breaker`` below.
    """
    import os

    _deduct_funding = os.getenv("EQUITY_DEDUCT_FUNDING", "false").lower() in ("1", "true", "yes")
    funding = (ev.funding_costs or 0.0) if _deduct_funding else 0.0
    pnl_delta = (ev.pnl or 0.0) - (ev.fee or 0.0) - funding
    ctx.risk_mgr.update_equity(pnl_delta)


# ---------------------------------------------------------------------------
# T0-b -- circuit breaker
# god-block source: no separate call site -- fused into
# execution/risk.py RiskManager.update_equity():794-802, which T0-a already
# invoked (`self.circuit_breaker.record_trade(pnl, self.equity, sim_time=...)`
# runs INSIDE update_equity, atomically with the equity mutation).
# ---------------------------------------------------------------------------
def on_close_circuit_breaker(ev: TradeClosed, ctx: CloseCtx) -> None:
    """OBSERVE-ONLY today: ``RiskManager.update_equity`` (called by
    ``on_close_equity`` immediately before this subscriber, per the T0
    tier's mandatory sequential ordering: equity -> circuit-breaker ->
    log_trade) ALREADY calls ``self.circuit_breaker.record_trade(...)``
    internally as part of one atomic operation -- there is no separate
    god-block call site to extract for "the CB update" (see
    execution/risk.py:794-815).

    Re-invoking ``circuit_breaker.record_trade(...)`` here would
    DOUBLE-COUNT this close for ``consecutive_losses`` / ``daily_pnl``
    purposes -- an exactly-once accounting bug. This subscriber therefore
    exists purely to satisfy the T0 tier's documented three-stage contract
    (see close_bus.py's module docstring) and to log the resulting breaker
    state for visibility; it performs NO mutation. If ``RiskManager`` is
    ever decoupled into equity-only + circuit-breaker-only primitives
    (a Phase D/E candidate), this becomes the real mutating call and this
    docstring should be updated accordingly.
    """
    cb = getattr(ctx.risk_mgr, "circuit_breaker", None)
    if cb is None:
        return
    logger.debug(
        "close_subscribers_accounting.on_close_circuit_breaker: "
        "position_id=%s close_type=%s total_pnl=%.2f consecutive_losses=%s tripped=%s "
        "(CB mutation already applied by on_close_equity's update_equity call)",
        ev.position_id, ev.close_type, ev.total_pnl or 0.0,
        getattr(cb, "consecutive_losses", "?"), getattr(cb, "tripped", "?"),
    )


# ---------------------------------------------------------------------------
# T0-c -- log_trade
# god-block source: multi_strategy_main.py:3807-3819
# ---------------------------------------------------------------------------
def _reconstruct_metadata(ev: TradeClosed) -> Dict[str, Any]:
    """Best-effort reconstruction of a metadata dict for ``log_trade``'s
    sqlite ``trades.metadata`` debug column.

    FIELD-GAP: NOT byte-identical to the original ``TradeEvent.metadata``
    dict -- ``TradeClosed`` deliberately flattens metadata into typed
    fields instead of carrying the raw bag forward (see trade_closed.py's
    module docstring). This reassembles the fields ``TradeClosed`` DOES
    carry so the sqlite debug column isn't simply NULL; any
    ``TradeEvent.metadata`` key with no ``TradeClosed`` field equivalent
    (e.g. ``peak_price``) is absent here. This column is a debugging aid,
    not consumed by any active learning loop found during extraction.
    """
    return {
        "total_pnl": ev.total_pnl,
        "total_fees": ev.fees_total,
        "funding_costs": ev.funding_costs,
        "hold_time_s": ev.hold_time_s,
        "outcome": ev.outcome,
        "state_path": ev.state_path,
        "entry_reasons": ev.entry_reasons,
        "entry_type": ev.entry_type,
        "primary_driver": ev.primary_driver,
        "regime": ev.regime,
        "trade_profile": ev.trade_profile,
        "entry": ev.entry,
        "sl": ev.original_sl,
        "tp1": ev.tp1,
        "tp2": ev.tp2,
        "confidence": ev.confidence,
        "mfe_pct": ev.mfe_pct,
        "mae_pct": ev.mae_pct,
        "highest_price": ev.highest_price,
        "lowest_price": ev.lowest_price,
        "position_id": ev.position_id,
        "leg_kind": ev.leg_kind.value if hasattr(ev.leg_kind, "value") else ev.leg_kind,
    }


def on_close_log_trade(ev: TradeClosed, ctx: CloseCtx) -> None:
    """Log this event to the sqlite ``trades`` table. Per-leg ``ev.pnl``/
    ``ev.fee`` (see module docstring), matching the god-block's
    ``log_trade(..., pnl=event.pnl, fee=event.fee, ...)`` call exactly.
    """
    fn = ctx.log_trade_fn or _default_log_trade
    fn(
        symbol=ev.symbol,
        action=ev.close_type,
        side=ev.side,
        price=ev.price,
        qty=ev.qty,
        pnl=ev.pnl,
        fee=ev.fee,
        leverage=ev.leverage,
        strategy=ev.strategy,
        metadata=_reconstruct_metadata(ev),
    )


# ---------------------------------------------------------------------------
# T1-a -- ledger
# god-block source: multi_strategy_main.py:4113-4195 (gated by the
# `if event.action in _FULL_CLOSE:` block starting :3844 -- reproduced here
# via the CloseBus `kind=(CloseKind.FULL,)` subscribe filter instead of a
# hand-maintained action-string allowlist, per spec04.md's stated intent
# that LegKind.TERMINAL/CloseKind.FULL replace such lists).
# ---------------------------------------------------------------------------
def _contributing_factors(ev: TradeClosed) -> list:
    """Reproduces the `_factors` fallback cascade at
    multi_strategy_main.py:4037-4055 (KELLY_IC_FACTOR_FIX), purely off
    ``ev.entry_reasons`` / ``ev.strategy`` -- no live position read needed.
    """
    import os

    er = ev.entry_reasons or {}
    factors = list(er.get("strategies") or [])
    if not factors and os.getenv("KELLY_IC_FACTOR_FIX", "true").lower() in ("1", "true", "yes"):
        factors = [str(s) for s in (er.get("strategies_agree") or []) if s]
        if not factors:
            pd = er.get("primary_driver") or er.get("setup_key")
            if pd:
                factors = [str(pd)]
    if not factors and ev.strategy:
        factors = [ev.strategy]
    if not factors:
        factors = ["llm_first"]
    return factors


def on_close_ledger(ev: TradeClosed, ctx: CloseCtx) -> None:
    """Write one row to trade_ledger.csv. Authoritative pnl is
    ``ev.total_pnl`` throughout (net_pnl, gross_pnl, running_equity basis,
    win/loss classification, realized_rr) -- never ``ev.pnl`` (see module
    docstring). ``position_id=ev.position_id`` per the 0.3b POSITION_IDENTITY
    column (spec04.md task instruction).

    FIELD-GAPs (documented, not silently defaulted):
      - regime_4h: god-block reads a live ``self._tick_regime_cache`` --
        no per-symbol multi-timeframe regime cache is carried on
        TradeClosed. Always "".
      - regime_1h: god-block falls back to the SAME live tick-cache when
        ``_rg_fb`` (pos.trade_profile.regime) is empty. We use
        ``ev.regime or "unknown"`` -- may occasionally read "unknown"
        where the god-block's live cache would have found a fresher value.
      - kelly_weight_applied: ``ctx.kelly_engine`` is a T2 (derived reader)
        collaborator, out of scope for this accounting-tier extraction --
        see close_context.py's field note. "" when ``ctx.kelly_engine`` is
        None (the accounting-tier default).
      - compound_size_multiplier: sourced from ``ev.compound_mult``, which
        is None until an emitter populates it (documented gap already on
        TradeClosed itself -- see trade_closed.py module docstring).
    """
    if ctx.trade_ledger is None:
        return

    entry = ev.entry or 0.0
    original_sl = ev.original_sl
    stop_width = abs(entry - original_sl) if original_sl else 0.0
    rr_qty = ev.original_qty or ev.qty or 0.0
    rr_risk = stop_width * rr_qty * (ev.leverage or 1)
    total_pnl = ev.total_pnl
    realized_rr = round(total_pnl / rr_risk, 3) if rr_risk > 0 else 0

    fees_total = ev.fees_total or 0.0
    funding_costs = ev.funding_costs or 0.0
    gross_pnl = round(total_pnl + fees_total + funding_costs, 2)

    entry_reasons = ev.entry_reasons or {}

    kelly_weight_applied = ""
    if ctx.kelly_engine is not None and ev.strategy:
        try:
            kelly_weight_applied = str(ctx.kelly_engine.compute_kelly_weight(ev.strategy))
        except Exception:
            kelly_weight_applied = ""

    # running_equity: sourced from the FROZEN ev.equity_after snapshot, NOT
    # a live ctx.risk_mgr.equity read (see close_context.py's field note
    # and the grep guard test).
    running_equity = "" if ev.equity_after is None else str(round(ev.equity_after, 2))
    session_dd_pct = "" if ev.session_dd_pct is None else str(ev.session_dd_pct)

    row = {
        "symbol": ev.symbol,
        "side": ev.side,
        "regime_1h": ev.regime or "unknown",
        "regime_4h": "",  # FIELD-GAP: live tick_regime_cache, not on TradeClosed
        "agreement_level": str(entry_reasons.get("num_agree", 1)),
        "contributing_factors": ",".join(_contributing_factors(ev)),
        "confidence_score": str(ev.confidence),
        "kelly_weight_applied": kelly_weight_applied,  # FIELD-GAP: T2 collaborator
        "compound_size_multiplier": "" if ev.compound_mult is None else str(ev.compound_mult),
        "leverage": str(ev.leverage),
        "hold_hours": f"{(ev.hold_time_s or 0.0) / 3600:.2f}",
        "exit_type": ev.close_type,
        "entry_price": str(ev.entry),
        "snapshot_entry": str(entry_reasons.get("snapshot_entry", "")),
        "exit_price": str(ev.price),
        "gross_pnl": str(gross_pnl),
        "fees": str(round(fees_total, 2)),
        "funding": str(round(-funding_costs, 4)),
        "net_pnl": str(round(total_pnl, 2)),
        "running_equity": running_equity,
        "session_dd_pct": session_dd_pct,
        "predicted_ev": str(entry_reasons.get("ev_per_dollar", "")),
        "realized_rr": str(realized_rr),
        "win": "1" if total_pnl > 0 else "0",
        "position_id": ev.position_id,
    }

    ctx.trade_ledger.record_trade(row, source=ctx.source, position_id=ev.position_id)

    # Write-ahead journal (Phase 0.3b): mark this position's close as fully
    # booked ONLY after the ledger write above succeeded. Safety net, not a
    # gate -- swallow failures exactly like the god-block does
    # (multi_strategy_main.py:4189-4193).
    # Routed through ctx.journal_booked_fn (None -> real journal_booked,
    # lazily imported) -- NEVER a bare direct import here. A direct import
    # is invisible to shadow/test harnesses that only inject via CloseCtx
    # fields, and the real journal_booked() is __file__-anchored to the
    # REAL data/position_journal.jsonl regardless of any shadow data_dir
    # (see close_context.py's journal_booked_fn field note and
    # shadow_close_wiring.py's module docstring for the full hazard).
    try:
        journal_booked_fn = ctx.journal_booked_fn or _default_journal_booked
        journal_booked_fn(ev.position_id, symbol=ev.symbol)
    except Exception as _jb_err:
        logger.debug(f"[POSITION-JOURNAL] journal_booked failed (non-fatal): {_jb_err}")


# ---------------------------------------------------------------------------
# T1-b -- trades_csv (record_trade_outcome + log_closed_trade)
# god-block source: multi_strategy_main.py:4714-4764 (gated by
# `_is_terminal_close` at :4676-4679 -- reproduced via the CloseBus
# `kind=(CloseKind.FULL,)` filter, same rationale as T1-a above; note the
# god-block's own gate has a live-position fallback clause
# (`self.pos_mgr.positions.get(symbol)`) that this extraction deliberately
# does NOT reproduce -- LegKind.TERMINAL already covers every close reason
# without a hand-maintained list or a live refetch).
# ---------------------------------------------------------------------------
def on_close_trades_csv(ev: TradeClosed, ctx: CloseCtx) -> None:
    """Writes both the trade_outcomes.csv row (``record_trade_outcome``,
    pollution-gated by ``core.provenance`` per 0.2) and the trades.csv row
    (``log_closed_trade``, not pollution-gated today). Authoritative pnl is
    ``ev.total_pnl`` throughout.

    tp1_hit / sl_after_tp1: derived from ``ev.state_path`` via the SAME
    substring convention ``Position.filled_tp1`` and ``log_closed_trade``
    itself already use (``"TP1_HIT" in state_path``) -- see
    position_manager.py:170-171. No FIELD-GAP: this is a legitimate
    ev-sourced derivation, not a live refetch of ``pos.filled_tp1``.
    """
    state_path = ev.state_path or ""
    tp1_hit = "TP1_HIT" in state_path
    sl_after_tp1 = (ev.close_type == "SL") and tp1_hit

    entry_reasons = ev.entry_reasons or {}
    volatility_band = (ev.trade_profile or {}).get("volatility_band", "")
    total_pnl = ev.total_pnl

    outcome_fn = ctx.record_trade_outcome_fn or _default_record_trade_outcome
    outcome_fn(
        symbol=ev.symbol,
        side=ev.side,
        outcome=ev.outcome,
        pnl=total_pnl,
        entry=ev.entry,
        sl=ev.original_sl,
        tp1=ev.tp1,
        tp2=ev.tp2,
        tp1_hit=tp1_hit,
        sl_after_tp1=sl_after_tp1,
        state_path=state_path,
        leverage=ev.leverage,
        confidence=ev.confidence,
        strategy=ev.strategy,
        entry_reasons=entry_reasons,
        entry_type=ev.entry_type,
        primary_driver=ev.primary_driver,
        regime=ev.regime,
        volatility_band=volatility_band,
        source=ctx.source,
    )

    trades_fn = ctx.log_closed_trade_fn or _default_log_closed_trade
    trades_fn(
        symbol=ev.symbol,
        side=ev.side,
        entry=ev.entry,
        exit_price=ev.price,
        action=ev.close_type,
        pnl=total_pnl,
        fees=ev.fees_total or 0.0,
        state_path=state_path,
        outcome=ev.outcome,
        leverage=ev.leverage,
        confidence=ev.confidence,
        strategy=ev.strategy,
        ml_samples_at_entry=0,
        ml_samples_at_exit=0,
        entry_reasons=entry_reasons,
        entry_type=ev.entry_type,
        primary_driver=ev.primary_driver,
        regime=ev.regime,
        volatility_band=volatility_band,
    )


# ---------------------------------------------------------------------------
# T1-c -- trade_logger
# god-block source: multi_strategy_main.py:3953-3956
# ---------------------------------------------------------------------------
def on_close_trade_logger(ev: TradeClosed, ctx: CloseCtx) -> None:
    """Mirrors ``self.trade_logger.log_trade_event(event, hold_time_s=...)``.
    ``TradeLogger.log_trade_event`` is duck-typed against a
    ``TradeEvent``-shaped object (reads ``.metadata``, ``.action``,
    ``.symbol``, ``.side``, ``.price``, ``.qty``, ``.pnl``, ``.fee``,
    ``.leverage``) -- ``TradeClosed`` uses different attribute names
    (``close_type`` not ``action``, no ``.metadata`` dict) so we pass a
    lightweight shim built from ``ev`` fields, reusing the existing
    (already-tested) ``TradeLogger``/``TradeLog``/CSV-append implementation
    unchanged rather than re-deriving its CSV-writing logic here.

    FIELD-GAP: raw dollar ``mfe``/``mae`` are NOT on ``TradeClosed`` (only
    ``mfe_pct``/``mae_pct`` are carried -- see trade_closed.py). Omitted
    from the shim's metadata so ``log_trade_event``'s own
    ``_meta.get("mfe", 0.0)`` / ``.get("mae", 0.0)`` defaults apply, exactly
    as they would for any TradeEvent missing those keys.
    """
    if ctx.trade_logger is None:
        return

    shim = SimpleNamespace(
        symbol=ev.symbol,
        action=ev.close_type,
        side=ev.side,
        price=ev.price,
        qty=ev.qty,
        pnl=ev.pnl,
        fee=ev.fee,
        leverage=ev.leverage,
        metadata={
            "mfe_pct": ev.mfe_pct,
            "mae_pct": ev.mae_pct,
        },
    )
    hold_time_s = int(ev.hold_time_s or 0)
    ctx.trade_logger.log_trade_event(shim, hold_time_s=hold_time_s)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_accounting(bus: CloseBus, ctx: CloseCtx) -> None:
    """Subscribe all six accounting-tier subscribers in the tier + order the
    spec mandates: T0 equity -> circuit_breaker -> log_trade (sequential,
    mandatory, applies to BOTH partial and full closes -- matches the
    god-block running this block unconditionally for every event); T1
    ledger -> trades_csv -> trade_logger (persistence; ledger and
    trades_csv are FULL-close only, matching the god-block's `_FULL_CLOSE`
    gate; trade_logger runs on both, matching its unconditional god-block
    call site).
    """
    bus.subscribe(
        "equity", lambda ev: on_close_equity(ev, ctx),
        tier=Tier.T0_CORE_ACCOUNTING,
    )
    bus.subscribe(
        "circuit_breaker", lambda ev: on_close_circuit_breaker(ev, ctx),
        tier=Tier.T0_CORE_ACCOUNTING,
    )
    bus.subscribe(
        "log_trade", lambda ev: on_close_log_trade(ev, ctx),
        tier=Tier.T0_CORE_ACCOUNTING,
    )
    bus.subscribe(
        "ledger", lambda ev: on_close_ledger(ev, ctx),
        tier=Tier.T1_PERSISTENCE, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "trades_csv", lambda ev: on_close_trades_csv(ev, ctx),
        tier=Tier.T1_PERSISTENCE, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "trade_logger", lambda ev: on_close_trade_logger(ev, ctx),
        tier=Tier.T1_PERSISTENCE,
    )
