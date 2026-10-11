"""Forward-grade the scanner's expected daily move (exp_move, volforecast HAR) against the naive baseline rv5.

The terminal leans on exp_move everywhere (stop distance, "normal day's move", safe leverage), and its live claim was
never checked. Laptop reply 54: this is the one claim reachable this month (~16 day-clusters).
log(scan): once per coin per UTC day, record px, exp_move (forecast of |next-day move| %) and rv5 (sd of the last 5
daily returns %). resolve(): 24h later, a = |close 24h later / px - 1| * 100 from HL 1h bars. Both forecasts are
scored on the same |move| target: the naive one as rv5 * sqrt(2/pi) (E|r| of a normal with sd rv5).
Losses per row: QLIKE on squares (a floored at 0.05% so a flat day cannot blow up the log) and absolute error.
Verdict on the day-clustered mean loss difference (HAR - naive; negative = HAR better), with its 80%-power MDE.
Writes data/hivemind/expmove_log.jsonl (rows, resolved in place on rewrite) and expmove_grades.json. Never trades.
"""
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import hl

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"
LOG = HM / "expmove_log.jsonl"
OUT = HM / "expmove_grades.json"
FLOOR = 0.05
K = math.sqrt(2 / math.pi)


def _rows():
    try:
        return [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def log(scan):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seen = {(r["day"], r["coin"]) for r in _rows()[-2000:]}
    new = [{"day": day, "ts": time.time(), "coin": r["coin"], "px": r["px"], "exp_move": r.get("exp_move"),
            "rv5": r.get("rv5")} for r in scan.get("coins", [])
           if (day, r["coin"]) not in seen and r.get("exp_move") and r.get("rv5") and r.get("px")]
    if new:
        with open(LOG, "a", encoding="utf-8") as f:
            for n in new:
                f.write(json.dumps(n) + chr(10))
    return len(new)


def _qlike(a, f):
    x = max(a, FLOOR) ** 2 / max(f, FLOOR) ** 2
    return x - math.log(x) - 1


def resolve():
    rows, now, changed = _rows(), time.time(), False
    for r in rows:
        if "a" in r or now < r["ts"] + 86400 + 3600:
            continue
        t = r["ts"] + 86400
        try:
            bars = hl.candles(r["coin"], "1h", (t - 3600) * 1000, (t + 6 * 3600) * 1000, ttl=3600) or []
        except Exception:
            continue
        p1 = next((float(b["c"]) for b in bars if b["t"] / 1000 >= t), None)
        if p1 is None:
            continue
        r["a"] = round(abs(p1 / r["px"] - 1) * 100, 4)
        changed = True
    if changed:
        tmp = LOG.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + chr(10) for r in rows), encoding="utf-8")
        tmp.replace(LOG)
    done = [r for r in rows if "a" in r]
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n": len(done)}
    for name, loss in (("qlike", _qlike), ("abs_err", lambda a, f: abs(a - f))):
        by = {}
        for r in done:
            d = loss(r["a"], r["exp_move"]) - loss(r["a"], r["rv5"] * K)
            by.setdefault(r["day"], []).append(d)
        dm = [statistics.mean(v) for _, v in sorted(by.items())]
        if len(dm) < 3:
            out[name] = {"n_days": len(dm), "verdict": "collecting: too few days"}
            continue
        m, se = statistics.mean(dm), statistics.stdev(dm) / len(dm) ** 0.5
        verdict = ("HAR beats naive" if m + 1.96 * se < 0 else "naive beats HAR" if m - 1.96 * se > 0
                   else f"no difference seen yet (can see > {2.8 * se:.3f})")
        out[name] = {"n_days": len(dm), "mean_diff": round(m, 4), "se": round(se, 4), "mde": round(2.8 * se, 4),
                     "verdict": verdict, "note": "HAR loss minus naive loss; negative = HAR better"}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(OUT)
    return out


if __name__ == "__main__":
    print("logged", log(json.loads((HM / "scan.json").read_text(encoding="utf-8"))))
    print(resolve())
