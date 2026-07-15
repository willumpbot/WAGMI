#!/usr/bin/env python
"""WAGMI data-integrity report — read-only, LLM-FREE, ZERO trading-path contact.

Counts contamination / growth in the counterfactual + trade stores so the owner
can see whether it's getting WORSE and can validate the eventual resolver fix
(see coordination/RESOLVER_AUDIT_2026-07-13.md, which found ~4,685 dup lines,
812 evicted-zero, 41 test rows). REPORTS NUMBERS ONLY — no fixes here (resolver
fixes touch the live veto path → owner queue).

Runs standalone (`python tools/data_integrity_report.py`) or as part of
weekly_research.py. Revert: delete this file (+ remove from weekly_research.py).
"""
import os
import json
import glob
import shutil

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BOT_DIR, "data")


def _jsonl_integrity(path):
    total = unique = dupes = test_rows = unparsable = resolved = pending = zero_pnl = 0
    seen = set()
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    rec = json.loads(line)
                except Exception:
                    unparsable += 1
                    continue
                if not isinstance(rec, dict):
                    continue
                rid = rec.get("record_id")
                if rid is not None:
                    if rid in seen:
                        dupes += 1
                    else:
                        seen.add(rid)
                        unique += 1
                rsn = (str(rec.get("skip_reason", "")) + str(rec.get("reason", ""))).lower()
                if "test" in rsn:
                    test_rows += 1
                if rec.get("resolved") is True:
                    resolved += 1
                elif rec.get("resolved") is False:
                    pending += 1
                try:
                    if float(rec.get("hypothetical_pnl_pct", 1)) == 0.0:
                        zero_pnl += 1
                except Exception:
                    pass
    except FileNotFoundError:
        return None
    except Exception as e:
        return {"error": str(e)}
    return dict(total=total, unique=unique, dupes=dupes, test_rows=test_rows,
                unparsable=unparsable, resolved=resolved, pending=pending, zero_pnl=zero_pnl)


def _linecount(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return None


def main():
    print(f"WAGMI data-integrity report — {DATA}")

    found = False
    for path in sorted(glob.glob(os.path.join(DATA, "**", "counterfactual*.jsonl"), recursive=True)):
        r = _jsonl_integrity(path)
        if not r:
            continue
        found = True
        rel = os.path.relpath(path, BOT_DIR)
        if "error" in r:
            print(f"\n{rel}: ERROR {r['error']}")
            continue
        print(f"\n{rel}:")
        print(f"  lines={r['total']} unique_ids={r['unique']} DUPES={r['dupes']} "
              f"test_rows={r['test_rows']} unparsable={r['unparsable']}")
        print(f"  resolved={r['resolved']} pending={r['pending']} zero_pnl={r['zero_pnl']}")
    if not found:
        print("\n(no counterfactual*.jsonl found)")

    scen = os.path.join(DATA, "counterfactuals", "scenarios.json")
    if os.path.exists(scen):
        try:
            d = json.load(open(scen, encoding="utf-8"))
            n = len(d) if isinstance(d, (list, dict)) else "?"
            print(f"\ndata/counterfactuals/scenarios.json: entries={n}")
        except Exception as e:
            print(f"\nscenarios.json: unreadable ({e})")

    tc = _linecount(os.path.join(DATA, "trades.csv"))
    tl = _linecount(os.path.join(DATA, "trade_ledger.csv"))
    delta = f"  DELTA={abs((tc or 0) - (tl or 0))}" if (tc and tl) else ""
    print(f"\ntrades.csv rows={tc}  trade_ledger.csv rows={tl}{delta}")

    try:
        u = shutil.disk_usage(DATA)
        print(f"\ndisk: free={u.free/1e9:.1f}GB / {u.total/1e9:.1f}GB ({u.free/u.total*100:.0f}% free)")
    except Exception:
        pass


if __name__ == "__main__":
    main()
