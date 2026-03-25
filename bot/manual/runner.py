"""
Standalone Manual Sniper Signal Runner.

Runs independently from the main trading bot. Fetches market data,
evaluates strategies, runs the sniper filter, sends Telegram alerts,
and simulates a $100 account — all without touching the bot.

Usage:
    cd bot && python -m manual.runner              # Run continuously
    cd bot && python -m manual.runner --once       # Single scan then exit
    cd bot && python -m manual.runner --status     # Show sim status and exit

This is the main entry point for the manual sniper system.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# Ensure bot/ is on path
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

from manual.config import ManualSniperConfig
from manual.sniper_filter import ManualSniperFilter
from manual.alerts import ManualSniperAlerter, format_sniper_alert
from manual.simulator import SniperSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("manual.runner")


def _fetch_prices(fetcher, symbols):
    """Get current prices for all symbols."""
    prices = {}
    for sym in symbols:
        try:
            from trading_config import DEFAULT_SYMBOLS
            sym_cfg = DEFAULT_SYMBOLS.get(sym)
            if sym_cfg:
                p = fetcher.fetch_live_price(sym)
                if p and p > 0:
                    prices[sym] = p
        except Exception:
            pass
    return prices


_cached_ensemble = None
_cached_symbols = None

def _get_ensemble(symbols):
    """Get or create the cached strategy ensemble (avoids re-init every scan)."""
    global _cached_ensemble, _cached_symbols
    if _cached_ensemble is not None and _cached_symbols == set(symbols):
        return _cached_ensemble

    from trading_config import TradingConfig, DEFAULT_SYMBOLS
    from strategies.regime_trend import RegimeTrendStrategy
    from strategies.monte_carlo_zones import MonteCarloZonesStrategy
    from strategies.confidence_scorer import ConfidenceScorerStrategy
    from strategies.ensemble import EnsembleStrategy
    from data.strategy_weights import StrategyWeightManager

    config = TradingConfig()
    weight_mgr = StrategyWeightManager()
    sym_dict = {s: DEFAULT_SYMBOLS[s] for s in symbols if s in DEFAULT_SYMBOLS}

    strategies = []
    for StratCls in [RegimeTrendStrategy, MonteCarloZonesStrategy, ConfidenceScorerStrategy]:
        try:
            strategies.append(StratCls(symbols=sym_dict))
        except Exception as e:
            logger.debug(f"{StratCls.__name__} init: {e}")

    if not strategies:
        logger.warning("No strategies loaded")
        return None

    chop = None
    if config.enable_chop_detector:
        try:
            from strategies.chop_detector import ChopDetector
            chop = ChopDetector(threshold=config.chop_threshold)
        except Exception:
            pass

    ensemble = EnsembleStrategy(
        strategies=strategies,
        mode=config.ensemble_mode,
        min_votes=config.min_votes_required,
        weight_manager=weight_mgr,
        veto_ratio=config.veto_ratio,
        chop_detector=chop,
        confidence_floor=config.ensemble_confidence_floor,
    )
    ensemble.apply_config_disables(config)

    _cached_ensemble = ensemble
    _cached_symbols = set(symbols)
    return ensemble


def _run_strategies(fetcher, symbols):
    """Run the strategy ensemble on each symbol and return signals."""
    from trading_config import DEFAULT_SYMBOLS

    ensemble = _get_ensemble(symbols)
    if ensemble is None:
        return []

    timeframes = ["5m", "1h", "6h", "1d"]
    signals = []
    for sym in symbols:
        try:
            sym_cfg = DEFAULT_SYMBOLS.get(sym)
            if not sym_cfg:
                continue
            data = fetcher.fetch_multi_timeframe(sym, sym_cfg.coingecko_id, timeframes)
            if not data:
                continue
            if "1d" in data and "daily" not in data:
                data["daily"] = data["1d"]
            signal = ensemble.evaluate(sym, data)
            if signal is not None:
                signals.append(signal)
        except Exception as e:
            logger.debug(f"Strategy eval error for {sym}: {e}")

    return signals


def show_status():
    """Print current simulation status."""
    status_path = os.path.join("data", "manual", "sim_status.json")
    if os.path.exists(status_path):
        with open(status_path) as f:
            status = json.load(f)
        eq = status.get("current_equity", 100)
        start = status.get("starting_equity", 100)
        trades = status.get("total_trades", 0)
        wins = status.get("wins", 0)
        wr = status.get("win_rate", 0)
        pnl = status.get("total_pnl", 0)
        dd = status.get("max_drawdown_pct", 0)
        streak = status.get("current_streak", 0)
        open_pos = status.get("open_positions", [])

        growth = ((eq - start) / start * 100) if start > 0 else 0
        print(f"\n{'=' * 40}")
        print(f"  SNIPER SIMULATION STATUS")
        print(f"{'=' * 40}")
        print(f"  Account:  ${start:.2f} -> ${eq:.2f} ({growth:+.1f}%)")
        print(f"  Trades:   {trades} (W:{wins} L:{trades - wins})")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  PnL:      ${pnl:+.2f}")
        print(f"  Max DD:   {dd:.1f}%")
        print(f"  Streak:   {streak:+d}")
        if open_pos:
            print(f"\n  Open positions:")
            for p in open_pos:
                print(f"    {p.get('symbol', '?')} {p.get('side', '?')} @ {p.get('entry', 0):.4f} (lev {p.get('leverage', 0):.0f}x)")
        print(f"{'=' * 40}\n")
    else:
        print("\nNo simulation data yet. Run: python -m manual.runner\n")


def run_once(fetcher, sniper_filter, alerter, simulator, symbols):
    """Single scan cycle."""
    # Fetch prices
    prices = _fetch_prices(fetcher, symbols)
    if not prices:
        logger.warning("No prices available")
        return 0

    # Check simulator open positions against current prices
    if simulator:
        closed = simulator.check_positions(prices)
        if closed:
            for c in closed:
                logger.info(
                    f"[SIM] Closed {c.get('symbol', '?')} {c.get('side', '?')} "
                    f"PnL: ${c.get('pnl', 0):+.2f} | Equity: ${simulator._equity:.2f}"
                )

    # Run strategies
    signals = _run_strategies(fetcher, symbols)

    count = 0
    for signal in signals:
        # Run through sniper filter
        result = sniper_filter.evaluate(signal)
        if result is None:
            continue

        count += 1

        # Print to console
        try:
            msg = format_sniper_alert(result)
            print(f"\n{msg}\n")
        except Exception:
            logger.info(
                f"SNIPER: {result.tier} | {result.symbol} {result.side} | "
                f"conf={result.confidence:.0f}% lev={result.leverage:.0f}x | "
                f"+${result.pnl_scalp:.2f} / -${result.loss_amount:.2f}"
            )

        # Send Telegram alert
        try:
            alerter.send_sniper_alert(result)
        except Exception as e:
            logger.debug(f"Telegram alert failed: {e}")

        # Feed to simulator
        if simulator:
            try:
                simulator.on_signal(result)
            except Exception as e:
                logger.debug(f"Simulator error: {e}")

    return count


def main():
    parser = argparse.ArgumentParser(description="Manual Sniper Signal Runner")
    parser.add_argument("--once", action="store_true", help="Single scan then exit")
    parser.add_argument("--status", action="store_true", help="Show sim status and exit")
    parser.add_argument("--interval", type=int, default=90, help="Scan interval in seconds (default: 90, offset from bot's 60s)")
    parser.add_argument("--no-sim", action="store_true", help="Disable simulator")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram alerts")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # Initialize
    logger.info("Starting Manual Sniper Runner...")

    config = ManualSniperConfig()
    sniper_filter = ManualSniperFilter(config)
    alerter = ManualSniperAlerter(config) if not args.no_telegram else None

    # Simulator
    simulator = None
    if not args.no_sim:
        try:
            simulator = SniperSimulator(starting_equity=config.equity)
            logger.info(f"Simulator active: ${simulator._equity:.2f} equity")
        except Exception as e:
            logger.warning(f"Simulator init failed: {e}")

    # Data fetcher
    try:
        from data.fetcher import DataFetcher
        fetcher = DataFetcher()
        logger.info("Data fetcher initialized")
    except Exception as e:
        logger.error(f"Cannot initialize data fetcher: {e}")
        return

    symbols = config.preferred_symbols
    logger.info(f"Scanning symbols: {symbols}")
    logger.info(f"Mode: {config.mode} | Equity: ${config.equity} | Max leverage: {config.max_leverage}x")
    logger.info(f"Scan interval: {args.interval}s")

    if args.once:
        count = run_once(fetcher, sniper_filter, alerter, simulator, symbols)
        logger.info(f"Scan complete: {count} sniper signals")
        if simulator:
            show_status()
        return

    # Continuous loop
    logger.info("Running continuously. Ctrl+C to stop.")
    scan_count = 0
    signal_count = 0

    try:
        while True:
            scan_count += 1
            try:
                count = run_once(fetcher, sniper_filter, alerter, simulator, symbols)
                signal_count += count
                if count > 0:
                    logger.info(f"Scan #{scan_count}: {count} sniper signal(s) | Total: {signal_count}")
                else:
                    if scan_count % 10 == 0:
                        eq_str = f" | Sim: ${simulator._equity:.2f}" if simulator else ""
                        logger.info(f"Scan #{scan_count}: no signals{eq_str}")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.warning(f"Scan error: {e}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info(f"\nStopped. {scan_count} scans, {signal_count} signals.")
        if simulator:
            show_status()


if __name__ == "__main__":
    main()
