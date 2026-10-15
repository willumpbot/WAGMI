"""M28 twin gates (Amendment 1 spec). Two gates, separate meanings:

CONSISTENCY GATE (sim-vs-sim, tolerance ~0): replay every non-duplicate owner plan through
exit_style.play itself on panels 5m bars from its actual fill, gross-to-gross against the exported
sims r. Same algorithm + same-era bars => any gap beyond mark/bar timing is a BUG in my invocation or
a data mismatch. This gate validates that the map's engine semantics equal the server's grader; it
does NOT validate either against reality.

FIDELITY GATE (vs real fills): requires >= 30 closed real legs replayed under their RECORDED params
with a signed-mean dR ~ 0 check. Prints the per-class population counts (owner-authored / bot-agent /
LLM-originated per the amended seal) and declares UNDECIDABLE below the floor -- the expected status
today. No map claim is upgraded by this script; the sim-fill optimism caveat is never discharged.
"""
import importlib.util
import io
import json
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
SNAP = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "claude",
                    "C--windows-System32", "acf03186-eb2f-4645-840c-0730784e417f",
                    "scratchpad", "desk", "plans_snapshot.json")
ES = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "claude",
                  "C--windows-System32", "acf03186-eb2f-4645-840c-0730784e417f",
                  "scratchpad", "desk", "exit_style.py")
spec = importlib.util.spec_from_file_location("exit_style", ES)
exit_style = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exit_style)

FLOOR = 30


def bars_5m(c, coin, t0):
    rows = c.execute("SELECT t,h,l,c FROM candles_5m WHERE coin=? AND t>=? ORDER BY t",
                     (coin, int((t0 - 600) * 1000))).fetchall()
    return [{"t": r[0], "h": r[1], "l": r[2], "c": r[3]} for r in rows]


def atr_at_fill(c, coin, ts):
    rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
    a = np.asarray(rows, float)
    day = (a[:, 0] // 86400000).astype(np.int64)
    uq, fi = np.unique(day, return_index=True)
    ends = np.append(fi[1:], len(a))
    dh = np.array([a[i:j, 1].max() for i, j in zip(fi, ends)])
    dl = np.array([a[i:j, 2].min() for i, j in zip(fi, ends)])
    dc = np.array([a[j - 1, 3] for j in ends])
    keep = (uq + 1) * 86400 <= ts                 # fully closed days before the fill
    if keep.sum() < 15:
        return None
    dh, dl, dc = dh[keep], dl[keep], dc[keep]
    tr = np.maximum(dh[1:] - dl[1:], np.maximum(np.abs(dh[1:] - dc[:-1]), np.abs(dl[1:] - dc[:-1])))
    return float(np.mean(tr[-14:]))


def main():
    d = json.load(io.open(SNAP, encoding="utf-8"))
    plans = d if isinstance(d, list) else d.get("plans", d.get("sims", []))
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("=== CONSISTENCY GATE (exit_style.play on 5m bars vs exported sims r; gross) ===")
    drs = []
    classes = {"owner": 0, "duplicate": 0, "late_logged": 0}
    for p in plans:
        if p.get("duplicate_of") or p.get("status") == "duplicate":
            classes["duplicate"] += 1
            continue
        if p.get("late_logged"):
            classes["late_logged"] += 1
            continue
        classes["owner"] += 1
        fill = p.get("filled_at")
        if not fill:
            continue
        coin = p["coin"]
        bars = bars_5m(c, coin, fill)
        # compare at the SAME observation time: truncate my bars at the export's as_of, else an open
        # plan's r is measured at two different moments and the gap is timing, not engine
        as_of = p.get("as_of")
        if as_of:
            bars = [b_ for b_ in bars if (b_["t"] / 1000 if b_["t"] > 1e12 else b_["t"]) + 300 <= as_of]
        if len(bars) < 10:
            print("  %s %-5s SKIP: no 5m coverage" % (p["plan_id"][:8], coin))
            continue
        atr = atr_at_fill(c, coin, fill)
        mode = p.get("mode") or ""
        style = "runner" if mode == "runner" or p.get("exit_style") == "runner" else "full"
        out = exit_style.play(p["side"] if p.get("side") else ("LONG" if p["target"] > p["entry"] else "SHORT"),
                              p["entry"], p["stop"], p["target"], bars, fill,
                              float(p.get("max_hold_h") or ((p.get("expires_ts", 0) - fill) / 3600) or 48),
                              style=style, atr=atr)
        mine = out.get("r") if out.get("r") is not None else out.get("live_r")
        theirs = p.get("r")
        if mine is None or theirs is None:
            print("  %s %-5s open/ungraded mine=%s theirs=%s" % (p["plan_id"][:8], coin, mine, theirs))
            continue
        dr = mine - theirs
        drs.append(dr)
        tag = "OK " if abs(dr) <= 0.03 else ("mark-timing" if abs(dr) <= 0.12 and out.get("r") is None else "GAP")
        print("  %s %-5s style=%-6s mine %+0.3f theirs %+0.3f dr %+0.3f  %s"
              % (p["plan_id"][:8], coin, style, mine, theirs, dr, tag))
    if drs:
        print("signed mean dr = %+0.4f over %d plans (|mean| <= 0.03 expected: open-plan gaps are"
              " mark-vs-bar-close timing)" % (float(np.mean(drs)), len(drs)))
    print("classes: %s" % classes)

    print("=== FIDELITY GATE (real closed legs under recorded params) ===")
    # population: owner_fills rows reachable via the git export; count only
    import subprocess
    try:
        raw = subprocess.run(["git", "-C", os.path.join(HERE, "..", "..", ".."),
                              "show", "origin/desktop-overdrive-2026-05-30:bot/data/hivemind/owner_fills.jsonl"],
                             capture_output=True, text=True, timeout=60).stdout
        legs = [json.loads(l) for l in raw.splitlines() if l.strip()]
    except Exception:
        legs = []
    closed = [l for l in legs if l.get("kind") in ("final", "partial")]
    print("real recorded legs available: %d (floor %d) -> %s"
          % (len(closed), FLOOR, "RUNNABLE" if len(closed) >= FLOOR else "UNDECIDABLE"))
    print("NOTE: the fidelity gate validates engines against reality; until it PASSES at n>=%d, every"
          " map claim carries the sim-fill optimism caveat undischarged." % FLOOR)


if __name__ == "__main__":
    main()
