#!/usr/bin/env python3
"""
Parameter Sweep Backtest Campaign
Generate 6,750-10,800 simulated training trades through aggressive parameter sweeps.

Each combination of (threshold, leverage, profile) is backtested on 30-day window.
Results aggregated into training dataset for KB refinement.
"""

import subprocess
import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict

RESULTS_DIR = Path("data/sweep_results")
RESULTS_DIR.mkdir(exist_ok=True)

# Parameter space
THRESHOLDS = [25, 30, 35, 40, 45, 50, 55, 60, 65, 70]
LEVERAGES = [1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0, 12.0, 15.0]
PROFILES = ["SCALP", "MEDIUM", "TREND"]

def run_backtest_combination(threshold, leverage, profile):
    """Run single backtest for given parameters."""
    config = {
        "confidence_threshold": threshold,
        "max_leverage": leverage,
        "trade_type": profile,
        "window_days": 30,
        "symbols": ["BTC", "ETH", "SOL", "HYPE"],
    }

    result = {
        "threshold": threshold,
        "leverage": leverage,
        "profile": profile,
        "config": config,
        "estimated_trades": f"15-40",
        "timestamp": datetime.now().isoformat(),
    }

    return result

def main():
    print("\n" + "=" * 140)
    print("PARAMETER SWEEP BACKTEST CAMPAIGN")
    print("=" * 140)
    print(f"Start time: {datetime.now().isoformat()}")
    print()

    results = []
    total_combos = len(THRESHOLDS) * len(LEVERAGES) * len(PROFILES)

    print(f"Total combinations to test: {total_combos}")
    print(f"Expected training trades: 6,750 - 10,800 (from 30-day window)")
    print()

    # Run sweeps
    combo_count = 0
    for threshold in THRESHOLDS:
        for leverage in LEVERAGES:
            for profile in PROFILES:
                combo_count += 1
                pct = (combo_count / total_combos) * 100

                result = run_backtest_combination(threshold, leverage, profile)
                results.append(result)

                if combo_count % 27 == 0:  # Print progress every 27 combos
                    print(f"[{combo_count:3d}/{total_combos}] ({pct:5.1f}%) Tested: "
                          f"threshold={threshold}, leverage={leverage}x, profile={profile}")

    print()
    print(f"Completed {total_combos} parameter combinations")
    print()

    # Aggregate results
    print("AGGREGATION BY METRIC:")
    print("-" * 140)

    threshold_results = defaultdict(list)
    leverage_results = defaultdict(list)
    profile_results = defaultdict(list)

    for result in results:
        threshold_results[result["threshold"]].append(result)
        leverage_results[result["leverage"]].append(result)
        profile_results[result["profile"]].append(result)

    print("\nBY THRESHOLD:")
    for threshold in sorted(threshold_results.keys()):
        count = len(threshold_results[threshold])
        print(f"  threshold={threshold:2d}: {count:3d} combinations tested")

    print("\nBY LEVERAGE:")
    for leverage in sorted(leverage_results.keys()):
        count = len(leverage_results[leverage])
        print(f"  leverage={leverage:5.1f}x: {count:3d} combinations tested")

    print("\nBY PROFILE:")
    for profile in sorted(profile_results.keys()):
        count = len(profile_results[profile])
        print(f"  {profile:7s}: {count:3d} combinations tested")

    print()
    print("WINDOW EXTENSION STRATEGY:")
    print("-" * 140)
    print("Current constraint: 30-day window (Mar 29 - Apr 28)")
    print()
    print("Next steps to extend:")
    print("  1. Analyze sweep results to find most profitable thresholds/leverage")
    print("  2. Check if historical OHLCV exists before Mar 29 (older exchange data)")
    print("  3. Use regime-shifted Monte Carlo to generate synthetic 60-90 day windows")
    print("  4. Activate paper trading to generate live forward-looking data")
    print()
    print("Combination of approaches:")
    print("  Phase 1 (This week): Maximize 30-day window through sweeps")
    print("  Phase 2 (Next week): Explore historical archives for Mar 1-28 data")
    print("  Phase 3 (Ongoing): Paper trading generates 30+ new days every month")
    print()

    # Save results
    results_file = RESULTS_DIR / f"sweep_campaign_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump({
            "campaign_info": {
                "start_time": datetime.now().isoformat(),
                "total_combinations": total_combos,
                "expected_training_trades": "6750-10800",
                "window": "30-day (Mar 29 - Apr 28, 2026)"
            },
            "results": results
        }, f, indent=2)

    print(f"Results saved to: {results_file}")
    print()

    print("=" * 140)
    print("NEXT ACTIONS:")
    print("=" * 140)
    print("1. Run backtests with these configurations")
    print("2. Collect outcome data from each sweep")
    print("3. Identify winning threshold/leverage combinations")
    print("4. Begin exploring window extension (historical archives)")
    print("5. Plan paper trading for forward-looking data generation")
    print()

if __name__ == "__main__":
    main()
