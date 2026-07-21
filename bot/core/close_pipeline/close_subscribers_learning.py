"""LEARNING-TIER (T2 "derived readers") close_bus subscribers (Phase 0.4-B,
batch 1).

This is a faithful RE-EXPRESSION of nine god-block bodies in
``multi_strategy_main.py``'s ``_process_symbol`` close-handling block --
two adjacent ``if event.action in _FULL_CLOSE:`` sections around
lines 3844-4118 (see each function's docstring for its exact source range).
Every value read here comes off the frozen ``TradeClosed`` event (``ev``)
or the injected ``CloseCtx`` (``ctx``), NEVER from ``pos_mgr.positions``, a
live ``pos`` refetch, or a ``risk_mgr.equity`` READ used to derive a value.
See the grep/AST guard in ``bot/tests/test_close_subscribers_learning.py``
for the mechanically enforced version of that invariant.

NOT YET WIRED: nothing calls ``register_learning`` from any live code path.
The god-block remains the sole authoritative close path until Phase D/E.
This file is built + unit-tested in isolation (Phase B).

NO FIELD-GAPS THIS BATCH: unlike the accounting-tier extraction (which hit
a few live-cache/entry-time-cache gaps), every value the nine learning
subscribers below need is already present on ``TradeClosed`` -- notably
``ev.trade_profile`` already carries ``regime``/``entry_type`` (see
execution/trade_profile.py's ``TradeProfile.to_dict``), and
``ev.pnl_pct_of_equity`` (computed once, at emit time, from the frozen
``equity_after`` snapshot) is EXACTLY the "%-of-equity" pnl the god-block
recomputes live via a ``risk_mgr.equity`` division in two separate places
(REGIME_FB_FIX's ``_rf_pnl`` and the Kelly section's ``_pnl_pct``) -- one
frozen field cleanly replaces both live divisions.

SCOPE NOTE ON CLOSE_DEDUP_GUARD: the god-block's IC-tracker/Kelly section
(multi_strategy_main.py:4085-4098) also consults an in-memory
``self._recent_close_keys`` cache to skip a duplicate re-fire of the same
close within a 3600s window. That cache is stateful ACROSS MULTIPLE close
events, not derivable from one frozen ``TradeClosed`` -- it is deliberately
NOT reproduced here, for the same reason close_subscribers_accounting.py's
``on_close_ledger`` doesn't reproduce it either (see that module's
``TestExactlyOnceViaBus`` test docstring): CloseBus's own applied-store
dedup is scoped to the T0_CORE_ACCOUNTING tier only, so T2 subscribers
(this file) run again on a duplicate ``publish()`` today, exactly like T1
does. A future outbox-ack-based mechanism is the intended long-term
replacement for the ad hoc ``_recent_close_keys`` cache, not this file.

THE NINE SUBSCRIBERS (tier, god-block source range):
  T2-a weight_mgr        on_close_weight_mgr        multi_strategy_main.py:3854
  T2-b regime_feedback   on_close_regime_feedback    multi_strategy_main.py:3856-3882
  T2-c confidence_floor  on_close_confidence_floor   multi_strategy_main.py:3883-3891
  T2-d hold_time_rules   on_close_hold_time_rules    multi_strategy_main.py:3892-3898
  T2-e parameter_tuner   on_close_parameter_tuner    multi_strategy_main.py:3912-3917
  T2-f feedback          on_close_feedback           multi_strategy_main.py:3958-4000
  T2-g graduated_rules   on_close_graduated_rules    multi_strategy_main.py:4002-4033
  T2-h ic_tracker        on_close_ic_tracker         multi_strategy_main.py:4100-4111
  T2-i kelly             on_close_kelly              multi_strategy_main.py:4113-4118

All nine are gated by the god-block's ``_FULL_CLOSE`` action-string
allowlist (multi_strategy_main.py:3824-3837) -- reproduced here via the
CloseBus ``kind=(CloseKind.FULL,)`` subscribe filter, same rationale as
close_subscribers_accounting.py's T1 subscribers.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from core.close_pipeline.close_bus import CloseBus, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import TradeClosed
from core.close_types import CloseKind

logger = logging.getLogger("bot.core.close_pipeline.close_subscribers_learning")


# ---------------------------------------------------------------------------
# Lazy default resolvers -- importing this module must never eagerly import
# llm.graduated_rules (keeps this leaf-ish and avoids dragging in its
# process-wide singleton + file I/O just to unit-test with a mock ctx).
# ---------------------------------------------------------------------------
def _default_graduated_rules_engine() -> Any:
    from llm.graduated_rules import get_graduated_rules_engine
    return get_graduated_rules_engine()


# ---------------------------------------------------------------------------
# Shared helper -- KELLY_IC_FACTOR_FIX fallback cascade.
# god-block source: multi_strategy_main.py:4036-4055 (also independently
# reproduced in close_subscribers_accounting.py's ``_contributing_factors``
# for the T1 ledger's ``contributing_factors`` column -- duplicated rather
# than imported cross-module so each close_pipeline subscriber file stays
# independently leaf-ish; both copies derive from the same
# ``ev.entry_reasons`` / ``ev.strategy`` fields and must stay in sync if the
# god-block's cascade ever changes).
# ---------------------------------------------------------------------------
def _contributing_factors(ev: TradeClosed) -> List[str]:
    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
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


def _resolved_confidence(ev: TradeClosed) -> float:
    """Reproduces the `pos.confidence if pos.confidence else 50.0` fallback
    used by regime_feedback/confidence_floor (multi_strategy_main.py:3859,
    3863) -- ``ev.confidence`` is the entry-time confidence already resolved
    onto ``TradeClosed`` at construction (meta or position snapshot)."""
    return ev.confidence if ev.confidence else 50.0


# ---------------------------------------------------------------------------
# T2-a -- weight_mgr
# god-block source: multi_strategy_main.py:3854
#   self.weight_mgr.record_outcome(_strategy_key, total_pnl > 0, symbol=symbol)
# ---------------------------------------------------------------------------
def on_close_weight_mgr(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.weight_mgr is None:
        return
    strategy_key = ev.strategy if ev.strategy else "ensemble"
    ctx.weight_mgr.record_outcome(strategy_key, ev.total_pnl > 0, symbol=ev.symbol)


# ---------------------------------------------------------------------------
# T2-b -- regime_feedback
# god-block source: multi_strategy_main.py:3856-3882
# ---------------------------------------------------------------------------
def on_close_regime_feedback(ev: TradeClosed, ctx: CloseCtx) -> None:
    """REGIME_FB_FIX env gate (default off): when enabled, records pnl as
    %-of-equity instead of raw dollars. The god-block recomputes this live
    via ``total_pnl / self.risk_mgr.equity * 100`` (falling back to 0.0 when
    equity <= 0) -- ``ev.pnl_pct_of_equity`` is the SAME computation, done
    once at emit time from the frozen ``equity_after`` snapshot, so we reuse
    it directly rather than re-deriving it from a live equity read (which
    the grep guard forbids). Falls back to 0.0 when the field is unset,
    matching the god-block's own degenerate-equity fallback.
    """
    if ctx.regime_feedback is None:
        return
    regime = ev.regime or "unknown"
    confidence = _resolved_confidence(ev)
    hold_hours = (ev.hold_time_s or 0.0) / 3600.0

    if os.getenv("REGIME_FB_FIX", "false").lower() in ("1", "true", "yes"):
        pnl = ev.pnl_pct_of_equity if ev.pnl_pct_of_equity is not None else 0.0
        metadata: Dict[str, Any] = {"symbol": ev.symbol, "action": ev.close_type, "pnl_usd": ev.total_pnl}
    else:
        pnl = ev.total_pnl
        metadata = {"symbol": ev.symbol, "action": ev.close_type}

    ctx.regime_feedback.record_trade(
        regime=regime,
        pnl=pnl,
        confidence=confidence,
        strategy=ev.strategy,
        hold_hours=hold_hours,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# T2-c -- confidence_floor
# god-block source: multi_strategy_main.py:3883-3891
# ---------------------------------------------------------------------------
def on_close_confidence_floor(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.confidence_floor is None:
        return
    ctx.confidence_floor.record_outcome(
        confidence=_resolved_confidence(ev),
        win=ev.total_pnl > 0,
        pnl=ev.total_pnl,
        strategy=ev.strategy,
        symbol=ev.symbol,
        regime=ev.regime or "unknown",
    )


# ---------------------------------------------------------------------------
# T2-d -- hold_time_rules
# god-block source: multi_strategy_main.py:3892-3898
# ---------------------------------------------------------------------------
def on_close_hold_time_rules(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.hold_time_rules is None:
        return
    hold_hours = (ev.hold_time_s or 0.0) / 3600.0
    ctx.hold_time_rules.record_trade(
        regime=ev.regime or "unknown",
        hold_hours=hold_hours,
        win=ev.total_pnl > 0,
        pnl=ev.total_pnl,
    )


# ---------------------------------------------------------------------------
# T2-e -- parameter_tuner
# god-block source: multi_strategy_main.py:3912-3917 (FEEDBACK_RECORD_FIX
# gate, default on -- the pre-fix broken signal_quality call this section
# used to share a try/except with is dead code, not extracted here; see
# module docstring)
# ---------------------------------------------------------------------------
def on_close_parameter_tuner(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.parameter_tuner is None:
        return
    ctx.parameter_tuner.record_trade_outcome(ev.total_pnl)


# ---------------------------------------------------------------------------
# T2-f -- feedback (FeedbackLoop; not signal_quality -- see close_context.py's
# field note)
# god-block source: multi_strategy_main.py:3958-4000
# ---------------------------------------------------------------------------
def on_close_feedback(ev: TradeClosed, ctx: CloseCtx) -> None:
    """``regime``/``entry_type`` here are sourced from ``ev.trade_profile``
    (matching the god-block's ``pos.trade_profile.regime`` /
    ``.entry_type`` at :3967-3970) -- a DIFFERENT source than the top-level
    ``ev.regime`` field other T2 subscribers use (that one is sourced from
    ``entry_reasons``/metadata, matching ``pos.entry_reasons.get("regime")``
    at :3862, the source regime_feedback/confidence_floor/hold_time_rules
    use above). Both are legitimate, distinct god-block read sites -- not a
    mapping error. ``ev.llm_action``/``ev.llm_conf``/``ev.llm_agreed``
    already reproduce the god-block's ``pos.entry_reasons.get("llm_action",
    "")`` etc. cascade exactly (see trade_closed.py's ``from_trade_event``),
    so no re-derivation needed here.
    """
    if ctx.feedback is None:
        return
    trade_profile = ev.trade_profile or {}
    regime = trade_profile.get("regime", "") or ""
    entry_type = trade_profile.get("entry_type", "") or ""
    entry_reasons = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
    num_agree = entry_reasons.get("num_agree", 1)

    ctx.feedback.record_outcome(
        confidence=ev.confidence if ev.confidence is not None else 0,
        win=ev.total_pnl > 0,
        pnl=ev.total_pnl,
        strategy=ev.strategy,
        symbol=ev.symbol,
        regime=regime,
        side=ev.side,
        entry_type=entry_type,
        num_agree=num_agree,
        hold_time_s=ev.hold_time_s,
        exit_action=ev.close_type,
        leverage=ev.leverage,
        llm_action=ev.llm_action,
        llm_confidence=ev.llm_conf,
        llm_agreed=ev.llm_agreed,
    )


# ---------------------------------------------------------------------------
# T2-g -- graduated_rules
# god-block source: multi_strategy_main.py:4002-4033
# ---------------------------------------------------------------------------
def on_close_graduated_rules(ev: TradeClosed, ctx: CloseCtx) -> None:
    """``hour_utc``: the god-block reads ``pos.open_time.hour`` off a live
    datetime; ``TradeClosed.open_time`` is the same value already flattened
    to an ISO-8601 string (see trade_closed.py module docstring on why --
    JSON-safety), so we parse it back to get ``.hour``. Falls back to -1
    (the god-block's own "skip hour-conditioned matching" sentinel) when
    absent or unparseable -- not a FIELD-GAP, just a string<->datetime
    round-trip.
    """
    engine = ctx.graduated_rules_engine if ctx.graduated_rules_engine is not None else _default_graduated_rules_engine()

    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
    strategies_active = er.get("strategies_agree") or (
        ev.entry_reasons if isinstance(ev.entry_reasons, list) else []
    )
    num_agree = (len(strategies_active) if strategies_active else 0) or er.get("num_agree", 0)

    confidence = er.get("confidence") or er.get("llm_confidence") or er.get("win_prob_deflated") or 0.0
    confidence = float(confidence) if confidence else 0.0
    if 0.0 < confidence <= 1.0:
        confidence *= 100.0

    trade_profile = ev.trade_profile or {}
    regime = er.get("regime") or trade_profile.get("regime", "") or ""

    hour_utc = -1
    if ev.open_time:
        try:
            hour_utc = datetime.fromisoformat(ev.open_time).hour
        except (TypeError, ValueError):
            hour_utc = -1

    engine.record_outcome(
        symbol=ev.symbol,
        regime=regime,
        side=ev.side,
        won=ev.total_pnl > 0,
        hour_utc=hour_utc,
        strategies_active=strategies_active,
        num_agree=num_agree,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# T2-h -- ic_tracker
# god-block source: multi_strategy_main.py:4100-4111 (IC_SIGN_FIX: feeds the
# raw signed market return, not direction-adjusted pnl -- see that comment's
# rationale in the god-block for why this is NOT total_pnl-based)
# ---------------------------------------------------------------------------
def on_close_ic_tracker(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.ic_tracker is None:
        return
    entry_px = ev.entry or 0.0
    exit_px = ev.price or 0.0
    if not (entry_px > 0 and exit_px > 0):
        logger.warning(
            f"[IC] {ev.symbol}: skipping IC record — invalid prices "
            f"(entry={entry_px}, exit={exit_px})"
        )
        return
    market_return = (exit_px - entry_px) / entry_px
    direction = 1 if ev.side == "LONG" else -1
    for factor in _contributing_factors(ev):
        ctx.ic_tracker.record(factor, direction, market_return)


# ---------------------------------------------------------------------------
# T2-i -- kelly
# god-block source: multi_strategy_main.py:4113-4118
# ---------------------------------------------------------------------------
def on_close_kelly(ev: TradeClosed, ctx: CloseCtx) -> None:
    """``pnl_pct``: the god-block computes ``_actual_return * 100`` where
    ``_actual_return = total_pnl / (self.risk_mgr.equity or 1.0)`` -- a live
    equity read the grep guard forbids. ``ev.pnl_pct_of_equity`` is the
    identical computation already frozen at emit time from
    ``equity_after`` -- see module docstring. Falls back to 0.0 when unset.
    """
    if ctx.kelly_engine is None:
        return
    pnl_pct = ev.pnl_pct_of_equity if ev.pnl_pct_of_equity is not None else 0.0
    for factor in _contributing_factors(ev):
        ctx.kelly_engine.record_trade(factor, ev.total_pnl > 0, pnl_pct)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_learning(bus: CloseBus, ctx: CloseCtx) -> None:
    """Subscribe all nine learning-tier subscribers in Tier T2, FULL-close
    only (matching the god-block's ``_FULL_CLOSE`` gate for every one of
    these nine call sites), in the deterministic order listed in the module
    docstring -- mirrors the god-block's own top-to-bottom source order.
    """
    bus.subscribe(
        "weight_mgr", lambda ev: on_close_weight_mgr(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "regime_feedback", lambda ev: on_close_regime_feedback(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "confidence_floor", lambda ev: on_close_confidence_floor(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "hold_time_rules", lambda ev: on_close_hold_time_rules(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "parameter_tuner", lambda ev: on_close_parameter_tuner(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "feedback", lambda ev: on_close_feedback(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "graduated_rules", lambda ev: on_close_graduated_rules(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "ic_tracker", lambda ev: on_close_ic_tracker(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "kelly", lambda ev: on_close_kelly(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
