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
from trading_config import TradingConfig, DEFAULT_SYMBOLS, DEFAULT_SYMBOL_OVERRIDES, get_symbol_param
from strategies.base import Signal
from strategies.regime_trend import RegimeTrendStrategy
from strategies.monte_carlo_zones import MonteCarloZonesStrategy
from strategies.confidence_scorer import ConfidenceScorerStrategy
from strategies.multi_tier_quality import MultiTierQualityStrategy
from strategies.ensemble import EnsembleStrategy
from execution.position_manager import PositionManager
from execution.leverage import LeverageManager
from execution.risk import RiskManager, CircuitBreaker
from execution.candidate import TradeCandidate, CandidateLogger
from strategies.chop_detector import ChopDetector

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

    def __init__(self, config: Optional[TradingConfig] = None, llm_integration=None,
                 fresh: bool = False, relaxed_cb: bool = False):
        self.config = config or TradingConfig()
        self.llm = llm_integration  # Optional BacktestLLMIntegration
        self._relaxed_cb = relaxed_cb

        # Initialize components
        self.fetcher = DataFetcher(cache_ttl=3600, backtest_mode=True, fresh=fresh)
        self._backtest_days = None  # Set during run()
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

        # Circuit breaker settings: default to LIVE settings for realistic backtests.
        # Use --relaxed-cb (or env vars) to widen for analysis/learning mode.
        if self._relaxed_cb:
            self.risk_mgr.circuit_breaker.daily_loss_limit_pct = float(
                os.getenv("BACKTEST_CB_DAILY_LOSS_PCT", "0.15")
            )
            self.risk_mgr.circuit_breaker.max_drawdown_pct = float(
                os.getenv("BACKTEST_CB_MAX_DRAWDOWN_PCT", "0.30")
            )
            bt_consec = int(os.getenv("BACKTEST_CB_MAX_CONSEC", "0"))
            if bt_consec > 0:
                self.risk_mgr.circuit_breaker.max_consecutive_losses = bt_consec
            elif self.risk_mgr.circuit_breaker.max_consecutive_losses <= 3:
                self.risk_mgr.circuit_breaker.max_consecutive_losses = 6

        # Results
        self.equity_curve: List[Dict] = []
        self.signals_generated: List[Dict] = []
        self.cb_events: List[Dict] = []  # Circuit breaker trip log
        self.signals_blocked_by_cb = 0  # Signals skipped due to CB
        self.signal_rejections: List[Dict] = []  # Track why signals were rejected
        self.candle_stats = {"total": 0, "signal": 0, "no_signal": 0, "cb_blocked": 0}
        self.symbol_pnl: Dict[str, float] = {}  # Per-symbol equity attribution

        # Candidate tracking for counterfactual analysis
        self._candidate_logger = None
        self._active_candidates: Dict[str, 'TradeCandidate'] = {}  # symbol -> candidate

        # Per-symbol re-entry gap: skip 1 candle after a close to prevent
        # same-bar re-entry artifacts in backtest
        self._last_close_candle: Dict[str, int] = {}  # symbol -> candle index

        # Last prices per symbol for cross-symbol MTM equity calculation
        self._last_prices: Dict[str, float] = {}

        # Raw mode: disable all risk gates for pure strategy analysis
        self._raw_mode = False

    def enable_raw_mode(self):
        """Disable all risk gates for pure strategy analysis."""
        self._raw_mode = True
        cb = self.risk_mgr.circuit_breaker
        cb.daily_loss_limit_pct = 1.0
        cb.max_drawdown_pct = 1.0
        cb.max_consecutive_losses = 999999
        self.risk_mgr.max_open_positions = 50
        self.risk_mgr.max_portfolio_leverage = 100.0

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

        # Configure fetcher to pull enough data for the requested backtest period
        self._backtest_days = days
        self.fetcher.backtest_days = days

        # Initialize candidate logger for dual-world analysis
        # Clear stale data from previous runs so results aren't contaminated
        self._clear_stale_analysis_data()
        self._candidate_logger = CandidateLogger()
        self._active_candidates = {}

        # Build strategies
        sym_configs = {s: DEFAULT_SYMBOLS[s] for s in symbols if s in DEFAULT_SYMBOLS}
        active_strategies = self._build_strategies(sym_configs, strategies)

        # Build chop detector with per-symbol volatility profiles
        chop = ChopDetector(threshold=getattr(self.config, "chop_threshold", 0.55))
        for sym in symbols:
            sym_overrides = DEFAULT_SYMBOL_OVERRIDES.get(sym)
            if sym_overrides and hasattr(sym_overrides, "volatility_profile"):
                chop.set_symbol_profile(sym, sym_overrides.volatility_profile)

        ensemble = EnsembleStrategy(
            strategies=active_strategies,
            mode=self.config.ensemble_mode,
            min_votes=self.config.min_votes_required,
            veto_ratio=self.config.veto_ratio,
            chop_detector=chop,
            confidence_floor=self.config.ensemble_confidence_floor,
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

        # Log data coverage for transparency
        print(f"\n  Data Coverage (requested {days} days):")
        for symbol, data in all_data.items():
            for tf, df in sorted(data.items()):
                if df is not None and not df.empty:
                    first = df["time"].iloc[0] if "time" in df.columns else df.index[0]
                    last = df["time"].iloc[-1] if "time" in df.columns else df.index[-1]
                    actual_days = (last - first).total_seconds() / 86400
                    print(f"    {symbol:>6s} {tf:>5s}: {len(df):>5d} candles | {actual_days:.1f} days ({first.strftime('%Y-%m-%d')} to {last.strftime('%Y-%m-%d')})")
                else:
                    print(f"    {symbol:>6s} {tf:>5s}: NO DATA")
        print()

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

            # Reset per-symbol LLM budget so each symbol gets fair share
            if self.llm:
                self.llm.reset_for_symbol(symbol)

            # Reset CB trip state between symbols so each gets fair evaluation.
            # peak_equity intentionally persists (account-level metric).
            # daily_pnl resets naturally at day boundaries.
            if hasattr(self.risk_mgr, "circuit_breaker") and self.risk_mgr.circuit_breaker:
                cb = self.risk_mgr.circuit_breaker
                cb.consecutive_losses = 0
                cb.tripped = False
                cb.trip_time = None
                cb._trip_sim_time = None
                cb.trip_reason = ""
                cb._override_count = 0
                cb.post_cooldown_caution = 0

            data = all_data.get(symbol, {})
            df_1h = data.get("1h", pd.DataFrame())

            # Track equity before this symbol's walk for attribution
            equity_before = self.risk_mgr.equity

            if df_1h.empty:
                # Try daily data for zone strategies
                df_daily = data.get("daily", pd.DataFrame())
                if df_daily.empty:
                    logger.warning(f"No data for {symbol}, skipping")
                    continue
                self._walk_daily(symbol, data, ensemble)
            else:
                self._walk_hourly(symbol, data, ensemble)

            # Record per-symbol equity attribution
            self.symbol_pnl[symbol] = self.risk_mgr.equity - equity_before
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
        """Build strategy instances. Each toggleable via STRATEGY_*_ENABLED env var."""
        import os
        all_strats = {}

        if os.getenv("STRATEGY_REGIME_TREND_ENABLED", "true").lower() == "true":
            all_strats["regime_trend"] = RegimeTrendStrategy(sym_configs, self.config.htf_hours)
        if os.getenv("STRATEGY_CONFIDENCE_SCORER_ENABLED", "true").lower() == "true":
            all_strats["confidence_scorer"] = ConfidenceScorerStrategy(sym_configs, data_dir="backtest_ml_data")
        if os.getenv("STRATEGY_MULTI_TIER_QUALITY_ENABLED", "true").lower() == "true":
            all_strats["multi_tier_quality"] = MultiTierQualityStrategy(sym_configs)
        if os.getenv("STRATEGY_MONTE_CARLO_ENABLED", "false").lower() == "true":
            all_strats["monte_carlo_zones"] = MonteCarloZonesStrategy(sym_configs)

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
                # Only include data BEFORE current candle to avoid look-ahead bias.
                # Signal evaluates on completed candles, entry fills on current close.
                mask = df["time"] < current_time
                w = df[mask].copy()
                # Drop rows with NaN in critical OHLCV columns
                ohlcv_cols = [c for c in ("open", "high", "low", "close", "volume") if c in w.columns]
                if ohlcv_cols:
                    w = w.dropna(subset=ohlcv_cols)
                if not w.empty:
                    windowed[tf] = w

            if not windowed:
                continue

            current_price = float(df_1h["close"].iloc[i])
            candle_high = float(df_1h["high"].iloc[i])
            candle_low = float(df_1h["low"].iloc[i])

            # Parse simulation timestamp for circuit breaker time awareness
            sim_time = pd.Timestamp(df_1h["time"].iloc[i])
            if sim_time.tzinfo is None:
                sim_time = sim_time.tz_localize("UTC")
            sim_dt = sim_time.to_pydatetime()

            # Check existing positions with intra-candle SL/TP simulation.
            # Check worst-case price first (SL side), then best-case (TP side),
            # then settle on close. This prevents backtest from surviving wicks
            # that would stop out live positions.
            # Exit slippage: exits slip AGAINST the trade (SL fills worse, TP fills worse)
            exit_slip = getattr(self.config, "slippage_bps", 0) / 10000.0
            pos = self.pos_mgr.positions.get(symbol)
            events = []
            if pos and pos.state != "CLOSED":
                is_long = pos.side == "LONG"
                # 1. Worst case first: check if SL was breached during candle
                # Apply exit slippage: SL fills worse (lower for long, higher for short)
                worst_price = candle_low if is_long else candle_high
                worst_with_slip = worst_price * (1 - exit_slip) if is_long else worst_price * (1 + exit_slip)
                events = self.pos_mgr.update_price(symbol, worst_with_slip)
                if not events:
                    # 2. Best case: check if TP was hit during candle
                    # TP exits are limit orders — fill at target price or better, no adverse slippage
                    best_price = candle_high if is_long else candle_low
                    events = self.pos_mgr.update_price(symbol, best_price)
                if not events:
                    # 3. Settle on close price for trailing stop updates etc
                    events = self.pos_mgr.update_price(symbol, current_price)
            else:
                events = self.pos_mgr.update_price(symbol, current_price)
            for event in events:
                # Tag close events with simulated time for hold duration calculation
                if event.action in self._CLOSE_ACTIONS:
                    event.metadata["close_sim_time"] = str(sim_dt)
                self.risk_mgr.update_equity(event.pnl - event.fee, sim_time=sim_dt)
                if event.action in self._CLOSE_ACTIONS:
                    self._record_trade_outcome(event, current_price)
                    self._last_close_candle[symbol] = i  # Track for re-entry gap
                # LLM: run Learning Agent on closed trades
                if self.llm and event.action in self._CLOSE_ACTIONS:
                    self.llm.clear_exit_counter(event.symbol)
                    self._run_llm_learning(event, current_price)

            # Accrue funding costs for open positions (1h per candle step)
            avg_funding_rate = getattr(self.config, "backtest_funding_rate", 0.0001)  # 0.01% per 8h
            _pos = self.pos_mgr.positions.get(symbol)
            if _pos and _pos.state != "CLOSED" and _pos.qty > 0:
                notional = _pos.entry * _pos.qty * _pos.leverage
                # 1 hour out of 8h funding interval = 1/8 fraction
                cost = abs(avg_funding_rate) * notional * (1.0 / 8.0)
                _pos.funding_costs += cost

            # Circuit breaker force-close: only close OPEN positions (still
            # exposed to initial risk). TRAILING/TP1_HIT positions already hit
            # profit targets and are protected by trailing stops — cutting
            # these kills winners. Let trailing stops do their job.
            if self.risk_mgr.circuit_breaker.tripped:
                pos = self.pos_mgr.positions.get(symbol)
                if pos and pos.state == "OPEN":
                    logger.warning(
                        f"[{symbol}] CB tripped — force-closing OPEN position"
                    )
                    cb_event = self.pos_mgr.force_close(
                        symbol, current_price, reason="CIRCUIT_BREAKER"
                    )
                    if cb_event:
                        self.risk_mgr.update_equity(
                            cb_event.pnl - cb_event.fee, sim_time=sim_dt
                        )
                        self._record_trade_outcome(cb_event, current_price)
                        self._last_close_candle[symbol] = i
                        if self.llm and cb_event.action in self._CLOSE_ACTIONS:
                            self.llm.clear_exit_counter(cb_event.symbol)
                            self._run_llm_learning(cb_event, current_price)
                        self.cb_events.append({
                            "time": str(df_1h["time"].iloc[i]),
                            "symbol": symbol,
                            "action": "force_close",
                            "reason": self.risk_mgr.circuit_breaker.trip_reason,
                            "equity": self.risk_mgr.equity,
                            "pnl": cb_event.pnl,
                        })

            # LLM: run Exit Agent on open positions
            if self.llm:
                self._run_llm_exit(symbol, current_price, windowed, sim_dt)

            # Volatility-aware re-entry gap: fast movers need shorter cooldowns
            from trading_config import DEFAULT_SYMBOL_OVERRIDES
            _vol_profile = getattr(DEFAULT_SYMBOL_OVERRIDES.get(symbol), "volatility_profile", "medium") if DEFAULT_SYMBOL_OVERRIDES.get(symbol) else "medium"
            _RE_ENTRY_GAPS = {"low": 4, "medium": 2, "high": 1}
            re_entry_gap = _RE_ENTRY_GAPS.get(_vol_profile, 3)
            last_close_idx = self._last_close_candle.get(symbol, -2)
            if i <= last_close_idx + re_entry_gap:
                continue  # Let the market breathe after a close

            # Try to generate signal — track CB blocks
            self.candle_stats["total"] += 1
            cb_blocked = not self.risk_mgr.can_open_position(self.pos_mgr.get_open_count(), sim_time=sim_dt)
            if not cb_blocked:
                signal = ensemble.evaluate(symbol, windowed)
                if signal and not signal.is_valid:
                    logger.debug(f"[{symbol}] Invalid signal rejected by is_valid")
                    signal = None
                if signal:
                    self.candle_stats["signal"] += 1
                    # Tag regime at signal time for regime-aware reporting
                    try:
                        statuses = ensemble.get_all_status(symbol, windowed)
                        adx_val = 25.0  # default neutral
                        for s in statuses:
                            if s.get("strategy") == "regime_trend":
                                al = s.get("align_long", 0)
                                ash = s.get("align_short", 0)
                                adx_val = s.get("adx", 25.0)
                                if al >= 3:
                                    signal.metadata["regime"] = "trending_bull"
                                elif ash >= 3:
                                    signal.metadata["regime"] = "trending_bear"
                                elif al >= 2 or ash >= 2:
                                    signal.metadata["regime"] = "mixed"
                                else:
                                    signal.metadata["regime"] = "ranging"
                                break
                        signal.metadata["adx"] = round(adx_val, 1)
                    except Exception:
                        signal.metadata.setdefault("regime", "unknown")
                        adx_val = 25.0

                    # ADX-based override: if ADX < 20, force ranging regardless of alignment
                    # This catches cases where alignment says "mixed" but market has no trend
                    if adx_val < 20.0 and signal.metadata.get("regime") not in ("trending_bull", "trending_bear"):
                        signal.metadata["regime"] = "ranging"

                    # Also check trade_profile regime (uses trend_adjustment from ensemble)
                    # This catches signals where align >= 2 but no actual trend alignment
                    trend_adj = signal.metadata.get("trend_adjustment", 0)
                    if trend_adj >= 0 and signal.metadata.get("regime") not in ("trending_bull", "trending_bear"):
                        # No trend alignment bonus → trade_profile would classify as ranging
                        # Override "mixed" to "ranging" since trend_adjustment confirms no trend
                        signal.metadata["regime"] = "ranging"

                    # Regime filter: skip trades in ranging markets (24% WR historically)
                    regime = signal.metadata.get("regime", "unknown")
                    if regime in ("ranging", "unknown"):
                        logger.info(
                            f"[{symbol}] Signal SKIPPED: {regime} regime "
                            f"(ADX={adx_val:.1f}, no directional alignment)"
                        )
                        self.candle_stats.setdefault("regime_blocked", 0)
                        self.candle_stats["regime_blocked"] += 1
                        continue

                    # Create candidate for dual-world tracking
                    candidate = self._create_candidate(signal, sim_dt)

                    # LLM: evaluate signal through multi-agent pipeline
                    signal = self._apply_llm_entry(
                        signal, symbol, windowed, current_price, sim_dt
                    )
                    if signal:
                        # Update candidate with LLM decision
                        candidate.llm_action = signal.metadata.get("llm_status", "approved")
                        candidate.llm_confidence = signal.confidence
                        candidate.llm_notes = signal.metadata.get("llm_notes")
                        self._active_candidates[symbol] = candidate
                        signal.metadata["sim_time"] = str(sim_dt)
                        self._execute_signal(signal, current_price)
                    else:
                        # LLM vetoed — log candidate with flat action
                        candidate.llm_action = "flat"
                        self._candidate_logger.log_candidate(candidate)
                else:
                    self.candle_stats["no_signal"] += 1
            else:
                self.candle_stats["cb_blocked"] += 1
                self.signals_blocked_by_cb += 1

            # Record equity with mark-to-market (unrealized PnL included)
            unrealized_pnl = 0.0
            for _sym, _pos in self.pos_mgr.get_open_positions().items():
                # For current symbol use current_price; for others use last known
                _price = current_price if _sym == symbol else self._last_prices.get(_sym, _pos.entry)
                if _pos.side == "LONG":
                    unrealized_pnl += (_price - _pos.entry) * _pos.qty
                else:
                    unrealized_pnl += (_pos.entry - _price) * _pos.qty
            mtm_equity = self.risk_mgr.equity + unrealized_pnl
            # Check CB using MTM equity — catches open-position drawdowns
            sim_time = df_1h["time"].iloc[i] if hasattr(df_1h["time"].iloc[i], "strftime") else None
            self.risk_mgr.check_unrealized_risk(unrealized_pnl, sim_time=sim_time)
            peak_eq = self.risk_mgr.circuit_breaker.peak_equity
            self.equity_curve.append({
                "time": str(df_1h["time"].iloc[i]),
                "equity": self.risk_mgr.equity,
                "mtm_equity": mtm_equity,
                "unrealized_pnl": round(unrealized_pnl, 2),
                "open_positions": self.pos_mgr.get_open_count(),
                "cb_active": self.risk_mgr.circuit_breaker.tripped,
                "drawdown_pct": round(
                    (peak_eq - mtm_equity) / peak_eq * 100, 1
                ) if peak_eq > 0 else 0,
            })
            # Track last price per symbol for cross-symbol MTM
            self._last_prices[symbol] = current_price

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
                # Exclude current candle from signal evaluation (look-ahead prevention)
                mask = df_tf["time"] < current_time
                windowed[tf] = df_tf[mask].copy()

            current_price = float(df["close"].iloc[i])
            candle_high = float(df["high"].iloc[i]) if "high" in df.columns else current_price
            candle_low = float(df["low"].iloc[i]) if "low" in df.columns else current_price

            # Parse simulation timestamp for circuit breaker time awareness
            sim_time = pd.Timestamp(df["time"].iloc[i])
            if sim_time.tzinfo is None:
                sim_time = sim_time.tz_localize("UTC")
            sim_dt = sim_time.to_pydatetime()

            # Intra-candle SL/TP: worst case → best case → close (with exit slippage)
            exit_slip = getattr(self.config, "slippage_bps", 0) / 10000.0
            pos = self.pos_mgr.positions.get(symbol)
            events = []
            if pos and pos.state != "CLOSED":
                is_long = pos.side == "LONG"
                worst_price = candle_low if is_long else candle_high
                worst_with_slip = worst_price * (1 - exit_slip) if is_long else worst_price * (1 + exit_slip)
                events = self.pos_mgr.update_price(symbol, worst_with_slip)
                if not events:
                    # TP exits are limit orders — no adverse slippage
                    best_price = candle_high if is_long else candle_low
                    events = self.pos_mgr.update_price(symbol, best_price)
                if not events:
                    events = self.pos_mgr.update_price(symbol, current_price)
            else:
                events = self.pos_mgr.update_price(symbol, current_price)
            for event in events:
                if event.action in self._CLOSE_ACTIONS:
                    event.metadata["close_sim_time"] = str(sim_dt)
                self.risk_mgr.update_equity(event.pnl - event.fee, sim_time=sim_dt)
                if event.action in self._CLOSE_ACTIONS:
                    self._record_trade_outcome(event, current_price)
                    self._last_close_candle[symbol] = i
                if self.llm and event.action in self._CLOSE_ACTIONS:
                    self.llm.clear_exit_counter(event.symbol)
                    self._run_llm_learning(event, current_price)

            # Circuit breaker force-close (same as _walk_hourly — OPEN only)
            if self.risk_mgr.circuit_breaker.tripped:
                pos = self.pos_mgr.positions.get(symbol)
                if pos and pos.state == "OPEN":
                    logger.warning(
                        f"[{symbol}] CB tripped — force-closing OPEN position"
                    )
                    cb_event = self.pos_mgr.force_close(
                        symbol, current_price, reason="CIRCUIT_BREAKER"
                    )
                    if cb_event:
                        self.risk_mgr.update_equity(
                            cb_event.pnl - cb_event.fee, sim_time=sim_dt
                        )
                        self._record_trade_outcome(cb_event, current_price)
                        self._last_close_candle[symbol] = i
                        if self.llm and cb_event.action in self._CLOSE_ACTIONS:
                            self.llm.clear_exit_counter(cb_event.symbol)
                            self._run_llm_learning(cb_event, current_price)

            if self.llm:
                self._run_llm_exit(symbol, current_price, windowed, sim_dt)

            # Volatility-aware re-entry gap (same logic as main loop)
            from trading_config import DEFAULT_SYMBOL_OVERRIDES
            _vol_profile = getattr(DEFAULT_SYMBOL_OVERRIDES.get(symbol), "volatility_profile", "medium") if DEFAULT_SYMBOL_OVERRIDES.get(symbol) else "medium"
            _RE_ENTRY_GAPS = {"low": 4, "medium": 2, "high": 1}
            re_entry_gap = _RE_ENTRY_GAPS.get(_vol_profile, 3)
            last_close_idx = self._last_close_candle.get(symbol, -2)
            if i <= last_close_idx + re_entry_gap:
                continue

            self.candle_stats["total"] += 1
            cb_blocked = not self.risk_mgr.can_open_position(self.pos_mgr.get_open_count(), sim_time=sim_dt)
            if not cb_blocked:
                signal = ensemble.evaluate(symbol, windowed)
                if signal and not signal.is_valid:
                    logger.debug(f"[{symbol}] Invalid signal rejected by is_valid (daily)")
                    signal = None
                if signal:
                    self.candle_stats["signal"] += 1
                    # Tag regime at signal time (same logic as _walk_hourly)
                    try:
                        statuses = ensemble.get_all_status(symbol, windowed)
                        adx_val = 25.0
                        for s in statuses:
                            if s.get("strategy") == "regime_trend":
                                al = s.get("align_long", 0)
                                ash = s.get("align_short", 0)
                                adx_val = s.get("adx", 25.0)
                                if al >= 3:
                                    signal.metadata["regime"] = "trending_bull"
                                elif ash >= 3:
                                    signal.metadata["regime"] = "trending_bear"
                                elif al >= 2 or ash >= 2:
                                    signal.metadata["regime"] = "mixed"
                                else:
                                    signal.metadata["regime"] = "ranging"
                                break
                        signal.metadata["adx"] = round(adx_val, 1)
                    except Exception:
                        signal.metadata.setdefault("regime", "unknown")
                        adx_val = 25.0

                    # ADX-based override: if ADX < 20, force ranging
                    if adx_val < 20.0 and signal.metadata.get("regime") not in ("trending_bull", "trending_bear"):
                        signal.metadata["regime"] = "ranging"

                    # Cross-check with trend_adjustment (same as _walk_hourly)
                    trend_adj = signal.metadata.get("trend_adjustment", 0)
                    if trend_adj >= 0 and signal.metadata.get("regime") not in ("trending_bull", "trending_bear"):
                        signal.metadata["regime"] = "ranging"

                    # Regime filter: skip ranging and unknown trades
                    regime = signal.metadata.get("regime", "unknown")
                    if regime in ("ranging", "unknown"):
                        logger.info(f"[{symbol}] Signal SKIPPED (daily): {regime} regime")
                        self.candle_stats.setdefault("regime_blocked", 0)
                        self.candle_stats["regime_blocked"] += 1
                        continue

                    # Create candidate for dual-world tracking
                    candidate = self._create_candidate(signal, sim_dt)

                    signal = self._apply_llm_entry(
                        signal, symbol, windowed, current_price, sim_dt
                    )
                    if signal:
                        candidate.llm_action = signal.metadata.get("llm_status", "approved")
                        candidate.llm_confidence = signal.confidence
                        candidate.llm_notes = signal.metadata.get("llm_notes")
                        self._active_candidates[symbol] = candidate
                        signal.metadata["sim_time"] = str(sim_dt)
                        self._execute_signal(signal, current_price)
                    else:
                        candidate.llm_action = "flat"
                        self._candidate_logger.log_candidate(candidate)
                else:
                    self.candle_stats["no_signal"] += 1
            else:
                self.candle_stats["cb_blocked"] += 1
                self.signals_blocked_by_cb += 1

            # MTM equity for daily walk (matches hourly walk behavior)
            _unrealized_pnl = 0.0
            for _sym, _pos in self.pos_mgr.get_open_positions().items():
                _price = current_price if _sym == symbol else self._last_prices.get(_sym, _pos.entry)
                if _pos.side == "LONG":
                    _unrealized_pnl += (_price - _pos.entry) * _pos.qty
                else:
                    _unrealized_pnl += (_pos.entry - _price) * _pos.qty
            _mtm_equity = self.risk_mgr.equity + _unrealized_pnl
            _sim_time = df["time"].iloc[i] if hasattr(df["time"].iloc[i], "strftime") else None
            self.risk_mgr.check_unrealized_risk(_unrealized_pnl, sim_time=_sim_time)
            _peak_eq = self.risk_mgr.circuit_breaker.peak_equity
            self.equity_curve.append({
                "time": str(df["time"].iloc[i]),
                "equity": self.risk_mgr.equity,
                "mtm_equity": _mtm_equity,
                "unrealized_pnl": round(_unrealized_pnl, 2),
                "open_positions": self.pos_mgr.get_open_count(),
                "cb_active": self.risk_mgr.circuit_breaker.tripped,
                "drawdown_pct": round(
                    (_peak_eq - _mtm_equity) / _peak_eq * 100, 1
                ) if _peak_eq > 0 else 0,
            })

            if self.llm:
                if i % 10 == 0:
                    self.llm.save_checkpoint(i, symbol, [], self.risk_mgr.equity)
                if i % 50 == 0:
                    print(self.llm.get_progress_line(i - warmup, total_candles - warmup))

        # Force-close any open position at end of symbol walk
        self._force_close_open(symbol, current_price, sim_dt)

    # ── Candidate Tracking ──────────────────────────────────────────

    def _create_candidate(self, signal: Signal, sim_dt: datetime) -> TradeCandidate:
        """Create a TradeCandidate from an ensemble signal for dual-world logging."""
        import time as _time
        return TradeCandidate(
            symbol=signal.symbol,
            side="LONG" if signal.side == "BUY" else "SHORT",
            entry=signal.entry,
            sl=signal.sl,
            tp1=signal.tp1,
            tp2=signal.tp2,
            atr=signal.atr,
            ensemble_confidence=signal.confidence,
            ensemble_strategy=signal.strategy,
            entry_type=signal.metadata.get("entry_type", "MEDIUM"),
            primary_driver=signal.strategy,
            regime=signal.metadata.get("regime", "unknown"),
            timestamp=sim_dt.timestamp(),
            num_agree=signal.metadata.get("num_agree", 1),
            strategies_agree=signal.metadata.get("strategies_agree", []),
        )

    def _update_candidate_on_close(self, event):
        """Update the active candidate with realized PnL when a position closes."""
        candidate = self._active_candidates.pop(event.symbol, None)
        if not candidate:
            return

        pos = self.pos_mgr.positions.get(event.symbol)
        pnl = pos.realized_pnl if pos else event.pnl

        candidate.realized_pnl = pnl
        candidate.leverage_used = event.leverage
        candidate.close_reason = event.action

        if pnl > 0:
            candidate.outcome = "WIN"
        elif pnl < -0.01:
            candidate.outcome = "LOSS"
        else:
            candidate.outcome = "BREAK_EVEN"

        # Calculate realized R-multiple
        stop_width = abs(candidate.entry - candidate.sl)
        qty = pos.qty if pos and pos.qty else 1
        denom = stop_width * qty
        if denom > 0:
            candidate.realized_r = pnl / denom

        # Hold time
        if pos and hasattr(pos, "open_time") and pos.open_time:
            import time as _time
            close_time = _time.time()
            if hasattr(event, "timestamp") and event.timestamp:
                close_time = event.timestamp
            candidate.hold_time_s = close_time - candidate.timestamp

        self._candidate_logger.log_candidate(candidate)

    # ── LLM Integration Helpers ────────────────────────────────────

    def _apply_llm_entry(self, signal, symbol, windowed, current_price, sim_dt):
        """Run LLM multi-agent pipeline on a signal. Returns signal or None (vetoed)."""
        if not self.llm:
            signal.metadata["llm_status"] = "no_llm"
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
            signal.metadata["llm_status"] = "fallback"
            return signal  # No LLM opinion -> use strategy signal as-is

        # Apply LLM decision
        if decision.action == "flat":
            logger.debug(f"[{symbol}] LLM vetoed signal: {decision.notes[:80] if decision.notes else ''}")
            return None  # Vetoed

        # Apply size multiplier to confidence (influences position sizing)
        if decision.size_multiplier != 1.0:
            signal.confidence = max(1.0, min(100.0, signal.confidence * decision.size_multiplier))

        signal.metadata["llm_status"] = "approved"

        # Store LLM thesis and notes on signal metadata so they propagate
        # to the Position object. Exit Agent needs thesis for continuity checks.
        if decision.notes:
            signal.metadata["llm_notes"] = decision.notes[:300]
        if hasattr(decision, "thesis") and decision.thesis:
            signal.metadata["llm_thesis"] = decision.thesis[:200]
        elif decision.notes:
            # Extract thesis from notes if available
            signal.metadata["llm_thesis"] = decision.notes[:200]

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
                (current_price - pos.entry) * pos.qty * pos.leverage
                if pos.side == "LONG"
                else (pos.entry - current_price) * pos.qty * pos.leverage
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

    def _record_trade_outcome(self, event, current_price: float):
        """Record a closed trade to data/analysis for performance tracking.

        This ensures backtest trades populate performance.json and
        trade_outcomes.csv just like live trades do, enabling the
        analyze_backtest.py script to show real PnL per trade.
        """
        if event.action not in self._CLOSE_ACTIONS:
            return

        try:
            from data.learning import record_trade_outcome

            pos = self.pos_mgr.positions.get(event.symbol)
            meta = event.metadata or {}

            # Determine outcome
            pnl = pos.realized_pnl if pos else event.pnl
            if pnl > 0:
                outcome = "WIN"
            elif pnl < -0.01:
                outcome = "LOSS"
            else:
                outcome = "BREAKEVEN"

            record_trade_outcome(
                symbol=event.symbol,
                side=event.side,
                outcome=outcome,
                pnl=pnl,
                entry=pos.entry if pos else 0,
                sl=pos.original_sl if pos and hasattr(pos, "original_sl") else (pos.sl if pos else 0),
                tp1=pos.tp1 if pos else 0,
                tp2=pos.tp2 if pos else 0,
                tp1_hit=pos.state in ("TP1_HIT", "TRAILING") if pos else False,
                sl_after_tp1=(event.action == "SL" and pos.state == "TP1_HIT") if pos else False,
                state_path=pos.state_path_str if pos and hasattr(pos, "state_path_str") else event.action,
                leverage=event.leverage,
                confidence=pos.confidence if pos else 0,
                strategy=event.strategy or "",
                entry_reasons=meta.get("entry_reasons", {}),
                entry_type=meta.get("entry_type", ""),
                primary_driver=event.strategy or "",
                regime=meta.get("regime", ""),
            )

            # Also update self-teaching system's trade counter
            try:
                from llm.learning_mode import record_trade_observed
                record_trade_observed(
                    symbol=event.symbol,
                    side=event.side,
                    outcome=outcome,
                    pnl=pnl,
                    confidence=pos.confidence if pos else 0,
                )
            except Exception:
                pass  # Self-teaching is optional

            # Validate insights against this trade outcome
            try:
                from llm.learning_integrator import get_integrator
                integrator = get_integrator()
                integrator.validate_insights_from_trade({
                    "symbol": event.symbol,
                    "side": event.side,
                    "outcome": outcome,
                    "pnl": pnl,
                    "strategy": event.strategy or "",
                    "regime": meta.get("regime", ""),
                })
            except Exception:
                pass  # Insight validation is optional

            # Update trade candidate with realized PnL for counterfactual analysis
            self._update_candidate_on_close(event)
        except Exception as e:
            logger.debug(f"[BACKTEST] Failed to record trade outcome: {e}")

    def _force_close_open(self, symbol: str, last_price: float, sim_dt: datetime):
        """Force-close any open position at the end of a symbol's walk."""
        pos = self.pos_mgr.positions.get(symbol)
        if pos and pos.state != "CLOSED":
            event = self.pos_mgr.force_close(symbol, last_price, reason="BACKTEST_END")
            if event:
                self.risk_mgr.update_equity(event.pnl - event.fee, sim_time=sim_dt)
                self._record_trade_outcome(event, last_price)
                logger.info(f"[{symbol}] Force-closed at backtest end: PnL={event.pnl:.2f}")

    def _execute_signal(self, signal: Signal, current_price: float):
        """Execute a signal in backtest mode with slippage simulation."""
        from execution.trade_profile import classify_trade, apply_profile_to_signal
        from core.signal_pipeline import RiskFilterChain

        # Apply slippage: shift entry by slippage bps, then shift SL/TP by
        # the same ABSOLUTE amount (not multiplicative — preserves R:R ratios).
        slippage_bps = getattr(self.config, "slippage_bps", 0)
        slip_mult = slippage_bps / 10000.0
        if signal.side == "BUY":
            slip_amount = signal.entry * slip_mult
            fill_price = signal.entry + slip_amount      # Buy higher (worse)
            signal.sl = signal.sl + slip_amount           # SL shifts by same $ amount
            signal.tp1 = signal.tp1 + slip_amount         # TP1 shifts
            signal.tp2 = signal.tp2 + slip_amount         # TP2 shifts
        else:
            slip_amount = signal.entry * slip_mult
            fill_price = signal.entry - slip_amount      # Sell lower (worse)
            signal.sl = signal.sl - slip_amount           # SL shifts
            signal.tp1 = signal.tp1 - slip_amount         # TP1 shifts
            signal.tp2 = signal.tp2 - slip_amount         # TP2 shifts

        signal.entry = fill_price  # Update entry for downstream consumers

        # Extract agreement metadata
        num_agree = signal.metadata.get("num_agree", 1)
        total = signal.metadata.get("total_strategies", 4)

        sym_cfg = DEFAULT_SYMBOLS.get(signal.symbol)
        risk_tier = sym_cfg.risk_tier if sym_cfg else "medium"

        extreme_count = sum(
            1 for p in self.pos_mgr.get_open_positions().values()
            if p.leverage > 5.0
        )

        # Raw mode: bypass RiskFilterChain for pure strategy analysis
        if self._raw_mode:
            lev_decision = self.leverage_mgr.decide(
                signal.confidence, num_agree, total, risk_tier, extreme_count
            )
            if lev_decision.leverage <= 0:
                return
            qty = self.risk_mgr.calculate_qty(
                fill_price, signal.sl, lev_decision.leverage,
                lev_decision.risk_multiplier,
                slippage_bps=slippage_bps,
                skip_notional_cap=True,
                symbol=signal.symbol,
            )
            if qty <= 0:
                return
            leverage = lev_decision.leverage
            risk_mult = lev_decision.risk_multiplier
        else:
            # Run through the full RiskFilterChain — same pipeline as live trading.
            # Includes: R:R check, EV filter, circuit breaker, max positions,
            # correlation guard, leverage decision, liquidation safety, position sizing.
            chain = RiskFilterChain(self.risk_mgr, self.leverage_mgr, self.config)
            result = chain.evaluate(
                signal=signal,
                equity=self.risk_mgr.equity,
                num_strategies_agree=num_agree,
                total_strategies=total,
                current_open_count=self.pos_mgr.get_open_count(),
                current_extreme_count=extreme_count,
                risk_tier=risk_tier,
                open_positions=self.pos_mgr.get_open_positions(),
            )

            if not result.approved:
                self.signal_rejections.append({
                    "symbol": signal.symbol, "strategy": signal.strategy,
                    "confidence": signal.confidence, "side": signal.side,
                    "gate": "risk_filter_chain",
                    "reason": result.rejection_reason,
                })
                return

            leverage = result.leverage
            risk_mult = result.risk_multiplier
            qty = result.position_qty

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

        # Extract LLM thesis/notes from signal metadata (stored by _apply_llm_entry)
        llm_notes = signal.metadata.get("llm_notes", "")
        llm_thesis = signal.metadata.get("llm_thesis", "")
        position_notes = llm_thesis or llm_notes

        self.pos_mgr.open_position(
            symbol=signal.symbol,
            side=side,
            entry=fill_price,
            qty=qty,
            sl=adjusted["sl"],
            tp1=adjusted["tp1"],
            tp2=adjusted["tp2"],
            atr=signal.atr,
            leverage=leverage,
            mode="leverage",
            strategy=signal.strategy,
            confidence=signal.confidence,
            tp1_close_pct=adjusted["tp1_close_pct"],
            entry_reasons={
                "backtest": True,
                "strategy": signal.strategy,
                "num_agree": signal.metadata.get("num_agree", 1),
                "strategies_agree": signal.metadata.get("strategies_agree", [signal.strategy]),
                "sim_time": signal.metadata.get("sim_time", ""),
                "regime": signal.metadata.get("regime", "unknown"),
            },
            trade_profile=trade_prof,
            notes=position_notes,
        )

        llm_tag = signal.metadata.get("llm_status", "unknown")
        logger.info(
            f"[{signal.symbol}] TRADE {signal.side} "
            f"conf={signal.confidence:.0f}% lev={leverage:.1f}x "
            f"({llm_tag})"
        )

        self.signals_generated.append({
            "symbol": signal.symbol,
            "strategy": signal.strategy,
            "side": signal.side,
            "confidence": signal.confidence,
            "leverage": leverage,
            "entry": signal.entry,
            "sl": signal.sl,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "llm_status": llm_tag,
            "regime": signal.metadata.get("regime", "unknown"),
        })

    def _clear_stale_analysis_data(self):
        """Remove stale data files from previous runs to prevent contamination."""
        stale_files = [
            os.path.join("data", "analysis", "trade_candidates.csv"),
            os.path.join("data", "analysis", "performance.json"),
            os.path.join("data", "logs", "safety_events.csv"),
        ]
        for f in stale_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                    logger.debug(f"Cleared stale file: {f}")
                except OSError:
                    pass

    def _generate_report(self, symbols: List[str], days: int) -> Dict[str, Any]:
        """Generate comprehensive backtest report."""
        trade_summary = self.pos_mgr.get_trade_summary()

        # Equity curve stats — use MTM equity (includes unrealized PnL) for accurate drawdown
        if self.equity_curve:
            equities = [e.get("mtm_equity", e["equity"]) for e in self.equity_curve]
            running_peak = equities[0]
            max_drawdown = 0
            max_dd_duration = 0
            dd_start = 0
            for idx, e in enumerate(equities):
                running_peak = max(running_peak, e)
                if running_peak > 0:
                    dd = (running_peak - e) / running_peak
                    max_drawdown = max(max_drawdown, dd)
                    if dd > 0 and dd_start == 0:
                        dd_start = idx
                    elif dd == 0:
                        if dd_start > 0:
                            max_dd_duration = max(max_dd_duration, idx - dd_start)
                        dd_start = 0
            if dd_start > 0:
                max_dd_duration = max(max_dd_duration, len(equities) - dd_start)
        else:
            max_drawdown = 0
            max_dd_duration = 0

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
            "circuit_breaker_stats": self._report_circuit_breaker(),
            "by_agreement": self._report_by_agreement(),
            "strategy_health": self._report_strategy_health(),
            "exit_types": self._report_exit_types(),
            "signal_funnel": self._report_signal_funnel(),
            "positions": self._report_positions(),
            "costs": self._report_costs(),
            "confidence_analysis": self._report_confidence_analysis(),
            "risk_metrics": self._report_risk_metrics(max_drawdown, max_dd_duration),
            "trailing_analysis": self._report_trailing_analysis(),
            "by_regime": self._report_by_regime(),
            "conf_regime_crosstab": self._report_confidence_regime_crosstab(),
            "symbol_pnl": self.symbol_pnl,
            "recommendations": self._generate_recommendations(),
            "equity_curve": self.equity_curve,
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

        # Feed findings into pattern cache for LLM knowledge pipeline
        try:
            from llm.pattern_cache import get_pattern_cache
            pc = get_pattern_cache()
            # Build symbol×side×regime cross-tab from trade log
            cross_tab: Dict[str, Dict] = {}
            for event in self.pos_mgr.trade_log:
                if event.action in self._CLOSE_ACTIONS:
                    sym = event.symbol or "?"
                    side = (event.metadata or {}).get("side", "BUY")
                    regime = (event.metadata or {}).get("regime", "unknown")
                    key = f"{sym}_{side}_{regime}"
                    if key not in cross_tab:
                        cross_tab[key] = {"wr": 0, "trades": 0, "pnl": 0.0,
                                          "avg_winner": 0.0, "avg_loser": 0.0,
                                          "_wins": 0, "_win_sum": 0.0, "_loss_sum": 0.0,
                                          "_losses": 0}
                    ct = cross_tab[key]
                    ct["trades"] += 1
                    ct["pnl"] += event.pnl
                    if event.pnl > 0:
                        ct["_wins"] += 1
                        ct["_win_sum"] += event.pnl
                    else:
                        ct["_losses"] += 1
                        ct["_loss_sum"] += event.pnl
            for key, ct in cross_tab.items():
                ct["wr"] = ct["_wins"] / ct["trades"] if ct["trades"] > 0 else 0
                ct["avg_winner"] = ct["_win_sum"] / ct["_wins"] if ct["_wins"] > 0 else 0
                ct["avg_loser"] = ct["_loss_sum"] / ct["_losses"] if ct["_losses"] > 0 else 0
                # Clean up internal fields
                for k in ("_wins", "_win_sum", "_losses", "_loss_sum"):
                    del ct[k]
            pc.ingest_backtest_report({"by_symbol_regime_side": cross_tab})
        except Exception as e:
            import logging
            logging.getLogger("bot.backtest").debug(f"Pattern cache ingestion failed: {e}")

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
        sym_winners = {}
        sym_losers = {}
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                sym = event.symbol
                if sym not in result:
                    result[sym] = {"trades": 0, "wins": 0, "pnl": 0.0}
                    sym_winners[sym] = []
                    sym_losers[sym] = []
                result[sym]["trades"] += 1
                if event.pnl > 0:
                    result[sym]["wins"] += 1
                    sym_winners[sym].append(event.pnl)
                else:
                    sym_losers[sym].append(event.pnl)
                result[sym]["pnl"] += event.pnl
        for sym, stats in result.items():
            stats["win_rate"] = stats["wins"] / stats["trades"] if stats["trades"] else 0
            w = sym_winners.get(sym, [])
            l = sym_losers.get(sym, [])
            stats["avg_winner"] = sum(w) / len(w) if w else 0.0
            stats["avg_loser"] = sum(l) / len(l) if l else 0.0
            stats["payoff_ratio"] = abs(stats["avg_winner"] / stats["avg_loser"]) if stats["avg_loser"] else 0.0
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

    def _report_circuit_breaker(self) -> Dict[str, Any]:
        """Report circuit breaker impact on backtest."""
        cb = self.risk_mgr.circuit_breaker
        # Count candles spent in CB-tripped state
        cb_candles = sum(1 for e in self.equity_curve if e.get("cb_active"))
        total_candles = len(self.equity_curve) or 1
        # Track equity curve valleys during CB
        cb_force_close_pnl = sum(e.get("pnl", 0) for e in self.cb_events)
        return {
            "total_trips": cb._trip_count,
            "signals_blocked": self.signals_blocked_by_cb,
            "candles_locked_out": cb_candles,
            "lockout_pct": round(cb_candles / total_candles * 100, 1),
            "force_close_events": len(self.cb_events),
            "force_close_pnl": round(cb_force_close_pnl, 2),
            "peak_equity": round(cb.peak_equity, 2),
        }

    def _report_by_agreement(self) -> Dict[str, Any]:
        """Report performance by number of strategies agreeing."""
        result = {}
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                meta = event.metadata or {}
                num_agree = meta.get("num_agree", 0)
                strategies = meta.get("strategies_agree", [])
                key = f"{num_agree}_agree"
                if key not in result:
                    result[key] = {
                        "trades": 0, "wins": 0, "pnl": 0.0,
                        "close_types": {}, "strategy_combos": {},
                    }
                bucket = result[key]
                bucket["trades"] += 1
                if event.pnl > 0:
                    bucket["wins"] += 1
                bucket["pnl"] += event.pnl
                # Track close types
                ct = bucket["close_types"]
                ct[event.action] = ct.get(event.action, 0) + 1
                # Track which strategy combos appear
                combo = "+".join(sorted(strategies)) if strategies else "unknown"
                sc = bucket["strategy_combos"]
                sc[combo] = sc.get(combo, 0) + 1
        for key, stats in result.items():
            stats["win_rate"] = stats["wins"] / stats["trades"] if stats["trades"] else 0
            stats["avg_pnl"] = stats["pnl"] / stats["trades"] if stats["trades"] else 0
            # Add profit factor per combo
            combo_details = {}
            for combo_key, combo_count in stats.get("strategy_combos", {}).items():
                combo_details[combo_key] = {
                    "trades": combo_count, "wins": 0, "gross_win": 0.0, "gross_loss": 0.0,
                }
            # Re-walk to compute combo-level PF
            for event in self.pos_mgr.trade_log:
                if event.action in self._CLOSE_ACTIONS:
                    meta = event.metadata or {}
                    n = meta.get("num_agree", 0)
                    if f"{n}_agree" != key:
                        continue
                    strats = meta.get("strategies_agree", [])
                    combo = "+".join(sorted(strats)) if strats else "unknown"
                    if combo in combo_details:
                        if event.pnl > 0:
                            combo_details[combo]["wins"] += 1
                            combo_details[combo]["gross_win"] += event.pnl
                        else:
                            combo_details[combo]["gross_loss"] += abs(event.pnl)
            for combo, cd in combo_details.items():
                cd["pf"] = round(cd["gross_win"] / cd["gross_loss"], 2) if cd["gross_loss"] > 0 else 99.0
                cd["wr"] = round(cd["wins"] / cd["trades"], 2) if cd["trades"] > 0 else 0
            stats["combo_details"] = combo_details
        return result

    def _report_strategy_health(self) -> Dict[str, Any]:
        """Per-strategy health metrics: PF, EV, streaks, worst trade.

        PnL is attributed proportionally: if 2 strategies agreed on a trade,
        each gets credited with 50% of the PnL (not 100% each).
        """
        contrib: Dict[str, Dict] = {}
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                meta = event.metadata or {}
                strategies = meta.get("strategies_agree", [])
                n_strats = max(len(strategies), 1)
                attributed_pnl = event.pnl / n_strats
                for strat in strategies:
                    if strat not in contrib:
                        contrib[strat] = {
                            "trades": 0, "wins": 0, "gross_win": 0.0,
                            "gross_loss": 0.0, "worst_trade": 0.0,
                            "max_loss_streak": 0, "_cur_streak": 0,
                            "pnl_curve": [],
                        }
                    c = contrib[strat]
                    c["trades"] += 1
                    c["pnl_curve"].append(attributed_pnl)
                    if attributed_pnl > 0:
                        c["wins"] += 1
                        c["gross_win"] += attributed_pnl
                        c["_cur_streak"] = 0
                    else:
                        c["gross_loss"] += abs(attributed_pnl)
                        c["_cur_streak"] += 1
                        c["max_loss_streak"] = max(c["max_loss_streak"], c["_cur_streak"])
                        c["worst_trade"] = min(c["worst_trade"], attributed_pnl)

        result = {}
        for strat, c in contrib.items():
            t = c["trades"]
            w = c["wins"]
            wr = w / t if t > 0 else 0
            pf = round(c["gross_win"] / c["gross_loss"], 2) if c["gross_loss"] > 0 else 99.0
            avg_win = c["gross_win"] / w if w > 0 else 0
            avg_loss = c["gross_loss"] / (t - w) if (t - w) > 0 else 0
            ev = round(avg_win * wr - avg_loss * (1 - wr), 2)
            net = round(c["gross_win"] - c["gross_loss"], 2)
            result[strat] = {
                "trades": t,
                "win_rate": round(wr, 3),
                "profit_factor": pf,
                "expected_value": ev,
                "net_pnl": net,
                "max_loss_streak": c["max_loss_streak"],
                "worst_trade": round(c["worst_trade"], 2),
                "gross_win": round(c["gross_win"], 2),
                "gross_loss": round(c["gross_loss"], 2),
            }
            del c["_cur_streak"]
            del c["pnl_curve"]
        return result

    def _report_exit_types(self) -> Dict[str, Any]:
        """Report performance by exit type (SL, TP1, TP2, TRAILING_STOP, etc.)."""
        result = {}
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                action = event.action
                if action not in result:
                    result[action] = {"trades": 0, "wins": 0, "pnl": 0.0}
                result[action]["trades"] += 1
                if event.pnl > 0:
                    result[action]["wins"] += 1
                result[action]["pnl"] += event.pnl
        for action, stats in result.items():
            t = stats["trades"]
            stats["win_rate"] = round(stats["wins"] / t, 3) if t > 0 else 0
            stats["avg_pnl"] = round(stats["pnl"] / t, 2) if t > 0 else 0
            stats["pnl"] = round(stats["pnl"], 2)
        return result

    # ── New Diagnostic Report Methods ─────────────────────────────────

    def _report_signal_funnel(self) -> Dict[str, Any]:
        """Signal pipeline conversion funnel — where signals are born and where they die."""
        total = self.candle_stats["total"]
        no_signal = self.candle_stats["no_signal"]
        cb_blocked = self.candle_stats["cb_blocked"]
        signal_gen = self.candle_stats["signal"]

        # Count rejections by gate
        gate_counts = {}
        for rej in self.signal_rejections:
            gate = rej.get("gate", "unknown")
            gate_counts[gate] = gate_counts.get(gate, 0) + 1

        executed = len(self.signals_generated)
        llm_vetoed = signal_gen - executed - sum(gate_counts.values())
        if llm_vetoed < 0:
            llm_vetoed = 0

        regime_blocked = self.candle_stats.get("regime_blocked", 0)

        return {
            "candles_processed": total,
            "no_signal": no_signal,
            "cb_blocked": cb_blocked,
            "regime_blocked": regime_blocked,
            "signals_generated": signal_gen,
            "gate_rejections": gate_counts,
            "llm_vetoed": llm_vetoed,
            "executed": executed,
            "conversion_rate": round(executed / total * 100, 1) if total > 0 else 0,
        }

    def _report_positions(self) -> Dict[str, Any]:
        """Group close events into actual positions for lifecycle analysis."""
        positions = []
        current_pos: Dict[str, Dict] = {}

        for idx, event in enumerate(self.pos_mgr.trade_log):
            if event.action == "OPEN":
                current_pos[event.symbol] = {
                    "open": event,
                    "open_idx": idx,
                    "closes": [],
                    "pnl": 0.0,
                    "fees": 0.0,
                    "hit_tp1": False,
                    "symbol": event.symbol,
                    "side": getattr(event, "side", ""),
                }
            elif event.action in self._CLOSE_ACTIONS:
                pos = current_pos.get(event.symbol)
                if pos:
                    pos["closes"].append(event)
                    pos["pnl"] += event.pnl
                    pos["fees"] += event.fee
                    if event.action == "TP1":
                        pos["hit_tp1"] = True
                    else:
                        # Final close — position complete
                        pos["final_action"] = event.action
                        meta = event.metadata or {}
                        # hold_time_s from position_manager is wallclock (~0.001s in backtest).
                        # Use sim-time fallback if wallclock is < 60s (i.e. not real hold time).
                        hold_s = meta.get("hold_time_s", 0)
                        if hold_s < 60:
                            # In backtest, wallclock hold_time is ~0.
                            # Use sim_time from entry_reasons + close_sim_time.
                            entry_reasons = meta.get("entry_reasons") or {}
                            open_sim = entry_reasons.get("sim_time", "")
                            close_sim = meta.get("close_sim_time", "")
                            if open_sim and close_sim:
                                try:
                                    open_t = pd.Timestamp(open_sim)
                                    close_t = pd.Timestamp(close_sim)
                                    hold_s = max((close_t - open_t).total_seconds(), 0)
                                except Exception:
                                    pass
                        pos["hold_time_s"] = hold_s
                        pos["confidence"] = meta.get("confidence", 0)
                        pos["num_agree"] = meta.get("num_agree", 0)
                        pos["strategies_agree"] = meta.get("strategies_agree", [])
                        positions.append(pos)
                        del current_pos[event.symbol]

        if not positions:
            return {"count": 0}

        # Classify outcomes
        outcomes = {}
        winners = [p for p in positions if p["pnl"] > 0]
        losers = [p for p in positions if p["pnl"] <= 0]
        hit_tp1 = [p for p in positions if p["hit_tp1"]]
        hold_times = [p["hold_time_s"] for p in positions if p["hold_time_s"] > 0]

        for p in positions:
            if p["hit_tp1"]:
                outcome_key = f"TP1 -> {p.get('final_action', 'unknown')}"
            else:
                outcome_key = p.get("final_action", "unknown")
            outcomes[outcome_key] = outcomes.get(outcome_key, 0) + 1

        win_pnls = [p["pnl"] for p in winners]
        loss_pnls = [p["pnl"] for p in losers]

        return {
            "count": len(positions),
            "win_rate": round(len(winners) / len(positions) * 100, 1),
            "hit_tp1_count": len(hit_tp1),
            "hit_tp1_pct": round(len(hit_tp1) / len(positions) * 100, 1),
            "outcomes": outcomes,
            "avg_hold_h": round(sum(hold_times) / len(hold_times) / 3600, 1) if hold_times else 0,
            "median_hold_h": round(sorted(hold_times)[len(hold_times) // 2] / 3600, 1) if hold_times else 0,
            "avg_winner": round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0,
            "avg_loser": round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0,
            "largest_winner": round(max(win_pnls), 2) if win_pnls else 0,
            "largest_loser": round(min(loss_pnls), 2) if loss_pnls else 0,
            "payoff_ratio": round(abs(sum(win_pnls) / len(win_pnls)) / abs(sum(loss_pnls) / len(loss_pnls)), 2) if loss_pnls and win_pnls and sum(loss_pnls) != 0 else 0,
        }

    def _report_costs(self) -> Dict[str, Any]:
        """Fee and funding cost breakdown — explains gross-to-net PnL gap."""
        gross_pnl = 0.0
        total_fees = 0.0
        total_funding = 0.0
        close_count = 0

        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                gross_pnl += event.pnl
                total_fees += event.fee
                close_count += 1
                meta = event.metadata or {}
                if event.action != "TP1":
                    total_funding += meta.get("funding_costs", 0)

        net_pnl = gross_pnl - total_fees - total_funding
        fee_drag_pct = round(total_fees / abs(gross_pnl) * 100, 1) if gross_pnl != 0 else 0

        # Break-even win rate: given avg win/loss sizes, what WR covers fees?
        wins = [e.pnl for e in self.pos_mgr.trade_log if e.action in self._CLOSE_ACTIONS and e.pnl > 0]
        losses = [e.pnl for e in self.pos_mgr.trade_log if e.action in self._CLOSE_ACTIONS and e.pnl <= 0]
        avg_win = sum(wins) / len(wins) if wins else 1
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1
        be_wr = round(avg_loss / (avg_win + avg_loss) * 100, 1) if (avg_win + avg_loss) > 0 else 50

        return {
            "gross_pnl": round(gross_pnl, 2),
            "total_fees": round(total_fees, 2),
            "total_funding": round(total_funding, 2),
            "net_pnl": round(net_pnl, 2),
            "fee_drag_pct": fee_drag_pct,
            "avg_fee_per_event": round(total_fees / close_count, 2) if close_count else 0,
            "breakeven_wr": be_wr,
        }

    def _report_confidence_analysis(self) -> Dict[str, Any]:
        """Bucket positions by confidence range to find optimal threshold."""
        buckets: Dict[str, Dict] = {}
        ranges = [(60, 69), (70, 79), (80, 89), (90, 100)]

        # Group by position (use OPEN events + sum close events)
        current_pos: Dict[str, Dict] = {}
        for event in self.pos_mgr.trade_log:
            if event.action == "OPEN":
                meta = event.metadata or {}
                conf = meta.get("confidence", getattr(event, "confidence", 0)) or 0
                current_pos[event.symbol] = {"pnl": 0.0, "confidence": conf}
            elif event.action in self._CLOSE_ACTIONS:
                pos = current_pos.get(event.symbol)
                if pos:
                    pos["pnl"] += event.pnl
                    meta = event.metadata or {}
                    if pos["confidence"] == 0:
                        pos["confidence"] = meta.get("confidence", 0) or 0
                    if event.action != "TP1":
                        conf = pos["confidence"]
                        bucket_key = "< 60%"
                        for lo, hi in ranges:
                            if lo <= conf <= hi:
                                bucket_key = f"{lo}-{hi}%"
                                break
                        if conf > 100:
                            bucket_key = "90-100%"
                        if bucket_key not in buckets:
                            buckets[bucket_key] = {"count": 0, "wins": 0, "pnl": 0.0, "gross_win": 0.0, "gross_loss": 0.0}
                        b = buckets[bucket_key]
                        b["count"] += 1
                        b["pnl"] += pos["pnl"]
                        if pos["pnl"] > 0:
                            b["wins"] += 1
                            b["gross_win"] += pos["pnl"]
                        else:
                            b["gross_loss"] += abs(pos["pnl"])
                        del current_pos[event.symbol]

        result = {}
        optimal_threshold = None
        for key in ["< 60%"] + [f"{lo}-{hi}%" for lo, hi in ranges]:
            if key in buckets:
                b = buckets[key]
                wr = round(b["wins"] / b["count"] * 100, 1) if b["count"] > 0 else 0
                pf = round(b["gross_win"] / b["gross_loss"], 2) if b["gross_loss"] > 0 else 99.0
                result[key] = {
                    "count": b["count"],
                    "win_rate": wr,
                    "pnl": round(b["pnl"], 2),
                    "profit_factor": pf,
                }
                if b["pnl"] < 0 and optimal_threshold is None:
                    optimal_threshold = key

        return {"buckets": result, "optimal_threshold": optimal_threshold}

    def _report_risk_metrics(self, max_drawdown: float, max_dd_duration: int) -> Dict[str, Any]:
        """Standard quantitative risk/performance metrics."""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return {}

        # Use MTM equity (includes unrealized PnL) for accurate risk metrics
        equities = [e.get("mtm_equity", e["equity"]) for e in self.equity_curve]
        starting = self.config.starting_equity
        final = equities[-1]

        # Daily returns: group equity curve by calendar date for accurate Sharpe
        from collections import defaultdict
        daily_equity_map = defaultdict(list)
        for e in self.equity_curve:
            date_str = str(e["time"])[:10]  # YYYY-MM-DD
            daily_equity_map[date_str].append(e.get("mtm_equity", e["equity"]))

        sorted_dates = sorted(daily_equity_map.keys())
        daily_returns = []
        for j in range(1, len(sorted_dates)):
            prev_eq = daily_equity_map[sorted_dates[j - 1]][-1]  # End of previous day
            curr_eq = daily_equity_map[sorted_dates[j]][-1]       # End of current day
            if prev_eq > 0:
                daily_returns.append((curr_eq - prev_eq) / prev_eq)

        if not daily_returns:
            return {}

        mean_daily = np.mean(daily_returns)
        std_daily = np.std(daily_returns)
        downside = [r for r in daily_returns if r < 0]
        std_downside = np.std(downside) if downside else 0.001

        # Annualize
        trading_days = len(daily_returns)
        annual_factor = 365  # crypto markets run 365 days
        annualized_return = ((final / starting) ** (annual_factor / max(trading_days, 1))) - 1

        sharpe = round(float(mean_daily / std_daily * np.sqrt(annual_factor)), 2) if std_daily > 0 else 0
        sortino = round(float(mean_daily / std_downside * np.sqrt(annual_factor)), 2) if std_downside > 0 else 0
        calmar = round(float(annualized_return / max_drawdown), 2) if max_drawdown > 0 else 0

        # Profit factor
        gross_wins = sum(e.pnl for e in self.pos_mgr.trade_log if e.action in self._CLOSE_ACTIONS and e.pnl > 0)
        gross_losses = abs(sum(e.pnl for e in self.pos_mgr.trade_log if e.action in self._CLOSE_ACTIONS and e.pnl <= 0))
        profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else 99.0

        # Time in market
        in_market = sum(1 for e in self.equity_curve if e.get("open_positions", 0) > 0)
        time_in_market = round(in_market / len(self.equity_curve) * 100, 1)

        # Recovery factor
        max_dd_dollars = max_drawdown * max(equities)
        net_profit = final - starting
        recovery_factor = round(net_profit / max_dd_dollars, 2) if max_dd_dollars > 0 else 0

        return {
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "profit_factor": profit_factor,
            "recovery_factor": recovery_factor,
            "time_in_market_pct": time_in_market,
            "max_dd_duration_candles": max_dd_duration,
            "annualized_return_pct": round(annualized_return * 100, 1),
        }

    def _report_by_regime(self) -> Dict[str, Any]:
        """Performance breakdown by market regime at entry."""
        regime_stats: Dict[str, Dict] = {}
        for sig in self.signals_generated:
            regime = sig.get("regime", "unknown")
            if regime not in regime_stats:
                regime_stats[regime] = {"trades": 0, "signals": 0}
            regime_stats[regime]["signals"] += 1

        # Match closed trades to their entry regime via trade_log metadata
        for event in self.pos_mgr.trade_log:
            if event.action not in self._CLOSE_ACTIONS:
                continue
            meta = event.metadata or {}
            regime = meta.get("regime", "") or (meta.get("entry_reasons") or {}).get("regime", "unknown")
            if regime not in regime_stats:
                regime_stats[regime] = {"trades": 0, "signals": 0}
            stats = regime_stats[regime]
            stats["trades"] = stats.get("trades", 0) + 1
            stats.setdefault("wins", 0)
            stats.setdefault("pnl", 0.0)
            if event.pnl > 0:
                stats["wins"] += 1
            stats["pnl"] += event.pnl

        # Compute win rates
        for regime, stats in regime_stats.items():
            t = stats.get("trades", 0)
            stats["win_rate"] = round(stats.get("wins", 0) / t * 100, 1) if t > 0 else 0
            stats["pnl"] = round(stats.get("pnl", 0), 2)

        return regime_stats

    def _report_confidence_regime_crosstab(self) -> Dict[str, Any]:
        """Cross-tab: confidence band × regime → WR and PnL.
        Reveals whether high confidence clusters in bad regimes."""
        grid: Dict[str, Dict[str, Dict]] = {}
        conf_ranges = [(0, 59, "< 60%"), (60, 69, "60-69%"), (70, 79, "70-79%"),
                       (80, 89, "80-89%"), (90, 100, "90-100%")]

        current_pos: Dict[str, Dict] = {}
        for event in self.pos_mgr.trade_log:
            if event.action == "OPEN":
                meta = event.metadata or {}
                conf = meta.get("confidence", getattr(event, "confidence", 0)) or 0
                regime = meta.get("regime", "") or (meta.get("entry_reasons") or {}).get("regime", "unknown")
                current_pos[event.symbol] = {"pnl": 0.0, "confidence": conf, "regime": regime}
            elif event.action in self._CLOSE_ACTIONS:
                pos = current_pos.get(event.symbol)
                if not pos:
                    # Position opened before this method saw the OPEN event — read from close
                    meta = event.metadata or {}
                    conf = meta.get("confidence", getattr(event, "confidence", 0)) or 0
                    regime = meta.get("regime", "") or (meta.get("entry_reasons") or {}).get("regime", "unknown")
                    pos = {"pnl": 0.0, "confidence": conf, "regime": regime}
                    current_pos[event.symbol] = pos
                if pos:
                    pos["pnl"] += event.pnl
                    # Update regime from close event if open didn't have it
                    if pos["regime"] == "unknown":
                        meta = event.metadata or {}
                        pos["regime"] = meta.get("regime", "") or (meta.get("entry_reasons") or {}).get("regime", "unknown")
                    if event.action != "TP1":
                        conf = pos["confidence"]
                        regime = pos["regime"]
                        conf_label = "< 60%"
                        for lo, hi, label in conf_ranges:
                            if lo <= conf <= hi:
                                conf_label = label
                                break
                        if conf_label not in grid:
                            grid[conf_label] = {}
                        if regime not in grid[conf_label]:
                            grid[conf_label][regime] = {"count": 0, "wins": 0, "pnl": 0.0}
                        cell = grid[conf_label][regime]
                        cell["count"] += 1
                        if pos["pnl"] > 0:
                            cell["wins"] += 1
                        cell["pnl"] += pos["pnl"]
                        del current_pos[event.symbol]

        return grid

    def _report_trailing_analysis(self) -> Dict[str, Any]:
        """Analyze trailing stop effectiveness vs fixed TP2."""
        # Build position lifecycle: match TP1 events to their final close
        tp1_positions: Dict[str, Dict] = {}  # symbol -> {tp1_pnl, tp1_price, ...}
        results = {"entered_trailing": 0, "outcomes": {}, "net_trailing_edge": 0.0}

        for event in self.pos_mgr.trade_log:
            if event.action == "TP1":
                tp1_positions[event.symbol] = {
                    "tp1_pnl": event.pnl,
                    "tp1_price": event.price,
                    "tp1_qty_closed": event.qty,
                }
            elif event.action in self._CLOSE_ACTIONS and event.action != "TP1":
                tp1_data = tp1_positions.pop(event.symbol, None)
                if tp1_data:
                    # This position hit TP1 then closed via trailing/SL/TP2
                    results["entered_trailing"] += 1
                    outcome_key = event.action
                    if outcome_key not in results["outcomes"]:
                        results["outcomes"][outcome_key] = {"count": 0, "pnl": 0.0}
                    results["outcomes"][outcome_key]["count"] += 1
                    results["outcomes"][outcome_key]["pnl"] += event.pnl
                    # The trailing edge: pnl of the remaining portion after TP1
                    results["net_trailing_edge"] += event.pnl

        results["net_trailing_edge"] = round(results["net_trailing_edge"], 2)
        for key in results["outcomes"]:
            o = results["outcomes"][key]
            o["avg_pnl"] = round(o["pnl"] / o["count"], 2) if o["count"] > 0 else 0
            o["pnl"] = round(o["pnl"], 2)
        return results

    def _generate_recommendations(self) -> List[str]:
        """Auto-generate actionable recommendations from backtest results."""
        recs = []
        health = self._report_strategy_health()

        # Flag strategies with poor profit factor
        for strat, h in health.items():
            if h["profit_factor"] < 0.8 and h["trades"] >= 10:
                recs.append(
                    f"CONSIDER DISABLING {strat} -- profit factor {h['profit_factor']}, "
                    f"net ${h['net_pnl']:,.2f} over {h['trades']} trades"
                )
            elif h["profit_factor"] < 1.0 and h["trades"] >= 20:
                recs.append(
                    f"WATCH {strat} -- profit factor {h['profit_factor']}, "
                    f"losing ${abs(h['net_pnl']):,.2f}"
                )

        # Compare agreement levels
        by_agree = self._report_by_agreement()
        agree_keys = sorted(by_agree.keys())
        if len(agree_keys) >= 2:
            best_agree = max(agree_keys, key=lambda k: by_agree[k].get("avg_pnl", 0))
            worst_agree = min(agree_keys, key=lambda k: by_agree[k].get("avg_pnl", 0))
            if by_agree[worst_agree]["avg_pnl"] < 0:
                recs.append(
                    f"{best_agree} outperforms {worst_agree} by "
                    f"${by_agree[best_agree]['pnl'] - by_agree[worst_agree]['pnl']:,.2f} "
                    f"-- review losing combos in {worst_agree}"
                )

        # Flag losing combos
        for key, stats in by_agree.items():
            for combo, cd in stats.get("combo_details", {}).items():
                if cd.get("pf", 99) < 0.8 and cd.get("trades", 0) >= 5:
                    recs.append(
                        f"LOSING COMBO in {key}: {combo} -- PF={cd['pf']}, "
                        f"{cd['trades']} trades"
                    )

        # Symbol recommendation
        by_sym = self._report_by_symbol()
        if by_sym:
            best_sym = max(by_sym.items(), key=lambda x: x[1].get("win_rate", 0))
            recs.append(
                f"Strongest symbol: {best_sym[0]} ({best_sym[1]['win_rate']:.0%} WR, "
                f"${best_sym[1]['pnl']:,.2f})"
            )

        # CB lockout warning
        cb = self._report_circuit_breaker()
        if cb.get("lockout_pct", 0) > 20:
            recs.append(
                f"Circuit breakers locked out {cb['lockout_pct']:.1f}% of backtest "
                f"-- signals may be too aggressive or risk limits too tight"
            )

        # Drawdown warning
        if self.equity_curve:
            equities = [e["equity"] for e in self.equity_curve]
            running_peak = equities[0]
            max_dd = 0
            for e in equities:
                running_peak = max(running_peak, e)
                if running_peak > 0:
                    max_dd = max(max_dd, (running_peak - e) / running_peak * 100)
            if max_dd > 30:
                recs.append(
                    f"Max drawdown {max_dd:.1f}% exceeds safe threshold "
                    f"-- consider reducing leverage or risk_per_trade"
                )

        # Fee drag warning
        costs = self._report_costs()
        if costs.get("fee_drag_pct", 0) > 50 and costs.get("gross_pnl", 0) > 0:
            recs.append(
                f"Fees consume {costs['fee_drag_pct']:.0f}% of gross PnL "
                f"(${costs['total_fees']:,.2f} in fees vs ${costs['gross_pnl']:,.2f} gross) "
                f"-- consider reducing trade frequency or tightening entry criteria"
            )

        # Signal funnel warning
        funnel = self._report_signal_funnel()
        if funnel.get("gate_rejections"):
            total_rejected = sum(funnel["gate_rejections"].values())
            if total_rejected > funnel.get("executed", 1) * 0.2:
                for gate, count in funnel["gate_rejections"].items():
                    if count > 5:
                        recs.append(
                            f"{count} signals rejected at {gate} gate "
                            f"-- check {gate} configuration"
                        )

        return recs

    def _report_trade_timeline(self) -> List[Dict[str, Any]]:
        """Build per-trade timeline with full position context for analysis."""
        # Index open events by symbol to match with close events
        open_events: Dict[str, Any] = {}
        for event in self.pos_mgr.trade_log:
            if event.action == "OPEN":
                open_events[event.symbol] = event

        # LLM decisions are looked up via reverse iteration in the loop below

        timeline = []
        for event in self.pos_mgr.trade_log:
            if event.action in self._CLOSE_ACTIONS:
                meta = event.metadata or {}
                open_ev = open_events.get(event.symbol)
                open_meta = open_ev.metadata if open_ev and open_ev.metadata else {}

                entry_price = meta.get("entry", 0) or getattr(event, "entry_price", 0) or (open_ev.price if open_ev else 0)
                exit_price = event.price

                sl = meta.get("sl", 0)
                tp1 = meta.get("tp1", 0)
                tp2 = meta.get("tp2", 0)
                confidence = meta.get("confidence", 0)

                # Calculate R:R achieved
                try:
                    risk = abs(float(entry_price) - float(sl)) if entry_price and sl else 0
                    reward = abs(float(event.pnl))
                    qty = float(event.qty) if event.qty else 0
                    rr_achieved = (reward / risk / qty) if risk > 0 and qty > 0 else 0
                except (TypeError, ValueError):
                    rr_achieved = 0

                # Duration in hours
                hold_s = meta.get("hold_time_s", 0)
                if hold_s:
                    duration_h = round(hold_s / 3600, 1)
                elif open_ev:
                    delta = event.timestamp - open_ev.timestamp
                    duration_h = round(delta.total_seconds() / 3600, 1)
                else:
                    duration_h = 0

                # State path from metadata
                state_path = meta.get("state_path", "")

                row = {
                    "symbol": event.symbol,
                    "side": getattr(event, "side", ""),
                    "strategy": event.strategy or "unknown",
                    "close_reason": event.action,
                    "entry": round(entry_price, 2) if entry_price else "",
                    "exit": round(exit_price, 2),
                    "sl": round(sl, 2) if sl else "",
                    "tp1": round(tp1, 2) if tp1 else "",
                    "tp2": round(tp2, 2) if tp2 else "",
                    "pnl": round(event.pnl, 2),
                    "fee": round(getattr(event, "fee", 0), 2),
                    "leverage": round(getattr(event, "leverage", 1.0), 2),
                    "confidence": round(confidence, 1) if confidence else "",
                    "rr_achieved": round(rr_achieved, 2) if rr_achieved else "",
                    "duration_h": duration_h,
                    "state_path": state_path,
                    "outcome": "WIN" if event.pnl > 0 else ("LOSS" if event.pnl < -0.01 else "BE"),
                }

                # LLM context
                if self.llm and self.llm.decisions:
                    for dec in reversed(self.llm.decisions):
                        if dec.get("symbol", "") == event.symbol:
                            row["llm_action"] = dec.get("action", "")
                            row["llm_regime"] = dec.get("regime", "")
                            row["llm_confidence"] = dec.get("confidence", 0)
                            break

                timeline.append(row)
        return timeline


def export_trade_csv(report: Dict, filepath: str):
    """Export per-trade timeline as CSV for spreadsheet analysis."""
    import csv

    timeline = report.get("trade_timeline", [])
    if not timeline:
        return

    fieldnames = [
        "symbol", "side", "strategy", "close_reason",
        "entry", "exit", "sl", "tp1", "tp2",
        "pnl", "fee", "leverage", "confidence",
        "rr_achieved", "duration_h", "state_path", "outcome",
        "llm_action", "llm_regime", "llm_confidence",
    ]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(timeline)

    # Auto-export equity curve alongside trade CSV
    equity_path = filepath.replace(".csv", "_equity_curve.csv")
    export_equity_curve_csv(report, equity_path)


def export_equity_curve_csv(report: Dict, filepath: str):
    """Export equity curve as CSV for visualization."""
    import csv

    curve = report.get("equity_curve", [])
    if not curve:
        return

    fieldnames = ["time", "equity", "open_positions", "cb_active", "drawdown_pct"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(curve)
    print(f"  Equity curve exported to {filepath}")


def print_report(report: Dict):
    """Pretty-print a comprehensive backtest diagnostic report."""
    r = report["results"]
    c = report["config"]
    positions = report.get("positions", {})
    costs = report.get("costs", {})
    risk = report.get("risk_metrics", {})

    W = 68  # report width

    print("\n" + "=" * W)
    print("BACKTEST REPORT")
    print("=" * W)

    # ── SUMMARY ──
    print(f"\n{'── SUMMARY ':─<{W}}")
    print(f"  Period:          {c['days']} days | {', '.join(c['symbols'])}")
    print(f"  Equity:          ${c['starting_equity']:,.2f} -> ${r['final_equity']:,.2f} ({r['total_return_pct']:+.2f}%)")
    print(f"  Max Drawdown:    {r['max_drawdown_pct']:.2f}%")
    if risk:
        print(f"  Sharpe / Sortino / Calmar: {risk.get('sharpe', 0)} / {risk.get('sortino', 0)} / {risk.get('calmar', 0)}")
    pos_count = positions.get("count", r.get("positions_opened", 0))
    events_count = r.get("close_events", r.get("total_trades", 0))
    tp1_pct = positions.get("hit_tp1_pct", 0)
    pos_wr = positions.get("win_rate", 0)
    print(f"\n  Positions:       {pos_count} opened | {positions.get('hit_tp1_count', 0)} hit TP1 ({tp1_pct:.1f}%)")
    print(f"  Close Events:    {events_count} (TP1 partials counted separately)")
    print(f"  Win Rate:        {pos_wr:.1f}% (by position) | {r.get('win_rate', 0):.1%} (by event)")
    print(f"\n  Gross PnL:       ${costs.get('gross_pnl', 0):>10,.2f}")
    print(f"  Fees:            ${costs.get('total_fees', 0):>10,.2f}")
    if costs.get("total_funding", 0) != 0:
        print(f"  Funding:         ${costs.get('total_funding', 0):>10,.2f}")
    print(f"  Net PnL:         ${costs.get('net_pnl', r.get('net_pnl', 0)):>10,.2f}")

    # ── SIGNAL FUNNEL ──
    funnel = report.get("signal_funnel", {})
    if funnel.get("candles_processed", 0) > 0:
        total = funnel["candles_processed"]
        print(f"\n{'── SIGNAL FUNNEL ':─<{W}}")
        print(f"  Candles processed: {total:,}")
        print(f"    No signal:       {funnel.get('no_signal', 0):>6,} ({funnel.get('no_signal', 0)/total*100:.1f}%)")
        print(f"    CB blocked:      {funnel.get('cb_blocked', 0):>6,} ({funnel.get('cb_blocked', 0)/total*100:.1f}%)")
        regime_blk = funnel.get("regime_blocked", 0)
        if regime_blk > 0:
            print(f"    Regime blocked:  {regime_blk:>6,} ({regime_blk/total*100:.1f}%)")
        print(f"    Signal gen:      {funnel.get('signals_generated', 0):>6,} ({funnel.get('signals_generated', 0)/total*100:.1f}%)")
        gates = funnel.get("gate_rejections", {})
        for gate, count in sorted(gates.items(), key=lambda x: -x[1]):
            print(f"      {gate} rejected:  {count:>4}")
        if funnel.get("llm_vetoed", 0) > 0:
            print(f"      LLM vetoed:    {funnel['llm_vetoed']:>4}")
        print(f"    Executed:        {funnel.get('executed', 0):>6,}")
        print(f"  Conversion:        {funnel.get('conversion_rate', 0):.1f}% (candle -> trade)")

    # ── COST BREAKDOWN ──
    if costs:
        print(f"\n{'── COST BREAKDOWN ':─<{W}}")
        print(f"  Gross PnL:         ${costs.get('gross_pnl', 0):>10,.2f}")
        print(f"  Trading fees:      ${-costs.get('total_fees', 0):>10,.2f}")
        if costs.get("total_funding", 0) != 0:
            print(f"  Funding costs:     ${-costs.get('total_funding', 0):>10,.2f}")
        print(f"  {'─' * 30}")
        print(f"  Net PnL:           ${costs.get('net_pnl', 0):>10,.2f}")
        print(f"  Fee drag:          {costs.get('fee_drag_pct', 0):.1f}% of gross PnL consumed by fees")
        print(f"  Avg fee/event:     ${costs.get('avg_fee_per_event', 0):.2f}")
        print(f"  Break-even WR:     {costs.get('breakeven_wr', 0):.1f}%")

    # ── POSITION LIFECYCLE ──
    if positions.get("count", 0) > 0:
        print(f"\n{'── POSITION LIFECYCLE ':─<{W}}")
        print(f"  Positions opened:  {positions['count']}")
        print(f"  Avg hold:          {positions.get('avg_hold_h', 0):.1f}h | Median: {positions.get('median_hold_h', 0):.1f}h")
        print(f"\n  Position outcomes:")
        for outcome, count in sorted(positions.get("outcomes", {}).items(), key=lambda x: -x[1]):
            pct = count / positions["count"] * 100
            print(f"    {outcome:24s}  {count:>4} ({pct:5.1f}%)")
        print(f"\n  Position win rate: {positions['win_rate']:.1f}%")
        print(f"  Avg winner:        ${positions.get('avg_winner', 0):>8.2f}")
        print(f"  Avg loser:         ${positions.get('avg_loser', 0):>8.2f}")
        print(f"  Payoff ratio:      {positions.get('payoff_ratio', 0):.2f}:1")
        print(f"  Largest winner:    ${positions.get('largest_winner', 0):>8.2f}")
        print(f"  Largest loser:     ${positions.get('largest_loser', 0):>8.2f}")

    # ── BY SYMBOL ──
    symbol_pnl = report.get("symbol_pnl", {})
    by_symbol = report.get("by_symbol", {})
    if by_symbol or symbol_pnl:
        print(f"\n{'── BY SYMBOL ':─<{W}}")
        for sym in sorted(set(list(by_symbol.keys()) + list(symbol_pnl.keys()))):
            stats = by_symbol.get(sym, {})
            net = symbol_pnl.get(sym, stats.get("pnl", 0))
            trades = stats.get("trades", 0)
            wr = stats.get("win_rate", 0)
            avg_w = stats.get("avg_winner", 0)
            avg_l = stats.get("avg_loser", 0)
            pr = stats.get("payoff_ratio", 0)
            print(f"    {sym:>6s}: {trades:>4} events, {wr:.0%} WR, ${net:>10,.2f} net PnL  "
                  f"(W=${avg_w:>7.2f} / L=${avg_l:>8.2f} = {pr:.2f}:1)")

    # ── STRATEGY HEALTH ──
    health = report.get("strategy_health", {})
    if health:
        print(f"\n{'── STRATEGY HEALTH (attributed PnL) ':─<{W}}")
        for strat in sorted(health.keys(), key=lambda k: -health[k].get("net_pnl", 0)):
            h = health[strat]
            flag = "  !! LOSING" if h["profit_factor"] < 1.0 and h["trades"] >= 10 else ""
            print(
                f"    {strat:22s}  PF={h['profit_factor']:<5}  "
                f"EV=${h['expected_value']:<8}  "
                f"net=${h['net_pnl']:>9,.2f}  "
                f"WR={h['win_rate']:.0%}  "
                f"streak={h['max_loss_streak']}  "
                f"worst=${h['worst_trade']:,.2f}{flag}"
            )

    # ── STRATEGY COMBOS ──
    by_agree = report.get("by_agreement", {})
    if by_agree:
        print(f"\n{'── STRATEGY COMBOS ':─<{W}}")
        for key in sorted(by_agree.keys()):
            stats = by_agree[key]
            wr = stats['win_rate']
            avg = stats['avg_pnl']
            print(f"  {key}: {stats['trades']} events, {wr:.0%} WR, "
                  f"${stats['pnl']:,.2f} total, ${avg:,.2f} avg")
            combo_details = stats.get("combo_details", {})
            for combo, cd in sorted(combo_details.items(), key=lambda x: -x[1].get("trades", 0)):
                if cd.get("trades", 0) >= 3:
                    label = "PROFITABLE" if cd.get("pf", 0) >= 1.0 else "LOSING"
                    print(f"    {combo:40s}  {cd['trades']:>4} trades  PF={cd['pf']:<5} WR={cd['wr']:.0%}  {label}")

    # ── CONFIDENCE ANALYSIS ──
    conf = report.get("confidence_analysis", {})
    conf_buckets = conf.get("buckets", {})
    if conf_buckets:
        print(f"\n{'── CONFIDENCE ANALYSIS ':─<{W}}")
        for key, b in conf_buckets.items():
            label = "PROFITABLE" if b["pnl"] > 0 else "LOSING"
            print(f"    {key:>8s}:  {b['count']:>4} positions  {b['win_rate']:.1f}% WR  "
                  f"${b['pnl']:>10,.2f}  PF={b['profit_factor']:<5}  {label}")
        if conf.get("optimal_threshold"):
            print(f"  Losing below: {conf['optimal_threshold']} -- consider raising confidence floor")

    # ── TRAILING STOP ANALYSIS ──
    trail = report.get("trailing_analysis", {})
    if trail.get("entered_trailing", 0) > 0:
        print(f"\n{'── TRAILING STOP ANALYSIS ':─<{W}}")
        print(f"  Positions entering trailing: {trail['entered_trailing']}")
        for outcome, data in sorted(trail.get("outcomes", {}).items(), key=lambda x: -x[1]["count"]):
            print(f"    -> {outcome:16s}  {data['count']:>4}  avg ${data['avg_pnl']:>8.2f}  total ${data['pnl']:>10,.2f}")
        print(f"  Net trailing edge: ${trail.get('net_trailing_edge', 0):>10,.2f}")
        verdict = "HELPING" if trail.get("net_trailing_edge", 0) > 0 else "HURTING"
        print(f"  Verdict: trailing stops are {verdict}")

    # ── EXIT TYPE BREAKDOWN ──
    exit_types = report.get("exit_types", {})
    if exit_types:
        print(f"\n{'── EXIT TYPE BREAKDOWN ':─<{W}}")
        for action in sorted(exit_types.keys(), key=lambda k: -exit_types[k]["trades"]):
            stats = exit_types[action]
            print(
                f"    {action:16s}  {stats['trades']:>4} events  "
                f"WR={stats['win_rate']:.0%}  "
                f"avg=${stats['avg_pnl']:>8.2f}  "
                f"total=${stats['pnl']:>10,.2f}"
            )

    # ── CONFIDENCE × REGIME CROSS-TAB ──
    crosstab = report.get("conf_regime_crosstab", {})
    if crosstab:
        print(f"\n{'── CONFIDENCE × REGIME ':─<{W}}")
        # Collect all regimes across all confidence bands
        all_regimes = sorted({r for bands in crosstab.values() for r in bands})
        # Header
        hdr = f"    {'':>10s}"
        for regime in all_regimes:
            hdr += f"  {regime:>16s}"
        print(hdr)
        # Rows by confidence band
        for conf_label in ["< 60%", "60-69%", "70-79%", "80-89%", "90-100%"]:
            if conf_label not in crosstab:
                continue
            row = f"    {conf_label:>10s}"
            for regime in all_regimes:
                cell = crosstab[conf_label].get(regime)
                if cell and cell["count"] > 0:
                    wr = cell["wins"] / cell["count"] * 100
                    row += f"  {cell['count']:>3}t {wr:>3.0f}%WR ${cell['pnl']:>7.0f}"
                else:
                    row += f"  {'---':>16s}"
            print(row)

    # ── BY REGIME ──
    by_regime = report.get("by_regime", {})
    if by_regime:
        print(f"\n{'── BY REGIME ':─<{W}}")
        for regime in sorted(by_regime.keys(), key=lambda k: -by_regime[k].get("trades", 0)):
            stats = by_regime[regime]
            t = stats.get("trades", 0)
            if t > 0:
                print(
                    f"    {regime:18s}  {t:>3} trades  "
                    f"WR={stats.get('win_rate', 0):>5.1f}%  "
                    f"PnL=${stats.get('pnl', 0):>10,.2f}"
                )

    # ── RISK METRICS ──
    if risk:
        print(f"\n{'── RISK METRICS ':─<{W}}")
        print(f"  Sharpe ratio:      {risk.get('sharpe', 0):>6} (annualized)")
        print(f"  Sortino ratio:     {risk.get('sortino', 0):>6}")
        print(f"  Calmar ratio:      {risk.get('calmar', 0):>6}")
        print(f"  Profit factor:     {risk.get('profit_factor', 0):>6}")
        print(f"  Recovery factor:   {risk.get('recovery_factor', 0):>6}")
        print(f"  Time in market:    {risk.get('time_in_market_pct', 0):>5.1f}%")
        print(f"  Max DD duration:   {risk.get('max_dd_duration_candles', 0):>5} candles")
        print(f"  Annualized return: {risk.get('annualized_return_pct', 0):>5.1f}%")

    # ── LEVERAGE STATS ──
    lev = report.get("leverage_stats", {})
    if lev:
        print(f"\n{'── LEVERAGE STATS ':─<{W}}")
        print(f"  Spot:      {lev.get('spot', {}).get('trades', 0):>4} events  ${lev.get('spot', {}).get('pnl', 0):>10,.2f}")
        print(f"  Leveraged: {lev.get('leveraged', {}).get('trades', 0):>4} events  ${lev.get('leveraged', {}).get('pnl', 0):>10,.2f}  avg {lev.get('leveraged', {}).get('avg_leverage', 0):.1f}x")

    # ── CIRCUIT BREAKER ──
    cb = report.get("circuit_breaker_stats", {})
    if cb:
        print(f"\n{'── CIRCUIT BREAKER ':─<{W}}")
        print(f"  Trips: {cb.get('total_trips', 0)} | Signals blocked: {cb.get('signals_blocked', 0)} | "
              f"Lockout: {cb.get('lockout_pct', 0):.1f}% of backtest")
        if cb.get("force_close_events", 0) > 0:
            print(f"  Force closes: {cb['force_close_events']} (PnL: ${cb.get('force_close_pnl', 0):,.2f})")

    # ── LLM STATS (only if used) ──
    llm_stats = report.get("llm_stats")
    if llm_stats:
        print(f"\n{'── LLM AGENT STATS ':─<{W}}")
        print(f"  Cost: ${llm_stats.get('total_cost_usd', 0):.4f} / ${llm_stats.get('budget_usd', 0):.2f} budget ({llm_stats.get('budget_used_pct', 0):.1f}% used)")
        print(f"  API calls: {llm_stats.get('llm_calls', 0)} | Failures: {llm_stats.get('llm_failures', 0)}")
        if llm_stats.get("budget_exhausted"):
            print(f"  WARNING: Budget was exhausted during run")

        agent_costs = report.get("llm_agent_costs", {})
        if agent_costs:
            for agent, cost in sorted(agent_costs.items(), key=lambda x: -x[1]):
                print(f"    {agent:12s}  ${cost:.4f}")

        veto_stats = report.get("llm_veto_stats", {})
        if veto_stats and veto_stats.get("total_decisions", 0) > 0:
            print(f"  Approved: {veto_stats['approved']} | Vetoed: {veto_stats['vetoed']} ({veto_stats['veto_rate']:.0%})")

    # ── RECOMMENDATIONS ──
    recs = report.get("recommendations", [])
    if recs:
        print(f"\n{'── RECOMMENDATIONS ':─<{W}}")
        for rec in recs:
            print(f"  > {rec}")

    # ── TOP / BOTTOM TRADES ──
    timeline = report.get("trade_timeline", [])
    if timeline:
        sorted_trades = sorted(timeline, key=lambda t: t.get("pnl", 0))
        worst = sorted_trades[:3]
        best = sorted_trades[-3:][::-1]
        if best and best[0].get("pnl", 0) > 0:
            print(f"\n{'── TOP WINNERS ':─<{W}}")
            for t in best:
                regime_str = f" [{t['llm_regime']}]" if t.get("llm_regime") else ""
                print(f"    {t['symbol']:6s} {t['strategy']:20s} ${t['pnl']:+8.2f}  {t.get('close_reason', '')}{regime_str}")
        if worst and worst[0].get("pnl", 0) < 0:
            print(f"\n{'── WORST LOSERS ':─<{W}}")
            for t in worst:
                regime_str = f" [{t['llm_regime']}]" if t.get("llm_regime") else ""
                print(f"    {t['symbol']:6s} {t['strategy']:20s} ${t['pnl']:+8.2f}  {t.get('close_reason', '')}{regime_str}")

    print("\n" + "=" * W)


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
