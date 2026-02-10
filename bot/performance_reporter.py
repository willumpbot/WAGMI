#!/usr/bin/env python
"""
Quick performance report for paper trading.

Usage:
    python performance_reporter.py              # Latest report
    python performance_reporter.py --period 7   # Last 7 days
    python performance_reporter.py --symbol BTC # Filter by symbol
"""

import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd


def load_latest_trades(log_dir: str = "paper_trades") -> Optional[pd.DataFrame]:
    """Load the latest trades CSV file."""
    trades_dir = Path(log_dir)
    if not trades_dir.exists():
        print(f"❌ No trades directory found at {log_dir}")
        return None

    trades_files = sorted(list(trades_dir.glob("trades_*.csv")))
    if not trades_files:
        print(f"❌ No trades found in {log_dir}")
        return None

    latest = trades_files[-1]
    print(f"📁 Loading: {latest.name}")

    df = pd.read_csv(latest)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def print_quick_stats(df: Optional[pd.DataFrame], symbol_filter: Optional[str] = None, days: Optional[int] = None):
    """Print quick performance stats."""
    if df is None or df.empty:
        print("❌ No trade data available")
        return

    # Filter by date if specified
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        df = df[df["timestamp"] >= cutoff]

    # Filter by symbol if specified
    if symbol_filter:
        df = df[df["symbol"] == symbol_filter.upper()]
        if df.empty:
            print(f"❌ No trades found for {symbol_filter}")
            return

    # Only count closed trades
    closed = df[df["action"].isin(["TP1", "TP2", "SL", "TRAILING_STOP"])]
    if closed.empty:
        print("⚠️  No closed trades yet")
        return

    # Calculate stats
    total = len(closed)
    wins = len(closed[closed["pnl"] > 0])
    losses = len(closed[closed["pnl"] < 0])
    breakeven = len(closed[closed["pnl"] == 0])

    total_pnl = closed["pnl"].sum()
    total_fees = closed["fee"].sum()
    net_pnl = total_pnl - total_fees

    win_rate = wins / total * 100 if total > 0 else 0

    print("\n" + "=" * 60)
    print("PAPER TRADING PERFORMANCE")
    if symbol_filter:
        print(f"Symbol: {symbol_filter.upper()}")
    if days:
        print(f"Period: Last {days} days")
    print("=" * 60)

    print(f"\n📊 RESULTS:")
    print(f"  Closed Trades: {total}")
    print(f"  Wins: {wins} | Losses: {losses} | Break-even: {breakeven}")
    print(f"  Win Rate: {win_rate:.1f}%")

    print(f"\n💰 PNL:")
    print(f"  Gross P&L: ${total_pnl:+.2f}")
    print(f"  Fees Paid: ${total_fees:.2f}")
    print(f"  Net P&L: ${net_pnl:+.2f}")

    if wins > 0:
        avg_win = closed[closed["pnl"] > 0]["pnl"].mean()
        print(f"  Avg Win: ${avg_win:.2f}")

    if losses > 0:
        avg_loss = closed[closed["pnl"] < 0]["pnl"].mean()
        print(f"  Avg Loss: ${avg_loss:.2f}")
        if wins > 0:
            profit_factor = abs(sum(closed[closed["pnl"] > 0]["pnl"]) / sum(closed[closed["pnl"] < 0]["pnl"]))
            print(f"  Profit Factor: {profit_factor:.2f}x")

    # By symbol
    print(f"\n📈 BY SYMBOL:")
    for sym in sorted(closed["symbol"].unique()):
        sym_trades = closed[closed["symbol"] == sym]
        sym_wins = len(sym_trades[sym_trades["pnl"] > 0])
        sym_wr = sym_wins / len(sym_trades) * 100 if sym_trades.size > 0 else 0
        sym_pnl = sym_trades["pnl"].sum()
        print(f"  {sym}: {len(sym_trades)} trades | {sym_wr:.1f}% WR | P&L: ${sym_pnl:+.2f}")

    # By exit type
    print(f"\n🚪 BY EXIT TYPE:")
    for action in sorted(closed["action"].unique()):
        act_trades = closed[closed["action"] == action]
        act_wins = len(act_trades[act_trades["pnl"] > 0])
        act_wr = act_wins / len(act_trades) * 100 if len(act_trades) > 0 else 0
        act_pnl = act_trades["pnl"].mean()
        print(f"  {action}: {len(act_trades)} | {act_wr:.1f}% WR | Avg P&L: ${act_pnl:+.2f}")

    print("\n" + "=" * 60)
    print(f"Data: {closed['timestamp'].min()} to {closed['timestamp'].max()}")
    print("=" * 60 + "\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Quick paper trading performance report")
    parser.add_argument("--symbol", default=None, help="Filter by symbol (e.g., BTC, ETH)")
    parser.add_argument("--period", type=int, default=None, help="Last N days (default: all)")
    parser.add_argument("--dir", default="paper_trades", help="Trade logs directory")

    args = parser.parse_args()

    df = load_latest_trades(args.dir)
    print_quick_stats(df, symbol_filter=args.symbol, days=args.period)


if __name__ == "__main__":
    main()
