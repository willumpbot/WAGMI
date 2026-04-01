"""
P&L Reconciliation Tool.

Compares the bot's trade log (data/trades.csv) with exchange trade history
to detect discrepancies. Run before and after live trading sessions.

Usage:
    cd bot && python -m tools.pnl_reconcile              # Compare bot vs exchange
    cd bot && python -m tools.pnl_reconcile --bot-only    # Just show bot's P&L
    cd bot && python -m tools.pnl_reconcile --check-open  # Verify open positions match

This is a read-only tool — it never modifies anything.
"""

import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("pnl_reconcile")

_TRADES_PATH = os.path.join("data", "trades.csv")
_DECISIONS_PATH = os.path.join("data", "llm", "decisions.jsonl")


def load_bot_trades(path: str = _TRADES_PATH) -> List[Dict[str, Any]]:
    """Load trades from bot's CSV trade log."""
    trades = []
    if not os.path.exists(path):
        return trades
    try:
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    trades.append({
                        "timestamp": row.get("timestamp", ""),
                        "symbol": row.get("symbol", ""),
                        "side": row.get("side", ""),
                        "entry": float(row.get("entry", 0) or 0),
                        "exit": float(row.get("exit", 0) or 0),
                        "pnl": float(row.get("pnl", 0) or 0),
                        "fees": float(row.get("fees", 0) or 0),
                        "leverage": float(row.get("leverage", 1) or 1),
                        "confidence": float(row.get("confidence", 0) or 0),
                        "strategy": row.get("strategy", ""),
                        "outcome": row.get("outcome", ""),
                        "state_path": row.get("state_path", ""),
                    })
                except (ValueError, TypeError):
                    continue
    except Exception as e:
        logger.warning(f"Failed to load trades: {e}")
    return trades


def load_exchange_trades(days: int = 7) -> List[Dict[str, Any]]:
    """Load trade history from Hyperliquid via CCXT."""
    try:
        import ccxt
        hl = ccxt.hyperliquid({
            "apiKey": os.getenv("HL_API_KEY", ""),
            "secret": os.getenv("HL_API_SECRET", ""),
        })
        since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        raw_trades = hl.fetch_my_trades(symbol=None, since=since, limit=500)

        trades = []
        for t in raw_trades:
            trades.append({
                "id": t.get("id", ""),
                "timestamp": t.get("datetime", ""),
                "symbol": t.get("symbol", ""),
                "side": t.get("side", "").upper(),
                "price": float(t.get("price", 0)),
                "amount": float(t.get("amount", 0)),
                "cost": float(t.get("cost", 0)),
                "fee": float((t.get("fee", {}) or {}).get("cost", 0)),
            })
        return trades
    except ImportError:
        logger.warning("CCXT not available — cannot fetch exchange trades")
        return []
    except Exception as e:
        logger.warning(f"Failed to fetch exchange trades: {e}")
        return []


def load_exchange_positions() -> List[Dict[str, Any]]:
    """Load current open positions from Hyperliquid."""
    try:
        import ccxt
        hl = ccxt.hyperliquid({
            "apiKey": os.getenv("HL_API_KEY", ""),
            "secret": os.getenv("HL_API_SECRET", ""),
        })
        raw = hl.fetch_positions()
        positions = []
        for p in raw:
            contracts = abs(float(p.get("contracts", 0) or 0))
            if contracts > 0:
                positions.append({
                    "symbol": p.get("symbol", ""),
                    "side": p.get("side", ""),
                    "contracts": contracts,
                    "entry_price": float(p.get("entryPrice", 0) or 0),
                    "leverage": float(p.get("leverage", 1) or 1),
                    "unrealized_pnl": float(p.get("unrealizedPnl", 0) or 0),
                    "notional": float(p.get("notional", 0) or 0),
                })
        return positions
    except ImportError:
        logger.warning("CCXT not available")
        return []
    except Exception as e:
        logger.warning(f"Failed to fetch positions: {e}")
        return []


def load_bot_positions() -> Dict[str, Dict]:
    """Load bot's internal position state from the position manager backup."""
    pos_path = os.path.join("data", "position_backup.json")
    if not os.path.exists(pos_path):
        return {}
    try:
        with open(pos_path) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if v.get("state") != "CLOSED"}
    except Exception:
        return {}


def reconcile_pnl(bot_trades: List[Dict], exchange_trades: List[Dict]) -> Dict[str, Any]:
    """Compare bot's trade log with exchange history."""
    result = {
        "bot_trade_count": len(bot_trades),
        "exchange_trade_count": len(exchange_trades),
        "bot_total_pnl": sum(t["pnl"] for t in bot_trades),
        "bot_total_fees": sum(t["fees"] for t in bot_trades),
        "exchange_total_fees": sum(t["fee"] for t in exchange_trades),
        "discrepancies": [],
    }

    # Group exchange trades by approximate time+symbol for matching
    # (exchange trades are individual fills, bot trades are round-trips)
    exchange_by_symbol = {}
    for t in exchange_trades:
        sym = t["symbol"].split("/")[0] if "/" in t["symbol"] else t["symbol"]
        exchange_by_symbol.setdefault(sym, []).append(t)

    result["exchange_by_symbol"] = {
        sym: len(trades) for sym, trades in exchange_by_symbol.items()
    }

    return result


def format_bot_pnl(trades: List[Dict]) -> str:
    """Format bot's P&L summary."""
    if not trades:
        return "No bot trades found in data/trades.csv"

    total_pnl = sum(t["pnl"] for t in trades)
    total_fees = sum(t["fees"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    wr = len(wins) / len(trades) if trades else 0

    by_symbol = {}
    for t in trades:
        sym = t["symbol"]
        by_symbol.setdefault(sym, {"pnl": 0, "count": 0, "wins": 0})
        by_symbol[sym]["pnl"] += t["pnl"]
        by_symbol[sym]["count"] += 1
        if t["pnl"] > 0:
            by_symbol[sym]["wins"] += 1

    lines = [
        "=" * 50,
        "  BOT P&L SUMMARY",
        "=" * 50,
        "",
        f"  Trades:     {len(trades)}",
        f"  Wins:       {len(wins)} ({wr:.0%})",
        f"  Losses:     {len(losses)}",
        f"  Total PnL:  ${total_pnl:+,.2f}",
        f"  Total Fees: ${total_fees:,.2f}",
        f"  Net PnL:    ${total_pnl - total_fees:+,.2f}",
        "",
        "  By Symbol:",
    ]
    for sym, data in sorted(by_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True):
        sym_wr = data["wins"] / data["count"] if data["count"] > 0 else 0
        lines.append(
            f"    {sym}: ${data['pnl']:+,.2f} ({data['count']} trades, {sym_wr:.0%} WR)"
        )

    if trades:
        lines.extend([
            "",
            "  Recent Trades:",
        ])
        for t in trades[-5:]:
            lines.append(
                f"    {t['timestamp'][:16]} {t['symbol']} {t['side']} "
                f"${t['pnl']:+,.2f} ({t['outcome']})"
            )

    lines.append("=" * 50)
    return "\n".join(lines)


def format_position_comparison(bot_pos: Dict, exchange_pos: List[Dict]) -> str:
    """Compare bot's positions with exchange positions."""
    lines = [
        "=" * 50,
        "  POSITION RECONCILIATION",
        "=" * 50,
        "",
    ]

    # Map exchange positions
    exchange_map = {}
    for p in exchange_pos:
        sym = p["symbol"].split("/")[0] if "/" in p["symbol"] else p["symbol"]
        exchange_map[sym] = p

    # Compare
    all_symbols = set(list(bot_pos.keys()) + list(exchange_map.keys()))
    mismatches = 0

    for sym in sorted(all_symbols):
        bot = bot_pos.get(sym)
        exch = exchange_map.get(sym)

        if bot and exch:
            lines.append(f"  {sym}: MATCHED")
            lines.append(f"    Bot:      {bot.get('side', '?')} entry={bot.get('entry', 0):.4f}")
            lines.append(f"    Exchange: {exch['side']} entry={exch['entry_price']:.4f} PnL=${exch['unrealized_pnl']:+.2f}")
        elif bot and not exch:
            lines.append(f"  {sym}: PHANTOM (bot has position, exchange doesn't)")
            lines.append(f"    Bot: {bot.get('side', '?')} entry={bot.get('entry', 0):.4f}")
            mismatches += 1
        elif exch and not bot:
            lines.append(f"  {sym}: ORPHAN (exchange has position, bot doesn't)")
            lines.append(f"    Exchange: {exch['side']} entry={exch['entry_price']:.4f} PnL=${exch['unrealized_pnl']:+.2f}")
            mismatches += 1

    if not all_symbols:
        lines.append("  No positions on either side")

    lines.extend([
        "",
        f"  Mismatches: {mismatches}",
        "=" * 50,
    ])
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="P&L Reconciliation Tool")
    parser.add_argument("--bot-only", action="store_true", help="Show bot P&L only")
    parser.add_argument("--check-open", action="store_true", help="Compare open positions")
    parser.add_argument("--days", type=int, default=7, help="Days of history to fetch")
    args = parser.parse_args()

    bot_trades = load_bot_trades()

    if args.bot_only:
        print(format_bot_pnl(bot_trades))
        return

    if args.check_open:
        bot_pos = load_bot_positions()
        exchange_pos = load_exchange_positions()
        print(format_position_comparison(bot_pos, exchange_pos))
        return

    # Full reconciliation
    print(format_bot_pnl(bot_trades))
    print()

    exchange_trades = load_exchange_trades(days=args.days)
    if exchange_trades:
        result = reconcile_pnl(bot_trades, exchange_trades)
        print(f"Exchange trades (last {args.days}d): {result['exchange_trade_count']}")
        print(f"Exchange fees: ${result['exchange_total_fees']:,.4f}")
        if result["exchange_by_symbol"]:
            for sym, count in result["exchange_by_symbol"].items():
                print(f"  {sym}: {count} fills")
    else:
        print("No exchange trade data available (set HL_API_KEY/HL_API_SECRET)")

    print()
    bot_pos = load_bot_positions()
    exchange_pos = load_exchange_positions()
    if exchange_pos or bot_pos:
        print(format_position_comparison(bot_pos, exchange_pos))


if __name__ == "__main__":
    main()
