#!/usr/bin/env python
"""
WAGMI Co-Pilot LIQUIDATION-CASCADE COLLECTOR - liq_summary.py
=============================================================================
Tiny read-only companion to liq_collector.py. Reads
data/copilot/liquidations/liq_events.jsonl and prints an inspection report:
events/day, notional/day, per-symbol/per-venue counts, biggest single liq.

Standalone, READ-ONLY - only reads the jsonl this collector itself writes.
No imports of llm/, execution/, core/, strategies/, no Discord, no writes.

CLI:
    python tools/copilot/liq_summary.py
    python tools/copilot/liq_summary.py --path data/copilot/liquidations/liq_events.jsonl
Also reachable via: python tools/copilot/liq_collector.py --summary
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_PATH = os.path.join(BOT_DIR, "data", "copilot", "liquidations", "liq_events.jsonl")


def load_events(path: str) -> list:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def print_summary(path: str = DEFAULT_PATH) -> None:
    rows = load_events(path)
    print(f"=== WAGMI liquidation-cascade collector - summary ===")
    print(f"file: {path}")
    if not rows:
        print("(no events captured yet - this is expected on a fresh collector; run "
              "liq_collector.py to start capturing. Zero rows is not a bug.)")
        return

    print(f"total events: {len(rows)}")

    # Date range + events/day, notional/day
    days = defaultdict(lambda: {"count": 0, "notional": 0.0})
    for r in rows:
        ts = r.get("ts_utc", "")
        day = ts[:10] if len(ts) >= 10 else "unknown"
        days[day]["count"] += 1
        days[day]["notional"] += r.get("notional_usd") or 0.0

    n_days = max(len(days), 1)
    total_notional = sum(d["notional"] for d in days.values())
    print(f"date range: {min(days)} .. {max(days)}  ({n_days} day(s) with data)")
    print(f"events/day (avg): {len(rows) / n_days:.1f}")
    print(f"notional/day (avg): ${total_notional / n_days:,.0f}")

    # Per-venue
    by_venue = defaultdict(int)
    for r in rows:
        by_venue[r.get("venue", "unknown")] += 1
    print("\nper-venue counts:")
    for v, c in sorted(by_venue.items(), key=lambda x: -x[1]):
        print(f"  {v:>10}: {c}")

    # Per-symbol
    by_symbol = defaultdict(lambda: {"count": 0, "notional": 0.0, "long": 0, "short": 0})
    for r in rows:
        s = by_symbol[r.get("symbol", "unknown")]
        s["count"] += 1
        s["notional"] += r.get("notional_usd") or 0.0
        side = r.get("side")
        if side == "long":
            s["long"] += 1
        elif side == "short":
            s["short"] += 1
    print("\nper-symbol counts (longs-liquidated / shorts-liquidated):")
    for sym, d in sorted(by_symbol.items(), key=lambda x: -x[1]["count"]):
        print(f"  {sym:>8}: {d['count']:>5} events  ${d['notional']:>14,.0f} notional  "
              f"(long={d['long']} short={d['short']})")

    # Daily breakdown (last 14 days)
    print("\nper-day breakdown (most recent 14):")
    for day in sorted(days)[-14:]:
        d = days[day]
        print(f"  {day}: {d['count']:>4} events  ${d['notional']:>12,.0f} notional")

    # Biggest single liquidation
    biggest = max(rows, key=lambda r: r.get("notional_usd") or 0.0)
    print("\nbiggest single liquidation:")
    print(f"  {biggest.get('ts_utc')}  {biggest.get('venue')}  {biggest.get('symbol')}  "
          f"{biggest.get('side')}  ${biggest.get('notional_usd'):,.0f}  @ {biggest.get('price')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize captured liquidation-cascade data.")
    ap.add_argument("--path", type=str, default=DEFAULT_PATH, help="Path to liq_events.jsonl")
    args = ap.parse_args()
    print_summary(args.path)


if __name__ == "__main__":
    main()
