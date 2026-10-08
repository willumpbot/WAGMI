"""Forward-grade the scanner's flags so they earn (or lose) the right to be trusted.

log(scan): once per coin+flag per UTC day, record the flag with the coin's price and the scanned universe's
prices. resolve(): after 1 and 5 days, the coin's return MINUS the median return of the same universe over
the same window (so a market-wide rally/dump doesn't count), signed by the flag's implied direction:
  ma50_pullback  -> long  (support from above should hold)
  on_20d_low     -> short (the 20d low breaks more than chance)
  everything else -> unsigned (graded on |excess move|, i.e. does it flag bigger-than-usual moves)
Writes data/hivemind/scan_grades.json: per flag n, mean excess %, hit rate, bootstrap 95% CI, verdict.
A flag needs n>=30 graded and a CI clear of zero before it is called "earned". Never trades anything.
"""
import json
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import hl

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"
LOG = HM / "scan_log.jsonl"
OUT = HM / "scan_grades.json"
SIGN = {"ma50_pullback": 1, "on_20d_low": -1}
HORIZONS = {"1d": 1, "5d": 5}
FEE_PCT = 0.09


def log(scan):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seen = set()
    try:
        for l in LOG.read_text(encoding="utf-8").splitlines()[-5000:]:
            r = json.loads(l)
            seen.add((r["day"], r["coin"], r["flag"]))
    except OSError:
        pass
    uni = {r["coin"]: r["px"] for r in scan.get("coins", [])}
    new = []
    for r in scan.get("coins", []):
        for f in r["flags"]:
            if (day, r["coin"], f) not in seen:
                new.append({"day": day, "ts": time.time(), "coin": r["coin"], "flag": f, "px": r["px"], "universe": uni})
    if new:
        with open(LOG, "a", encoding="utf-8") as fh:
            for n in new:
                fh.write(json.dumps(n) + "\n")
    return len(new)


def _close_at(coin, t_s, cache):
    """First hourly close at or after t_s (None if not yet available)."""
    key = (coin, int(t_s // 86400))
    if key not in cache:
        try:
            cache[key] = hl.candles(coin, "1h", (t_s - 3600) * 1000, (t_s + 6 * 3600) * 1000, ttl=3600)
        except Exception:
            cache[key] = []
    for b in cache[key] or []:
        if b["t"] / 1000 >= t_s:
            return float(b["c"])
    return None


def _ci(xs, n_boot=2000):
    if len(xs) < 5:
        return None
    rnd = random.Random(7)
    ms = sorted(statistics.mean(rnd.choices(xs, k=len(xs))) for _ in range(n_boot))
    return [round(ms[int(0.025 * n_boot)], 3), round(ms[int(0.975 * n_boot)], 3)]


def resolve():
    try:
        rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        rows = []
    try:
        done = json.loads(OUT.read_text(encoding="utf-8")).get("_resolved", {})
    except Exception:
        done = {}
    now, cache = time.time(), {}
    for r in rows:
        for h, days in HORIZONS.items():
            k = f"{r['day']}|{r['coin']}|{r['flag']}|{h}"
            if k in done or now < r["ts"] + days * 86400 + 3600:
                continue
            t = r["ts"] + days * 86400
            p1 = _close_at(r["coin"], t, cache)
            if p1 is None:
                continue
            rets = []
            for c, p0 in r["universe"].items():
                q = _close_at(c, t, cache) if c != r["coin"] else p1
                if q and p0:
                    rets.append((q / p0 - 1) * 100)
            if len(rets) < 10:
                continue
            ex = (p1 / r["px"] - 1) * 100 - statistics.median(rets)
            done[k] = round(ex, 3)
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "flags": {}, "_resolved": done}
    flags = sorted({k.split("|")[2] for k in done})
    for f in flags:
        out["flags"][f] = {}
        for h in HORIZONS:
            xs = [v for k, v in done.items() if k.split("|")[2] == f and k.endswith("|" + h)]
            sg = SIGN.get(f)
            ys = [sg * x - FEE_PCT for x in xs] if sg else [abs(x) for x in xs]
            if not ys:
                continue
            ci = _ci(ys)
            if sg:
                verdict = ("earned" if len(ys) >= 30 and ci and ci[0] > 0 else
                           "backwards" if len(ys) >= 30 and ci and ci[1] < 0 else "collecting" if len(ys) < 30 else "no edge")
            else:
                verdict = "size-only flag (graded on move size, not direction)"
            out["flags"][f][h] = {"n": len(ys), "mean_pct": round(statistics.mean(ys), 3), "ci95": ci,
                                  "hit": round(sum(y > 0 for y in ys) / len(ys), 3) if sg else None,
                                  "direction": {1: "long", -1: "short"}.get(sg, "none"), "verdict": verdict}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(OUT)
    return out


if __name__ == "__main__":
    s = json.loads((HM / "scan.json").read_text(encoding="utf-8"))
    print("logged", log(s))
    print(json.dumps(resolve()["flags"], indent=1))
