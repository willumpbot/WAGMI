"""Syndicate deep-dive: minute-by-minute paths for every Syndicate first-call in the last N days, and realistic
trading rules simulated on them (entry delay, take-profit, partials, trailing, stops, costs).

Data stays LOCAL (data/hivemind/tg/ is gitignored): the call list comes from other people's messages. Prices are
public (GeckoTerminal, free, cached in data/hivemind/tg/paths/<CA>.json so reruns cost nothing).

  python tools/hivemind/syndicate_study.py --days 14          # fetch (rate-limited) + simulate
  python tools/hivemind/syndicate_study.py --days 14 --offline

Writes data/hivemind/tg/syndicate_study.json and SYNDICATE_STUDY.md, plus an ANONYMISED export for the laptop
(bot/data/laptop_mining/server_exports/syndicate_paths_anon.jsonl.gz: hashed caller id, call time, minute path as
multiples of the entry price; no handles, no message text, no contract addresses).
"""
import gzip
import hashlib
import json
import random
import re
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
TG = BOT / "data" / "hivemind" / "tg"
PATHS = TG / "paths"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
SYNDICATE = -1003904703116
COST = 0.03            # 3% round trip: fees + slippage at small size (memecard: ~1-2% slippage under $500)


def _get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "wagmi-hivemind/1.0"})
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except Exception as e:
            if "404" in str(e):
                return None
            time.sleep(4 * (i + 1))
    return None


def first_calls(days):
    since = time.time() - days * 86400
    rows = []
    for f in ("history_calls.jsonl", "calls.jsonl"):
        try:
            for l in (TG / f).read_text(encoding="utf-8").splitlines():
                r = json.loads(l)
                if (r.get("chat_id") == SYNDICATE or r.get("chat") == "Syndicate 2.0") and r.get("ca") and r["ts"] >= since:
                    rows.append(r)
        except OSError:
            pass
    rows.sort(key=lambda r: r["ts"])
    calls = {}
    for r in rows:
        ca = r["ca"]
        if ca in calls or ca.startswith("0x") or ca.islower():
            continue
        snd = r.get("sender") or ""
        human = snd and not snd.lower().endswith("bot")
        caller = snd if human else None
        if not human:
            m = re.search(r"├\s*@?([A-Za-z0-9_]{3,})\s*(?:\n|/|$)", r.get("msg") or "")
            caller = ("@" + m.group(1)) if m else None
        calls[ca] = {"ca": ca, "ts": r["ts"], "caller": caller, "bot_first": not human}
    return list(calls.values())


def fetch_path(c, offline=False):
    """Minute bars from the call to +24h (paged) and hourly bars to +7d. Cached."""
    cp = PATHS / (c["ca"] + ".json")
    if cp.exists():
        d = json.loads(cp.read_text(encoding="utf-8"))
        if d.get("complete") or offline or time.time() - d.get("fetched", 0) < 3600:
            return d
    if offline:
        return None
    d = {"ca": c["ca"], "fetched": time.time()}
    pools = _get(f"{GT}/tokens/{c['ca']}/pools?page=1"); time.sleep(2.2)
    try:
        d["pool"] = pools["data"][0]["attributes"]["address"]
        d["liq_now"] = float(pools["data"][0]["attributes"].get("reserve_in_usd") or 0)
    except Exception:
        d["error"] = "no pool"
        PATHS.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(d), encoding="utf-8")
        return d
    t0, mins = int(c["ts"]), []
    end = min(int(time.time()), t0 + 24 * 3600)
    cursor = min(end, t0 + 1000 * 60)
    for _ in range(3):   # up to 3 pages of 1000 one-minute bars
        o = _get(f"{GT}/pools/{d['pool']}/ohlcv/minute?aggregate=1&limit=1000&currency=usd&before_timestamp={cursor}")
        time.sleep(2.2)
        bars = (((o or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        mins += [b for b in bars if t0 - 120 <= b[0] <= end]
        if cursor >= end:
            break
        cursor = min(end, cursor + 1000 * 60)
    seen = {}
    for b in mins:
        seen[b[0]] = b
    d["min"] = [seen[k] for k in sorted(seen)]
    o = _get(f"{GT}/pools/{d['pool']}/ohlcv/hour?aggregate=1&limit=200&currency=usd"); time.sleep(2.2)
    hb = (((o or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    d["hour"] = sorted(b for b in hb if b[0] >= t0 - 3600)
    d["complete"] = time.time() > t0 + 7 * 86400 + 3600
    PATHS.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(d), encoding="utf-8")
    return d


def path_multiples(c, d, delay_min):
    """Entry = close of the first minute bar starting >= call + delay. Returns (entry, [(t, hi, lo, close) as
    multiples of entry] minute path to 24h, then hourly to 7d)."""
    t_in = c["ts"] + delay_min * 60
    mb = [b for b in d.get("min", []) if b[0] >= t_in - 59]
    if not mb or mb[0][0] > t_in + 180:   # no trading at the moment we'd enter
        return None, None
    e = mb[0][4]
    if not e:
        return None, None
    p = [(b[0], b[2] / e, b[3] / e, b[4] / e) for b in mb[1:]]
    last = p[-1][0] if p else mb[0][0]
    p += [(b[0], b[2] / e, b[3] / e, b[4] / e) for b in d.get("hour", []) if b[0] > last and b[0] <= c["ts"] + 7 * 86400]
    return e, p


def sim(p, tp=None, partial=None, trail=None, stop=None, hold_h=24, t0=0):
    """Return net multiple-1 (fraction) after COST. Bars processed in time order; within a bar the adverse extreme
    is assumed FIRST (stop before target: conservative)."""
    pos, realised, peak, end_t = 1.0, 0.0, 1.0, t0 + hold_h * 3600
    for t, hi, lo, cl in p:
        if t > end_t:
            break
        if stop and lo <= stop:
            realised += pos * stop
            pos = 0
            break
        if trail and peak >= trail[0] and lo <= peak * (1 - trail[1]):
            realised += pos * peak * (1 - trail[1])
            pos = 0
            break
        if partial and pos > 0.5 and hi >= partial[0]:
            realised += 0.5 * partial[0]
            pos -= 0.5
        if tp and hi >= tp:
            realised += pos * tp
            pos = 0
            break
        peak = max(peak, hi)
        last = cl
    if pos > 0:
        last = [b for b in p if b[0] <= end_t]
        realised += pos * (last[-1][3] if last else 1.0)
    return realised - 1 - COST


RULES = {
    "hold 24h": dict(),
    "sell all 1.3x": dict(tp=1.3),
    "sell all 1.5x": dict(tp=1.5),
    "sell all 2x": dict(tp=2.0),
    "sell all 3x": dict(tp=3.0),
    "half at 1.5x, rest 3x": dict(partial=(1.5,), tp=3.0),
    "half at 2x, rest 5x": dict(partial=(2.0,), tp=5.0),
    "1.5x then trail 25%": dict(trail=(1.5, 0.25)),
    "2x then trail 30%": dict(trail=(2.0, 0.30)),
    "sell 1.5x, stop -40%": dict(tp=1.5, stop=0.6),
    "sell 2x, stop -50%": dict(tp=2.0, stop=0.5),
    "half 1.5x, trail 30% after 2x": dict(partial=(1.5,), trail=(2.0, 0.30)),
}
DELAYS = [1, 3, 5, 15, 30]


def summarise(xs):
    if not xs:
        return {"n": 0}
    xs = sorted(xs)
    rnd = random.Random(1)
    boots = sorted(statistics.mean(rnd.choices(xs, k=len(xs))) for _ in range(2000))
    return {"n": len(xs), "mean": round(statistics.mean(xs) * 100, 1), "median": round(statistics.median(xs) * 100, 1),
            "win": round(sum(x > 0 for x in xs) / len(xs) * 100), "ci": [round(boots[50] * 100, 1), round(boots[1950] * 100, 1)],
            "worst": round(xs[0] * 100), "best": round(xs[-1] * 100)}


def main():
    days = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--days=")), 14))
    offline = "--offline" in sys.argv
    calls = first_calls(days)
    print(f"{len(calls)} Syndicate first-calls in the last {days} days", flush=True)
    for i, c in enumerate(calls):
        fetch_path(c, offline)
        if i % 10 == 9:
            print(f"  fetched {i + 1}/{len(calls)}", flush=True)
    try:
        rec = json.loads((TG / "track.json").read_text(encoding="utf-8")).get("callers") or {}
    except Exception:
        rec = {}
    res = {"days": days, "n_calls": len(calls), "cost": COST, "rules": {}, "delays": {}, "by_caller": {}, "speed": {}}
    usable = []
    for c in calls:
        d = fetch_path(c, offline=True) or {}
        e, p = path_multiples(c, d, 3)
        if p and len(p) > 30 and (time.time() - c["ts"] > 24 * 3600):
            usable.append((c, d))
    res["n_usable"] = len(usable)
    for name, kw in RULES.items():
        res["rules"][name] = summarise([sim(path_multiples(c, d, 3)[1], t0=c["ts"] + 180, **kw) for c, d in usable])
    for dl in DELAYS:   # how much speed matters, for the rule that historically worked
        xs = []
        for c, d in usable:
            e, p = path_multiples(c, d, dl)
            if p:
                xs.append(sim(p, tp=1.5, t0=c["ts"] + dl * 60))
        res["delays"][f"{dl} min"] = summarise(xs)
    hit15, hit2, t15 = 0, 0, []
    for c, d in usable:
        e, p = path_multiples(c, d, 3)
        h = next((t for t, hi, lo, cl in p if hi >= 1.5), None)
        if h:
            hit15 += 1
            t15.append((h - c["ts"]) / 60)
        if any(hi >= 2 for t, hi, lo, cl in p):
            hit2 += 1
    res["speed"] = {"hit_1_5x_pct": round(hit15 / max(1, len(usable)) * 100), "hit_2x_pct": round(hit2 / max(1, len(usable)) * 100),
                    "median_min_to_1_5x": round(statistics.median(t15)) if t15 else None}
    byc = defaultdict(list)
    for c, d in usable:
        byc[c["caller"] or "(bot alert)"].append(sim(path_multiples(c, d, 3)[1], tp=1.5, t0=c["ts"] + 180))
    for k, xs in sorted(byc.items(), key=lambda kv: -len(kv[1])):
        res["by_caller"][k] = dict(summarise(xs), star=bool((rec.get(k) or {}).get("watch")))
    starred = [x for k, xs in byc.items() if (rec.get(k) or {}).get("watch") for x in xs]
    others = [x for k, xs in byc.items() if not (rec.get(k) or {}).get("watch") for x in xs]
    res["star_vs_rest"] = {"star": summarise(starred), "rest": summarise(others)}
    (TG / "syndicate_study.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    # anonymised export for the laptop: hashed caller, call time, minute path as entry multiples (3-min delay)
    exp = BOT / "data" / "laptop_mining" / "server_exports" / "syndicate_paths_anon.jsonl.gz"
    with gzip.open(exp, "wt", encoding="utf-8") as f:
        for c, d in usable:
            e, p = path_multiples(c, d, 0)
            if not p:
                continue
            f.write(json.dumps({"caller_hash": hashlib.sha256((c["caller"] or "bot").encode()).hexdigest()[:10],
                                "starred": bool((rec.get(c["caller"]) or {}).get("watch")), "call_ts": int(c["ts"]),
                                "path": [[int(t - c["ts"]), round(hi, 4), round(lo, 4), round(cl, 4)] for t, hi, lo, cl in p]}) + "\n")
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = main()
    print(json.dumps({k: r[k] for k in ("n_calls", "n_usable", "speed")}, indent=1))
    for k, v in r["rules"].items():
        print(f"{k:32} {v}")
    print("delays:", {k: (v.get('mean'), v.get('win')) for k, v in r["delays"].items()})
    print("star vs rest:", r["star_vs_rest"])
