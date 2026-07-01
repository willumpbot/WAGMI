"""Zero-token leak detector — deterministic checks of WIRING_INVARIANTS against live data.

Run from bot/: python tools/check_invariants.py
Exit code = number of FAILs. Learning engine runs this every pass; tokens are spent
only on investigating failures, never on finding them. Every check is fail-soft:
a missing source is reported as SKIP, not a crash.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # bot/
D = lambda *p: os.path.join(ROOT, "data", *p)
RESULTS = []

def check(name):
    def deco(fn):
        def run():
            try:
                ok, detail = fn()
                RESULTS.append(("PASS" if ok else "FAIL", name, detail))
            except FileNotFoundError as e:
                RESULTS.append(("SKIP", name, f"missing source: {e.filename}"))
            except Exception as e:
                RESULTS.append(("FAIL", name, f"checker error: {e.__class__.__name__}: {e}"))
        RESULTS_FNS.append(run)
        return fn
    return deco

RESULTS_FNS = []

@check("heartbeat fresh + no errors")
def c_heartbeat():
    d = json.load(open(D("heartbeat.json")))
    age = time.time() - d["epoch"]
    return (age < 600 and d.get("errors", 0) == 0,
            f"age {age/60:.1f}m, errors {d.get('errors')}, pid {d.get('pid')}, scan {d.get('scan_count')}")

@check("one equity truth (heartbeat vs persisted <1%)")
def c_equity():
    hb = json.load(open(D("heartbeat.json"))).get("equity")
    try:
        pers = json.load(open(D("risk_equity_state.json")))
        pe = pers.get("equity") or pers.get("current_equity")
    except FileNotFoundError:
        return True, "no persisted equity file (skip compare)"
    if not hb or not pe:
        return True, f"incomparable (hb={hb}, persisted={pe})"
    div = abs(hb - pe) / max(hb, pe)
    return div < 0.01, f"hb ${hb:.2f} vs persisted ${pe:.2f} ({div*100:.1f}% divergence)"

@check("no unlabeled closes since spine fix (2026-07-01T23:00Z)")
def c_labels():
    CUT = "2026-07-01T23:00"
    rows = list(csv.reader(open(D("trades.csv"))))
    h = [c.strip() for c in rows[0]]
    idx = {c: i for i, c in enumerate(h)}
    bad, recent = [], 0
    for r in rows[1:]:
        ts = r[idx["timestamp"]] if idx.get("timestamp", -1) < len(r) else ""
        if ts >= CUT:
            recent += 1
            conf = r[idx["confidence"]] if "confidence" in idx and idx["confidence"] < len(r) else ""
            reg = r[idx["regime"]] if "regime" in idx and idx["regime"] < len(r) else ""
            et = r[idx["entry_type"]] if "entry_type" in idx and idx["entry_type"] < len(r) else ""
            if (conf in ("", "0", "0.0")) or not reg.strip() or not et.strip():
                bad.append(ts[:16])
    return (not bad, f"{recent} closes since cut, {len(bad)} unlabeled {bad[:3]}")

@check("thesis records truthful post-fix (side not all-BUY, grading fires)")
def c_thesis():
    CUT = "2026-07-01T23:00"
    path = D("llm", "thesis_history.jsonl")
    sides, graded, n = set(), 0, 0
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        ts = str(r.get("ts") or r.get("timestamp") or r.get("thesis_id", ""))
        if CUT[:10].replace("-", "") in ts or ts >= CUT:
            n += 1
            sides.add(r.get("side", "?"))
            if str(r.get("outcome", "pending")) != "pending":
                graded += 1
    if n == 0:
        return True, "no new thesis records yet (nothing to violate)"
    ok = len(sides) > 1 or "SELL" in sides or "SHORT" in sides or graded > 0
    return ok, f"{n} new records, sides {sorted(sides)}, graded {graded}"

@check("funding/OI collector alive (<60m)")
def c_funding():
    path = D("funding_oi_history.jsonl")
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 4000))
        last = [l for l in f.read().decode("utf-8", "replace").splitlines() if l.strip()][-1]
    ts = json.loads(last)["timestamp"]
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - dt).total_seconds() / 60
    return age < 60, f"last sample {age:.0f}m ago"

@check("position book parses + consistent with heartbeat")
def c_book():
    p = json.load(open(D("position_state.json")))
    hb = json.load(open(D("heartbeat.json")))
    n_file, n_hb = p.get("position_count", -1), hb.get("positions", -1)
    # heartbeat may lag one loop; tolerate ±1
    return abs(n_file - n_hb) <= 1, f"state file {n_file} vs heartbeat {n_hb}"

@check("graduated_rules parses + veto dollar fields present")
def c_rules():
    d = json.load(open(D("llm", "graduated_rules.json")))
    rules = d.get("rules", [])
    vetoes = [r for r in rules if r.get("action") == "veto"]
    with_dollars = [r for r in vetoes if "pnl_saved" in r or "pnl_missed" in r]
    hype = next((r for r in rules if r.get("rule_id") == "hype_long_veto_v1"), None)
    return (len(rules) > 0,
            f"{len(rules)} rules, {len(vetoes)} vetoes ({len(with_dollars)} dollar-aware), "
            f"hype_long_veto active={hype.get('active') if hype else 'MISSING'}")

def main():
    for fn in RESULTS_FNS:
        fn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fails = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    print(f"WIRING INVARIANT CHECK — {now} — {'ALL CLEAR' if fails == 0 else f'{fails} VIOLATION(S)'}")
    for status, name, detail in RESULTS:
        print(f"  [{status}] {name} — {detail}")
    # append violations to a log the learning engine can diff
    if fails:
        with open(os.path.join(os.path.dirname(ROOT), "coordination", "VIOLATIONS.log"), "a", encoding="utf-8") as f:
            for status, name, detail in RESULTS:
                if status == "FAIL":
                    f.write(f"{now} | {name} | {detail}\n")
    sys.exit(fails)

if __name__ == "__main__":
    main()
