"""M3 step 1 — fetch the price path after each Syndicate first-call. Moved to the laptop (server OOM).

INPUT: `server_exports/syndicate_calls_anon.jsonl` — 200 first-calls over 30 days
(2026-09-11 -> 10-11), each `{ca, call_ts, caller_hash, starred, first_seen_via_bot_alert}`.

WHAT THIS DELIBERATELY DOES NOT TOUCH. `caller_hash` and `starred` are dropped on read and never
written to the output. The standing rule on this data is that the PC grades callers locally and the
laptop does not build caller grading; the moonbag question — when to sell — does not need to know
who called it, so it will not be told. The output carries the call timestamp, the price path as
MULTIPLES of the entry, and nothing else identifying.

OUTPUT: `syndicate_paths.jsonl`, one row per call:
    {"i": <index>, "call_ts": ..., "m1": [minute multiples, 0..24h], "h1": [hourly multiples, 0..7d]}
Multiples, not prices, so nothing here identifies a token either.

RATE LIMITS. GeckoTerminal's free tier is roughly 30 requests/minute. 200 calls x 3 requests = 600,
so this throttles hard and resumes: already-fetched rows are skipped, making it safe to re-run
after an interruption.
"""
import io
import json
import os
import time
import urllib.error
import urllib.request

SRC = os.path.join("server_exports", "syndicate_calls_anon.jsonl")
OUT = "syndicate_paths.jsonl"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
PAUSE = 2.1              # ~28 req/min, under the free-tier ceiling
MIN_H = 24               # minute resolution out to 24h
HOUR_H = 24 * 7          # hourly out to 7 days


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json",
                              "User-Agent": "wagmi-research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
            time.sleep(PAUSE)
            return out
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (k + 1))      # backing off is cheaper than being banned
                continue
            if e.code in (404, 400):
                return None                   # token has no pool; not retryable
            time.sleep(4 * (k + 1))
        except Exception:
            time.sleep(4 * (k + 1))
    return None


def best_pool(ca):
    """The deepest pool, since a thin one gives a path that is mostly noise."""
    d = get("%s/tokens/%s/pools" % (GT, ca))
    if not d or not isinstance(d, dict):
        return None
    best, bestliq = None, -1.0
    for p in (d.get("data") or []):
        a = p.get("attributes") or {}
        try:
            liq = float(a.get("reserve_in_usd") or 0)
        except (TypeError, ValueError):
            liq = 0.0
        pid = (p.get("id") or "").split("_", 1)[-1]
        if pid and liq > bestliq:
            best, bestliq = pid, liq
    return best


def ohlcv(pool, res, before):
    d = get("%s/pools/%s/ohlcv/%s?limit=1000&before_timestamp=%d" % (GT, pool, res, before))
    if not d or not isinstance(d, dict):
        return []
    lst = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    rows = []
    for b in lst:
        try:
            rows.append((int(b[0]), float(b[4])))     # (ts, close)
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort()
    return rows


def path_multiples(rows, t0, horizon_s, step_s):
    """Resample to a fixed grid of multiples of the entry close. Forward-fills gaps, which
    is the honest choice for an illiquid token: no trade means no new price, not a zero."""
    rows = [r for r in rows if t0 <= r[0] <= t0 + horizon_s]
    if not rows:
        return None
    entry = rows[0][1]
    if entry <= 0:
        return None
    out, j, last = [], 0, rows[0][1]
    n = horizon_s // step_s
    for k in range(n + 1):
        tk = t0 + k * step_s
        while j < len(rows) and rows[j][0] <= tk:
            last = rows[j][1]
            j += 1
        out.append(round(last / entry, 6))
    return out


def main():
    calls = []
    for line in io.open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        # caller_hash and starred are dropped HERE and never reach the output
        calls.append({"ca": d["ca"], "call_ts": int(d["call_ts"])})
    calls.sort(key=lambda c: c["call_ts"])

    done = set()
    if os.path.exists(OUT):
        for line in io.open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["i"])
            except Exception:
                continue
    print("%d calls, %d already fetched, %d to go" % (len(calls), len(done),
                                                      len(calls) - len(done)), flush=True)

    f = io.open(OUT, "a", encoding="utf-8")
    ok = nopool = nopath = 0
    t_start = time.time()
    for i, c in enumerate(calls):
        if i in done:
            continue
        pool = best_pool(c["ca"])
        if not pool:
            nopool += 1
            f.write(json.dumps({"i": i, "call_ts": c["call_ts"], "skip": "no_pool"}) + "\n")
            f.flush()
            continue
        t0 = c["call_ts"]
        mins = ohlcv(pool, "minute", t0 + MIN_H * 3600 + 60)
        hrs = ohlcv(pool, "hour", t0 + HOUR_H * 3600 + 3600)
        m1 = path_multiples(mins, t0, MIN_H * 3600, 60)
        h1 = path_multiples(hrs, t0, HOUR_H * 3600, 3600)
        if not m1 and not h1:
            nopath += 1
            f.write(json.dumps({"i": i, "call_ts": t0, "skip": "no_path"}) + "\n")
            f.flush()
            continue
        f.write(json.dumps({"i": i, "call_ts": t0, "m1": m1, "h1": h1}) + "\n")
        f.flush()
        ok += 1
        if (ok + nopool + nopath) % 10 == 0:
            el = time.time() - t_start
            print("  %d/%d  ok %d  no_pool %d  no_path %d  %.0fs"
                  % (i + 1, len(calls), ok, nopool, nopath, el), flush=True)
    f.close()
    print("DONE ok %d, no_pool %d, no_path %d, %.0fs"
          % (ok, nopool, nopath, time.time() - t_start), flush=True)


if __name__ == "__main__":
    main()
