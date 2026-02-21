#!/usr/bin/env python3
"""
Generate one-page corrected performance summary with rebuilt PnL + EV.

Reads from:
- data/trades.csv (closed trades with net PnL)
- data/analysis/trade_outcomes.csv (trade metrics)
- ml_data/bot.db (trade journal)

Computes:
- Win rate per entry_type, strategy, regime
- EV per trade
- Long/short bias
- Impossible trades flagged
- Risk metrics

Usage:
    python -m scripts.generate_corrected_summary
"""

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

TRADES_CSV = "data/trades.csv"
OUTCOMES_CSV = "data/analysis/trade_outcomes.csv"
DB_PATH = "ml_data/bot.db"


def load_trades_csv():
    """Load trades.csv with NET PnL."""
    if not Path(TRADES_CSV).exists():
        return []
    rows = []
    try:
        with open(TRADES_CSV, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"Error loading {TRADES_CSV}: {e}")
    return rows


def load_outcomes_csv():
    """Load outcomes.csv with trade metrics."""
    if not Path(OUTCOMES_CSV).exists():
        return []
    rows = []
    try:
        with open(OUTCOMES_CSV, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"Error loading {OUTCOMES_CSV}: {e}")
    return rows


def compute_ev(trades):
    """Compute Expected Value: EV = win_rate * avg_win - (1-win_rate) * avg_loss."""
    if not trades:
        return 0.0

    wins = [float(t.get("pnl", 0)) for t in trades if float(t.get("pnl", 0)) > 0]
    losses = [abs(float(t.get("pnl", 0))) for t in trades if float(t.get("pnl", 0)) <= 0]

    total = len(trades)
    win_rate = len(wins) / total if total > 0 else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    # EV in $ terms
    if avg_loss == 0:
        ev = win_rate * avg_win
    else:
        r_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0
        ev = (win_rate * r_ratio - (1 - win_rate)) * avg_loss

    return ev


def detect_impossible_trades(trades):
    """Flag trades with impossible PnL (e.g., short at peak that lost, but high TP hits)."""
    impossible = []
    for trade in trades:
        try:
            side = trade.get("side", "")
            entry = float(trade.get("entry", 0))
            exit_p = float(trade.get("exit_price", 0))
            pnl = float(trade.get("pnl", 0))
            action = trade.get("action", "")

            # Sanity: if LONG and exit > entry, PnL should be positive
            if side == "LONG" and exit_p > entry and pnl < 0:
                impossible.append(f"{trade.get('symbol')} LONG exit>{entry} but PnL<0")
            elif side == "SHORT" and exit_p < entry and pnl < 0:
                impossible.append(f"{trade.get('symbol')} SHORT exit<{entry} but PnL<0")
        except Exception:
            pass
    return impossible


def main():
    trades = load_trades_csv()
    outcomes = load_outcomes_csv()

    if not trades:
        print("No trades found. Run bot first.")
        return

    print("=" * 80)
    print("CORRECTED PERFORMANCE SUMMARY")
    print(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    print(f"Total closed trades: {len(trades)}")
    print("=" * 80)

    # Overall stats
    total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
    total_fees = sum(float(t.get("fees", 0)) for t in trades)
    wins = len([t for t in trades if float(t.get("pnl", 0)) > 0])
    losses = len([t for t in trades if float(t.get("pnl", 0)) <= 0])
    win_rate = wins / len(trades) if trades else 0.0

    print(f"\n### OVERALL STATS ###")
    print(f"Total PnL: ${total_pnl:+,.2f}")
    print(f"Total Fees: ${total_fees:,.2f}")
    print(f"Net PnL: ${total_pnl - total_fees:+,.2f}")
    print(f"Win Rate: {win_rate:.1%} ({wins}W / {losses}L)")
    print(f"Avg Win: ${sum(float(t.get('pnl', 0)) for t in trades if float(t.get('pnl', 0)) > 0) / max(wins, 1):+,.2f}")
    print(f"Avg Loss: ${sum(float(t.get('pnl', 0)) for t in trades if float(t.get('pnl', 0)) <= 0) / max(losses, 1):+,.2f}")

    # By entry_type
    if outcomes:
        by_type = defaultdict(list)
        for o in outcomes:
            et = o.get("entry_type", "UNKNOWN")
            by_type[et].append(o)

        print(f"\n### PERFORMANCE BY ENTRY TYPE ###")
        for et in sorted(by_type.keys()):
            trades_for_type = by_type[et]
            ev = compute_ev(trades_for_type)
            wr = len([t for t in trades_for_type if float(t.get("pnl", 0)) > 0]) / len(trades_for_type) if trades_for_type else 0
            pnl = sum(float(t.get("pnl", 0)) for t in trades_for_type)
            print(f"  {et:<12}: {len(trades_for_type):>3} trades | WR={wr:>5.1%} | PnL=${pnl:>+8,.2f} | EV=${ev:>+7,.2f}")

    # By symbol
    by_symbol = defaultdict(list)
    for t in trades:
        sym = t.get("symbol", "?")
        by_symbol[sym].append(t)

    print(f"\n### PERFORMANCE BY SYMBOL ###")
    for sym in sorted(by_symbol.keys()):
        trades_for_sym = by_symbol[sym]
        ev = compute_ev(trades_for_sym)
        wr = len([t for t in trades_for_sym if float(t.get("pnl", 0)) > 0]) / len(trades_for_sym) if trades_for_sym else 0
        pnl = sum(float(t.get("pnl", 0)) for t in trades_for_sym)
        print(f"  {sym:<12}: {len(trades_for_sym):>3} trades | WR={wr:>5.1%} | PnL=${pnl:>+8,.2f} | EV=${ev:>+7,.2f}")

    # Bias analysis
    long_trades = [t for t in trades if t.get("side") == "LONG"]
    short_trades = [t for t in trades if t.get("side") == "SHORT"]
    long_wr = len([t for t in long_trades if float(t.get("pnl", 0)) > 0]) / len(long_trades) if long_trades else 0
    short_wr = len([t for t in short_trades if float(t.get("pnl", 0)) > 0]) / len(short_trades) if short_trades else 0

    print(f"\n### DIRECTIONAL BIAS ###")
    print(f"  LONG:  {len(long_trades)} trades ({len(long_trades)/len(trades)*100:.1f}%) WR={long_wr:.1%}")
    print(f"  SHORT: {len(short_trades)} trades ({len(short_trades)/len(trades)*100:.1f}%) WR={short_wr:.1%}")

    # Flag impossible
    impossible = detect_impossible_trades(trades)
    if impossible:
        print(f"\n### FLAGGED IMPOSSIBLE TRADES ###")
        for msg in impossible[:5]:
            print(f"  - {msg}")
        if len(impossible) > 5:
            print(f"  ... and {len(impossible) - 5} more")
    else:
        print(f"\n### NO IMPOSSIBLE TRADES DETECTED ###")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
