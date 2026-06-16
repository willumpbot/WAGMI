#!/usr/bin/env python3
"""
Clean up known-bullshit data points from the bot's learning stores.

Run from repo root: python coordination/cleanup_bullshit_data.py [--dry-run]

What it cleans:
  1. counterfactual scenarios with |delta| > 100% (P3 amplification bug residue)
  2. kelly_weights pre-2026-05-30 (pre-fee-fix era poisoning)
  3. flags llm_memory entries that reference dead rules (n=411, omniscient_integrated)

Backs up each file before modifying.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DRY_RUN = "--dry-run" in sys.argv

CUTOFF_TS = datetime(2026, 5, 30, tzinfo=timezone.utc).timestamp()


def backup(path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bk = path.with_suffix(path.suffix + f".bak.{ts}")
    if not DRY_RUN:
        shutil.copy2(path, bk)
    return bk


def clean_counterfactuals():
    path = REPO_ROOT / "bot" / "data" / "counterfactuals" / "scenarios.json"
    if not path.exists():
        print(f"[SKIP] {path} not found")
        return
    data = json.load(open(path))
    scenarios = data.get("scenarios", [])
    before = len(scenarios)
    kept = [s for s in scenarios if abs(s.get("delta", 0)) < 100 and abs(s.get("actual_pnl", 0)) < 100000]
    removed = before - len(kept)
    print(f"[counterfactuals] {before} total -> keep {len(kept)} (drop {removed} amplification-bug records)")
    if removed > 0 and not DRY_RUN:
        bk = backup(path)
        print(f"  backup: {bk.name}")
        data["scenarios"] = kept
        data["cleaned_at"] = datetime.now(timezone.utc).isoformat()
        json.dump(data, open(path, "w"), indent=2)
        print(f"  WROTE {path}")
    elif DRY_RUN:
        print("  [DRY-RUN] would purge")


def clean_kelly_weights():
    path = REPO_ROOT / "bot" / "data" / "kelly_weights.json"
    if not path.exists():
        print(f"[SKIP] {path} not found")
        return
    data = json.load(open(path))
    trades = data.get("trades", {})
    total_before = sum(len(v) if isinstance(v, list) else 0 for v in trades.values())
    cleaned = {}
    for strat, info in trades.items():
        if isinstance(info, list):
            cleaned[strat] = [t for t in info if t.get("ts", 0) >= CUTOFF_TS]
        else:
            cleaned[strat] = info
    total_after = sum(len(v) if isinstance(v, list) else 0 for v in cleaned.values())
    dropped = total_before - total_after
    print(f"[kelly_weights] {total_before} trades -> keep {total_after} (drop {dropped} pre-2026-05-30)")
    if dropped > 0 and not DRY_RUN:
        bk = backup(path)
        print(f"  backup: {bk.name}")
        data["trades"] = cleaned
        data["cleaned_at"] = datetime.now(timezone.utc).isoformat()
        json.dump(data, open(path, "w"), indent=2)
        print(f"  WROTE {path}")
    elif DRY_RUN:
        print("  [DRY-RUN] would purge pre-2026-05-30 records")


def flag_dead_rule_citations():
    """Find but don't delete: log entries referencing disabled rules."""
    # llm_memory.json has bot's stored "memories" that may cite n=411 or omniscient_integrated
    path = REPO_ROOT / "bot" / "data" / "llm" / "llm_memory.json"
    if not path.exists():
        print(f"[SKIP] {path} not found")
        return
    data = json.load(open(path))
    flagged = []

    def scan(obj, path_str=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                scan(v, f"{path_str}.{k}" if path_str else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                scan(v, f"{path_str}[{i}]")
        elif isinstance(obj, str):
            if "n=411" in obj or "omniscient_integrated" in obj or "2.3% WR" in obj:
                flagged.append((path_str[:60], obj[:80]))

    scan(data)
    print(f"[llm_memory] {len(flagged)} citations of dead rules (n=411 / omniscient / 2.3% WR)")
    for loc, txt in flagged[:5]:
        print(f"  {loc}: {txt}")
    print("  (not auto-purged — review and decide whether to scrub)")


def main():
    if DRY_RUN:
        print("=== DRY-RUN MODE (no files will be modified) ===\n")
    else:
        print("=== LIVE MODE (will modify files, backups created) ===\n")
    clean_counterfactuals()
    print()
    clean_kelly_weights()
    print()
    flag_dead_rule_citations()
    print()
    print("Done. Use --dry-run to preview without writing.")


if __name__ == "__main__":
    main()
