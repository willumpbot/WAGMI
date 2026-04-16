"""Backfill Finding 16: rewrite outcome column for mislabeled historical trades.

Finding 16 root cause: `position_manager.py:_classify_outcome` previously
returned "CLEAN_LOSS" unconditionally on SL-triggered closes that hadn't
hit TP1, even when the trailed SL closed the position at a profit.

21 historical rows in trades.csv have `pnl > 0` AND `outcome = CLEAN_LOSS`
AND state_path does NOT contain `TP1_HIT`. These are the mislabeled ones.
They should be rewritten as `CLEAN_WIN`.

Safe to re-run: idempotent (reads `pnl` and `outcome` together, only flips
mislabels). Writes the backup first so the original file can be restored.

Usage:
    python bot/scripts/backfill_outcome_labels.py --dry-run
    python bot/scripts/backfill_outcome_labels.py --apply
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from pathlib import Path

TRADES_FILE = Path("data") / "trades.csv"
BACKUP_SUFFIX = ".bak.finding16"


def find_mislabeled_rows(rows: list[list[str]], header: list[str]) -> list[tuple[int, list[str]]]:
    """Return indices and rows where outcome should be flipped."""
    pnl_idx = header.index("pnl")
    outcome_idx = header.index("outcome")
    state_path_idx = header.index("state_path")
    mislabeled = []
    for i, row in enumerate(rows):
        try:
            pnl = float(row[pnl_idx])
        except (ValueError, IndexError):
            continue
        outcome = row[outcome_idx] if outcome_idx < len(row) else ""
        state_path = row[state_path_idx] if state_path_idx < len(row) else ""
        # Mislabel: positive PnL but labeled CLEAN_LOSS, and TP1_HIT not in path
        if pnl > 0 and outcome == "CLEAN_LOSS" and "TP1_HIT" not in state_path:
            mislabeled.append((i, row))
    return mislabeled


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument("--trades-file", default=str(TRADES_FILE), help="Path to trades.csv")
    args = parser.parse_args()

    trades_path = Path(args.trades_file)
    if not trades_path.exists():
        print(f"ERROR: trades file not found: {trades_path}", file=sys.stderr)
        return 1

    with trades_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    if "outcome" not in header or "pnl" not in header or "state_path" not in header:
        print(f"ERROR: expected columns pnl/outcome/state_path in header: {header}", file=sys.stderr)
        return 1

    mislabeled = find_mislabeled_rows(rows, header)

    print(f"Trades file:        {trades_path}")
    print(f"Total rows:         {len(rows)}")
    print(f"Mislabeled rows:    {len(mislabeled)}")
    if not mislabeled:
        print("Nothing to do. File is clean.")
        return 0

    pnl_idx = header.index("pnl")
    outcome_idx = header.index("outcome")

    print("\nMislabeled trades:")
    total_pnl_flipped = 0.0
    for i, row in mislabeled:
        try:
            pnl = float(row[pnl_idx])
        except (ValueError, IndexError):
            pnl = 0.0
        total_pnl_flipped += pnl
        print(
            f"  row {i:4d}: {row[0][:19]} {row[1]:4s} {row[2]:5s} "
            f"pnl=${pnl:+.2f}  CLEAN_LOSS -> CLEAN_WIN"
        )
    print(f"\nTotal positive PnL that was mislabeled: ${total_pnl_flipped:+.2f}")

    if not args.apply:
        print("\n(Dry run. Pass --apply to write changes.)")
        return 0

    # Back up original
    backup_path = trades_path.with_suffix(trades_path.suffix + BACKUP_SUFFIX)
    shutil.copy2(trades_path, backup_path)
    print(f"\nBackup written: {backup_path}")

    # Apply fix
    for i, _row in mislabeled:
        rows[i][outcome_idx] = "CLEAN_WIN"

    with trades_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"Wrote {len(mislabeled)} label fixes to {trades_path}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
