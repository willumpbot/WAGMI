#!/usr/bin/env python3
"""
Reconstruct trade_ledger entries from bot logs that the P1 CSV write bug ate.

For every [TRADE_CLOSED] event in bot/logs/bot_*.log, check if a matching
ledger row exists. If not, write a reconstructed row.

Run from repo root:
  python coordination/rebuild_ledger_from_logs.py           # show what's missing
  python coordination/rebuild_ledger_from_logs.py --write   # append to ledger
"""
import csv
import json
import os
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
import hashlib

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "bot" / "data" / "trade_ledger.csv"
WRITE = "--write" in sys.argv

LEDGER_HEADERS = [
    "trade_id", "timestamp", "symbol", "side", "regime_1h", "regime_4h",
    "agreement_level", "contributing_factors", "confidence_score",
    "kelly_weight_applied", "compound_size_multiplier", "leverage",
    "hold_hours", "exit_type", "entry_price", "snapshot_entry",
    "exit_price", "gross_pnl", "fees", "funding", "net_pnl",
    "running_equity", "session_dd_pct", "ab_gate_hash",
]


def load_ledger_keys():
    """Return set of (symbol, timestamp_floor) for existing ledger rows."""
    keys = set()
    if LEDGER.exists():
        with open(LEDGER) as f:
            for row in csv.DictReader(f):
                try:
                    ts = int(float(row.get("timestamp", 0)))
                    keys.add((row.get("symbol", ""), ts))
                except Exception:
                    pass
    return keys


def parse_log_closes(log_path: Path):
    """Yield (timestamp, parsed_event) for every TRADE_CLOSED in the log."""
    if not log_path.exists():
        return
    with open(log_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("msg", "").startswith("[TRADE_CLOSED]"):
                    data = rec.get("data", {})
                    if data.get("event") == "TRADE_CLOSED":
                        ts_str = rec.get("ts", "")
                        yield ts_str, data
            except Exception:
                pass


def make_trade_id(symbol: str, ts: float) -> str:
    h = hashlib.md5(f"{symbol}{ts}".encode()).hexdigest()
    return h[:12]


def build_row(ts_str: str, ev: dict) -> dict:
    """Build a ledger row from a TRADE_CLOSED log event."""
    # Parse timestamp
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        ts_epoch = dt.timestamp()
    except Exception:
        ts_epoch = 0
    sym = ev.get("symbol", "")
    entry = float(ev.get("entry_price", 0) or 0)
    exit_p = float(ev.get("exit_price", 0) or 0)
    side = ev.get("side", "")
    pnl = float(ev.get("pnl", 0) or 0)
    hold_s = float(ev.get("hold_time", 0) or 0)
    lev = float(ev.get("leverage", 0) or 0)
    regime = ev.get("regime", "") or "unknown"
    exit_reason = ev.get("exit_reason", "")
    return {
        "trade_id": make_trade_id(sym, ts_epoch),
        "timestamp": str(ts_epoch),
        "symbol": sym,
        "side": side,
        "regime_1h": regime,
        "regime_4h": "",
        "agreement_level": "1",
        "contributing_factors": "RECONSTRUCTED_FROM_LOG",
        "confidence_score": str(ev.get("confidence", 0) or 0),
        "kelly_weight_applied": "",
        "compound_size_multiplier": "",
        "leverage": str(lev),
        "hold_hours": f"{hold_s/3600:.2f}",
        "exit_type": exit_reason,
        "entry_price": str(entry),
        "snapshot_entry": "",
        "exit_price": str(exit_p),
        "gross_pnl": str(round(pnl, 2)),
        "fees": "",
        "funding": "0",
        "net_pnl": str(round(pnl, 2)),
        "running_equity": "",
        "session_dd_pct": "",
        "ab_gate_hash": "",
    }


def main():
    print(f"Ledger: {LEDGER}")
    existing = load_ledger_keys()
    print(f"Existing ledger rows: {len(existing)}\n")

    log_dir = REPO_ROOT / "bot" / "logs"
    logs = sorted(log_dir.glob("bot_2026*.log"))
    missing = []
    matched = []
    for log in logs:
        for ts_str, ev in parse_log_closes(log):
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts_floor = int(dt.timestamp())
            except Exception:
                ts_floor = 0
            sym = ev.get("symbol", "")
            # Fuzzy match within +/-2s in case of slight precision diff
            key_matched = any(
                k[0] == sym and abs(k[1] - ts_floor) <= 2
                for k in existing
            )
            if key_matched:
                matched.append((log.name, ts_str, ev))
            else:
                missing.append((log.name, ts_str, ev))

    print(f"Logged closes: {len(matched) + len(missing)}")
    print(f"  In ledger: {len(matched)}")
    print(f"  MISSING from ledger: {len(missing)}\n")

    if missing:
        print("Missing closes by day:")
        by_day = {}
        for log_name, ts_str, ev in missing:
            day = ts_str[:10]
            by_day.setdefault(day, []).append((ts_str, ev))
        for day in sorted(by_day):
            evs = by_day[day]
            total_pnl = sum(float(e.get("pnl", 0) or 0) for _, e in evs)
            print(f"  {day}: {len(evs)} closes, total PnL=${total_pnl:+.2f}")
            for ts, ev in evs[:3]:
                print(f"    {ts} {ev.get('symbol')} {ev.get('side')} {ev.get('exit_reason')} pnl={ev.get('pnl',0):+.2f}")
        print()

    if WRITE and missing:
        # Backup ledger first
        bk = LEDGER.with_suffix(f".csv.bak.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(LEDGER, bk)
        print(f"Backup: {bk.name}")

        # Append missing rows
        with open(LEDGER, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
            for log_name, ts_str, ev in missing:
                row = build_row(ts_str, ev)
                w.writerow(row)
        print(f"APPENDED {len(missing)} reconstructed rows to ledger")
        print(f"Run again without --write to verify count")
    elif missing:
        print(f"Use --write to append {len(missing)} reconstructed rows to ledger")
    else:
        print("Ledger is complete. Nothing to reconstruct.")


if __name__ == "__main__":
    main()
