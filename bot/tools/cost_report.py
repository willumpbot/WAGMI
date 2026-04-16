"""
Cost report — CLI tool to summarize today's LLM spend with cache breakdown.

Usage (from bot/ directory):
    python tools/cost_report.py

Shows:
    - Total spend vs budget (with visual progress)
    - Per-model breakdown (Haiku vs Sonnet)
    - Prompt cache hit rate + estimated savings
    - Budget threshold proximity (soft/hard limits)
    - LLM-first pipeline call count (if tracked)

Does not modify state. Safe to run while the bot is live.
"""

import json
import os
import sys
from datetime import datetime, timezone


_PRICING = {
    "claude-haiku-4-5-20251001": ("Haiku 4.5", 0.80, 4.00, 1.00, 0.08),
    "claude-sonnet-4-5-20250929": ("Sonnet 4.5", 3.00, 15.00, 3.75, 0.30),
    "claude-opus-4-20250115": ("Opus 4", 15.00, 75.00, 18.75, 1.50),
}


def _bar(pct: float, width: int = 30) -> str:
    filled = int(pct * width)
    return "#" * filled + "-" * (width - filled)


def _format_money(amount: float) -> str:
    return f"${amount:.4f}" if amount < 0.1 else f"${amount:.3f}"


def main():
    path = os.path.join("data", "llm", "cost_tracker.json")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Run from bot/ directory.")
        sys.exit(1)

    with open(path) as f:
        state = json.load(f)

    date = state.get("date", "?")
    spend = state.get("spend", 0.0)
    budget = state.get("budget", 0.0)
    calls = state.get("calls", 0)
    calls_by_model = state.get("calls_by_model", {})
    spend_by_model = state.get("spend_by_model", {})
    cache_read = state.get("cache_read_tokens", 0)
    cache_create = state.get("cache_create_tokens", 0)
    cache_hits = state.get("cache_hits", 0)

    pct = spend / budget if budget > 0 else 0.0

    print()
    print("=" * 60)
    print(f"  LLM COST REPORT - {date} UTC")
    print("=" * 60)
    print()
    print(f"  SPEND:   {_format_money(spend)} / ${budget:.2f} ({pct:.1%})")
    print(f"  BAR:     [{_bar(pct)}] {pct:.0%}")
    print()

    # Threshold indicators
    thresholds = [
        (0.70, "soft limit (downgrade non-critical)", "->"),
        (0.90, "hard limit (Haiku-only)", "!!"),
        (1.00, "BUDGET EXCEEDED (full stop)", "XX"),
    ]
    for thresh, label, marker in thresholds:
        reached = "PASSED" if pct >= thresh else f"at ${budget * thresh:.2f}"
        print(f"  {marker} {thresh:.0%} {label}: {reached}")
    print()

    # Per-model breakdown
    print("  CALLS & SPEND BY MODEL:")
    for model_id, count in sorted(calls_by_model.items(), key=lambda kv: -kv[1]):
        name, _, _, _, _ = _PRICING.get(model_id, (model_id, 0, 0, 0, 0))
        model_spend = spend_by_model.get(model_id, 0.0)
        avg = model_spend / count if count > 0 else 0.0
        print(f"    {name:12s}: {count:4d} calls  {_format_money(model_spend):>10s}  avg {_format_money(avg)}/call")
    print()

    # Cache stats
    if cache_hits > 0 or cache_read > 0 or cache_create > 0:
        hit_rate = cache_hits / calls if calls > 0 else 0.0
        print("  PROMPT CACHE:")
        print(f"    Hit rate:          {hit_rate:.1%} ({cache_hits}/{calls})")
        print(f"    Read tokens:       {cache_read:,}")
        print(f"    Write tokens:      {cache_create:,}")
        # Rough savings estimate: if these read tokens had been uncached,
        # cost 10x more. Assume 70/30 Haiku/Sonnet split.
        savings_read = cache_read * (0.70 * 0.72 + 0.30 * 2.70) / 1_000_000
        print(f"    Est. savings:      {_format_money(savings_read)} (vs uncached)")
    else:
        print("  PROMPT CACHE: no hits yet (cache warms within first 5 min)")
    print()

    # Projections
    now = datetime.now(timezone.utc)
    hours_elapsed = now.hour + now.minute / 60.0
    hours_remaining = 24 - hours_elapsed
    if hours_elapsed > 0.1 and calls > 0:
        burn_per_hour = spend / hours_elapsed
        projected_end = spend + burn_per_hour * hours_remaining
        print(f"  PROJECTIONS (UTC hour={hours_elapsed:.1f}):")
        print(f"    Burn rate:         {_format_money(burn_per_hour)}/hr")
        print(f"    Projected EOD:     {_format_money(projected_end)} "
              f"({'OVER' if projected_end > budget else 'under'} budget)")
        if burn_per_hour > 0:
            print(f"    Hrs to exhaust:    {((budget - spend) / burn_per_hour):.1f}")
        else:
            print("    Hrs to exhaust:    inf")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
