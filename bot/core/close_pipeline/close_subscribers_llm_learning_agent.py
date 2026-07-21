"""LLM LEARNING AGENT close_bus subscriber (Phase 0.4-B, FINAL batch).

THIS COMPLETES THE SUBSCRIBER EXTRACTION -- the last of the god-block's
close-handling subscribers. Every prior batch (accounting, learning batch
1/2, misc batch 3) deliberately deferred this one because, unlike every
other subscriber, it makes a LIVE LLM call (via the multi-agent
coordinator's ``get_post_trade_lesson`` -- routed through ``claude -p`` per
this project's CLI-routing convention; NEVER an ``ANTHROPIC_API_KEY``), not
just a deterministic in-process record.

GOD-BLOCK SOURCE: ``multi_strategy_main.py``'s ``_process_symbol`` close
block, lines 4392-4471 (the ``LLM_MULTI_AGENT``-gated "Multi-Agent
Learning: run LLM Learning Agent on each closed trade" section). This sits
in the SAME ungated-by-``_FULL_CLOSE`` region as batch 2's
``on_close_learning_integrator`` (4333-4346) and ``on_close_thesis_grading``
(4348-4390) -- see close_subscribers_learning2.py's module docstring: "All
ten are gated by the god-block's ``_FULL_CLOSE`` action-string allowlist" --
this subscriber is registered with the same ``kind=(CloseKind.FULL,)``
filter for the same reason (full/terminal closes only, matching every
sibling subscriber sourced from this same god-block region).

TWO LLM-ADJACENT CALLS, ONE SUBSCRIBER:
  1. ``get_coordinator().get_post_trade_lesson(trade_data)`` -- the actual
     LLM call, extracting a lesson dict from the closed trade.
  2. ``process_agent_lesson(lesson, trade_data)`` -- a deterministic
     (non-LLM) wiring step that fans the lesson out to deep_memory /
     knowledge_base / calibration. The god-block guards this second call in
     its OWN nested ``try/except`` (multi_strategy_main.py:4429-4469,
     independent of the outer ``try/except`` around the LLM call itself) --
     reproduced here as a second, independently-swallowed ``try/except`` so
     a lesson-wiring failure can never be confused with (or mask) an LLM
     call failure, exactly matching the god-block's two-try-block shape.

EV/CTX MAPPING (every value traced to the frozen ``TradeClosed`` event or
injected ``CloseCtx`` -- NEVER ``pos_mgr.positions``, a live ``pos``
refetch, or a ``risk_mgr.equity`` read used to derive a value):
  - ``symbol``/``side``/``strategy``/``leverage``/``close_type``(exit_action)
    /``price``(exit_price) -- direct ``ev.*`` fields.
  - ``total_pnl``/``outcome`` -- ``ev.total_pnl`` (never ``ev.pnl``, the
    per-leg delta -- see trade_closed.py's module docstring).
  - ``pnl_pct``/``pnl_pct_signed`` -- the god-block computes
    ``total_pnl / self.risk_mgr.equity * 100`` TWICE (identically) at close
    time; that is a live ``risk_mgr.equity`` READ used to derive a value,
    the exact anti-pattern this extraction forbids. ``TradeClosed`` already
    computes the SAME ratio ONCE at emit time from the frozen
    ``equity_after`` snapshot (see ``trade_closed.py``'s
    ``pnl_pct_of_equity`` field) -- both god-block occurrences map onto
    this one frozen field.
  - ``confidence`` -- ``ev.confidence`` (``pos.confidence if pos else 0`` in
    the god-block; ``ev.confidence`` is only ``None`` when no position
    snapshot was ever attached, matching "no pos" -> 0 fallback).
  - ``regime``/``entry_type`` -- ``pos.trade_profile.regime`` /
    ``.entry_type`` in the god-block (``_rg_fb``/``_et_fb``, set a few
    lines above this block's source range) -- reproduced via
    ``ev.trade_profile.get("regime"/"entry_type")``, the same
    trade-profile-first helper used throughout close_subscribers_misc.py
    and close_subscribers_learning2.py.
  - ``hold_time_s``/``hold_hours`` -- ``ev.hold_time_s`` and
    ``ev.hold_time_s / 3600.0`` (the god-block's own ``_hold_h``
    computation, reproduced identically).
  - ``notes`` (carries ``thesis_id=`` for the coordinator's internal
    ``close_thesis()`` no-op path) -- ``pos.entry_reasons.get("llm_notes",
    "")`` in the god-block -- reproduced via ``ev.entry_reasons.get(
    "llm_notes", "")``.
  - ``entry_price``/``price_move_pct`` (second call only) -- ``pos.entry``
    -> ``ev.entry``; ``price_move_pct = (exit_price - entry_price) /
    entry_price * 100`` reproduced identically from ``ev.price``/``ev.entry``.
  - ``agent_confidences`` (second call only) -- the god-block re-parses
    ``pos.entry_reasons`` (handling the "maybe a JSON string" case) to pull
    ``agent_confidences``; ``TradeClosed.entry_reasons`` is ALWAYS a dict by
    construction (see trade_closed.py's ``__post_init__`` deep-copy), so
    this subscriber uses the same defensive ``isinstance(ev.entry_reasons,
    dict)`` guard already established by close_subscribers_misc.py (e.g.
    ``on_close_growth``, ``on_close_cost_optimizer``) instead of
    re-implementing JSON parsing.

FIELD-GAP: NONE. Unlike several batch-3 subscribers, every value the
god-block reads for this call site is available on the frozen
``TradeClosed`` event (directly or via ``trade_profile``/``entry_reasons``)
-- there is no live-only aggregate this subscriber needs to default away.

FIRE-AND-FORGET / NO-REPLAY / ERROR-SWALLOWING (T3):
  - Registered ``tier=Tier.T3_FIRE_AND_FORGET``, ``required=False``,
    ``replay=False`` -- a missed lesson on a boot-time backlog is
    acceptable; replaying it would mean re-issuing a live LLM call for a
    trade that closed before this process started, which spec04.md's
    T-R14 explicitly forbids ("boot with N-event backlog: 0 LLM calls").
  - ``dedupe`` left at its default ``True`` -- one lesson per closed
    position; a duplicate ``publish()`` of the same close must not trigger
    a second LLM call (CloseBus's generalized exactly-once seam, keyed by
    ``(subscriber_name, position_id)``).
  - The whole function is gated by ``LLM_MULTI_AGENT`` (mirroring the
    god-block's own env check at multi_strategy_main.py:4394) -- when off,
    this is a pure no-op: no lesson-input dict is even built.
  - EVERY exception -- gate/env resolution, coordinator resolution, the
    LLM call itself, lesson parsing, ``process_agent_lesson`` resolution,
    and the lesson-wiring call -- is caught and logged at ``debug`` level,
    never re-raised. ``CloseBus`` already isolates one subscriber's
    exception from its siblings (see close_bus.py's per-subscriber
    ``try/except``), but this subscriber additionally swallows internally
    (matching the god-block's OWN two nested ``try/except`` blocks at this
    call site) so an LLM/API hiccup never shows up as a "failed" delivery
    at all -- it is expected, ordinary, and silent, exactly as it is live
    today.

NOT YET WIRED: nothing calls ``register_llm_learning_agent`` from any live
code path. The god-block remains the sole authoritative close path until
Phase D/E. This file is built + unit-tested in isolation (Phase B); tests
MUST mock ``learning_agent_fn``/``process_agent_lesson_fn`` -- never let a
real LLM call happen in a test.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional

from core.close_pipeline.close_bus import CloseBus, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import TradeClosed
from core.close_types import CloseKind

logger = logging.getLogger("bot.core.close_pipeline.close_subscribers_llm_learning_agent")


# ---------------------------------------------------------------------------
# Lazy default resolvers -- importing this module must never eagerly import
# llm.agents.coordinator / llm.agents.learning_integration (the coordinator
# import chain drags in the LLM client) just to unit-test with a mock ctx.
# ---------------------------------------------------------------------------
def _default_llm_multi_agent_enabled() -> bool:
    return os.getenv("LLM_MULTI_AGENT", "").lower() in ("1", "true", "yes")


def _default_learning_agent_fn() -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    from llm.agents.coordinator import get_coordinator
    return get_coordinator().get_post_trade_lesson


def _default_process_agent_lesson_fn() -> Callable[[Dict[str, Any], Dict[str, Any]], None]:
    from llm.agents.learning_integration import process_agent_lesson
    return process_agent_lesson


# ---------------------------------------------------------------------------
# Shared helpers -- duplicated (not imported) from close_subscribers_misc.py
# / close_subscribers_learning2.py for the same module-independence reason
# documented in every prior batch's file.
# ---------------------------------------------------------------------------
def _trade_profile_regime(ev: TradeClosed) -> str:
    trade_profile = ev.trade_profile or {}
    return trade_profile.get("regime", "") or ""


def _trade_profile_entry_type(ev: TradeClosed) -> str:
    trade_profile = ev.trade_profile or {}
    return trade_profile.get("entry_type", "") or ""


# ---------------------------------------------------------------------------
# T3-final -- llm_learning_agent
# god-block source: multi_strategy_main.py:4392-4471
# ---------------------------------------------------------------------------
def on_close_llm_learning_agent(ev: TradeClosed, ctx: CloseCtx) -> None:
    """See module docstring for the full ev/ctx mapping, the
    ``LLM_MULTI_AGENT`` gate, and the fire-and-forget/no-replay/
    swallow-errors handling. This function never raises.
    """
    try:
        enabled = (
            ctx.llm_multi_agent_enabled if ctx.llm_multi_agent_enabled is not None
            else _default_llm_multi_agent_enabled()
        )
        if not enabled:
            return

        er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
        regime = _trade_profile_regime(ev)
        entry_type = _trade_profile_entry_type(ev)
        win = ev.total_pnl > 0
        outcome = "WIN" if win else "LOSS"
        pnl_pct = ev.pnl_pct_of_equity if ev.pnl_pct_of_equity is not None else 0.0
        confidence = ev.confidence if ev.confidence is not None else 0
        hold_time_s = ev.hold_time_s or 0.0
        hold_hours = hold_time_s / 3600.0
        notes = er.get("llm_notes", "") or ""

        lesson_input: Dict[str, Any] = {
            "symbol": ev.symbol,
            "side": ev.side,
            "outcome": outcome,
            "pnl": ev.total_pnl,
            "pnl_pct": pnl_pct,
            "pnl_pct_signed": pnl_pct,
            "confidence": confidence,
            "regime": regime,
            "strategy": ev.strategy,
            "hold_time_s": hold_time_s,
            "hold_hours": hold_hours,
            "exit_action": ev.close_type,
            "exit_price": ev.price,
            "leverage": ev.leverage,
            "entry_type": entry_type,
            "notes": notes,  # carries thesis_id= for the coordinator's close_thesis() no-op
        }
    except Exception:
        logger.debug("[LEARNING-AGENT] building lesson input failed -- skipping", exc_info=True)
        return

    try:
        learning_agent_fn = (
            ctx.learning_agent_fn if ctx.learning_agent_fn is not None
            else _default_learning_agent_fn()
        )
    except Exception:
        logger.debug("[LEARNING-AGENT] coordinator unavailable -- skipping", exc_info=True)
        return

    try:
        lesson = learning_agent_fn(lesson_input)
    except Exception as e:
        # Fire-and-forget: an LLM call failure must NEVER propagate.
        logger.debug(f"[LEARNING-AGENT] Multi-agent learning error: {e}")
        return

    if not lesson or not isinstance(lesson, dict):
        return

    lesson_txt = lesson.get("lesson", "") or lesson.get("insight", "")
    if lesson_txt:
        logger.info(f"[LEARNING-AGENT] {ev.symbol}: {str(lesson_txt)[:100]}")

    # Second, independently-swallowed try/except -- matches the god-block's
    # own nested try/except around the lesson-wiring call (see module
    # docstring). A wiring failure must not be confused with an LLM
    # failure, and must not propagate either.
    try:
        entry_px = ev.entry if ev.entry else 0.0
        try:
            price_move_pct = ((ev.price - entry_px) / entry_px * 100.0) if entry_px else 0.0
        except (TypeError, ZeroDivisionError):
            price_move_pct = 0.0
        agent_confidences = er.get("agent_confidences", {}) or {}

        trade_data_for_learning: Dict[str, Any] = {
            "symbol": ev.symbol,
            "side": ev.side,
            "outcome": outcome,
            "pnl": ev.total_pnl,
            "pnl_pct": pnl_pct,
            "entry_price": entry_px,
            "exit_price": ev.price,
            "price_move_pct": price_move_pct,
            "confidence": confidence,
            "agent_confidences": agent_confidences,
            "regime": regime,
            "strategy": ev.strategy,
            "notes": notes,
        }

        process_fn = (
            ctx.process_agent_lesson_fn if ctx.process_agent_lesson_fn is not None
            else _default_process_agent_lesson_fn()
        )
        process_fn(lesson, trade_data_for_learning)
        logger.debug("[LEARNING-AGENT] Lesson wired to deep_memory/knowledge/calibration")
    except Exception as e:
        logger.debug(f"[LEARNING-AGENT] Integration error: {e}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_llm_learning_agent(bus: CloseBus, ctx: CloseCtx) -> None:
    """Subscribe the final batch-0.4-B subscriber, FULL-close only
    (matching this god-block call site's ``_FULL_CLOSE``-gated region --
    see module docstring), T3 fire-and-forget: ``required=False``,
    ``replay=False`` (never replayed at boot -- a missed lesson on restart
    is acceptable; re-issuing a live LLM call for a stale backlog is not),
    ``dedupe`` left at its default ``True`` (one lesson per closed
    position, no duplicate LLM calls on a re-publish).
    """
    bus.subscribe(
        "llm_learning_agent", lambda ev: on_close_llm_learning_agent(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
