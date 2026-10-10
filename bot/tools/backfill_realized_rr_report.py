"""READ-ONLY one-off: how many historical trade_ledger.csv rows could have
realized_rr / stop_initial backfilled? (LEDGER_RR_FIX, 2026-10-10)

Prints a report only. Opens every file read-only and writes NOTHING.

Why rows are blank: realized_rr was computed by the close handler since
2026-03 but was not in LEDGER_COLUMNS until RR_ZERO_FIX (2026-07-14), so
record_trade() silently dropped it -> every row before 2026-07-15 is blank.
That is an ERA artifact, not an exit-path one; the apparent
outcome-dependence (TP2/TIME_STOP/TRAILING 0-5% vs LLM_EXIT_HIGH 97%)
is because those exit types were common before the fix and LLM_EXIT_HIGH
only appeared after it.

Sources, in the order tried per blank row:
  1. data/trade_events.jsonl TRADE_OPENED (entry, sl = INITIAL stop,
     position_size = qty at open, leverage), matched on symbol + side +
     entry price (rel tol 1e-6), latest open at/before the ledger close
     timestamp. Fake/test events excluded via
     core.structured_logging.is_fake_trade_event.
  2. data/position_journal.jsonl OPEN (entry + qty, NO stop) -- only
     counted as "qty-only" (cannot produce R without a stop).
  data/trades.csv carries neither stop nor qty -> listed for completeness.

Leverage: the ledger's net_pnl is in base (de-leveraged) units for every
row (2026-07-24 migration + PNL_LEVERAGE_FIX=true), so the estimate uses a
leverage factor of 1.0 -- the same convention the live writer now uses.

Usage:  python tools/backfill_realized_rr_report.py [--data-dir PATH]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _is_fake(evt: dict) -> bool:
    try:
        from core.structured_logging import is_fake_trade_event
        return bool(is_fake_trade_event(evt))
    except Exception:
        return False


def _ts(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return 0.0


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _side(s: str) -> str:
    s = (s or "").upper()
    return {"BUY": "LONG", "SELL": "SHORT"}.get(s, s)


def _same_px(a: float, b: float) -> bool:
    return a > 0 and b > 0 and abs(a - b) / max(a, b) < 1e-6


def load_opens(path: str):
    opens = defaultdict(list)  # (symbol, side) -> [(ts, entry, sl, qty, lev)]
    n = fake = 0
    if not os.path.exists(path):
        return opens, n, fake
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"TRADE_OPENED"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            n += 1
            if _is_fake(e):
                fake += 1
                continue
            opens[(e.get("symbol"), _side(e.get("side")))].append((
                _ts(e.get("timestamp")), _f(e.get("entry")), _f(e.get("sl")),
                _f(e.get("position_size")), _f(e.get("leverage"), 1.0),
            ))
    for v in opens.values():
        v.sort()
    return opens, n, fake


def load_journal_opens(path: str):
    out = defaultdict(list)  # (symbol, side) -> [(ts, entry, qty)]
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("phase") != "OPEN":
                continue
            m = e.get("meta") or {}
            out[(e.get("symbol"), _side(m.get("side")))].append(
                (_ts(e.get("ts")), _f(m.get("entry")), _f(m.get("qty"))))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    args = ap.parse_args(argv)
    d = os.path.abspath(args.data_dir)

    ledger_path = os.path.join(d, "trade_ledger.csv")
    with open(ledger_path, "r", newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    opens, n_open_evts, n_fake = load_opens(os.path.join(d, "trade_events.jsonl"))
    jopens = load_journal_opens(os.path.join(d, "position_journal.jsonl"))

    blank = [r for r in rows if (r.get("realized_rr") or "") == ""]
    print(f"data dir: {d}")
    print(f"ledger rows: {len(rows)}   realized_rr blank: {len(blank)} "
          f"({len(blank) / max(len(rows), 1):.0%})")
    print(f"trade_events TRADE_OPENED: {n_open_evts} (fake/test excluded: {n_fake})")

    by_exit = defaultdict(Counter)
    est_by_exit = defaultdict(list)
    sl_mismatch = 0
    for r in blank:
        et = r.get("exit_type", "?")
        key = (r.get("symbol"), _side(r.get("side")))
        entry = _f(r.get("entry_price"))
        close_ts = _ts(r.get("timestamp"))
        cands = [o for o in opens.get(key, []) if o[0] <= close_ts + 1 and _same_px(o[1], entry)]
        if cands:
            _, e_entry, e_sl, e_qty, _lev = cands[-1]
            if e_sl > 0 and e_qty > 0 and abs(e_entry - e_sl) > 0:
                rr = _f(r.get("net_pnl")) / (abs(e_entry - e_sl) * e_qty)
                by_exit[et]["backfillable"] += 1
                est_by_exit[et].append(rr)
                continue
            sl_mismatch += 1
        if any(o[0] <= close_ts + 1 and _same_px(o[1], entry) for o in jopens.get(key, [])):
            by_exit[et]["qty_only(journal, no stop)"] += 1
        else:
            by_exit[et]["no_source"] += 1

    print("\nblank rows by exit_type -> recoverability:")
    tot = Counter()
    for et in sorted(by_exit, key=lambda k: -sum(by_exit[k].values())):
        c = by_exit[et]
        tot.update(c)
        rr = sorted(est_by_exit.get(et, []))
        med = f"  median est R={rr[len(rr) // 2]:+.2f}" if rr else ""
        print(f"  {et:<18} n={sum(c.values()):>4}  " +
              "  ".join(f"{k}={v}" for k, v in sorted(c.items())) + med)
    print(f"\nTOTAL backfillable (stop+qty found): {tot['backfillable']} / {len(blank)}")
    print(f"qty-only (journal, no stop -> NOT backfillable): {tot['qty_only(journal, no stop)']}")
    print(f"no source: {tot['no_source']}   (matched open w/o usable sl/qty: {sl_mismatch})")
    print("\nNOTE: estimate only (factor-1 leverage, latest matching open). "
          "This script modified nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
