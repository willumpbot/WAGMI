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

    from data.db import init_db
    init_db()

    from trading_config import TradingConfig, DEFAULT_SYMBOLS
    from multi_strategy_main import MultiStrategyBot

    config = TradingConfig()
    symbols_str = ", ".join(DEFAULT_SYMBOLS.keys())

    print("=" * 60)
    print("NunuIRL Paper Trading")
    print("=" * 60)
    print(f"  Discord: {'configured' if config.discord_webhook else 'NOT SET (add DISCORD_WEBHOOK to .env)'}")
    print(f"  Telegram: {'configured' if config.telegram_token else 'NOT SET (add TELEGRAM_TOKEN to .env)'}")
    print(f"  Symbols: {symbols_str}")
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

    # LLM integration (opt-in)
    llm_integration = None
    use_llm = getattr(args, "llm", False)
    budget = getattr(args, "budget", 5.0)
    resume = getattr(args, "resume", False)

    if use_llm:
        from backtest.llm_integration import BacktestLLMIntegration
        llm_integration = BacktestLLMIntegration(
            budget_usd=budget,
            checkpoint_dir="data/backtest_checkpoints",
            resume=resume,
        )

    fresh_mode = getattr(args, "fresh", False)
    relaxed_cb = getattr(args, "relaxed_cb", False)
    yes_mode = getattr(args, "yes", False)
    engine = BacktestEngine(config, llm_integration=llm_integration, fresh=fresh_mode,
                            relaxed_cb=relaxed_cb, resume=resume, yes=yes_mode)

    raw_mode = getattr(args, "raw", False)
    if raw_mode:
        engine.enable_raw_mode()

    sim_agents = getattr(args, "sim_agents", False)
    if sim_agents:
        engine._sim_agents_enabled = True
        print("  Simulated LLM Agents: ENABLED (rule-based, no API)")
        print("  Pipeline: Regime → Trade (7-gate) → Risk → Critic")

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()] or None

    learn = getattr(args, "learn", False)
    if learn:
        print(f"Running backtest with LEARNING: {symbols} | {args.days} days | equity=${args.equity:,.0f}")
        print("  Results will feed: strategy weights, deep memory, feedback loop,")
        print("  self-teaching knowledge base, growth orchestrator, insight journal")
        if not use_llm:
            print("  Learning mode: LOCAL ONLY (no LLM API calls)")
    else:
        print(f"Running backtest: {symbols} | {args.days} days | equity=${args.equity:,.0f}")

    if raw_mode:
        print("  RAW MODE: Circuit breakers, notional caps, and position limits DISABLED")

    if relaxed_cb:
        print("  RELAXED CB: Using widened circuit breaker settings (15% daily / 30% drawdown)")

    if use_llm:
        print(f"  LLM Agents: ENABLED (budget=${budget:.2f})")
        print("  Pipeline: Regime -> Trade -> Risk -> Critic (entry)")
        print("  + Exit Agent (open positions) + Learning Agent (closed trades)")
        if resume:
            print("  Resume: from last checkpoint")
    elif resume:
        print("  Resume: from last checkpoint (simple mode)")

    report = engine.run(symbols, args.days, strategies, learn=learn, start_date=getattr(args, "start_date", "") or None)

    if report.get("error") == "preflight_failed":
        print("\nBACKTEST ABORTED: LLM preflight checks failed.")
        for err in report.get("errors", []):
            print(f"  ERROR: {err}")
        return

    if report.get("error") == "user_cancelled":
        print("\nBacktest cancelled by user.")
        return

    print_report(report)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")

    csv_path = getattr(args, "csv", "")
    if csv_path:
        from backtest.engine import export_trade_csv
        export_trade_csv(report, csv_path)
        print(f"Trade log exported to {csv_path}")


def cmd_signals(args):
    """One-shot signal check across all symbols."""
    from trading_config import TradingConfig, DEFAULT_SYMBOLS
    from data.fetcher import DataFetcher
    from strategies.regime_trend import RegimeTrendStrategy
    from strategies.monte_carlo_zones import MonteCarloZonesStrategy
    from strategies.confidence_scorer import ConfidenceScorerStrategy
    from strategies.multi_tier_quality import MultiTierQualityStrategy
    from strategies.funding_rate import FundingRateStrategy
    from strategies.oi_delta import OIDeltaStrategy
    from strategies.bollinger_squeeze import BollingerSqueezeStrategy
    from strategies.vmc_cipher import VMCCipherStrategy
    from strategies.lead_lag import LeadLagStrategy
    from strategies.liquidation_cascade import LiquidationCascadeStrategy
    from strategies.probability_engine import ProbabilityEngineStrategy
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
        FundingRateStrategy(DEFAULT_SYMBOLS),
        OIDeltaStrategy(DEFAULT_SYMBOLS),
        BollingerSqueezeStrategy(DEFAULT_SYMBOLS),
        VMCCipherStrategy(DEFAULT_SYMBOLS),
        LeadLagStrategy(DEFAULT_SYMBOLS),
        LiquidationCascadeStrategy(DEFAULT_SYMBOLS),
        ProbabilityEngineStrategy(DEFAULT_SYMBOLS),
    ]
    ensemble = EnsembleStrategy(strategies=strategies, mode=config.ensemble_mode, min_votes=config.min_votes_required, veto_ratio=config.veto_ratio)
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
            data = fetcher.fetch_multi_timeframe(symbol, sym_cfg.coingecko_id, needed_tfs)
            price = fetcher.latest_price(symbol, sym_cfg.coingecko_id)
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


def cmd_positions(args):
    """Show open positions and unrealized PnL."""
    from trading_config import TradingConfig, DEFAULT_SYMBOLS
    from data.fetcher import DataFetcher
    from multi_strategy_main import MultiStrategyBot

    config = TradingConfig()
    bot = MultiStrategyBot(config)

    open_pos = bot.pos_mgr.get_open_positions()
    if not open_pos:
        print("No open positions.")
        return

    print("=" * 80)
    print(f"Open Positions ({len(open_pos)})")
    print("=" * 80)

    prices = {}
    for symbol in open_pos.keys():
        sym_cfg = DEFAULT_SYMBOLS.get(symbol)
        if sym_cfg:
            price = bot.fetcher.latest_price(symbol, sym_cfg.coingecko_id)
            if price:
                prices[symbol] = price

    total_unrealized = 0.0
    for symbol, pos in open_pos.items():
        price = prices.get(symbol)
        if price:
            if pos.side == "LONG":
                unrealized = (price - pos.entry) * pos.qty * pos.leverage
            else:
                unrealized = (pos.entry - price) * pos.qty * pos.leverage
            total_unrealized += unrealized

            pct_move = ((price - pos.entry) / pos.entry * 100) if pos.side == "LONG" else ((pos.entry - price) / pos.entry * 100)
            print(
                f"  {symbol:10s} | {pos.side:5s} | "
                f"Entry: ${pos.entry:>12,.4f} | "
                f"Price: ${price:>12,.4f} | "
                f"Qty: {pos.qty:>10.4f} | "
                f"Lev: {pos.leverage:>4.1f}x | "
                f"Unrealized: ${unrealized:>10,.2f} | "
                f"Move: {pct_move:>+6.2f}%"
            )
            if pos.state != "CLOSED":
                print(f"    State: {pos.state_path_str} | SL: ${pos.sl:,.4f} | TP1: ${pos.tp1:,.4f} | TP2: ${pos.tp2:,.4f}")

    print("=" * 80)
    print(f"Total Unrealized PnL: ${total_unrealized:+,.2f}")
    print(f"Equity: ${bot.risk_mgr.equity:,.2f}")
    print("=" * 80)


def cmd_rl_train(args):
    """Train RL policy from transition buffer."""
    from rl.train_offline import train
    from rl.buffer import get_buffer_stats, load_buffer

    transitions = load_buffer()
    stats = get_buffer_stats(transitions)

    print("=" * 60)
    print("NunuIRL RL Offline Training")
    print("=" * 60)
    print(f"  Buffer transitions: {stats.get('total', 0)}")

    if stats.get("total", 0) == 0:
        print("  No transitions in buffer. Run paper trading first.")
        return

    print(f"  Avg reward: {stats.get('avg_reward', 0):.4f}")
    print(f"  Win rate: {stats.get('win_rate', 0):.1%}")
    print(f"  By regime: {json.dumps(stats.get('by_regime', {}), indent=4)}")
    print()

    policy = train()
    if policy:
        print("Training complete!")
        print(f"  Regime multipliers: {json.dumps(policy.get('regime_multipliers', {}), indent=4)}")
        print(f"  Symbol risk caps: {json.dumps(policy.get('symbol_risk_caps', {}), indent=4)}")
        print(f"  Policy saved to: data/rl/rl_policy.json")
        print()
        print("To enable: set ENABLE_RL_POLICY=true in .env")
    else:
        print("Training skipped (insufficient data).")


def cmd_status(args):
    """Show market assessment from all strategies without trading."""
    from trading_config import TradingConfig, DEFAULT_SYMBOLS
    from data.fetcher import DataFetcher
    from strategies.regime_trend import RegimeTrendStrategy
    from strategies.monte_carlo_zones import MonteCarloZonesStrategy
    from strategies.confidence_scorer import ConfidenceScorerStrategy
    from strategies.multi_tier_quality import MultiTierQualityStrategy
    from strategies.funding_rate import FundingRateStrategy
    from strategies.oi_delta import OIDeltaStrategy
    from strategies.bollinger_squeeze import BollingerSqueezeStrategy
    from strategies.vmc_cipher import VMCCipherStrategy
    from strategies.lead_lag import LeadLagStrategy
    from strategies.liquidation_cascade import LiquidationCascadeStrategy
    from strategies.probability_engine import ProbabilityEngineStrategy
    from strategies.ensemble import EnsembleStrategy

    config = TradingConfig()
    fetcher = DataFetcher(cache_ttl=60)

    strategies = [
        RegimeTrendStrategy(DEFAULT_SYMBOLS, config.htf_hours),
        MonteCarloZonesStrategy(DEFAULT_SYMBOLS),
        ConfidenceScorerStrategy(DEFAULT_SYMBOLS, data_dir="ml_data"),
        MultiTierQualityStrategy(DEFAULT_SYMBOLS),
        FundingRateStrategy(DEFAULT_SYMBOLS),
        OIDeltaStrategy(DEFAULT_SYMBOLS),
        BollingerSqueezeStrategy(DEFAULT_SYMBOLS),
        VMCCipherStrategy(DEFAULT_SYMBOLS),
        LeadLagStrategy(DEFAULT_SYMBOLS),
        LiquidationCascadeStrategy(DEFAULT_SYMBOLS),
        ProbabilityEngineStrategy(DEFAULT_SYMBOLS),
    ]
    ensemble = EnsembleStrategy(strategies=strategies, mode=config.ensemble_mode, min_votes=config.min_votes_required, veto_ratio=config.veto_ratio)
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
            data = fetcher.fetch_multi_timeframe(symbol, sym_cfg.coingecko_id, needed_tfs)
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
    # Fix Windows console encoding (cp1252 can't handle Unicode in log messages)
    if sys.platform == 'win32':
        for stream in [sys.stdout, sys.stderr]:
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='replace')

    # Load .env: bot/.env first (specific config), then root .env (fallback)
    # load_dotenv does NOT override existing vars, so first-loaded wins
    try:
        from dotenv import load_dotenv
        local_env = Path(__file__).parent / ".env"
        root_env = Path(__file__).parent.parent / ".env"
        if local_env.exists():
            load_dotenv(local_env)
        if root_env.exists():
            load_dotenv(root_env)
        if not local_env.exists() and not root_env.exists():
            load_dotenv()  # fallback to cwd
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
    sub_bt.add_argument("--symbols", default="HYPE,SOL,BTC", help="Comma-separated symbols")
    sub_bt.add_argument("--days", type=int, default=30, help="Days of history")
    sub_bt.add_argument("--strategies", default="", help="Strategy names (empty=all)")
    sub_bt.add_argument("--equity", type=float, default=10000, help="Starting equity")
    sub_bt.add_argument("--output", default="", help="Save JSON results to file")
    sub_bt.add_argument("--learn", action="store_true", help="Feed results into all learning systems (strategy weights, deep memory, feedback, knowledge base, growth)")
    sub_bt.add_argument("--llm", action="store_true", help="Enable LLM multi-agent pipeline during backtest (requires ANTHROPIC_API_KEY)")
    sub_bt.add_argument("--budget", type=float, default=5.0, help="Max LLM API spend in USD (default: $5)")
    sub_bt.add_argument("--resume", action="store_true", help="Resume LLM backtest from last checkpoint")
    sub_bt.add_argument("--yes", "-y", action="store_true", help="Skip interactive confirmation prompt (for scripted/parallel runs)")
    sub_bt.add_argument("--csv", default="", help="Export per-trade timeline to CSV file")
    sub_bt.add_argument("--raw", action="store_true", help="Disable circuit breakers, notional caps, and risk gates for raw strategy analysis")
    sub_bt.add_argument("--fresh", action="store_true", help="Force re-fetch data from exchanges, ignoring disk cache")
    sub_bt.add_argument("--relaxed-cb", action="store_true", help="Use relaxed circuit breaker settings (15%%/30%%) instead of live (5%%/10%%)")
    sub_bt.add_argument("--sim-agents", action="store_true", help="Enable simulated LLM agents (rule-based, no API) to filter signals")
    sub_bt.add_argument("--start-date", default="", help="Start main loop from this date (YYYY-MM-DD). Warmup still uses earlier data from --days window.")

    # Signals
    sub_sig = subparsers.add_parser("signals", help="One-shot signal check")
    sub_sig.add_argument("--symbols", default="", help="Comma-separated symbols (empty=all)")

    # Status
    sub_status = subparsers.add_parser("status", help="Market assessment")
    sub_status.add_argument("--symbols", default="", help="Comma-separated symbols (empty=all)")

    # Positions
    sub_pos = subparsers.add_parser("positions", help="Show open positions")

    # RL training
    sub_rl = subparsers.add_parser("rl-train", help="Train RL policy from buffer")

    args = parser.parse_args()

    if args.command == "paper":
        cmd_paper(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "signals":
        cmd_signals(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "positions":
        cmd_positions(args)
    elif args.command == "rl-train":
        cmd_rl_train(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
