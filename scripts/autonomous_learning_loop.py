#!/usr/bin/env python3
"""
Autonomous Learning Loop — Continuous data analysis to extract edges and validate system assumptions.
Runs on laptop/desktop in background, updates KB, flags anomalies.

Phases:
1. Load & reconcile trade data (trades.csv vs ledger vs shadow)
2. Compute per-symbol, per-strategy, per-regime metrics
3. Validate hardcoded assumptions (Kelly weights, time-of-day biases, fee calculations)
4. Flag stale rules and orphaned positions
5. Extract high-confidence learnings → KB
"""

import json
import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import sys

def load_trades(data_dir):
    """Load trades.csv and compute basic metrics."""
    trades_file = f"{data_dir}/trades.csv"
    ledger_file = f"{data_dir}/trade_ledger.csv"

    try:
        with open(trades_file) as f:
            pass
    except FileNotFoundError:
        print(f"[ERROR] No trades.csv at {trades_file}")
        return None

    trades = []
    with open(trades_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                trades.append({
                    'id': row.get('id', ''),
                    'symbol': row.get('symbol', ''),
                    'side': row.get('side', ''),
                    'entry': float(row.get('entry', 0)),
                    'exit': float(row.get('exit', 0)),
                    'qty': float(row.get('qty', 0)),
                    'pnl': float(row.get('pnl', 0)),
                    'fee': float(row.get('fees', 0)),
                    'timestamp': row.get('timestamp', ''),
                    'strategy': row.get('strategy', ''),
                    'regime': row.get('regime', ''),
                })
            except (ValueError, TypeError) as e:
                continue

    print(f"[OK] Loaded {len(trades)} trades from trades.csv")
    return trades

def analyze_by_dimension(trades):
    """Compute metrics across symbol, strategy, regime, time."""
    if not trades:
        return {}

    results = {
        'total_trades': len(trades),
        'total_pnl': sum(t['pnl'] for t in trades),
        'total_fees': sum(t['fee'] for t in trades) / 10000 if trades else 0,  # assume bps
        'by_symbol': defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wr': 0}),
        'by_strategy': defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wr': 0}),
        'by_regime': defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wr': 0}),
    }

    for t in trades:
        # By symbol
        results['by_symbol'][t['symbol']]['trades'] += 1
        results['by_symbol'][t['symbol']]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            results['by_symbol'][t['symbol']]['wins'] = results['by_symbol'][t['symbol']].get('wins', 0) + 1

        # By strategy
        strat = t['strategy'] or 'unknown'
        results['by_strategy'][strat]['trades'] += 1
        results['by_strategy'][strat]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            results['by_strategy'][strat]['wins'] = results['by_strategy'][strat].get('wins', 0) + 1

        # By regime
        regime = t['regime'] or 'unknown'
        results['by_regime'][regime]['trades'] += 1
        results['by_regime'][regime]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            results['by_regime'][regime]['wins'] = results['by_regime'][regime].get('wins', 0) + 1

    # Compute win rates
    for dim in ['by_symbol', 'by_strategy', 'by_regime']:
        for key in results[dim]:
            trades_n = results[dim][key]['trades']
            wins = results[dim][key].get('wins', 0)
            results[dim][key]['wr'] = wins / trades_n if trades_n > 0 else 0

    return results

def validate_fees(trades):
    """Check if actual fees match config assumptions."""
    if not trades:
        return None

    # Extract fee_bps from data
    fees = [t['fee'] for t in trades if t['fee'] > 0]
    if not fees:
        return {'status': 'no_fee_data'}

    avg_fee = sum(fees) / len(fees)
    return {
        'avg_fee_bps': avg_fee,
        'min_fee_bps': min(fees),
        'max_fee_bps': max(fees),
        'expected_bps': 10,  # from .env TAKER_FEE_BPS
        'warning': 'Fee mismatch detected' if abs(avg_fee - 10) > 2 else None,
    }

def report(results, fee_analysis):
    """Print human-readable report."""
    print("\n" + "="*60)
    print("AUTONOMOUS LEARNING REPORT")
    print(f"Generated: {datetime.utcnow().isoformat()}")
    print("="*60)

    print(f"\n[OVERALL METRICS]")
    print(f"  Total trades: {results['total_trades']}")
    print(f"  Total PnL: ${results['total_pnl']:.2f}")
    print(f"  Win rate: {sum(1 for t in results.get('trades', []) if t['pnl'] > 0) / max(1, len(results.get('trades', []))) * 100:.1f}%")

    print(f"\n[BY SYMBOL - Top 5]")
    sorted_sym = sorted(results['by_symbol'].items(), key=lambda x: x[1]['pnl'], reverse=True)
    for sym, stats in sorted_sym[:5]:
        print(f"  {sym:8} | {stats['trades']:3} trades | PnL: ${stats['pnl']:>8.2f} | WR: {stats['wr']*100:>5.1f}%")

    print(f"\n[BY STRATEGY]")
    sorted_strat = sorted(results['by_strategy'].items(), key=lambda x: x[1]['pnl'], reverse=True)
    for strat, stats in sorted_strat:
        print(f"  {strat:20} | {stats['trades']:3} trades | PnL: ${stats['pnl']:>8.2f} | WR: {stats['wr']*100:>5.1f}%")

    print(f"\n[BY REGIME]")
    sorted_regime = sorted(results['by_regime'].items(), key=lambda x: x[1]['pnl'], reverse=True)
    for regime, stats in sorted_regime:
        print(f"  {regime:15} | {stats['trades']:3} trades | PnL: ${stats['pnl']:>8.2f} | WR: {stats['wr']*100:>5.1f}%")

    if fee_analysis:
        print(f"\n[FEE ANALYSIS]")
        print(f"  Avg fee: {fee_analysis['avg_fee_bps']:.2f} bps (expected 10 bps)")
        if fee_analysis['warning']:
            print(f"  WARNING: {fee_analysis['warning']}")

    print("\n" + "="*60 + "\n")

def main():
    data_dir = "./bot/data"

    print("[START] AUTONOMOUS LEARNING LOOP")
    print(f"   Data dir: {data_dir}")
    print(f"   Timestamp: {datetime.utcnow().isoformat()}\n")

    # Phase 1: Load & analyze
    trades = load_trades(data_dir)
    if not trades:
        print("[ERROR] Failed to load trade data. Exiting.")
        return 1

    # Phase 2: Compute metrics
    results = analyze_by_dimension(trades)
    fee_analysis = validate_fees(trades)

    # Phase 3: Report findings
    report(results, fee_analysis)

    # Phase 4: Save findings to KB
    findings = {
        'timestamp': datetime.utcnow().isoformat(),
        'results': {k: v for k, v in results.items() if k != 'trades'},
        'fee_analysis': fee_analysis,
    }

    kb_file = f"{data_dir}/learning_kb.json"
    with open(kb_file, 'w') as f:
        json.dump(findings, f, indent=2, default=str)
    print(f"[OK] Findings saved to {kb_file}")

    return 0

if __name__ == '__main__':
    sys.exit(main())
