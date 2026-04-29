#!/usr/bin/env python3
"""
Extended Window Backtesting
Run simulated trades across 30-day, 60-day, 90-day, 180-day windows using cached OHLCV data.

Key insight: data/cache contains up to 365 days of historical OHLCV for BTC/ETH/SOL/HYPE.
This enables training data generation across MUCH longer periods than just 30 days.
"""

import json
from pathlib import Path
from datetime import datetime

print("\n" + "=" * 140)
print("EXTENDED WINDOW BACKTEST CAMPAIGN")
print("=" * 140)
print(f"Start time: {datetime.now().isoformat()}")
print()

# Analyze available cached data
cache_dir = Path("data/cache")
available_windows = {}

if cache_dir.exists():
    cache_files = sorted(cache_dir.glob("*.csv"))

    for f in cache_files:
        parts = f.stem.split("_")
        if len(parts) >= 3:
            symbol = parts[0].upper()
            period = parts[2]

            if period not in ["sim"]:  # Skip sim files
                if symbol not in available_windows:
                    available_windows[symbol] = set()
                available_windows[symbol].add(period)

print("AVAILABLE DATA WINDOWS BY SYMBOL:")
print("-" * 140)
for symbol in sorted(available_windows.keys()):
    periods = sorted(available_windows[symbol], key=lambda x: int(x.replace('d', '')) if x != '0d' else 0)
    print(f"  {symbol:6s}: {', '.join(periods)}")

print()
print("BACKTEST CAMPAIGN PLAN:")
print("-" * 140)
print()

windows_to_test = {
    "30-day": "Mar 29 - Apr 28 (current)",
    "60-day": "Feb 28 - Apr 28 (2 months)",
    "90-day": "Jan 29 - Apr 28 (3 months)",
    "180-day": "Oct 31, 2025 - Apr 28, 2026 (6 months)"
}

print("Training data generation across extended windows:")
print()
for window_name, description in windows_to_test.items():
    print(f"  {window_name:10s}: {description}")

print()
print("ESTIMATED TRAINING TRADES:")
print("-" * 140)

estimates = {
    "30-day": (6750, 10800, "1 month"),
    "60-day": (13500, 21600, "2 months"),
    "90-day": (20250, 32400, "3 months"),
    "180-day": (40500, 64800, "6 months")
}

print()
for window, (low, high, desc) in estimates.items():
    print(f"  {window:10s}: {low:6,d} - {high:6,d} simulated trades ({desc})")

print()
total_min = sum(e[0] for e in estimates.values())
total_max = sum(e[1] for e in estimates.values())
print(f"  TOTAL:     {total_min:6,d} - {total_max:6,d} combined training trades")

print()
print("EXECUTION TIMELINE:")
print("-" * 140)
print()
print("Phase 1: 30-day window optimization (TODAY)")
print("  - Run all 270 parameter sweeps on Mar 29 - Apr 28")
print("  - Generate 6,750-10,800 training trades")
print("  - Identify best threshold/leverage combinations")
print()

print("Phase 2: 60-day extended backtests (NEXT: 2-4 hours)")
print("  - Run same 270 parameters on Feb 28 - Apr 28")
print("  - Generate 13,500-21,600 training trades")
print("  - Validate that best configs still work over 2-month window")
print()

print("Phase 3: 90-day strategic backtests (NEXT: 4-8 hours)")
print("  - Run top-20 best performing parameters on 90-day window")
print("  - Generate ~400-650 training trades per config")
print("  - Test robustness across quarterly patterns")
print()

print("Phase 4: 180-day validation (NEXT: Optional, 8-16 hours)")
print("  - Run top-5 best performing parameters on 6-month window")
print("  - Generate ~300-400 training trades per config")
print("  - Validate KB works across seasonal market changes")
print()

print()
print("CUMULATIVE IMPACT:")
print("-" * 140)
print()
print("Current training data: 205 historical + 61 simulated = 266 total")
print()
print("After Phase 1 (30-day sweeps):")
print("  + 6,750-10,800 simulated trades")
print("  = 7,015-11,066 total training examples")
print()
print("After Phase 2 (60-day sweeps):")
print("  + 13,500-21,600 simulated trades")
print("  = 20,515-32,466 total training examples (77x initial)")
print()
print("After Phase 3 (90-day sweeps):")
print("  + 20,250-32,400 simulated trades")
print("  = 40,765-64,866 total training examples (154x initial)")
print()
print("After Phase 4 (180-day validation):")
print("  + 40,500-64,800 simulated trades")
print("  = 81,265-129,666 total training examples (306x initial)")
print()

print("=" * 140)
print()

# Save plan
plan_file = Path("data/extended_backtest_plan.json")
with open(plan_file, 'w') as f:
    json.dump({
        "campaign": "Extended Window Backtest Campaign",
        "start_time": datetime.now().isoformat(),
        "available_windows": {k: list(v) for k, v in available_windows.items()},
        "windows_to_test": windows_to_test,
        "estimates": estimates,
        "total_expected_training_trades": f"{total_min:,d} - {total_max:,d}",
        "phases": {
            "phase_1": "30-day sweeps (270 configs)",
            "phase_2": "60-day sweeps (270 configs)",
            "phase_3": "90-day top-20 sweeps",
            "phase_4": "180-day top-5 validation"
        }
    }, f, indent=2)

print(f"Plan saved to: {plan_file}")
print()
print("READY TO BEGIN EXTENDED BACKTESTING")
print("This will generate 80K-130K training examples vs. 266 currently available")
print("=" * 140)
