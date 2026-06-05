#!/usr/bin/env python3
"""
Regime Validation & ETH Root Cause Analysis

Investigates:
1. Are illiquid regime detections actually correct?
2. Why is ETH losing -$2,909 (78% of losses)?
3. What separates profitable trending trades from losing illiquid trades?
4. Can we extract regime detection rules from winning vs losing trades?
"""

import csv
import json
from collections import defaultdict
from datetime import datetime

def load_trades(filepath):
    """Load trades from CSV."""
    trades = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                trades.append({
                    'timestamp': row.get('timestamp', ''),
                    'symbol': row.get('symbol', ''),
                    'side': row.get('side', ''),
                    'entry': float(row.get('entry', 0)),
                    'exit': float(row.get('exit', 0)),
                    'pnl': float(row.get('pnl', 0)),
                    'confidence': float(row.get('confidence', 0)),
                    'strategy': row.get('strategy', ''),
                    'regime': row.get('regime', ''),
                    'volatility_band': row.get('volatility_band', ''),
                    'leverage': float(row.get('leverage', 0)),
                })
            except (ValueError, TypeError):
                continue
    return trades

def analyze_regime_accuracy(trades):
    """Check if regime classifications correlate with outcomes."""
    regime_stats = defaultdict(lambda: {
        'wins': 0, 'losses': 0, 'total_pnl': 0, 'count': 0,
        'avg_conf': 0, 'avg_lev': 0
    })

    for t in trades:
        regime = t['regime'] or 'unknown'
        regime_stats[regime]['count'] += 1
        regime_stats[regime]['total_pnl'] += t['pnl']
        regime_stats[regime]['avg_conf'] += t['confidence']
        regime_stats[regime]['avg_lev'] += t['leverage']
        if t['pnl'] > 0:
            regime_stats[regime]['wins'] += 1
        else:
            regime_stats[regime]['losses'] += 1

    # Compute averages
    for regime in regime_stats:
        n = regime_stats[regime]['count']
        if n > 0:
            regime_stats[regime]['avg_conf'] /= n
            regime_stats[regime]['avg_lev'] /= n
            regime_stats[regime]['win_rate'] = regime_stats[regime]['wins'] / n

    return dict(regime_stats)

def analyze_eth_issue(trades):
    """Deep dive into why ETH is losing so much."""
    eth_trades = [t for t in trades if t['symbol'] == 'ETH']
    others = [t for t in trades if t['symbol'] != 'ETH']

    eth_by_regime = defaultdict(list)
    for t in eth_trades:
        eth_by_regime[t['regime']].append(t['pnl'])

    print("\n[ETH DEEP DIVE]")
    print(f"ETH trades: {len(eth_trades)} (total sample: {len(trades)})")
    print(f"ETH PnL: ${sum(t['pnl'] for t in eth_trades):.2f}")
    print(f"Non-ETH PnL: ${sum(t['pnl'] for t in others):.2f}")
    print(f"ETH as % of losses: {abs(sum(t['pnl'] for t in eth_trades)) / sum(abs(t['pnl']) for t in trades if t['pnl'] < 0) * 100:.1f}%")

    print("\nETH by regime:")
    for regime in sorted(eth_by_regime.keys()):
        trades_in_regime = eth_by_regime[regime]
        pnl = sum(trades_in_regime)
        wr = sum(1 for p in trades_in_regime if p > 0) / len(trades_in_regime)
        print(f"  {regime:15} {len(trades_in_regime):3} trades | PnL: ${pnl:>8.2f} | WR: {wr*100:>5.1f}%")

def analyze_confidence_vs_outcome(trades):
    """Check if confidence scores actually predict outcomes."""
    low_conf = [t for t in trades if t['confidence'] < 50]
    high_conf = [t for t in trades if t['confidence'] >= 50]

    print("\n[CONFIDENCE CALIBRATION]")
    print(f"Low confidence (<50): {len(low_conf)} trades")
    if low_conf:
        low_wr = sum(1 for t in low_conf if t['pnl'] > 0) / len(low_conf)
        low_pnl = sum(t['pnl'] for t in low_conf)
        print(f"  PnL: ${low_pnl:.2f}, WR: {low_wr*100:.1f}%")

    print(f"High confidence (>=50): {len(high_conf)} trades")
    if high_conf:
        high_wr = sum(1 for t in high_conf if t['pnl'] > 0) / len(high_conf)
        high_pnl = sum(t['pnl'] for t in high_conf)
        print(f"  PnL: ${high_pnl:.2f}, WR: {high_wr*100:.1f}%")

    # Are high confidence trades actually better?
    if low_conf and high_conf:
        low_avg = sum(t['pnl'] for t in low_conf) / len(low_conf)
        high_avg = sum(t['pnl'] for t in high_conf) / len(high_conf)
        if low_avg > high_avg:
            print(f"  WARNING: Low confidence trades ({low_avg:.2f} avg) beat high conf ({high_avg:.2f} avg)")

def analyze_leverage_correlation(trades):
    """Check if leverage is sized appropriately."""
    by_lev = defaultdict(list)
    for t in trades:
        lev_bucket = f"{int(t['leverage'])}x"
        by_lev[lev_bucket].append(t['pnl'])

    print("\n[LEVERAGE SIZING]")
    for lev in sorted(by_lev.keys(), key=lambda x: float(x[:-1])):
        pnls = by_lev[lev]
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        total_pnl = sum(pnls)
        print(f"  {lev:5} | {len(pnls):3} trades | PnL: ${total_pnl:>8.2f} | WR: {wr*100:>5.1f}%")

def main():
    trades = load_trades("./bot/data/trades.csv")
    print(f"Loaded {len(trades)} trades")

    # Run analyses
    regime_stats = analyze_regime_accuracy(trades)

    print("\n[REGIME ACCURACY]")
    for regime in sorted(regime_stats.keys(), key=lambda x: regime_stats[x]['total_pnl']):
        stats = regime_stats[regime]
        print(f"  {regime:15} | {stats['count']:3} | PnL: ${stats['total_pnl']:>8.2f} | "
              f"WR: {stats['win_rate']*100:>5.1f}% | Conf: {stats['avg_conf']:>5.1f} | Lev: {stats['avg_lev']:>4.1f}x")

    analyze_eth_issue(trades)
    analyze_confidence_vs_outcome(trades)
    analyze_leverage_correlation(trades)

    print("\n[SUMMARY]")
    print(f"Total trades: {len(trades)}")
    print(f"Total PnL: ${sum(t['pnl'] for t in trades):.2f}")
    print(f"Win rate: {sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100:.1f}%")

if __name__ == '__main__':
    main()
