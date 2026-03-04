"""
Backtesting engine.
Downloads historical data, feeds it candle-by-candle to strategies,
simulates position management with realistic fills and fees,
and generates performance reports.

Usage:
    python -m backtest.engine --symbol BTC --days 30 --strategy all
"""

import argparse
import json
import logging
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.fetcher import DataFetcher
from trading_config import TradingConfig, DEFAULT_SYMBOLS
from strategies.base import Signal
from strategies.regime_trend import RegimeTrendStrategy
from strategies.monte_carlo_zones import MonteCarloZonesStrategy
from strategies.confidence_scorer import ConfidenceScorerStrategy
from strategies.multi_tier_quality import MultiTierQualityStrategy
from strategies.ensemble import EnsembleStrategy
from execution.position_manager import PositionManager
from execution.leverage import LeverageManager
from execution.risk import RiskManager, CircuitBreaker

logger = logging.getLogger("bot.backtest")


class BacktestEngine:
    """
    Simulates trading strategies on historical data.

    Process:
    1. Fetch historical OHLCV data for all needed timeframes
    2. Walk forward through 1h candles (the highest resolution we need)
    3. At each step, build data windows for each timeframe
    4. Run ensemble strategy evaluation
    5. Open/manage positions with PositionManager
    6. Track equity curve, PnL, etc.
    """

    def __init__(self, config: Optional[TradingConfig] = None, llm_integration=None):
        self.config = config or TradingConfig()
        self.llm = llm_integration  # Optional BacktestLLMIntegration

        # Initialize components
        self.fetcher = DataFetcher(cache_ttl=3600, backtest_mode=True)
        self.risk_mgr = RiskManager(
            starting_equity=self.config.starting_equity,
            risk_per_trade=self.config.risk_per_trade,
            max_open_positions=self.config.max_open_positions,
            circuit_breaker=CircuitBreaker(
                daily_loss_limit_pct=self.config.circuit_breaker_daily_loss_pct,
                max_consecutive_losses=self.config.max_consecutive_losses,
            ),
        )
        self.pos_mgr = PositionManager(
            taker_fee_bps=self.config.taker_fee_bps,
            enable_trailing=self.config.enable_trailing_stop,
            trailing_atr_mult=self.config.trailing_stop_atr_mult,
        )
        self.leverage_mgr = LeverageManager(
            enable_leverage=self.config.enable_leverage,
            max_leverage=self.config.max_leverage,
        )

        # Results
        self.equity_curve: List[Dict] = []
        self.signals_generated: List[Dict] = []

    def run(
        self,
        symbols: List[str],
        days: int = 30,
        strategies: Optional[List[str]] = None,
        learn: bool = False,
    ) -> Dict[str, Any]:
        """
        Run a backtest.

        Args:
            symbols: List of symbol names (e.g. ["BTC", "ETH", "SOL"])
            days: Number of days of historical data to test on
            strategies: Which strategies to use (default: all)
            learn: If True, feed results into all learning systems

        Returns:
            Dict with backtest results (includes learning_summary if learn=True)
        """
        logger.info(f"Starting backtest: {symbols} | {days} days | strategies={strategies or 'all'}")

        # Build strategies
        sym_configs = {s: DEFAULT_SYMBOLS[s] for s in symbols if s in DEFAULT_SYMBOLS}
        active_strategies = self._build_strategies(sym_configs, strategies)

        ensemble = EnsembleStrategy(
            strategies=active_strategies,
            mode=self.config.ensemble_mode,
            min_votes=self.config.min_votes_required,
            veto_ratio=self.config.veto_ratio,
        )

        # Fetch historical data for all symbols
        all_data = {}
        needed_tfs = ensemble.get_all_required_timeframes()

        for symbol in symbols:
            sym_cfg = sym_configs.get(symbol)
            if not sym_cfg:
                continue
            logger.info(f"Fetching data for {symbol} ({sym_cfg.coingecko_id})")
            data = self.fetcher.fetch_multi_timeframe(symbol, sym_cfg.coingecko_id, needed_tfs)
            all_data[symbol] = data

        # LLM preflight: validate everything before spending API credits
        if self.llm:
            preflight = self.llm.run_preflight(symbols, all_data, ensemble, self.config)
            if not preflight.passed:
                return {
                    "error": "preflight_failed",
                    "errors": preflight.errors,
                    "warnings": preflight.warnings,
                }
            print(f"\n  Preflight: PASSED")
            print(f"  Estimated cost: ${preflight.estimated_cost:.2f} ({preflight.estimated_llm_calls} API calls)")
            print(f"  Candles to process: {preflight.candle_count}")
            if preflight.warnings:
                for w in preflight.warnings:
                    print(f"  WARNING: {w}")
            try:
                confirm = input(f"\n  Proceed with LLM backtest (budget ${self.llm.budget_usd:.2f})? [y/N] ")
                if confirm.strip().lower() != "y":
                    return {"error": "user_cancelled"}
            except (EOFError, KeyboardInterrupt):
                return {"error": "user_cancelled"}
            print()

            # Handle resume: restore equity from checkpoint
            if self.llm.resume_state:
                self.risk_mgr.equity = self.llm.resume_state.equity
                logger.info(
                    f"Resumed from checkpoint: equity=${self.llm.resume_state.equity:.2f}"
                )

        # Track which symbols are completed (for checkpoint/resume)
        symbols_completed = []
        if self.llm and self.llm.resume_state:
            symbols_completed = list(self.llm.resume_state.symbols_completed)

        # Walk forward through data
        # Use 1h timeframe as the primary clock
        for symbol in symbols:
            # Skip already-completed symbols on resume
            if symbol in symbols_completed:
                logger.info(f"Skipping {symbol} (already completed in checkpoint)")
                continue
            data = all_data.get(symbol, {})
            df_1h = data.get("1h", pd.DataFrame())
            if df_1h.empty:
                # Try daily data for zone strategies
                df_daily = data.get("daily", pd.DataFrame())
                if df_daily.empty:
                    logger.warning(f"No data for {symbol}, skipping")
                    continue
                self._walk_daily(symbol, data, ensemble)
            else:
                self._walk_hourly(symbol, data, ensemble)

            symbols_completed.append(symbol)

        # Flush LLM decisions and generate report
        if self.llm:
            self.llm.flush_decisions()

        report = self._generate_report(symbols, days)

        # Feed learning systems if requested
        if learn:
            report["learning_summary"] = self._run_learning_bridge()

        return report

    def _run_learning_bridge(self) -> Dict[str, Any]:
        """Feed backtest results into all learning systems."""
        try:
            from backtest.learning_bridge import BacktestLearningBridge

            bridge = BacktestLearningBridge()
            result = bridge.ingest(self)
            print("\n" + bridge.get_summary())
            return result
        except Exception as e:
            logger.warning(f"Learning bridge failed: {e}")
            return {"status": "error", "error": str(e)}

    def _build_strategies(self, sym_configs, strategy_names) -> list:
        """Build strategy instances."""
        all_strats = {
            "regime_trend": RegimeTrendStrategy(sym_configs, self.config.htf_hours),
            "monte_carlo_zones": MonteCarloZonesStrategy(sym_configs),
            "confidence_scorer": ConfidenceScorerStrategy(sym_configs, data_dir="backtest_ml_data"),
            "multi_tier_quality": MultiTierQualityStrategy(sym_configs),
        }

        if strategy_names:
            return [s for name, s in all_strats.items() if name in strategy_names]
        return list(all_strats.values())

    def _walk_hourly(self, symbol: str, data: Dict[str, pd.DataFrame], ensemble: EnsembleStrategy):
        """Walk forward through hourly candles."""
        df_1h = data.get("1h", pd.DataFrame())
        if df_1h.empty or len(df_1h) < 50:
            return

        # We need enough history before we start generating signals
        warmup = 50
        total_candles = len(df_1h)

        # Handle resume: skip to checkpointed candle
        start_idx = warmup
        if (self.llm and self.llm.resume_state
                and self.llm.resume_state.symbol == symbol):
            start_idx = max(warmup, self.llm.resume_state.candle_index + 1)
            logger.info(f"[{symbol}] Resuming from candle {start_idx}")

        for i in range(start_idx, total_candles):
            # Build windowed data for this point in time
            windowed = {}
            for tf, df in data.items():
                if df.empty:
                    continue
                current_time = df_1h["time"].iloc[i]
                # Only include data up to current time
                mask = df["time"] <= current_time
                windowed[tf] = df[mask].copy()

            current_price = float(df_1h["close"].iloc[i])

            # Parse simulation timestamp for circuit breaker time awareness
            sim_time = pd.Timestamp(df_1h["time"].iloc[i])
            if sim_time.tzinfo is None:
                sim_time = sim_time.tz_localize("UTC")
            sim_dt = sim_time.to_pydatetime()

            # Check existing positions
            events = self.pos_mgr.update_price(symbol, current_price)
            for event in events:
                self.risk_mgr.update_equity(event.pnl - event.fee, sim_time=sim_dt)
                # LLM: run Learning Agent on closed trades
                if self.llm and event.action in self._CLOSE_ACTIONS:
                    self.llm.clear_exit_counter(event.symbol)
                    self._run_llm_learning(event, current_price)

            # LLM: run Exit Agent on open positions
            if self.llm:
                self._run_llm_exit(symbol, current_price, windowed, sim_dt)

            # Try to generate signal
            if self.risk_mgr.can_open_position(self.pos_mgr.get_open_count(), sim_time=sim_dt):
                signal = ensemble.evaluate(symbol, windowed)
                if signal:
                    # LLM: evaluate signal through multi-agent pipeline
                    signal = self._apply_llm_entry(
                        signal, symbol, windowed, current_price, sim_dt
                    )
                    if signal:
                        self._execute_signal(signal, current_price)

            # Record equity
            self.equity_curve.append({
                "time": str(df_1h["time"].iloc[i]),
                "equity": self.risk_mgr.equity,
                "open_positions": self.pos_mgr.get_open_count(),
            })

            # LLM: checkpoint and progress
            if self.llm:
                if i % 10 == 0:
                    self.llm.save_checkpoint(
                        candle_index=i,
                        symbol=symbol,
                        symbols_completed=[],  # Updated after symbol completes
                        equity=self.risk_mgr.equity,
                    )
                if i % 50 == 0:
                    print(self.llm.get_progress_line(i - warmup, total_candles - warmup))

        # Force-close any open position at end of symbol walk
        self._force_close_open(symbol, current_price, sim_dt)

    def _walk_daily(self, symbol: str, data: Dict[str, pd.DataFrame], ensemble: EnsembleStrategy):
        """Walk forward through daily data points."""
        df = data.get("daily", pd.DataFrame())
        if df.empty or len(df) < 50:
            return

        warmup = 50
        total_candles = len(df)

        start_idx = warmup
        if (self.llm and self.llm.resume_state
                and self.llm.resume_state.symbol == symbol):
            start_idx = max(warmup, self.llm.resume_state.candle_index + 1)

        for i in range(start_idx, total_candles):
            windowed = {}
            for tf, df_tf in data.items():
                if df_tf.empty:
                    continue
                current_time = df["time"].iloc[i]
                mask = df_tf["time"] <= current_time
                windowed[tf] = df_tf[mask].copy()

            current_price = float(df["close"].iloc[i])

            # Parse simulation timestamp for circuit breaker time awareness
            sim_time = pd.Timestamp(df["time"].iloc[i])
            if sim_time.tzinfo is None:
                sim_time = sim_time.tz_localize("UTC")
            sim_dt = sim_time.to_pydatetime()

            events = self.pos_mgr.update_price(symbol, current_price)
            for event in events:
                self.risk_mgr.update_equity(event.pnl - event.fee, sim_time=sim_dt)
                if self.llm and event.action in self._CLOSE_ACTIONS:
                    self.llm.clear_exit_counter(event.symbol)
                    self._run_llm_learning(event, current_price)

            if self.llm:
                self._run_llm_exit(symbol, current_price, windowed, sim_dt)

            if self.risk_mgr.can_open_position(self.pos_mgr.get_open_count(), sim_time=sim_dt):
                signal = ensemble.evaluate(symbol, windowed)
                if signal:
                    signal = self._apply_llm_entry(
                        signal, symbol, windowed, current_price, sim_dt
                    )
                    if signal:
                        self._execute_signal(signal, current_price)

            self.equity_curve.append({
                "time": str(df["time"].iloc[i]),
                "equity": self.risk_mgr.equity,
                "open_positions": self.pos_mgr.get_open_count(),
            })

            if self.llm:
                if i % 10 == 0:
                    self.llm.save_checkpoint(i, symbol, [], self.risk_mgr.equity)
                if i % 50 == 0:
                    print(self.llm.get_progress_line(i - warmup, total_candles - warmup))

        # Force-close any open position at end of symbol walk
        self._force_close_open(symbol, current_price, sim_dt)

    # ── LLM Integration Helpers ────────────────────────────────────

    def _apply_llm_entry(self, signal, symbol, windowed, current_price, sim_dt):
        """Run LLM multi-agent pipeline on a signal. Returns signal or None (vetoed)."""
        if not self.llm:
            return signal

        snapshot_data = self.llm.build_backtest_snapshot(
            symbol=symbol,
            windowed_data=windowed,
            signal=signal,
            current_price=current_price,
            open_positions=self.pos_mgr.get_open_positions(),
            equity=self.risk_mgr.equity,
            circuit_breaker_active=not self.risk_mgr.can_open_position(
                self.pos_mgr.get_open_count(), sim_time=sim_dt
            ),
        )

        decision = self.llm.evaluate_entry(snapshot_data, signal, "pre_trade_backtest")
        if decision is None:
            return signal  # No LLM opinion -> use strategy signal as-is

        # Apply LLM decision
        if decision.action == "flat":
            logger.debug(f"[{symbol}] LLM vetoed signal: {decision.notes[:80] if decision.notes else ''}")
            return None  # Vetoed

        # Apply size multiplier to confidence (influences position sizing)
        if decision.size_multiplier != 1.0:
            signal.confidence = max(1.0, min(100.0, signal.confidence * decision.size_multiplier))

        return signal

    def _run_llm_exit(self, symbol, current_price, windowed, sim_dt):
        """Run Exit Agent on open position for this symbol."""
        pos = self.pos_mgr.positions.get(symbol)
        if not pos or pos.state == "CLOSED":
            return

        position_data = {
            "symbol": symbol,
            "side": pos.side,
            "entry": pos.entry,
            "sl": pos.sl,
            "tp1": pos.tp1,
            "tp2": pos.tp2,
            "leverage": pos.leverage,
            "state": pos.state,
            "unrealized_pnl": (
                (current_price - pos.entry) * pos.qty
                if pos.side == "LONG"
                else (pos.entry - current_price) * pos.qty
            ),
            # Exit Agent expects these for thesis-based and duration-based decisions
            "hold_time_s": (sim_dt - pos.open_time).total_seconds() if hasattr(pos, "open_time") and pos.open_time else 0,
            "thesis": getattr(pos, "notes", "")[:200],
            "setup_type": getattr(pos, "setup_type", ""),
        }

        # Build minimal market snapshot for exit context
        market_data = self.llm.build_backtest_snapshot(
            symbol=symbol,
            windowed_data=windowed,
            signal=None,
            current_price=current_price,
            open_positions=self.pos_mgr.get_open_positions(),
            equity=self.risk_mgr.equity,
        )

        exit_rec = self.llm.evaluate_exit(position_data, market_data)
        if (exit_rec
                and exit_rec.get("action") == "close"
                and exit_rec.get("urgency") in ("high", "critical")):
            event = self.pos_mgr.force_close(symbol, current_price, reason="LLM_EXIT")
            if event:
                self.risk_mgr.update_equity(event.pnl - event.fee, sim_time=sim_dt)
                logger.info(
                    f"[{symbol}] LLM Exit Agent closed position: "
                    f"PnL={event.pnl:.2f}, reason={exit_rec.get('reason', '')[:60]}"
                )

    def _run_llm_learning(self, event, current_price):
        """Run Learning Agent on a closed trade.

        Enriches trade_data from event.metadata which contains regime,
        hold_time_s, entry_reasons, setup_type from the Position.
        Note: event.price on close events is the EXIT price, not entry.
        Entry price is recovered from the OPEN event in trade_log.
        """
        meta = event.metadata or {}

        # Find entry price from the OPEN event for this symbol
        entry_price = 0.0
        for log_event in self.pos_mgr.trade_log:
            if log_event.symbol == event.symbol and log_event.action == "OPEN":
                entry_price = log_event.price
                # Don't break — use the most recent OPEN for this symbol

        trade_data = {
            "symbol": event.symbol,
            "side": event.side,
            "pnl": event.pnl,
            "outcome": meta.get("outcome", "WIN" if event.pnl > 0 else "LOSS"),
            "exit_reason": event.action,
            "leverage": event.leverage,
            "strategy": event.strategy or "unknown",
            "exit_price": current_price,
            "entry_price": entry_price,
            "regime": meta.get("regime", "unknown"),
            "hold_time_s": meta.get("hold_time_s", 0),
            "entry_reasons": meta.get("entry_reasons", {}),
            "setup_type": meta.get("entry_type", ""),
            "confidence": meta.get("confidence", 0),
        }
        self.llm.run_learning(trade_data)

    def _force_close_open(self, symbol: str, last_price: float, sim_dt: datetime):
        """Force-close any open position at the end of a symbol's walk."""
        pos = self.pos_mgr.positions.get(symbol)
        if pos and pos.state != "CLOSED":
            event = self.pos_mgr.force_close(symbol, last_price, reason="BACKTEST_END")
            if event:
                self.risk_mgr.update_equity(event.pnl - event.fee, sim_time=sim_dt)
                logger.info(f"[{symbol}] Force-closed at backtest end: PnL={event.pnl:.2f}")

    def _execute_signal(self, signal: Signal, current_price: float):
        """Execute a signal in backtest mode with slippage simulation."""
        from execution.trade_profile import classify_trade, apply_profile_to_signal

        # Apply slippage to entry price (simulate realistic fills)
        slippage_bps = getattr(self.config, "slippage_bps", 0)
        slip_mult = slippage_bps / 10000.0
        if signal.side == "BUY":
            fill_price = signal.entry * (1 + slip_mult)  # Buy higher
        else:
            fill_price = signal.entry * (1 - slip_mult)  # Sell lower

        # Determine leverage
        num_agree = signal.metadata.get("num_agree", 1)
        total = signal.metadata.get("total_strategies", 4)

        sym_cfg = DEFAULT_SYMBOLS.get(signal.symbol)
        risk_tier = sym_cfg.risk_tier if sym_cfg else "medium"

        extreme_count = sum(
            1 for p in self.pos_mgr.get_open_positions().values()
            if p.leverage > 5.0
        )

        lev_decision = self.leverage_mgr.decide(
            signal.confidence, num_agree, total, risk_tier, extreme_count
        )

        if lev_decision.leverage <= 0:
            return

        qty = self.risk_mgr.calculate_qty(
            fill_price, signal.sl, lev_decision.leverage, lev_decision.risk_multiplier,
            slippage_bps=slippage_bps,
        )
        if qty <= 0:
            return

        side = "LONG" if signal.side == "BUY" else "SHORT"

        # Classify trade and apply profile-based exit levels
        trade_prof = classify_trade(
            signal_metadata=signal.metadata,
            confidence=signal.confidence,
            atr=signal.atr,
            entry=fill_price,
            side=signal.side,
        )
        adjusted = apply_profile_to_signal(
            trade_prof,
            entry=fill_price,
            sl=signal.sl,
            tp1=signal.tp1,
            tp2=signal.tp2,
            atr=signal.atr,
            side=signal.side,
        )

        self.pos_mgr.open_position(
            symbol=signal.symbol,
            side=side,
            entry=fill_price,
            qty=qty,
            sl=adjusted["sl"],
            tp1=adjusted["tp1"],
            tp2=adjusted["tp2"],
            atr=signal.atr,
            leverage=lev_decision.leverage,
            mode=lev_decision.mode,
            strategy=signal.strategy,
            confidence=signal.confidence,
            tp1_close_pct=adjusted["tp1_close_pct"],
            entry_reasons={"backtest": True, "strategy": signal.strategy},
            trade_profile=trade_prof,
        )

        self.signals_generated.append({
            "symbol": signal.symbol,
            "strategy": signal.strategy,
            "side": signal.side,
            "confidence": signal.confidence,
            "leverage": lev_decision.leverage,
            "entry": signal.entry,
            "sl": signal.sl,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
        })

    def _generate_report(self, symbols: List[str], days: int) -> Dict[str, Any]:
        """Generate comprehensive backtest report."""
        trade_summary = self.pos_mgr.get_trade_summary()

        # Equity curve stats
        if self.equity_curve:
            equities = [e["equity"] for e in self.equity_curve]
            peak = max(equities)
            drawdowns = [(peak - e) / peak for e in equities]
            max_drawdown = max(drawdowns) if drawdowns else 0
        else:
            max_drawdown = 0

        report = {
            "config": {
                "symbols": symbols,
                "days": days,
                "starting_equity": self.config.starting_equity,
                "risk_per_trade": self.config.risk_per_trade,
                "ensemble_mode": self.config.ensemble_mode,
                "leverage_enabled": self.config.enable_leverage,
                "trailing_stop_enabled": self.config.enable_trailing_stop,
            },
            "results": {
                "final_equity": self.risk_mgr.equity,
                "total_return_pct": (self.risk_mgr.equity - self.config.starting_equity) / self.config.starting_equity * 100,
                "max_drawdown_pct": max_drawdown * 100,
                "total_signals": len(self.signals_generated),
                **trade_summary,
            },
            "by_strategy": self._report_by_strategy(),
            "by_symbol": self._report_by_symbol(),
            "leverage_stats": self._report_leverage(),
            "equity_curve_length": len(self.equity_curve),
        }

        # Add LLM stats and detailed data if LLM integration was used
        if self.llm:
            llm_summary = self.llm.get_summary()
            report["llm_stats"] = llm_summary
            report["llm_agent_costs"] = llm_summary.get("agent_costs", {})
            report["llm_regime_timeline"] = llm_summary.get("regime_timeline", [])
            report["llm_veto_stats"] = llm_summary.get("veto_stats", {})
            report["llm_exit_decisions"] = self.llm.exit_decisions
            report["llm_learning_lessons"] = len(self.llm.learning_lessons)

        # Per-trade timeline (always available, enriched with LLM data when present)
        report["trade_timeline"] = self._report_trade_timeline()

        return report

    # Actions that represent trade closes (not OPEN events)
    _CLOSE_ACTIONS = ("SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT",
                      "EMERGENCY", "BACKTEST_END", "HOLD_LIMIT",
                      "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE")

    def _report_by_strategy(self) -> Dict:
        result = {}
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                strat = event.strategy or "unknown"
                if strat not in result:
                    result[strat] = {"trades": 0, "wins": 0, "pnl": 0.0}
                result[strat]["trades"] += 1
                if event.pnl > 0:
                    result[strat]["wins"] += 1
                result[strat]["pnl"] += event.pnl
        for strat, stats in result.items():
            stats["win_rate"] = stats["wins"] / stats["trades"] if stats["trades"] else 0
        return result

    def _report_by_symbol(self) -> Dict:
        result = {}
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                sym = event.symbol
                if sym not in result:
                    result[sym] = {"trades": 0, "wins": 0, "pnl": 0.0}
                result[sym]["trades"] += 1
                if event.pnl > 0:
                    result[sym]["wins"] += 1
                result[sym]["pnl"] += event.pnl
        for sym, stats in result.items():
            stats["win_rate"] = stats["wins"] / stats["trades"] if stats["trades"] else 0
        return result

    def _report_leverage(self) -> Dict:
        spot = {"trades": 0, "pnl": 0.0}
        leveraged = {"trades": 0, "pnl": 0.0, "avg_leverage": 0.0}
        levs = []
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                if event.leverage <= 1.0:
                    spot["trades"] += 1
                    spot["pnl"] += event.pnl
                else:
                    leveraged["trades"] += 1
                    leveraged["pnl"] += event.pnl
                    levs.append(event.leverage)
        if levs:
            leveraged["avg_leverage"] = sum(levs) / len(levs)
        return {"spot": spot, "leveraged": leveraged}


    def _report_trade_timeline(self) -> List[Dict[str, Any]]:
        """Build per-trade timeline with LLM decision context if available."""
        # Build LLM decision lookup by timestamp (approximate matching)
        llm_lookup = {}
        if self.llm:
            for dec in self.llm.decisions:
                # Key by action type for correlation
                ts = dec.get("timestamp", "")
                llm_lookup[ts] = dec

        timeline = []
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                entry = {
                    "symbol": event.symbol,
                    "side": getattr(event, "side", ""),
                    "strategy": event.strategy or "unknown",
                    "action": event.action,
                    "entry_price": getattr(event, "entry_price", 0),
                    "exit_price": event.price,
                    "pnl": round(event.pnl, 2),
                    "fee": round(getattr(event, "fee", 0), 2),
                    "leverage": getattr(event, "leverage", 1.0),
                }
                # Enrich with LLM context if available
                if self.llm and self.llm.decisions:
                    # Find the most recent decision for this symbol (match by symbol field)
                    for dec in reversed(self.llm.decisions):
                        dec_symbol = dec.get("symbol", "")
                        if dec_symbol == event.symbol:
                            entry["llm_action"] = dec.get("action", "")
                            entry["llm_regime"] = dec.get("regime", "")
                            entry["llm_confidence"] = dec.get("confidence", 0)
                            break
                timeline.append(entry)
        return timeline


def export_trade_csv(report: Dict, filepath: str):
    """Export per-trade timeline as CSV for spreadsheet analysis."""
    import csv

    timeline = report.get("trade_timeline", [])
    if not timeline:
        return

    fieldnames = ["symbol", "side", "strategy", "action", "entry_price",
                  "exit_price", "pnl", "fee", "leverage",
                  "llm_action", "llm_regime", "llm_confidence"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(timeline)


def print_report(report: Dict):
    """Pretty-print a backtest report."""
    r = report["results"]
    c = report["config"]

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Symbols:         {', '.join(c['symbols'])}")
    print(f"  Period:          {c['days']} days")
    print(f"  Starting Equity: ${c['starting_equity']:,.2f}")
    print(f"  Final Equity:    ${r['final_equity']:,.2f}")
    print(f"  Total Return:    {r['total_return_pct']:+.2f}%")
    print(f"  Max Drawdown:    {r['max_drawdown_pct']:.2f}%")
    print(f"  Total Signals:   {r['total_signals']}")
    print(f"  Total Trades:    {r.get('total_trades', 0)}")
    print(f"  Win Rate:        {r.get('win_rate', 0):.1%}")
    print(f"  Net PnL:         ${r.get('net_pnl', 0):,.2f}")

    if report.get("by_strategy"):
        print("\n  By Strategy:")
        for strat, stats in report["by_strategy"].items():
            print(f"    {strat}: {stats['trades']} trades, {stats['win_rate']:.0%} win rate, ${stats['pnl']:,.2f}")

    if report.get("by_symbol"):
        print("\n  By Symbol:")
        for sym, stats in report["by_symbol"].items():
            print(f"    {sym}: {stats['trades']} trades, {stats['win_rate']:.0%} win rate, ${stats['pnl']:,.2f}")

    lev = report.get("leverage_stats", {})
    if lev:
        print(f"\n  Leverage Stats:")
        print(f"    Spot trades:      {lev.get('spot', {}).get('trades', 0)} | PnL: ${lev.get('spot', {}).get('pnl', 0):,.2f}")
        print(f"    Leveraged trades: {lev.get('leveraged', {}).get('trades', 0)} | PnL: ${lev.get('leveraged', {}).get('pnl', 0):,.2f}")
        print(f"    Avg leverage:     {lev.get('leveraged', {}).get('avg_leverage', 0):.1f}x")

    llm_stats = report.get("llm_stats")
    if llm_stats:
        print(f"\n  LLM Agent Stats:")
        print(f"    Total cost:       ${llm_stats.get('total_cost_usd', 0):.4f}")
        print(f"    Budget:           ${llm_stats.get('budget_usd', 0):.2f} ({llm_stats.get('budget_used_pct', 0):.1f}% used)")
        print(f"    API calls:        {llm_stats.get('llm_calls', 0)}")
        print(f"    Failures:         {llm_stats.get('llm_failures', 0)}")
        print(f"    Candles w/ LLM:   {llm_stats.get('candles_with_llm', 0)}")
        print(f"    Candles fallback: {llm_stats.get('candles_fallback', 0)}")
        print(f"    Decisions logged: {llm_stats.get('decisions_logged', 0)}")
        if llm_stats.get("budget_exhausted"):
            print(f"    WARNING: Budget was exhausted during run")

        # Per-agent cost breakdown
        agent_costs = report.get("llm_agent_costs", {})
        if agent_costs:
            print(f"\n  Per-Agent Costs:")
            for agent, cost in sorted(agent_costs.items(), key=lambda x: -x[1]):
                print(f"    {agent:12s}  ${cost:.4f}")

        # Veto breakdown
        veto_stats = report.get("llm_veto_stats", {})
        if veto_stats and veto_stats.get("total_decisions", 0) > 0:
            print(f"\n  LLM Decision Breakdown:")
            print(f"    Approved:      {veto_stats['approved']}")
            print(f"    Vetoed:        {veto_stats['vetoed']} ({veto_stats['veto_rate']:.0%})")
            if veto_stats.get("critic_vetoes"):
                print(f"    Critic vetoes: {veto_stats['critic_vetoes']}")

        # Regime timeline
        regime_timeline = report.get("llm_regime_timeline", [])
        if regime_timeline:
            print(f"\n  Regime Timeline ({len(regime_timeline)} transitions):")
            for rt in regime_timeline[:15]:
                print(f"    {rt['timestamp'][:16]}  {rt['regime']}")
            if len(regime_timeline) > 15:
                print(f"    ... and {len(regime_timeline) - 15} more")

        # Learning stats
        lessons = report.get("llm_learning_lessons", 0)
        exits = len(report.get("llm_exit_decisions", []))
        if lessons or exits:
            print(f"\n  Learning Captured:")
            print(f"    Lessons processed:   {lessons}")
            print(f"    Exit evaluations:    {exits}")

    # Top trades by PnL
    timeline = report.get("trade_timeline", [])
    if timeline:
        sorted_trades = sorted(timeline, key=lambda t: t.get("pnl", 0))
        worst = sorted_trades[:3]
        best = sorted_trades[-3:][::-1]
        if best and best[0].get("pnl", 0) > 0:
            print(f"\n  Top Winning Trades:")
            for t in best:
                regime_str = f" [{t['llm_regime']}]" if t.get("llm_regime") else ""
                print(f"    {t['symbol']:6s} {t['strategy']:20s} ${t['pnl']:+8.2f}{regime_str}")
        if worst and worst[0].get("pnl", 0) < 0:
            print(f"\n  Worst Losing Trades:")
            for t in worst:
                regime_str = f" [{t['llm_regime']}]" if t.get("llm_regime") else ""
                print(f"    {t['symbol']:6s} {t['strategy']:20s} ${t['pnl']:+8.2f}{regime_str}")

    print("=" * 60)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--symbols", default="BTC,ETH,SOL", help="Comma-separated symbols")
    parser.add_argument("--days", type=int, default=30, help="Days of history")
    parser.add_argument("--strategies", default="", help="Comma-separated strategy names (empty=all)")
    parser.add_argument("--equity", type=float, default=10000, help="Starting equity")
    parser.add_argument("--output", default="", help="Save results to JSON file")
    parser.add_argument("--learn", action="store_true", help="Feed results into all learning systems")
    args = parser.parse_args()

    config = TradingConfig()
    config.starting_equity = args.equity

    engine = BacktestEngine(config)
    symbols = [s.strip() for s in args.symbols.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()] or None

    report = engine.run(symbols, args.days, strategies, learn=args.learn)
    print_report(report)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
