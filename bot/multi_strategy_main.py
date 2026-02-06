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
from datetime import datetime, timezone
from typing import Dict, Any

from data.fetcher import DataFetcher
from trading_config import TradingConfig, DEFAULT_SYMBOLS
from strategies.regime_trend import RegimeTrendStrategy
from strategies.monte_carlo_zones import MonteCarloZonesStrategy
from strategies.confidence_scorer import ConfidenceScorerStrategy
from strategies.multi_tier_quality import MultiTierQualityStrategy
from strategies.ensemble import EnsembleStrategy
from execution.position_manager import PositionManager
from execution.leverage import LeverageManager
from execution.risk import RiskManager, CircuitBreaker
from ml.learner import SignalLearner, TradeOutcome
from alerts.router import AlertRouter

# Setup logging
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

        self._tick = 0
        self._needed_tfs = self.ensemble.get_all_required_timeframes()

    def run(self):
        """Main run loop."""
        logger.info("=" * 60)
        logger.info(f"Multi-Strategy Bot Starting")
        logger.info(f"  Environment: {self.config.environment}")
        logger.info(f"  Symbols: {list(DEFAULT_SYMBOLS.keys())}")
        logger.info(f"  Strategies: {[s.name for s in self.strategies]}")
        logger.info(f"  Ensemble mode: {self.config.ensemble_mode} (min_votes={self.config.min_votes_required})")
        logger.info(f"  Leverage: {'enabled' if self.config.enable_leverage else 'disabled'} (max={self.config.max_leverage}x)")
        logger.info(f"  ML: {'enabled' if self.config.enable_ml else 'disabled'}")
        logger.info(f"  Trailing stop: {'enabled' if self.config.enable_trailing_stop else 'disabled'}")
        logger.info(f"  Scan interval: {self.config.scan_interval_s}s")
        logger.info("=" * 60)

        if self.config.auto_trade:
            logger.warning("AUTO-TRADING ENABLED - REAL MONEY MODE")
            logger.warning("Starting in 5 seconds... Press CTRL+C to abort")
            time.sleep(5)

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
        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            try:
                self._process_symbol(symbol, sym_cfg)
            except Exception as e:
                logger.error(f"[{symbol}] Error: {e}", exc_info=True)

        # Heartbeat every 60 ticks
        if self._tick % 60 == 0:
            self._send_heartbeat()

    def _process_symbol(self, symbol: str, sym_cfg):
        """Process one symbol: fetch data, check positions, generate signals."""
        # Fetch data for all needed timeframes
        data = self.fetcher.fetch_multi_timeframe(sym_cfg.coingecko_id, self._needed_tfs)

        # Get current price
        current_price = self.fetcher.latest_price(sym_cfg.coingecko_id)
        if current_price is None:
            return

        # Update existing positions
        events = self.pos_mgr.update_price(symbol, current_price)
        for event in events:
            self.risk_mgr.update_equity(event.pnl - event.fee)

            # Record outcome for ML
            if self.ml and event.action in ("SL", "TP2", "TRAILING_STOP"):
                pos = self.pos_mgr.positions.get(symbol)
                self.ml.record_outcome(TradeOutcome(
                    symbol=symbol,
                    strategy=event.strategy,
                    side=event.side,
                    confidence=pos.confidence if pos else 0,
                    leverage=event.leverage,
                    win=event.pnl > 0,
                    pnl=event.pnl,
                    exit_action=event.action,
                    hold_time_s=event.metadata.get("hold_time_s", 0),
                    hour_of_day=datetime.now(timezone.utc).hour,
                    day_of_week=datetime.now(timezone.utc).weekday(),
                ))

            # Send alert
            details = (
                f"{event.action} {event.side} @ {event.price:.4f}\n"
                f"PnL: ${event.pnl:+.2f} | Leverage: {event.leverage:.1f}x"
            )
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

        # Try to generate new signal
        if not self.risk_mgr.can_open_position(self.pos_mgr.get_open_count()):
            return
        if symbol in open_pos:
            return  # Already have position in this symbol

        signal_result = self.ensemble.evaluate(symbol, data)
        if signal_result is None:
            return

        # ML confidence adjustment
        original_conf = signal_result.confidence
        if self.ml:
            adjusted_conf = self.ml.adjust_confidence(
                original_conf,
                regime_score=signal_result.metadata.get("align_long", 0) or signal_result.metadata.get("regime_score", 0),
                vwap_aligned=signal_result.metadata.get("vwap_align", False),
                ema_aligned=signal_result.metadata.get("ema_1h_align", False),
                stop_width_ratio=signal_result.stop_width / max(signal_result.atr, 1e-9) if signal_result.atr else 1.5,
                leverage=1.0,
                side=signal_result.side,
            )
            signal_result.confidence = adjusted_conf

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

        # Calculate position size
        qty = self.risk_mgr.calculate_qty(signal_result.entry, signal_result.sl)
        if qty <= 0:
            return

        # Open position
        side = "LONG" if signal_result.side == "BUY" else "SHORT"
        self.pos_mgr.open_position(
            symbol=symbol,
            side=side,
            entry=signal_result.entry,
            qty=qty,
            sl=signal_result.sl,
            tp1=signal_result.tp1,
            tp2=signal_result.tp2,
            atr=signal_result.atr,
            leverage=lev_decision.leverage,
            mode=lev_decision.mode,
            strategy=signal_result.strategy,
            confidence=signal_result.confidence,
        )

        # Send signal alert
        tier = signal_result.metadata.get("tier", "")
        self.alerts.send_signal(signal_result, lev_decision.leverage, tier)

        logger.info(
            f"[{symbol}] OPENED {side} | Conf: {original_conf:.0f}%->{signal_result.confidence:.0f}% | "
            f"Lev: {lev_decision.leverage:.1f}x ({lev_decision.reason}) | "
            f"Strategies: {signal_result.metadata.get('strategies_agree', [signal_result.strategy])}"
        )

    def _send_heartbeat(self):
        """Send periodic status heartbeat."""
        status = {
            "equity": self.risk_mgr.equity,
            "open_positions": self.pos_mgr.get_open_count(),
            "daily_pnl": self.risk_mgr.circuit_breaker.daily_pnl,
            "ml_samples": len(self.ml.outcomes) if self.ml else 0,
            "circuit_breaker": self.risk_mgr.circuit_breaker.get_status(),
        }
        self.alerts.send_heartbeat(status)
        logger.info(
            f"[HEARTBEAT] equity=${status['equity']:,.2f} "
            f"positions={status['open_positions']} "
            f"daily_pnl=${status['daily_pnl']:+,.2f} "
            f"ml_samples={status['ml_samples']}"
        )


def main():
    # Ensure log directory exists
    os.makedirs("logs", exist_ok=True)
    os.makedirs("ml_data", exist_ok=True)

    config = TradingConfig()
    bot = MultiStrategyBot(config)
    bot.run()


if __name__ == "__main__":
    main()
