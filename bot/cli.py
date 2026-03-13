"""
CLI entrypoint for the WAGMI trading bot.

Usage:
    python cli.py                    # Paper trading (default)
    python cli.py --mode paper       # Explicit paper mode
    python cli.py --mode replay      # Replay mode (analyze trade logs)
    python cli.py --mode live        # Live trading (requires confirmation)
    python cli.py --mode evolve      # Strategy evolution report (daily review)
    python cli.py --mode tiers       # Show LLM usage tier comparison
    python cli.py --mode optimize    # Run parameter optimizer (grid/random search)

Paper mode: Uses live feeds, simulates fills, logs identical schema to live.
Replay mode: Runs replay engine against trade logs, outputs anomaly report.
Evolve mode: Generates the Strategy Evolution Report — the student's daily journal.
Tiers mode: Shows LLM usage tier comparison and current configuration.
Optimize mode: Run parameter optimization against historical backtests.
Live mode: Real execution on Hyperliquid. Requires confirmation.
"""

import argparse
import os
import sys
import logging

logger = logging.getLogger("bot.cli")


def main():
    parser = argparse.ArgumentParser(
        description="WAGMI Multi-Strategy Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modes:\n"
            "  paper   - Paper trading with live data (default, safe)\n"
            "  replay  - Replay trade logs and detect anomalies\n"
            "  live    - Real money trading (requires confirmation)\n"
            "  evolve  - Strategy evolution report (daily review)\n"
            "  tiers   - Show LLM usage tier comparison\n"
        ),
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["paper", "replay", "live", "evolve", "tiers", "optimize", "compare", "walkforward", "gate"],
        default="paper",
        help="Trading mode (default: paper)",
    )
    parser.add_argument(
        "--replay-file",
        default=None,
        help="CSV file to replay (replay mode only)",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompts (use with caution)",
    )
    parser.add_argument(
        "--symbols",
        default="BTC,ETH,SOL",
        help="Comma-separated symbols for optimize mode (default: BTC,ETH,SOL)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of history for optimize mode (default: 30)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=100,
        help="Number of trials for optimize mode (default: 100)",
    )
    parser.add_argument(
        "--metric",
        default="sharpe",
        choices=["sharpe", "total_pnl", "win_rate", "total_return_pct"],
        help="Optimization metric (default: sharpe)",
    )
    parser.add_argument(
        "--modes",
        default="0,2,3,5",
        help="Comma-separated LLM modes for compare mode (default: 0,2,3,5)",
    )

    args = parser.parse_args()

    if args.mode == "replay":
        _run_replay(args.replay_file)
    elif args.mode == "live":
        _run_live(args.yes)
    elif args.mode == "compare":
        _run_compare(args.symbols, args.days, args.modes)
    elif args.mode == "walkforward":
        _run_walkforward(args.symbols, args.days)
    elif args.mode == "evolve":
        _run_evolve()
    elif args.mode == "tiers":
        _run_tiers()
    elif args.mode == "optimize":
        _run_optimize(args.symbols, args.days, args.trials, args.metric)
    elif args.mode == "gate":
        _run_gate()
    else:
        _run_paper()


def _run_paper():
    """Paper trading mode - safe default."""
    os.environ.setdefault("ENVIRONMENT", "paper")
    logger.info("Starting in PAPER mode (simulated fills, live data)")
    from multi_strategy_main import MultiStrategyBot
    from trading_config import TradingConfig
    config = TradingConfig()
    bot = MultiStrategyBot(config)
    bot.run()


def _run_live(skip_confirm: bool = False):
    """Live trading mode - requires confirmation."""
    if not skip_confirm:
        print("=" * 60)
        print("WARNING: LIVE TRADING MODE")
        print("This will execute REAL trades with REAL money on Hyperliquid.")
        print("=" * 60)
        print()
        print("Pre-flight checks:")
        print("  1. API keys configured")
        print("  2. Risk limits set (check RISK_PER_TRADE, MAX_OPEN_POSITIONS)")
        print("  3. Circuit breaker configured")
        print("  4. Telegram alerts configured")
        print("  5. Paper trading results reviewed")
        print()
        confirm = input("Type 'CONFIRM LIVE' to proceed: ").strip()
        if confirm != "CONFIRM LIVE":
            print("Aborted. Use --mode paper for safe testing.")
            sys.exit(0)

    os.environ["ENVIRONMENT"] = "production"
    logger.info("Starting in LIVE mode - REAL MONEY")
    from multi_strategy_main import MultiStrategyBot
    from trading_config import TradingConfig
    config = TradingConfig()
    bot = MultiStrategyBot(config)
    bot.run()


def _run_replay(replay_file: str = None):
    """Replay mode - analyze trade logs."""
    from engine.replay_engine import replay_from_csv, format_replay_report

    if replay_file is None:
        # Try default locations
        candidates = [
            os.path.join("data", "analysis", "trade_candidates.csv"),
            os.path.join("data", "logs", "trades_enhanced.csv"),
            os.path.join("data", "trades.csv"),
        ]
        for path in candidates:
            if os.path.exists(path):
                replay_file = path
                break

    if not replay_file or not os.path.exists(replay_file):
        print("No trade log found for replay.")
        print("Specify a file: python cli.py --mode replay --replay-file path/to/trades.csv")
        sys.exit(1)

    print(f"Replaying: {replay_file}")
    print("-" * 60)

    result = replay_from_csv(replay_file)
    report = format_replay_report(result)
    print(report)

    print("-" * 60)
    summary = result.summary()
    print(f"\nTotal anomalies: {summary['total_anomalies']}")

    if result.anomalies:
        print("\nAll anomalies:")
        for a in result.anomalies:
            print(f"  [{a.severity:8s}] {a.anomaly_type:20s} | {a.symbol:6s} | {a.description}")

    # Exit code: non-zero if critical anomalies found
    high = sum(1 for a in result.anomalies if a.severity == "high")
    if high > 0:
        print(f"\n{high} HIGH severity anomalies found.")
        sys.exit(1)
    else:
        print("\nNo high severity anomalies.")
        sys.exit(0)


def _run_evolve():
    """Strategy evolution report — the student's daily journal."""
    from feedback.evolution_tracker import EvolutionTracker
    tracker = EvolutionTracker("data")
    report = tracker.generate_report()
    print(tracker.format_report(report))


def _run_tiers():
    """Show LLM usage tier comparison and current configuration."""
    from llm.usage_tiers import format_tier_comparison
    print(format_tier_comparison())


def _run_walkforward(symbols_str: str, days: int):
    """Run walk-forward validation to detect overfitting."""
    from backtest.walk_forward import WalkForwardRunner

    symbols = [s.strip() for s in symbols_str.split(",")]

    print("=" * 70)
    print(f"WALK-FORWARD VALIDATION: {', '.join(symbols)} | {days} days")
    print("=" * 70)
    print()

    runner = WalkForwardRunner(symbols=symbols, total_days=days)
    report = runner.run()
    print(runner.format_report(report))


def _run_compare(symbols_str: str, days: int, modes_str: str):
    """Run mode comparison: A/B test LLM autonomy levels."""
    from backtest.mode_comparison import ModeComparisonRunner

    symbols = [s.strip() for s in symbols_str.split(",")]
    modes = [int(m.strip()) for m in modes_str.split(",")]

    print("=" * 70)
    print(f"MODE COMPARISON: {', '.join(symbols)} | {days} days")
    print(f"Modes: {modes}")
    print("=" * 70)
    print()

    runner = ModeComparisonRunner(symbols=symbols, days=days, modes=modes)
    report = runner.run()
    print(runner.format_report(report))


def _run_optimize(symbols_str: str, days: int, max_trials: int, metric: str):
    """Run parameter optimization against historical backtests."""
    from optimization.param_optimizer import (
        ParameterOptimizer,
        create_backtest_fn,
        STRATEGY_PARAM_SPACES,
        TIMEFRAME_WEIGHT_SPACES,
    )

    symbols = [s.strip() for s in symbols_str.split(",")]

    print("=" * 60)
    print("PARAMETER OPTIMIZER")
    print("=" * 60)
    print(f"  Symbols:    {', '.join(symbols)}")
    print(f"  Days:       {days}")
    print(f"  Max trials: {max_trials}")
    print(f"  Metric:     {metric}")
    print("=" * 60)

    # Phase 1: Strategy params (ATR, confidence, veto, min_votes)
    print("\n[1/3] Optimizing strategy parameters...")
    bt_fn = create_backtest_fn(symbols=symbols, days=days)
    optimizer = ParameterOptimizer(bt_fn)
    strat_result = optimizer.grid_search(
        STRATEGY_PARAM_SPACES, metric=metric, max_trials=max_trials,
    )
    print(f"  Best {metric}: {strat_result.best_score:.4f}")
    print(f"  Best params: {strat_result.best_params}")
    print(f"  Trials: {strat_result.total_trials} in {strat_result.duration_s:.1f}s")

    # Phase 2: Timeframe weights
    print("\n[2/3] Optimizing timeframe weights...")
    tf_result = optimizer.grid_search(
        TIMEFRAME_WEIGHT_SPACES, metric=metric, max_trials=max_trials,
    )
    print(f"  Best {metric}: {tf_result.best_score:.4f}")
    print(f"  Best params: {tf_result.best_params}")
    print(f"  Trials: {tf_result.total_trials} in {tf_result.duration_s:.1f}s")

    # Phase 3: Sensitivity analysis on best params
    print("\n[3/3] Running sensitivity analysis...")
    combined_best = {**strat_result.best_params, **tf_result.best_params}
    all_spaces = {**STRATEGY_PARAM_SPACES, **TIMEFRAME_WEIGHT_SPACES}
    sensitivity = optimizer.sensitivity_analysis(combined_best, all_spaces, metric=metric)

    print("\n" + "=" * 60)
    print("SENSITIVITY ANALYSIS")
    print("=" * 60)
    for param, results in sensitivity.items():
        scores = [s for _, s in results if s > float("-inf")]
        if scores:
            spread = max(scores) - min(scores)
            best_val = max(results, key=lambda t: t[1])[0]
            print(f"  {param:25s} | spread={spread:.4f} | best={best_val}")

    print("\n" + "=" * 60)
    print("COMBINED OPTIMAL PARAMETERS")
    print("=" * 60)
    for k, v in combined_best.items():
        print(f"  {k:25s} = {v}")
    print("=" * 60)

    # Save results
    import json
    output_path = os.path.join("data", "optimization_results.json")
    os.makedirs("data", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "best_strategy_params": strat_result.best_params,
            "best_strategy_score": strat_result.best_score,
            "best_tf_params": tf_result.best_params,
            "best_tf_score": tf_result.best_score,
            "combined": combined_best,
            "metric": metric,
            "symbols": symbols,
            "days": days,
        }, f, indent=2)
    print(f"\nResults saved to {output_path}")


def _run_gate():
    """Run go-live gate evaluation and print results."""
    from validation.go_live_gate import GoLiveGate
    from feedback.trade_ledger import TradeLedger

    print("=" * 60)
    print("  GO-LIVE GATE EVALUATION")
    print("=" * 60)

    try:
        ledger = TradeLedger("data")
    except Exception:
        ledger = None

    ic_tracker = None
    try:
        from feedback.ic_tracker import ICTracker
        ic_tracker = ICTracker(data_dir="data")
    except Exception:
        pass

    gate = GoLiveGate(trade_ledger=ledger, ic_tracker=ic_tracker)
    result = gate.evaluate()
    print(gate.format_report(result))

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
