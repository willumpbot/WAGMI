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
from data.db import init_db, log_signal, log_trade, log_equity, get_daily_summary
from data.strategy_weights import StrategyWeightManager
from data.risk_log import log_rejection, get_rejection_counts
from data.ml_log import log_ml_stats, log_ml_confidence
from data.trade_log import log_closed_trade
from data.learning import record_trade_outcome, get_performance
from trading_config import TradingConfig, DEFAULT_SYMBOLS
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


# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log"),
    ],
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

        # Data
        self.fetcher = DataFetcher(
            max_retries=3,
            retry_delay=5.0,
            cache_ttl=max(30, config.scan_interval_s - 5),
        )

        # Strategy accuracy weights
        self.weight_mgr = StrategyWeightManager(
            path="ml_data/strategy_weights.json",
            decay_alpha=0.9,
        )

        # Strategies
        sym_configs = DEFAULT_SYMBOLS
        self.strategies = [
            RegimeTrendStrategy(sym_configs, config.htf_hours),
            MonteCarloZonesStrategy(sym_configs),
            ConfidenceScorerStrategy(sym_configs, data_dir="ml_data"),
            MultiTierQualityStrategy(sym_configs),
        ]
        self.ensemble = EnsembleStrategy(
            strategies=self.strategies,
            mode=config.ensemble_mode,
            min_votes=config.min_votes_required,
            weight_manager=self.weight_mgr,
            veto_ratio=config.veto_ratio,
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
        self._cooldown_seconds = 120  # 2 minutes after a loss
        self._win_cooldown_seconds = 300  # 5 minutes after a win (anti-round-trip)

        # Correlation guard: prevent correlated blowups
        self._max_same_direction = int(os.getenv("MAX_SAME_DIRECTION", "3"))
        self._max_same_tier = int(os.getenv("MAX_SAME_TIER", "2"))

        # Track last close result per symbol for anti-round-tripping
        self._last_close_win: Dict[str, bool] = {}  # symbol -> was_win
        self._last_close_side: Dict[str, str] = {}  # symbol -> "LONG"/"SHORT"

        # Signal dedup: prevent spam from repeated same-side evaluations
        self._last_signal: Dict[str, tuple] = {}  # symbol -> (side, timestamp)
        self._signal_dedup_seconds = 300  # 5 minutes between same-side signals per symbol

        # Last known prices for fill-price validation
        self._last_prices: Dict[str, float] = {}  # symbol -> price

        # LLM meta-brain
        self.llm_mode = get_llm_mode()
        self._llm_triggers = TriggerAccumulator()

        # Dual-world candidate logging (baseline vs LLM)
        self._candidate_logger = CandidateLogger()

        # Track 1h price changes for cross-market divergence detection
        self._price_changes_1h: Dict[str, float] = {}

        # Telegram command bot
        tg_user_id = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))
        self.telegram_bot = TelegramCommandBot(
            token=config.telegram_token,
            allowed_user_id=tg_user_id,
            bot_instance=self,
        )

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
        logger.info("=" * 60)

        # Startup health check
        self._run_health_check()

        if self.config.auto_trade:
            logger.warning("AUTO-TRADING ENABLED - REAL MONEY MODE")
            logger.warning("Starting in 5 seconds... Press CTRL+C to abort")
            time.sleep(5)

        # Start Telegram command bot
        self.telegram_bot.start()

        # Signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        while not self.stop_event.is_set():
            try:
                self._tick_once()
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)

            self._tick += 1
            self._sleep_interruptible(self.config.scan_interval_s)

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

        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            try:
                self._process_symbol(symbol, sym_cfg, trace_id)
            except Exception as e:
                logger.error(f"[{trace_id}][{symbol}] Error: {e}", exc_info=True)

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

        # Heartbeat every 60 ticks (~1 hour at 60s intervals)
        if self._tick % 60 == 0:
            self._send_heartbeat()

        # Market update every 15 ticks (~15 min) - sends even without signals
        if self._tick % 15 == 0 and self._tick % 60 != 0:
            self._send_market_update(trace_id)

    def _process_symbol(self, symbol: str, sym_cfg, trace_id: str = ""):
        """Process one symbol: fetch data, check positions, generate signals."""
        # Fetch data for all needed timeframes
        data = self.fetcher.fetch_multi_timeframe(symbol, sym_cfg.coingecko_id, self._needed_tfs)

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
                           "EMERGENCY", "LIQUIDATION_AVOID")

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

            # Record outcome for ML (use TOTAL trade PnL, not just final leg)
            if self.ml and event.action in _FULL_CLOSE:
                pos = self.pos_mgr.positions.get(symbol)
                total_pnl = pos.realized_pnl if pos else event.pnl
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
                ))

            # Learning hooks + enhanced trade log on full closes
            if event.action in _FULL_CLOSE:
                self._symbol_cooldown[symbol] = time.time()
                pos = self.pos_mgr.positions.get(symbol)
                # Anti-round-trip: track win/loss and side for cooldown logic
                if pos:
                    self._last_close_win[symbol] = pos.realized_pnl > 0
                    self._last_close_side[symbol] = pos.side

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

            # Send alert
            details = (
                f"{event.action} {event.side} @ {_fmt_price(event.price)}\n"
                f"PnL: ${event.pnl:+.2f} | Leverage: {event.leverage:.1f}x"
            )
            if event.action in _FULL_CLOSE:
                pos = self.pos_mgr.positions.get(symbol)
                if pos:
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
        if symbol in open_pos:
            return  # Already have position in this symbol
        if self.pos_mgr.get_open_count() >= self.risk_mgr.max_open_positions:
            return  # Max positions reached (hard limit, no override)

        # Per-symbol cooldown: don't re-enter too quickly after closing
        # Longer cooldown after WINS to prevent round-tripping profits
        last_close = self._symbol_cooldown.get(symbol, 0)
        was_win = self._last_close_win.get(symbol, False)
        cd = self._win_cooldown_seconds if was_win else self._cooldown_seconds
        if time.time() - last_close < cd:
            return

        # Correlation guard: check before evaluating (saves compute)
        # We need to know the signal direction first, so we do a quick check
        # on existing positions to reject early if same-tier is maxed out
        sym_tier = sym_cfg.risk_tier
        tier_count = sum(
            1 for s, p in open_pos.items()
            if DEFAULT_SYMBOLS.get(s) and DEFAULT_SYMBOLS[s].risk_tier == sym_tier
        )
        if tier_count >= self._max_same_tier:
            return  # Too many positions in same risk tier

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

        # Regime shift detection (from strategy metadata)
        current_regime = signal_result.metadata.get("regime", "")
        if current_regime and self._llm_triggers.check_regime_shift(symbol, current_regime):
            self._llm_triggers.add(
                LLMTrigger.REGIME_SHIFT,
                symbol=symbol,
                context=f"{symbol} regime shifted to '{current_regime}'",
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

        # Log every signal generated to database (even if not traded)
        log_signal(
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

        # ── Circuit breaker check (with high-confidence override) ──
        if not self.risk_mgr.can_open_position(
            self.pos_mgr.get_open_count(),
            confidence=signal_result.confidence,
            cb_conf_override_pct=self.config.cb_conf_override_pct,
        ):
            return

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

        # Calculate position size (risk-based: qty = risk$ / (stop_dist * leverage))
        qty = self.risk_mgr.calculate_qty(
            signal_result.entry, signal_result.sl,
            leverage=lev_decision.leverage,
            risk_multiplier=lev_decision.risk_multiplier,
            symbol=symbol,
        )
        if qty <= 0:
            return

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
                return
            else:
                # LLM approved (or API failed -> default proceed)
                candidate.llm_action = "proceed"
                if veto_result is None:
                    # _llm_veto_check returns None for proceed
                    pass

        # Log candidate as proceeding (will be updated with outcome on close)
        candidate.llm_action = candidate.llm_action or "no_llm"
        candidate.leverage_used = lev_decision.leverage
        self._candidate_logger.log_candidate(candidate)

        # Open position with profile-adjusted levels
        self.pos_mgr.open_position(
            symbol=symbol,
            side=side,
            entry=signal_result.entry,
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

        # Log trade open to database
        log_trade(
            symbol=symbol,
            action="OPEN",
            side=side,
            price=signal_result.entry,
            qty=qty,
            leverage=lev_decision.leverage,
            strategy=signal_result.strategy,
            metadata={"confidence": signal_result.confidence, "strategies": signal_result.metadata.get("strategies_agree", [])}
        )

        # Mark signal as traded
        log_signal(
            symbol=symbol,
            strategy=signal_result.strategy,
            side=signal_result.side,
            confidence=signal_result.confidence,
            entry=signal_result.entry,
            sl=signal_result.sl,
            tp1=signal_result.tp1,
            tp2=signal_result.tp2,
            atr=signal_result.atr,
            leverage=lev_decision.leverage,
            traded=True,
            metadata=signal_result.metadata
        )

        # Send signal alert
        tier = signal_result.metadata.get("tier", "")
        self.alerts.send_signal(signal_result, lev_decision.leverage, tier)

        logger.info(
            f"[{trace_id}][{symbol}] OPENED {side} | "
            f"Type: {trade_prof.entry_type} | "
            f"Conf: {original_conf:.0f}%->{signal_result.confidence:.0f}% | "
            f"Lev: {lev_decision.leverage:.1f}x ({lev_decision.reason}) | "
            f"TP1close: {tp1_pct:.0%} | Trail: {trade_prof.exit_params.trailing_style} | "
            f"Regime: {trade_prof.regime} | "
            f"Driver: {trade_prof.primary_driver} | "
            f"Strategies: {signal_result.metadata.get('strategies_agree', [signal_result.strategy])}"
        )

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

        # Global context
        eth_btc = eth_price / btc_price if btc_price > 0 else 0.0
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

        # Risk context
        risk_ctx = LLMRiskContext(
            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
            max_daily_loss=self.risk_mgr.equity * self.config.circuit_breaker_daily_loss_pct,
            equity=self.risk_mgr.equity,
            max_leverage=self.config.max_leverage,
            current_leverage=0.0,  # TODO: sum of open position leverages
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
            })

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

        self.alerts.send_heartbeat(status)
        strat_weights = self.weight_mgr.get_all_weights()
        weights_str = " ".join(f"{k}={v:.2f}" for k, v in strat_weights.items()) if strat_weights else "none"
        rej_str = " ".join(f"{k}={v}" for k, v in rejections.items()) if rejections else "none"
        wr20 = perf.get("win_rate_20", 0)
        logger.info(
            f"[HEARTBEAT] equity=${status['equity']:,.2f} "
            f"positions={status['open_positions']} "
            f"daily_pnl=${status['daily_pnl']:+,.2f} "
            f"WR20={wr20:.0%} "
            f"ml_trades={status['ml_samples']} "
            f"ml_snaps={status['ml_snapshots']}({status['ml_snap_trained']}filled) "
            f"direction_model={'YES' if status['ml_direction_model'] else 'no'} "
            f"strat_weights=[{weights_str}] "
            f"rejections=[{rej_str}] "
            f"api={fetcher_stats['total_requests']} "
            f"cache={fetcher_stats['cache_hits']}"
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
    os.makedirs("ml_data", exist_ok=True)
    init_db()  # Initialize SQLite database for trade journal

    config = TradingConfig()
    bot = MultiStrategyBot(config)
    bot.run()


if __name__ == "__main__":
    main()
