"""LEARNING-TIER (T2 "derived readers") close_bus subscribers (Phase 0.4-B,
batch 2 -- MEMORY/ML/LEARNING).

This is a faithful RE-EXPRESSION of ten god-block bodies in
``multi_strategy_main.py``'s ``_process_symbol`` close-handling block
(lines 4243-4661; see each function's docstring for its exact source
range). Every value read here comes off the frozen ``TradeClosed`` event
(``ev``) or the injected ``CloseCtx`` (``ctx``), NEVER from
``pos_mgr.positions``, a live ``pos`` refetch, or a ``risk_mgr.equity``
READ used to derive a value. See the grep/AST guard in
``bot/tests/test_close_subscribers_learning2.py`` for the mechanically
enforced version of that invariant.

NOT YET WIRED: nothing calls ``register_learning2`` from any live code
path. The god-block remains the sole authoritative close path until
Phase D/E. This file is built + unit-tested in isolation (Phase B).

THE TEN SUBSCRIBERS (tier, god-block source range, registration order --
mirrors the god-block's own top-to-bottom source order, NOT the order the
subscribers are enumerated in spec/task lists):
  T2-j deep_memory_dna    on_close_deep_memory_dna    multi_strategy_main.py:4243-4263
  T2-k post_trade_learner on_close_post_trade_learner multi_strategy_main.py:4265-4287
  T2-l reflection         on_close_reflection         multi_strategy_main.py:4289-4316
  T2-m autopsy            on_close_autopsy            multi_strategy_main.py:4318-4327
  T2-n learning_integrator on_close_learning_integrator multi_strategy_main.py:4333-4346
  T2-o thesis_grading     on_close_thesis_grading      multi_strategy_main.py:4348-4390
  T2-p rl_buffer          on_close_rl_buffer          multi_strategy_main.py:4473-4504
  T2-q counterfactual     on_close_counterfactual     multi_strategy_main.py:4549-4562
  T2-r signal_outcome     on_close_signal_outcome     multi_strategy_main.py:4599-4620
  T2-s ml                 on_close_ml                 multi_strategy_main.py:4622-4661

All ten are gated by the god-block's ``_FULL_CLOSE`` action-string
allowlist (multi_strategy_main.py:3824-3837) -- reproduced here via the
CloseBus ``kind=(CloseKind.FULL,)`` subscribe filter, same rationale as
close_subscribers_learning.py's (batch 1) T2 subscribers.

SKIPPED (not part of this batch's scope -- see the extraction mandate's
explicit T3 fire-forget/misc exclusion list; deferred to batch 3):
alerts, telemetry, growth, discovery, adaptive_risk/sizer, _llm_triggers,
quant_brain chase, survival, cost_optimizer, auto_demotion, agent_perf,
active_learning, cooldown, learning_mode, A/B, continuous_backtest,
shadow_ledger, and the LLM Learning Agent call
(multi_strategy_main.py:4392-4471, gated by ``LLM_MULTI_AGENT`` -- makes a
live LLM call, explicitly out of scope for a deterministic T2 rewrite).

CANNOT BE FAITHFULLY REPRODUCED FROM THE FROZEN EVENT ALONE (flagged for
the eventual emit-site/helper -- see each function's docstring for detail):
  - deep_memory's ``dm.regimes.record_transition(...)`` half (analytics.py
    :263-280) needs ``self.regime_detector.get_transition_summary()`` --
    LIVE current-regime state with no per-event equivalent. NOT extracted;
    only the ``record_full_trade`` call is reproduced here.
  - deep_memory's ``btc_trend`` needs a live cross-symbol
    (``self._last_prices["BTC"]``) price cache -- a single position's
    TradeClosed event cannot carry another symbol's market state. Defaults
    to "neutral" (see on_close_deep_memory_dna's docstring for exactly how
    this differs from the live behavior).
  - on_close_ml's ``close_volatility``/``close_price_change_1h_pct`` needed
    a live OHLCV fetch (network I/O) at close time -- structurally
    impossible to reproduce from an already-frozen event under any
    rewrite; would need a helper that fetches BEFORE freezing the event and
    attaches the result via ``TradeClosed.close_volatility``'s already-
    reserved (but never populated in production) field.

FIELD-GAPS THIS BATCH (value needed but not on TradeClosed -- listed here,
also called out per-function): deep_memory's ``btc_trend``/``funding_rate``
/``atr``/``setup_type`` (pos.setup_type half); post_trade_learner's
``funding_rate``; reflection's ``atr``; ml's ``close_price_change_1h_pct``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from core.close_pipeline.close_bus import CloseBus, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import TradeClosed
from core.close_types import CloseKind

logger = logging.getLogger("bot.core.close_pipeline.close_subscribers_learning2")


# ---------------------------------------------------------------------------
# Lazy default resolvers -- importing this module must never eagerly import
# llm.brain_wiring / llm.trade_autopsy / llm.learning_integrator (keeps this
# leaf-ish and avoids dragging in process-wide singletons + file I/O just to
# unit-test with a mock ctx).
# ---------------------------------------------------------------------------
def _default_thesis_grader() -> Any:
    import llm.brain_wiring as _bw
    return _bw


def _default_autopsy_engine() -> Any:
    import llm.trade_autopsy as _ta
    return _ta


def _default_learning_integrator() -> Any:
    from llm.learning_integrator import get_learning_integrator
    return get_learning_integrator()


def _default_post_trade_learner() -> Any:
    class _Default:
        @staticmethod
        def generate_immediate_lesson(trade_data: Any) -> Any:
            from llm.post_trade_learner import generate_immediate_lesson
            return generate_immediate_lesson(trade_data)

        @staticmethod
        def apply_memory_update(update: Any, *, symbol: str = "", regime: str = "") -> None:
            from llm.memory_store import apply_memory_update
            apply_memory_update(update, symbol=symbol, regime=regime)

    return _Default()


def _default_log_signal_outcome_fn() -> Callable[..., Any]:
    from data.db import log_signal_outcome
    return log_signal_outcome


def _default_rl_append_transition_fn() -> Callable[..., Any]:
    from rl.buffer import append_transition
    return append_transition


# ---------------------------------------------------------------------------
# Shared helper -- trade_profile-first regime, matching the god-block's
# ``pos.trade_profile.regime`` read site (used by feedback/reflection/ML/
# RL/post_trade_learner/learning_integrator/signal_outcome below, mirroring
# batch 1's on_close_feedback source).
# ---------------------------------------------------------------------------
def _trade_profile_regime(ev: TradeClosed) -> str:
    trade_profile = ev.trade_profile or {}
    return trade_profile.get("regime", "") or ""


# ---------------------------------------------------------------------------
# T2-j -- deep_memory_dna
# god-block source: multi_strategy_main.py:4243-4263 (calls
# self._record_trade_dna, defined in core/analytics.py:169-261's
# AnalyticsMixin._record_trade_dna -- the exact dm.record_full_trade() call
# this reproduces).
# ---------------------------------------------------------------------------
def on_close_deep_memory_dna(ev: TradeClosed, ctx: CloseCtx) -> None:
    """NOT extracted: the god-block's cache-invalidation side effects that
    run immediately after a successful DNA record (dynamic_thresholds()
    .invalidate(), prompt_enricher.invalidate_cache()) -- unrelated
    collaborators outside this batch's ten-subscriber scope -- and
    analytics.py:263-280's ``dm.regimes.record_transition(...)`` call,
    which reads ``self.regime_detector.get_transition_summary()`` (LIVE
    current-regime bot state, no per-event equivalent -- see module
    docstring's "CANNOT BE FAITHFULLY REPRODUCED" list).

    FIELD-GAPs (values the god-block sourced from live bot-level caches, or
    fields TradeClosed does not carry at all -- defaulted here, never
    refetched):
      - btc_trend: originally from self._last_prices["BTC"] /
        self._price_changes_1h["BTC"] (live cross-symbol cache). Defaults
        to "neutral" here -- the SAME value the original produces when
        btc_1h_change happens to be flat (its own no-signal default), but
        this rewrite produces "neutral" unconditionally, not just when BTC
        happened to be flat.
      - funding_rate: self._last_funding_rates.get(symbol, 0.0) (live
        cache). Defaults to 0.0.
      - atr: pos.atr -- TradeClosed carries no atr field. Defaults to 0.0.
      - setup_type: pos.setup_type half of the
        ``entry_reasons["setup_key"] or pos.setup_type`` cascade --
        TradeClosed carries no setup_type field, so only the
        entry_reasons half survives here.
    """
    if ctx.deep_memory is None:
        return

    total_pnl = ev.total_pnl
    if total_pnl > 0:
        outcome = "WIN"
    elif total_pnl < -0.01:
        outcome = "LOSS"
    else:
        outcome = "BREAKEVEN"

    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
    trade_profile = ev.trade_profile or {}

    regime = trade_profile.get("regime", "") or er.get("regime", "") or ""
    entry_type = trade_profile.get("entry_type", "") or ""

    strategies_agreed = er.get("strategies_agreed") or er.get("strategies_agree") or []
    if not strategies_agreed and ev.strategy:
        strategies_agreed = [ev.strategy]

    setup_type = er.get("setup_key", "") or ""  # FIELD-GAP: pos.setup_type half gone

    # trade_id: reproduces f"{symbol}_{side}_{int(open_time.timestamp())}";
    # falls back to a position_id-based id when open_time is absent/
    # unparseable (still globally unique, just a different string shape).
    trade_id = f"{ev.symbol}_{ev.side}_{ev.position_id}"
    if ev.open_time:
        try:
            trade_id = f"{ev.symbol}_{ev.side}_{int(datetime.fromisoformat(ev.open_time).timestamp())}"
        except (TypeError, ValueError):
            pass

    ctx.deep_memory.record_full_trade(
        trade_id=trade_id,
        symbol=ev.symbol,
        side=ev.side,
        entry_price=ev.entry or 0.0,
        exit_price=ev.price,
        sl=ev.original_sl or 0.0,
        tp1=ev.tp1 or 0.0,
        tp2=ev.tp2 or 0.0,
        confidence=ev.confidence or 0.0,
        leverage=ev.leverage,
        regime=regime,
        strategies_agreed=strategies_agreed,
        outcome=outcome,
        pnl=total_pnl,
        hold_time_s=ev.hold_time_s or 0.0,
        exit_reason=ev.close_type,
        llm_action=ev.llm_action,
        llm_confidence=ev.llm_conf,
        llm_reasoning=er.get("llm_reasoning", "") or "",
        entry_type=entry_type,
        setup_type=setup_type,
        btc_trend="neutral",  # FIELD-GAP -- see docstring
        volume_ratio=0.0,     # matches god-block's own hardcoded 0.0
        funding_rate=0.0,     # FIELD-GAP -- see docstring
        atr=0.0,              # FIELD-GAP -- see docstring
    )


# ---------------------------------------------------------------------------
# T2-k -- post_trade_learner
# god-block source: multi_strategy_main.py:4265-4287
# ---------------------------------------------------------------------------
def on_close_post_trade_learner(ev: TradeClosed, ctx: CloseCtx) -> None:
    """FIELD-GAP: funding_rate sourced from
    self._last_funding_rates.get(symbol, 0) (live bot-level cache) -- not on
    TradeClosed. Defaults to 0.0.
    """
    if ctx.post_trade_learner is None:
        return

    regime = _trade_profile_regime(ev)
    lesson = ctx.post_trade_learner.generate_immediate_lesson({
        "symbol": ev.symbol,
        "side": ev.side,
        "outcome": "WIN" if ev.total_pnl > 0 else "LOSS",
        "pnl": ev.total_pnl,
        "confidence": ev.confidence if ev.confidence is not None else 0,
        "regime": regime,
        "strategy": ev.strategy,
        "hold_time_s": ev.hold_time_s,
        "exit_action": ev.close_type,
        "llm_action": ev.llm_action,
        "llm_confidence": ev.llm_conf,
        "funding_rate": 0.0,  # FIELD-GAP -- see docstring
    })
    if lesson:
        ctx.post_trade_learner.apply_memory_update(lesson, symbol=ev.symbol, regime=regime)


# ---------------------------------------------------------------------------
# T2-l -- reflection
# god-block source: multi_strategy_main.py:4289-4316
# ---------------------------------------------------------------------------
def on_close_reflection(ev: TradeClosed, ctx: CloseCtx) -> None:
    """FIELD-GAP: atr (getattr(pos, 'atr', 0)) -- TradeClosed carries no atr
    field. Defaults to 0.0.
    """
    if ctx.reflection is None:
        return

    regime = _trade_profile_regime(ev)
    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}

    win_prob = er.get("win_prob", er.get("win_prob_deflated", 0)) or 0
    ev_per_dollar = er.get("ev_per_dollar", 0) or 0
    rr = er.get("rr_tp1", er.get("rr1", 0)) or 0

    ctx.reflection.on_close(
        symbol=ev.symbol,
        side=ev.side,
        entry_price=ev.entry or 0,
        exit_price=ev.price,
        pnl=ev.total_pnl,
        hold_time_s=ev.hold_time_s or 0,
        leverage=ev.leverage,
        confidence=ev.confidence if ev.confidence is not None else 0,
        regime=regime,
        exit_action=ev.close_type,
        sl_price=ev.original_sl or 0,
        tp1_price=ev.tp1 or 0,
        peak_price=ev.highest_price or 0,
        lowest_price=ev.lowest_price or 0,
        win_prob=win_prob,
        ev=ev_per_dollar,
        rr=rr,
        entry_reasons=er,
        atr=0.0,  # FIELD-GAP -- see docstring
    )


# ---------------------------------------------------------------------------
# T2-m -- autopsy
# god-block source: multi_strategy_main.py:4318-4327
# ---------------------------------------------------------------------------
def on_close_autopsy(ev: TradeClosed, ctx: CloseCtx) -> None:
    """STATEFUL ACROSS EVENTS (like batch 1's CLOSE_DEDUP_GUARD note): the
    god-block's autopsy cadence is driven by ``self._closed_trade_count``, a
    counter incremented on EVERY full close -- not derivable from any single
    frozen TradeClosed. Reproduced via ``ctx.closed_trade_count``, a plain
    mutable int on the long-lived, per-bot CloseCtx instance, incremented in
    place exactly like the god-block increments its own instance attribute.
    """
    engine = ctx.autopsy if ctx.autopsy is not None else _default_autopsy_engine()
    ctx.closed_trade_count += 1
    if engine.should_run_autopsy(ctx.closed_trade_count):
        engine.generate_autopsy()


# ---------------------------------------------------------------------------
# T2-n -- learning_integrator
# god-block source: multi_strategy_main.py:4333-4346
# ---------------------------------------------------------------------------
def on_close_learning_integrator(ev: TradeClosed, ctx: CloseCtx) -> None:
    integrator = ctx.learning_integrator if ctx.learning_integrator is not None else _default_learning_integrator()
    integrator.on_trade_closed({
        "symbol": ev.symbol,
        "side": ev.side,
        "outcome": "WIN" if ev.total_pnl > 0 else "LOSS",
        "pnl": ev.total_pnl,
        "confidence": ev.confidence if ev.confidence is not None else 0,
        "regime": _trade_profile_regime(ev),
        "strategy": ev.strategy,
    })


# ---------------------------------------------------------------------------
# T2-o -- thesis_grading
# god-block source: multi_strategy_main.py:4348-4390
# ---------------------------------------------------------------------------
def on_close_thesis_grading(ev: TradeClosed, ctx: CloseCtx) -> None:
    """``ev.entry_reasons`` is already a parsed dict on the frozen event
    (TradeClosed.__post_init__ deep-copies it, and from_trade_event/
    the position snapshot already normalize a JSON-string entry_reasons
    into a dict at construction time) -- unlike the god-block, which has to
    ``json.loads(pos.entry_reasons)`` defensively here because ``pos`` may
    still carry the raw string. No re-parsing needed.

    pnl_pct: the god-block computes ``total_pnl / self.risk_mgr.equity *
    100`` (live equity read, forbidden). ``ev.pnl_pct_of_equity`` is the
    identical computation already frozen at emit time -- see
    close_subscribers_learning.py's on_close_kelly for the same
    substitution pattern.
    """
    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
    notes = str(er.get("llm_notes", "") or "")
    thesis_id = str(er.get("thesis_id", "") or "")
    if not thesis_id and "thesis_id=" in notes:
        try:
            thesis_id = notes.split("thesis_id=")[1].split(" ")[0].split("|")[0].strip()
        except (IndexError, AttributeError):
            thesis_id = ""
    if not thesis_id:
        return

    grader = ctx.thesis_grader if ctx.thesis_grader is not None else _default_thesis_grader()
    pnl_pct = ev.pnl_pct_of_equity if ev.pnl_pct_of_equity is not None else 0.0

    if ev.side == "LONG":
        max_favorable = ev.highest_price
        max_adverse = ev.lowest_price
    else:
        max_favorable = ev.lowest_price
        max_adverse = ev.highest_price

    grader.close_thesis(
        thesis_id=thesis_id,
        exit_price=ev.price,
        pnl_pct=pnl_pct,
        max_favorable=max_favorable,
        max_adverse=max_adverse,
        actual_hold_h=(ev.hold_time_s or 0.0) / 3600.0,
    )


# ---------------------------------------------------------------------------
# T2-p -- rl_buffer
# god-block source: multi_strategy_main.py:4473-4504
# ---------------------------------------------------------------------------
def on_close_rl_buffer(ev: TradeClosed, ctx: CloseCtx) -> None:
    """FIELD-GAPs:
      - state.volatility: originally ``_close_vol if '_close_vol' in dir()
        else 0`` -- in the god-block's actual execution order this ALWAYS
        evaluates the dir()-check False (the RL buffer block runs BEFORE
        the ML block that defines ``_close_vol``, multi_strategy_main.py:
        4630), so live behavior is already 0.0 here today in practice.
        Reproduced via ``ev.close_volatility`` (also unpopulated in
        production today -- see on_close_ml's docstring), defaulting to 0.0.
      - action.llm_mode: ``self.llm_mode.name`` -- current BOT-LEVEL mode
        (config/state, not a per-position value), not on TradeClosed.
        Threaded via ``ctx.llm_mode_name`` (a config passthrough, not a live
        re-read of mutable position/equity state); defaults to "".

    reward's risk-amount denominator: the god-block computes
    ``self.risk_mgr.equity * 0.01`` (live equity read). Reproduced via
    ``ev.equity_after * 0.01`` -- the frozen post-trade equity snapshot,
    same substitution pattern as batch 1's on_close_kelly/on_close_ic_tracker.
    """
    fn = ctx.rl_append_transition_fn if ctx.rl_append_transition_fn is not None else _default_rl_append_transition_fn()

    regime = _trade_profile_regime(ev)
    trade_profile = ev.trade_profile or {}
    entry_type = trade_profile.get("entry_type", "") or ""
    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}

    risk_amt = (ev.equity_after or 0.0) * 0.01
    reward = ev.total_pnl / risk_amt if risk_amt > 0 else 0.0

    fn(
        state={
            "symbol": ev.symbol,
            "regime": regime,
            "confidence": ev.confidence if ev.confidence is not None else 0,
            "side": ev.side,
            "entry": ev.entry or 0,
            "volatility": ev.close_volatility if ev.close_volatility is not None else 0.0,
        },
        action={
            "llm_mode": ctx.llm_mode_name or "",
            "llm_action": ev.llm_action,
            "size_multiplier": er.get("llm_size_mult", 1.0),
            "leverage": ev.leverage,
            "entry_type": entry_type,
        },
        reward=round(reward, 4),
        metadata={
            "trigger": er.get("trigger", "") or "",
            "hold_time_s": ev.hold_time_s or 0,
            "outcome": "WIN" if ev.total_pnl > 0 else "LOSS",
            "pnl": round(ev.total_pnl, 2),
            "strategy": ev.strategy,
        },
    )


# ---------------------------------------------------------------------------
# T2-q -- counterfactual
# god-block source: multi_strategy_main.py:4549-4562
# ---------------------------------------------------------------------------
def on_close_counterfactual(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.counterfactual is None:
        return
    ctx.counterfactual.record_exit_alternative(
        symbol=ev.symbol,
        actual_exit_action=ev.close_type,
        actual_exit_price=ev.price,
        tp1_price=ev.tp1 or 0,
        tp2_price=ev.tp2 or 0,
        entry_price=ev.entry or 0,
        actual_pnl=ev.total_pnl,
    )


# ---------------------------------------------------------------------------
# T2-r -- signal_outcome
# god-block source: multi_strategy_main.py:4599-4620
# ---------------------------------------------------------------------------
def on_close_signal_outcome(ev: TradeClosed, ctx: CloseCtx) -> None:
    """pnl_pct: the god-block computes ``total_pnl / (self.risk_mgr.equity *
    self.config.risk_per_trade) * 100`` -- a live equity read AND a config
    constant. ``ev.pnl_pct_of_equity`` is the frozen equivalent of
    ``total_pnl / equity_after * 100``; dividing that by
    ``ctx.risk_per_trade`` (a static config passthrough, never a live
    mutable read) reproduces the identical ratio. Falls back to 0.0 when
    either is unavailable, matching the god-block's own equity<=0 fallback.
    """
    fn = ctx.log_signal_outcome_fn if ctx.log_signal_outcome_fn is not None else _default_log_signal_outcome_fn()
    regime = _trade_profile_regime(ev)

    pnl_pct = 0.0
    if ev.pnl_pct_of_equity is not None and ctx.risk_per_trade:
        pnl_pct = ev.pnl_pct_of_equity / ctx.risk_per_trade

    fn(
        symbol=ev.symbol,
        strategy=ev.strategy or "",
        side=ev.side,
        confidence=ev.confidence if ev.confidence is not None else 0,
        entry_price=ev.entry or 0,
        exit_price=ev.price,
        exit_action=ev.close_type,
        pnl=ev.total_pnl,
        pnl_pct=pnl_pct,
        hold_time_s=ev.hold_time_s or 0,
        regime=regime,
        leverage=ev.leverage,
        win=ev.total_pnl > 0,
    )


# ---------------------------------------------------------------------------
# T2-s -- ml
# god-block source: multi_strategy_main.py:4622-4661
# ---------------------------------------------------------------------------
def on_close_ml(ev: TradeClosed, ctx: CloseCtx) -> None:
    """CANNOT FAITHFULLY REPRODUCE: close_volatility / close_price_change_1h
    _pct were computed live via ``self.fetcher.fetch_ohlcv(...)`` -- a
    network call at close time, fundamentally not derivable from an
    already-frozen event. ``TradeClosed.close_volatility`` exists as a
    reserved field but is NEVER populated by ``from_trade_event`` in
    production today (defaults None -- see trade_closed.py's module
    docstring), so this subscriber's close_volatility reads 0.0 until a
    Phase C/D helper starts fetching BEFORE freezing the event and passing
    it in explicitly. close_price_change_1h_pct has no TradeClosed field at
    all -- FIELD-GAP, defaults to 0.0.

    hour_of_day/day_of_week: the god-block used ``datetime.now(timezone
    .utc)`` at record time (effectively == close time, since this runs
    synchronously right after the close). Reproduced here from
    ``ev.close_time`` instead of a live now() call, falling back to 0/0 if
    unparseable.
    """
    if ctx.ml is None:
        return
    from ml.learner import TradeOutcome

    close_regime = _trade_profile_regime(ev)

    hour_of_day = 0
    day_of_week = 0
    if ev.close_time:
        try:
            _dt = datetime.fromisoformat(ev.close_time)
            hour_of_day = _dt.hour
            day_of_week = _dt.weekday()
        except (TypeError, ValueError):
            pass

    ctx.ml.record_outcome(TradeOutcome(
        symbol=ev.symbol,
        strategy=ev.strategy,
        side=ev.side,
        confidence=ev.confidence if ev.confidence is not None else 0,
        leverage=ev.leverage,
        win=ev.total_pnl > 0,
        pnl=ev.total_pnl,
        exit_action=ev.close_type,
        hold_time_s=ev.hold_time_s or 0.0,
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        close_volatility=ev.close_volatility if ev.close_volatility is not None else 0.0,
        close_price_change_1h_pct=0.0,  # FIELD-GAP -- see docstring
        close_regime=close_regime,
    ))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_learning2(bus: CloseBus, ctx: CloseCtx) -> None:
    """Subscribe all ten batch-2 learning-tier subscribers in Tier T2,
    FULL-close only (matching the god-block's ``_FULL_CLOSE`` gate for
    every one of these ten call sites), in the deterministic source order
    listed in the module docstring -- mirrors the god-block's own
    top-to-bottom source order (multi_strategy_main.py:4243-4661).
    """
    bus.subscribe(
        "deep_memory_dna", lambda ev: on_close_deep_memory_dna(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "post_trade_learner", lambda ev: on_close_post_trade_learner(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "reflection", lambda ev: on_close_reflection(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "autopsy", lambda ev: on_close_autopsy(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "learning_integrator", lambda ev: on_close_learning_integrator(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "thesis_grading", lambda ev: on_close_thesis_grading(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "rl_buffer", lambda ev: on_close_rl_buffer(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "counterfactual", lambda ev: on_close_counterfactual(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "signal_outcome", lambda ev: on_close_signal_outcome(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "ml", lambda ev: on_close_ml(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
