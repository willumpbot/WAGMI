#!/usr/bin/env python3
"""
4-Layer Professional Gate Stack Calibration Script
Systematically tests all gate combinations on 90-day backtest window
Measures: # trades, WR%, PnL, gate effectiveness vs. deep analysis target (9-10 trades @ 75% WR)
"""

import subprocess
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

def run_backtest(days=90):
    """Run backtest and extract summary metrics"""
    try:
        result = subprocess.run(
            [sys.executable, "run.py", "backtest"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=Path(__file__).parent
        )

        # Extract metrics from output
        output = result.stdout
        metrics = {
            "num_trades": 0,
            "win_rate": 0,
            "pnl": 0,
            "pnl_net": 0,
            "ratio": 0,
        }

        # Parse the output for key metrics
        for line in output.split('\n'):
            if "Positions:" in line and "opened" in line:
                parts = line.split('|')
                if len(parts) > 0:
                    trade_part = parts[0].strip()
                    num = trade_part.split()[-2] if len(trade_part.split()) > 1 else "0"
                    try:
                        metrics["num_trades"] = int(num)
                    except:
                        pass
            elif "Win Rate:" in line and "%" in line:
                parts = line.split('|')
                if len(parts) > 0:
                    wr_str = parts[0].split('(')[-1].split('%')[0].strip()
                    try:
                        metrics["win_rate"] = float(wr_str)
                    except:
                        pass
            elif "Gross PnL:" in line and "$" in line:
                try:
                    pnl_str = line.split('$')[-1].split()[0].replace(',', '')
                    metrics["pnl"] = float(pnl_str)
                except:
                    pass
            elif "Net PnL:" in line and "$" in line and "Gross" not in line:
                try:
                    pnl_str = line.split('$')[-1].split()[0].replace(',', '')
                    metrics["pnl_net"] = float(pnl_str)
                except:
                    pass
            elif "W=$" in line and "L=$" in line:
                # Extract win/loss ratio
                try:
                    ratio_part = line.split('=')[-1].strip()
                    metrics["ratio"] = float(ratio_part)
                except:
                    pass

        return metrics
    except Exception as e:
        print(f"Error running backtest: {e}")
        return None

def update_env(gate_l1=False, gate_l2=False, gate_l3=False):
    """Update .env file with gate configuration"""
    env_path = Path(__file__).parent / ".env"

    with open(env_path, 'r') as f:
        lines = f.readlines()

    # Find and update gate lines
    for i, line in enumerate(lines):
        if "GATE_HIGH_VOLATILITY_REGIMES=" in line:
            value = "true" if gate_l1 else "false"
            lines[i] = f"GATE_HIGH_VOLATILITY_REGIMES={value}      # Layer 1: high_volatility rejection\n"
        elif "GATE_TREND_FOLLOW_SETUPS=" in line:
            value = "true" if gate_l2 else "false"
            lines[i] = f"GATE_TREND_FOLLOW_SETUPS={value}          # Layer 2: trend_follow rejection\n"
        elif "ENABLE_CONFIDENCE_DISTRIBUTION_GATING=" in line:
            value = "true" if gate_l3 else "false"
            lines[i] = f"ENABLE_CONFIDENCE_DISTRIBUTION_GATING={value}  # Layer 3: 70-79% confidence rejection\n"

    with open(env_path, 'w') as f:
        f.writelines(lines)

def main():
    print("=" * 80)
    print("4-Layer Professional Gate Stack Calibration")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 80)
    print()

    # Define test cases: (name, L1, L2, L3)
    test_cases = [
        ("BASELINE (all disabled)", False, False, False),
        ("L1 only (high_vol rejection)", True, False, False),
        ("L2 only (trend_follow rejection)", False, True, False),
        ("L3 only (confidence band rejection)", False, False, True),
        ("L1+L2 (regime + setup)", True, True, False),
        ("L1+L3 (regime + confidence)", True, False, True),
        ("L2+L3 (setup + confidence)", False, True, True),
        ("ALL LAYERS (L1+L2+L3)", True, True, True),
    ]

    results = []

    for name, l1, l2, l3 in test_cases:
        print(f"Testing: {name}")
        print(f"  Gates: L1={l1}, L2={l2}, L3={l3}")

        # Update environment
        update_env(gate_l1=l1, gate_l2=l2, gate_l3=l3)

        # Run backtest
        metrics = run_backtest()
        if metrics:
            print(f"  Results: {metrics['num_trades']} trades, {metrics['win_rate']:.1f}% WR, ${metrics['pnl_net']:.2f} net PnL")
            results.append({
                "name": name,
                "l1": l1,
                "l2": l2,
                "l3": l3,
                **metrics
            })
        else:
            print(f"  ERROR: Could not parse results")

        print()

    # Save results
    results_file = Path(__file__).parent / "data" / f"GATE_CALIBRATION_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)

    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)

    print("=" * 80)
    print("CALIBRATION SUMMARY")
    print("=" * 80)
    print()
    print(f"{'Configuration':<35} {'Trades':<8} {'WR%':<8} {'Net PnL':<12} {'Deviation from target':<20}")
    print("-" * 85)

    target_trades = 9.5
    target_wr = 75.0

    for result in results:
        name = result['name'][:33]
        trades = result['num_trades']
        wr = result['win_rate']
        pnl = result['pnl_net']

        # Calculate distance from target
        trade_dev = abs(trades - target_trades) / target_trades * 100
        wr_dev = abs(wr - target_wr) / target_wr * 100
        combined_dev = (trade_dev + wr_dev) / 2

        dev_str = f"{combined_dev:.1f}%"

        print(f"{name:<35} {trades:<8} {wr:<8.1f} ${pnl:<11.2f} {dev_str:<20}")

    print()
    print(f"Target: 9-10 trades at 75% WR (deep analysis)")
    print(f"Results saved to: {results_file}")
    print()
    print("=" * 80)

if __name__ == "__main__":
    main()
