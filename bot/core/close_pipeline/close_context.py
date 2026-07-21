"""``CloseCtx`` — the collaborator bundle accounting-tier close subscribers
read from (Phase 0.4-B, part 2).

WHY THIS EXISTS: the god-block in ``multi_strategy_main.py`` reaches
directly into ``self.risk_mgr``, ``self.trade_ledger``, ``self.trade_logger``,
module-level functions (``data.db.log_trade``, ``data.learning.
record_trade_outcome``, ``data.trade_log.log_closed_trade``), and an
optional ``self.kelly_engine``. A close_bus subscriber must not import
``multi_strategy_main`` (leaf-module invariant, see close_subscribers_
accounting.py's module docstring) and must be unit-testable with a plain
mock -- so every collaborator the six accounting subscribers touch is
threaded through this one small, dependency-light dataclass instead.

FIELD NOTES:
  - ``risk_mgr``: anything exposing ``.update_equity(pnl)`` and
    ``.circuit_breaker`` (an object with ``.consecutive_losses`` /
    ``.tripped`` / ``.daily_pnl``) -- matches ``execution.risk.RiskManager``
    duck-type. Subscribers never read ``risk_mgr.equity`` for VALUE
    DERIVATION (that is the exact "risk_mgr.equity read-for-derivation"
    anti-pattern the grep guard forbids) -- they call ``update_equity()``
    to MUTATE it and otherwise read the post-booking value off the frozen
    ``TradeClosed.equity_after`` field, never live off the object.
  - ``trade_ledger``: anything exposing ``.record_trade(dict, *,
    source=None, position_id=None)`` -- matches ``feedback.trade_ledger.
    TradeLedger``.
  - ``trade_logger``: optional, anything exposing ``.log_trade_event(event,
    hold_time_s=0)`` -- matches ``execution.trade_logger.TradeLogger``.
    ``None`` means "no paper-trading trade logger configured" (mirrors the
    god-block's ``if self.trade_logger:`` guard at multi_strategy_main.py:3954).
  - ``kelly_engine``: optional, SOFT collaborator. It is a Tier-2 (derived
    reader) object per spec04.md's close_subscribers.py module docstring --
    accounting-tier subscribers do not own it. It is exposed here ONLY
    because one T1 ledger column (``kelly_weight_applied``) reads it in the
    god-block (multi_strategy_main.py:4153-4156). See close_subscribers_
    accounting.py's on_close_ledger docstring for the FIELD-GAP this
    produces when ``kelly_engine`` is ``None`` (the accounting-tier default).
  - ``source``: optional explicit ``core.provenance.Source`` override
    threaded into every gated write (``trade_ledger.record_trade``,
    ``record_trade_outcome``). ``None`` preserves today's behavior exactly
    (the callee resolves provenance itself via env/pytest-context -- see
    core/provenance.py's ``resolve_source``).
  - ``log_trade_fn`` / ``record_trade_outcome_fn`` / ``log_closed_trade_fn``:
    optional injectable overrides of the three module-level write functions
    the god-block calls directly. ``None`` means "use the real production
    function" (resolved lazily, by local import, inside the subscriber that
    needs it -- see close_subscribers_accounting.py's ``_default_*``
    helpers) so importing this module never drags in ``data.db`` /
    ``data.learning`` / ``data.trade_log`` eagerly. Tests pass a ``Mock`` /
    plain callable here instead so NO real data file is ever touched.

LEARNING-TIER (T2) FIELDS (Phase 0.4-B, batch 1 -- see
close_subscribers_learning.py):
  - ``weight_mgr``: anything exposing ``.record_outcome(strategy, win,
    symbol="")`` -- matches ``data.strategy_weights.StrategyWeightManager``.
  - ``regime_feedback``: anything exposing ``.record_trade(regime, pnl,
    confidence, strategy, hold_hours=0.0, metadata=None)`` -- matches
    ``feedback.regime_feedback.RegimeFeedbackManager``.
  - ``confidence_floor``: anything exposing ``.record_outcome(confidence,
    win, pnl, strategy="", symbol="", regime="")`` -- matches
    ``feedback.adaptive_confidence.AdaptiveConfidenceFloor``.
  - ``hold_time_rules``: anything exposing ``.record_trade(regime,
    hold_hours, win, pnl)`` -- matches
    ``feedback.hold_time_rules.HoldTimeRuleManager``.
  - ``parameter_tuner``: anything exposing ``.record_trade_outcome(pnl)`` --
    matches ``feedback.parameter_tuner.ParameterTuner``.
  - ``feedback``: anything exposing ``.record_outcome(confidence, win, pnl,
    strategy, symbol, regime, side, entry_type, num_agree, hold_time_s,
    exit_action, leverage, llm_action, llm_confidence, llm_agreed)`` --
    matches ``feedback.loop.FeedbackLoop``. NOT the same collaborator as
    accounting-tier's fields; this is the god-block's ``self.feedback``
    (signal-quality-adjacent feedback loop), unrelated to
    ``feedback.signal_quality.SignalQualityScorer`` (that scorer's
    ``record_outcome`` call was already dead code removed by
    FEEDBACK_RECORD_FIX per multi_strategy_main.py's comment at the
    god-block source -- nothing to extract for it).
  - ``ic_tracker``: anything exposing ``.record(factor, predicted_direction,
    actual_return)`` -- matches ``feedback.ic_tracker.ICTracker``.
    (``kelly_engine`` above is reused, not duplicated, for the Kelly
    subscriber -- see close_subscribers_learning.py's ``on_close_kelly``.)
  - ``graduated_rules_engine``: optional, anything exposing
    ``.record_outcome(symbol, regime, side, won, hour_utc,
    strategies_active, num_agree, confidence)`` -- matches
    ``llm.graduated_rules.GraduatedRulesEngine``. ``None`` means "use the
    real process-wide singleton" (resolved lazily via
    ``llm.graduated_rules.get_graduated_rules_engine()`` inside the
    subscriber, mirroring the ``_default_*`` lazy-import pattern) so
    importing this module never drags in ``llm.graduated_rules`` eagerly.

LEARNING-TIER (T2) FIELDS, BATCH 2 (Phase 0.4-B, see
close_subscribers_learning2.py) -- ten MEMORY/ML/LEARNING terminal hooks:
  - ``deep_memory``: anything exposing ``.record_full_trade(trade_id,
    symbol, side, entry_price, exit_price, sl, tp1, tp2, confidence,
    leverage, regime, strategies_agreed, outcome, pnl, hold_time_s,
    exit_reason, llm_action="", llm_confidence=0.0, llm_reasoning="",
    entry_type="", setup_type="", btc_trend="", volume_ratio=0.0,
    funding_rate=0.0, atr=0.0)`` -- matches
    ``llm.deep_memory.DeepMemoryManager``. ``None`` means "skip" (matches
    the god-block's ``if _dm_pos:`` guard); no lazy default resolver here
    (unlike the T2-batch-1 singletons) because the god-block itself always
    has ``_DEEP_MEMORY_AVAILABLE`` gating this via an explicit collaborator,
    never re-fetches a singleton inline at the call site.
  - ``thesis_grader``: anything exposing ``.close_thesis(thesis_id,
    exit_price, pnl_pct, max_favorable=None, max_adverse=None,
    actual_hold_h=None)`` -- matches the ``llm.brain_wiring`` module itself
    (its ``close_thesis`` function). ``None`` means "use the real module"
    (resolved lazily via ``import llm.brain_wiring``).
  - ``post_trade_learner``: anything exposing
    ``.generate_immediate_lesson(trade_data: dict) -> Optional[str]`` and
    ``.apply_memory_update(update, *, symbol="", regime="")`` -- matches a
    thin wrapper over ``llm.post_trade_learner.generate_immediate_lesson``
    + ``llm.memory_store.apply_memory_update``. ``None`` means "skip"
    (matches the god-block's bare ``try/except`` around this whole section
    having no separate availability gate of its own -- tests should treat
    "not configured" as the off switch here).
  - ``reflection``: anything exposing ``.on_close(symbol, side, entry_price,
    exit_price, pnl, hold_time_s, leverage, confidence, regime, exit_action,
    sl_price=0, tp1_price=0, peak_price=0, lowest_price=0, win_prob=0, ev=0,
    rr=0, entry_reasons=None, atr=0)`` -- matches
    ``llm.reflection_engine.ReflectionEngine``. ``None`` means "skip"
    (matches the god-block's ``if hasattr(self, '_reflection_engine') and
    self._reflection_engine is not None:`` guard).
  - ``autopsy``: optional, anything exposing ``.should_run_autopsy(count) ->
    bool`` and ``.generate_autopsy() -> str`` -- matches the
    ``llm.trade_autopsy`` module itself. ``None`` means "use the real
    module" (resolved lazily). See ``closed_trade_count`` below for the
    stateful cadence counter this collaborator needs.
  - ``learning_integrator``: optional, anything exposing
    ``.on_trade_closed(trade_data: dict)`` -- matches
    ``llm.learning_integrator.LearningIntegrator``. ``None`` means "use the
    real process-wide singleton" (resolved lazily via
    ``llm.learning_integrator.get_learning_integrator()``).
  - ``ml``: optional, anything exposing ``.record_outcome(TradeOutcome)`` --
    matches ``ml.learner.MLLearner``-shaped collaborator (the god-block's
    ``self.ml``). ``None`` means "skip" (matches the god-block's ``if
    self.ml and ...:`` guard). No lazy default -- this is a stateful,
    already-constructed learner instance on the bot, never a
    freshly-resolved singleton.
  - ``counterfactual``: optional, anything exposing
    ``.record_exit_alternative(symbol, actual_exit_action,
    actual_exit_price, tp1_price, tp2_price, entry_price, actual_pnl)`` --
    matches ``analytics.counterfactual.CounterfactualEngine`` (the
    god-block's ``self.counterfactual``). ``None`` means "skip" (matches
    the god-block's ``if self.counterfactual:`` guard).
  - ``log_signal_outcome_fn`` / ``rl_append_transition_fn``: optional
    injectable overrides of ``data.db.log_signal_outcome`` /
    ``rl.buffer.append_transition``. ``None`` means "use the real function"
    (resolved lazily by local import), same rationale as the accounting
    tier's ``log_trade_fn``-family fields.
  - ``risk_per_trade``: optional static config passthrough (NOT a live
    mutable read) -- the god-block's signal-outcome pnl_pct divides by
    ``self.config.risk_per_trade`` in addition to equity; threaded here so
    ``on_close_signal_outcome`` never has to reach into a bot config object.
  - ``llm_mode_name``: optional static config/state passthrough -- the
    god-block's RL buffer action dict reads ``self.llm_mode.name`` (current
    bot-level LLM autonomy mode, not a per-position value). ``None``
    defaults to ``""``.
  - ``closed_trade_count``: plain mutable ``int``, default 0. Mirrors the
    god-block's ``self._closed_trade_count`` -- a counter incremented on
    EVERY full close (not derivable from any single frozen event) that
    drives the autopsy subscriber's every-5-trades cadence. Lives on this
    long-lived, per-bot ``CloseCtx`` instance and is incremented in place by
    ``on_close_autopsy``, exactly like the god-block increments its own
    instance attribute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class CloseCtx:
    """Collaborator bundle for the six accounting-tier close subscribers.

    Only ``risk_mgr`` is required -- every other field is optional so tests
    can construct a minimal ``CloseCtx`` and only wire in the collaborator(s)
    the subscriber under test actually needs.
    """

    risk_mgr: Any

    trade_ledger: Optional[Any] = None
    trade_logger: Optional[Any] = None
    kelly_engine: Optional[Any] = None

    source: Optional[Any] = None

    log_trade_fn: Optional[Callable[..., None]] = None
    record_trade_outcome_fn: Optional[Callable[..., None]] = None
    log_closed_trade_fn: Optional[Callable[..., None]] = None

    # ---- LEARNING-TIER (T2) collaborators, Phase 0.4-B batch 1 -- see the
    # module docstring's "LEARNING-TIER (T2) FIELDS" section for each
    # collaborator's expected duck-type. All optional so tests only wire in
    # what the subscriber under test actually needs.
    weight_mgr: Optional[Any] = None
    regime_feedback: Optional[Any] = None
    confidence_floor: Optional[Any] = None
    hold_time_rules: Optional[Any] = None
    parameter_tuner: Optional[Any] = None
    feedback: Optional[Any] = None
    ic_tracker: Optional[Any] = None
    graduated_rules_engine: Optional[Any] = None

    # ---- LEARNING-TIER (T2) collaborators, Phase 0.4-B batch 2 -- see the
    # module docstring's "LEARNING-TIER (T2) FIELDS, BATCH 2" section for
    # each collaborator's expected duck-type. All optional so tests only
    # wire in what the subscriber under test actually needs.
    deep_memory: Optional[Any] = None
    thesis_grader: Optional[Any] = None
    post_trade_learner: Optional[Any] = None
    reflection: Optional[Any] = None
    autopsy: Optional[Any] = None
    learning_integrator: Optional[Any] = None
    ml: Optional[Any] = None
    counterfactual: Optional[Any] = None

    log_signal_outcome_fn: Optional[Callable[..., Any]] = None
    rl_append_transition_fn: Optional[Callable[..., Any]] = None

    risk_per_trade: Optional[float] = None
    llm_mode_name: Optional[str] = None
    closed_trade_count: int = 0
