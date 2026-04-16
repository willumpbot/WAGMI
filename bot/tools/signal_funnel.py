"""
Signal funnel analyzer — shows how many signals become trades.

Reads data/logs/signal_outcomes.jsonl and breaks down:
    - Total signals per symbol
    - Pass/reject counts at each gate
    - Top rejection reasons
    - LLM-first pipeline stages (toxic_block, llm_skip, llm_execute)
    - Execution rate (signals → trades)

Usage (from bot/):
    python tools/signal_funnel.py                # last 24h
    python tools/signal_funnel.py --hours 168    # last 7 days
    python tools/signal_funnel.py --symbol HYPE  # single symbol

Does not modify state. Safe while bot is live.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict


_LOG_PATH = os.path.join("data", "logs", "signal_outcomes.jsonl")


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=24.0,
                   help="Time window in hours (default: 24)")
    p.add_argument("--symbol", type=str, default=None,
                   help="Filter to one symbol (e.g., HYPE)")
    p.add_argument("--log-path", type=str, default=_LOG_PATH)
    return p.parse_args()


def main():
    args = _parse_args()

    if not os.path.exists(args.log_path):
        print(f"ERROR: {args.log_path} not found.")
        sys.exit(1)

    cutoff_ts = time.time() - (args.hours * 3600)

    total = 0
    by_symbol = Counter()
    by_side = Counter()
    by_strategy = Counter()
    passed_count = 0
    hard_rejected_count = 0
    soft_rejected_count = 0
    rejection_reasons = Counter()
    llm_first_stages = Counter()
    llm_first_pass = 0

    with open(args.log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            ts = rec.get("ts", 0)
            if ts < cutoff_ts:
                continue

            sym = rec.get("sym", "")
            if args.symbol and sym != args.symbol:
                continue

            total += 1
            by_symbol[sym] += 1
            by_side[rec.get("side", "")] += 1
            by_strategy[rec.get("strat", "")] += 1

            if rec.get("passed"):
                passed_count += 1
            if rec.get("hard_rej"):
                hard_rejected_count += 1
            else:
                if not rec.get("passed"):
                    soft_rejected_count += 1

            reason = rec.get("rej_reason", "")
            if reason:
                # Truncate to avoid ultra-long keys
                rejection_reasons[reason[:70]] += 1

            # LLM-first pipeline stages (only set by _track_llm_first_outcome)
            meta = rec.get("meta", {}) or {}
            if meta.get("pipeline") == "llm_first":
                stage = meta.get("stage", "unknown")
                llm_first_stages[stage] += 1
                if stage == "llm_execute":
                    llm_first_pass += 1

    print()
    print("=" * 60)
    print(f"  SIGNAL FUNNEL — last {args.hours:.1f}h")
    if args.symbol:
        print(f"  symbol: {args.symbol}")
    print("=" * 60)
    print()

    if total == 0:
        print(f"  No records in window.")
        return

    exec_rate = passed_count / total if total > 0 else 0.0
    print(f"  TOTAL RECORDS:     {total:,}")
    print(f"  PASSED:            {passed_count:,} ({exec_rate:.1%})")
    print(f"  HARD REJECTED:     {hard_rejected_count:,} ({hard_rejected_count/total:.1%})")
    print(f"  SOFT REJECTED:     {soft_rejected_count:,} ({soft_rejected_count/total:.1%})")
    print()

    print("  BY SYMBOL:")
    for sym, count in by_symbol.most_common():
        pct = count / total * 100
        print(f"    {sym:6s}: {count:5d} ({pct:5.1f}%)")
    print()

    print("  BY STRATEGY (source of signal):")
    for strat, count in by_strategy.most_common(10):
        pct = count / total * 100
        print(f"    {strat:25s}: {count:5d} ({pct:5.1f}%)")
    print()

    print("  BY SIDE:")
    for side, count in by_side.most_common():
        pct = count / total * 100
        print(f"    {side:5s}: {count:5d} ({pct:5.1f}%)")
    print()

    if rejection_reasons:
        print("  TOP REJECTION REASONS:")
        for reason, count in rejection_reasons.most_common(10):
            pct = count / total * 100
            print(f"    {count:5d} ({pct:4.1f}%)  {reason}")
        print()

    if llm_first_stages:
        print("  LLM-FIRST PIPELINE STAGES:")
        for stage, count in llm_first_stages.most_common():
            print(f"    {stage:15s}: {count:5d}")
        print()
        llm_total = sum(llm_first_stages.values())
        llm_exec_rate = llm_first_pass / llm_total if llm_total > 0 else 0.0
        print(f"  LLM-FIRST EXEC RATE: {llm_first_pass}/{llm_total} ({llm_exec_rate:.1%})")
        print()
    else:
        print("  LLM-FIRST: no tracked decisions yet in window")
        print()

    print("=" * 60)


if __name__ == "__main__":
    main()
