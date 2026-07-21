"""MISC-TIER (T2 "derived readers" + T3 "fire-and-forget") close_bus
subscribers (Phase 0.4-B, batch 3 -- the remaining/misc subscribers).

This is a faithful RE-EXPRESSION of nineteen god-block bodies in
``multi_strategy_main.py``'s ``_process_symbol`` close-handling block
(lines ~3936-4954; see each function's docstring for its exact source
range). Every value read here comes off the frozen ``TradeClosed`` event
(``ev``) or the injected ``CloseCtx`` (``ctx``), NEVER from
``pos_mgr.positions``, a live ``pos`` refetch, or a ``risk_mgr.equity`` READ
used to derive a value. See the grep/AST guard in
``bot/tests/test_close_subscribers_misc.py`` for the mechanically enforced
version of that invariant.

NOT YET WIRED: nothing calls ``register_misc`` from any live code path. The
god-block remains the sole authoritative close path until Phase D/E. This
file is built + unit-tested in isolation (Phase B).

THE NINETEEN SUBSCRIBERS (tier, god-block source range):
  T2-t  continuous_backtest        on_close_continuous_backtest        multi_strategy_main.py:3918-3932
  T2-u  shadow_ledger               on_close_shadow_ledger               multi_strategy_main.py:4197-4201
  T2-v  adaptive_risk                on_close_adaptive_risk               multi_strategy_main.py:4532-4540
  T2-w  adaptive_sizer               on_close_adaptive_sizer              multi_strategy_main.py:4542-4547
  T3-a  llm_triggers_outcome         on_close_llm_triggers_outcome        multi_strategy_main.py:3936-3944
  T3-b  quant_brain_chase            on_close_quant_brain_chase           multi_strategy_main.py:3946-3951
  T3-c  regime_strategy_weighter     on_close_regime_strategy_weighter    multi_strategy_main.py:3972-3976
  T3-d  growth                       on_close_growth                      multi_strategy_main.py:4203-4222
  T3-e  discovery_corpus             on_close_discovery_corpus            multi_strategy_main.py:4224-4241
  T3-f  risk_telemetry               on_close_risk_telemetry              multi_strategy_main.py:4506-4513
  T3-g  survival                     on_close_survival                    multi_strategy_main.py:4515-4530
  T3-h  ab_testing                   on_close_ab_testing                  multi_strategy_main.py:4564-4584
  T3-i  learning_mode                on_close_learning_mode               multi_strategy_main.py:4586-4597
  T3-j  cooldown_tracking            on_close_cooldown_tracking           multi_strategy_main.py:4680-4697
  T3-k  telemetry                    on_close_telemetry                   multi_strategy_main.py:4698-4703
  T3-l  llm_triggers_notify          on_close_llm_triggers_notify         multi_strategy_main.py:4705-4713
  T3-m  agent_perf                   on_close_agent_perf                  multi_strategy_main.py:4778-4791
  T3-n  cost_optimizer               on_close_cost_optimizer              multi_strategy_main.py:4793-4802
  T3-o  alert                        on_close_alert                       multi_strategy_main.py:4908-4954

TIER SPLIT (per the extraction mandate): only four of these are T2 --
continuous_backtest, shadow_ledger, adaptive_risk, adaptive_sizer -- because
they feed FUTURE trading decisions (sizing/backtest/risk multipliers), same
class as batch 1/2's learning-tier subscribers. Everything else here is T3
fire-and-forget (alerts, telemetry, growth/discovery corpora, agent
performance/cost bookkeeping, A/B testing, learning-mode phase tracking,
LLM trigger notifications, cooldown bookkeeping) -- none of it gates or
blocks any live trading decision, matching close_bus.py's T3 contract
(``replay=False`` -- never replayed at boot).

ALL NINETEEN are gated by the god-block's ``_FULL_CLOSE`` / terminal-close
condition (``_is_terminal_close`` at multi_strategy_main.py:4676-4679, a
superset of ``_FULL_CLOSE`` -- see close_subscribers_accounting.py's T1
docstring for why LegKind.TERMINAL / CloseKind.FULL already covers this
without a hand-maintained allowlist) -- reproduced here via the CloseBus
``kind=(CloseKind.FULL,)`` subscribe filter, same rationale as every prior
batch's T1/T2 subscribers.

DEFERRED / NOT EXTRACTED THIS BATCH (see report for full detail):
  - The LLM Multi-Agent Learning block (multi_strategy_main.py:4392-4471,
    ``LLM_MULTI_AGENT``-gated) -- makes a live ``claude -p`` call; a
    separate careful item per the extraction mandate, not touched here.
  - Candidate backfill (``self._active_candidates.pop(symbol, None)`` +
    ``self._candidate_logger.log_candidate(...)``,
    multi_strategy_main.py:4767-4776) -- needs a LIVE lookup into
    ``self._active_candidates`` keyed by symbol (an entry-time object
    stored earlier in the bot's lifecycle); ``TradeClosed.candidate_ref``
    is a RESERVED field for exactly this correlation id but is never
    populated by any current emitter (see trade_closed.py's module
    docstring) -- cannot be faithfully reproduced from the frozen event
    alone. Same class as batch 2's btc_trend/close_volatility gaps.
  - Auto-demotion (multi_strategy_main.py:4804-4878) -- needs a LIVE
    aggregate of the last 30 closed trades (from trades.csv or the ledger),
    a LIVE cost-tracker budget read, and a LIVE risk_mgr.equity-vs-config
    drawdown calculation, AND it MUTATES ``self.llm_mode`` (bot-level
    autonomy control state, not a "recording" side effect) -- structurally
    different from every other subscriber in this file. Cannot be
    faithfully reproduced from one frozen event; deferred as
    god-block-structural + not-reproducible.
  - Active learning cycle (multi_strategy_main.py:4880-4906) -- needs a
    LIVE aggregate of the last 20 trades (``self._active_learning
    ._load_trades(20)``), LIVE ``self._agent_perf.get_all_stats()``, and a
    LIVE wall-clock timer check (``should_run()``) independent of this
    event's content -- same "needs aggregate live state, not one frozen
    event" class as auto-demotion above. Not extracted.
  - Circuit-breaker trip alert (multi_strategy_main.py:4956-4970,
    ``if not self.risk_mgr.circuit_breaker.is_trading_allowed(): ...``) --
    a bot-wide system-health check triggered AFTER close processing, not
    keyed off this trade's own data at all (it fires identically regardless
    of which symbol just closed) -- god-block-structural, not a per-event
    subscriber.
  - Exchange close-order submission (multi_strategy_main.py:3779-3795),
    the ``_pos_for_gate`` / ``_is_terminal_close`` completeness-gate
    computation (:4675-4678), and CLOSE_DEDUP_GUARD's ``_recent_close_keys``
    cache (already documented as god-block-structural in
    close_subscribers_learning.py's module docstring) -- control flow, not
    subscribers.
  - Leverage liquidation-risk check on OTHER open positions
    (multi_strategy_main.py:4972-4992) -- runs after the close loop, keyed
    off ``self.pos_mgr.get_open_positions()``, unrelated to the specific
    trade that just closed -- god-block-structural.

SURPRISE FOUND DURING EXTRACTION: ``self._agent_perf.record_outcome(...)``
(multi_strategy_main.py:4781) calls a method that does not exist on the real
``AgentPerformanceTracker`` class (``llm/agents/performance_tracker.py`` --
its actual API is ``score_trade``/``record_pipeline_run``, no
``record_outcome``). This call has always raised ``AttributeError`` in
production, silently swallowed by its own ``except Exception`` handler --
i.e. this god-block call site has been dead code (this specific write) since
it was added. Reproduced faithfully as-is (a duck-typed ``.record_outcome``
call) per this extraction's "faithful re-expression, not a bug fix" mandate
-- see ``on_close_agent_perf``'s docstring and close_context.py's
``agent_perf`` field note.

Similarly, ``self._regime_strategy_weighter`` is permanently ``None`` in
production: its constructor imports ``data.regime_strategy_weighter``, a
module that does not exist anywhere in the current tree, so the god-block's
own init ``try/except`` always fails and leaves the attribute ``None`` --
see ``on_close_regime_strategy_weighter``'s docstring.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from core.close_pipeline.close_bus import CloseBus, Tier
from core.close_pipeline.close_context import CloseCtx
from core.close_pipeline.trade_closed import TradeClosed
from core.close_types import CloseKind

logger = logging.getLogger("bot.core.close_pipeline.close_subscribers_misc")


# ---------------------------------------------------------------------------
# Lazy default resolvers -- importing this module must never eagerly import
# execution.adaptive_risk / llm.survival_pressure / llm.learning_mode /
# llm.strategy_discovery.corpus / llm.triggers / data.fetchers.telemetry /
# alerts.enhanced_telegram (keeps this leaf-ish and avoids dragging in
# process-wide singletons + file I/O just to unit-test with a mock ctx).
# ---------------------------------------------------------------------------
def _default_adaptive_sizer() -> Any:
    from execution.adaptive_risk import get_adaptive_sizer
    return get_adaptive_sizer()


def _default_survival_record_outcome_fn() -> Callable[..., None]:
    from llm.survival_pressure import record_trade_outcome
    return record_trade_outcome


def _default_telemetry_cls() -> Any:
    from data.fetchers.telemetry import Telemetry
    return Telemetry


def _default_format_trade_event_fn() -> Callable[..., str]:
    from alerts.enhanced_telegram import format_trade_event_telegram
    return format_trade_event_telegram


# ---------------------------------------------------------------------------
# Shared helper -- trade_profile-first regime (same convention as
# close_subscribers_learning2.py's ``_trade_profile_regime`` -- duplicated
# rather than imported cross-module so each close_pipeline subscriber file
# stays independently leaf-ish).
# ---------------------------------------------------------------------------
def _trade_profile_regime(ev: TradeClosed) -> str:
    trade_profile = ev.trade_profile or {}
    return trade_profile.get("regime", "") or ""


def _trade_profile_entry_type(ev: TradeClosed) -> str:
    trade_profile = ev.trade_profile or {}
    return trade_profile.get("entry_type", "") or ""


def _resolved_confidence(ev: TradeClosed) -> float:
    """Reproduces the `pos.confidence if pos.confidence else 50.0` fallback
    cascade used by the first god-block try-block (multi_strategy_main.py
    :3859-3863) -- duplicated from close_subscribers_learning.py's
    identically-named helper for the same module-independence reason.
    """
    return ev.confidence if ev.confidence else 50.0


# ---------------------------------------------------------------------------
# T2-t -- continuous_backtest
# god-block source: multi_strategy_main.py:3918-3932 (FEEDBACK_RECORD_FIX
# gate, default on -- see close_subscribers_learning.py's on_close_
# parameter_tuner docstring for the same fix's other half)
# ---------------------------------------------------------------------------
def on_close_continuous_backtest(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.continuous_backtest is None:
        return
    ctx.continuous_backtest.record_outcome(
        symbol=ev.symbol,
        win=ev.total_pnl > 0,
        pnl=ev.total_pnl,
        confidence_at_entry=_resolved_confidence(ev),
        strategy=ev.strategy,
        regime=ev.regime or "unknown",
        hold_time_s=ev.hold_time_s or 0,
        exit_action=ev.close_type,
        leverage=ev.leverage if ev.leverage else 1.0,
    )


# ---------------------------------------------------------------------------
# T2-u -- shadow_ledger
# god-block source: multi_strategy_main.py:4197-4201
# ---------------------------------------------------------------------------
def on_close_shadow_ledger(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.shadow_ledger is None:
        return
    ctx.shadow_ledger.resolve_shadows(ev.symbol, ev.price)


# ---------------------------------------------------------------------------
# T2-v -- adaptive_risk
# god-block source: multi_strategy_main.py:4532-4540
# ---------------------------------------------------------------------------
def on_close_adaptive_risk(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.adaptive_risk is None:
        return
    ctx.adaptive_risk.record_outcome(win=ev.total_pnl > 0, regime=_trade_profile_regime(ev))


# ---------------------------------------------------------------------------
# T2-w -- adaptive_sizer
# god-block source: multi_strategy_main.py:4542-4547
# ---------------------------------------------------------------------------
def on_close_adaptive_sizer(ev: TradeClosed, ctx: CloseCtx) -> None:
    sizer = ctx.adaptive_sizer if ctx.adaptive_sizer is not None else _default_adaptive_sizer()
    sizer.record_outcome(ev.symbol, won=ev.total_pnl > 0)


# ---------------------------------------------------------------------------
# T3-a -- llm_triggers_outcome
# god-block source: multi_strategy_main.py:3936-3944
# ---------------------------------------------------------------------------
def on_close_llm_triggers_outcome(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.llm_triggers is None:
        return
    ctx.llm_triggers.record_trade_outcome(
        strategy=ev.strategy,
        entry_type=_trade_profile_entry_type(ev),
        win=ev.total_pnl > 0,
    )


# ---------------------------------------------------------------------------
# T3-b -- quant_brain_chase
# god-block source: multi_strategy_main.py:3946-3951
# ---------------------------------------------------------------------------
def on_close_quant_brain_chase(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.quant_brain is None:
        return
    ctx.quant_brain.record_outcome(ev.symbol, ev.total_pnl > 0)


# ---------------------------------------------------------------------------
# T3-c -- regime_strategy_weighter
# god-block source: multi_strategy_main.py:3972-3976
# ---------------------------------------------------------------------------
def on_close_regime_strategy_weighter(ev: TradeClosed, ctx: CloseCtx) -> None:
    """See close_context.py's ``regime_strategy_weighter`` field note:
    ``ctx.regime_strategy_weighter`` is permanently ``None`` in production
    today (the collaborator module doesn't exist in the current tree), so
    this subscriber is a no-op live -- faithfully reproduced, not fixed.
    """
    regime = _trade_profile_regime(ev)
    if ctx.regime_strategy_weighter is None or not regime or not ev.strategy:
        return
    ctx.regime_strategy_weighter.record_outcome(regime, ev.strategy, ev.total_pnl > 0)


# ---------------------------------------------------------------------------
# T3-d -- growth
# god-block source: multi_strategy_main.py:4203-4222
# ---------------------------------------------------------------------------
def on_close_growth(ev: TradeClosed, ctx: CloseCtx) -> None:
    """``hour``: the god-block uses ``datetime.now(timezone.utc).hour`` at
    record time (effectively == close time, synchronous call) -- reproduced
    from ``ev.close_time`` instead of a live now() call, same substitution
    pattern as close_subscribers_learning2.py's on_close_ml. Falls back to 0
    if unparseable/absent.
    """
    if ctx.growth is None:
        return
    from datetime import datetime

    hour = 0
    if ev.close_time:
        try:
            hour = datetime.fromisoformat(ev.close_time).hour
        except (TypeError, ValueError):
            hour = 0

    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
    ctx.growth.on_trade_closed({
        "symbol": ev.symbol,
        "side": ev.side,
        "outcome": "WIN" if ev.total_pnl > 0 else "LOSS",
        "pnl": ev.total_pnl,
        "pnl_pct": ev.pnl_pct_of_equity if ev.pnl_pct_of_equity is not None else 0,
        "confidence": ev.confidence if ev.confidence is not None else 0,
        "regime": _trade_profile_regime(ev),
        "strategy": ev.strategy,
        "num_agree": er.get("num_agree", 1),
        "hold_time_s": ev.hold_time_s or 0,
        "leverage": ev.leverage,
        "hour": hour,
        "entry_type": _trade_profile_entry_type(ev),
    })


# ---------------------------------------------------------------------------
# T3-e -- discovery_corpus
# god-block source: multi_strategy_main.py:4224-4241
# ---------------------------------------------------------------------------
def on_close_discovery_corpus(ev: TradeClosed, ctx: CloseCtx) -> None:
    fn = ctx.add_observation_fn
    if fn is None:
        try:
            from llm.strategy_discovery.corpus import add_observation as fn
        except Exception:
            return
    regime = _trade_profile_regime(ev) or "unknown"
    outcome_str = "WIN" if ev.total_pnl > 0 else "LOSS"
    fn(
        category="trade_outcome",
        symbol=ev.symbol,
        regime=regime,
        observation=(
            f"{ev.strategy} {ev.side} {outcome_str}: "
            f"pnl=${ev.total_pnl:.2f}, regime={regime}, "
            f"exit={ev.close_type}, entry_type={_trade_profile_entry_type(ev)}, "
            f"lev={ev.leverage:.0f}x, "
            f"hold={(ev.hold_time_s or 0.0):.0f}s"
        ),
    )


# ---------------------------------------------------------------------------
# T3-f -- risk_telemetry
# god-block source: multi_strategy_main.py:4506-4513
# ---------------------------------------------------------------------------
def on_close_risk_telemetry(ev: TradeClosed, ctx: CloseCtx) -> None:
    """FIELD-GAP: ``daily_pnl`` -- the god-block reads
    ``self.risk_mgr.circuit_breaker.daily_pnl`` (a LIVE rolling accumulator
    across ALL of today's trades, not this single trade's pnl) -- no
    per-event equivalent on ``TradeClosed``. Defaults to 0.0.
    ``equity``: sourced from the frozen ``ev.equity_after`` snapshot, not a
    live ``risk_mgr.equity`` read.
    """
    if ctx.risk_telemetry is None:
        return
    ctx.risk_telemetry.update(
        equity=ev.equity_after if ev.equity_after is not None else 0.0,
        daily_pnl=0.0,  # FIELD-GAP -- see docstring
    )


# ---------------------------------------------------------------------------
# T3-g -- survival
# god-block source: multi_strategy_main.py:4515-4530
# ---------------------------------------------------------------------------
def on_close_survival(ev: TradeClosed, ctx: CloseCtx) -> None:
    """FIELD-GAP: ``funding_cost`` -- the god-block computes this from
    ``self._last_funding_rates.get(symbol, 0)`` (a LIVE cross-call cache);
    when that rate is falsy (the common case -- no cache hit) the
    god-block's own ``if _fr and pos:`` guard already skips the computation
    and leaves ``_funding_cost`` at its 0.0 default, so this reproduces the
    SAME value the live path produces whenever the cache misses. Always 0.0
    here (the cache is never available to a frozen event).
    """
    fn = ctx.survival_record_outcome_fn
    if fn is None:
        try:
            fn = _default_survival_record_outcome_fn()
        except Exception:
            return
    fn(
        outcome="WIN" if ev.total_pnl > 0 else "LOSS",
        pnl=ev.total_pnl,
        funding_cost=0.0,  # FIELD-GAP -- see docstring
        equity=ev.equity_after if ev.equity_after is not None else 0.0,
    )


# ---------------------------------------------------------------------------
# T3-h -- ab_testing
# god-block source: multi_strategy_main.py:4564-4584
# ---------------------------------------------------------------------------
def on_close_ab_testing(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.ab_manager is None:
        return
    regime = _trade_profile_regime(ev)
    for exp in ctx.ab_manager.get_active_experiments():
        group = ctx.ab_manager.get_assignment(exp.id, ev.symbol, ev.strategy or "")
        ctx.ab_manager.record_outcome(
            experiment_id=exp.id,
            group=group,
            symbol=ev.symbol,
            pnl=ev.total_pnl,
            win=ev.total_pnl > 0,
            metadata={
                "strategy": ev.strategy,
                "regime": regime,
                "leverage": ev.leverage,
            },
        )


# ---------------------------------------------------------------------------
# T3-i -- learning_mode
# god-block source: multi_strategy_main.py:4586-4597
# ---------------------------------------------------------------------------
def on_close_learning_mode(ev: TradeClosed, ctx: CloseCtx) -> None:
    active_fn = ctx.learning_mode_active_fn
    record_fn = ctx.learning_mode_record_fn
    if active_fn is None or record_fn is None:
        try:
            from llm.learning_mode import is_learning_mode_active, record_trade_observed
            active_fn = active_fn or is_learning_mode_active
            record_fn = record_fn or record_trade_observed
        except Exception:
            return
    if not active_fn():
        return
    record_fn(
        symbol=ev.symbol,
        side=ev.side,
        outcome="WIN" if ev.total_pnl > 0 else "LOSS",
        pnl=ev.total_pnl,
        confidence=ev.confidence if ev.confidence is not None else 0,
    )


# ---------------------------------------------------------------------------
# T3-j -- cooldown_tracking
# god-block source: multi_strategy_main.py:4680-4697
# ---------------------------------------------------------------------------
def on_close_cooldown_tracking(ev: TradeClosed, ctx: CloseCtx) -> None:
    """Mutates ``ctx.symbol_cooldown`` / ``ctx.symbol_daily_pnl`` /
    ``ctx.last_close_win`` / ``ctx.last_close_side`` IN PLACE -- same
    "stateful, lives on the long-lived per-bot CloseCtx" pattern as
    ``ctx.closed_trade_count`` (see close_subscribers_learning2.py's
    on_close_autopsy). ``time.time()`` (wall clock) is used deliberately,
    not ``ev.close_time`` -- this cooldown gates REAL elapsed processing
    time for the NEXT trade decision, not the semantic close time of this
    event (matching the god-block's own ``time.time()`` call at this site).
    """
    ctx.symbol_cooldown[ev.symbol] = time.time()

    today = time.strftime("%Y-%m-%d", time.gmtime())
    if ctx.symbol_daily_pnl_date != today:
        ctx.symbol_daily_pnl.clear()
        ctx.symbol_daily_pnl_date = today
    ctx.symbol_daily_pnl[ev.symbol] = ctx.symbol_daily_pnl.get(ev.symbol, 0) + ev.total_pnl
    if ctx.symbol_daily_pnl[ev.symbol] <= ctx.symbol_daily_loss_limit:
        logger.warning(
            f"[{ev.symbol}] DAILY LOSS LIMIT HIT: ${ctx.symbol_daily_pnl[ev.symbol]:.2f} "
            f"-- pausing {ev.symbol} for today"
        )

    ctx.last_close_win[ev.symbol] = ev.total_pnl > 0
    ctx.last_close_side[ev.symbol] = ev.side


# ---------------------------------------------------------------------------
# T3-k -- telemetry
# god-block source: multi_strategy_main.py:4698-4703
# ---------------------------------------------------------------------------
def on_close_telemetry(ev: TradeClosed, ctx: CloseCtx) -> None:
    telemetry = ctx.telemetry_cls if ctx.telemetry_cls is not None else _default_telemetry_cls()
    if ev.total_pnl > 0:
        telemetry.inc("trades_won")
    else:
        telemetry.inc("trades_lost")
    telemetry.record("pnls", ev.total_pnl)


# ---------------------------------------------------------------------------
# T3-l -- llm_triggers_notify
# god-block source: multi_strategy_main.py:4705-4713
# ---------------------------------------------------------------------------
def on_close_llm_triggers_notify(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.llm_triggers is None:
        return
    from llm.triggers import LLMTrigger

    ctx.llm_triggers.add(
        LLMTrigger.POSITION_CLOSED,
        symbol=ev.symbol,
        context=(
            f"Closed {ev.side} {ev.symbol} via {ev.close_type} "
            f"PnL=${ev.total_pnl:+.2f}"
        ),
    )


# ---------------------------------------------------------------------------
# T3-m -- agent_perf
# god-block source: multi_strategy_main.py:4778-4791
# ---------------------------------------------------------------------------
def on_close_agent_perf(ev: TradeClosed, ctx: CloseCtx) -> None:
    """See module docstring's "SURPRISE FOUND" note and close_context.py's
    ``agent_perf`` field note: the real ``AgentPerformanceTracker`` has no
    ``record_outcome`` method, so this call always raised ``AttributeError``
    in production (silently swallowed). Reproduced faithfully as-is.

    FIELD-GAP: ``mfe_pct``/``mae_pct`` sourced from ``getattr(pos,
    'max_favorable_pct'/'max_adverse_pct', 0)`` in the god-block -- neither
    attribute exists anywhere on the ``Position`` class, so that
    ``hasattr``-style guard is ALWAYS False in production (always 0), not a
    gap introduced by this extraction. ``exit_time``: reproduced from
    ``ev.close_time`` instead of a live ``datetime.now()`` call, same
    substitution pattern used throughout batch 2.
    """
    if ctx.agent_perf is None:
        return
    ctx.agent_perf.record_outcome(
        symbol=ev.symbol,
        pnl=ev.total_pnl,
        entry_time=ev.open_time or "",
        exit_time=ev.close_time or "",
        mfe_pct=0.0,  # matches the god-block's own always-False hasattr guard
        mae_pct=0.0,  # matches the god-block's own always-False hasattr guard
        side=ev.side,
    )


# ---------------------------------------------------------------------------
# T3-n -- cost_optimizer
# god-block source: multi_strategy_main.py:4793-4802
# ---------------------------------------------------------------------------
def on_close_cost_optimizer(ev: TradeClosed, ctx: CloseCtx) -> None:
    if ctx.cost_optimizer is None:
        return
    er = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
    pipeline_type = er.get("cost_pipeline", "standard")
    ctx.cost_optimizer.record_outcome(pipeline_type=pipeline_type, pnl=ev.total_pnl)


# ---------------------------------------------------------------------------
# T3-o -- alert
# god-block source: multi_strategy_main.py:4908-4954
# ---------------------------------------------------------------------------
def on_close_alert(ev: TradeClosed, ctx: CloseCtx) -> None:
    """FIELD-GAPs (live risk_mgr aggregate reads, not on TradeClosed):
      - ``daily_pnl``: ``self.risk_mgr.circuit_breaker.daily_pnl``. 0.0.
      - ``daily_trades`` / ``daily_wins``: ``self.risk_mgr.daily_summary()``
        dict entries. 0 / 0.
      - ``max_favorable_pct``: same always-False ``hasattr`` guard as
        ``on_close_agent_perf`` above (Position has no such attribute). 0.
    ``equity`` is sourced from the frozen ``ev.equity_after`` snapshot, not
    a live ``risk_mgr.equity`` read. This subscriber only fires on FULL
    closes (the CloseBus ``kind=(CloseKind.FULL,)`` filter), so
    ``total_pnl`` is always ``ev.total_pnl`` -- matching the god-block's own
    ``total_pnl if event.action in _FULL_CLOSE else 0`` ternary, which is
    always the ``total_pnl`` branch at this call site.
    """
    if ctx.alerts is None:
        return

    entry_reasons = ev.entry_reasons if isinstance(ev.entry_reasons, dict) else {}
    state_path = ev.state_path or ""
    fmt_fn = ctx.format_trade_event_fn if ctx.format_trade_event_fn is not None else _default_format_trade_event_fn()

    try:
        message = fmt_fn(
            action=ev.close_type,
            symbol=ev.symbol,
            side=ev.side,
            price=ev.price,
            pnl=ev.pnl,
            leverage=ev.leverage,
            total_pnl=ev.total_pnl,
            hold_time_s=ev.hold_time_s or 0,
            strategy=ev.strategy or "",
            equity=ev.equity_after if ev.equity_after is not None else 0.0,
            daily_pnl=0.0,     # FIELD-GAP -- see docstring
            daily_trades=0,    # FIELD-GAP -- see docstring
            daily_wins=0,      # FIELD-GAP -- see docstring
            entry_price=ev.entry or 0,
            original_sl=ev.original_sl or 0,
            confidence=ev.confidence if ev.confidence is not None else 0,
            num_agree=entry_reasons.get("num_agree", 0),
            ev_per_dollar=entry_reasons.get("ev_per_dollar", 0),
            regime=entry_reasons.get("regime", ""),
            tp1_hit="TP1" in state_path,
            tp1_price=ev.tp1 or 0,
            max_favorable_pct=0,  # matches the god-block's own always-False hasattr guard
        )
        ctx.alerts.send_trade_event(ev.close_type, ev.symbol, message)
    except Exception:
        details = (
            f"{ev.close_type} {ev.side} @ {ev.price}\n"
            f"PnL: ${ev.pnl:+.2f} | Leverage: {ev.leverage:.1f}x\n"
            f"Total PnL: ${ev.total_pnl:+.2f}"
        )
        ctx.alerts.send_trade_event(ev.close_type, ev.symbol, details)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_misc(bus: CloseBus, ctx: CloseCtx) -> None:
    """Subscribe all nineteen batch-3 subscribers, FULL-close only (matching
    every one of these nineteen god-block call sites' terminal-close gate),
    T2 (continuous_backtest/shadow_ledger/adaptive_risk/adaptive_sizer)
    before T3 (everything else) -- mirrors the god-block's own top-to-bottom
    source order within each tier.
    """
    bus.subscribe(
        "continuous_backtest", lambda ev: on_close_continuous_backtest(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "shadow_ledger", lambda ev: on_close_shadow_ledger(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "adaptive_risk", lambda ev: on_close_adaptive_risk(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "adaptive_sizer", lambda ev: on_close_adaptive_sizer(ev, ctx),
        tier=Tier.T2_DERIVED_READERS, kind=(CloseKind.FULL,),
    )
    bus.subscribe(
        "llm_triggers_outcome", lambda ev: on_close_llm_triggers_outcome(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "quant_brain_chase", lambda ev: on_close_quant_brain_chase(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "regime_strategy_weighter", lambda ev: on_close_regime_strategy_weighter(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "growth", lambda ev: on_close_growth(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "discovery_corpus", lambda ev: on_close_discovery_corpus(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "risk_telemetry", lambda ev: on_close_risk_telemetry(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "survival", lambda ev: on_close_survival(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "ab_testing", lambda ev: on_close_ab_testing(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "learning_mode", lambda ev: on_close_learning_mode(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "cooldown_tracking", lambda ev: on_close_cooldown_tracking(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "telemetry", lambda ev: on_close_telemetry(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "llm_triggers_notify", lambda ev: on_close_llm_triggers_notify(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "agent_perf", lambda ev: on_close_agent_perf(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "cost_optimizer", lambda ev: on_close_cost_optimizer(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
    bus.subscribe(
        "alert", lambda ev: on_close_alert(ev, ctx),
        tier=Tier.T3_FIRE_AND_FORGET, kind=(CloseKind.FULL,), required=False, replay=False,
    )
