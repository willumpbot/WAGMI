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
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone


_LOG_PATH = os.path.join("data", "logs", "signal_outcomes.jsonl")
_RISK_REJECTIONS_PATH = os.path.join("data", "logs", "risk_rejections.csv")


def _read_risk_rejections(path: str, cutoff_ts: float, symbol_filter: str | None):
    """Read risk_rejections.csv; return Counter of reasons and list of rows in window."""
    if not os.path.exists(path):
        return Counter(), Counter(), 0
    by_symbol = Counter()
    by_reason = Counter()
    total = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                ts_str = row.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(
                        ts_str.replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    continue
                if ts < cutoff_ts:
                    continue
                sym = row.get("symbol", "")
                if symbol_filter and sym != symbol_filter:
                    continue
                total += 1
                by_symbol[sym] += 1
                # Normalize reason: strip common prefix, group by semantic category
                reason = row.get("reason", "")
                if not reason:
                    category = "unknown"
                else:
                    # Strip "risk_filter_chain: " wrapper to get to the real cause
                    body = reason
                    if ":" in body:
                        body = body.split(":", 1)[1].strip()
                    # Map common phrases to short categories
                    low = body.lower()
                    if "duplicate position" in low:
                        category = "duplicate_position"
                    elif "ev " in low[:4] or "< min" in low and "expected value" in low:
                        category = "negative_EV"
                    elif "circuit breaker" in low or "cb " in low:
                        category = "circuit_breaker"
                    elif "stop" in low and ("too tight" in low or "near zero" in low):
                        category = "stop_too_tight"
                    elif "leverage" in low and ("cap" in low or "exceed" in low):
                        category = "leverage_cap"
                    elif "sector" in low and ("exposure" in low or "cap" in low):
                        category = "sector_cap"
                    elif "liquidation" in low:
                        category = "liquidation_risk"
                    elif "position limit" in low or "max_open_positions" in low:
                        category = "position_limit"
                    else:
                        category = body[:60]
                by_reason[category] += 1
    except Exception as e:
        print(f"WARN: reading {path} failed: {e}", file=sys.stderr)
    return by_symbol, by_reason, total


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=24.0,
                   help="Time window in hours (default: 24)")
    p.add_argument("--symbol", type=str, default=None,
                   help="Filter to one symbol (e.g., HYPE)")
    p.add_argument("--log-path", type=str, default=_LOG_PATH)
    p.add_argument("--risk-path", type=str, default=_RISK_REJECTIONS_PATH,
                   help="Path to risk_rejections.csv (pre-pipeline rejects)")
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

    # Pre-pipeline risk_filter_chain rejects — signals that never made it to the ensemble log
    rej_by_sym, rej_by_reason, rej_total = _read_risk_rejections(
        args.risk_path, cutoff_ts, args.symbol
    )
    if rej_total > 0:
        print(f"  RISK-FILTER REJECTS (pre-pipeline, last {args.hours:.1f}h): {rej_total:,}")
        print("    BY SYMBOL:")
        for sym, count in rej_by_sym.most_common():
            print(f"      {sym:6s}: {count:5d}")
        print("    BY CATEGORY:")
        for cat, count in rej_by_reason.most_common(10):
            pct = count / rej_total * 100
            print(f"      {count:5d} ({pct:4.1f}%)  {cat}")
        print()

    print("=" * 60)


if __name__ == "__main__":
    main()
