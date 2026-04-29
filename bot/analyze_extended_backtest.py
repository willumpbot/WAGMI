#!/usr/bin/env python3
"""
Extended Backtest Results Analyzer
Extracts key metrics from 90-day backtest and provides deployment recommendations
"""

import os
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def parse_backtest_log(log_path):
    """Extract backtest metrics from log file"""
    metrics = {
        "num_trades": 0,
        "win_rate": 0.0,
        "pnl_gross": 0.0,
        "pnl_net": 0.0,
        "max_dd": 0.0,
        "profit_factor": 0.0,
        "sharpe": 0.0,
        "trades": []
    }

    try:
        with open(log_path, 'r') as f:
            content = f.read()

        # Parse summary line
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if "Positions:" in line and "opened" in line:
                # Extract trade count
                parts = line.split('|')
                if len(parts) > 0:
                    try:
                        num_str = parts[0].split()[-2]
                        metrics["num_trades"] = int(num_str)
                    except: pass

            elif "Win Rate:" in line:
                # Extract win rate
                try:
                    wr_str = line.split('(')[1].split('%')[0].strip()
                    metrics["win_rate"] = float(wr_str)
                except: pass

            elif "Gross PnL:" in line and "$" in line:
                try:
                    pnl_str = line.split('$')[-1].split()[0].replace(',', '')
                    metrics["pnl_gross"] = float(pnl_str)
                except: pass

            elif "Net PnL:" in line and "$" in line and "Gross" not in line:
                try:
                    pnl_str = line.split('$')[-1].split()[0].replace(',', '')
                    metrics["pnl_net"] = float(pnl_str)
                except: pass

            elif "Max DD:" in line:
                try:
                    dd_str = line.split()[-1].strip('%')
                    metrics["max_dd"] = float(dd_str)
                except: pass

            elif "Profit Factor:" in line:
                try:
                    pf_str = line.split(':')[-1].strip()
                    metrics["profit_factor"] = float(pf_str)
                except: pass

            elif "Sharpe Ratio:" in line:
                try:
                    sharpe_str = line.split(':')[-1].strip()
                    metrics["sharpe"] = float(sharpe_str)
                except: pass

    except Exception as e:
        print(f"Error parsing log: {e}")

    return metrics

def generate_deployment_recommendation(metrics):
    """Generate deployment recommendation based on backtest results"""
    recommendation = {
        "option": "",
        "rationale": "",
        "confidence": 0,
        "next_steps": []
    }

    # Decision logic
    if metrics["num_trades"] == 0:
        recommendation["option"] = "OPTION 1: Conservative (Disable All Gates)"
        recommendation["rationale"] = "Gates are rejecting all trades. Too aggressive for current market. Deploy baseline."
        recommendation["confidence"] = 95
        recommendation["next_steps"] = [
            "Set all gates to FALSE in .env",
            "Deploy to paper trading with baseline",
            "Run 180-day parallel validation to understand gate effectiveness",
            "Incrementally enable gates one layer at a time"
        ]

    elif metrics["win_rate"] >= 70:
        if metrics["num_trades"] >= 8:
            recommendation["option"] = "OPTION 3: Full Stack (Keep All Gates Enabled)"
            recommendation["rationale"] = f"Gates produce {metrics['num_trades']} trades at {metrics['win_rate']:.1f}% WR. Excellent filter."
            recommendation["confidence"] = 90
            recommendation["next_steps"] = [
                "Keep all gates ENABLED in .env",
                "Deploy to paper trading immediately",
                "Monitor paper results vs backtest predictions",
                "Track gate effectiveness over 180d"
            ]
        else:
            recommendation["option"] = "OPTION 2: Progressive (Layer 1 Only)"
            recommendation["rationale"] = f"Gates producing {metrics['num_trades']} trades at {metrics['win_rate']:.1f}% WR. Enable L1 only."
            recommendation["confidence"] = 75
            recommendation["next_steps"] = [
                "Enable only Layer 1 (regime gate) in .env",
                "Disable L2 and L3 temporarily",
                "Deploy to paper, monitor for 30d",
                "Then progressively enable L2, then L3"
            ]

    elif metrics["win_rate"] >= 50:
        recommendation["option"] = "OPTION 2: Progressive (Layer 1 Only)"
        recommendation["rationale"] = f"Gates producing {metrics['num_trades']} trades at {metrics['win_rate']:.1f}% WR. Start conservative."
        recommendation["confidence"] = 70
        recommendation["next_steps"] = [
            "Enable only Layer 1 (high_volatility) gate",
            "Deploy to paper trading",
            "After 30d paper results, evaluate enabling L2"
        ]

    else:  # WR < 50%
        recommendation["option"] = "OPTION 1: Conservative (Disable All Gates)"
        recommendation["rationale"] = f"Gates produce poor WR ({metrics['win_rate']:.1f}%). Disabling for baseline."
        recommendation["confidence"] = 85
        recommendation["next_steps"] = [
            "Set all gates to FALSE",
            "Deploy baseline configuration",
            "Run extended 180-day analysis",
            "Investigate why gates hurt performance"
        ]

    return recommendation

def main():
    data_dir = Path(__file__).parent / "data"

    # Find most recent extended backtest log
    logs = sorted(data_dir.glob("EXTENDED_BACKTEST_90D_*.log"), reverse=True)

    if not logs:
        print("❌ No extended backtest logs found")
        print("   Launch backtest: python run.py backtest --symbols BTC,ETH,SOL --days 90")
        sys.exit(1)

    log_path = logs[0]
    print(f"\n📊 Analyzing backtest: {log_path.name}")
    print("=" * 80)

    # Parse results
    metrics = parse_backtest_log(log_path)

    if metrics["num_trades"] == 0:
        print("⏳ Backtest still running or not completed. Checking again...")
        sys.exit(0)

    # Generate recommendation
    rec = generate_deployment_recommendation(metrics)

    # Print results
    print(f"\n📈 BACKTEST RESULTS (90-day window, BTC/ETH/SOL)")
    print(f"   Trades: {metrics['num_trades']}")
    print(f"   Win Rate: {metrics['win_rate']:.1f}%")
    print(f"   Gross PnL: ${metrics['pnl_gross']:.2f}")
    print(f"   Net PnL: ${metrics['pnl_net']:.2f}")
    print(f"   Max DD: {metrics['max_dd']:.1f}%")
    print(f"   Profit Factor: {metrics['profit_factor']:.2f}x")
    print(f"   Sharpe Ratio: {metrics['sharpe']:.2f}")

    print(f"\n🎯 DEPLOYMENT RECOMMENDATION")
    print(f"   Option: {rec['option']}")
    print(f"   Confidence: {rec['confidence']}%")
    print(f"   Rationale: {rec['rationale']}")

    print(f"\n📋 NEXT STEPS")
    for i, step in enumerate(rec['next_steps'], 1):
        print(f"   {i}. {step}")

    # Save results
    results_file = data_dir / f"EXTENDED_BACKTEST_RESULTS_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics,
            "recommendation": rec,
            "log_file": str(log_path)
        }, f, indent=2)

    print(f"\n✅ Results saved to: {results_file.name}")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
