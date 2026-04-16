"""
Bot status quick-check — one-screen health summary.

Prints:
    - LLM-FIRST mode active/inactive
    - Cost status (spend, budget, burn rate)
    - Recent LLM-first decisions (last N)
    - Signal funnel (last hour)
    - Bot process running check

Usage (from bot/):
    python tools/bot_status.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone


def _read_json_safe(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _check_bot_running():
    """Return True if a python.exe process is running with >50MB memory
    (the bot). Windows-specific."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.split("\n")
        for line in lines:
            if "python.exe" in line:
                parts = line.split()
                if len(parts) >= 5:
                    mem_str = parts[-2].replace(",", "")
                    try:
                        mem_kb = int(mem_str)
                        if mem_kb > 50_000:  # >50MB = likely the bot
                            return True, parts[1], mem_kb
                    except ValueError:
                        pass
        return False, None, 0
    except Exception:
        return False, None, 0


def _recent_llm_first_decisions(path, count=5):
    """Read the last N LLM-first decisions from signal_outcomes.jsonl."""
    if not os.path.exists(path):
        return []
    results = []
    try:
        # Read in reverse — tail the file
        with open(path, "rb") as f:
            f.seek(0, 2)  # end of file
            size = f.tell()
            chunk_size = min(64 * 1024, size)
            f.seek(size - chunk_size)
            tail = f.read().decode("utf-8", errors="replace")
        lines = tail.split("\n")
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            meta = rec.get("meta", {}) or {}
            if meta.get("pipeline") == "llm_first":
                results.append(rec)
                if len(results) >= count:
                    break
    except Exception:
        pass
    return results


def main():
    print()
    print("=" * 60)
    print("  BOT STATUS QUICK-CHECK")
    print("=" * 60)
    print()

    # Process check
    running, pid, mem_kb = _check_bot_running()
    if running:
        print(f"  BOT PROCESS: RUNNING (pid={pid}, {mem_kb/1024:.0f}MB)")
    else:
        print("  BOT PROCESS: NOT RUNNING")
    print()

    # LLM-FIRST mode
    env_path = ".env"
    llm_first = "unknown"
    llm_mode = "unknown"
    multi_agent = "unknown"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("LLM_FIRST_MODE="):
                    llm_first = line.split("=", 1)[1].split("#")[0].strip()
                elif line.startswith("LLM_MODE="):
                    llm_mode = line.split("=", 1)[1].split("#")[0].strip()
                elif line.startswith("LLM_MULTI_AGENT="):
                    multi_agent = line.split("=", 1)[1].split("#")[0].strip()

    llm_first_status = "ACTIVE" if llm_first.lower() == "true" else f"off ({llm_first})"
    print(f"  LLM_FIRST_MODE:   {llm_first_status}")
    print(f"  LLM_MODE:         {llm_mode}")
    print(f"  LLM_MULTI_AGENT:  {multi_agent}")
    print()

    # Cost state
    cost = _read_json_safe(os.path.join("data", "llm", "cost_tracker.json"))
    if cost:
        spend = cost.get("spend", 0.0)
        budget = cost.get("budget", 0.0)
        pct = spend / budget if budget > 0 else 0
        calls = cost.get("calls", 0)
        cache_write = cost.get("cache_create_tokens", 0)
        cache_read = cost.get("cache_read_tokens", 0)
        cache_hits = cost.get("cache_hits", 0)

        status = "OK"
        if pct >= 0.90:
            status = "HARD LIMIT (Haiku-only)"
        elif pct >= 0.70:
            status = "SOFT LIMIT (downgrades active)"

        print(f"  COST:             ${spend:.3f} / ${budget:.2f} ({pct:.0%})  [{status}]")
        print(f"  CALLS TODAY:      {calls}")
        print(f"  CACHE WRITES:     {cache_write:,} tokens")
        print(f"  CACHE HITS:       {cache_hits} ({cache_read:,} tokens read)")
    else:
        print("  COST:             (cost_tracker.json not found)")
    print()

    # Recent LLM-first decisions
    outcomes = _recent_llm_first_decisions(
        os.path.join("data", "logs", "signal_outcomes.jsonl"),
        count=5,
    )
    if outcomes:
        print("  RECENT LLM-FIRST DECISIONS:")
        for rec in outcomes:
            ts = rec.get("ts", 0)
            age = time.time() - ts
            age_str = f"{int(age/60)}m" if age < 3600 else f"{age/3600:.1f}h"
            sym = rec.get("sym", "?")
            side = rec.get("side", "?")
            meta = rec.get("meta", {}) or {}
            stage = meta.get("stage", "?")
            reason = (rec.get("rej_reason") or "")[:50]
            print(f"    [{age_str:>5s} ago] {sym:5s} {side:5s} {stage:12s}  {reason}")
    else:
        print("  RECENT LLM-FIRST: no decisions tracked yet")
    print()

    # Projection
    if cost and budget > 0:
        now = datetime.now(timezone.utc)
        hours_elapsed = now.hour + now.minute / 60.0
        if hours_elapsed > 0.1 and cost.get("spend", 0) > 0:
            burn = cost["spend"] / hours_elapsed
            remaining = 24 - hours_elapsed
            projected = cost["spend"] + burn * remaining
            verdict = "OVER" if projected > budget else "under"
            print(f"  PROJECTED EOD:    ${projected:.2f} ({verdict} budget)")
            if burn > 0:
                print(f"  HRS TO EXHAUST:   {(budget - cost['spend']) / burn:.1f}")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
