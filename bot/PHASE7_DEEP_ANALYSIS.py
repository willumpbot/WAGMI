"""
PHASE 7: Deep Trade Analysis - Find What Actually Works
========================================================
Instead of guessing optimizations, measure what's profitable in the data.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass

@dataclass
class Trade:
    symbol: str
    side: str
    leverage: float
    confidence: float
    regime: str
    pnl: float
    fees: float
    outcome: str

    @property
    def net_pnl(self):
        return self.pnl - self.fees

    @property
    def is_win(self):
        return self.net_pnl > 0

def load_trades(csv_path: str) -> list[Trade]:
    """Load trades from CSV"""
    trades = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                trades.append(Trade(
                    symbol=row['symbol'],
                    side=row['side'],
                    leverage=float(row['leverage']),
                    confidence=float(row['confidence']),
                    regime=row.get('regime', 'unknown'),
                    pnl=float(row['pnl']),
                    fees=float(row['fees']),
                    outcome=row.get('outcome', '')
                ))
            except (ValueError, KeyError):
                continue
    return trades

def analyze_by_dimension(trades: list[Trade], dimension: str):
    """Analyze profitability by any dimension"""
    by_dim = defaultdict(lambda: {'wins': 0, 'total': 0, 'pnl': 0, 'trades': []})

    for t in trades:
        if dimension == 'symbol':
            key = t.symbol
        elif dimension == 'side':
            key = t.side
        elif dimension == 'regime':
            key = t.regime
        elif dimension == 'symbol_side':
            key = f"{t.symbol}_{t.side}"
        elif dimension == 'symbol_regime':
            key = f"{t.symbol}_{t.regime}"
        elif dimension == 'leverage_bucket':
            if t.leverage < 5:
                key = "Low (1-5x)"
            elif t.leverage < 10:
                key = "Med (5-10x)"
            else:
                key = "High (10x+)"
        elif dimension == 'confidence_bucket':
            if t.confidence < 40:
                key = "Low (<40%)"
            elif t.confidence < 60:
                key = "Mid (40-60%)"
            elif t.confidence < 80:
                key = "High (60-80%)"
            else:
                key = "VHigh (80%+)"
        else:
            continue

        by_dim[key]['trades'].append(t)
        by_dim[key]['total'] += 1
        if t.is_win:
            by_dim[key]['wins'] += 1
        by_dim[key]['pnl'] += t.net_pnl

    # Sort by PnL
    sorted_results = sorted(by_dim.items(), key=lambda x: x[1]['pnl'], reverse=True)

    return sorted_results

def main():
    trades = load_trades('data/trades.csv')
    print("=" * 80)
    print("PHASE 7: DEEP TRADE ANALYSIS - WHAT ACTUALLY WORKS")
    print("=" * 80)
    print(f"\nTotal trades: {len(trades)}\n")

    # 1. BY SYMBOL
    print("1. PROFITABILITY BY SYMBOL")
    print("-" * 80)
    for symbol, data in analyze_by_dimension(trades, 'symbol'):
        wr = 100 * data['wins'] / data['total'] if data['total'] > 0 else 0
        per_trade = data['pnl'] / data['total'] if data['total'] > 0 else 0
        status = "PROFITABLE" if data['pnl'] > 0 else "LOSING"
        print(f"  {symbol:6s} n={data['total']:3d} WR={wr:5.1f}% PnL=${data['pnl']:8.2f} per_trade=${per_trade:6.2f} [{status}]")

    # 2. BY SYMBOL + SIDE
    print("\n2. PROFITABILITY BY SYMBOL + DIRECTION")
    print("-" * 80)
    best_setups = analyze_by_dimension(trades, 'symbol_side')[:10]
    worst_setups = analyze_by_dimension(trades, 'symbol_side')[-10:]

    print("  TOP 10 (Most Profitable):")
    for setup, data in best_setups:
        wr = 100 * data['wins'] / data['total'] if data['total'] > 0 else 0
        per_trade = data['pnl'] / data['total'] if data['total'] > 0 else 0
        print(f"    {setup:15s} n={data['total']:3d} WR={wr:5.1f}% Total=${data['pnl']:8.2f} Per=${per_trade:6.2f}")

    print("\n  BOTTOM 10 (Losing):")
    for setup, data in worst_setups:
        wr = 100 * data['wins'] / data['total'] if data['total'] > 0 else 0
        per_trade = data['pnl'] / data['total'] if data['total'] > 0 else 0
        print(f"    {setup:15s} n={data['total']:3d} WR={wr:5.1f}% Total=${data['pnl']:8.2f} Per=${per_trade:6.2f}")

    # 3. BY REGIME
    print("\n3. PROFITABILITY BY REGIME")
    print("-" * 80)
    for regime, data in analyze_by_dimension(trades, 'regime'):
        wr = 100 * data['wins'] / data['total'] if data['total'] > 0 else 0
        per_trade = data['pnl'] / data['total'] if data['total'] > 0 else 0
        status = "PROFITABLE" if data['pnl'] > 0 else "LOSING"
        print(f"  {regime:20s} n={data['total']:3d} WR={wr:5.1f}% PnL=${data['pnl']:8.2f} per_trade=${per_trade:6.2f} [{status}]")

    # 4. BY LEVERAGE BUCKET
    print("\n4. PROFITABILITY BY LEVERAGE")
    print("-" * 80)
    for leverage_bucket, data in analyze_by_dimension(trades, 'leverage_bucket'):
        wr = 100 * data['wins'] / data['total'] if data['total'] > 0 else 0
        per_trade = data['pnl'] / data['total'] if data['total'] > 0 else 0
        status = "PROFITABLE" if data['pnl'] > 0 else "LOSING"
        print(f"  {leverage_bucket:15s} n={data['total']:3d} WR={wr:5.1f}% PnL=${data['pnl']:8.2f} per_trade=${per_trade:6.2f} [{status}]")

    # 5. BY CONFIDENCE BUCKET
    print("\n5. PROFITABILITY BY CONFIDENCE")
    print("-" * 80)
    for conf_bucket, data in analyze_by_dimension(trades, 'confidence_bucket'):
        wr = 100 * data['wins'] / data['total'] if data['total'] > 0 else 0
        per_trade = data['pnl'] / data['total'] if data['total'] > 0 else 0
        status = "PROFITABLE" if data['pnl'] > 0 else "LOSING"
        print(f"  {conf_bucket:15s} n={data['total']:3d} WR={wr:5.1f}% PnL=${data['pnl']:8.2f} per_trade=${per_trade:6.2f} [{status}]")

    # 6. SYMBOL + REGIME
    print("\n6. PROFITABILITY BY SYMBOL + REGIME (Top 10)")
    print("-" * 80)
    best_combos = analyze_by_dimension(trades, 'symbol_regime')[:10]
    for combo, data in best_combos:
        wr = 100 * data['wins'] / data['total'] if data['total'] > 0 else 0
        per_trade = data['pnl'] / data['total'] if data['total'] > 0 else 0
        print(f"  {combo:30s} n={data['total']:3d} WR={wr:5.1f}% Total=${data['pnl']:8.2f}")

    # 7. KEY INSIGHTS
    print("\n7. KEY INSIGHTS FROM HISTORICAL DATA")
    print("-" * 80)

    # Find most consistent edge
    symbol_side_results = analyze_by_dimension(trades, 'symbol_side')
    profitable = [x for x in symbol_side_results if x[1]['pnl'] > 0 and x[1]['total'] >= 5]

    print("\n  HIGH-CONVICTION EDGES (5+ trades, positive PnL):")
    for setup, data in profitable[:5]:
        wr = 100 * data['wins'] / data['total']
        per_trade = data['pnl'] / data['total']
        print(f"    {setup:15s}: {wr:.0f}% WR, ${per_trade:.2f}/trade (n={data['total']})")

    # Find worst regimes
    regime_results = analyze_by_dimension(trades, 'regime')
    losing = [x for x in regime_results if x[1]['pnl'] < 0]

    print("\n  LOSING REGIMES (Where to cut losses):")
    for regime, data in losing[:5]:
        wr = 100 * data['wins'] / data['total']
        per_trade = data['pnl'] / data['total']
        print(f"    {regime:20s}: {wr:.0f}% WR, ${per_trade:.2f}/trade (n={data['total']})")

    # Summary stats
    overall_pnl = sum(t.net_pnl for t in trades)
    overall_wins = sum(1 for t in trades if t.is_win)
    print(f"\n  Overall: {overall_wins}/{len(trades)} wins ({100*overall_wins/len(trades):.1f}% WR), ${overall_pnl:.2f} PnL")

    print("\n" + "=" * 80)

if __name__ == '__main__':
    main()
