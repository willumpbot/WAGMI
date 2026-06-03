"""
Recompute kelly_weights.json from trade_ledger.csv.

The live bot tracks kelly `won` flags from pos.realized_pnl in real time.
Between late May and June 2, 2026, TAKER_FEE_BPS=45 was active in .env
(a 10x overestimate of Hyperliquid's actual 0.045% taker fee). Any trades
recorded during that window had inflated fees, producing wrong `won` flags.

This script rebuilds the kelly trades dict from trade_ledger.csv, which is
ground-truth: its net_pnl column reflects the fees that were actually logged
at close time. We derive:
  won      = net_pnl > 0
  pnl_pct  = net_pnl / running_equity * 100

Run from bot/ directory:
    python scripts/recompute_kelly_from_ledger.py [--dry-run]
"""

import argparse
import csv
import json
import os
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

LEDGER_PATH  = Path("data/trade_ledger.csv")
KELLY_PATH   = Path("data/kelly_weights.json")
BACKUP_SUFFIX = f".bak_{int(time.time())}"

KELLY_FLOOR = 0.15
KELLY_CAP   = 1.0
MIN_TRADES  = 3


def raw_kelly(win_rate: float, payoff_ratio: float) -> float:
    if payoff_ratio <= 0:
        return 0.0
    f = win_rate - (1.0 - win_rate) / payoff_ratio
    return max(0.0, f)


def clamp_kelly(half_k: float) -> float:
    return max(KELLY_FLOOR, min(KELLY_CAP, half_k))


def compute_weight(trades: list) -> float:
    if len(trades) < MIN_TRADES:
        return KELLY_FLOOR
    wins   = [t for t in trades if t["won"]]
    losses = [t for t in trades if not t["won"]]
    total  = len(trades)
    wr     = len(wins) / total
    if not losses:
        avg_win = sum(abs(t["pnl_pct"]) for t in wins) / len(wins) if wins else 0.0
        pr = max(avg_win, 3.0)
    elif not wins:
        pr = 0.0
    else:
        avg_win  = sum(abs(t["pnl_pct"]) for t in wins)  / len(wins)
        avg_loss = sum(abs(t["pnl_pct"]) for t in losses) / len(losses)
        pr = avg_win / avg_loss if avg_loss > 1e-10 else max(avg_win, 3.0)
    return clamp_kelly(raw_kelly(wr, pr) / 2.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing files")
    args = parser.parse_args()

    if not LEDGER_PATH.exists():
        print(f"ERROR: {LEDGER_PATH} not found. Run from bot/ directory.")
        sys.exit(1)

    # Build trades dict from ledger
    trades_by_factor: dict = defaultdict(list)
    skipped = 0
    loaded  = 0

    with open(LEDGER_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                net_pnl   = float(row["net_pnl"])
                equity    = float(row["running_equity"])
                factors_s = row.get("contributing_factors", "").strip()
                ts_str    = row.get("timestamp", "")
            except (KeyError, ValueError):
                skipped += 1
                continue

            if not factors_s or equity <= 0:
                skipped += 1
                continue

            factors  = [f.strip() for f in factors_s.split(",") if f.strip()]
            won      = net_pnl > 0
            pnl_pct  = net_pnl / equity * 100.0

            # Approximate timestamp from ledger row (ISO string or epoch)
            try:
                from datetime import datetime, timezone
                if "T" in ts_str or "-" in ts_str:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                else:
                    ts = float(ts_str)
            except Exception:
                ts = time.time()

            for factor in factors:
                trades_by_factor[factor].append({
                    "won": won,
                    "pnl_pct": round(pnl_pct, 6),
                    "ts": ts,
                })
                loaded += 1

    print(f"Loaded {loaded} factor-trade records from ledger ({skipped} rows skipped)")
    print(f"Factors found: {sorted(trades_by_factor.keys())}")

    # Compute weights
    weights: dict = {}
    for factor, trades in trades_by_factor.items():
        w = compute_weight(trades)
        wins = sum(1 for t in trades if t["won"])
        wr   = wins / len(trades) if trades else 0
        print(f"  {factor:30s} n={len(trades):3d}  WR={wr:.1%}  weight={w:.3f}")
        weights[factor] = w

    # Load existing file for comparison
    existing: dict = {}
    if KELLY_PATH.exists():
        try:
            existing = json.loads(KELLY_PATH.read_text())
        except json.JSONDecodeError:
            pass

    old_weights = existing.get("weights", {})
    print("\nWeight changes (old -> new):")
    all_factors = set(list(old_weights.keys()) + list(weights.keys()))
    for f in sorted(all_factors):
        old = old_weights.get(f, None)
        new = weights.get(f, None)
        tag = ""
        if old is None:
            tag = "(new)"
        elif new is None:
            tag = "(removed)"
        elif abs(old - new) > 0.001:
            tag = "(changed)"
        if tag:
            print(f"  {f:30s} {old!s:10s} -> {new!s:10s}  {tag}")

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return

    # Backup existing
    if KELLY_PATH.exists():
        backup = KELLY_PATH.with_suffix(BACKUP_SUFFIX)
        shutil.copy2(KELLY_PATH, backup)
        print(f"\nBacked up original to {backup}")

    # Write new kelly_weights.json
    data = {
        "trades": dict(trades_by_factor),
        "weights": weights,
        "updated_at": time.time(),
        "recomputed_from": str(LEDGER_PATH),
        "recompute_note": "Rebuilt from trade_ledger.csv to correct fee-bug contamination (TAKER_FEE_BPS was 45, fixed to 5 on 2026-06-02).",
    }
    with open(KELLY_PATH, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {KELLY_PATH} ({loaded} records, {len(weights)} factors)")


if __name__ == "__main__":
    main()
