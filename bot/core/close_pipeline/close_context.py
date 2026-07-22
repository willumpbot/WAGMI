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
  - ``journal_booked_fn``: optional injectable override of
    ``core.position_journal.journal_booked`` -- the write-ahead-journal
    "CLOSED_BOOKED" stamp ``on_close_ledger`` writes AFTER the ledger row
    succeeds (Phase 0.3b safety net; see position_journal.py's module
    docstring). ``None`` means "use the real production
    ``core.position_journal.journal_booked``" (resolved lazily, by local
    import, inside ``on_close_ledger`` -- same lazy-default pattern as
    ``log_trade_fn``/``record_trade_outcome_fn``/``log_closed_trade_fn``
    above), so PROD/flip behavior is UNCHANGED and the god-block's
    crash-recovery safety net (startup_reconcile's "unbooked" detection)
    stays intact once the close pipeline becomes authoritative. Shadow
    wiring MUST inject a recorder here (never the real function) -- the
    real ``journal_booked`` writes to the REAL, ``__file__``-anchored
    ``data/position_journal.jsonl`` regardless of any ``data_dir`` override
    passed elsewhere, so leaving this ``None`` in a shadow ``CloseCtx``
    would (a) write outside ``data/shadow/`` and (b) in a god-block-ledger-
    write-FAILED scenario, wrongly stamp CLOSED_BOOKED into the real
    journal for a close the real ledger never recorded -- masking a lost
    close from crash recovery. See shadow_close_wiring.py's module
    docstring for the full hazard writeup.

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

MISC-TIER (T2 + T3) FIELDS, BATCH 3 (Phase 0.4-B, see
close_subscribers_misc.py) -- the remaining T3 fire-and-forget/misc
subscribers plus the four explicitly-T2 "derived reader" ones (adaptive_risk,
adaptive_sizer, shadow_ledger, continuous_backtest -- per the extraction
mandate's tiering note). All optional, ``None``/empty default means "skip",
matching each god-block call site's own availability guard:
  - ``adaptive_risk``: anything exposing ``.record_outcome(win, regime="")``
    -- matches ``execution.adaptive_risk.AdaptiveRisk`` (the god-block's
    ``self.adaptive_risk``).
  - ``adaptive_sizer``: anything exposing ``.record_outcome(symbol, won)``
    -- matches ``execution.adaptive_risk.AdaptiveSizer`` (the god-block's
    ``execution.adaptive_risk.get_adaptive_sizer(self.config)`` singleton).
    ``None`` resolves lazily via ``get_adaptive_sizer()`` (no config arg --
    the process-wide singleton is already configured by bot init time).
  - ``shadow_ledger``: anything exposing ``.resolve_shadows(symbol,
    exit_price)`` -- matches ``feedback.shadow_ledger.ShadowLedger``.
  - ``continuous_backtest``: anything exposing ``.record_outcome(symbol,
    win, pnl, confidence_at_entry, strategy, regime="", hold_time_s=0,
    exit_action="", leverage=1.0)`` -- matches
    ``feedback.continuous_backtest.ContinuousBacktest``.
  - ``llm_triggers``: anything exposing ``.record_trade_outcome(strategy,
    entry_type, win)`` and ``.add(trigger, symbol="", context="")`` --
    matches ``llm.triggers`` module's trigger tracker (the god-block's
    ``self._llm_triggers``). Two DISTINCT god-block call sites use this one
    collaborator's two different methods (see on_close_llm_triggers_outcome
    / on_close_llm_triggers_notify below).
  - ``quant_brain``: optional, anything exposing ``.record_outcome(symbol,
    won)`` -- matches ``llm.quant_brain.QuantBrain`` (the god-block's
    ``self._quant_brain``, chase-prevention outcome tracking).
  - ``regime_strategy_weighter``: optional, anything exposing
    ``.record_outcome(regime, strategy, won)`` -- matches the god-block's
    ``self._regime_strategy_weighter``. NOTE: the module this collaborator
    would be constructed from (``data.regime_strategy_weighter``) does not
    exist anywhere in the current tree, so the god-block's own init wraps
    construction in a ``try/except`` that always fails today, leaving
    ``self._regime_strategy_weighter`` permanently ``None`` in production
    -- this field faithfully reproduces that "always None today" duck-typed
    seam, not a bug this extraction introduces.
  - ``growth``: optional, anything exposing ``.on_trade_closed(dict)`` --
    matches ``llm.growth.orchestrator``'s growth intelligence orchestrator
    (the god-block's ``self.growth``).
  - ``ab_manager``: optional, anything exposing ``.get_active_experiments()
    -> List[Experiment]`` (each with ``.id``), ``.get_assignment(exp_id,
    symbol, trace_id) -> str``, and ``.record_outcome(experiment_id, group,
    symbol, pnl, win, metadata=None)`` -- matches
    ``analytics.ab_testing.ABTestManager`` (the god-block's
    ``self.ab_manager``).
  - ``agent_perf``: optional, anything exposing ``.record_outcome(symbol,
    pnl, entry_time, exit_time, mfe_pct, mae_pct, side)`` -- matches the
    god-block's ``self._agent_perf`` (from
    ``llm.agents.agent_performance.get_tracker()``, multi_strategy_main.py
    :822-823). F1 CORRECTION: an earlier pass of this audit claimed the
    real ``AgentPerformanceTracker`` class exposes no ``record_outcome``
    method -- that check hit the WRONG module
    (``llm.agents.performance_tracker``, which happens to also define a
    class named ``AgentPerformanceTracker`` but is NOT the one the
    god-block actually constructs). The class the god-block really uses,
    ``llm.agents.agent_performance.AgentPerformanceTracker``, DOES define
    ``record_outcome(symbol, pnl, entry_time, exit_time, mfe_pct, mae_pct,
    side)`` (agent_performance.py:86-94) -- a real, live method that
    persists its result. This call site is NOT dead code; a real
    ``AgentPerformanceTracker`` instance wired in here reproduces the
    identical real, persisting behavior seen live today.
  - ``cost_optimizer``: optional, anything exposing
    ``.record_outcome(pipeline_type, pnl)`` -- matches
    ``llm.agents.cost_optimizer.AgentCostOptimizer`` (the god-block's
    ``self._cost_optimizer``).
  - ``risk_telemetry``: optional, anything exposing ``.update(equity,
    daily_pnl)`` -- matches ``risk.self_tuning.RiskTelemetry`` (the
    god-block's ``self.risk_telemetry``).
  - ``telemetry_cls``: optional, a ``Telemetry``-shaped class/object
    exposing classmethods ``.inc(key)`` / ``.record(key, value)`` --
    matches ``data.fetchers.telemetry.Telemetry``. ``None`` resolves
    lazily to the real module-level class (a process-wide counters
    singleton, not a live position/equity read -- safe to import lazily).
  - ``alerts``: optional, anything exposing ``.send_trade_event(action,
    symbol, message)`` -- matches the god-block's ``self.alerts``.
  - ``format_trade_event_fn``: optional injectable override of
    ``alerts.enhanced_telegram.format_trade_event_telegram``. ``None``
    means "use the real function" (resolved lazily by local import).
  - ``survival_record_outcome_fn``: optional injectable override of
    ``llm.survival_pressure.record_trade_outcome``. ``None`` resolves
    lazily; an ``ImportError`` on that lazy resolve is swallowed (mirrors
    the god-block's own ``_SURVIVAL_PRESSURE_AVAILABLE`` import-time gate).
  - ``learning_mode_active_fn`` / ``learning_mode_record_fn``: optional
    injectable overrides of ``llm.learning_mode.is_learning_mode_active`` /
    ``.record_trade_observed``. ``None`` resolves both lazily together (an
    ``ImportError`` on either is swallowed, mirroring
    ``_LEARNING_MODE_AVAILABLE``).
  - ``add_observation_fn``: optional injectable override of
    ``llm.strategy_discovery.corpus.add_observation``. ``None`` resolves
    lazily.
  - ``symbol_cooldown`` / ``symbol_daily_pnl`` / ``symbol_daily_pnl_date`` /
    ``symbol_daily_loss_limit`` / ``last_close_win`` / ``last_close_side``:
    plain mutable per-symbol dicts (+ a date string, + a static float
    threshold), mirroring the god-block's own
    ``self._symbol_cooldown`` / ``self._symbol_daily_pnl`` /
    ``self._symbol_daily_pnl_date`` / ``self._symbol_daily_loss_limit`` /
    ``self._last_close_win`` / ``self._last_close_side`` instance
    attributes -- same "stateful, lives on the long-lived per-bot CloseCtx"
    pattern as ``closed_trade_count`` above, mutated in place by
    ``on_close_cooldown_tracking``.

LLM-LEARNING-AGENT (T3) FIELDS, PHASE 0.4-B FINAL BATCH (see
close_subscribers_llm_learning_agent.py) -- the last remaining god-block
subscriber, deliberately deferred by every prior batch because it makes a
LIVE LLM call (``claude -p`` via the multi-agent coordinator, never an API
key -- see CLI-routing convention):
  - ``learning_agent_fn``: optional, anything with the signature
    ``(trade_data: Dict[str, Any]) -> Optional[Dict[str, Any]]`` -- matches
    ``llm.agents.coordinator.get_coordinator().get_post_trade_lesson``
    (bound method). ``None`` means "use the real process-wide coordinator
    singleton" (resolved lazily via ``llm.agents.coordinator.
    get_coordinator()`` inside the subscriber, mirroring the
    ``graduated_rules_engine``/``learning_integrator`` lazy-singleton
    pattern) so importing this module never drags in the coordinator (and
    therefore the LLM client) eagerly. Tests MUST pass a ``Mock`` here --
    never let the real resolver run -- so no test can ever make a live LLM
    call.
  - ``process_agent_lesson_fn``: optional, anything with the signature
    ``(lesson_data: Dict[str, Any], trade_data: Dict[str, Any]) -> None`` --
    matches ``llm.agents.learning_integration.process_agent_lesson``.
    ``None`` means "use the real module-level function" (resolved lazily by
    local import), same rationale as the accounting tier's
    ``log_trade_fn``-family fields.
  - ``llm_multi_agent_enabled``: optional static gate passthrough mirroring
    the god-block's own ``os.getenv("LLM_MULTI_AGENT", "").lower() in ("1",
    "true", "yes")`` check at multi_strategy_main.py:4394 (re-read at every
    close, not cached) -- reading an env var directly is not a "live
    mutable per-position value" the extraction mandate forbids (it is
    process-wide static config, same class as ``risk_per_trade`` /
    ``llm_mode_name`` above), so this field is threaded through rather than
    read as a bare ``os.getenv`` inside the subscriber. ``None`` means
    "resolve ``LLM_MULTI_AGENT`` from the environment the same way the
    god-block does" (lazy default); tests set this explicitly (``True`` /
    ``False``) so the gate is exercised deterministically without depending
    on process environment state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


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
    journal_booked_fn: Optional[Callable[..., None]] = None

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

    # ---- MISC-TIER (T2 + T3) collaborators, Phase 0.4-B batch 3 -- see the
    # module docstring's "MISC-TIER (T2 + T3) FIELDS, BATCH 3" section for
    # each collaborator's expected duck-type. All optional so tests only
    # wire in what the subscriber under test actually needs.
    adaptive_risk: Optional[Any] = None
    adaptive_sizer: Optional[Any] = None
    shadow_ledger: Optional[Any] = None
    continuous_backtest: Optional[Any] = None
    llm_triggers: Optional[Any] = None
    quant_brain: Optional[Any] = None
    regime_strategy_weighter: Optional[Any] = None
    growth: Optional[Any] = None
    ab_manager: Optional[Any] = None
    agent_perf: Optional[Any] = None
    cost_optimizer: Optional[Any] = None
    risk_telemetry: Optional[Any] = None
    telemetry_cls: Optional[Any] = None
    alerts: Optional[Any] = None

    format_trade_event_fn: Optional[Callable[..., str]] = None
    survival_record_outcome_fn: Optional[Callable[..., None]] = None
    learning_mode_active_fn: Optional[Callable[[], bool]] = None
    learning_mode_record_fn: Optional[Callable[..., None]] = None
    add_observation_fn: Optional[Callable[..., None]] = None

    symbol_cooldown: Dict[str, float] = field(default_factory=dict)
    symbol_daily_pnl: Dict[str, float] = field(default_factory=dict)
    symbol_daily_pnl_date: Optional[str] = None
    symbol_daily_loss_limit: float = float("-inf")
    last_close_win: Dict[str, bool] = field(default_factory=dict)
    last_close_side: Dict[str, str] = field(default_factory=dict)

    # ---- LLM-LEARNING-AGENT (T3) collaborators, Phase 0.4-B FINAL batch --
    # see the module docstring's "LLM-LEARNING-AGENT (T3) FIELDS" section.
    # All optional; ``None`` means "resolve the real production
    # collaborator lazily" for the two callables, and "read LLM_MULTI_AGENT
    # from the environment" for the gate flag.
    learning_agent_fn: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None
    process_agent_lesson_fn: Optional[Callable[[Dict[str, Any], Dict[str, Any]], None]] = None
    llm_multi_agent_enabled: Optional[bool] = None
