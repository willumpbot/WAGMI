"""
CLI entrypoint for the WAGMI trading bot.

Usage:
    python cli.py                    # Paper trading (default)
    python cli.py --mode paper       # Explicit paper mode
    python cli.py --mode replay      # Replay mode (analyze trade logs)
    python cli.py --mode live        # Live trading (requires confirmation)
    python cli.py --mode evolve      # Strategy evolution report (daily review)
    python cli.py --mode tiers       # Show LLM usage tier comparison

Paper mode: Uses live feeds, simulates fills, logs identical schema to live.
Replay mode: Runs replay engine against trade logs, outputs anomaly report.
Evolve mode: Generates the Strategy Evolution Report — the student's daily journal.
Tiers mode: Shows LLM usage tier comparison and current configuration.
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
        ),
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["paper", "replay", "live"],
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

    args = parser.parse_args()

    if args.mode == "replay":
        _run_replay(args.replay_file)
    elif args.mode == "live":
        _run_live(args.yes)
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


if __name__ == "__main__":
    main()
