"""
FULL-SYSTEM HISTORICAL REPLAY harness.

Owner directive: "use historical chart data with our full system triggering
Claude and everything to emulate; that gives us data to replicate to live."

Replays historical candles through the REAL pipeline — ensemble -> risk gates
-> 9-agent LLM coordinator (CLI-routed `claude -p`) -> the restored
profit-lock exit engine — and records honest closes. This manufactures the
clean-close sample without waiting on live time.

TOTAL ISOLATION (hard constraint): the replay runs in a CODE SANDBOX — a copy
of the bot's code under bot/data/replay/<run_id>/sandbox/ with a fresh, empty
data/ tree. Both relative paths ("data/...") and __file__-anchored paths
(llm/agents stores, ml_data, logs) resolve INSIDE the sandbox, so no
production writer can reach production data by construction. Isolation is
additionally verified by a before/after snapshot diff of production bot/data.

Point-in-time honesty: the sandbox's memory/rules/stats stores start EMPTY,
so no future knowledge leaks into prompts (caveat: the live bot has
accumulated memory that the replay brain lacks — reported honestly).

Usage (from bot/):
    python tools/replay_harness.py --start 2026-06-20 --end 2026-06-27 \
        --symbols BTC,ETH,SOL --max-llm-calls 60 --sleep 15

Outputs:
    bot/data/replay/<run_id>/replay_trades.csv   (production trades.csv schema)
    bot/data/replay/<run_id>/run.log, isolation_report.json, sandbox/...
    coordination/REPLAY_RUN_<run_id>.md          (run report per THE_STANDARD)
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent          # bot/
REPO_DIR = BOT_DIR.parent                                  # WAGMI/
REPLAY_ROOT = BOT_DIR / "data" / "replay"

# Code dirs copied into the sandbox (everything the pipeline can import).
CODE_DIRS = [
    "alerts", "analytics", "backtest", "bot", "classification", "config",
    "core", "engine", "execution", "feedback", "learning", "llm", "manual",
    "ml", "monitoring", "optimization", "research", "risk", "rl", "scripts",
    "signals", "social", "strategies", "tools", "validation", "wallet",
]
COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", "*.log",
)
# Production data trees snapshotted for the isolation proof.
ISOLATION_SCOPE = ["data", "ml_data", "backtest_ml_data"]
# The whole trade lifecycle actions that count as a final close.
FINAL_CLOSE_ACTIONS = ("SL", "TP2", "TRAILING_STOP", "EARLY_EXIT",
                       "LLM_EXIT_AGENT", "CIRCUIT_BREAKER", "HOLD_LIMIT",
                       "FORCE_CLOSE", "TIME_STOP")

TRADES_CSV_COLUMNS = [
    "timestamp", "symbol", "side", "entry", "exit", "tp1_hit", "tp2_hit",
    "sl_hit", "trailing_hit", "early_exit", "pnl", "fees",
    "ml_samples_at_entry", "ml_samples_at_exit", "ml_conf_at_entry",
    "ml_conf_at_exit", "state_path", "outcome", "leverage", "confidence",
    "strategy", "entry_reasons", "entry_type", "primary_driver", "regime",
    "volatility_band",
]


# ── Sandbox construction ─────────────────────────────────────────────


def build_sandbox(run_dir: Path) -> Path:
    """Copy the bot's CODE (never its data) into an isolated sandbox."""
    sandbox = run_dir / "sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)

    # Top-level code + env
    for f in BOT_DIR.glob("*.py"):
        shutil.copy2(f, sandbox / f.name)
    env_file = BOT_DIR / ".env"
    if env_file.exists():
        shutil.copy2(env_file, sandbox / ".env")

    # Package dirs
    for d in CODE_DIRS:
        src = BOT_DIR / d
        if src.is_dir():
            shutil.copytree(src, sandbox / d, ignore=COPY_IGNORE)

    # bot/data is a hybrid: code package + runtime data. Copy ONLY the code.
    data_pkg = sandbox / "data"
    data_pkg.mkdir()
    for f in (BOT_DIR / "data").glob("*.py"):
        shutil.copy2(f, data_pkg / f.name)
    fetchers_src = BOT_DIR / "data" / "fetchers"
    if fetchers_src.is_dir():
        shutil.copytree(fetchers_src, data_pkg / "fetchers", ignore=COPY_IGNORE)

    # Fresh runtime skeleton (empty stores = no future knowledge in prompts)
    for sub in ["analysis", "cache", "llm", "llm/deep_memory", "llm/teaching",
                "feedback", "logs", "portfolio_risk", "ml", "learning",
                "counterfactuals", "position_backups", "manual",
                "backtest_checkpoints"]:
        (data_pkg / sub).mkdir(parents=True, exist_ok=True)
    for extra in ["logs", "ml_data", "backtest_ml_data", "replay_out",
                  "backtest_results", "analysis"]:
        (sandbox / extra).mkdir(exist_ok=True)

    # Marker: the runner refuses to start without it.
    (sandbox / ".replay_sandbox").write_text(
        f"replay sandbox built {datetime.now(timezone.utc).isoformat()}\n")
    return sandbox


# ── Isolation proof ──────────────────────────────────────────────────


def snapshot_production_data() -> dict:
    """Snapshot (size, mtime_ns) of every production data file.

    Excludes bot/data/replay (the harness's own output root).
    """
    snap = {}
    for scope in ISOLATION_SCOPE:
        root = BOT_DIR / scope
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(BOT_DIR)).replace("\\", "/")
            if rel.startswith("data/replay/"):
                continue
            try:
                st = p.stat()
                snap[rel] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    # Also watch the live ledger at bot/trades.csv (legacy location)
    for extra in ["trades.csv"]:
        p = BOT_DIR / extra
        if p.is_file():
            st = p.stat()
            snap[extra] = (st.st_size, st.st_mtime_ns)
    return snap


def diff_snapshots(before: dict, after: dict) -> dict:
    changed = sorted(k for k in before.keys() & after.keys()
                     if before[k] != after[k])
    created = sorted(after.keys() - before.keys())
    deleted = sorted(before.keys() - after.keys())
    return {"changed": changed, "created": created, "deleted": deleted}


# ── Post-processing: production-schema trades CSV ────────────────────


def _load_jsonl(path: Path) -> list:
    rows = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def build_replay_trades_csv(sandbox: Path, run_dir: Path) -> list:
    """Pair OPEN -> final close events into production trades.csv schema."""
    events = _load_jsonl(sandbox / "replay_out" / "trade_events.jsonl")
    decisions = _load_jsonl(sandbox / "data" / "llm" / "backtest_decisions.jsonl")

    # Latest approved LLM thesis per symbol (in decision order) for joining
    theses_by_symbol = {}
    for d in decisions:
        if d.get("symbol") and d.get("action") not in (None, "flat"):
            notes = d.get("notes", "")
            if notes:
                theses_by_symbol.setdefault(d["symbol"], []).append(notes)

    trades = []
    open_by_symbol = {}
    thesis_cursor = {}
    for ev in events:
        sym = ev["symbol"]
        if ev["action"] == "OPEN":
            # Attach the next unconsumed thesis for this symbol
            idx = thesis_cursor.get(sym, 0)
            sym_theses = theses_by_symbol.get(sym, [])
            ev["_thesis"] = sym_theses[idx] if idx < len(sym_theses) else ""
            thesis_cursor[sym] = idx + 1
            open_by_symbol[sym] = ev
        elif ev["action"] in FINAL_CLOSE_ACTIONS:
            meta = ev.get("metadata", {}) or {}
            open_ev = open_by_symbol.pop(sym, {})
            open_meta = (open_ev.get("metadata") or {})
            state_path = meta.get("state_path", "")
            entry_reasons = dict(meta.get("entry_reasons")
                                 or open_meta.get("entry_reasons") or {})
            thesis = open_ev.get("_thesis", "")
            if thesis:
                entry_reasons["thesis"] = thesis[:300]
            entry_reasons["replay"] = True
            entry_reasons["mfe_pct"] = meta.get("mfe_pct", 0)
            entry_reasons["mae_pct"] = meta.get("mae_pct", 0)
            entry_reasons["funding_costs"] = round(
                float(meta.get("funding_costs", 0) or 0), 4)
            entry_reasons["exit_action"] = ev["action"]

            trades.append({
                "timestamp": meta.get("close_sim_time") or ev.get("timestamp", ""),
                "symbol": sym,
                "side": ev.get("side", ""),
                "entry": meta.get("entry", open_ev.get("price", 0)),
                "exit": ev.get("price", 0),
                "tp1_hit": "TP1_HIT" in state_path or "TP1" in state_path,
                "tp2_hit": ev["action"] == "TP2",
                "sl_hit": ev["action"] == "SL",
                "trailing_hit": ev["action"] == "TRAILING_STOP",
                "early_exit": ev["action"] in
                              ("EARLY_EXIT", "LLM_EXIT_AGENT", "TIME_STOP"),
                "pnl": round(float(meta.get("total_pnl", ev.get("pnl", 0)) or 0), 4),
                "fees": round(float(meta.get("total_fees", ev.get("fee", 0)) or 0), 4),
                "ml_samples_at_entry": 0,
                "ml_samples_at_exit": 0,
                "ml_conf_at_entry": "0.0000",
                "ml_conf_at_exit": "0.0000",
                "state_path": state_path,
                "outcome": meta.get("outcome", ""),
                "leverage": ev.get("leverage", 1.0),
                "confidence": meta.get("confidence",
                                       open_meta.get("confidence", 0)),
                "strategy": ev.get("strategy", ""),
                "entry_reasons": json.dumps(entry_reasons),
                "entry_type": meta.get("entry_type", ""),
                "primary_driver": meta.get("primary_driver", ""),
                "regime": meta.get("regime", ""),
                "volatility_band": meta.get("volatility_band", ""),
            })

    out_path = run_dir / "replay_trades.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADES_CSV_COLUMNS)
        w.writeheader()
        for t in trades:
            w.writerow(t)
    return trades


# ── Run report ───────────────────────────────────────────────────────


def _split_stats(trades: list, key_fn) -> dict:
    groups = {}
    for t in trades:
        groups.setdefault(key_fn(t), []).append(t)
    out = {}
    for k, ts in sorted(groups.items()):
        wins = sum(1 for t in ts if float(t["pnl"]) > 0)
        out[k] = {
            "n": len(ts),
            "wins": wins,
            "wr": round(wins / len(ts) * 100, 1) if ts else 0,
            "pnl": round(sum(float(t["pnl"]) for t in ts), 2),
        }
    return out


def write_run_report(run_id: str, run_dir: Path, sandbox: Path,
                     trades: list, isolation: dict, elapsed_min: float,
                     args) -> Path:
    summary = {}
    summary_path = sandbox / "replay_out" / "llm_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    journal = _load_jsonl(sandbox / "data" / "replay_llm_journal.jsonl")

    n = len(trades)
    wins = sum(1 for t in trades if float(t["pnl"]) > 0)
    net_pnl = round(sum(float(t["pnl"]) for t in trades), 2)
    total_fees = round(sum(float(t["fees"]) for t in trades), 2)
    llm_calls = summary.get("llm_calls", 0)
    by_side = _split_stats(trades, lambda t: t["side"])
    by_regime = _split_stats(trades, lambda t: t["regime"] or "unknown")

    closes_per_60 = round(n / max(llm_calls, 1) * 60, 1)
    prod_touched = isolation["changed"] + isolation["created"] + isolation["deleted"]

    lines = [
        f"# REPLAY_RUN_{run_id} — full-system historical replay",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        f"by tools/replay_harness.py (THE_STANDARD v1.3 compliant reporting)",
        "",
        "## What this is",
        "Historical candles replayed through the REAL pipeline: ensemble -> "
        "RiskFilterChain (6 gates) -> 9-agent LLM coordinator (CLI-routed "
        "claude -p, default agent models) -> restored profit-lock exit engine "
        "(PositionManager: TP1 partial + BE stop, progressive trailing, 5m "
        "intra-bar fills). Manufactured clean-close sample for the live ledger.",
        "",
        "## Window & config",
        f"- Window: {args.start} -> {args.end} (walk); fetch depth {args.days}d "
        f"(extra = indicator warmup)",
        f"- Symbols: {args.symbols}",
        f"- Starting equity: ${args.equity:.0f} (matches live account scale)",
        f"- Fee model: {summary.get('fee_model', {})} "
        "(taker both sides; entry slippage rescales SL/TP proportionally; "
        "exit slippage on stop fills; conservative worst->best->close fill "
        "order inside each bar)",
        f"- LLM cap: {args.max_llm_calls} calls, sleep {args.sleep}s/pipeline "
        "(live-bot quota protection)",
        "",
        "## Results",
        f"- Closes generated: {n}",
        f"- Win rate: {round(wins / n * 100, 1) if n else 0}% ({wins}W/{n - wins}L)",
        f"- Net PnL (after fees+funding): ${net_pnl:+.2f} on ${args.equity:.0f} "
        f"equity | fees paid ${total_fees:.2f}",
        f"- Final equity: ${summary.get('final_equity', 0):.2f}",
        f"- Per-side: {json.dumps(by_side)}",
        f"- Per-regime: {json.dumps(by_regime)}",
        "",
        "## LLM usage (honest accounting)",
        f"- Total LLM calls: {llm_calls} (cap {summary.get('call_cap')}; "
        f"cap reached: {summary.get('call_cap_reached')})",
        f"- Journal entries: {len(journal)} | failures: "
        f"{summary.get('llm_failures', 0)} | pre-filter skips: "
        f"{summary.get('pre_filter_skips', 0)}",
        f"- Entry-event filter: {summary.get('replay_entry_events', 'n/a')} "
        f"qualifying events | starved by caps: "
        f"{summary.get('replay_starved_events', 'n/a')} | cooldown-suppressed: "
        f"{summary.get('replay_cooldown_skips', 'n/a')} | per-symbol calls: "
        f"{json.dumps(summary.get('replay_symbol_calls', {}))}",
        f"- Wall time: {elapsed_min:.0f} min",
        f"- SCALING MATH: ~{closes_per_60} closes per 60 LLM calls at this "
        f"signal density ({n} closes / {llm_calls} calls)",
        "",
        "## Isolation proof",
        f"- Sandbox: bot/data/replay/{run_id}/sandbox (code copy + empty data "
        "tree; runner refuses to start outside a marked sandbox)",
        f"- Production data diff (bot/data, bot/ml_data, bot/backtest_ml_data, "
        f"bot/trades.csv; before vs after): "
        f"{len(prod_touched)} paths changed",
    ]
    if prod_touched:
        lines.append("- CHANGED PATHS (expected: live-bot churn only — the "
                     "replay process has no handle to these by construction; "
                     "verify none are backtest/replay artifacts):")
        for p in prod_touched[:40]:
            lines.append(f"    - {p}")
    else:
        lines.append("- ZERO production files changed during the run.")
    lines += [
        "",
        "## Fidelity caveats (honest, per THE_STANDARD)",
        "- EMPTY MEMORY: the replay brain starts with empty memory/rules/"
        "stats stores (prevents future-knowledge leaks, but the live bot "
        "carries accumulated memory the replay lacks).",
        "- SNAPSHOT SCOPE: replay prompts contain candle-derived stats only "
        "(price changes, volume ratio, ATR); live prompts also carry "
        "funding/OI/intel feeds not reconstructed point-in-time here.",
        "- FILL MODEL: 1h bars with 5m intra-bar sub-fills where 5m data "
        "exists; stop fills assume candle-low/high touch = fill (conservative)"
        "; funding approximated at a flat rate per 8h.",
        "- NON-DETERMINISM: LLM outputs vary run-to-run; a replay is one "
        "sample of the policy, not a deterministic backtest.",
        "- REPLAY_MODE veto rule: entries with no LLM opinion (failure/cap/"
        "pre-filter) are skipped, not traded mechanically — the sample is "
        "100% LLM-approved trades (live has a mechanical fallback path).",
        "",
        f"Artifacts: bot/data/replay/{run_id}/replay_trades.csv, run.log, "
        f"isolation_report.json, sandbox/replay_out/*",
    ]

    report_path = REPO_DIR / "coordination" / f"REPLAY_RUN_{run_id}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ── Main ─────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Full-system historical replay")
    ap.add_argument("--symbols", default="BTC,ETH,SOL")
    ap.add_argument("--start", required=True, help="walk start (YYYY-MM-DD)")
    ap.add_argument("--end", required=True, help="walk end (YYYY-MM-DD)")
    ap.add_argument("--days", type=int, default=11,
                    help="fetch depth back from --end (extra = warmup)")
    ap.add_argument("--equity", type=float, default=500.0)
    ap.add_argument("--budget", type=float, default=5.0,
                    help="LLM budget USD (secondary to call cap)")
    ap.add_argument("--max-llm-calls", type=int,
                    default=int(os.getenv("REPLAY_MAX_LLM_CALLS", "60")))
    ap.add_argument("--sleep", type=float, default=15.0,
                    help="seconds between LLM pipelines (quota protection)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--timeout-min", type=int, default=240)
    ap.add_argument("--post-only", action="store_true",
                    help="skip the run; post-process an existing run dir "
                         "(salvage after a harness/session crash)")
    ap.add_argument("--elapsed-min", type=float, default=0.0,
                    help="wall minutes to report in --post-only mode")
    args = ap.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    run_dir = REPLAY_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.post_only:
        sandbox = run_dir / "sandbox"
        before_raw = json.loads(
            (run_dir / "isolation_before.json").read_text(encoding="utf-8"))
        before = {k: tuple(v) for k, v in before_raw.items()}
        after = snapshot_production_data()
        isolation = diff_snapshots(before, after)
        (run_dir / "isolation_report.json").write_text(
            json.dumps(isolation, indent=2), encoding="utf-8")
        trades = build_replay_trades_csv(sandbox, run_dir)
        print(f"[HARNESS] {len(trades)} closes -> {run_dir / 'replay_trades.csv'}")
        report_path = write_run_report(
            run_id, run_dir, sandbox, trades, isolation,
            args.elapsed_min, args)
        print(f"[HARNESS] run report -> {report_path}")
        return 0

    print(f"[HARNESS] run_id={run_id}")
    print("[HARNESS] building sandbox (code copy, empty data tree)...")
    sandbox = build_sandbox(run_dir)

    print("[HARNESS] snapshotting production data for isolation proof...")
    before = snapshot_production_data()
    (run_dir / "isolation_before.json").write_text(
        json.dumps(before), encoding="utf-8")

    env = dict(os.environ)
    env.update({
        "REPLAY_MODE": "1",
        "USE_CLI_LLM": "true",
        "REPLAY_SYMBOLS": args.symbols,
        "REPLAY_START": args.start,
        "REPLAY_END": args.end,
        "REPLAY_DAYS": str(args.days),
        "REPLAY_EQUITY": str(args.equity),
        "REPLAY_BUDGET_USD": str(args.budget),
        "REPLAY_MAX_LLM_CALLS": str(args.max_llm_calls),
        "REPLAY_LLM_SLEEP_S": str(args.sleep),
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(sandbox),
        # Keep the sandbox off the API-billing path even if .env has a key
        "ANTHROPIC_API_KEY": "",
    })

    log_path = run_dir / "run.log"
    print(f"[HARNESS] launching replay subprocess (log: {log_path})...")
    started = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        proc = subprocess.Popen(
            [sys.executable, "tools/replay_runner.py"],
            cwd=str(sandbox), env=env,
            stdout=logf, stderr=subprocess.STDOUT,
        )
        try:
            rc = proc.wait(timeout=args.timeout_min * 60)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = -9
            print("[HARNESS] TIMEOUT — subprocess killed")
    elapsed_min = (time.time() - started) / 60

    print(f"[HARNESS] subprocess exited rc={rc} after {elapsed_min:.1f} min")

    print("[HARNESS] verifying isolation...")
    after = snapshot_production_data()
    isolation = diff_snapshots(before, after)
    (run_dir / "isolation_report.json").write_text(
        json.dumps(isolation, indent=2), encoding="utf-8")
    touched = isolation["changed"] + isolation["created"] + isolation["deleted"]
    print(f"[HARNESS] isolation diff: {len(touched)} production paths "
          f"changed (live-bot churn expected; replay artifacts NOT expected)")

    print("[HARNESS] building replay_trades.csv...")
    trades = build_replay_trades_csv(sandbox, run_dir)
    print(f"[HARNESS] {len(trades)} closes -> {run_dir / 'replay_trades.csv'}")

    report_path = write_run_report(
        run_id, run_dir, sandbox, trades, isolation, elapsed_min, args)
    print(f"[HARNESS] run report -> {report_path}")

    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
