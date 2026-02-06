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
from trading_config import TradingConfig, DEFAULT_SYMBOLS, RISK_MULTIPLIERS
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

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or TradingConfig()

        # Initialize components
        self.fetcher = DataFetcher(cache_ttl=3600)  # long cache for backtest
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
    ) -> Dict[str, Any]:
        """
        Run a backtest.

        Args:
            symbols: List of symbol names (e.g. ["BTC", "ETH", "SOL"])
            days: Number of days of historical data to test on
            strategies: Which strategies to use (default: all)

        Returns:
            Dict with backtest results
        """
        logger.info(f"Starting backtest: {symbols} | {days} days | strategies={strategies or 'all'}")

        # Build strategies
        sym_configs = {s: DEFAULT_SYMBOLS[s] for s in symbols if s in DEFAULT_SYMBOLS}
        active_strategies = self._build_strategies(sym_configs, strategies)

        ensemble = EnsembleStrategy(
            strategies=active_strategies,
            mode=self.config.ensemble_mode,
            min_votes=self.config.min_votes_required,
        )

        # Fetch historical data for all symbols
        all_data = {}
        needed_tfs = ensemble.get_all_required_timeframes()

        for symbol in symbols:
            sym_cfg = sym_configs.get(symbol)
            if not sym_cfg:
                continue
            logger.info(f"Fetching data for {symbol} ({sym_cfg.coingecko_id})")
            data = self.fetcher.fetch_multi_timeframe(sym_cfg.coingecko_id, needed_tfs)
            all_data[symbol] = data

        # Walk forward through data
        # Use 1h timeframe as the primary clock
        for symbol in symbols:
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

        # Generate report
        return self._generate_report(symbols, days)

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

        for i in range(warmup, len(df_1h)):
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

            # Check existing positions
            events = self.pos_mgr.update_price(symbol, current_price)
            for event in events:
                self.risk_mgr.update_equity(event.pnl - event.fee)

            # Try to generate signal
            if self.risk_mgr.can_open_position(self.pos_mgr.get_open_count()):
                signal = ensemble.evaluate(symbol, windowed)
                if signal:
                    self._execute_signal(signal, current_price)

            # Record equity
            self.equity_curve.append({
                "time": str(df_1h["time"].iloc[i]),
                "equity": self.risk_mgr.equity,
                "open_positions": self.pos_mgr.get_open_count(),
            })

    def _walk_daily(self, symbol: str, data: Dict[str, pd.DataFrame], ensemble: EnsembleStrategy):
        """Walk forward through daily data points."""
        df = data.get("daily", pd.DataFrame())
        if df.empty or len(df) < 50:
            return

        warmup = 50

        for i in range(warmup, len(df)):
            windowed = {}
            for tf, df_tf in data.items():
                if df_tf.empty:
                    continue
                current_time = df["time"].iloc[i]
                mask = df_tf["time"] <= current_time
                windowed[tf] = df_tf[mask].copy()

            current_price = float(df["close"].iloc[i])

            events = self.pos_mgr.update_price(symbol, current_price)
            for event in events:
                self.risk_mgr.update_equity(event.pnl - event.fee)

            if self.risk_mgr.can_open_position(self.pos_mgr.get_open_count()):
                signal = ensemble.evaluate(symbol, windowed)
                if signal:
                    self._execute_signal(signal, current_price)

            self.equity_curve.append({
                "time": str(df["time"].iloc[i]),
                "equity": self.risk_mgr.equity,
                "open_positions": self.pos_mgr.get_open_count(),
            })

    def _execute_signal(self, signal: Signal, current_price: float):
        """Execute a signal in backtest mode."""
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

        qty = self.risk_mgr.calculate_qty(signal.entry, signal.sl)
        if qty <= 0:
            return

        side = "LONG" if signal.side == "BUY" else "SHORT"

        self.pos_mgr.open_position(
            symbol=signal.symbol,
            side=side,
            entry=signal.entry,
            qty=qty,
            sl=signal.sl,
            tp1=signal.tp1,
            tp2=signal.tp2,
            atr=signal.atr,
            leverage=lev_decision.leverage,
            mode=lev_decision.mode,
            strategy=signal.strategy,
            confidence=signal.confidence,
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

        return report

    def _report_by_strategy(self) -> Dict:
        result = {}
        for event in self.pos_mgr.trade_log:
            if event.action in ("SL", "TP1", "TP2", "TRAILING_STOP"):
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
            if event.action in ("SL", "TP1", "TP2", "TRAILING_STOP"):
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
            if event.action in ("SL", "TP1", "TP2", "TRAILING_STOP"):
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

    print("=" * 60)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--symbols", default="BTC,ETH,SOL", help="Comma-separated symbols")
    parser.add_argument("--days", type=int, default=30, help="Days of history")
    parser.add_argument("--strategies", default="", help="Comma-separated strategy names (empty=all)")
    parser.add_argument("--equity", type=float, default=10000, help="Starting equity")
    parser.add_argument("--output", default="", help="Save results to JSON file")
    args = parser.parse_args()

    config = TradingConfig()
    config.starting_equity = args.equity

    engine = BacktestEngine(config)
    symbols = [s.strip() for s in args.symbols.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()] or None

    report = engine.run(symbols, args.days, strategies)
    print_report(report)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
