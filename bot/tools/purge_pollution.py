"""Phase 0.2 purge tool -- detect (and, only with --apply, remove) the two
confirmed pollution incidents that motivated core/provenance.py:

  1. 253 fabricated POPCAT rows (~23% of the file) in
     bot/data/analysis/trade_outcomes.csv -- appended by a backtest run that
     reused the live record_trade_outcome() write path before the write-time
     gate existed.
  2. A stray "TEST" key in bot/data/momentum_state.json -- written by a
     test/sim process sharing the live state path.

DEFAULT MODE IS DRY-RUN. This script only REPORTS what it would remove
(counts + sample rows) until you pass --apply. It never touches anything on
the first run of a session; --apply is required, explicit, and irreversible
without a manual backup.

SAFETY GUARDS:
  - All paths are resolved via core.paths (this worktree's own
    __file__-anchored DATA_DIR) -- never a hardcoded or cwd-relative path.
  - refuse_if_live_tree() hard-refuses to run at all if this file's own
    resolved location is under the live C:\\Users\\vince\\WAGMI\\ tree
    (as opposed to the isolated C:\\Users\\vince\\WAGMI_measurework\\
    worktree it was written for). This is a belt-and-suspenders check: the
    __file__-anchoring already makes it structurally very hard for this
    script to touch the wrong tree, but the guard makes that explicit and
    fails loudly instead of silently operating on the wrong data.

Usage (run from bot/):
    python tools/purge_pollution.py                # dry-run (default)
    python tools/purge_pollution.py --apply         # actually remove pollution
    python tools/purge_pollution.py --apply --yes   # skip the confirmation prompt
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap bot/ onto sys.path so `from core import paths` resolves when this
# script is invoked directly (python tools/purge_pollution.py) instead of as
# part of the package (mirrors tests/test_paths.py's own bootstrap).
_BOT_ROOT_FOR_IMPORT = Path(__file__).resolve().parent.parent
if str(_BOT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT_FOR_IMPORT))

from core import paths  # noqa: E402

# The live tree this script must NEVER operate against, even by accident.
# Compared case-insensitively against BOT_ROOT's resolved path (Windows
# paths are case-insensitive).
_LIVE_TREE_MARKER = "wagmi"
_ISOLATED_WORKTREE_MARKER = "wagmi_measurework"

# Symbol substring that identifies the fabricated backtest pollution batch.
_POLLUTED_SYMBOL_MARKER = "POPCAT"

# Marker key(s) that indicate a sim/test write landed in live state.
_SIM_MARKER_KEYS = ("TEST", "SIM")


class LiveTreeGuardError(RuntimeError):
    """Raised when this script's resolved location is not inside the
    isolated measurework worktree it was written for. Refusing to run is
    the only safe behavior here -- see module docstring."""


def refuse_if_live_tree() -> None:
    """Hard guard: refuse to operate unless BOT_ROOT is unambiguously the
    isolated worktree (…\\WAGMI_measurework\\bot), never the live
    …\\WAGMI\\bot tree."""
    root_str = str(paths.BOT_ROOT.resolve()).lower()
    if _ISOLATED_WORKTREE_MARKER not in root_str:
        raise LiveTreeGuardError(
            f"REFUSING TO RUN: resolved BOT_ROOT={paths.BOT_ROOT} does not look "
            f"like the isolated '{_ISOLATED_WORKTREE_MARKER}' worktree this "
            f"script was written for. This guard exists specifically so this "
            f"script can never be run against the live WAGMI bot's data."
        )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def detect_popcat_pollution(csv_path: Path):
    """Return (total_rows, polluted_rows, sample) for trade_outcomes.csv.

    polluted_rows are rows whose symbol column contains the POPCAT marker.
    Never mutates the file.
    """
    if not csv_path.exists():
        return 0, [], []

    with open(csv_path, newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    polluted = [
        (i, row) for i, row in enumerate(rows)
        if _POLLUTED_SYMBOL_MARKER in str(row.get("symbol", "")).upper()
    ]
    return len(rows), polluted, [row for _, row in polluted[:5]]


def detect_test_key_pollution(state_path: Path):
    """Return a list of (json-path, value) for every TEST/SIM marker key
    found anywhere in momentum_state.json's top-level or nested dicts.

    Never mutates the file.
    """
    if not state_path.exists():
        return []

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  WARNING: could not parse {state_path}: {e}")
        return []

    findings = []

    def _scan(obj, path_prefix):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in _SIM_MARKER_KEYS:
                    findings.append((f"{path_prefix}.{key}", value))
                _scan(value, f"{path_prefix}.{key}")

    _scan(state, "$")
    return findings


# ---------------------------------------------------------------------------
# Removal (only reached with --apply)
# ---------------------------------------------------------------------------
def _backup(path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_suffix(path.suffix + f".pre_purge_{ts}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def apply_popcat_purge(csv_path: Path, polluted_indices: set) -> Path:
    with open(csv_path, newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    header, data_rows = all_rows[0], all_rows[1:]
    backup_path = _backup(csv_path)
    kept = [row for i, row in enumerate(data_rows) if i not in polluted_indices]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(kept)

    return backup_path


def apply_test_key_purge(state_path: Path) -> Path:
    backup_path = _backup(state_path)
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)

    def _strip(obj):
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if key in _SIM_MARKER_KEYS:
                    del obj[key]
                else:
                    _strip(obj[key])

    _strip(state)

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)

    return backup_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually remove pollution (default: dry-run report only).")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt when --apply is used.")
    args = parser.parse_args(argv)

    refuse_if_live_tree()

    outcomes_path = paths.trade_outcomes_path()
    momentum_path = paths.momentum_state_path()

    print(f"[purge_pollution] DATA_DIR = {paths.DATA_DIR}")
    print(f"[purge_pollution] mode     = {'APPLY (destructive)' if args.apply else 'DRY-RUN (report only)'}")
    print()

    # --- trade_outcomes.csv / POPCAT ---
    print(f"Scanning {outcomes_path} for '{_POLLUTED_SYMBOL_MARKER}' pollution...")
    total_rows, polluted, sample = detect_popcat_pollution(outcomes_path)
    if not outcomes_path.exists():
        print("  file does not exist in this worktree -- nothing to scan.")
    else:
        pct = (len(polluted) / total_rows * 100) if total_rows else 0.0
        print(f"  total rows: {total_rows}")
        print(f"  polluted rows ({_POLLUTED_SYMBOL_MARKER}): {len(polluted)} ({pct:.1f}%)")
        for row in sample:
            print(f"    sample: {row}")
    print()

    # --- momentum_state.json / TEST key ---
    print(f"Scanning {momentum_path} for TEST/SIM marker keys...")
    findings = detect_test_key_pollution(momentum_path)
    if not momentum_path.exists():
        print("  file does not exist in this worktree -- nothing to scan.")
    else:
        print(f"  marker keys found: {len(findings)}")
        for json_path, value in findings:
            print(f"    {json_path} = {value!r}")
    print()

    if not args.apply:
        print("Dry-run complete. No files were modified. Re-run with --apply to remove the above.")
        return 0

    if not polluted and not findings:
        print("Nothing to apply -- no pollution detected.")
        return 0

    if not args.yes:
        resp = input(
            f"About to remove {len(polluted)} POPCAT row(s) from {outcomes_path.name} "
            f"and {len(findings)} marker key(s) from {momentum_path.name}. "
            f"Backups will be written alongside each file. Continue? [y/N] "
        )
        if resp.strip().lower() != "y":
            print("Aborted.")
            return 1

    if polluted:
        polluted_indices = {i for i, _ in polluted}
        backup_path = apply_popcat_purge(outcomes_path, polluted_indices)
        print(f"Removed {len(polluted)} polluted row(s) from {outcomes_path}")
        print(f"  backup: {backup_path}")

    if findings:
        backup_path = apply_test_key_purge(momentum_path)
        print(f"Removed {len(findings)} marker key(s) from {momentum_path}")
        print(f"  backup: {backup_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
