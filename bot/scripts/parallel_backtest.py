"""
Parallel Backtest Runner — Lever 4

Runs multiple symbol backtests simultaneously. Same total quota, ~4x wall-clock throughput.

Usage examples:

  # Run BTC + ETH in parallel, 15-day windows, with LLM
  python scripts/parallel_backtest.py \\
    --jobs "BTC:15:2026-01-15" "ETH:15:2026-01-15" \\
    --budget 4.0 --raw

  # Four symbols, different date windows
  python scripts/parallel_backtest.py \\
    --jobs "BTC:15:2025-10-15" "ETH:15:2025-10-15" "SOL:15:2026-01-15" "HYPE:15:2026-03-15" \\
    --budget 3.0 --llm --raw

Job format: SYMBOL:DAYS[:START_DATE]
  - START_DATE optional. Defaults to today minus DAYS.

Rate limit handling:
  - If any subprocess exits with code 2 (quota exhausted), all jobs pause 90s then resume.
  - Results written to data/parallel_backtest_YYYY-MM-DD/ one file per job.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_BOT_DIR = Path(__file__).parent.parent
_RESULTS_BASE = _BOT_DIR / "data" / "parallel_backtest_results"

QUOTA_PAUSE_SECONDS = 90   # pause duration when a 429/quota error detected
MAX_CONCURRENT = 8         # safety cap on simultaneous subprocesses


def parse_job(job_str: str) -> Tuple[str, int, Optional[str]]:
    """Parse 'SYMBOL:DAYS[:START_DATE]' → (symbol, days, start_date_or_None)."""
    parts = job_str.split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid job spec '{job_str}'. Expected SYMBOL:DAYS[:START_DATE]")
    symbol = parts[0].strip().upper()
    days = int(parts[1])
    start_date = parts[2].strip() if len(parts) >= 3 else None
    return symbol, days, start_date


def build_command(
    symbol: str,
    days: int,
    start_date: Optional[str],
    budget: float,
    llm: bool,
    raw: bool,
    extra_args: List[str],
) -> List[str]:
    """Build the run.py backtest command for a single job."""
    cmd = [sys.executable, "run.py", "backtest",
           "--symbols", symbol,
           "--days", str(days),
           "--equity", "10000"]
    if start_date:
        cmd += ["--start-date", start_date]
    if llm:
        cmd += ["--llm", "--budget", str(budget)]
    if raw:
        cmd.append("--raw")
    cmd.append("--yes")  # skip interactive confirmation for parallel runs
    cmd += extra_args
    return cmd


def run_parallel(
    jobs: List[Tuple[str, int, Optional[str]]],
    budget: float,
    llm: bool,
    raw: bool,
    extra_args: List[str],
    results_dir: Path,
) -> dict:
    """
    Launch all jobs as subprocesses, collect output, handle quota pauses.
    Returns summary dict: {job_str: {"exit_code": int, "log_path": str}}.
    """
    results_dir.mkdir(parents=True, exist_ok=True)

    # Build subprocess entries
    procs = []
    for symbol, days, start_date in jobs:
        label = f"{symbol}_{days}d"
        if start_date:
            label += f"_{start_date}"
        log_path = results_dir / f"{label}.log"
        cmd = build_command(symbol, days, start_date, budget, llm, raw, extra_args)
        log_f = open(log_path, "w", buffering=1)
        proc = subprocess.Popen(
            cmd,
            cwd=str(_BOT_DIR),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            text=True,
        )
        procs.append({
            "label": label,
            "symbol": symbol,
            "proc": proc,
            "log_path": log_path,
            "log_f": log_f,
            "start_time": time.time(),
            "exit_code": None,
        })
        print(f"  [{label}] started PID {proc.pid} -> {log_path.name}")

    summary = {}
    quota_paused = False

    while True:
        all_done = True
        for entry in procs:
            if entry["exit_code"] is not None:
                continue
            rc = entry["proc"].poll()
            if rc is not None:
                entry["exit_code"] = rc
                elapsed = (time.time() - entry["start_time"]) / 60
                status = "OK" if rc == 0 else f"ERR({rc})"
                print(f"  [{entry['label']}] {status} in {elapsed:.1f}min")
                entry["log_f"].close()
                summary[entry["label"]] = {
                    "exit_code": rc,
                    "log_path": str(entry["log_path"]),
                    "elapsed_min": round(elapsed, 1),
                }
                # Detect quota exhaustion (exit code 2 or log contains 429)
                if rc != 0:
                    try:
                        log_tail = entry["log_path"].read_text(errors="replace")[-2000:]
                        if "429" in log_tail or "quota" in log_tail.lower() or "rate limit" in log_tail.lower():
                            if not quota_paused:
                                print(f"\n  [QUOTA] {entry['label']} hit rate limit. "
                                      f"Pausing all jobs for {QUOTA_PAUSE_SECONDS}s...")
                                quota_paused = True
                    except Exception:
                        pass
            else:
                all_done = False

        if all_done:
            break

        if quota_paused:
            time.sleep(QUOTA_PAUSE_SECONDS)
            quota_paused = False
            print("  [QUOTA] Resuming after pause...")
        else:
            time.sleep(10)

    return summary


def print_summary(summary: dict, results_dir: Path) -> None:
    """Print results table and save to results_dir/summary.json."""
    print(f"\n{'='*60}")
    print(f"Parallel Backtest Results")
    print(f"{'='*60}")
    ok = sum(1 for v in summary.values() if v["exit_code"] == 0)
    fail = len(summary) - ok
    print(f"  {ok} succeeded, {fail} failed")
    print()
    for label, info in sorted(summary.items()):
        status = "OK" if info["exit_code"] == 0 else f"FAIL({info['exit_code']})"
        print(f"  {label:<35} {status:<10} {info['elapsed_min']:.1f}min  {Path(info['log_path']).name}")

    out_file = results_dir / "summary.json"
    with open(out_file, "w") as f:
        json.dump({
            "generated": datetime.now(timezone.utc).isoformat(),
            "results": summary,
        }, f, indent=2)
    print(f"\nSummary saved to {out_file}")

    # Quick PnL scrape from each log
    print(f"\n--- PnL Summary (scraped from logs) ---")
    for label, info in sorted(summary.items()):
        if info["exit_code"] != 0:
            print(f"  {label}: FAILED")
            continue
        try:
            log_text = Path(info["log_path"]).read_text(errors="replace")
            # Look for "Net PnL" or "Total PnL" lines
            for line in log_text.splitlines():
                if "net pnl" in line.lower() or "total pnl" in line.lower() or "win rate" in line.lower():
                    print(f"  {label}: {line.strip()}")
                    break
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Parallel backtest runner (Lever 4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--jobs", nargs="+", required=True,
        help="Job specs: SYMBOL:DAYS[:START_DATE]. E.g. BTC:15:2026-01-15"
    )
    parser.add_argument("--budget", type=float, default=4.0,
                        help="LLM budget per job in USD (default 4.0)")
    parser.add_argument("--llm", action="store_true",
                        help="Enable LLM agents (default: False)")
    parser.add_argument("--raw", action="store_true",
                        help="Raw mode: disable circuit breakers (for research)")
    parser.add_argument("--extra", nargs="*", default=[],
                        help="Extra args passed verbatim to each run.py backtest call")
    args = parser.parse_args()

    if len(args.jobs) > MAX_CONCURRENT:
        print(f"Warning: {len(args.jobs)} jobs exceeds MAX_CONCURRENT={MAX_CONCURRENT}. Capping.")
        args.jobs = args.jobs[:MAX_CONCURRENT]

    jobs = []
    for j in args.jobs:
        try:
            jobs.append(parse_job(j))
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    results_dir = _RESULTS_BASE / timestamp

    print(f"Parallel backtest: {len(jobs)} jobs, budget=${args.budget:.2f}/job, llm={args.llm}")
    print(f"Results dir: {results_dir}")
    print()

    t0 = time.time()
    summary = run_parallel(jobs, args.budget, args.llm, args.raw, args.extra or [], results_dir)
    elapsed = (time.time() - t0) / 60
    print(f"\nAll jobs complete in {elapsed:.1f}min (wall-clock)")

    print_summary(summary, results_dir)


if __name__ == "__main__":
    main()
