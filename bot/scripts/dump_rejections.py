#!/usr/bin/env python3
"""
Dump all trade rejections and pruning decisions for the day.
Useful for understanding why signals were NOT traded.

Usage:
    python -m scripts.dump_rejections
"""

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Paths
REJECTIONS_FILE = "data/logs/risk_rejections.csv"
SAFETY_EVENTS_FILE = "data/logs/safety_events.csv"
SYMBOL_PRECISION_FILE = "config/symbol_precision.json"


def load_csv(path):
    """Load a CSV file into list of dicts."""
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"Error reading {path}: {e}")
    return rows


def load_json(path):
    """Load JSON file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {path}: {e}")
    return {}


def main():
    rejections = load_csv(REJECTIONS_FILE)
    safety = load_csv(SAFETY_EVENTS_FILE)
    symbols_spec = load_json(SYMBOL_PRECISION_FILE)

    print("=" * 80)
    print("TRADE REJECTIONS & PRUNING DECISIONS")
    print(f"Report generated: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    # Group rejections by reason
    if rejections:
        print("\n### REJECTIONS BY REASON ###\n")
        by_reason = {}
        for row in rejections:
            reason = row.get("reason", "UNKNOWN")
            if reason not in by_reason:
                by_reason[reason] = []
            by_reason[reason].append(row)

        for reason, rows in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            print(f"{reason}: {len(rows)} rejections")
            # Show first 3 examples
            for row in rows[:3]:
                ts = row.get("timestamp", "")
                symbol = row.get("symbol", "?")
                conf = row.get("confidence", "?")
                print(f"  - {ts[:19]} {symbol} conf={conf}")
            if len(rows) > 3:
                print(f"  ... and {len(rows) - 3} more")
            print()
    else:
        print("\n[No rejections logged today]\n")

    # Safety events
    if safety:
        print("\n### SAFETY EVENTS ###\n")
        for row in safety[-10:]:  # Last 10
            ts = row.get("timestamp", "")
            event_type = row.get("event_type", "?")
            reason = row.get("reason", "")
            print(f"  {ts[:19]} {event_type}: {reason}")
    else:
        print("\n[No safety events logged today]\n")

    # Symbol health
    print("\n### SYMBOL CONFIGURATION ###\n")
    print(f"{'Symbol':<12} {'Price DP':<10} {'Qty DP':<8} {'Min Qty':<12} {'Max Lev':<10}")
    print("-" * 52)
    for symbol in sorted(symbols_spec.keys()):
        spec = symbols_spec[symbol]
        price_dp = spec.get("price", "?")
        qty_dp = spec.get("qty", "?")
        min_qty = spec.get("min_qty", "?")
        max_lev = spec.get("max_leverage", "?")
        print(f"{symbol:<12} {price_dp:<10} {qty_dp:<8} {min_qty:<12} {max_lev:<10}")

    # Summary stats
    print("\n### SUMMARY ###\n")
    total_rejections = len(rejections)
    total_safety = len(safety)
    print(f"Total rejections: {total_rejections}")
    print(f"Total safety events: {total_safety}")
    print(f"Symbols configured: {len(symbols_spec)}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
