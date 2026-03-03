"""
Main entry point for the multi-strategy auto-trading bot.
Wires together all components: data fetcher, strategies, ensemble,
position management, leverage, risk, ML, and alerts.

Usage:
    python multi_strategy_main.py           # Paper trading (default)
    ENVIRONMENT=production python multi_strategy_main.py  # Live trading
"""

import logging
import os
import signal
import sys
import time
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

import pandas as pd

from data.fetcher import DataFetcher
from data.db import (
    init_db, log_signal, log_trade, log_equity, get_daily_summary,
    update_signal_traded, log_signal_outcome, log_health_event,
    update_daily_performance, get_signal_performance, get_recent_trades,
)
from data.strategy_weights import StrategyWeightManager
from data.risk_log import log_rejection, get_rejection_counts
from data.ml_log import log_ml_stats, log_ml_confidence
from data.trade_log import log_closed_trade
from data.learning import record_trade_outcome, get_performance
from trading_config import TradingConfig, DEFAULT_SYMBOLS, apply_profile, get_symbol_param
from strategies.regime_trend import RegimeTrendStrategy
from strategies.monte_carlo_zones import MonteCarloZonesStrategy
from strategies.confidence_scorer import ConfidenceScorerStrategy
from strategies.multi_tier_quality import MultiTierQualityStrategy
from strategies.ensemble import EnsembleStrategy
from execution.position_manager import PositionManager
from execution.leverage import LeverageManager
from execution.risk import RiskManager, CircuitBreaker
from execution.trade_logger import TradeLogger
from ml.learner import SignalLearner, TradeOutcome, MarketSnapshot
from alerts.router import AlertRouter
from alerts.telegram_bot import TelegramCommandBot
from execution.trade_profile import classify_trade, apply_profile_to_signal
from execution.precision import validate_fill_price, get_min_qty, get_max_leverage, get_all_symbol_specs

# LLM meta-brain
from llm.autonomy import LLMMode, get_llm_mode, should_call_llm, llm_has_veto, describe_mode
from llm.decision_engine import get_trading_decision, DecisionResult
from llm.decision_types import (
    StrategySignal as LLMStrategySignal,
    MarketSnapshot as LLMMarketSnapshot,
    GlobalContext as LLMGlobalContext,
)
from llm.risk_gating import RiskContext as LLMRiskContext
from llm.triggers import LLMTrigger, TriggerAccumulator, TRIGGER_LABELS
from execution.candidate import TradeCandidate, CandidateLogger
from execution.reconciliation import (
    reconcile_positions,
    save_circuit_breaker_state,
    restore_circuit_breaker_state,
    periodic_reconciliation_check,
)
from execution.time_sizing import get_time_multiplier
from execution.ops_guard import OpsGuard
from execution.rotation_manager import RotationManager, RotationConfig
from data.fetchers.telemetry import Telemetry

# Feedback loop system
from feedback.loop import FeedbackLoop
from feedback.signal_quality import QualityFeatures

# Signal ingestion pipeline
from signals.telegram_ingest import TelegramSignalMonitor, IngestedSignal
from signals.llm_analyzer import analyze_signal, format_analysis_for_telegram

# Growth intelligence — self-evolving meta-brain
from llm.growth.orchestrator import get_growth_orchestrator

# LLM exit engine — dynamic SL/TP management for open positions
try:
    from llm.exit_engine import ExitEngine
    from llm.exit_types import ExitDecision
    _EXIT_ENGINE_AVAILABLE = True
except ImportError:
    _EXIT_ENGINE_AVAILABLE = False

# Feedback loop closers — self-performance, veto tracking, cost, operator channel
from llm.veto_tracker import get_veto_tracker
from llm.cost_tracker import get_cost_tracker
from llm.operator_channel import get_operator_channel
from llm.self_performance import get_performance_stats

# Wave 1: Signal Flagger — cheap heuristic flags for LLM attention routing
try:
    from llm.signal_flagger import get_signal_flagger, FlagType, FlaggedSignal
    _SIGNAL_FLAGGER_AVAILABLE = True
except ImportError:
    _SIGNAL_FLAGGER_AVAILABLE = False

# Wave 1: Signal Override — bypass soft blockers for powerful signals
try:
    from llm.signal_override import (
        should_override_blocker, BlockerType, get_override_engine,
    )
    _SIGNAL_OVERRIDE_AVAILABLE = True
except ImportError:
    _SIGNAL_OVERRIDE_AVAILABLE = False

# Wave 1: Self-Teaching — periodic learning cycles + knowledge injection
try:
    from llm.self_teaching import get_teaching_engine
    _SELF_TEACHING_AVAILABLE = True
except ImportError:
    _SELF_TEACHING_AVAILABLE = False

# Wave 2: Liquidity Guard — pre-trade market health validation
try:
    from execution.liquidity_guard import validate_liquidity
    _LIQUIDITY_GUARD_AVAILABLE = True
except ImportError:
    _LIQUIDITY_GUARD_AVAILABLE = False

# Phase D+E+F: new modules
from execution.funding_timer import should_close_before_funding, minutes_until_next_funding
from strategies.regime_detector import RegimeTransitionDetector
from monitoring.health import HealthMonitor
from execution.graceful_degradation import DegradationManager

# Watchdog: background health monitoring with stall detection and auto-alerts
from monitoring.watchdog import get_watchdog

# Enhanced Telegram alerts: actionable signal formatting
from alerts.enhanced_telegram import (
    format_signal_telegram, format_trade_event_telegram,
    format_heartbeat_telegram, format_daily_report_telegram,
)

# Global Brain + Portfolio Brain: cross-market reasoning for LLM
from llm.global_brain import build_global_context, apply_global_bias
from llm.portfolio_brain import build_portfolio_snapshot

# Self-Tuning Risk Engine: adaptive risk profiles
from risk.self_tuning import (
    get_telemetry as get_risk_telemetry,
    evaluate_and_adjust as risk_evaluate_and_adjust,
    get_dynamic_leverage_cap,
    get_profile_params as get_risk_profile_params,
)

# RL system: transition logging + policy application
from rl.buffer import append_transition as rl_append_transition
from rl.apply_policy import get_combined_rl_multiplier, is_rl_enabled

# Deep memory + cross-symbol pattern tracking
try:
    from llm.deep_memory import get_deep_memory, TradeDNA
    _DEEP_MEMORY_AVAILABLE = True
except ImportError:
    _DEEP_MEMORY_AVAILABLE = False

try:
    from strategies.cross_symbol_patterns import CrossSymbolTracker
    _CROSS_SYMBOL_AVAILABLE = True
except ImportError:
    _CROSS_SYMBOL_AVAILABLE = False

# Survival Pressure: performance accountability injected into LLM context
try:
    from llm.survival_pressure import (
        record_trade_outcome as survival_record_outcome,
        get_survival_context_for_llm,
        get_survival_report,
    )
    _SURVIVAL_PRESSURE_AVAILABLE = True
except ImportError:
    _SURVIVAL_PRESSURE_AVAILABLE = False

# Learning Mode: progressive LLM autonomy (ABSORB -> APPRENTICE -> ACTIVE)
try:
    from llm.learning_mode import (
        is_learning_mode_active,
        get_current_phase,
        record_signal_observed as learning_record_signal,
        record_trade_observed as learning_record_trade,
        record_counterfactual,
        apply_learning_constraints,
        get_learning_report,
        LearningPhase,
    )
    _LEARNING_MODE_AVAILABLE = True
except ImportError:
    _LEARNING_MODE_AVAILABLE = False

# Autonomy Progression: gate-based mode advancement (VETO_ONLY -> SIZING -> DIRECTION -> FULL)
try:
    from llm.progression import evaluate_progression, format_progression_status
    _PROGRESSION_AVAILABLE = True
except ImportError:
    _PROGRESSION_AVAILABLE = False

# Uplift Analytics: baseline vs LLM-filtered performance comparison
try:
    from llm.uplift_analytics import compute_uplift, format_uplift_report
    _UPLIFT_AVAILABLE = True
except ImportError:
    _UPLIFT_AVAILABLE = False

# Adaptive Risk: dynamic risk-per-trade based on streak and regime
try:
    from execution.adaptive_risk import get_adaptive_risk
    _ADAPTIVE_RISK_AVAILABLE = True
except ImportError:
    _ADAPTIVE_RISK_AVAILABLE = False

# Strategy Pruning: auto-reduce weights for underperforming strategies
try:
    from execution.strategy_pruning import evaluate_and_adjust as pruning_evaluate, get_strategy_weight
    _STRATEGY_PRUNING_AVAILABLE = True
except ImportError:
    _STRATEGY_PRUNING_AVAILABLE = False

# Human Copy-Trade Classifier: gate for copy-tradable signal publication
try:
    from classification.human_copy_classifier import classify_human_copy_tradable, CopyTradeResult
    _COPY_CLASSIFIER_AVAILABLE = True
except ImportError:
    _COPY_CLASSIFIER_AVAILABLE = False

# LLM Self-Performance: rolling accuracy stats for self-calibration
try:
    from llm.self_performance import get_compact_stats as get_llm_self_stats
    _SELF_PERF_AVAILABLE = True
except ImportError:
    _SELF_PERF_AVAILABLE = False

# Wave 3: Portfolio Risk Engine — correlation matrix, vol forecasting, risk budgeting
try:
    from analytics.portfolio_risk import get_portfolio_risk_engine
    _PORTFOLIO_RISK_AVAILABLE = True
except ImportError:
    _PORTFOLIO_RISK_AVAILABLE = False

# Wave 4: Performance Attribution — which decisions actually made money
try:
    from analytics.attribution import compute_attribution, format_attribution_report
    _ATTRIBUTION_AVAILABLE = True
except ImportError:
    _ATTRIBUTION_AVAILABLE = False

# Wave 4: A/B Testing — live strategy variant testing
try:
    from analytics.ab_testing import get_ab_manager
    _AB_TESTING_AVAILABLE = True
except ImportError:
    _AB_TESTING_AVAILABLE = False

# Wave 4: Counterfactual Learning — what-if analysis for vetoes and sizing
try:
    from analytics.counterfactual import get_counterfactual_engine
    _COUNTERFACTUAL_AVAILABLE = True
except ImportError:
    _COUNTERFACTUAL_AVAILABLE = False

# Wave 4: Meta-Learning — pattern analysis and strategy idea generation
try:
    from analytics.meta_learning import get_meta_engine
    _META_LEARNING_AVAILABLE = True
except ImportError:
    _META_LEARNING_AVAILABLE = False

# Web Dashboard: visual monitoring
try:
    from dashboard.server import get_dashboard_server
    _DASHBOARD_AVAILABLE = True
except ImportError:
    _DASHBOARD_AVAILABLE = False


def get_tp1_close_pct(confidence: float) -> float:
    """Legacy confidence-based TP1 close percentage.
    Now superseded by TradeProfile for live trading, but kept for
    backward compat (backtest engine, tests).
    Lower confidence = lock in more profit. Higher = let more ride."""
    if confidence < 70:
        return 1.00
    elif confidence < 85:
        return 0.70
    elif confidence < 92:
        return 0.50
    else:
        return 0.30


def _fmt_price(price: float) -> str:
    """Format price with appropriate precision (handles micro-prices like PEPE)."""
    if price == 0:
        return "0"
    abs_p = abs(price)
    if abs_p >= 1.0:
        return f"{price:,.2f}"
    elif abs_p >= 0.001:
        return f"{price:.4f}"
    elif abs_p >= 0.000001:
        return f"{price:.8f}"
    else:
        return f"{price:.12f}"


# Setup structured logging with rotating file handler
from core.structured_logging import setup_logging, log_trade_event, log_metric

_is_production = os.getenv("ENVIRONMENT", "paper").lower() == "production"
setup_logging(
    json_mode=_is_production,
    level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir="logs",
)
logger = logging.getLogger("bot.main")


class MultiStrategyBot:
    """
    The main bot that orchestrates everything.

    Loop:
    1. Fetch data for all symbols
    2. Run ensemble evaluation
    3. ML-adjust confidence
    4. Determine leverage
    5. Open positions if signal passes filters
    6. Update existing positions (TP/SL/trailing)
    7. Record outcomes for ML learning
    8. Send alerts
    9. Sleep and repeat
    """

    def __init__(self, config: TradingConfig):
        self.config = config
        self.stop_event = threading.Event()

        # Apply paper/live profile overrides (caps leverage, risk, etc.)
        apply_profile(config)

        # Data
        self.fetcher = DataFetcher(
            max_retries=config.fetcher_max_retries,
            retry_delay=5.0,
            cache_ttl=max(30, config.scan_interval_s - 5),
            cb_threshold=config.fetcher_circuit_breaker_threshold,
            cb_reset_s=config.fetcher_circuit_breaker_reset_s,
        )

        # Strategy accuracy weights
        self.weight_mgr = StrategyWeightManager(
            path="ml_data/strategy_weights.json",
            decay_alpha=0.9,
        )

        # Strategies (pass config params to constructors)
        sym_configs = DEFAULT_SYMBOLS
        self.strategies = [
            RegimeTrendStrategy(sym_configs, config.htf_hours),
            MonteCarloZonesStrategy(
                sym_configs,
                mc_sims=config.mc_num_sims,
                mc_hours=config.mc_forward_hours,
            ),
            ConfidenceScorerStrategy(sym_configs, data_dir="ml_data"),
            MultiTierQualityStrategy(sym_configs),
        ]
        # Chop detector: multi-factor choppy market filter
        chop = None
        if config.enable_chop_detector:
            try:
                from strategies.chop_detector import ChopDetector
                chop = ChopDetector(threshold=config.chop_threshold)
                logger.info(f"[INIT] Chop detector enabled (threshold={config.chop_threshold})")
            except Exception as e:
                logger.warning(f"[INIT] Chop detector init failed: {e}")

        self.ensemble = EnsembleStrategy(
            strategies=self.strategies,
            mode=config.ensemble_mode,
            min_votes=config.min_votes_required,
            weight_manager=self.weight_mgr,
            veto_ratio=config.veto_ratio,
            chop_detector=chop,
            confidence_floor=config.ensemble_confidence_floor,
        )

        # Execution
        self.risk_mgr = RiskManager(
            starting_equity=config.starting_equity,
            risk_per_trade=config.risk_per_trade,
            max_open_positions=config.max_open_positions,
            circuit_breaker=CircuitBreaker(
                daily_loss_limit_pct=config.circuit_breaker_daily_loss_pct,
                max_consecutive_losses=config.max_consecutive_losses,
                cooldown_minutes=config.circuit_breaker_cooldown_min,
            ),
        )
        self.pos_mgr = PositionManager(
            taker_fee_bps=config.taker_fee_bps,
            enable_trailing=config.enable_trailing_stop,
            trailing_atr_mult=config.trailing_stop_atr_mult,
        )
        self.leverage_mgr = LeverageManager(
            enable_leverage=config.enable_leverage,
            max_leverage=config.max_leverage,
        )

        # ML
        self.ml = SignalLearner(
            data_dir="ml_data",
            min_samples=config.ml_min_samples,
            retrain_interval=config.ml_retrain_interval,
            adjustment_weight=config.ml_adjustment_weight,
        ) if config.enable_ml else None

        # Alerts
        self.alerts = AlertRouter(
            discord_webhook=config.discord_webhook,
            telegram_token=config.telegram_token,
            telegram_chat_id=config.telegram_chat_id,
        )

        # Trade logging (paper trading validation)
        self.trade_logger = TradeLogger(log_dir="paper_trades") if not config.auto_trade else None

        self._tick = 0
        self._needed_tfs = self.ensemble.get_all_required_timeframes()

        # Per-symbol cooldown: prevent rapid re-entry after a position closes
        self._symbol_cooldown: Dict[str, float] = {}  # symbol -> timestamp of last close
        self._cooldown_seconds = config.loss_cooldown_s
        self._win_cooldown_seconds = config.win_cooldown_s

        # Correlation guard: prevent correlated blowups
        self._max_same_direction = int(os.getenv("MAX_SAME_DIRECTION", "3"))
        self._max_same_tier = int(os.getenv("MAX_SAME_TIER", "2"))

        # Track last close result per symbol for anti-round-tripping
        self._last_close_win: Dict[str, bool] = {}  # symbol -> was_win
        self._last_close_side: Dict[str, str] = {}  # symbol -> "LONG"/"SHORT"

        # Signal dedup: prevent spam from repeated same-side evaluations
        self._last_signal: Dict[str, tuple] = {}  # symbol -> (side, timestamp)
        self._signal_dedup_seconds = config.signal_dedup_window_s

        # Last known prices for fill-price validation
        self._last_prices: Dict[str, float] = {}  # symbol -> price
        # Last known funding rates per symbol (updated from fetcher)
        self._last_funding_rates: Dict[str, float] = {}  # symbol -> funding rate

        # LLM meta-brain
        self.llm_mode = get_llm_mode()
        self._llm_triggers = TriggerAccumulator()

        # Dual-world candidate logging (baseline vs LLM)
        self._candidate_logger = CandidateLogger()

        # Operations guard: kill switch, rate limiting, exposure limits
        self.ops_guard = OpsGuard()

        # Trade rotation manager: rotate stale/losing positions into better signals
        if config.enable_rotation:
            self.rotation_mgr = RotationManager(RotationConfig(
                min_hold_before_rotation_s=config.rotation_min_hold_s,
                global_rotation_cooldown_s=config.rotation_global_cooldown_s,
                max_rotations_per_hour=config.rotation_max_per_hour,
                max_rotations_per_day=config.rotation_max_per_day,
                estimated_round_trip_fee_pct=config.taker_fee_bps / 100.0,  # bps -> %
            ))
        else:
            self.rotation_mgr = None

        # Feedback loop: self-improving confidence, backtesting, quality scoring
        self.feedback = FeedbackLoop(data_dir="data/feedback")

        # Growth intelligence: self-evolving meta-brain
        self.growth = get_growth_orchestrator()

        # Operator channel: LLM → operator communication via Telegram
        self.operator_channel = get_operator_channel(alert_router=self.alerts)

        # Wave 1: Signal Flagger — cheap heuristic flags for every signal
        self.signal_flagger = get_signal_flagger() if _SIGNAL_FLAGGER_AVAILABLE else None

        # Wave 1: Signal Override — bypass soft blockers for powerful signals
        self.signal_override = get_override_engine() if _SIGNAL_OVERRIDE_AVAILABLE else None

        # Wave 1: Self-Teaching — periodic learning cycles
        self.teaching_engine = get_teaching_engine() if _SELF_TEACHING_AVAILABLE else None

        # Seed knowledge base with foundational axioms (idempotent — skips if already seeded)
        if self.teaching_engine:
            try:
                from llm.knowledge_seed import seed_knowledge_base
                seed_knowledge_base()
            except Exception as e:
                logger.debug(f"Knowledge seed error (non-fatal): {e}")

        # Veto tracker: counterfactual validation for LLM vetoes
        self.veto_tracker = get_veto_tracker()

        # Phase D+E+F: new subsystems
        self.regime_detector = RegimeTransitionDetector()
        self.health_monitor = HealthMonitor()
        self.degradation = DegradationManager()

        # LLM exit engine: dynamic SL/TP management for open positions
        if _EXIT_ENGINE_AVAILABLE:
            self.exit_engine = ExitEngine()
            logger.info("[INIT] LLM exit engine loaded")
        else:
            self.exit_engine = None
            logger.warning("[INIT] LLM exit engine unavailable — running without dynamic exits")
        self._exit_check_counter = 0

        # Cross-symbol pattern tracker: detects lead-lag relationships
        self.cross_symbol_tracker = CrossSymbolTracker() if _CROSS_SYMBOL_AVAILABLE else None

        # Track 1h price changes for cross-market divergence detection
        self._price_changes_1h: Dict[str, float] = {}

        # Self-tuning risk engine: adaptive profiles based on equity curve
        self.risk_telemetry = get_risk_telemetry()

        # Adaptive risk: dynamic risk-per-trade based on streak and regime
        self.adaptive_risk = get_adaptive_risk() if _ADAPTIVE_RISK_AVAILABLE else None

        # Cache global bias from Global Brain (updated each LLM context build)
        self._global_bias: str = "neutral"
        self._global_bias_adjustment: Dict[str, Any] = {}

        # Telegram command bot
        tg_user_id = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))
        self.telegram_bot = TelegramCommandBot(
            token=config.telegram_token,
            allowed_user_id=tg_user_id,
            bot_instance=self,
        )

        # Telegram signal ingestion pipeline
        self.signal_monitor = TelegramSignalMonitor(
            on_signal=self._handle_ingested_signal,
        )

        # Watchdog: background health monitoring with stall detection
        self.watchdog = get_watchdog(
            alert_fn=self.alerts.send_market_update if self.alerts else None,
        )

        # Wave 3: Portfolio Risk Engine — correlation, vol forecasting, risk budgeting
        self.portfolio_risk = get_portfolio_risk_engine() if (
            _PORTFOLIO_RISK_AVAILABLE and config.enable_portfolio_risk
        ) else None

        # Wave 4: A/B Testing — live strategy variant testing
        self.ab_manager = get_ab_manager() if (
            _AB_TESTING_AVAILABLE and config.enable_ab_testing
        ) else None

        # Wave 4: Counterfactual Learning — what-if veto and sizing analysis
        self.counterfactual = get_counterfactual_engine() if (
            _COUNTERFACTUAL_AVAILABLE and config.enable_counterfactual
        ) else None

        # Wave 4: Meta-Learning — pattern analysis and strategy idea generation
        self.meta_engine = get_meta_engine() if (
            _META_LEARNING_AVAILABLE and config.enable_meta_learning
        ) else None

        # Web Dashboard
        self.dashboard = get_dashboard_server() if (
            _DASHBOARD_AVAILABLE and config.enable_dashboard
        ) else None

    def _run_health_check(self):
        """Startup symbol health check: validate precision, connectivity, leverage caps."""
        logger.info("=" * 60)
        logger.info("SYMBOL HEALTH CHECK")
        logger.info("=" * 60)
        specs = get_all_symbol_specs()
        healthy = 0
        total = len(DEFAULT_SYMBOLS)

        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            spec = specs.get(symbol, {})
            price_dp = spec.get("price", 2)
            qty_dp = spec.get("qty", 4)
            min_q = spec.get("min_qty", 0.01)
            tick = spec.get("tick_size", 0.01)
            max_lev = spec.get("max_leverage", 25)

            # Try to fetch a ticker price
            price = self.fetcher.latest_price(symbol, sym_cfg.coingecko_id)
            if price and price > 0:
                status = "OK"
                healthy += 1
            else:
                status = "NO DATA"

            logger.info(
                f"  {symbol:10s} | {status:7s} | "
                f"price={f'${price:,.{price_dp}f}' if price else 'N/A':>16s} | "
                f"tick={tick} | qty_dp={qty_dp} min_qty={min_q} | "
                f"max_lev={max_lev}x | tier={sym_cfg.risk_tier}"
            )

            # Cache the price for fill validation
            if price and price > 0:
                self._last_prices[symbol] = price

        logger.info(f"Health: {healthy}/{total} symbols reachable")
        logger.info("=" * 60)

    def _reconcile_exchange_positions(self):
        """Restore open positions from Hyperliquid on startup."""
        logger.info("=" * 60)
        logger.info("POSITION RECONCILIATION")
        logger.info("=" * 60)
        try:
            count = reconcile_positions(
                pos_mgr=self.pos_mgr,
                exchanges=self.fetcher._exchanges,
                last_prices=self._last_prices,
                risk_mgr=self.risk_mgr,
            )
            if count > 0:
                logger.info(f"Reconciled {count} open positions from Hyperliquid")
                self.alerts.send_market_update(
                    f"[STARTUP] Reconciled {count} open position(s) from Hyperliquid"
                )
            else:
                logger.info("No open positions to reconcile")
        except Exception as e:
            logger.warning(f"Position reconciliation failed: {e}")
        logger.info("=" * 60)

    def run(self):
        """Main run loop."""
        logger.info("=" * 60)
        logger.info(f"Multi-Strategy Bot Starting")
        logger.info(f"  Environment: {self.config.environment}")
        logger.info(f"  Symbols: {len(DEFAULT_SYMBOLS)} ({', '.join(DEFAULT_SYMBOLS.keys())})")
        logger.info(f"  Strategies: {[s.name for s in self.strategies]}")
        logger.info(f"  Ensemble mode: {self.config.ensemble_mode} (min_votes={self.config.min_votes_required})")
        logger.info(f"  Leverage: {'enabled' if self.config.enable_leverage else 'disabled'} (max={self.config.max_leverage}x)")
        logger.info(f"  ML: {'enabled' if self.config.enable_ml else 'disabled'}")
        logger.info(f"  Trailing stop: {'enabled' if self.config.enable_trailing_stop else 'disabled'}")
        logger.info(f"  Scan interval: {self.config.scan_interval_s}s")
        logger.info(f"  Max positions: {self.config.max_open_positions}")
        logger.info(f"  Risk per trade: {self.config.risk_per_trade:.1%}")
        logger.info(f"  LLM meta-brain: {self.llm_mode.name} ({describe_mode(self.llm_mode)})")
        logger.info(f"  Signal monitor: {len(self.signal_monitor.channel_ids)} channels configured")
        logger.info("=" * 60)

        # Startup health check
        self._run_health_check()

        # Position reconciliation: restore open positions from exchange
        self._reconcile_exchange_positions()

        # Restore circuit breaker state from disk (survives restarts during drawdowns)
        try:
            restore_circuit_breaker_state(self.risk_mgr.circuit_breaker)
        except Exception as e:
            logger.debug(f"CB state restore skipped: {e}")

        if self.config.auto_trade:
            logger.warning("AUTO-TRADING ENABLED - REAL MONEY MODE")
            logger.warning("Starting in 5 seconds... Press CTRL+C to abort")
            time.sleep(5)

        # Start Telegram command bot
        self.telegram_bot.start()

        # Start signal ingestion pipeline
        self.signal_monitor.start()

        # Start watchdog (background health monitoring)
        self.watchdog.start()
        log_health_event("BOT_START", "INFO", f"Bot started: {len(DEFAULT_SYMBOLS)} symbols, LLM={self.llm_mode.name}")

        # Start web dashboard (background HTTP server)
        if self.dashboard:
            try:
                self.dashboard.start(bot_instance=self)
                logger.info(f"[INIT] Web dashboard started on port {self.config.dashboard_port}")
            except Exception as e:
                logger.warning(f"[INIT] Dashboard start failed: {e}")

        # Start HTTP health endpoint (container/orchestrator readiness probes)
        try:
            from monitoring.health_server import start_health_server
            start_health_server(
                health_monitor=self.health_monitor,
                port=self.config.health_port,
                extra_status_fn=lambda: {
                    "tick": self._tick,
                    "open_positions": self.pos_mgr.get_open_count(),
                    "equity": self.risk_mgr.equity,
                    "circuit_breaker": "tripped" if self.risk_mgr.circuit_breaker.tripped else "ok",
                },
            )
            logger.info(f"[INIT] Health server started on port {self.config.health_port}")
        except Exception as e:
            logger.warning(f"[INIT] Health server start failed: {e}")

        # Signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        while not self.stop_event.is_set():
            try:
                self._tick_once()
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                self.watchdog.record_error()

            self._tick += 1
            self._sleep_interruptible(self.config.scan_interval_s)

        self.watchdog.stop()
        log_health_event("BOT_STOP", "INFO", f"Bot stopped gracefully after {self._tick} ticks")
        logger.info("Bot stopped gracefully")

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}, stopping...")
        self.stop_event.set()

    def _sleep_interruptible(self, seconds: float):
        step = 0.5
        waited = 0.0
        while waited < seconds and not self.stop_event.is_set():
            time.sleep(min(step, seconds - waited))
            waited += step

    def _tick_once(self):
        """One iteration of the main loop."""
        trace_id = uuid.uuid4().hex[:8]
        _loop_start = time.time()

        # Collect candidate signals for rotation evaluation
        self._tick_candidates: list = []

        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            try:
                self._process_symbol(symbol, sym_cfg, trace_id)
            except Exception as e:
                logger.error(f"[{trace_id}][{symbol}] Error: {e}", exc_info=True)
                self.health_monitor.record_error()

        # ── Trade rotation evaluation ──
        # Check if any open position should be rotated into a better signal
        if self.rotation_mgr and self._tick_candidates:
            try:
                self._evaluate_rotations(trace_id)
            except Exception as e:
                logger.warning(f"[{trace_id}] Rotation evaluation error: {e}")

        # LLM meta-brain: hybrid trigger system
        # Triggers accumulated during symbol processing; also check periodic + cross-market
        if should_call_llm(self.llm_mode):
            # Check cross-market divergence (BTC vs alts)
            divergence = self._llm_triggers.check_cross_market_divergence(
                self._price_changes_1h
            )
            if divergence:
                self._llm_triggers.add(
                    LLMTrigger.CROSS_MARKET_DIVERGENCE,
                    context=divergence,
                )

            # Check memory-worthy events (performance shifts, streaks)
            mem_events = self._llm_triggers.check_memory_events()
            for mem_ctx in mem_events:
                self._llm_triggers.add(
                    LLMTrigger.MEMORY_EVENT,
                    context=mem_ctx,
                )

            # Check periodic fallback (5-minute heartbeat)
            if self._llm_triggers.event_count == 0:
                if self._llm_triggers.check_periodic():
                    self._llm_triggers.add(LLMTrigger.PERIODIC)

            # Fire if any trigger should run
            if self._llm_triggers.should_fire():
                try:
                    self._run_llm_metabrain(trace_id)
                except Exception as e:
                    logger.warning(f"[{trace_id}] LLM meta-brain error: {e}")
                self._llm_triggers.clear()
            else:
                self._llm_triggers.clear()

        # Feedback loop: run periodic backtests and apply parameter adjustments
        try:
            self.feedback.tick()
        except Exception as e:
            logger.warning(f"[{trace_id}] Feedback loop tick error: {e}")

        # Growth intelligence: periodic learning cycles, hypothesis graduation,
        # veto resolution, auto-safe proposal application, report generation
        try:
            # Build current prices for veto resolution
            _growth_prices = {}
            for _sym, _cfg in DEFAULT_SYMBOLS.items():
                p = self._last_prices.get(_sym)
                if p:
                    _growth_prices[_sym] = {"high": p, "low": p, "close": p}
            self.growth.tick(
                current_prices=_growth_prices,
                market_state={"price_changes_1h": self._price_changes_1h},
            )
        except Exception as e:
            logger.debug(f"[{trace_id}] Growth tick error: {e}")

        # LLM exit intelligence: evaluate open positions for dynamic SL/TP adjustments
        # Runs every 5th tick (~5 min at 60s intervals) to balance responsiveness vs cost
        self._exit_check_counter += 1
        if self._exit_check_counter >= 5:
            self._exit_check_counter = 0
            try:
                self._check_llm_exit_suggestions()
            except Exception as e:
                logger.warning(f"[{trace_id}] Exit intelligence error: {e}")

        # Position aging alerts: flag positions held too long with adverse funding
        # Runs every 10th tick (~10 min at 60s intervals)
        if self._tick % 10 == 0:
            try:
                self._check_position_aging()
            except Exception as e:
                logger.debug(f"[{trace_id}] Position aging check error: {e}")

        # Record health monitor heartbeat every tick
        _loop_elapsed = time.time() - _loop_start
        self.health_monitor.record_heartbeat(
            loop_duration_s=_loop_elapsed,
            positions=self.pos_mgr.get_open_count(),
            equity=self.risk_mgr.equity,
        )

        # Watchdog heartbeat: report we're alive
        self.watchdog.heartbeat(
            equity=self.risk_mgr.equity,
            scan_count=self._tick,
            exchange_healthy=not self.degradation.should_halt_entries(),
        )

        # Equity snapshot to DB every 15 ticks (~15 min at 60s intervals)
        if self._tick % 15 == 0:
            try:
                log_equity(
                    equity=self.risk_mgr.equity,
                    open_positions=self.pos_mgr.get_open_count(),
                    daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
                )
            except Exception:
                pass

        # Strategy research cycle: every 240 ticks (~4 hours at 60s intervals)
        if self._tick % 240 == 0 and self._tick > 0:
            try:
                from llm.strategy_discovery.research_agent import run_research_cycle
                notify_fn = None
                if self.alerts:
                    notify_fn = self.alerts.send_market_update
                proposals = run_research_cycle(
                    max_proposals=3,
                    notify_fn=notify_fn,
                )
                if proposals:
                    logger.info(
                        f"[{trace_id}] Research cycle: {len(proposals)} new proposals"
                    )
            except Exception as e:
                logger.debug(f"[{trace_id}] Research cycle error: {e}")

        # Self-Teaching: run learning cycle when enough trades accumulated
        # Checks every 60 ticks (~1 hour), but only runs if should_run_cycle() says yes
        if self._tick % 60 == 30 and self.teaching_engine and self.config.enable_self_teaching:
            try:
                if self.teaching_engine.should_run_cycle():
                    # Gather recent trades from deep memory for analysis
                    _teach_trades = []
                    try:
                        from llm.deep_memory import get_deep_memory
                        _dm = get_deep_memory()
                        _teach_trades = _dm.trade_dna._trades[-50:] if hasattr(_dm.trade_dna, '_trades') and _dm.trade_dna._trades else []
                    except Exception:
                        pass

                    _teach_report = self.teaching_engine.run_learning_cycle(
                        recent_trades=_teach_trades,
                        market_state={
                            "price_changes_1h": self._price_changes_1h,
                            "global_bias": self._global_bias,
                            "equity": self.risk_mgr.equity,
                        },
                    )
                    if _teach_report.get("knowledge_added"):
                        logger.info(
                            f"[TEACH] Learning cycle #{_teach_report['cycle_number']}: "
                            f"level={_teach_report['curriculum_level']}, "
                            f"+{len(_teach_report['knowledge_added'])} knowledge items"
                        )
            except Exception as e:
                logger.debug(f"[{trace_id}] Self-teaching cycle error: {e}")

        # Self-Tuning Risk: evaluate and auto-adjust risk profile every 30 ticks (~30 min)
        if self._tick % 30 == 0 and self._tick > 0:
            try:
                new_profile = risk_evaluate_and_adjust()
                if new_profile:
                    logger.info(f"[RISK-TUNE] Auto-adjusted to {new_profile} profile")
                    if self.alerts:
                        self.alerts.send_market_update(
                            f"Risk profile auto-adjusted to *{new_profile}*"
                        )
            except Exception as e:
                logger.debug(f"Risk tuning evaluation error: {e}")

        # Heartbeat every 60 ticks (~1 hour at 60s intervals)
        if self._tick % 60 == 0:
            self._send_heartbeat()
            Telemetry.save_snapshot()  # Persist telemetry for dashboards/LLM

        # Market update every 15 ticks (~15 min) - sends even without signals
        if self._tick % 15 == 0 and self._tick % 60 != 0:
            self._send_market_update(trace_id)

        # Evolution tracker: daily strategy evolution report (~1440 ticks at 60s = 24h)
        if self._tick % 1440 == 0 and self._tick > 0:
            try:
                from feedback.evolution_tracker import EvolutionTracker
                tracker = EvolutionTracker("data")
                report = tracker.generate_report()
                if self.alerts and report:
                    # Enhanced daily report with full breakdown
                    _dr_ds = get_daily_summary()
                    _dr_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    try:
                        _dr_msg = format_daily_report_telegram(
                            date=_dr_date,
                            total_trades=report.total_trades,
                            wins=_dr_ds.get("wins", 0),
                            losses=_dr_ds.get("losses", 0),
                            net_pnl=report.net_pnl,
                            equity=self.risk_mgr.equity,
                            by_strategy=_dr_ds.get("by_strategy"),
                        )
                        self.alerts.send_market_update(_dr_msg)
                    except Exception:
                        # Fallback to simple
                        summary = (
                            f"*Daily Evolution Report*\n"
                            f"Trades: {report.total_trades}\n"
                            f"Win rate: {report.win_rate:.1%}\n"
                            f"Net PnL: ${report.net_pnl:+.2f}"
                        )
                        self.alerts.send_market_update(summary)

                    # Aggregate daily performance into SQLite
                    update_daily_performance(_dr_date)
                # ── Feed lessons into LLM memory for future decisions ──
                if hasattr(report, "lessons") and report.lessons:
                    try:
                        from llm.memory_store import apply_memory_update
                        _fed = 0
                        for lesson in report.lessons[:5]:  # Top 5 highest-confidence lessons
                            if lesson.confidence >= 0.5 and lesson.action:
                                # Format with structured markers so quality gate passes
                                _note = f"{lesson.category}: {lesson.message} — {lesson.action}"
                                apply_memory_update(update=_note)
                                _fed += 1
                        if _fed:
                            logger.info(f"[EVOLUTION] Fed {_fed} lessons into LLM memory")
                    except Exception as e:
                        logger.debug(f"Evolution→LLM memory feed error: {e}")

                logger.info(f"[EVOLUTION] Daily report generated: {report.total_trades} trades")
            except Exception as e:
                logger.debug(f"Evolution tracker error: {e}")

        # Uplift Analytics + Progression: evaluate LLM value and autonomy readiness
        # Runs every 720 ticks (~12 hours) — gives enough time for data to accumulate
        if self._tick % 720 == 360 and self._tick > 360:
            # Uplift Analytics: compute baseline vs LLM-filtered performance delta
            if _UPLIFT_AVAILABLE:
                try:
                    uplift_data = compute_uplift()
                    if uplift_data.get("with_outcome", 0) >= 10:
                        uplift_report = format_uplift_report(uplift_data)
                        logger.info(f"[UPLIFT]\n{uplift_report}")
                        _uplift_delta = uplift_data.get("uplift", {})
                        if _uplift_delta.get("has_data"):
                            _is_positive = _uplift_delta.get("is_positive", False)
                            if self.alerts:
                                self.alerts.send_market_update(
                                    f"*LLM Uplift Report*\n"
                                    f"Verdict: {'POSITIVE' if _is_positive else 'NEGATIVE'}\n"
                                    f"WR delta: {_uplift_delta.get('win_rate_delta', 0):+.1%}\n"
                                    f"Avg PnL delta: ${_uplift_delta.get('avg_pnl_delta', 0):+.2f}"
                                )
                except Exception as e:
                    logger.debug(f"Uplift analytics error: {e}")

            # Progression Controller: evaluate readiness for next autonomy level
            if _PROGRESSION_AVAILABLE:
                try:
                    prog_report = evaluate_progression(self.llm_mode)
                    if prog_report and prog_report.all_passed:
                        logger.info(
                            f"[PROGRESSION] READY to advance: "
                            f"{prog_report.current_mode.name} -> {prog_report.target_mode.name} "
                            f"({prog_report.passed_count}/{prog_report.total_count} gates passed)"
                        )
                        if self.alerts:
                            self.alerts.send_market_update(
                                f"*Autonomy Progression Ready*\n"
                                f"{prog_report.current_mode.name} -> {prog_report.target_mode.name}\n"
                                f"All {prog_report.total_count} gates passed.\n"
                                f"Use /mode to advance."
                            )
                    elif prog_report:
                        logger.info(
                            f"[PROGRESSION] Not ready: "
                            f"{prog_report.passed_count}/{prog_report.total_count} gates"
                        )
                except Exception as e:
                    logger.debug(f"Progression evaluation error: {e}")

        # Strategy Pruning: evaluate and adjust weights for underperforming strategies
        # Runs every 1440 ticks (~24h) offset by 480 to avoid overlap with evolution report
        if self._tick % 1440 == 480 and self._tick > 480:
            if _STRATEGY_PRUNING_AVAILABLE:
                try:
                    _perf_path = os.path.join("data", "analysis", "performance.json")
                    if os.path.exists(_perf_path):
                        import json as _json
                        with open(_perf_path) as _f:
                            _perf_data = _json.load(_f)
                        adjustments = pruning_evaluate(_perf_data)
                        if adjustments:
                            logger.info(
                                f"[PRUNING] {len(adjustments)} strategy weight adjustments made"
                            )
                            if self.alerts:
                                _adj_lines = [
                                    f"  {a['name']}: {a['old_weight']:.2f} -> {a['new_weight']:.2f} ({a['action']})"
                                    for a in adjustments
                                ]
                                self.alerts.send_market_update(
                                    f"*Strategy Pruning*\n"
                                    + "\n".join(_adj_lines)
                                )
                except Exception as e:
                    logger.debug(f"Strategy pruning error: {e}")

        # RL auto-training: retrain policy daily if buffer has enough data
        if self._tick % 1440 == 720 and self._tick > 720:
            try:
                from rl.buffer import get_buffer_stats
                from rl.train_offline import train
                stats = get_buffer_stats()
                if stats.get("total", 0) >= 50:
                    policy = train()
                    if policy:
                        logger.info(
                            f"[RL-AUTO] Daily retrain: {stats['total']} transitions, "
                            f"policy updated"
                        )
            except Exception as e:
                logger.debug(f"RL auto-training error: {e}")

        # ── Wave 3: Portfolio Risk Engine — periodic correlation/vol updates ──
        # Every 30 ticks (~30 min): update forecasts and rebalance suggestions
        if self._tick % 30 == 15 and self.portfolio_risk:
            try:
                self.portfolio_risk.tick(
                    prices=self._last_prices,
                    open_positions={s: {"side": p.side, "entry": p.entry,
                                       "qty": p.qty, "leverage": p.leverage}
                                   for s, p in self.pos_mgr.get_open_positions().items()},
                    equity=self.risk_mgr.equity,
                )
                # Check for cascade signals
                if self.config.enable_cascade_signals:
                    _cascades = self.portfolio_risk.detect_cascade_signals(
                        self._price_changes_1h, threshold_pct=2.0
                    )
                    for _cs in _cascades[:2]:  # Cap at 2 alerts per tick
                        logger.info(
                            f"[CASCADE] {_cs.get('leader')} -> {_cs.get('follower')}: "
                            f"expected {_cs.get('expected_direction')}"
                        )
                        self._llm_triggers.add(
                            LLMTrigger.CROSS_MARKET_DIVERGENCE,
                            context=f"Cascade: {_cs.get('leader')} moved {_cs.get('leader_change', 0):.1f}%, "
                                    f"{_cs.get('follower')} may follow {_cs.get('expected_direction')}",
                        )
            except Exception as e:
                logger.debug(f"[{trace_id}] Portfolio risk tick error: {e}")

        # ── Wave 4: Counterfactual Resolution — resolve pending veto scenarios ──
        # Every 60 ticks (~1 hour): check if vetoed trades would have hit TP/SL
        if self._tick % 60 == 45 and self.counterfactual:
            try:
                self.counterfactual.resolve_pending(
                    current_prices=self._last_prices,
                    lookback_hours=24,
                )
            except Exception as e:
                logger.debug(f"[{trace_id}] Counterfactual resolution error: {e}")

        # ── Wave 4: Meta-Learning — periodic pattern analysis ──
        # Every 360 ticks (~6 hours): analyze decision patterns and generate ideas
        if self._tick % 360 == 180 and self._tick > 180 and self.meta_engine:
            try:
                # Gather recent trades from DB
                _ml_trades = get_recent_trades(50)
                self.meta_engine.tick(
                    recent_trades=_ml_trades,
                    market_state={
                        "price_changes_1h": self._price_changes_1h,
                        "global_bias": self._global_bias,
                        "equity": self.risk_mgr.equity,
                    },
                )
                _meta_ideas = self.meta_engine.get_active_ideas()
                if _meta_ideas:
                    logger.info(
                        f"[META-LEARN] {len(_meta_ideas)} active strategy ideas"
                    )
            except Exception as e:
                logger.debug(f"[{trace_id}] Meta-learning tick error: {e}")

        # ── Wave 4: Performance Attribution — daily attribution report ──
        # Every 1440 ticks (~24h), offset by 960 to avoid overlap
        if self._tick % 1440 == 960 and self._tick > 960 and _ATTRIBUTION_AVAILABLE:
            try:
                _attr_report = compute_attribution(days=7)
                if _attr_report and _attr_report.total_trades >= 5:
                    _attr_text = format_attribution_report(_attr_report)
                    logger.info(f"[ATTRIBUTION]\n{_attr_text}")
                    if self.alerts:
                        # Send summary to Telegram
                        _top = ", ".join(_attr_report.top_contributors[:3]) if _attr_report.top_contributors else "none"
                        _worst = ", ".join(_attr_report.worst_detractors[:3]) if _attr_report.worst_detractors else "none"
                        self.alerts.send_market_update(
                            f"*Performance Attribution (7d)*\n"
                            f"PnL: ${_attr_report.total_pnl:+.2f} | "
                            f"Trades: {_attr_report.total_trades}\n"
                            f"Top contributors: {_top}\n"
                            f"Worst detractors: {_worst}\n"
                            f"LLM value-add: ${_attr_report.llm_value_add:+.2f}\n"
                            f"Sizing alpha: ${_attr_report.sizing_alpha:+.2f}"
                        )
            except Exception as e:
                logger.debug(f"[{trace_id}] Attribution report error: {e}")

        # ── Wave 4: A/B Testing — evaluate experiments periodically ──
        # Every 720 ticks (~12h): check experiment results
        if self._tick % 720 == 420 and self._tick > 420 and self.ab_manager:
            try:
                for _exp in self.ab_manager.get_active_experiments():
                    _result = self.ab_manager.evaluate_experiment(_exp.id)
                    if _result and _result.is_significant:
                        _action_msg = _result.recommended_action.replace("_", " ").title()
                        logger.info(
                            f"[A/B TEST] {_exp.name}: SIGNIFICANT result! "
                            f"p={_result.p_value:.4f}, recommendation={_action_msg}"
                        )
                        if self.alerts:
                            self.alerts.send_market_update(
                                f"*A/B Test Result*\n"
                                f"Experiment: {_exp.name}\n"
                                f"Control WR: {_result.control_win_rate:.1%} | "
                                f"Variant WR: {_result.variant_win_rate:.1%}\n"
                                f"Control PnL: ${_result.control_avg_pnl:+.2f} | "
                                f"Variant PnL: ${_result.variant_avg_pnl:+.2f}\n"
                                f"p-value: {_result.p_value:.4f} | "
                                f"Action: {_action_msg}"
                            )
                        if _result.recommended_action == "graduate_variant":
                            self.ab_manager.graduate_experiment(_exp.id)
            except Exception as e:
                logger.debug(f"[{trace_id}] A/B test evaluation error: {e}")

        # ── Circuit breaker state persistence ──
        # Save CB state every 10 ticks so it survives restarts during drawdowns
        if self._tick % 10 == 0:
            try:
                save_circuit_breaker_state(self.risk_mgr.circuit_breaker)
            except Exception:
                pass

        # ── Periodic position reconciliation ──
        # Every 60 ticks (~1h): detect phantom (bot-only) and orphan (exchange-only) positions
        if self._tick % 60 == 45 and self._tick > 0:
            try:
                result = periodic_reconciliation_check(
                    pos_mgr=self.pos_mgr,
                    exchanges=self.fetcher._exchanges,
                )
                if result.get("phantoms") or result.get("orphans"):
                    logger.warning(
                        f"[RECONCILE] Drift detected: "
                        f"{len(result.get('phantoms', []))} phantom, "
                        f"{len(result.get('orphans', []))} orphan"
                    )
                    if self.alerts:
                        self.alerts.send_market_update(
                            f"Position drift detected: "
                            f"{len(result.get('phantoms', []))} phantom, "
                            f"{len(result.get('orphans', []))} orphan positions"
                        )
            except Exception as e:
                logger.debug(f"[{trace_id}] Periodic reconciliation error: {e}")

    def _process_symbol(self, symbol: str, sym_cfg, trace_id: str = ""):
        """Process one symbol: fetch data, check positions, generate signals."""
        # F3: Graceful degradation — halt new entries if exchange is down
        if self.degradation.should_halt_entries():
            # Still process existing positions for SL/TP, but skip new entries
            open_pos = self.pos_mgr.get_open_positions()
            if symbol not in open_pos:
                return  # Skip signal evaluation for symbols without positions

        # Fetch data for all needed timeframes
        try:
            data = self.fetcher.fetch_multi_timeframe(symbol, sym_cfg.coingecko_id, self._needed_tfs)
            self.degradation.record_exchange_success()
        except Exception as e:
            self.degradation.record_exchange_error()
            logger.warning(f"[{symbol}] Exchange fetch failed: {e}")
            return

        # Get current price
        current_price = self.fetcher.latest_price(symbol, sym_cfg.coingecko_id)
        if current_price is None:
            return

        # Fill-price guardrail: validate against last known price
        last_known = self._last_prices.get(symbol)
        if last_known is not None:
            err = validate_fill_price(symbol, current_price, last_known)
            if err:
                log_rejection(symbol, "FILL_PRICE_OFFSCALE", confidence=0)
                logger.warning(f"[{symbol}] PRICE REJECTED: {err}")
                return
        self._last_prices[symbol] = current_price

        # Cross-symbol pattern tracking: record price for lead-lag detection
        if self.cross_symbol_tracker:
            try:
                self.cross_symbol_tracker.record_price(symbol, current_price)
            except Exception:
                pass  # Non-critical

        # Wave 3: Portfolio risk engine — record price for correlation/vol tracking
        if self.portfolio_risk:
            try:
                self.portfolio_risk.record_price(symbol, current_price)
            except Exception:
                pass  # Non-critical

        # Fetch and cache funding rate (throttled: once per 60 ticks per symbol)
        if self._tick % 60 == 0 or symbol not in self._last_funding_rates:
            try:
                fr = self.fetcher.fetch_funding_rate(symbol)
                if fr is not None:
                    self._last_funding_rates[symbol] = fr
            except Exception:
                pass

        # Track 1h price changes for cross-market divergence detection
        try:
            df_1h_div = data.get("1h")
            if df_1h_div is not None and not df_1h_div.empty and len(df_1h_div) > 2:
                pch = (current_price - float(df_1h_div["close"].iloc[-2])) / float(df_1h_div["close"].iloc[-2]) * 100
                self._price_changes_1h[symbol] = pch
        except Exception:
            pass

        # Record market snapshot for ML passive learning
        if self.ml:
            snapshot = MarketSnapshot(symbol=symbol, price=current_price)
            # Compute market context from available data
            try:
                df_1h = data.get("1h")
                if df_1h is not None and not df_1h.empty and len(df_1h) > 2:
                    snapshot.price_change_1h_pct = (current_price - float(df_1h["close"].iloc[-2])) / float(df_1h["close"].iloc[-2]) * 100
                    if len(df_1h) > 24:
                        snapshot.price_change_24h_pct = (current_price - float(df_1h["close"].iloc[-24])) / float(df_1h["close"].iloc[-24]) * 100
                    avg_vol = float(df_1h["volume"].tail(20).mean())
                    if avg_vol > 0:
                        snapshot.volume_ratio = float(df_1h["volume"].iloc[-1]) / avg_vol
                    # ATR-based volatility (ATR14 / price as percentage)
                    if len(df_1h) > 14:
                        prev_c = df_1h["close"].shift(1)
                        tr = pd.concat([
                            df_1h["high"] - df_1h["low"],
                            (df_1h["high"] - prev_c).abs(),
                            (df_1h["low"] - prev_c).abs(),
                        ], axis=1).max(axis=1)
                        atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
                        snapshot.volatility = atr14 / current_price * 100
            except Exception:
                pass
            self.ml.record_snapshot(snapshot)

        # Pre-close trigger: predict if any open position is about to close
        open_pos = self.pos_mgr.get_open_positions()
        if symbol in open_pos:
            pos = open_pos[symbol]
            pre_close = self._llm_triggers.check_pre_close(
                symbol=symbol,
                side=pos.side,
                entry=pos.entry,
                current_price=current_price,
                sl=pos.sl,
                tp1=pos.tp1,
                tp2=pos.tp2,
                state=pos.state,
                atr=pos.atr,
            )
            if pre_close:
                self._llm_triggers.add(
                    LLMTrigger.PRE_CLOSE,
                    symbol=symbol,
                    context=pre_close,
                )

        # Liquidation distance monitoring: check every tick for leveraged positions
        if symbol in open_pos and open_pos[symbol].leverage > 1.0:
            _liq_pos = open_pos[symbol]
            _liq_check = self.leverage_mgr.check_liquidation_risk(
                entry=_liq_pos.entry,
                current_price=current_price,
                side=_liq_pos.side,
                leverage=_liq_pos.leverage,
                safety_buffer=0.03,  # 3% distance triggers alert
            )
            _liq_dist = _liq_check.get("distance_pct", 1.0)
            if _liq_dist < 0.015:
                # < 1.5% from liquidation — force close
                logger.warning(
                    f"[{trace_id}][{symbol}] LIQUIDATION PROXIMITY: "
                    f"{_liq_dist:.1%} from liquidation at {_liq_check.get('liquidation_price', 0):.4f}. "
                    f"Force closing."
                )
                self.pos_mgr.force_close(symbol, current_price, "LIQUIDATION_PROXIMITY")
            elif _liq_dist < 0.03:
                # < 3% from liquidation — tighten SL
                _new_sl = current_price * (0.995 if _liq_pos.side == "LONG" else 1.005)
                if (_liq_pos.side == "LONG" and _new_sl > _liq_pos.sl) or \
                   (_liq_pos.side == "SHORT" and _new_sl < _liq_pos.sl):
                    _liq_pos.sl = _new_sl
                    logger.warning(
                        f"[{trace_id}][{symbol}] Liquidation warning: "
                        f"{_liq_dist:.1%} distance — tightened SL to {_new_sl:.4f}"
                    )

        # D2: Funding-aware hold time optimization
        # Close marginal positions before 8-hour funding payments
        if symbol in open_pos and open_pos[symbol].leverage > 1.0:
            _fund_pos = open_pos[symbol]
            _fr = self._last_funding_rates.get(symbol, 0.0)
            if _fr != 0:
                _p = self._last_prices.get(symbol, _fund_pos.entry)
                if _fund_pos.side == "LONG":
                    _unrealized_pct = (_p - _fund_pos.entry) / _fund_pos.entry * 100
                else:
                    _unrealized_pct = (_fund_pos.entry - _p) / _fund_pos.entry * 100
                if should_close_before_funding(
                    pnl_pct=_unrealized_pct,
                    funding_rate=_fr,
                    leverage=_fund_pos.leverage,
                    side=_fund_pos.side,
                ):
                    logger.info(
                        f"[{trace_id}][{symbol}] Closing before funding: "
                        f"PnL={_unrealized_pct:.2f}%, rate={_fr:.5f}, "
                        f"lev={_fund_pos.leverage:.0f}x"
                    )
                    self.pos_mgr.force_close(symbol, current_price, "FUNDING_AVOIDANCE")

        # Update existing positions (pass 5m data for early exit momentum detection)
        df_5m = data.get("5m")
        events = self.pos_mgr.update_price(symbol, current_price, df_5m=df_5m)
        for event in events:
            self.risk_mgr.update_equity(event.pnl - event.fee)

            # Log trade event to database
            log_trade(
                symbol=event.symbol,
                action=event.action,
                side=event.side,
                price=event.price,
                qty=event.qty,
                pnl=event.pnl,
                fee=event.fee,
                leverage=event.leverage,
                strategy=event.strategy,
                metadata=event.metadata
            )

            # Full close actions (for ML, weight tracking, cooldown)
            _FULL_CLOSE = ("SL", "TP2", "TRAILING_STOP", "EARLY_EXIT",
                           "EMERGENCY", "LIQUIDATION_AVOID",
                           "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE")

            # Record outcome for strategy weight tracking (only on full close, use total PnL)
            if event.action in _FULL_CLOSE and event.strategy:
                pos = self.pos_mgr.positions.get(symbol)
                total_pnl = pos.realized_pnl if pos else event.pnl
                self.weight_mgr.record_outcome(event.strategy, total_pnl > 0)

                # Record for LLM memory-worthy event detection
                _et = ""
                if pos and pos.trade_profile:
                    _et = pos.trade_profile.entry_type
                self._llm_triggers.record_trade_outcome(
                    strategy=event.strategy,
                    entry_type=_et,
                    win=total_pnl > 0,
                )

            # Log trade event (paper trading compatibility)
            if self.trade_logger:
                hold_time = event.metadata.get("hold_time_s", 0)
                self.trade_logger.log_trade_event(event, hold_time_s=hold_time)

            # Record outcome for feedback loop (TOTAL trade PnL)
            if event.action in _FULL_CLOSE:
                pos = self.pos_mgr.positions.get(symbol)
                total_pnl = pos.realized_pnl if pos else event.pnl
                _et_fb = ""
                _pd_fb = ""
                _rg_fb = ""
                if pos and pos.trade_profile:
                    _et_fb = pos.trade_profile.entry_type
                    _pd_fb = pos.trade_profile.primary_driver
                    _rg_fb = pos.trade_profile.regime
                # Extract LLM decision data from position's entry_reasons
                _llm_action = pos.entry_reasons.get("llm_action", "") if pos and pos.entry_reasons else ""
                _llm_conf = pos.entry_reasons.get("llm_confidence", 0.0) if pos and pos.entry_reasons else 0.0
                _llm_agreed = pos.entry_reasons.get("llm_agreed", True) if pos and pos.entry_reasons else True
                try:
                    self.feedback.record_outcome(
                        confidence=pos.confidence if pos else 0,
                        win=total_pnl > 0,
                        pnl=total_pnl,
                        strategy=event.strategy,
                        symbol=symbol,
                        regime=_rg_fb,
                        side=event.side,
                        entry_type=_et_fb,
                        num_agree=pos.entry_reasons.get("num_agree", 1) if pos and pos.entry_reasons else 1,
                        hold_time_s=event.metadata.get("hold_time_s", 0),
                        exit_action=event.action,
                        leverage=event.leverage,
                        llm_action=_llm_action,
                        llm_confidence=_llm_conf,
                        llm_agreed=_llm_agreed,
                    )
                except Exception as e:
                    logger.warning(f"Feedback outcome error: {e}")

                # Growth intelligence: feed trade data to self-evolving systems
                try:
                    now_utc = datetime.now(timezone.utc)
                    self.growth.on_trade_closed({
                        "symbol": symbol,
                        "side": event.side,
                        "outcome": "WIN" if total_pnl > 0 else "LOSS",
                        "pnl": total_pnl,
                        "pnl_pct": (total_pnl / self.risk_mgr.equity * 100) if self.risk_mgr.equity > 0 else 0,
                        "confidence": pos.confidence if pos else 0,
                        "regime": _rg_fb,
                        "strategy": event.strategy,
                        "num_agree": pos.entry_reasons.get("num_agree", 1) if pos and pos.entry_reasons else 1,
                        "hold_time_s": event.metadata.get("hold_time_s", 0),
                        "leverage": event.leverage,
                        "hour": now_utc.hour,
                        "entry_type": _et_fb,
                    })
                except Exception as e:
                    logger.debug(f"Growth trade record error: {e}")

                # E1: Feed strategy discovery corpus with trade observations
                try:
                    from llm.strategy_discovery.corpus import add_observation
                    _outcome_str = "WIN" if total_pnl > 0 else "LOSS"
                    add_observation(
                        category="trade_outcome",
                        symbol=symbol,
                        regime=_rg_fb or "unknown",
                        observation=(
                            f"{event.strategy} {event.side} {_outcome_str}: "
                            f"pnl=${total_pnl:.2f}, regime={_rg_fb}, "
                            f"exit={event.action}, entry_type={_et_fb}, "
                            f"lev={event.leverage:.0f}x, "
                            f"hold={event.metadata.get('hold_time_s', 0):.0f}s"
                        ),
                    )
                except Exception:
                    pass  # Corpus not critical

                # Deep memory: record full trade DNA for LLM knowledge base
                try:
                    _dm_pos = self.pos_mgr.positions.get(symbol)
                    if _dm_pos:
                        self._record_trade_dna(symbol, _dm_pos, event)
                except Exception as e:
                    logger.debug(f"Deep memory trade DNA error: {e}")

                # Post-Trade Learner: generate immediate lesson and inject into memory
                try:
                    from llm.post_trade_learner import generate_immediate_lesson
                    from llm.memory_store import apply_memory_update as _ptl_mem_update
                    _ptl_lesson = generate_immediate_lesson({
                        "symbol": symbol,
                        "side": event.side,
                        "outcome": "WIN" if total_pnl > 0 else "LOSS",
                        "pnl": total_pnl,
                        "confidence": pos.confidence if pos else 0,
                        "regime": _rg_fb,
                        "strategy": event.strategy,
                        "hold_time_s": event.metadata.get("hold_time_s", 0),
                        "exit_action": event.action,
                        "llm_action": _llm_action,
                        "llm_confidence": _llm_conf,
                        "funding_rate": self._last_funding_rates.get(symbol, 0)
                            if hasattr(self, '_last_funding_rates') else 0,
                    })
                    if _ptl_lesson:
                        _ptl_mem_update(_ptl_lesson, symbol=symbol, regime=_rg_fb)
                except Exception as e:
                    logger.debug(f"Post-trade learner error: {e}")

                # Trade Autopsy: generate periodic structured analysis every 5 trades
                try:
                    from llm.trade_autopsy import should_run_autopsy, generate_autopsy
                    # Count closed trades (approximate via feedback loop or counter)
                    _trade_count = getattr(self, '_closed_trade_count', 0) + 1
                    self._closed_trade_count = _trade_count
                    if should_run_autopsy(_trade_count):
                        generate_autopsy()  # Pulls from deep memory, caches result
                except Exception as e:
                    logger.debug(f"Trade autopsy error: {e}")

                # Self-Teaching: feed closed trade to learning engine
                if self.teaching_engine and self.config.enable_self_teaching:
                    try:
                        self.teaching_engine.record_trade_for_learning({
                            "symbol": symbol,
                            "side": event.side,
                            "outcome": "WIN" if total_pnl > 0 else "LOSS",
                            "pnl": total_pnl,
                            "confidence": getattr(
                                self.pos_mgr.positions.get(symbol), "confidence", 0
                            ),
                            "regime": _rg_fb,
                            "strategy": event.strategy,
                            "entry_type": _et_fb,
                            "num_agree": signal_result.metadata.get("num_agree", 1) if hasattr(signal_result, 'metadata') else 1,
                            "hold_time_s": event.metadata.get("hold_time_s", 0),
                            "leverage": event.leverage,
                            "exit_action": event.action,
                        })
                    except Exception as e:
                        logger.debug(f"Self-teaching trade record error: {e}")

                # RL buffer: record transition for offline learning
                try:
                    _rl_pos = self.pos_mgr.positions.get(symbol)
                    _risk_amt = self.risk_mgr.equity * 0.01  # 1% risk base
                    _rl_reward = total_pnl / _risk_amt if _risk_amt > 0 else 0
                    rl_append_transition(
                        state={
                            "symbol": symbol,
                            "regime": _rg_fb,
                            "confidence": _rl_pos.confidence if _rl_pos else 0,
                            "side": event.side,
                            "entry": _rl_pos.entry if _rl_pos else 0,
                            "volatility": _close_vol if '_close_vol' in dir() else 0,
                        },
                        action={
                            "llm_mode": self.llm_mode.name if hasattr(self.llm_mode, 'name') else str(self.llm_mode),
                            "llm_action": _llm_action,
                            "size_multiplier": _rl_pos.entry_reasons.get("llm_size_mult", 1.0) if _rl_pos and _rl_pos.entry_reasons else 1.0,
                            "leverage": event.leverage,
                            "entry_type": _et_fb,
                        },
                        reward=round(_rl_reward, 4),
                        metadata={
                            "trigger": _rl_pos.entry_reasons.get("trigger", "") if _rl_pos and _rl_pos.entry_reasons else "",
                            "hold_time_s": event.metadata.get("hold_time_s", 0),
                            "outcome": "WIN" if total_pnl > 0 else "LOSS",
                            "pnl": round(total_pnl, 2),
                            "strategy": event.strategy,
                        },
                    )
                except Exception as e:
                    logger.debug(f"RL buffer append error: {e}")

                # Self-Tuning Risk: update telemetry on trade close
                try:
                    self.risk_telemetry.update(
                        equity=self.risk_mgr.equity,
                        daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
                    )
                except Exception as e:
                    logger.debug(f"Risk telemetry update error: {e}")

                # Survival Pressure: track outcome for LLM accountability
                if _SURVIVAL_PRESSURE_AVAILABLE:
                    try:
                        _funding_cost = 0.0
                        _fr = self._last_funding_rates.get(symbol, 0)
                        if _fr and pos:
                            _hold_h = event.metadata.get("hold_time_s", 0) / 3600
                            _funding_cost = abs(_fr) * pos.leverage * abs(pos.qty) * pos.entry * (_hold_h / 8)
                        survival_record_outcome(
                            outcome="WIN" if total_pnl > 0 else "LOSS",
                            pnl=total_pnl,
                            funding_cost=_funding_cost,
                            equity=self.risk_mgr.equity,
                        )
                    except Exception as e:
                        logger.debug(f"Survival pressure record error: {e}")

                # Adaptive Risk: record outcome for dynamic risk sizing
                if self.adaptive_risk:
                    try:
                        self.adaptive_risk.record_outcome(
                            win=total_pnl > 0,
                            regime=_rg_fb,
                        )
                    except Exception as e:
                        logger.debug(f"Adaptive risk record error: {e}")

                # Wave 4: Counterfactual — record exit alternative (TP1 vs TP2)
                if self.counterfactual:
                    try:
                        self.counterfactual.record_exit_alternative(
                            symbol=symbol,
                            actual_exit_action=event.action,
                            actual_exit_price=event.price,
                            tp1_price=pos.tp1 if pos else 0,
                            tp2_price=pos.tp2 if pos else 0,
                            entry_price=pos.entry if pos else 0,
                            actual_pnl=total_pnl,
                        )
                    except Exception as e:
                        logger.debug(f"Counterfactual exit record error: {e}")

                # Wave 4: A/B Testing — record outcome for active experiments
                if self.ab_manager:
                    try:
                        for exp in self.ab_manager.get_active_experiments():
                            _ab_group = self.ab_manager.get_assignment(
                                exp.id, symbol, event.strategy or ""
                            )
                            self.ab_manager.record_outcome(
                                experiment_id=exp.id,
                                group=_ab_group,
                                symbol=symbol,
                                pnl=total_pnl,
                                win=total_pnl > 0,
                                metadata={
                                    "strategy": event.strategy,
                                    "regime": _rg_fb,
                                    "leverage": event.leverage,
                                },
                            )
                    except Exception as e:
                        logger.debug(f"A/B testing outcome record error: {e}")

                # Learning Mode: record trade observation for phase progression
                if _LEARNING_MODE_AVAILABLE and is_learning_mode_active():
                    try:
                        learning_record_trade(
                            symbol=symbol,
                            side=event.side,
                            outcome="WIN" if total_pnl > 0 else "LOSS",
                            pnl=total_pnl,
                            confidence=pos.confidence if pos else 0,
                        )
                    except Exception as e:
                        logger.debug(f"Learning mode trade record error: {e}")

                # Signal Outcome Tracking: log to SQLite for performance scoring
                try:
                    _so_entry = pos.entry if pos else 0
                    _so_conf = pos.confidence if pos else 0
                    _so_pnl_pct = (total_pnl / (self.risk_mgr.equity * self.config.risk_per_trade) * 100) if self.risk_mgr.equity > 0 else 0
                    log_signal_outcome(
                        symbol=symbol,
                        strategy=event.strategy or "",
                        side=event.side,
                        confidence=_so_conf,
                        entry_price=_so_entry,
                        exit_price=event.price,
                        exit_action=event.action,
                        pnl=total_pnl,
                        pnl_pct=_so_pnl_pct,
                        hold_time_s=event.metadata.get("hold_time_s", 0),
                        regime=_rg_fb,
                        leverage=event.leverage,
                        win=total_pnl > 0,
                    )
                except Exception as e:
                    logger.debug(f"Signal outcome tracking error: {e}")

            # Record outcome for ML (use TOTAL trade PnL, not just final leg)
            if self.ml and event.action in _FULL_CLOSE:
                pos = self.pos_mgr.positions.get(symbol)
                total_pnl = pos.realized_pnl if pos else event.pnl

                # Gather close-time market context for richer ML learning
                _close_vol = 0.0
                _close_pchange_1h = 0.0
                _close_regime = ""
                try:
                    sym_cfg = DEFAULT_SYMBOLS.get(symbol)
                    if sym_cfg:
                        df_1h = self.fetcher.fetch_ohlcv(symbol, sym_cfg.coingecko_id, "1h")
                        if df_1h is not None and not df_1h.empty and len(df_1h) > 14:
                            atr_series = df_1h["close"].rolling(14, min_periods=1).std()
                            _close_vol = float(atr_series.iloc[-1] / df_1h["close"].iloc[-1] * 100) if df_1h["close"].iloc[-1] > 0 else 0.0
                            _close_pchange_1h = float((df_1h["close"].iloc[-1] - df_1h["close"].iloc[-2]) / df_1h["close"].iloc[-2] * 100) if len(df_1h) > 1 else 0.0
                        _close_regime = _rg_fb  # reuse regime from feedback block above
                except Exception as e:
                    logger.debug(f"ML close-context fetch error: {e}")

                self.ml.record_outcome(TradeOutcome(
                    symbol=symbol,
                    strategy=event.strategy,
                    side=event.side,
                    confidence=pos.confidence if pos else 0,
                    leverage=event.leverage,
                    win=total_pnl > 0,
                    pnl=total_pnl,
                    exit_action=event.action,
                    hold_time_s=event.metadata.get("hold_time_s", 0),
                    hour_of_day=datetime.now(timezone.utc).hour,
                    day_of_week=datetime.now(timezone.utc).weekday(),
                    close_volatility=_close_vol,
                    close_price_change_1h_pct=_close_pchange_1h,
                    close_regime=_close_regime,
                ))

            # Learning hooks + enhanced trade log on full closes
            if event.action in _FULL_CLOSE:
                self._symbol_cooldown[symbol] = time.time()
                pos = self.pos_mgr.positions.get(symbol)
                # Anti-round-trip: track win/loss and side for cooldown logic
                if pos:
                    self._last_close_win[symbol] = pos.realized_pnl > 0
                    self._last_close_side[symbol] = pos.side
                    # Telemetry: track win/loss and PnL
                    if pos.realized_pnl > 0:
                        Telemetry.inc("trades_won")
                    else:
                        Telemetry.inc("trades_lost")
                    Telemetry.record("pnls", pos.realized_pnl)

                # LLM trigger: position closed -> learn from it
                _close_pnl = pos.realized_pnl if pos else event.pnl
                _close_side = pos.side if pos else event.side
                self._llm_triggers.add(
                    LLMTrigger.POSITION_CLOSED,
                    symbol=symbol,
                    context=f"Closed {_close_side} {symbol} via {event.action} "
                            f"PnL=${_close_pnl:+.2f}",
                )
                if pos:
                    # Extract profile data for logging
                    _et = pos.trade_profile.entry_type if pos.trade_profile else ""
                    _pd = pos.trade_profile.primary_driver if pos.trade_profile else ""
                    _rg = pos.trade_profile.regime if pos.trade_profile else ""
                    _vb = pos.trade_profile.volatility_band if pos.trade_profile else ""

                    # Record to data/analysis/trade_outcomes.csv
                    record_trade_outcome(
                        symbol=symbol,
                        side=event.side,
                        outcome=pos.outcome,
                        pnl=pos.realized_pnl,
                        entry=pos.entry,
                        sl=pos.original_sl,
                        tp1=pos.tp1,
                        tp2=pos.tp2,
                        tp1_hit=pos.filled_tp1,
                        sl_after_tp1=event.action == "SL" and pos.filled_tp1,
                        state_path=pos.state_path_str,
                        leverage=pos.leverage,
                        confidence=pos.confidence,
                        strategy=pos.strategy,
                        entry_reasons=pos.entry_reasons,
                        entry_type=_et,
                        primary_driver=_pd,
                        regime=_rg,
                        volatility_band=_vb,
                    )
                    # Record to data/trades.csv (enhanced)
                    log_closed_trade(
                        symbol=symbol,
                        side=event.side,
                        entry=pos.entry,
                        exit_price=event.price,
                        action=event.action,
                        pnl=pos.realized_pnl,
                        fees=pos.fees_paid,
                        state_path=pos.state_path_str,
                        outcome=pos.outcome,
                        leverage=pos.leverage,
                        confidence=pos.confidence,
                        strategy=pos.strategy,
                        ml_samples_at_entry=0,
                        ml_samples_at_exit=len(self.ml.outcomes) if self.ml else 0,
                        entry_reasons=pos.entry_reasons,
                        entry_type=_et,
                        primary_driver=_pd,
                        regime=_rg,
                        volatility_band=_vb,
                    )

            # Send enhanced trade event alert
            pos = self.pos_mgr.positions.get(symbol)
            _total_pnl_alert = pos.realized_pnl if pos else event.pnl
            _hold_time_alert = event.metadata.get("hold_time_s", 0)
            try:
                _enhanced_msg = format_trade_event_telegram(
                    action=event.action,
                    symbol=symbol,
                    side=event.side,
                    price=event.price,
                    pnl=event.pnl,
                    leverage=event.leverage,
                    total_pnl=_total_pnl_alert if event.action in _FULL_CLOSE else 0,
                    hold_time_s=_hold_time_alert,
                    strategy=event.strategy or "",
                    equity=self.risk_mgr.equity,
                )
                self.alerts.send_trade_event(event.action, symbol, _enhanced_msg)
            except Exception:
                # Fallback to simple format
                details = (
                    f"{event.action} {event.side} @ {_fmt_price(event.price)}\n"
                    f"PnL: ${event.pnl:+.2f} | Leverage: {event.leverage:.1f}x"
                )
                if event.action in _FULL_CLOSE and pos:
                    details += f"\nTotal PnL: ${pos.realized_pnl:+.2f}"
                self.alerts.send_trade_event(event.action, symbol, details)

            # Check circuit breaker
            if not self.risk_mgr.circuit_breaker.is_trading_allowed():
                reason = self.risk_mgr.circuit_breaker.trip_reason
                self.alerts.send_circuit_breaker(reason)

        # Check leverage liquidation risk on open positions
        open_pos = self.pos_mgr.get_open_positions()
        if symbol in open_pos:
            pos = open_pos[symbol]
            if pos.leverage > 1.0:
                liq_check = self.leverage_mgr.check_liquidation_risk(
                    pos.entry, current_price, pos.side, pos.leverage
                )
                if liq_check["at_risk"]:
                    logger.warning(f"[{symbol}] LIQUIDATION RISK: {liq_check}")
                    self.pos_mgr.force_close(symbol, current_price, "LIQUIDATION_AVOID")

        # Clean up stale closed positions (prevent memory growth overnight)
        from execution.position_state import CLOSED as _CLOSED
        stale = [s for s, p in self.pos_mgr.positions.items()
                 if p.state == _CLOSED and s not in open_pos]
        for s in stale:
            del self.pos_mgr.positions[s]

        # Try to generate new signal
        if self.telegram_bot.is_paused:
            return  # Paused via Telegram /pause command
        if self.ops_guard.is_killed:
            return  # Kill switch active

        # If we already have a position in this symbol, still evaluate signals
        # for rotation candidates (other symbols may want to rotate into this one)
        has_position = symbol in open_pos
        at_max_positions = self.pos_mgr.get_open_count() >= self.risk_mgr.max_open_positions

        # If we have a position and rotation is enabled, still evaluate the
        # ensemble so the signal can serve as a rotation candidate for OTHER
        # open positions that might want to rotate into this symbol.
        if has_position and not self.rotation_mgr:
            return  # No rotation, nothing to do

        # Per-symbol cooldown: don't re-enter too quickly after closing
        # (skip for rotation candidate collection — cooldown is for fresh entries)
        if not has_position:
            last_close = self._symbol_cooldown.get(symbol, 0)
            was_win = self._last_close_win.get(symbol, False)
            cd = self._win_cooldown_seconds if was_win else self._cooldown_seconds
            if time.time() - last_close < cd:
                return

        # Correlation guard: check before evaluating (saves compute)
        # We need to know the signal direction first, so we do a quick check
        # on existing positions to reject early if same-tier is maxed out
        if not has_position:
            sym_tier = sym_cfg.risk_tier
            tier_count = sum(
                1 for s, p in open_pos.items()
                if DEFAULT_SYMBOLS.get(s) and DEFAULT_SYMBOLS[s].risk_tier == sym_tier
            )
            if tier_count >= self._max_same_tier:
                return  # Too many positions in same risk tier

        # ── Wave 2: Regime-based strategy filter ──
        # Disable strategies that historically fail in the current regime
        if self.config.enable_regime_strategy_filter:
            try:
                _cur_regime = self.regime_detector.get_regime(symbol)
                if _cur_regime:
                    from llm.deep_memory import get_deep_memory
                    _dm = get_deep_memory()
                    _strat_wr = _dm.trade_dna.get_win_rate_by("strategy")
                    _disabled = set()
                    for _sname, _swdata in _strat_wr.items():
                        if _swdata.get("total", 0) >= 10 and _swdata.get("win_rate", 1.0) < 0.35:
                            _disabled.add(_sname)
                    if _disabled:
                        self.ensemble.set_disabled_strategies(_disabled)
                        logger.info(
                            f"[{trace_id}][{symbol}] Regime filter: disabled {_disabled} "
                            f"in {_cur_regime} regime"
                        )
                    else:
                        self.ensemble.set_disabled_strategies(set())
                else:
                    self.ensemble.set_disabled_strategies(set())
            except Exception:
                self.ensemble.set_disabled_strategies(set())

        signal_result = self.ensemble.evaluate(symbol, data)

        # Update last snapshot with ensemble context for ML learning
        if self.ml and self.ml.snapshots:
            last_snap = self.ml.snapshots[-1]
            if last_snap.symbol == symbol:
                if signal_result:
                    last_snap.ensemble_direction = signal_result.side
                    last_snap.ensemble_confidence = signal_result.confidence

        if signal_result is None:
            return

        Telemetry.inc("total_signals")

        # Signal dedup: skip if we just saw the same side signal for this symbol
        now = time.time()
        last_sig = self._last_signal.get(symbol)
        if last_sig and last_sig[0] == signal_result.side:
            elapsed = now - last_sig[1]
            if elapsed < self._signal_dedup_seconds:
                return  # same signal, skip silently
        self._last_signal[symbol] = (signal_result.side, now)

        # LLM triggers: detect meaningful decision boundaries
        num_agree = signal_result.metadata.get("num_agree", 1)

        # High-confidence signal trigger (>=75%)
        if signal_result.confidence >= 75:
            self._llm_triggers.add(
                LLMTrigger.HIGH_CONFIDENCE,
                symbol=symbol,
                context=f"{symbol} {signal_result.side} signal "
                        f"conf={signal_result.confidence:.0f}%",
            )

        # Strategy consensus trigger (3+ agree)
        if num_agree >= 3:
            strategies = signal_result.metadata.get("strategies_agree", [])
            self._llm_triggers.add(
                LLMTrigger.STRATEGY_CONSENSUS,
                symbol=symbol,
                context=f"{num_agree} strategies agree on {symbol} "
                        f"{signal_result.side}: {strategies}",
            )

        # Regime shift detection (from strategy metadata) + transition tracking
        current_regime = signal_result.metadata.get("regime", "")
        if current_regime:
            # E2: Feed regime detector for transition detection
            regime_result = self.regime_detector.update(symbol, current_regime)
            if regime_result["transitioning"]:
                signal_result.metadata["regime_transition"] = {
                    "from": regime_result["from_regime"],
                    "to": regime_result["to_regime"],
                    "confidence": regime_result["confidence"],
                }
                # Fire explicit LLM trigger on regime transition
                self._llm_triggers.add(
                    LLMTrigger.REGIME_SHIFT,
                    symbol=symbol,
                    context=f"Regime transition: {regime_result.get('from_regime', '?')} -> "
                            f"{regime_result.get('to_regime', '?')} for {symbol}",
                )
            if self._llm_triggers.check_regime_shift(symbol, current_regime):
                _transition_ctx = ""
                if regime_result.get("transitioning"):
                    _transition_ctx = (
                        f" (transition: {regime_result['from_regime']}->"
                        f"{regime_result['to_regime']} "
                        f"conf={regime_result['confidence']:.0%})"
                    )
                self._llm_triggers.add(
                    LLMTrigger.REGIME_SHIFT,
                    symbol=symbol,
                    context=f"{symbol} regime shifted to '{current_regime}'{_transition_ctx}",
                )

        # Strategy disagreement detection (2 long vs 2 short, or high-conf outlier)
        try:
            statuses = self.ensemble.get_all_status(symbol, data)
            strat_signals = {}
            strat_confs = {}
            for s in statuses:
                strat_name = s.get("strategy", "unknown")
                action = s.get("action", s.get("side", "neutral"))
                if action in ("BUY", "buy"):
                    strat_signals[strat_name] = "long"
                elif action in ("SELL", "sell"):
                    strat_signals[strat_name] = "short"
                else:
                    strat_signals[strat_name] = "neutral"
                conf = s.get("confidence", 0)
                if conf == 0:
                    align_l = s.get("align_long", 0)
                    align_s = s.get("align_short", 0)
                    conf = max(align_l, align_s) / 100.0 if max(align_l, align_s) > 1 else max(align_l, align_s)
                strat_confs[strat_name] = min(conf, 1.0)
            disagreement = self._llm_triggers.check_strategy_disagreement(
                strat_signals, strat_confs
            )
            if disagreement:
                self._llm_triggers.add(
                    LLMTrigger.STRATEGY_DISAGREEMENT,
                    symbol=symbol,
                    context=f"{symbol}: {disagreement}",
                )
        except Exception:
            pass

        # Anti-round-trip: same-direction re-entry after a win needs 10% more confidence
        last_side = self._last_close_side.get(symbol)
        was_win = self._last_close_win.get(symbol, False)
        new_side = "LONG" if signal_result.side == "BUY" else "SHORT"
        if was_win and last_side == new_side and signal_result.confidence < 75:
            log_rejection(symbol, "ANTI_ROUNDTRIP",
                          confidence=signal_result.confidence)
            logger.info(
                f"[{trace_id}][{symbol}] Anti-round-trip: same-dir re-entry "
                f"after win needs >=75% conf (got {signal_result.confidence:.0f}%)"
            )
            return

        # ── Signal Flagger: cheap heuristic flag evaluation ──
        # Runs on every signal (no LLM call). Flags interesting characteristics
        # (SNIPER, ANOMALY, BREAKOUT, etc.) and fires LLM triggers for high-priority flags.
        _flagged_signal = None
        if self.signal_flagger and self.config.enable_signal_flagger:
            try:
                _sf_regime = signal_result.metadata.get("regime", "")
                _sf_vol_ratio = signal_result.metadata.get("volume_ratio", 1.0)
                _sf_funding = self._last_funding_rates.get(symbol, 0.0)
                _sf_pch_1h = self._price_changes_1h.get(symbol, 0.0)

                # BTC trend context for the flagger
                _sf_btc_1h = self._price_changes_1h.get("BTC", 0.0)
                _sf_btc_trend = "bullish" if _sf_btc_1h > 0.5 else ("bearish" if _sf_btc_1h < -0.5 else "neutral")

                _flagged_signal = self.signal_flagger.evaluate_signal(
                    symbol=symbol,
                    side=signal_result.side,
                    confidence=signal_result.confidence,
                    regime=_sf_regime,
                    num_agree=num_agree,
                    total_strategies=len(self.strategies),
                    volume_ratio=_sf_vol_ratio,
                    funding_rate=_sf_funding,
                    btc_trend=_sf_btc_trend,
                    price_change_1h=_sf_pch_1h,
                )

                # High-priority flags fire an LLM trigger for richer meta-brain context
                if _flagged_signal and _flagged_signal.should_trigger_llm:
                    self._llm_triggers.add(
                        LLMTrigger.HIGH_CONFIDENCE,
                        symbol=symbol,
                        context=f"FLAGGED: {_flagged_signal.flag_summary} "
                                f"conf={signal_result.confidence:.0f}%",
                    )
                    logger.info(
                        f"[{trace_id}][{symbol}] Signal flagged: {_flagged_signal.flag_summary}"
                    )

                # Attach flags to metadata for downstream logging
                if _flagged_signal and _flagged_signal.flags:
                    signal_result.metadata["signal_flags"] = _flagged_signal.flag_summary
                    signal_result.metadata["flag_max_priority"] = _flagged_signal.max_priority
            except Exception as e:
                logger.debug(f"[{trace_id}][{symbol}] Signal flagger error: {e}")

        # Log every signal generated to database (even if not traded)
        _signal_id = log_signal(
            symbol=symbol,
            strategy=signal_result.strategy,
            side=signal_result.side,
            confidence=signal_result.confidence,
            entry=signal_result.entry,
            sl=signal_result.sl,
            tp1=signal_result.tp1,
            tp2=signal_result.tp2,
            atr=signal_result.atr,
            leverage=1.0,
            traded=False,
            metadata=signal_result.metadata
        )

        # Log signal (paper trading compatibility)
        if self.trade_logger:
            regime_score = signal_result.metadata.get("align_long", 0) or signal_result.metadata.get("regime_score", 0)
            num_agree = signal_result.metadata.get("num_agree", 1)
            total_strategies = signal_result.metadata.get("total_strategies", len(self.strategies))
            self.trade_logger.log_signal(
                symbol=symbol,
                signal_obj=signal_result,
                trace_id=trace_id,
                regime_score=regime_score,
                num_agree=num_agree,
                total_strategies=total_strategies,
            )

        # ML confidence adjustment (pass full market context for both models)
        original_conf = signal_result.confidence
        ml_volatility = 0.0  # Used by feedback loop below even if ML is disabled
        if self.ml:
            # Compute market context for ML
            ml_pchange_1h = 0.0
            ml_pchange_24h = 0.0
            ml_vol_ratio = 1.0
            ml_volatility = 0.0
            try:
                df_1h = data.get("1h")
                if df_1h is not None and not df_1h.empty and len(df_1h) > 2:
                    ml_pchange_1h = (current_price - float(df_1h["close"].iloc[-2])) / float(df_1h["close"].iloc[-2]) * 100
                    if len(df_1h) > 24:
                        ml_pchange_24h = (current_price - float(df_1h["close"].iloc[-24])) / float(df_1h["close"].iloc[-24]) * 100
                    avg_vol = float(df_1h["volume"].tail(20).mean())
                    if avg_vol > 0:
                        ml_vol_ratio = float(df_1h["volume"].iloc[-1]) / avg_vol
                    if len(df_1h) > 14:
                        prev_c = df_1h["close"].shift(1)
                        tr = pd.concat([
                            df_1h["high"] - df_1h["low"],
                            (df_1h["high"] - prev_c).abs(),
                            (df_1h["low"] - prev_c).abs(),
                        ], axis=1).max(axis=1)
                        atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
                        ml_volatility = atr14 / current_price * 100
            except Exception:
                pass

            adjusted_conf = self.ml.adjust_confidence(
                original_conf,
                regime_score=signal_result.metadata.get("align_long", 0) or signal_result.metadata.get("regime_score", 0),
                vwap_aligned=signal_result.metadata.get("vwap_align", False),
                ema_aligned=signal_result.metadata.get("ema_1h_align", False),
                stop_width_ratio=signal_result.stop_width / max(signal_result.atr, 1e-9) if signal_result.atr else 1.5,
                leverage=1.0,
                side=signal_result.side,
                price_change_1h_pct=ml_pchange_1h,
                price_change_24h_pct=ml_pchange_24h,
                volume_ratio=ml_vol_ratio,
                volatility=ml_volatility,
                num_strategies_agree=signal_result.metadata.get("num_agree", 1),
            )
            signal_result.confidence = adjusted_conf

        # ── Feedback loop: adaptive confidence floor + quality scoring ──
        # Replaces static 65% floor with dynamic, learned thresholds
        try:
            _regime = signal_result.metadata.get("regime", "")
            _entry_type_fb = ""
            _vol_ratio_fb = signal_result.metadata.get("volume_ratio", 1.0)

            should_trade, fb_adjusted_conf, fb_floor, fb_reason = self.feedback.evaluate_signal(
                confidence=signal_result.confidence,
                strategy=signal_result.strategy,
                symbol=symbol,
                regime=_regime,
                side=signal_result.side,
                entry_type=_entry_type_fb,
                num_agree=signal_result.metadata.get("num_agree", 1),
                total_strategies=signal_result.metadata.get("total_strategies", len(self.strategies)),
                volume_ratio=_vol_ratio_fb,
                volatility=ml_volatility if self.ml else 0.0,
                rr1=signal_result.risk_reward_tp1,
                trend_alignment=signal_result.metadata.get("trend_adjustment", 0.0),
            )

            # Apply quality-adjusted confidence
            signal_result.confidence = fb_adjusted_conf

            # Record signal for backtest tracking
            self.feedback.record_signal(
                symbol=symbol,
                side=signal_result.side,
                confidence=signal_result.confidence,
                strategy=signal_result.strategy,
                entry=signal_result.entry,
                sl=signal_result.sl,
                tp1=signal_result.tp1,
                regime=_regime,
                num_agree=signal_result.metadata.get("num_agree", 1),
            )

            if not should_trade:
                # ── Signal Override: can powerful signal bypass feedback floor? ──
                _override_ok = False
                if (self.signal_override and self.config.enable_signal_override
                        and _SIGNAL_OVERRIDE_AVAILABLE):
                    try:
                        _ov_result = should_override_blocker(
                            confidence=signal_result.confidence,
                            num_agree=signal_result.metadata.get("num_agree", 1),
                            total_strategies=len(self.strategies),
                            blocker=BlockerType.CONFIDENCE_FLOOR,
                            blocker_detail=fb_reason,
                            volume_confirms=signal_result.metadata.get("volume_ratio", 1.0) >= 1.5,
                            regime_aligned=_regime in ("trend", "trending"),
                            trend_aligned=signal_result.metadata.get("trend_adjustment", 0) > 0,
                            current_equity=self.risk_mgr.equity,
                            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
                        )
                        if _ov_result.should_override:
                            _override_ok = True
                            logger.info(
                                f"[{trace_id}][{symbol}] OVERRIDE: feedback floor bypassed "
                                f"(power={_ov_result.power_score:.0f}, {_ov_result.reason})"
                            )
                    except Exception as e:
                        logger.debug(f"Signal override feedback error: {e}")

                if not _override_ok:
                    logger.info(f"[{trace_id}][{symbol}] Feedback floor: {fb_reason}")
                    return
        except Exception as e:
            logger.warning(f"[{trace_id}][{symbol}] Feedback loop error (proceeding): {e}")

        # ── Circuit breaker check (with high-confidence override) ──
        if not self.risk_mgr.can_open_position(
            self.pos_mgr.get_open_count(),
            confidence=signal_result.confidence,
            cb_conf_override_pct=self.config.cb_conf_override_pct,
        ):
            # ── Signal Override: can powerful signal bypass circuit breaker? ──
            _cb_override_ok = False
            if (self.signal_override and self.config.enable_signal_override
                    and _SIGNAL_OVERRIDE_AVAILABLE):
                try:
                    _cb_blocker = BlockerType.CIRCUIT_BREAKER
                    if self.risk_mgr.circuit_breaker.consecutive_losses >= self.config.max_consecutive_losses:
                        _cb_blocker = BlockerType.CONSECUTIVE_LOSSES

                    _cb_ov_result = should_override_blocker(
                        confidence=signal_result.confidence,
                        num_agree=signal_result.metadata.get("num_agree", 1),
                        total_strategies=len(self.strategies),
                        blocker=_cb_blocker,
                        volume_confirms=signal_result.metadata.get("volume_ratio", 1.0) >= 1.5,
                        regime_aligned=signal_result.metadata.get("regime", "") in ("trend", "trending"),
                        trend_aligned=signal_result.metadata.get("trend_adjustment", 0) > 0,
                        current_equity=self.risk_mgr.equity,
                        daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
                    )
                    if _cb_ov_result.should_override:
                        _cb_override_ok = True
                        logger.warning(
                            f"[{trace_id}][{symbol}] OVERRIDE: circuit breaker bypassed "
                            f"(power={_cb_ov_result.power_score:.0f}, {_cb_ov_result.reason})"
                        )
                except Exception as e:
                    logger.debug(f"Signal override CB error: {e}")

            if not _cb_override_ok:
                return

        # Portfolio leverage guard: block new entries when total leverage too high
        _portfolio_lev = self._compute_portfolio_leverage()
        _max_portfolio_lev = max(self.config.max_portfolio_leverage * 2.5, 8.0)  # Notional-based cap is primary
        if _portfolio_lev >= _max_portfolio_lev:
            log_rejection(symbol, "PORTFOLIO_LEVERAGE",
                          confidence=signal_result.confidence,
                          portfolio_leverage=_portfolio_lev)
            logger.info(
                f"[{trace_id}][{symbol}] Portfolio leverage guard: "
                f"{_portfolio_lev:.1f}x >= {_max_portfolio_lev:.1f}x max"
            )
            return

        # Get CB override constraints (graduated risk during CB override)
        cb_constraints = self.risk_mgr.circuit_breaker.get_override_constraints(
            confidence=signal_result.confidence
        )

        # ── Risk filters (all rejections logged to data/logs/risk_rejections.csv) ──
        rr1 = signal_result.risk_reward_tp1
        sl_distance = signal_result.stop_width

        # R:R sanity filter
        if rr1 < 0.5:
            log_rejection(symbol, "rr1_too_low", rr1=rr1, sl_distance=sl_distance,
                          confidence=signal_result.confidence)
            logger.info(f"[{trace_id}][{symbol}] Rejected: R:R1={rr1:.2f} < 0.5")
            return

        # SL too tight relative to ATR (noise will stop us out)
        if signal_result.atr > 0 and sl_distance < signal_result.atr * 0.5:
            log_rejection(symbol, "sl_too_tight", rr1=rr1, sl_distance=sl_distance,
                          confidence=signal_result.confidence)
            logger.info(f"[{trace_id}][{symbol}] Rejected: SL distance {sl_distance:.4f} < 0.5*ATR")
            return

        # Determine leverage
        num_agree = signal_result.metadata.get("num_agree", 1)
        total = signal_result.metadata.get("total_strategies", len(self.strategies))
        extreme_count = sum(1 for p in open_pos.values() if p.leverage > 5.0)

        lev_decision = self.leverage_mgr.decide(
            signal_result.confidence,
            num_agree,
            total,
            sym_cfg.risk_tier,
            extreme_count,
        )

        if lev_decision.leverage <= 0:
            return  # Confidence too low

        # Feedback-driven leverage cap (learned from backtest performance)
        try:
            _fb_regime = signal_result.metadata.get("regime", "")
            fb_lev_cap = self.feedback.get_leverage_cap(symbol, _fb_regime)
            if lev_decision.leverage > fb_lev_cap:
                lev_decision.leverage = fb_lev_cap
                lev_decision.reason = f"feedback-capped to {fb_lev_cap:.0f}x"
        except Exception:
            pass  # Feedback failure shouldn't block trading

        # Circuit breaker override constraints: cap leverage during CB
        if cb_constraints.get("constrained"):
            cb_max_lev = cb_constraints["max_leverage"]
            if lev_decision.leverage > cb_max_lev:
                logger.info(
                    f"[{trace_id}][{symbol}] CB override: leverage {lev_decision.leverage:.1f}x → {cb_max_lev:.1f}x"
                )
                lev_decision.leverage = cb_max_lev
                lev_decision.reason = f"CB override capped to {cb_max_lev:.0f}x"

        # Self-Tuning Risk: dynamic leverage cap based on drawdown
        try:
            dyn_lev_cap = get_dynamic_leverage_cap(self.config.max_leverage)
            if lev_decision.leverage > dyn_lev_cap:
                logger.info(
                    f"[{trace_id}][{symbol}] Risk-tune: leverage "
                    f"{lev_decision.leverage:.1f}x → {dyn_lev_cap:.1f}x (drawdown cap)"
                )
                lev_decision.leverage = dyn_lev_cap
        except Exception:
            pass

        # Per-symbol leverage cap from precision config
        sym_max_lev = get_max_leverage(symbol)
        if lev_decision.leverage > sym_max_lev:
            lev_decision.leverage = sym_max_lev
            lev_decision.reason = f"capped to {sym_max_lev}x ({symbol} limit)"

        # Extra R:R gate for high leverage: need R:R1 >= 1.0 above 8x
        if lev_decision.leverage > 8.0 and rr1 < 1.0:
            log_rejection(symbol, "rr1_too_low_high_lev", rr1=rr1,
                          leverage=lev_decision.leverage,
                          confidence=signal_result.confidence)
            logger.info(
                f"[{trace_id}][{symbol}] Rejected: R:R1={rr1:.2f} < 1.0 at {lev_decision.leverage:.1f}x"
            )
            return

        # ── Rotation candidate collection ──
        # If we already have a position in this symbol or are at max positions,
        # don't open a new position — but save the signal as a potential rotation
        # target for other open positions that may want to rotate into this one.
        if has_position or at_max_positions:
            if self.rotation_mgr and not has_position:
                self._tick_candidates.append({
                    "symbol": symbol,
                    "side": signal_result.side,
                    "entry": signal_result.entry,
                    "sl": signal_result.sl,
                    "tp1": signal_result.tp1,
                    "tp2": signal_result.tp2,
                    "atr": signal_result.atr,
                    "confidence": signal_result.confidence,
                    "align_score": signal_result.metadata.get("num_agree", 1),
                    "strategy": signal_result.strategy,
                    "rr1": rr1,
                })
            return

        # ── Wave 2: Signal Decay — reduce confidence for stale signals ──
        _signal_gen_time = signal_result.metadata.get("generated_at", 0)
        if _signal_gen_time and self.config.signal_decay_seconds > 0:
            _signal_age = time.time() - _signal_gen_time
            if _signal_age > self.config.signal_decay_seconds:
                _decay = max(0.8, 1.0 - (_signal_age - 60) / 600)
                signal_result.confidence *= _decay
                logger.info(
                    f"[{trace_id}][{symbol}] Signal decay: {_signal_age:.0f}s old, "
                    f"conf * {_decay:.2f} = {signal_result.confidence:.0f}%"
                )

        # ── Wave 2: Liquidity Guard — reject dead markets, reduce size in thin liquidity ──
        _liq_size_mult = 1.0
        if self.config.enable_liquidity_guard and _LIQUIDITY_GUARD_AVAILABLE:
            try:
                _liq_result = validate_liquidity(
                    symbol=symbol,
                    volume_ratio=signal_result.metadata.get("volume_ratio", 1.0),
                    funding_rate=self._last_funding_rates.get(symbol, 0.0),
                )
                if not _liq_result.can_trade:
                    log_rejection(symbol, "LIQUIDITY_GUARD",
                                  confidence=signal_result.confidence)
                    logger.info(
                        f"[{trace_id}][{symbol}] Liquidity guard: {_liq_result.reason}"
                    )
                    return
                _liq_size_mult = _liq_result.size_multiplier
                if _liq_size_mult < 1.0:
                    logger.info(
                        f"[{trace_id}][{symbol}] Liquidity guard: "
                        f"size * {_liq_size_mult:.2f} ({_liq_result.reason})"
                    )
            except Exception as e:
                logger.debug(f"Liquidity guard error: {e}")

        # ── Push 1: Funding rate entry filter ──
        # Reject entries near negative funding (avoid paying funding right after entry)
        if self.config.enable_funding_check:
            _fr_entry = self._last_funding_rates.get(symbol, 0.0)
            if _fr_entry != 0 and lev_decision.leverage > 2.0:
                _side_lower = side.lower()
                _is_paying = (
                    (_side_lower == "long" and _fr_entry > 0) or
                    (_side_lower == "short" and _fr_entry < 0)
                )
                if _is_paying and abs(_fr_entry) > 0.0005:
                    from execution.funding_timer import minutes_until_next_funding
                    _mins = minutes_until_next_funding()
                    if _mins < 60:
                        log_rejection(symbol, "FUNDING_ENTRY_FILTER",
                                      confidence=signal_result.confidence,
                                      funding_rate=_fr_entry)
                        logger.info(
                            f"[{trace_id}][{symbol}] Funding entry filter: "
                            f"{side} at {lev_decision.leverage:.0f}x, rate={_fr_entry:.5f}, "
                            f"{_mins}min to payment — skipping"
                        )
                        return

        # ── Push 1: Min profit threshold gate ──
        # Reject trades where TP1 profit < min_mult * total expected costs
        _tp1_distance_pct = abs(signal_result.tp1 - signal_result.entry) / signal_result.entry if signal_result.entry > 0 else 0
        _total_cost_pct = (self.config.taker_fee_bps + self.config.slippage_bps) * 2 / 10000.0
        if _tp1_distance_pct < self.config.min_profit_threshold_mult * _total_cost_pct:
            log_rejection(symbol, "MIN_PROFIT_THRESHOLD",
                          confidence=signal_result.confidence,
                          tp1_pct=_tp1_distance_pct * 100,
                          cost_pct=_total_cost_pct * 100)
            logger.info(
                f"[{trace_id}][{symbol}] Min profit gate: "
                f"TP1 distance={_tp1_distance_pct*100:.3f}% < "
                f"{self.config.min_profit_threshold_mult}x costs={_total_cost_pct*100:.3f}%"
            )
            return

        # ── Push 1: Per-symbol parameter overrides ──
        _sym_max_lev = get_symbol_param(symbol, "max_leverage", self.config)
        if lev_decision.leverage > _sym_max_lev:
            logger.info(
                f"[{trace_id}][{symbol}] Per-symbol override: "
                f"leverage {lev_decision.leverage:.1f}x → {_sym_max_lev:.1f}x"
            )
            lev_decision.leverage = _sym_max_lev
        _sym_risk = get_symbol_param(symbol, "risk_per_trade", self.config)

        # Calculate position size (risk-based: qty = risk$ / (stop_dist * leverage))
        qty = self.risk_mgr.calculate_qty(
            signal_result.entry, signal_result.sl,
            leverage=lev_decision.leverage,
            risk_multiplier=lev_decision.risk_multiplier,
            symbol=symbol,
            slippage_bps=self.config.slippage_bps,
        )
        if qty <= 0:
            return

        # Circuit breaker override: reduce size during CB
        if cb_constraints.get("constrained"):
            cb_size_mult = cb_constraints["size_multiplier"]
            qty = qty * cb_size_mult
            logger.info(
                f"[{trace_id}][{symbol}] CB override: qty * {cb_size_mult:.2f} = {qty:.6f}"
            )

        # Portfolio correlation guard: reduce size for correlated same-direction trades
        try:
            corr_info = self._compute_portfolio_correlation()
            if corr_info["risk_level"] == "high":
                qty = qty * 0.70  # 30% reduction
                logger.info(f"[{trace_id}][{symbol}] Correlation guard (high): qty * 0.70")
            elif corr_info["risk_level"] == "medium":
                qty = qty * 0.85  # 15% reduction
                logger.info(f"[{trace_id}][{symbol}] Correlation guard (medium): qty * 0.85")
        except Exception:
            pass

        # Global Brain bias: adjust sizing based on macro regime
        try:
            _gb_size_mult = self._global_bias_adjustment.get("size_multiplier", 1.0)
            if _gb_size_mult != 1.0:
                qty = qty * _gb_size_mult
                logger.info(
                    f"[{trace_id}][{symbol}] Global bias ({self._global_bias}): "
                    f"qty * {_gb_size_mult:.2f} = {qty:.6f}"
                )
        except Exception:
            pass

        # Wave 3: Portfolio Risk Engine — dynamic position limits based on correlation/vol
        if self.portfolio_risk:
            try:
                _pr_limit = self.portfolio_risk.get_position_limit(
                    symbol=symbol,
                    side=side,
                    open_positions={s: {"side": p.side, "entry": p.entry, "qty": p.qty, "leverage": p.leverage}
                                   for s, p in open_pos.items()},
                    equity=self.risk_mgr.equity,
                )
                _pr_max_pct = _pr_limit.get("max_qty_pct", 1.0)
                if _pr_max_pct < 1.0:
                    qty = qty * _pr_max_pct
                    logger.info(
                        f"[{trace_id}][{symbol}] Portfolio risk limit: "
                        f"qty * {_pr_max_pct:.2f} ({_pr_limit.get('reason', '')})"
                    )
            except Exception as e:
                logger.debug(f"Portfolio risk limit error: {e}")

        # Time-aware sizing: reduce during weekends / low-liquidity hours
        time_mult = get_time_multiplier()
        if time_mult < 1.0:
            qty = qty * time_mult
            logger.info(
                f"[{trace_id}][{symbol}] Time sizing: qty * {time_mult:.2f} = {qty:.6f}"
            )

        # Liquidity guard sizing (applied after all other multipliers)
        if _liq_size_mult < 1.0:
            qty = qty * _liq_size_mult
            logger.info(
                f"[{trace_id}][{symbol}] Liquidity guard sizing: "
                f"qty * {_liq_size_mult:.2f} = {qty:.6f}"
            )

        # Enforce minimum order size
        min_q = get_min_qty(symbol)
        if qty < min_q:
            log_rejection(symbol, "BELOW_MIN_QTY", confidence=signal_result.confidence)
            logger.info(f"[{trace_id}][{symbol}] Rejected: qty {qty} < min {min_q}")
            return

        # ── Trade Classification Layer ──
        # Classify trade -> TradeProfile (drives exits, TP1%, trailing)
        # Add volume_ratio to metadata for regime detection
        try:
            df_1h_vol = data.get("1h")
            if df_1h_vol is not None and not df_1h_vol.empty and len(df_1h_vol) >= 20:
                avg_v = float(df_1h_vol["volume"].tail(20).mean())
                cur_v = float(df_1h_vol["volume"].iloc[-1])
                if avg_v > 0:
                    signal_result.metadata["volume_ratio"] = cur_v / avg_v
        except Exception:
            pass

        trade_prof = classify_trade(
            signal_metadata=signal_result.metadata,
            confidence=signal_result.confidence,
            atr=signal_result.atr,
            entry=signal_result.entry,
            side=signal_result.side,
        )

        # ── CB entry_type filter: when CB is active, only allow TREND/REGIME ──
        if self.risk_mgr.circuit_breaker.tripped:
            allowed_types = ("TREND", "REGIME")
            if trade_prof.entry_type not in allowed_types:
                log_rejection(
                    symbol, "CB_HIGH_CONF_ONLY",
                    confidence=signal_result.confidence,
                    rr1=signal_result.risk_reward_tp1,
                )
                logger.info(
                    f"[SAFETY] CB active: rejecting {trade_prof.entry_type} trade "
                    f"(only {allowed_types} allowed during CB)"
                )
                return

        # Apply profile-recommended TP1/SL/TP2 (overrides strategy levels)
        adjusted = apply_profile_to_signal(
            trade_prof,
            entry=signal_result.entry,
            sl=signal_result.sl,
            tp1=signal_result.tp1,
            tp2=signal_result.tp2,
            atr=signal_result.atr,
            side=signal_result.side,
        )
        adj_sl = adjusted["sl"]
        adj_tp1 = adjusted["tp1"]
        adj_tp2 = adjusted["tp2"]
        tp1_pct = adjusted["tp1_close_pct"]

        # Build entry reasons: WHY this trade was entered (for EV analysis)
        # Extract LLM decision info from candidate (if LLM was involved)
        _cand_llm_action = candidate.llm_action if hasattr(candidate, 'llm_action') and candidate.llm_action else ""
        _cand_llm_conf = candidate.llm_confidence if hasattr(candidate, 'llm_confidence') and candidate.llm_confidence else 0.0

        entry_reasons = {
            "strategies_agree": signal_result.metadata.get("strategies_agree", []),
            "num_agree": num_agree,
            "trend_adjustment": signal_result.metadata.get("trend_adjustment", 0),
            "regime_score": signal_result.metadata.get("align_long", 0) or signal_result.metadata.get("regime_score", 0),
            "individual_confidences": signal_result.metadata.get("individual_confidences", {}),
            "mode": signal_result.metadata.get("mode", ""),
            "rr1": round(rr1, 2),
            "ml_adjusted": original_conf != signal_result.confidence,
            "entry_type": trade_prof.entry_type,
            "primary_driver": trade_prof.primary_driver,
            "regime": trade_prof.regime,
            "volatility_band": trade_prof.volatility_band,
            # LLM decision data for feedback loop
            "llm_action": _cand_llm_action,
            "llm_confidence": _cand_llm_conf,
            "llm_agreed": _cand_llm_action in ("proceed", "go", "", None),
            # Signal flagger data for post-trade analysis
            "signal_flags": signal_result.metadata.get("signal_flags", ""),
            "flag_max_priority": signal_result.metadata.get("flag_max_priority", 0),
        }

        # Correlation guard: max same-direction positions
        side = "LONG" if signal_result.side == "BUY" else "SHORT"
        same_dir_count = sum(1 for p in open_pos.values() if p.side == side)
        if same_dir_count >= self._max_same_direction:
            log_rejection(symbol, "CORRELATION_GUARD",
                          confidence=signal_result.confidence)
            logger.info(
                f"[{trace_id}][{symbol}] Correlation guard: "
                f"{same_dir_count} {side} positions open (max {self._max_same_direction})"
            )
            return

        # LLM trigger: about to open a position (highest priority)
        self._llm_triggers.add(
            LLMTrigger.PRE_TRADE,
            symbol=symbol,
            context=f"Opening {side} {symbol} @ {_fmt_price(signal_result.entry)} "
                    f"lev={lev_decision.leverage:.1f}x conf={signal_result.confidence:.0f}% "
                    f"type={trade_prof.entry_type}",
        )

        # ── VETO_ONLY+ mode: synchronous LLM check before trade entry ──
        # Build a TradeCandidate for dual-world logging regardless of mode
        candidate = TradeCandidate(
            symbol=symbol,
            side=side,
            entry=signal_result.entry,
            sl=adj_sl,
            tp1=adj_tp1,
            tp2=adj_tp2,
            atr=signal_result.atr,
            ensemble_confidence=signal_result.confidence,
            ensemble_strategy=signal_result.strategy,
            entry_type=trade_prof.entry_type,
            primary_driver=trade_prof.primary_driver,
            regime=trade_prof.regime,
            timestamp=time.time(),
            trace_id=trace_id,
            num_agree=num_agree,
            strategies_agree=signal_result.metadata.get("strategies_agree", []),
            risk_reward_tp1=rr1,
        )

        if llm_has_veto(self.llm_mode):
            veto_result = self._llm_veto_check(candidate, trace_id)
            if veto_result is not None:
                # LLM vetoed this trade
                candidate.llm_action = "flat"
                candidate.llm_confidence = veto_result.decision.confidence if veto_result.decision else None
                candidate.llm_regime = veto_result.decision.regime if veto_result.decision else None
                candidate.llm_notes = veto_result.decision.notes if veto_result.decision else veto_result.reason
                candidate.leverage_used = lev_decision.leverage
                self._candidate_logger.log_candidate(candidate)

                log_rejection(symbol, "LLM_VETO",
                              confidence=signal_result.confidence)
                logger.info(
                    f"[{trace_id}][{symbol}] LLM VETO: {side} trade rejected | "
                    f"reason: {veto_result.reason}"
                )
                self.alerts.send_market_update(
                    f"[LLM VETO] {symbol} {side} {trade_prof.entry_type} "
                    f"conf={signal_result.confidence:.0f}% "
                    f"lev={lev_decision.leverage:.1f}x\n"
                    f"Reason: {candidate.llm_notes or 'no reason given'}"
                )

                # Growth intelligence: track veto for outcome analysis
                try:
                    self.growth.on_veto(
                        symbol=symbol,
                        side=side,
                        confidence=signal_result.confidence,
                        entry_price=signal_result.entry,
                        sl_price=signal_result.sl,
                        tp1_price=signal_result.tp1,
                        tp2_price=signal_result.tp2,
                        llm_reason=candidate.llm_notes or "",
                        regime=signal_result.metadata.get("regime", ""),
                        trigger="pre_trade_veto",
                        strategies_agreed=num_agree,
                    )
                except Exception as e:
                    logger.debug(f"Growth veto record error: {e}")

                # Learning Mode: record counterfactual for veto accuracy tracking
                if _LEARNING_MODE_AVAILABLE and is_learning_mode_active():
                    try:
                        record_counterfactual(
                            llm_would_have_vetoed=True,
                            actual_outcome="PENDING",  # Will be resolved later
                            pnl=0.0,
                            symbol=symbol,
                            reasoning=candidate.llm_notes or "",
                        )
                    except Exception:
                        pass

                # Wave 4: Counterfactual — record vetoed trade for later resolution
                if self.counterfactual:
                    try:
                        self.counterfactual.record_veto(
                            symbol=symbol,
                            side=side,
                            entry_price=signal_result.entry,
                            sl_price=signal_result.sl,
                            tp1_price=signal_result.tp1,
                            tp2_price=signal_result.tp2,
                            confidence=signal_result.confidence,
                            reason=candidate.llm_notes or "LLM veto",
                        )
                    except Exception as e:
                        logger.debug(f"Counterfactual veto record error: {e}")

                # Learning Mode: in ABSORB phase, override veto to proceed
                if _LEARNING_MODE_AVAILABLE and is_learning_mode_active():
                    try:
                        _lm_action, _lm_size, _lm_reason = apply_learning_constraints(
                            llm_action="flat",
                            llm_confidence=candidate.llm_confidence or 0.5,
                            llm_size_multiplier=1.0,
                            signal_confidence=signal_result.confidence,
                        )
                        if _lm_action != "flat":
                            logger.info(
                                f"[{trace_id}][{symbol}] Learning mode OVERRIDE: "
                                f"veto -> {_lm_action} ({_lm_reason})"
                            )
                            candidate.llm_action = _lm_action
                            # Fall through to proceed instead of returning
                        else:
                            return  # Veto still stands
                    except Exception:
                        return  # Default: respect veto if learning mode fails
                else:
                    return
            else:
                # LLM approved (or API failed -> default proceed)
                candidate.llm_action = "proceed"
                if veto_result is None:
                    # _llm_veto_check returns None for proceed
                    pass

        # Learning Mode: record signal observation
        if _LEARNING_MODE_AVAILABLE and is_learning_mode_active():
            try:
                learning_record_signal(
                    symbol=symbol,
                    side=side,
                    confidence=signal_result.confidence,
                    regime=signal_result.metadata.get("regime", ""),
                    strategies=signal_result.metadata.get("strategies_agree", [signal_result.strategy]),
                    num_agree=num_agree,
                )
            except Exception:
                pass

        # Log candidate as proceeding (will be updated with outcome on close)
        candidate.llm_action = candidate.llm_action or "no_llm"
        candidate.leverage_used = lev_decision.leverage
        self._candidate_logger.log_candidate(candidate)

        # ── LLM size multiplier: apply the meta-brain's sizing adjustment ──
        # In SIZING+ modes, the LLM can scale position size 0.5x-2.0x
        llm_sz = getattr(candidate, 'llm_size_mult', None)
        if llm_sz is not None and llm_sz != 1.0 and self.llm_mode >= LLMMode.SIZING:
            # Learning Mode: constrain size adjustment during learning phases
            if _LEARNING_MODE_AVAILABLE and is_learning_mode_active():
                try:
                    _, llm_sz, _lm_reason = apply_learning_constraints(
                        llm_action="proceed",
                        llm_confidence=candidate.llm_confidence or 0.5,
                        llm_size_multiplier=llm_sz,
                        signal_confidence=signal_result.confidence,
                    )
                except Exception:
                    pass
            llm_sz = max(0.5, min(2.0, llm_sz))  # Safety clamp
            qty = qty * llm_sz
            logger.info(
                f"[{trace_id}][{symbol}] LLM size mult: qty * {llm_sz:.2f} = {qty:.6f}"
            )

        # ── Adaptive Risk: dynamic risk-per-trade multiplier based on streak/regime ──
        if self.adaptive_risk:
            try:
                _regime_label = signal_result.metadata.get("regime", "")
                _sym_wr = self.feedback.quality.get_symbol_win_rate(symbol) if hasattr(self.feedback.quality, 'get_symbol_win_rate') else 0.0
                _ar_mult = self.adaptive_risk.get_risk_multiplier(
                    regime=_regime_label,
                    symbol_wr=_sym_wr,
                )
                if _ar_mult != 1.0:
                    qty = qty * _ar_mult
                    logger.info(
                        f"[{trace_id}][{symbol}] Adaptive risk: qty * {_ar_mult:.3f} = {qty:.6f}"
                    )
            except Exception as e:
                logger.debug(f"Adaptive risk application error: {e}")

        # ── RL policy multiplier: apply learned regime/symbol adjustments ──
        if is_rl_enabled():
            try:
                _rl_regime = signal_result.metadata.get("regime", "unknown")
                _rl_mult = get_combined_rl_multiplier(symbol, _rl_regime)
                if _rl_mult != 1.0:
                    qty = qty * _rl_mult
                    logger.info(
                        f"[{trace_id}][{symbol}] RL policy: qty * {_rl_mult:.2f} = {qty:.6f}"
                    )
            except Exception as e:
                logger.debug(f"RL policy application error: {e}")

        # ── Profitable pattern boost: confirmed winners get larger size ──
        # Uses deep memory: if this strategy+regime+symbol combo has >60% WR
        # over 10+ trades, allow up to 1.3x size boost
        try:
            sym_data = self.feedback.quality.by_symbol.get(symbol)
            strat_data = self.feedback.quality.by_strategy.get(signal_result.strategy)
            regime_data = self.feedback.quality.by_regime.get(
                signal_result.metadata.get("regime", "")
            )
            # Need at least one dimension with enough data
            pattern_boost = 1.0
            if sym_data and sym_data["total"] >= 10:
                sym_wr = sym_data["wins"] / sym_data["total"]
                if sym_wr >= 0.60:
                    pattern_boost = max(pattern_boost, 1.0 + (sym_wr - 0.50) * 0.6)
            if strat_data and strat_data["total"] >= 10:
                strat_wr = strat_data["wins"] / strat_data["total"]
                if strat_wr >= 0.60:
                    pattern_boost = max(pattern_boost, 1.0 + (strat_wr - 0.50) * 0.6)
            # Regime alignment: if this regime has good WR, boost
            if regime_data and regime_data["total"] >= 8:
                reg_wr = regime_data["wins"] / regime_data["total"]
                if reg_wr >= 0.55:
                    pattern_boost = max(pattern_boost, 1.0 + (reg_wr - 0.50) * 0.4)
            # Cap at 1.3x (confirmed profitable = up to 30% more aggressive)
            pattern_boost = min(1.3, pattern_boost)
            if pattern_boost > 1.0:
                qty = qty * pattern_boost
                logger.info(
                    f"[{trace_id}][{symbol}] Profitable pattern boost: "
                    f"qty * {pattern_boost:.2f} = {qty:.6f}"
                )
        except Exception:
            pass

        # ── Push 1: Portfolio notional cap ──
        # Prevent aggregate over-leverage across all positions
        _new_notional = qty * signal_result.entry * lev_decision.leverage
        if not self.pos_mgr.check_portfolio_notional_cap(
            new_notional=_new_notional,
            equity=self.risk_mgr.equity,
            max_portfolio_leverage=self.config.max_portfolio_leverage,
        ):
            log_rejection(symbol, "PORTFOLIO_NOTIONAL_CAP",
                          confidence=signal_result.confidence,
                          new_notional=_new_notional)
            return

        # ── OpsGuard: rate limiting, exposure limits ──
        position_size_usd = qty * signal_result.entry * lev_decision.leverage
        total_exposure = sum(
            p.qty * p.entry * p.leverage
            for p in self.pos_mgr.get_open_positions().values()
        )
        ops_check = self.ops_guard.can_execute(
            position_size_usd=position_size_usd,
            equity=self.risk_mgr.equity,
            total_exposure_usd=total_exposure,
        )
        if not ops_check["allowed"]:
            Telemetry.inc("throttle_blocks")
            log_rejection(symbol, "OPS_GUARD", confidence=signal_result.confidence)
            logger.warning(f"[{trace_id}][{symbol}] OPS GUARD: {ops_check['reason']}")
            return

        # ── LIVE PRICE ENTRY: fetch fresh price right before opening ──
        # signal_result.entry is the stale candle-close price from strategy eval.
        # We need the actual live market price for accurate entry/TP/SL/PnL.
        snapshot_entry = signal_result.entry
        live_entry = self.fetcher.fetch_live_price(symbol)
        if live_entry is None:
            live_entry = current_price  # fall back to tick-start price

        # Compute slippage between signal snapshot and live execution price
        slippage_pct = abs(live_entry - snapshot_entry) / snapshot_entry * 100 if snapshot_entry > 0 else 0
        max_slippage = float(os.getenv("MAX_ENTRY_SLIPPAGE_PCT", "1.5"))

        if slippage_pct > max_slippage:
            log_rejection(symbol, "ENTRY_SLIPPAGE",
                          confidence=signal_result.confidence)
            logger.warning(
                f"[{trace_id}][{symbol}] ENTRY REJECTED: slippage {slippage_pct:.2f}% "
                f"(snapshot={_fmt_price(snapshot_entry)} live={_fmt_price(live_entry)} "
                f"max={max_slippage}%)"
            )
            return

        # Use live price as actual entry
        actual_entry = live_entry

        # Shift TP/SL proportionally to match the live entry price
        entry_shift = actual_entry - snapshot_entry
        adj_sl = adj_sl + entry_shift
        adj_tp1 = adj_tp1 + entry_shift
        adj_tp2 = adj_tp2 + entry_shift

        # Safety: ensure SL/TP are still on the correct side of entry
        if side == "LONG":
            if adj_sl >= actual_entry:
                adj_sl = actual_entry - signal_result.atr * 1.5 if signal_result.atr > 0 else actual_entry * 0.98
            if adj_tp1 <= actual_entry:
                adj_tp1 = actual_entry + signal_result.atr * 1.0 if signal_result.atr > 0 else actual_entry * 1.01
            if adj_tp2 <= actual_entry:
                adj_tp2 = actual_entry + signal_result.atr * 2.0 if signal_result.atr > 0 else actual_entry * 1.02
        else:  # SHORT
            if adj_sl <= actual_entry:
                adj_sl = actual_entry + signal_result.atr * 1.5 if signal_result.atr > 0 else actual_entry * 1.02
            if adj_tp1 >= actual_entry:
                adj_tp1 = actual_entry - signal_result.atr * 1.0 if signal_result.atr > 0 else actual_entry * 0.99
            if adj_tp2 >= actual_entry:
                adj_tp2 = actual_entry - signal_result.atr * 2.0 if signal_result.atr > 0 else actual_entry * 0.98

        # Recalculate qty with live entry price (stop distance may have changed)
        live_sl_dist = abs(actual_entry - adj_sl)
        snapshot_sl_dist = abs(snapshot_entry - (adj_sl - entry_shift))
        if snapshot_sl_dist > 0 and live_sl_dist > 0:
            # Scale qty to maintain the same dollar risk
            qty = qty * (snapshot_sl_dist / live_sl_dist)
            min_q = get_min_qty(symbol)
            if qty < min_q:
                log_rejection(symbol, "BELOW_MIN_QTY_LIVE", confidence=signal_result.confidence)
                logger.info(f"[{trace_id}][{symbol}] Rejected: live-adjusted qty {qty} < min {min_q}")
                return

        if slippage_pct > 0.1:
            logger.info(
                f"[{trace_id}][{symbol}] Entry slippage: {slippage_pct:.2f}% "
                f"(snapshot={_fmt_price(snapshot_entry)} -> live={_fmt_price(actual_entry)})"
            )

        # Track snapshot vs live for dual-entry analysis
        entry_reasons["snapshot_entry"] = snapshot_entry
        entry_reasons["live_entry"] = actual_entry
        entry_reasons["entry_slippage_pct"] = round(slippage_pct, 4)

        # Collect as rotation candidate for other open positions
        if self.rotation_mgr:
            self._tick_candidates.append({
                "symbol": symbol,
                "side": signal_result.side,
                "entry": actual_entry,
                "sl": adj_sl,
                "tp1": adj_tp1,
                "tp2": adj_tp2,
                "atr": signal_result.atr,
                "confidence": signal_result.confidence,
                "align_score": signal_result.metadata.get("num_agree", 1),
                "strategy": signal_result.strategy,
                "rr1": rr1,
            })

        # Telemetry: record trade and slippage
        Telemetry.inc("total_trades")
        Telemetry.record("slippages", slippage_pct)
        self.ops_guard.record_trade()

        # Open position with LIVE price as entry
        self.pos_mgr.open_position(
            symbol=symbol,
            side=side,
            entry=actual_entry,
            qty=qty,
            sl=adj_sl,
            tp1=adj_tp1,
            tp2=adj_tp2,
            atr=signal_result.atr,
            leverage=lev_decision.leverage,
            mode=lev_decision.mode,
            strategy=signal_result.strategy,
            confidence=signal_result.confidence,
            tp1_close_pct=tp1_pct,
            entry_reasons=entry_reasons,
            trade_profile=trade_prof,
        )

        # Log trade open to database (with live price)
        log_trade(
            symbol=symbol,
            action="OPEN",
            side=side,
            price=actual_entry,
            qty=qty,
            leverage=lev_decision.leverage,
            strategy=signal_result.strategy,
            metadata={
                "confidence": signal_result.confidence,
                "strategies": signal_result.metadata.get("strategies_agree", []),
                "snapshot_entry": snapshot_entry,
                "live_entry": actual_entry,
                "entry_slippage_pct": round(slippage_pct, 4),
            }
        )

        # Mark the original signal as traded (update, don't duplicate)
        if _signal_id:
            update_signal_traded(_signal_id, traded=True)

        # Send signal alert (enhanced format with actionable data)
        tier = signal_result.metadata.get("tier", "")
        try:
            # Fetch historical win rates for context
            _sp = get_signal_performance(7, symbol=symbol)
            _sym_wr = _sp.get("by_symbol", {}).get(symbol, {}).get("win_rate", 0)
            _sym_trades = _sp.get("by_symbol", {}).get(symbol, {}).get("trades", 0)
            _strat_wr = _sp.get("by_strategy", {}).get(signal_result.strategy, {}).get("win_rate", 0)
            _enhanced_signal = format_signal_telegram(
                symbol=symbol,
                side=side,
                confidence=signal_result.confidence,
                entry=actual_entry,
                sl=signal_result.sl,
                tp1=signal_result.tp1,
                tp2=signal_result.tp2,
                leverage=lev_decision.leverage,
                strategies_agree=signal_result.metadata.get("strategies_agree"),
                num_agree=signal_result.metadata.get("num_agree", 1),
                total_strategies=len(self.strategies),
                regime=trade_prof.regime or "",
                equity=self.risk_mgr.equity,
                risk_per_trade=self.config.risk_per_trade,
                win_rate_symbol=_sym_wr,
                win_rate_strategy=_strat_wr,
                total_trades_symbol=_sym_trades,
            )
            # Send enhanced to Telegram, normal to Discord
            if self.alerts.telegram_token and self.alerts.telegram_chat_id:
                self.alerts._send_telegram(_enhanced_signal)
            self.alerts.send_signal(signal_result, lev_decision.leverage, tier)
        except Exception:
            self.alerts.send_signal(signal_result, lev_decision.leverage, tier)

        logger.info(
            f"[{trace_id}][{symbol}] OPENED {side} | "
            f"Type: {trade_prof.entry_type} | "
            f"Entry: {_fmt_price(actual_entry)} (snap={_fmt_price(snapshot_entry)} slip={slippage_pct:.2f}%) | "
            f"Conf: {original_conf:.0f}%->{signal_result.confidence:.0f}% | "
            f"Lev: {lev_decision.leverage:.1f}x ({lev_decision.reason}) | "
            f"TP1close: {tp1_pct:.0%} | Trail: {trade_prof.exit_params.trailing_style} | "
            f"Regime: {trade_prof.regime} | "
            f"Driver: {trade_prof.primary_driver} | "
            f"Strategies: {signal_result.metadata.get('strategies_agree', [signal_result.strategy])}"
        )

        # Human Copy-Trade Classifier: check if signal qualifies for copy-trading
        if _COPY_CLASSIFIER_AVAILABLE:
            try:
                _copy_result = classify_human_copy_tradable(
                    confidence=signal_result.confidence,
                    regime=trade_prof.regime or "",
                    volatility_band=trade_prof.volatility_band or "",
                    entry_type=trade_prof.entry_type or "",
                    primary_driver=trade_prof.primary_driver or "",
                    leverage=lev_decision.leverage,
                    rr=rr1,
                    snapshot_age_s=slippage_pct,
                    slippage_pct=slippage_pct,
                    circuit_breaker_active=self.risk_mgr.circuit_breaker.tripped,
                )
                if _copy_result.eligible:
                    logger.info(
                        f"[{trace_id}][{symbol}] COPY-TRADABLE: score={_copy_result.score:.0f}"
                    )
                    self.alerts.send_market_update(
                        f"*COPY-TRADE SIGNAL*\n"
                        f"{symbol} {side} @ {_fmt_price(actual_entry)}\n"
                        f"Confidence: {signal_result.confidence:.0f}%\n"
                        f"R:R: {rr1:.2f}\n"
                        f"Leverage: {lev_decision.leverage:.1f}x\n"
                        f"Regime: {trade_prof.regime}\n"
                        f"Type: {trade_prof.entry_type}\n"
                        f"Score: {_copy_result.score:.0f}/100"
                    )
                    # Tag the candidate for copy-trade tracking
                    entry_reasons["human_copy_tradable"] = True
                    entry_reasons["copy_score"] = _copy_result.score
            except Exception as e:
                logger.debug(f"Copy classifier error: {e}")

    # ── Trade Rotation ─────────────────────────────────────────────

    def _evaluate_rotations(self, trace_id: str = ""):
        """
        Evaluate whether any open position should be rotated into a better signal.

        Called once per tick after all symbols have been processed. Uses the
        candidate signals collected during symbol processing.
        """
        open_pos = self.pos_mgr.get_open_positions()
        if not open_pos:
            return

        # Build position dicts compatible with rotation manager
        positions_dict = {}
        for sym, pos in open_pos.items():
            positions_dict[sym] = {
                "symbol": sym,
                "side": pos.side,
                "entry": pos.entry,
                "sl": pos.sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "qty": pos.qty,
                "status": "open",
                "open_time": pos.open_time.isoformat() if pos.open_time else None,
            }

        # Filter candidates: exclude symbols that already have open positions
        # (can't rotate INTO a symbol we already hold)
        candidates = [
            c for c in self._tick_candidates
            if c["symbol"] not in open_pos
        ]

        if not candidates:
            return

        # Get current prices
        current_prices = {sym: self._last_prices[sym]
                          for sym in positions_dict if sym in self._last_prices}

        actions = self.rotation_mgr.evaluate_rotations(
            positions_dict, candidates, current_prices
        )

        for action in actions:
            self._execute_rotation(action, trace_id)

    def _execute_rotation(self, action, trace_id: str = ""):
        """Execute a rotation: close the old position, open the new one."""
        close_symbol = action.close_symbol
        new_signal = action.open_signal
        new_symbol = new_signal["symbol"]

        logger.info(
            f"[{trace_id}] ROTATION: {close_symbol} -> {new_symbol} | "
            f"reason={action.close_reason} | "
            f"current_pnl={action.current_unrealized_pct:+.2f}% | "
            f"old_rr={action.old_rr_ratio:.2f} -> new_rr={action.new_rr_ratio:.2f} "
            f"({action.rr_improvement:.2f}x improvement) | "
            f"new_conf={action.confidence_new:.0f}%"
        )

        # 1. Close the old position
        close_price = self._last_prices.get(close_symbol)
        if close_price is None:
            logger.warning(f"[{trace_id}] Rotation aborted: no price for {close_symbol}")
            return

        close_event = self.pos_mgr.force_close(
            close_symbol, close_price, action.close_reason
        )
        if close_event is None:
            logger.warning(f"[{trace_id}] Rotation aborted: could not close {close_symbol}")
            return

        # Process the close event (equity, logging, ML, etc.)
        self.risk_mgr.update_equity(close_event.pnl - close_event.fee)
        log_trade(
            symbol=close_event.symbol,
            action=close_event.action,
            side=close_event.side,
            price=close_event.price,
            qty=close_event.qty,
            pnl=close_event.pnl,
            fee=close_event.fee,
            leverage=close_event.leverage,
            strategy=close_event.strategy,
            metadata={
                **close_event.metadata,
                "rotation_to": new_symbol,
                "rotation_reason": action.close_reason,
                "rotation_rr_improvement": action.rr_improvement,
            }
        )

        # Record cooldown for the closed symbol
        self._symbol_cooldown[close_symbol] = time.time()
        pos = self.pos_mgr.positions.get(close_symbol)
        if pos:
            self._last_close_win[close_symbol] = pos.realized_pnl > 0
            self._last_close_side[close_symbol] = pos.side

        # Send alert
        self.alerts.send_trade_event(
            action.close_reason, close_symbol,
            f"ROTATION: {close_symbol} -> {new_symbol}\n"
            f"PnL: ${close_event.pnl:+.2f} | R/R improvement: {action.rr_improvement:.1f}x\n"
            f"New signal confidence: {action.confidence_new:.0f}%"
        )

        # 2. Record the rotation
        self.rotation_mgr.record_rotation(action)
        Telemetry.inc("rotations")

        # 3. The new position will be opened on the next tick when
        # the signal is re-evaluated (don't double-open here since
        # the signal may have already been opened in _process_symbol)
        logger.info(
            f"[{trace_id}] Rotation complete: closed {close_symbol}, "
            f"{new_symbol} signal available for entry next tick"
        )

    # ── LLM Exit Intelligence ─────────────────────────────────────

    def _check_llm_exit_suggestions(self):
        """Evaluate open positions for dynamic SL/TP adjustments using the exit engine.

        Uses heuristic rules informed by deep memory data (strategy win rates,
        regime-specific patterns) to decide when to tighten stops on losing patterns
        and widen TPs on confirmed winning patterns.

        Called every 5th tick from _tick_once() to avoid excessive computation.
        """
        if not self.exit_engine:
            return

        open_positions = self.pos_mgr.get_open_positions()
        if not open_positions:
            return

        now = datetime.now(timezone.utc)

        # Deep memory: fetch strategy effectiveness for pattern-aware decisions
        deep_mem = None
        strategy_effectiveness = {}
        if _DEEP_MEMORY_AVAILABLE:
            try:
                deep_mem = get_deep_memory()
                strategy_effectiveness = deep_mem.trade_dna.get_strategy_effectiveness()
            except Exception:
                pass  # Non-critical — fall back to heuristics without memory

        for symbol, pos in open_positions.items():
            try:
                # Respect per-symbol cooldown built into the exit engine
                if not self.exit_engine.should_evaluate(symbol):
                    continue

                current_price = self._last_prices.get(symbol)
                if current_price is None or current_price <= 0:
                    continue

                # ── Build exit context ──
                is_long = pos.side == "LONG"
                if is_long:
                    unrealized_pnl = (current_price - pos.entry) * pos.qty * pos.leverage
                    unrealized_pct = (current_price - pos.entry) / pos.entry
                else:
                    unrealized_pnl = (pos.entry - current_price) * pos.qty * pos.leverage
                    unrealized_pct = (pos.entry - current_price) / pos.entry

                # Time in position
                hold_seconds = (now - pos.open_time).total_seconds()
                hold_minutes = hold_seconds / 60.0

                # Current regime
                regime = "unknown"
                try:
                    regime = self.regime_detector.get_regime(symbol)
                except Exception:
                    pass

                # Funding rate
                funding_rate = self._last_funding_rates.get(symbol, 0.0)

                # ── Qualification gate: skip positions that don't warrant review ──
                # Position must meet at least one criterion:
                should_review = False

                # 1. Position open > 30 minutes
                if hold_minutes > 30:
                    should_review = True

                # 2. Losing position open > 15 minutes
                if unrealized_pnl < 0 and hold_minutes > 15:
                    should_review = True

                # 3. Regime has shifted to an adverse state
                if regime in ("panic", "crash", "extreme_fear"):
                    should_review = True

                if not should_review:
                    continue

                # ── Deep memory pattern lookup ──
                # Check if the strategy combo that opened this trade is historically
                # profitable or a known loser, so we can be more/less aggressive
                strategy_key = pos.strategy  # e.g. "RegimeTrend,MonteCarlo"
                strategy_wr = 0.5  # default neutral
                strategy_sample_size = 0
                if strategy_effectiveness and strategy_key in strategy_effectiveness:
                    se = strategy_effectiveness[strategy_key]
                    strategy_wr = se.get("win_rate", 0.5)
                    strategy_sample_size = se.get("total", 0)

                # Also check symbol-specific history from deep memory
                symbol_wr = 0.5
                if deep_mem:
                    try:
                        symbol_trades = deep_mem.trade_dna.get_by_symbol(symbol, limit=20)
                        if len(symbol_trades) >= 5:
                            wins = sum(1 for t in symbol_trades if t.get("outcome") == "WIN")
                            symbol_wr = wins / len(symbol_trades)
                    except Exception:
                        pass

                # ── Heuristic exit decision rules ──
                # These rules use regime, PnL, funding, and deep memory patterns
                # to make fast, cost-free decisions (no LLM API call per position)
                decision = None
                risk_distance = abs(pos.entry - pos.original_sl) if pos.original_sl else 0
                equity = self.risk_mgr.equity if self.risk_mgr.equity > 0 else 1.0
                loss_pct_of_equity = abs(unrealized_pnl) / equity if unrealized_pnl < 0 else 0

                # Rule 1: Panic/crash regime + LONG position → tighten SL aggressively
                if regime in ("panic", "crash", "extreme_fear") and is_long:
                    # Move SL to halfway between current SL and current price
                    new_sl = (pos.sl + current_price) / 2.0
                    if new_sl > pos.sl:  # Only tighten (move up for longs)
                        confidence = 0.75 if regime == "panic" else 0.85
                        decision = ExitDecision(
                            symbol=symbol,
                            exit_action="tighten_sl",
                            exit_confidence=confidence,
                            new_sl=new_sl,
                            reason=f"Regime={regime}, protecting capital on LONG "
                                   f"(strategy WR={strategy_wr:.0%} in this combo)",
                        )

                # Rule 2: Unrealized loss > 2% of equity → tighten SL
                elif loss_pct_of_equity > 0.02:
                    # Tighten to 60% of remaining distance
                    if is_long:
                        new_sl = pos.sl + (current_price - pos.sl) * 0.4
                    else:
                        new_sl = pos.sl - (pos.sl - current_price) * 0.4
                    # Only if it actually tightens
                    tightens = (is_long and new_sl > pos.sl) or (not is_long and new_sl < pos.sl)
                    if tightens:
                        # Lower confidence if strategy has a good track record (give it room)
                        conf = 0.65 if strategy_wr < 0.5 or strategy_sample_size < 5 else 0.55
                        decision = ExitDecision(
                            symbol=symbol,
                            exit_action="tighten_sl",
                            exit_confidence=conf,
                            new_sl=new_sl,
                            reason=f"Unrealized loss {loss_pct_of_equity:.1%} of equity "
                                   f"(strat WR={strategy_wr:.0%}, n={strategy_sample_size})",
                        )

                # Rule 3: Big winner → partial close or widen TP based on pattern strength
                elif risk_distance > 0 and unrealized_pnl > 0:
                    gain_vs_risk = abs(unrealized_pct * pos.entry) / risk_distance
                    if gain_vs_risk >= 3.0 and pos.state not in ("TP1_HIT", "TRAILING"):
                        # On confirmed winning patterns, widen TP instead of partial close
                        if strategy_wr >= 0.6 and strategy_sample_size >= 10:
                            # Strong pattern → let it ride, widen TP2
                            if is_long:
                                new_tp = current_price + risk_distance * 2.0
                                if new_tp > pos.tp2:
                                    decision = ExitDecision(
                                        symbol=symbol,
                                        exit_action="widen_tp",
                                        exit_confidence=0.70,
                                        new_tp=new_tp,
                                        reason=f"Confirmed winning pattern "
                                               f"(strat WR={strategy_wr:.0%}, n={strategy_sample_size}), "
                                               f"gain={gain_vs_risk:.1f}x risk — letting winner run",
                                    )
                            else:
                                new_tp = current_price - risk_distance * 2.0
                                if new_tp < pos.tp2:
                                    decision = ExitDecision(
                                        symbol=symbol,
                                        exit_action="widen_tp",
                                        exit_confidence=0.70,
                                        new_tp=new_tp,
                                        reason=f"Confirmed winning pattern "
                                               f"(strat WR={strategy_wr:.0%}, n={strategy_sample_size}), "
                                               f"gain={gain_vs_risk:.1f}x risk — letting winner run",
                                    )
                        else:
                            # Unproven or weak pattern → lock in partial profit
                            decision = ExitDecision(
                                symbol=symbol,
                                exit_action="partial",
                                exit_confidence=0.65,
                                partial_pct=0.5,
                                reason=f"Gain={gain_vs_risk:.1f}x risk, "
                                       f"pattern unproven (strat WR={strategy_wr:.0%}, "
                                       f"n={strategy_sample_size}) — locking 50%",
                            )

                # Rule 4: Adverse funding rate > 0.05% → tighten SL
                elif abs(funding_rate) > 0.0005:
                    funding_is_adverse = (is_long and funding_rate > 0) or \
                                         (not is_long and funding_rate < 0)
                    if funding_is_adverse and hold_minutes > 30:
                        # Tighten SL modestly (20% closer to price)
                        if is_long:
                            new_sl = pos.sl + (current_price - pos.sl) * 0.2
                        else:
                            new_sl = pos.sl - (pos.sl - current_price) * 0.2
                        tightens = (is_long and new_sl > pos.sl) or (not is_long and new_sl < pos.sl)
                        if tightens:
                            decision = ExitDecision(
                                symbol=symbol,
                                exit_action="tighten_sl",
                                exit_confidence=0.55,
                                new_sl=new_sl,
                                reason=f"Adverse funding rate {funding_rate:.5f} "
                                       f"(hold={hold_minutes:.0f}min, "
                                       f"symbol WR={symbol_wr:.0%})",
                            )

                # ── Apply decision via exit engine ──
                if decision is not None:
                    result = self.exit_engine.apply_exit_decision(
                        decision=decision,
                        position=pos,
                        current_price=current_price,
                    )

                    if result["applied"]:
                        action = result["action"]
                        logger.info(
                            f"[EXIT-INTEL] {symbol} {action}: {result['details']} "
                            f"(regime={regime}, hold={hold_minutes:.0f}min)"
                        )

                        # Handle close/partial actions that need exchange execution
                        if action == "close":
                            self.pos_mgr.force_close(symbol, current_price, "LLM_EXIT_ENGINE")
                        elif action == "partial":
                            # Partial close: reduce qty, log the partial
                            partial_pct = result.get("partial_pct", 0.5)
                            close_qty = pos.qty * partial_pct
                            pos.qty -= close_qty
                            logger.info(
                                f"[EXIT-INTEL] {symbol} partial close: "
                                f"closed {close_qty:.6f}, remaining {pos.qty:.6f}"
                            )
                    else:
                        logger.debug(
                            f"[EXIT-INTEL] {symbol} decision not applied: "
                            f"{result.get('details', 'unknown')}"
                        )
                else:
                    # No action needed — mark as evaluated to respect cooldown
                    self.exit_engine.mark_evaluated(symbol)

            except Exception as e:
                logger.warning(f"[EXIT-INTEL] Error evaluating {symbol}: {e}")

    # ── Position Aging Alerts ─────────────────────────────────────

    def _check_position_aging(self):
        """Alert on positions held too long — funding costs eat profits.
        Also enforces max hold time limits (tighten SL or force close)."""
        open_pos = self.pos_mgr.get_open_positions()
        now = time.time()
        max_hold = self.config.max_hold_hours
        hold_action = self.config.hold_limit_action

        for sym, pos in open_pos.items():
            if not hasattr(pos, 'open_time') or pos.open_time is None:
                continue
            # Calculate age
            if isinstance(pos.open_time, datetime):
                age_hours = (now - pos.open_time.timestamp()) / 3600
            else:
                age_hours = (now - pos.open_time) / 3600

            # Hold limit enforcement
            price = self._last_prices.get(sym, pos.entry)
            event = self.pos_mgr.check_hold_limits(sym, price, max_hold, hold_action)
            if event:
                logger.warning(f"[HOLD_LIMIT] {sym} force-closed after {age_hours:.0f}h")
                if self.alerts:
                    try:
                        self.alerts.send_trade_event(
                            "HOLD_LIMIT", sym,
                            f"Force closed after {age_hours:.0f}h (max {max_hold}h)\nPnL: ${event.pnl:.2f}"
                        )
                    except Exception:
                        pass
                continue  # Position is now closed

            # Alert thresholds
            funding_rate = self._last_funding_rates.get(sym, 0.0)
            is_paying = (pos.side == "LONG" and funding_rate > 0) or \
                        (pos.side == "SHORT" and funding_rate < 0)

            # Calculate estimated funding cost since entry
            notional = pos.qty * price * pos.leverage
            periods_since_entry = age_hours / 8  # 8h funding periods
            est_funding_paid = abs(funding_rate) * periods_since_entry * notional if is_paying else 0
            est_funding_pct = est_funding_paid / self.risk_mgr.equity * 100 if self.risk_mgr.equity > 0 else 0

            # Alert conditions
            if age_hours > 24 and is_paying and est_funding_pct > 0.1:
                logger.warning(
                    f"[AGING] {sym} {pos.side} open {age_hours:.0f}h, "
                    f"estimated funding paid: {est_funding_pct:.2f}% of equity"
                )
                if self.alerts and age_hours > 48:
                    try:
                        self.alerts.send_market_update(
                            f"[POSITION AGING] {sym} {pos.side}\n"
                            f"Open: {age_hours:.0f}h\n"
                            f"Funding paid: ~{est_funding_pct:.2f}% of equity\n"
                            f"Current PnL: ${pos.realized_pnl:.2f}"
                        )
                    except Exception:
                        pass

    # ── LLM Meta-Brain Integration ────────────────────────────────

    def _llm_veto_check(self, candidate: TradeCandidate, trace_id: str = ""):
        """Synchronous LLM check before opening a trade (VETO_ONLY+ mode).

        Returns DecisionResult if LLM says "flat" (veto), None if "proceed".
        If LLM fails (API error, timeout), defaults to proceed (no veto).
        """
        logger.info(
            f"[{trace_id}][{candidate.symbol}] LLM veto check: "
            f"{candidate.side} {candidate.entry_type} "
            f"conf={candidate.ensemble_confidence:.0f}%"
        )

        markets, global_ctx, risk_ctx, positions = self._build_llm_context()
        if not markets:
            return None  # No data -> no veto

        trigger_ctx = (
            f"PRE_TRADE veto check: {candidate.side} {candidate.symbol} "
            f"@ {_fmt_price(candidate.entry)} "
            f"type={candidate.entry_type} conf={candidate.ensemble_confidence:.0f}% "
            f"regime={candidate.regime} rr1={candidate.risk_reward_tp1:.2f} "
            f"strategies={candidate.strategies_agree}"
        )

        result = get_trading_decision(
            markets=markets,
            global_context=global_ctx,
            risk_context=risk_ctx,
            active_positions=positions,
            mode=self.llm_mode,
            use_compact_prompt=True,  # Save tokens on veto checks
            trigger_reason="pre_trade_veto",
            trigger_context=trigger_ctx,
            event_triggered=True,  # Bypass periodic throttle
        )

        # Log API usage
        if result.usage and result.usage.get("input_tokens", 0) > 0:
            from llm.client import get_usage_stats
            stats = get_usage_stats()
            logger.info(
                f"[LLM-VETO] tokens={result.usage.get('input_tokens', 0)}in/"
                f"{result.usage.get('output_tokens', 0)}out "
                f"est=${stats['estimated_cost_usd']:.4f}"
            )

        if result.decision is None:
            # API error or validation failure -> default to proceed
            logger.info(
                f"[{trace_id}][{candidate.symbol}] LLM veto: "
                f"no decision ({result.reason}), defaulting to proceed"
            )
            return None

        if result.decision.action == "flat":
            # LLM says skip this trade
            return result

        # LLM says proceed (or was downgraded from flip)
        candidate.llm_action = result.decision.action
        candidate.llm_confidence = result.decision.confidence
        candidate.llm_regime = result.decision.regime
        candidate.llm_size_mult = result.decision.size_multiplier
        candidate.llm_entry_adj = result.decision.entry_adjustment
        candidate.llm_notes = result.decision.notes
        candidate.llm_memory_update = result.decision.memory_update
        return None

    def _build_llm_context(self):
        """Build MarketSnapshot + GlobalContext + RiskContext from current bot state.

        Uses cached fetcher data (still hot from _tick_once processing).
        Called once per tick, not per symbol.
        """
        markets = []
        btc_price = 0.0
        btc_1h = 0.0
        btc_24h = 0.0
        eth_price = 0.0

        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            price = self._last_prices.get(symbol)
            if not price or price <= 0:
                continue

            # Track BTC/ETH for global context
            if symbol == "BTC":
                btc_price = price
            elif symbol == "ETH":
                eth_price = price

            # Get cached data (fetcher cache is still warm)
            data = self.fetcher.fetch_multi_timeframe(
                symbol, sym_cfg.coingecko_id, self._needed_tfs
            )

            # Compute market context from 1h data
            pchange_1h = 0.0
            pchange_24h = 0.0
            vol_ratio = 1.0
            volatility = 0.0

            df_1h = data.get("1h")
            if df_1h is not None and not df_1h.empty and len(df_1h) > 2:
                try:
                    pchange_1h = (price - float(df_1h["close"].iloc[-2])) / float(df_1h["close"].iloc[-2]) * 100
                    if len(df_1h) > 24:
                        pchange_24h = (price - float(df_1h["close"].iloc[-24])) / float(df_1h["close"].iloc[-24]) * 100
                    avg_vol = float(df_1h["volume"].tail(20).mean())
                    if avg_vol > 0:
                        vol_ratio = float(df_1h["volume"].iloc[-1]) / avg_vol
                    if len(df_1h) > 14:
                        prev_c = df_1h["close"].shift(1)
                        tr = pd.concat([
                            df_1h["high"] - df_1h["low"],
                            (df_1h["high"] - prev_c).abs(),
                            (df_1h["low"] - prev_c).abs(),
                        ], axis=1).max(axis=1)
                        atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
                        volatility = atr14 / price * 100
                except Exception:
                    pass

                if symbol == "BTC":
                    btc_1h = pchange_1h
                    btc_24h = pchange_24h

            # Get strategy signals from ensemble (uses cached evaluations)
            signals = []
            try:
                statuses = self.ensemble.get_all_status(symbol, data)
                for s in statuses:
                    strat_name = s.get("strategy", "unknown")
                    # Determine side from strategy output
                    action = s.get("action", s.get("side", "neutral"))
                    if action in ("BUY", "buy"):
                        side = "long"
                    elif action in ("SELL", "sell"):
                        side = "short"
                    else:
                        side = "neutral"

                    # Extract confidence-like metric
                    conf = s.get("confidence", 0)
                    if conf == 0:
                        # Try to infer from other fields
                        align_l = s.get("align_long", 0)
                        align_s = s.get("align_short", 0)
                        conf = max(align_l, align_s) / 100.0 if max(align_l, align_s) > 1 else max(align_l, align_s)

                    regime_score = s.get("regime_score", s.get("align_long", 0))
                    if isinstance(regime_score, (int, float)) and regime_score > 1:
                        regime_score = regime_score / 100.0

                    signals.append(LLMStrategySignal(
                        symbol=symbol,
                        strategy=strat_name,
                        side=side,
                        confidence=min(conf, 1.0),
                        regime_score=min(regime_score, 1.0) if isinstance(regime_score, (int, float)) else 0.0,
                    ))
            except Exception:
                pass

            markets.append(LLMMarketSnapshot(
                symbol=symbol,
                price=price,
                price_change_1h_pct=pchange_1h,
                price_change_24h_pct=pchange_24h,
                volume_ratio=vol_ratio,
                volatility=volatility,
                signals=signals,
            ))

        # Global Brain: build cross-market context for LLM reasoning
        try:
            _gb_ctx = build_global_context(
                btc_price=btc_price,
                btc_1h_change=btc_1h,
                btc_24h_change=btc_24h,
                eth_price=eth_price,
                last_prices=self._last_prices,
                funding_rates=self._last_funding_rates,
            )
            self._global_bias = _gb_ctx.get("classified_bias", "neutral")
            self._global_bias_adjustment = apply_global_bias(
                self._global_bias,
                max_positions=self.config.max_open_positions,
            )
        except Exception as e:
            _gb_ctx = {}
            logger.debug(f"Global brain context error: {e}")

        # Global context (enriched with telemetry for LLM learning)
        eth_btc = eth_price / btc_price if btc_price > 0 else 0.0
        telem_snap = Telemetry.snapshot()
        global_ctx = LLMGlobalContext(
            timestamp=int(time.time() * 1000),
            btc_price=btc_price,
            btc_change_1h_pct=btc_1h,
            btc_change_24h_pct=btc_24h,
            eth_btc_ratio=eth_btc,
            total_open_positions=self.pos_mgr.get_open_count(),
            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
            equity=self.risk_mgr.equity,
            circuit_breaker_active=self.risk_mgr.circuit_breaker.tripped,
        )
        # Attach telemetry so the LLM can learn from execution quality
        cb = self.risk_mgr.circuit_breaker
        # Build recent outcomes string (e.g., "WWLLL") from feedback quality scorer
        _recent_out_str = ""
        if self.feedback.quality.overall_recent:
            _recent_out_str = "".join(
                "W" if r else "L" for r in self.feedback.quality.overall_recent[-5:]
            )
        # Daily win rate from feedback
        _daily_wr = None
        if len(self.feedback.quality.overall_recent) >= 3:
            _daily_wr = sum(self.feedback.quality.overall_recent) / len(self.feedback.quality.overall_recent)

        global_ctx.extra = {
            "win_rate": telem_snap.get("win_rate", 0),
            "total_trades": telem_snap.get("total_trades", 0),
            "avg_slippage": telem_snap.get("avg_slippage", 0),
            "avg_snapshot_age": telem_snap.get("avg_snapshot_age", 0),
            "stale_signals": telem_snap.get("stale_signals", 0),
            "circuit_breaker_triggers": telem_snap.get("circuit_breaker_triggers", 0),
            "throttle_blocks": telem_snap.get("throttle_blocks", 0),
            "ops_guard_status": self.ops_guard.format_status(),
            # Loss streak context for LLM awareness
            "consecutive_losses": cb.consecutive_losses,
            "recent_outcomes": _recent_out_str,
            "daily_win_rate": _daily_wr,
            # Portfolio correlation risk for LLM sizing adjustment
            "correlation_risk": self._compute_portfolio_correlation().get("risk_level", "low"),
            # Portfolio leverage for risk awareness
            "portfolio_leverage": self._compute_portfolio_leverage(),
            # Estimated daily funding cost (% of equity)
            "estimated_daily_funding_cost": self._compute_estimated_daily_funding(),
            # D5: Session performance for LLM context
            "session_performance": self.feedback.quality.get_session_performance(),
            # E2: Active regime transitions
            "regime_transitions": self.regime_detector.get_transition_summary(),
            # Global Brain: market-wide bias classification
            "global_bias": self._global_bias,
            "sector_activity": _gb_ctx.get("sectors_active", {}),
            "net_funding": _gb_ctx.get("net_funding", 0.0),
        }

        # Cross-symbol pattern signals: inject lead-lag relationships for LLM
        if self.cross_symbol_tracker:
            try:
                _cs_signals = self.cross_symbol_tracker.get_active_signals()
                if _cs_signals:
                    global_ctx.extra["cross_symbol_signals"] = _cs_signals[:5]  # Cap at 5
                _cs_patterns = self.cross_symbol_tracker.get_pattern_summary()
                if _cs_patterns:
                    global_ctx.extra["cross_symbol_patterns"] = _cs_patterns
            except Exception as e:
                logger.debug(f"Cross-symbol pattern injection error: {e}")

        # Risk context
        risk_ctx = LLMRiskContext(
            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
            max_daily_loss=self.risk_mgr.equity * self.config.circuit_breaker_daily_loss_pct,
            equity=self.risk_mgr.equity,
            max_leverage=self.config.max_leverage,
            current_leverage=self._compute_portfolio_leverage(),
            volatility=max((m.volatility for m in markets), default=0.0),
            max_volatility=15.0,  # 15% ATR/price = extreme
            open_positions=self.pos_mgr.get_open_count(),
            max_positions=self.config.max_open_positions,
            circuit_breaker_active=self.risk_mgr.circuit_breaker.tripped,
            consecutive_losses=self.risk_mgr.circuit_breaker.consecutive_losses,
        )

        # Active positions
        active_positions = []
        open_pos = self.pos_mgr.get_open_positions()
        for sym, pos in open_pos.items():
            p = self._last_prices.get(sym, 0)
            if pos.side == "LONG":
                unrealized = (p - pos.entry) * pos.qty * pos.leverage if p else 0
            else:
                unrealized = (pos.entry - p) * pos.qty * pos.leverage if p else 0
            active_positions.append({
                "symbol": sym,
                "side": pos.side,
                "entry": pos.entry,
                "leverage": pos.leverage,
                "unrealized_pnl": round(unrealized, 2),
                "funding_rate": self._last_funding_rates.get(sym, 0.0),
            })

        # Portfolio Brain: cross-symbol portfolio reasoning for LLM
        try:
            _portfolio_snap = build_portfolio_snapshot(
                pos_mgr=self.pos_mgr,
                last_prices=self._last_prices,
                equity=self.risk_mgr.equity,
            )
            global_ctx.extra["portfolio_snapshot"] = _portfolio_snap
        except Exception as e:
            logger.debug(f"Portfolio brain snapshot error: {e}")

        # Self-Tuning Risk: inject current profile for LLM awareness
        try:
            _risk_profile = get_risk_profile_params()
            global_ctx.extra["risk_profile"] = _risk_profile.get("description", "normal")
            global_ctx.extra["dynamic_leverage_cap"] = get_dynamic_leverage_cap(
                self.config.max_leverage
            )
        except Exception as e:
            logger.debug(f"Risk profile context error: {e}")

        # Survival Pressure: inject accountability context into LLM prompt
        if _SURVIVAL_PRESSURE_AVAILABLE:
            try:
                global_ctx.extra["survival_status"] = get_survival_context_for_llm()
            except Exception as e:
                logger.debug(f"Survival context injection error: {e}")

        # Wave 3: Portfolio Risk Engine — inject vol forecasts and risk budget
        if self.portfolio_risk:
            try:
                _pr_budget = self.portfolio_risk.compute_risk_budget(
                    equity=self.risk_mgr.equity,
                    open_positions={s: {"side": p.side, "entry": p.entry,
                                       "qty": p.qty, "leverage": p.leverage}
                                   for s, p in self.pos_mgr.get_open_positions().items()},
                )
                global_ctx.extra["portfolio_risk_budget"] = {
                    "utilization": round(_pr_budget.utilization, 2),
                    "remaining_pct": round(_pr_budget.remaining_budget, 2),
                    "concentration_warning": _pr_budget.concentration_warning,
                }
            except Exception as e:
                logger.debug(f"Portfolio risk context error: {e}")

        # Wave 4: Meta-Learning — inject active insights for LLM awareness
        if self.meta_engine:
            try:
                _meta_insights = self.meta_engine.get_active_ideas()
                if _meta_insights:
                    global_ctx.extra["meta_learning_ideas"] = [
                        {"name": i.name, "trigger": i.trigger_condition, "status": i.status}
                        for i in _meta_insights[:3]
                    ]
            except Exception as e:
                logger.debug(f"Meta-learning context error: {e}")

        # Wave 4: Counterfactual — inject veto accuracy for LLM calibration
        if self.counterfactual:
            try:
                _cf_stats = self.counterfactual.get_summary_stats()
                if _cf_stats:
                    global_ctx.extra["counterfactual_stats"] = _cf_stats
            except Exception as e:
                logger.debug(f"Counterfactual context error: {e}")

        # LLM Self-Performance: inject rolling accuracy stats for self-calibration
        if _SELF_PERF_AVAILABLE:
            try:
                _sp_stats = get_llm_self_stats()
                if _sp_stats:
                    global_ctx.extra["llm_self_performance"] = _sp_stats
            except Exception as e:
                logger.debug(f"Self-performance stats injection error: {e}")

        # Learning Mode: inject current phase for LLM awareness
        if _LEARNING_MODE_AVAILABLE:
            try:
                if is_learning_mode_active():
                    _lm_phase = get_current_phase()
                    global_ctx.extra["learning_mode"] = {
                        "active": True,
                        "phase": _lm_phase.name,
                        "description": (
                            "ABSORB: Observing only, cannot veto" if _lm_phase == LearningPhase.ABSORB
                            else "APPRENTICE: Learning, limited influence" if _lm_phase == LearningPhase.APPRENTICE
                            else "ACTIVE: Full autonomy earned"
                        ),
                    }
                else:
                    global_ctx.extra["learning_mode"] = {"active": False, "phase": "GRADUATED"}
            except Exception as e:
                logger.debug(f"Learning mode context injection error: {e}")

        # Adaptive Risk: inject current risk multiplier for LLM sizing awareness
        if self.adaptive_risk:
            try:
                _ar_status = self.adaptive_risk.get_status()
                global_ctx.extra["adaptive_risk"] = {
                    "recent_streak": _ar_status.get("recent_streak", ""),
                    "recent_wr": round(_ar_status.get("recent_wr", 0), 2),
                }
            except Exception as e:
                logger.debug(f"Adaptive risk context injection error: {e}")

        return markets, global_ctx, risk_ctx, active_positions

    def _run_llm_metabrain(self, trace_id: str = ""):
        """Run the LLM meta-brain via hybrid trigger system.

        Called when at least one trigger has fired. The trigger accumulator
        determines the highest-priority trigger and combines context from
        all pending events.

        In ADVISORY mode: call LLM, log decision, send to alerts, no influence.
        """
        # Get the best trigger, combined context, and all reason labels
        trigger_type, trigger_ctx, all_reasons = self._llm_triggers.get_best()
        trigger_label = TRIGGER_LABELS.get(trigger_type, "unknown") if trigger_type else "periodic"
        is_event = trigger_type is not None and trigger_type != LLMTrigger.PERIODIC

        logger.info(
            f"[{trace_id}][LLM] Trigger: {trigger_label} "
            f"reasons=[{', '.join(all_reasons)}] "
            f"(events: {self._llm_triggers.event_summary})"
        )

        # F3: Graceful degradation — skip LLM if API is degraded
        if self.degradation.should_skip_llm():
            logger.info(
                f"[{trace_id}][LLM] Skipping — LLM API degraded (ensemble-only mode)"
            )
            return

        markets, global_ctx, risk_ctx, positions = self._build_llm_context()

        if not markets:
            return

        result = get_trading_decision(
            markets=markets,
            global_context=global_ctx,
            risk_context=risk_ctx,
            active_positions=positions,
            mode=self.llm_mode,
            trigger_reason=trigger_label,
            trigger_context=trigger_ctx,
            event_triggered=is_event,
        )

        # F3: Track LLM API health for graceful degradation
        if result.reason and result.reason.startswith("api_error"):
            self.degradation.record_llm_error()
        else:
            self.degradation.record_llm_success()

        # Mark the trigger as called (for cooldown tracking)
        if trigger_type:
            self._llm_triggers.mark_called(trigger_type)

        # Log result
        if result.source == "none" and result.reason in ("throttled_no_cache", "off"):
            return  # Silent skip

        if result.source == "cache":
            return  # Already logged when cached

        if result.decision:
            d = result.decision
            logger.info(
                f"[{trace_id}][LLM] {d.action.upper()} conf={d.confidence:.2f} "
                f"regime={d.regime} size_mult={d.size_multiplier:.2f} "
                f"trigger={trigger_label} | {d.notes}"
            )

            # In ADVISORY/VETO_ONLY mode: send to alerts for visibility
            if self.llm_mode in (LLMMode.ADVISORY, LLMMode.VETO_ONLY):
                reasons_str = ", ".join(all_reasons) if all_reasons else trigger_label
                orig_str = ""
                if result.original_action and result.original_action != d.action:
                    orig_str = f"\nOriginal: {result.original_action} (downgraded)"
                self.alerts.send_market_update(
                    f"[LLM META-BRAIN] {d.action.upper()} "
                    f"conf={d.confidence:.0%} regime={d.regime}\n"
                    f"Size mult: {d.size_multiplier:.2f}x\n"
                    f"Trigger: {trigger_label}\n"
                    f"All reasons: {reasons_str}"
                    f"{orig_str}\n"
                    f"{d.notes}"
                )
        elif result.reason:
            logger.info(f"[{trace_id}][LLM] No decision: {result.reason}")

        # Log API usage periodically
        if result.usage and result.usage.get("input_tokens", 0) > 0:
            from llm.client import get_usage_stats
            stats = get_usage_stats()
            logger.info(
                f"[LLM-COST] calls={stats['total_calls']} "
                f"tokens={stats['total_input_tokens']}in/{stats['total_output_tokens']}out "
                f"est=${stats['estimated_cost_usd']:.4f}"
            )

    def _compute_portfolio_leverage(self) -> float:
        """Compute total portfolio leverage as a fraction of equity.

        Formula: sum(abs(qty) * price * leverage) / equity
        E.g., 3 positions at 5x each with $1000 notional each = 15000 / equity.
        """
        open_pos = self.pos_mgr.get_open_positions()
        if not open_pos:
            return 0.0
        equity = self.risk_mgr.equity
        if equity <= 0:
            return 0.0
        total_notional = 0.0
        for sym, pos in open_pos.items():
            price = self._last_prices.get(sym, pos.entry)
            total_notional += abs(pos.qty) * price * pos.leverage
        return round(total_notional / equity, 2)

    def _compute_estimated_daily_funding(self) -> float:
        """Compute estimated daily funding cost as % of equity.

        Funding on Hyperliquid is paid 3x/day (every 8 hours).
        Cost = sum(abs(funding_rate) * 3 * leverage * position_value / equity) * 100
        Only counts positions paying funding (long+positive or short+negative rate).
        """
        open_pos = self.pos_mgr.get_open_positions()
        if not open_pos:
            return 0.0
        equity = self.risk_mgr.equity
        if equity <= 0:
            return 0.0
        total_daily_cost_pct = 0.0
        for sym, pos in open_pos.items():
            fr = self._last_funding_rates.get(sym, 0.0)
            if fr == 0:
                continue
            price = self._last_prices.get(sym, pos.entry)
            pos_value = abs(pos.qty) * price
            # Check if position is paying or receiving funding
            side_lower = pos.side.lower()
            is_paying = (
                (side_lower in ("long", "buy") and fr > 0) or
                (side_lower in ("short", "sell") and fr < 0)
            )
            if is_paying:
                # 3 payments per day, scaled by leverage
                daily_cost = abs(fr) * 3 * pos.leverage * pos_value / equity * 100
                total_daily_cost_pct += daily_cost
        return round(total_daily_cost_pct, 4)

    def _record_trade_dna(self, symbol: str, pos, event):
        """Record full trade DNA to deep memory after a position closes.

        Populates the deep memory system with complete trade anatomy
        so the LLM can learn from every trade: what worked, what failed,
        and which strategy/regime/symbol combos are most profitable.
        """
        if not _DEEP_MEMORY_AVAILABLE:
            return
        try:
            dm = get_deep_memory()

            # Determine outcome
            total_pnl = pos.realized_pnl if pos else event.pnl
            if total_pnl > 0:
                outcome = "WIN"
            elif total_pnl < -0.01:
                outcome = "LOSS"
            else:
                outcome = "BREAKEVEN"

            # Extract trade profile data
            _regime = ""
            _entry_type = ""
            if pos.trade_profile:
                _regime = pos.trade_profile.regime or ""
                _entry_type = pos.trade_profile.entry_type or ""

            # Extract LLM decision context from entry_reasons
            _er = pos.entry_reasons or {}
            _llm_action = _er.get("llm_action", "")
            _llm_conf = _er.get("llm_confidence", 0.0)
            _llm_reasoning = _er.get("llm_reasoning", "")
            _strategies_agreed = _er.get("strategies_agreed", [])
            if not _strategies_agreed and pos.strategy:
                _strategies_agreed = [pos.strategy]

            # Hold time
            hold_time_s = 0.0
            if pos.open_time:
                hold_time_s = (datetime.now(timezone.utc) - pos.open_time).total_seconds()

            # BTC trend context
            btc_price = self._last_prices.get("BTC", 0)
            btc_1h_change = self._price_changes_1h.get("BTC", 0)
            if btc_1h_change > 0.5:
                btc_trend = "bullish"
            elif btc_1h_change < -0.5:
                btc_trend = "bearish"
            else:
                btc_trend = "neutral"

            # Volume ratio and funding rate
            _vol_ratio = 0.0
            _funding_rate = self._last_funding_rates.get(symbol, 0.0)

            # ATR at entry (stored on position)
            _atr = pos.atr if pos.atr else 0.0

            # Generate trade ID
            trade_id = f"{symbol}_{pos.side}_{int(pos.open_time.timestamp())}"

            dm.record_full_trade(
                trade_id=trade_id,
                symbol=symbol,
                side=pos.side,
                entry_price=pos.entry,
                exit_price=event.price,
                sl=pos.original_sl,
                tp1=pos.tp1,
                tp2=pos.tp2,
                confidence=pos.confidence,
                leverage=pos.leverage,
                regime=_regime,
                strategies_agreed=_strategies_agreed,
                outcome=outcome,
                pnl=total_pnl,
                hold_time_s=hold_time_s,
                exit_reason=event.action,
                llm_action=_llm_action,
                llm_confidence=_llm_conf,
                llm_reasoning=_llm_reasoning,
                entry_type=_entry_type,
                btc_trend=btc_trend,
                volume_ratio=_vol_ratio,
                funding_rate=_funding_rate,
                atr=_atr,
            )

            # Record regime transition if regime changed during trade
            if _regime:
                current_regime = ""
                try:
                    current_regime = self.regime_detector.get_transition_summary()
                    if isinstance(current_regime, dict):
                        current_regime = current_regime.get("current", "")
                    elif isinstance(current_regime, list) and current_regime:
                        current_regime = str(current_regime[0])
                    else:
                        current_regime = str(current_regime) if current_regime else ""
                except Exception:
                    pass
                if current_regime and current_regime != _regime:
                    dm.regimes.record_transition(
                        from_regime=_regime,
                        to_regime=current_regime,
                        symbol=symbol,
                        trigger=f"trade_close_{event.action}",
                        context={"pnl": total_pnl, "hold_time_s": hold_time_s},
                    )

            logger.info(
                f"[DEEP-MEM] Recorded trade DNA: {symbol} {pos.side} "
                f"{outcome} PnL=${total_pnl:+.2f}"
            )

        except Exception as e:
            logger.debug(f"[DEEP-MEM] Failed to record trade DNA: {e}")

    def _compute_portfolio_correlation(self) -> Dict[str, Any]:
        """Compute directional correlation risk across open positions.

        Returns risk assessment: low/medium/high based on same-direction
        exposure in correlated assets (BTC/ETH/SOL etc.).
        """
        open_pos = self.pos_mgr.get_open_positions()
        if len(open_pos) < 2:
            return {"avg_correlation": 0.0, "net_delta": 0, "risk_level": "low"}

        longs = [(s, p) for s, p in open_pos.items() if p.side == "LONG"]
        shorts = [(s, p) for s, p in open_pos.items() if p.side == "SHORT"]
        net_delta = len(longs) - len(shorts)

        HIGH_CORR_PAIRS = {
            frozenset({"BTC", "ETH"}): 0.85,
            frozenset({"SOL", "ETH"}): 0.70,
            frozenset({"BTC", "SOL"}): 0.65,
            frozenset({"AVAX", "SOL"}): 0.55,
            frozenset({"LINK", "ETH"}): 0.55,
        }

        # Check correlation among same-direction positions
        same_dir = [s for s, _ in longs] if len(longs) >= len(shorts) else [s for s, _ in shorts]
        max_corr = 0.0
        for i, s1 in enumerate(same_dir):
            for s2 in same_dir[i + 1:]:
                pair = frozenset({s1.split("/")[0], s2.split("/")[0]})
                corr = HIGH_CORR_PAIRS.get(pair, 0.3)
                max_corr = max(max_corr, corr)

        risk_level = "high" if max_corr > 0.7 or abs(net_delta) >= 3 else (
            "medium" if max_corr > 0.5 or abs(net_delta) >= 2 else "low"
        )

        return {
            "avg_correlation": round(max_corr, 2),
            "net_delta": net_delta,
            "same_dir_count": max(len(longs), len(shorts)),
            "risk_level": risk_level,
        }

    def _send_heartbeat(self):
        """Send periodic status heartbeat."""
        fetcher_stats = self.fetcher.get_stats()
        ml_snap_filled = 0
        if self.ml:
            ml_snap_filled = sum(1 for s in self.ml.snapshots if s.future_return_1h is not None)
        status = {
            "equity": self.risk_mgr.equity,
            "open_positions": self.pos_mgr.get_open_count(),
            "daily_pnl": self.risk_mgr.circuit_breaker.daily_pnl,
            "ml_samples": len(self.ml.outcomes) if self.ml else 0,
            "ml_snapshots": len(self.ml.snapshots) if self.ml else 0,
            "ml_snap_trained": ml_snap_filled,
            "ml_direction_model": self.ml.snapshot_weights is not None if self.ml else False,
            "circuit_breaker": self.risk_mgr.circuit_breaker.get_status(),
        }

        # Log equity snapshot to database
        log_equity(
            equity=self.risk_mgr.equity,
            open_positions=self.pos_mgr.get_open_count(),
            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
            unrealized_pnl=self.pos_mgr.get_total_unrealized_pnl({
                sym: self.fetcher.latest_price(sym, DEFAULT_SYMBOLS[sym].coingecko_id) or 0
                for sym in DEFAULT_SYMBOLS.keys()
            })
        )

        # Daily strategy weight recompute from trades DB
        self.weight_mgr.recompute_from_db()

        # ML stats logging (data/ml/ml_stats.jsonl)
        ml_conf_trade = 0.0
        ml_conf_snapshot = 0.0
        ml_conf_fast = 0.0
        if self.ml:
            ml_conf_trade = self.ml.predict_win_probability(70, 0, False, False, 1.5) if self.ml.weights is not None and len(self.ml.weights) > 0 else 0.0
            ml_conf_snapshot = 1.0 if self.ml.snapshot_weights is not None else 0.0
            ml_conf_fast = 1.0 if self.ml.fast_weights is not None else 0.0
        log_ml_stats(
            ml_samples_total=status["ml_samples"],
            ml_conf_trade=ml_conf_trade,
            ml_conf_snapshot=ml_conf_snapshot,
            ml_conf_fast=ml_conf_fast,
            equity=status["equity"],
            open_positions=status["open_positions"],
        )

        # Risk rejection counts for heartbeat
        rejections = get_rejection_counts()

        # Rolling performance from learning hooks
        perf = get_performance()

        # Veto tracker: check counterfactual outcomes for vetoed signals
        try:
            def _price_fetcher(sym):
                return self.fetcher.latest_price(sym, "") or 0
            self.veto_tracker.check_outcomes(price_fetcher=_price_fetcher)
        except Exception as e:
            logger.debug(f"[HEARTBEAT] Veto check failed: {e}")

        # Operator channel: detect and report operational anomalies
        try:
            perf_stats = get_performance_stats()
            correlation_info = self._compute_portfolio_correlation()
            cost_stats = get_cost_tracker().get_stats()

            op_context = {
                "consecutive_losses": self.risk_mgr.circuit_breaker.consecutive_losses,
                "llm_accuracy": perf_stats.get("accuracy", 0.5),
                "llm_decisions_count": perf_stats.get("total_decisions", 0),
                "budget_used_pct": cost_stats.get("budget_used_pct", 0),
                "correlation_risk": correlation_info.get("risk_level", "low"),
                "hours_since_last_trade": 0,  # populated below
                "signals_generated": len(get_daily_summary().get("by_strategy", {})),
                "estimated_daily_funding_cost": self._compute_estimated_daily_funding(),
                "flip_success_rate": perf_stats.get("flip_success_rate", 0.5),
                "flip_count": perf_stats.get("flip_count", 0),
                "calibration": perf_stats.get("calibration", 0.0),
                "veto_accuracy": perf_stats.get("veto_accuracy", 0.5),
                "veto_count": self.veto_tracker.get_stats().get("resolved", 0),
                "streak": perf_stats.get("streak", ""),
            }
            self.operator_channel.check_and_report(op_context)
        except Exception as e:
            logger.debug(f"[HEARTBEAT] Operator channel check failed: {e}")

        # Survival Pressure: include survival score in heartbeat
        if _SURVIVAL_PRESSURE_AVAILABLE:
            try:
                _surv_report = get_survival_report()
                status["survival_score"] = _surv_report.get("survival_score", 50)
                status["survival_trend"] = _surv_report.get("improvement_trend", "neutral")
                status["net_pnl_after_funding"] = _surv_report.get("net_pnl_after_funding", 0)
            except Exception:
                pass

        # Learning Mode: include phase in heartbeat
        if _LEARNING_MODE_AVAILABLE:
            try:
                _lm_report = get_learning_report()
                status["learning_phase"] = _lm_report.get("phase", "UNKNOWN")
                status["learning_graduated"] = _lm_report.get("graduated", False)
            except Exception:
                pass

        self.alerts.send_heartbeat(status)

        # Enhanced Telegram heartbeat with actionable format
        try:
            _hb_ds = get_daily_summary()
            _hb_msg = format_heartbeat_telegram(
                equity=status["equity"],
                open_positions=status["open_positions"],
                daily_pnl=status.get("daily_pnl", 0),
                daily_trades=_hb_ds.get("total_trades", 0),
                daily_wins=_hb_ds.get("wins", 0),
                llm_mode=self.llm_mode.name,
                health_status="OK" if self.watchdog.get_status().get("stalled") is False else "STALLED",
            )
            # Only send enhanced heartbeat to Telegram (Discord gets normal one)
            if self.alerts.telegram_token and self.alerts.telegram_chat_id:
                self.alerts._send_telegram(_hb_msg)
        except Exception:
            pass

        # Update daily performance aggregation in SQLite
        try:
            update_daily_performance()
        except Exception:
            pass

        # Wave 3: Portfolio Risk — rebalance suggestions in heartbeat
        if self.portfolio_risk and self.pos_mgr.get_open_count() >= 2:
            try:
                _rebal = self.portfolio_risk.get_rebalance_suggestions(
                    open_positions={s: {"side": p.side, "entry": p.entry,
                                       "qty": p.qty, "leverage": p.leverage}
                                   for s, p in self.pos_mgr.get_open_positions().items()},
                    equity=self.risk_mgr.equity,
                )
                if _rebal:
                    _rebal_str = "; ".join(
                        f"{r.get('symbol')}: {r.get('action')} ({r.get('reason', '')})"
                        for r in _rebal[:3]
                    )
                    logger.info(f"[REBALANCE] Suggestions: {_rebal_str}")
                    status["rebalance_suggestions"] = _rebal_str
            except Exception as e:
                logger.debug(f"Rebalance suggestion error: {e}")

        # Wave 4: Counterfactual — include veto accuracy in heartbeat
        if self.counterfactual:
            try:
                _cf_acc = self.counterfactual.get_veto_accuracy()
                if _cf_acc.get("total_resolved", 0) > 0:
                    status["veto_accuracy_cf"] = round(_cf_acc.get("accuracy", 0), 2)
                    status["veto_net_value"] = round(_cf_acc.get("net_veto_value", 0), 2)
            except Exception:
                pass

        strat_weights = self.weight_mgr.get_all_weights()
        weights_str = " ".join(f"{k}={v:.2f}" for k, v in strat_weights.items()) if strat_weights else "none"
        rej_str = " ".join(f"{k}={v}" for k, v in rejections.items()) if rejections else "none"
        wr20 = perf.get("win_rate_20", 0)

        _surv_str = ""
        if "survival_score" in status:
            _surv_str = f"survival={status['survival_score']:.0f}/{status['survival_trend']} "
        _learn_str = ""
        if "learning_phase" in status:
            _learn_str = f"learn={status['learning_phase']} "

        logger.info(
            f"[HEARTBEAT] equity=${status['equity']:,.2f} "
            f"positions={status['open_positions']} "
            f"daily_pnl=${status['daily_pnl']:+,.2f} "
            f"WR20={wr20:.0%} "
            f"{_surv_str}"
            f"{_learn_str}"
            f"ml_trades={status['ml_samples']} "
            f"ml_snaps={status['ml_snapshots']}({status['ml_snap_trained']}filled) "
            f"direction_model={'YES' if status['ml_direction_model'] else 'no'} "
            f"strat_weights=[{weights_str}] "
            f"rejections=[{rej_str}] "
            f"api={fetcher_stats['total_requests']} "
            f"cache={fetcher_stats['cache_hits']}"
        )

    def _handle_ingested_signal(self, signal: IngestedSignal):
        """Handle an incoming signal from the Telegram signal ingestion pipeline.

        Runs LLM analysis, sends the thought process to Telegram, and
        optionally routes TAKE signals into the trading pipeline.
        """
        logger.info(
            f"[SIGNAL-PIPE] Received: {signal.symbol} {signal.side} "
            f"entry={signal.entry_price} sl={signal.stop_loss} tp1={signal.take_profit_1} "
            f"quality={signal.parse_quality:.0%}"
        )

        # Skip low-quality parses
        if signal.parse_quality < 0.6:
            logger.info(f"[SIGNAL-PIPE] Skipping low-quality parse ({signal.parse_quality:.0%})")
            return

        # Get knowledge context for the LLM
        knowledge_context = ""
        try:
            from llm.knowledge_seed import get_course_summary_for_prompt
            from llm.self_teaching import get_teaching_engine
            engine = get_teaching_engine()
            knowledge_context = (
                get_course_summary_for_prompt(signal.symbol, "") + "\n" +
                engine.get_knowledge_for_prompt(signal.symbol, "")
            )
        except Exception as e:
            logger.debug(f"[SIGNAL-PIPE] Knowledge context error: {e}")

        # Get roadmap state for curriculum level
        curriculum_level = 1
        learning_phase = "ABSORB"
        try:
            from llm.knowledge_roadmap import get_roadmap_state, PHASE_CONFIGS
            state = get_roadmap_state()
            config = PHASE_CONFIGS.get(state.current_phase, {})
            curriculum_level = config.get("curriculum_level", 1)
            learning_phase = config.get("learning_phase", "ABSORB")
        except Exception:
            pass

        # Get market data for context
        market_data = {}
        sym_cfg = DEFAULT_SYMBOLS.get(signal.symbol)
        if sym_cfg:
            try:
                price = self.fetcher.latest_price(signal.symbol, sym_cfg.coingecko_id)
                if price:
                    market_data["current_price"] = price
                    market_data["signal_vs_market_pct"] = (
                        (signal.entry_price - price) / price * 100
                    ) if signal.entry_price > 0 else 0
            except Exception:
                pass

        # Run LLM analysis
        from dataclasses import asdict
        analysis = analyze_signal(
            signal_data=asdict(signal),
            market_data=market_data,
            knowledge_context=knowledge_context,
            curriculum_level=curriculum_level,
            learning_phase=learning_phase,
        )

        if analysis:
            # Send the digestible thought process to Telegram
            telegram_msg = format_analysis_for_telegram(analysis)
            self.alerts.send_market_update(telegram_msg)

            logger.info(
                f"[SIGNAL-PIPE] Analysis complete: {signal.symbol} {signal.side} -> "
                f"{analysis.verdict} (conf={analysis.verdict_confidence:.0%})"
            )

            # Update the ingested signal with analysis results
            signal.llm_analyzed = True
            signal.llm_verdict = analysis.verdict
            signal.llm_reasoning = analysis.verdict_reasoning
            signal.llm_confidence = analysis.verdict_confidence
            signal.llm_analysis_id = analysis.analysis_id

            # Log updated signal
            from signals.telegram_ingest import log_ingested_signal
            log_ingested_signal(signal)

            # Route high-confidence TAKE verdicts into trading pipeline
            if (analysis.verdict == "TAKE"
                    and analysis.verdict_confidence >= 0.75
                    and signal.entry_price > 0
                    and signal.stop_loss > 0
                    and signal.take_profit_1 > 0):
                logger.info(
                    f"[SIGNAL-PIPE] TAKE verdict for {signal.symbol} "
                    f"(conf={analysis.verdict_confidence:.0%}) — logging as external signal"
                )
                # Log to signals DB so it appears in analytics
                log_signal(
                    symbol=signal.symbol,
                    strategy="external_telegram",
                    side=signal.side,
                    confidence=analysis.verdict_confidence * 100,
                    entry=signal.entry_price,
                    sl=signal.stop_loss,
                    tp1=signal.take_profit_1,
                    tp2=signal.take_profit_2 if signal.take_profit_2 else 0,
                    atr=0,
                    leverage=1.0,
                    traded=False,
                    metadata={
                        "source": "telegram_ingest",
                        "llm_verdict": analysis.verdict,
                        "llm_confidence": analysis.verdict_confidence,
                        "analysis_id": analysis.analysis_id,
                        "original_source": signal.source_channel,
                    }
                )
        else:
            logger.warning(f"[SIGNAL-PIPE] LLM analysis failed for {signal.symbol}")
            self.alerts.send_market_update(
                f"[SIGNAL] {signal.symbol} {signal.side} "
                f"entry={signal.entry_price} sl={signal.stop_loss} tp1={signal.take_profit_1}\n"
                f"(LLM analysis unavailable)"
            )

    def _send_market_update(self, trace_id: str = ""):
        """Send periodic market assessment even when no signals fire.
        Helps testers stay informed and feeds data for ML improvement."""
        lines = [f"[MARKET UPDATE] {datetime.now(timezone.utc).strftime('%H:%M UTC')}"]

        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            try:
                data = self.fetcher.fetch_multi_timeframe(symbol, sym_cfg.coingecko_id, self._needed_tfs)
                price = self.fetcher.latest_price(symbol, sym_cfg.coingecko_id)
                if price is None:
                    continue

                # Get all strategy assessments
                statuses = self.ensemble.get_all_status(symbol, data)

                # Volume ratio for chop detection
                vol_str = ""
                df_1h = data.get("1h")
                if df_1h is not None and not df_1h.empty and len(df_1h) >= 20:
                    avg_v = float(df_1h["volume"].tail(20).mean())
                    cur_v = float(df_1h["volume"].iloc[-1])
                    if avg_v > 0:
                        vr = cur_v / avg_v
                        vol_str = f" vol={vr:.1f}x" + (" [LOW]" if vr < 0.4 else "")

                # Build compact summary
                assessments = []
                for s in statuses:
                    strat = s.get("strategy", "?")
                    if strat == "regime_trend":
                        align_l = s.get("align_long", 0)
                        align_s = s.get("align_short", 0)
                        cross = s.get("cross", "none")
                        assessments.append(f"RT: L{align_l}/S{align_s} cross={cross}")
                    elif strat == "monte_carlo_zones":
                        action = s.get("action", "?")
                        mc = s.get("mc_prediction", {})
                        up = mc.get("up_prob", 0) if mc else 0
                        assessments.append(f"MC: {action} up={up:.0%}")
                    elif strat == "confidence_scorer":
                        action = s.get("action", "?")
                        assessments.append(f"CS: {action}")
                    elif strat == "multi_tier_quality":
                        side = s.get("side", "?")
                        regime = s.get("regime_score", 0)
                        assessments.append(f"MT: {side} regime={regime}")

                assessment_str = " | ".join(assessments)

                # Check if any open position
                open_pos = self.pos_mgr.get_open_positions()
                pos_str = ""
                if symbol in open_pos:
                    pos = open_pos[symbol]
                    pnl = (price - pos.entry) * pos.qty if pos.side == "LONG" else (pos.entry - price) * pos.qty
                    pos_str = f" [OPEN {pos.side} {pos.leverage:.0f}x PnL=${pnl:+,.0f}]"

                lines.append(f"  {symbol} ${_fmt_price(price)}{vol_str}{pos_str}")
                lines.append(f"    {assessment_str}")

            except Exception as e:
                lines.append(f"  {symbol}: error ({e})")

        msg = "\n".join(lines)
        self.alerts.send_market_update(msg)
        logger.info(msg.replace("\n", " | "))


def main():
    # Load .env (project root first, then bot/)
    try:
        from pathlib import Path
        from dotenv import load_dotenv
        root_env = Path(__file__).parent.parent / ".env"
        if root_env.exists():
            load_dotenv(root_env)
        else:
            load_dotenv()
    except ImportError:
        pass

    os.makedirs("ml_data", exist_ok=True)
    init_db()  # Initialize SQLite database for trade journal

    config = TradingConfig()
    bot = MultiStrategyBot(config)
    bot.run()


if __name__ == "__main__":
    main()
