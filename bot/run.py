#!/usr/bin/env python3
"""
NunuIRL Quick Launcher
Unified entry point for paper trading, backtesting, and signal monitoring.

Usage:
    python run.py paper           # Start paper trading (signals to Discord/Telegram)
    python run.py backtest        # Run backtest on BTC,ETH,SOL (30 days)
    python run.py backtest --symbols BTC,HYPE --days 60
    python run.py signals         # One-shot: check all symbols, print signals, exit
    python run.py status          # Show current market assessment for all symbols
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure bot/ is in path
sys.path.insert(0, str(Path(__file__).parent))


def cmd_paper(args):
    """Start paper trading with live signals."""
    os.makedirs("logs", exist_ok=True)
    os.makedirs("ml_data", exist_ok=True)

    from trading_config import TradingConfig
    from multi_strategy_main import MultiStrategyBot

    config = TradingConfig()

    print("=" * 60)
    print("NunuIRL Paper Trading")
    print("=" * 60)
    print(f"  Discord: {'configured' if config.discord_webhook else 'NOT SET (add DISCORD_WEBHOOK to .env)'}")
    print(f"  Telegram: {'configured' if config.telegram_token else 'NOT SET (add TELEGRAM_TOKEN to .env)'}")
    print(f"  Symbols: BTC, ETH, SOL, XRP, AVAX, HYPE, BNB, RENDER, JUP")
    print(f"  Strategies: 4 (regime_trend, monte_carlo, confidence, multi_tier)")
    print(f"  Leverage: {'enabled' if config.enable_leverage else 'disabled'} (max {config.max_leverage}x)")
    print(f"  ML: {'enabled' if config.enable_ml else 'disabled'}")
    print(f"  Trailing stop: {'enabled' if config.enable_trailing_stop else 'disabled'}")
    print(f"  Scan interval: {config.scan_interval_s}s")
    print("=" * 60)

    if not config.discord_webhook and not config.telegram_token:
        print("\nWARNING: No alert channels configured!")
        print("  Set DISCORD_WEBHOOK and/or TELEGRAM_TOKEN in .env")
        print("  Signals will only appear in logs/bot_*.log\n")

    bot = MultiStrategyBot(config)
    bot.run()


def cmd_backtest(args):
    """Run backtest on historical data."""
    from trading_config import TradingConfig
    from backtest.engine import BacktestEngine, print_report

    config = TradingConfig()
    config.starting_equity = args.equity

    engine = BacktestEngine(config)
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()] or None

    print(f"Running backtest: {symbols} | {args.days} days | equity=${args.equity:,.0f}")
    report = engine.run(symbols, args.days, strategies)
    print_report(report)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


def cmd_signals(args):
    """One-shot signal check across all symbols."""
    from trading_config import TradingConfig, DEFAULT_SYMBOLS
    from data.fetcher import DataFetcher
    from strategies.regime_trend import RegimeTrendStrategy
    from strategies.monte_carlo_zones import MonteCarloZonesStrategy
    from strategies.confidence_scorer import ConfidenceScorerStrategy
    from strategies.multi_tier_quality import MultiTierQualityStrategy
    from strategies.ensemble import EnsembleStrategy
    from execution.leverage import LeverageManager

    config = TradingConfig()
    fetcher = DataFetcher(cache_ttl=60)
    leverage_mgr = LeverageManager(enable_leverage=config.enable_leverage, max_leverage=config.max_leverage)

    strategies = [
        RegimeTrendStrategy(DEFAULT_SYMBOLS, config.htf_hours),
        MonteCarloZonesStrategy(DEFAULT_SYMBOLS),
        ConfidenceScorerStrategy(DEFAULT_SYMBOLS, data_dir="ml_data"),
        MultiTierQualityStrategy(DEFAULT_SYMBOLS),
    ]
    ensemble = EnsembleStrategy(strategies=strategies, mode=config.ensemble_mode, min_votes=config.min_votes_required)
    needed_tfs = ensemble.get_all_required_timeframes()

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(DEFAULT_SYMBOLS.keys())

    print("=" * 60)
    print(f"NunuIRL Signal Check | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    for symbol in symbols:
        sym_cfg = DEFAULT_SYMBOLS.get(symbol)
        if not sym_cfg:
            print(f"  {symbol}: unknown symbol, skipping")
            continue

        print(f"\n--- {symbol} ---")
        try:
            data = fetcher.fetch_multi_timeframe(sym_cfg.coingecko_id, needed_tfs)
            price = fetcher.latest_price(sym_cfg.coingecko_id)
            print(f"  Price: ${price:,.2f}" if price else "  Price: unavailable")

            signal = ensemble.evaluate(symbol, data)
            if signal:
                num_agree = signal.metadata.get("num_agree", 1)
                total = signal.metadata.get("total_strategies", 4)
                lev = leverage_mgr.decide(signal.confidence, num_agree, total, sym_cfg.risk_tier)

                print(f"  SIGNAL: {signal.side} | Confidence: {signal.confidence:.0f}%")
                print(f"  Leverage: {lev.leverage:.1f}x ({lev.tier})")
                print(f"  Entry: ${signal.entry:,.2f} | SL: ${signal.sl:,.2f}")
                print(f"  TP1: ${signal.tp1:,.2f} | TP2: ${signal.tp2:,.2f}")
                print(f"  Strategies: {signal.metadata.get('strategies_agree', [signal.strategy])}")
            else:
                print("  No signal (strategies disagree or all HOLD)")

        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 60)


def cmd_status(args):
    """Show market assessment from all strategies without trading."""
    from trading_config import TradingConfig, DEFAULT_SYMBOLS
    from data.fetcher import DataFetcher
    from strategies.regime_trend import RegimeTrendStrategy
    from strategies.monte_carlo_zones import MonteCarloZonesStrategy
    from strategies.confidence_scorer import ConfidenceScorerStrategy
    from strategies.multi_tier_quality import MultiTierQualityStrategy
    from strategies.ensemble import EnsembleStrategy

    config = TradingConfig()
    fetcher = DataFetcher(cache_ttl=60)

    strategies = [
        RegimeTrendStrategy(DEFAULT_SYMBOLS, config.htf_hours),
        MonteCarloZonesStrategy(DEFAULT_SYMBOLS),
        ConfidenceScorerStrategy(DEFAULT_SYMBOLS, data_dir="ml_data"),
        MultiTierQualityStrategy(DEFAULT_SYMBOLS),
    ]
    ensemble = EnsembleStrategy(strategies=strategies, mode=config.ensemble_mode, min_votes=config.min_votes_required)
    needed_tfs = ensemble.get_all_required_timeframes()

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(DEFAULT_SYMBOLS.keys())

    print("=" * 60)
    print(f"NunuIRL Market Status | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    for symbol in symbols:
        sym_cfg = DEFAULT_SYMBOLS.get(symbol)
        if not sym_cfg:
            continue

        print(f"\n=== {symbol} ===")
        try:
            data = fetcher.fetch_multi_timeframe(sym_cfg.coingecko_id, needed_tfs)
            statuses = ensemble.get_all_status(symbol, data)
            for s in statuses:
                strat = s.get("strategy", "?")
                print(f"  [{strat}]")
                for k, v in s.items():
                    if k not in ("symbol", "strategy"):
                        if isinstance(v, float):
                            print(f"    {k}: {v:.4f}")
                        else:
                            print(f"    {k}: {v}")
        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 60)


def main():
    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="NunuIRL Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  paper      Start paper trading with live signals to Discord/Telegram
  backtest   Run historical backtest
  signals    One-shot signal check (print and exit)
  status     Show market assessment from all strategies
        """,
    )
    subparsers = parser.add_subparsers(dest="command")

    # Paper trading
    sub_paper = subparsers.add_parser("paper", help="Start paper trading")

    # Backtest
    sub_bt = subparsers.add_parser("backtest", help="Run backtest")
    sub_bt.add_argument("--symbols", default="BTC,ETH,SOL", help="Comma-separated symbols")
    sub_bt.add_argument("--days", type=int, default=30, help="Days of history")
    sub_bt.add_argument("--strategies", default="", help="Strategy names (empty=all)")
    sub_bt.add_argument("--equity", type=float, default=10000, help="Starting equity")
    sub_bt.add_argument("--output", default="", help="Save JSON results to file")

    # Signals
    sub_sig = subparsers.add_parser("signals", help="One-shot signal check")
    sub_sig.add_argument("--symbols", default="", help="Comma-separated symbols (empty=all)")

    # Status
    sub_status = subparsers.add_parser("status", help="Market assessment")
    sub_status.add_argument("--symbols", default="", help="Comma-separated symbols (empty=all)")

    args = parser.parse_args()

    if args.command == "paper":
        cmd_paper(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "signals":
        cmd_signals(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
