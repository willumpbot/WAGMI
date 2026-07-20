"""
LLM Analytics CLI - offline evaluation and tuning suite.

Run after a paper or live trading session to evaluate LLM performance.

Usage:
    cd bot/
    python -m llm.analyze                              # today's session
    python -m llm.analyze --session 2026-02-22         # specific date
    python -m llm.analyze --focus regimes              # regime-only analysis
    python -m llm.analyze --focus triggers             # trigger-only analysis
    python -m llm.analyze --focus confidence           # confidence calibration
    python -m llm.analyze --plots                      # generate PNG plots
    python -m llm.analyze --csv                        # export CSV summaries
    python -m llm.analyze --llm-log path --trades path # custom paths
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from llm.joiner import load_decisions, load_trades, join_decisions_trades
from llm.metrics import compute_metrics, format_report, export_summary_csv
from llm.plots import generate_all_plots
from llm.config_eval import (
    CONFIDENCE_BUCKETS,
    MIN_SAMPLES_FOR_STATS,
    VALID_REGIMES,
    VALID_TRIGGERS,
    MODE_PROGRESSION,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)
logger = logging.getLogger("bot.llm.analyze")


def _resolve_paths(args) -> tuple:
    """Resolve LLM log and trades paths from args."""
    llm_path = args.llm_log
    trades_path = args.trades

    # Default paths
    if not llm_path:
        llm_path = os.path.join("data", "llm", "decisions.jsonl")
    if not trades_path:
        trades_path = os.path.join("data", "trades.csv")

    return llm_path, trades_path


def _load_trades_default() -> list:
    """Load closed trades from the canonical ledger for the default (no
    --trades override) path.

    FALLACY_AUDIT (measurework, item 5, display_only_safe): trades.csv
    silently misses closes vs trade_ledger.csv (accounting hole), inflating
    WR in every offline report this CLI produces. join_decisions_trades()
    matches by timestamp proximity (not state_path), so building TradeRecord
    objects from the ledger is a safe swap; only state_path/entry_type/
    primary_driver/volatility_band degrade to "" (not present in the ledger
    schema) -- entry/exit/pnl/fees/leverage/confidence/strategy/regime are
    all populated.
    """
    from llm.joiner import TradeRecord
    from data.trade_source import load_closed_trades
    from datetime import datetime, timezone

    records = []
    for row in load_closed_trades():
        ts_str = row.get("timestamp", "")
        ts_float = 0.0
        if ts_str:
            try:
                dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts_float = dt.timestamp()
            except (ValueError, TypeError):
                pass
        records.append(TradeRecord(
            timestamp=ts_str,
            ts=ts_float,
            symbol=row.get("symbol", ""),
            side=(row.get("side", "") or "").lower(),
            entry=row.get("entry", 0.0),
            exit=row.get("exit", 0.0),
            pnl=row.get("pnl", 0.0),
            fees=row.get("fees", 0.0),
            state_path=row.get("state_path", ""),
            outcome=row.get("outcome", ""),
            leverage=row.get("leverage", 1.0),
            confidence=row.get("confidence", 0.0),
            strategy=row.get("strategy", ""),
            entry_type=row.get("entry_type", ""),
            primary_driver="",
            regime=row.get("regime", ""),
            volatility_band="",
            entry_reasons="",
            raw=dict(row),
        ))
    return records


def _print_focused_report(result, focus: str):
    """Print a focused subset of the report."""
    from llm.metrics import BucketStats, _safe_pct

    sep = "-" * 60

    if focus == "regimes":
        print(sep)
        print("REGIME ANALYSIS")
        print(sep)
        print()
        print("Regime distribution:")
        total = sum(result.regime_dist.values())
        for regime in VALID_REGIMES:
            count = result.regime_dist.get(regime, 0)
            pct = _safe_pct(count, total)
            bar = "#" * int(pct / 2)
            print(f"  {regime:20s}: {count:4d} ({pct:5.1f}%) {bar}")

        flip_rate = _safe_pct(result.regime_flip_count, max(total - 1, 1))
        print(f"\n  Regime flip rate: {result.regime_flip_count} flips ({flip_rate:.1f}%)")

        print()
        print("Regime-conditioned performance:")
        print(f"  {'Regime':20s} | {'Calls':>5s} | {'Matched':>7s} | {'WinRate':>7s} | {'AvgPnL':>8s} | {'TotalPnL':>9s}")
        print(f"  {'-'*20}-+-{'-'*5}-+-{'-'*7}-+-{'-'*7}-+-{'-'*8}-+-{'-'*9}")
        for regime in VALID_REGIMES:
            stats = result.regime_stats.get(regime, BucketStats())
            if stats.count == 0:
                continue
            print(
                f"  {regime:20s} | {stats.count:5d} | {stats.matched:7d} | "
                f"{stats.win_rate:6.1f}% | ${stats.avg_pnl:+7.2f} | ${stats.total_pnl:+8.2f}"
            )

        # Action distribution per regime
        print()
        print("LLM action distribution per regime:")
        regime_actions = {}
        for jr in result.joined_records:
            d = jr.decision
            if d.action in ("api_error", "validation_failed"):
                continue
            r = d.regime or "unknown"
            a = d.action.lower()
            if r not in regime_actions:
                regime_actions[r] = {"long": 0, "short": 0, "flat": 0}
            regime_actions[r][a] = regime_actions[r].get(a, 0) + 1

        for regime in VALID_REGIMES:
            acts = regime_actions.get(regime, {})
            if not acts:
                continue
            total_a = sum(acts.values())
            parts = [f"{a}={c}({_safe_pct(c,total_a):.0f}%)" for a, c in sorted(acts.items()) if c > 0]
            print(f"  {regime:20s}: {' '.join(parts)}")

    elif focus == "triggers":
        print(sep)
        print("TRIGGER ANALYSIS")
        print(sep)
        print()
        print(f"  {'Trigger':30s} | {'Fired':>5s} | {'Matched':>7s} | {'WinRate':>7s} | {'AvgPnL':>8s} | {'TotalPnL':>9s}")
        print(f"  {'-'*30}-+-{'-'*5}-+-{'-'*7}-+-{'-'*7}-+-{'-'*8}-+-{'-'*9}")
        all_triggers = list(VALID_TRIGGERS) + [
            t for t in result.trigger_stats if t not in VALID_TRIGGERS
        ]
        for trigger in all_triggers:
            stats = result.trigger_stats.get(trigger, BucketStats())
            if stats.count == 0:
                continue
            print(
                f"  {trigger:30s} | {stats.count:5d} | {stats.matched:7d} | "
                f"{stats.win_rate:6.1f}% | ${stats.avg_pnl:+7.2f} | ${stats.total_pnl:+8.2f}"
            )

        # Most common trigger combinations
        print()
        print("Trigger frequency:")
        sorted_triggers = sorted(result.trigger_stats.items(), key=lambda x: -x[1].count)
        total_fires = sum(s.count for _, s in sorted_triggers)
        for trigger, stats in sorted_triggers:
            pct = _safe_pct(stats.count, total_fires)
            bar = "#" * int(pct / 2)
            print(f"  {trigger:30s}: {stats.count:4d} ({pct:5.1f}%) {bar}")

    elif focus == "confidence":
        print(sep)
        print("CONFIDENCE CALIBRATION ANALYSIS")
        print(sep)
        print()
        print(f"  {'Bucket':12s} | {'Count':>5s} | {'Matched':>7s} | {'WinRate':>7s} | {'AvgPnL':>8s} | {'TotalPnL':>9s}")
        print(f"  {'-'*12}-+-{'-'*5}-+-{'-'*7}-+-{'-'*7}-+-{'-'*8}-+-{'-'*9}")
        for lo, hi, label in CONFIDENCE_BUCKETS:
            stats = result.confidence_stats.get(label, BucketStats())
            print(
                f"  {f'[{lo:.1f}-{hi:.1f})':12s} | {stats.count:5d} | {stats.matched:7d} | "
                f"{stats.win_rate:6.1f}% | ${stats.avg_pnl:+7.2f} | ${stats.total_pnl:+8.2f}"
            )

        # Confidence distribution histogram
        print()
        print("Confidence distribution:")
        for lo, hi, label in CONFIDENCE_BUCKETS:
            stats = result.confidence_stats.get(label, BucketStats())
            total = result.total_decisions - result.error_count
            pct = _safe_pct(stats.count, total) if total > 0 else 0
            bar = "#" * int(pct)
            print(f"  {f'[{lo:.1f}-{hi:.1f})':12s}: {stats.count:4d} ({pct:5.1f}%) {bar}")

        # Correlation insight
        print()
        print("Calibration quality:")
        prev_wr = None
        monotonic = True
        for lo, hi, label in CONFIDENCE_BUCKETS:
            stats = result.confidence_stats.get(label, BucketStats())
            if stats.matched >= MIN_SAMPLES_FOR_STATS:
                wr = stats.win_rate
                if prev_wr is not None and wr < prev_wr - 5:
                    monotonic = False
                prev_wr = wr
        if monotonic and prev_wr is not None:
            print("  GOOD: Win rate generally increases with confidence")
        elif prev_wr is not None:
            print("  WARNING: Win rate does NOT consistently increase with confidence")
            print("  Consider recalibrating confidence scoring")

    elif focus == "mode":
        print(sep)
        print("MODE PROGRESSION ANALYSIS")
        print(sep)
        print()
        print(f"Current modes used: {', '.join(result.modes_used) or 'N/A'}")
        print(f"Total decisions: {result.total_decisions}")
        print()

        for transition, thresholds in MODE_PROGRESSION.items():
            print(f"{transition}:")
            min_dec = thresholds.get("min_decisions", 0)
            met = result.total_decisions >= min_dec
            print(f"  Min decisions: {min_dec} {'[MET]' if met else '[NOT MET]'} (current: {result.total_decisions})")

            # Action accuracy
            matched_with_trade = sum(1 for jr in result.joined_records if jr.trade and jr.trade.pnl != 0)
            correct = sum(
                1 for jr in result.joined_records
                if jr.trade and jr.trade.pnl != 0
                and (
                    (jr.decision.action.lower() in ("long", "short") and jr.trade.pnl > 0)
                    or (jr.decision.action.lower() == "flat" and jr.trade.pnl < 0)
                )
            )
            acc = correct / matched_with_trade if matched_with_trade > 0 else 0
            min_acc = thresholds.get("min_action_accuracy", 0)
            if min_acc:
                met = acc >= min_acc
                print(f"  Action accuracy: {min_acc:.0%} {'[MET]' if met else '[NOT MET]'} (current: {acc:.1%})")

            # Regime flip rate
            max_flip = thresholds.get("max_regime_flip_rate", 0)
            if max_flip:
                total = sum(result.regime_dist.values())
                flip_rate = result.regime_flip_count / max(total - 1, 1) if total > 1 else 0
                met = flip_rate <= max_flip
                print(f"  Regime flip rate: <={max_flip:.0%} {'[MET]' if met else '[NOT MET]'} (current: {flip_rate:.1%})")

            print()

    else:
        print(f"Unknown focus: {focus}. Use: regimes, triggers, confidence, mode")

    print(sep)


def main():
    parser = argparse.ArgumentParser(
        description="LLM Analytics - offline evaluation and tuning suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m llm.analyze                          # analyze today's session
  python -m llm.analyze --session 2026-02-22     # specific date
  python -m llm.analyze --focus regimes          # regime analysis only
  python -m llm.analyze --focus triggers         # trigger analysis only
  python -m llm.analyze --focus confidence       # confidence calibration
  python -m llm.analyze --focus mode             # mode progression check
  python -m llm.analyze --plots                  # generate PNG plots
  python -m llm.analyze --csv                    # export CSV summaries
  python -m llm.analyze --plots --csv            # both plots and CSVs
""",
    )

    parser.add_argument(
        "--session",
        default="today",
        help="Session label (used for report header, default: today)",
    )
    parser.add_argument(
        "--llm-log",
        default="",
        help="Path to LLM decisions JSONL file",
    )
    parser.add_argument(
        "--trades",
        default="",
        help="Path to trades CSV file",
    )
    parser.add_argument(
        "--focus",
        choices=["regimes", "triggers", "confidence", "mode"],
        default="",
        help="Focus on a specific analysis area",
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Generate matplotlib plots (saved as PNGs)",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Export CSV summary files",
    )
    parser.add_argument(
        "--output-dir",
        default="data/llm/reports",
        help="Output directory for CSVs and plots",
    )

    args = parser.parse_args()

    # Resolve paths
    llm_path, trades_path = _resolve_paths(args)

    print(f"Loading LLM decisions from: {llm_path}")
    print(f"Loading trades from: {trades_path}")
    print()

    # Load data.
    # FALLACY_AUDIT (measurework, item 5): default trades source is the
    # canonical trade_ledger.csv (via trade_source), not trades.csv, which
    # silently misses closes. An explicit --trades override still reads that
    # exact CSV path verbatim (legacy behavior preserved for callers who pass
    # a specific file, e.g. a backtest export).
    decisions = load_decisions(llm_path)
    if args.trades:
        trades = load_trades(trades_path)
    else:
        trades = _load_trades_default()

    if not decisions:
        print("No LLM decisions found. Nothing to analyze.")
        print(f"  Expected: {llm_path}")
        print("  Run the bot in ADVISORY mode first to generate decisions.")
        sys.exit(1)

    print(f"Loaded {len(decisions)} LLM decisions, {len(trades)} trades")

    # Join
    joined = join_decisions_trades(decisions, trades)

    # Compute metrics
    result = compute_metrics(joined)

    # Print report
    if args.focus:
        _print_focused_report(result, args.focus)
    else:
        session_label = args.session
        if session_label == "today":
            session_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report = format_report(result, session_label)
        print(report)

    # Export CSVs
    if args.csv:
        export_summary_csv(result, args.output_dir)
        print(f"\nCSV reports written to: {args.output_dir}/")

    # Generate plots
    if args.plots:
        plot_dir = os.path.join(args.output_dir, "plots") if "plots" not in args.output_dir else args.output_dir
        paths = generate_all_plots(result, plot_dir)
        if paths:
            print(f"\nPlots saved:")
            for p in paths:
                print(f"  {p}")
        else:
            print("\nNo plots generated (insufficient data or matplotlib not installed)")


if __name__ == "__main__":
    main()
