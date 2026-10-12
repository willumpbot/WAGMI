"""THE BIG PULL -- price paths for 18,437 anonymised meme calls across three chats.

Owner, via the server: *"i really really doubt we can tell the winners from the duds ... but there
are going to be massive trends in how we trade it."* So Mission Z is now mostly Z1: treat every
call as one small ticket in a portfolio and find the mechanics -- entry delay, first-hour stop,
scale-out, time stop -- that survive. That needs a PATH per call, which is this script.

Input: server_exports/tg_calls_history_anon.jsonl.gz
  18,437 first-calls per coin: dtn 10,282 (2025-03 -> 2026-06), dtn_hitters 7,821 (2025-03 ->
  2026-10), syndicate 334 (2026-08 -> 10). Fields chat, ca, call_ts, caller_hash.
  ~55x the M3 sample, which is what makes the mechanics question answerable at all.

TWO RULES THAT COME STRAIGHT FROM M3 GOING WRONG:
  1. A DEAD POOL IS A DUD, NOT A MISSING ROW. In M3, 20 of 200 calls had no pool and dropping them
     flipped the best rule from +6.7% to -8.0%. Old pools here are 18 months old; many will be gone.
     Every failure is RECORDED with its reason so the scoring can count it as a total loss rather
     than silently exclude it.
  2. RESUME ON `ca`, NEVER ON LIST POSITION. The call list is append-only and grows, so an
     index-keyed resume re-fetches some rows and skips others. (I shipped that bug once already.)

Cost: 2 requests per call (pool lookup, then minute OHLCV covering 24h) at 2.1s = roughly 21 hours
for the full corpus. Resumable, so it can be stopped and restarted freely, and partial output is
already usable -- the chats are processed NEWEST FIRST so the most recoverable pools land early.

caller_hash is carried through UNUSED. Z2 (caller form) is a separate question with its own
constraint, and nothing here grades a caller.
"""
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

SRC = os.path.join("server_exports", "tg_calls_history_anon.jsonl.gz")
OUT = "megacalls_paths.jsonl"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
PAUSE = 2.1
MIN_H = 24          # minute grid out to 24h -- covers every entry delay and first-hour stop
HOUR_H = 72         # hourly grid out to 72h -- covers the time stops


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json",
                              "User-Agent": "wagmi-research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
            time.sleep(PAUSE)
            return out, None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(25 * (k + 1))
                continue
            if e.code in (400, 404):
                return None, "http_%d" % e.code
            time.sleep(4 * (k + 1))
        except Exception:
            time.sleep(4 * (k + 1))
    return None, "unreachable"


def best_pool(ca):
    d, err = get("%s/tokens/%s/pools" % (GT, ca))
    if not d or not isinstance(d, dict):
        return None, err or "no_pool_response"
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
    return (best, None) if best else (None, "no_pools_listed")


def ohlc(pool, res, before):
    d, err = get("%s/pools/%s/ohlcv/%s?limit=1000&before_timestamp=%d" % (GT, pool, res, before))
    if not d or not isinstance(d, dict):
        return [], err or "no_ohlcv"
    lst = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    rows = []
    for b in lst:
        try:
            rows.append((int(b[0]), float(b[2]), float(b[4])))   # ts, HIGH, close
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort()
    return rows, None


def grids(rows, t0, horizon_s, step_s):
    """Running max-high AND the close, both as multiples of the entry close.

    The peak series answers "did it touch X", the close series answers "what would a time stop
    have got". Both are needed for the Z1 grid, and storing both costs nothing extra.
    """
    rows = [r for r in rows if t0 <= r[0] <= t0 + horizon_s]
    if not rows:
        return None, None
    base = rows[0][2]
    if base <= 0:
        return None, None
    peak, close, j, run, last = [], [], 0, rows[0][1], rows[0][2]
    n = horizon_s // step_s
    for k in range(n + 1):
        tk = t0 + k * step_s
        while j < len(rows) and rows[j][0] <= tk:
            run = max(run, rows[j][1])
            last = rows[j][2]
            j += 1
        peak.append(round(run / base, 6))
        close.append(round(last / base, 6))
    return peak, close


def load_calls():
    calls = []
    with gzip.open(SRC, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("ca") and d.get("call_ts"):
                calls.append({"ca": d["ca"], "call_ts": int(d["call_ts"]),
                              "chat": d.get("chat") or "?"})
    # NEWEST FIRST: recent pools are far likelier to still exist, so partial output is useful
    calls.sort(key=lambda c: -c["call_ts"])
    return calls


def main():
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    calls = load_calls()
    done = set()
    if os.path.exists(OUT):
        for line in io.open(OUT, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("ca"):
                done.add(d["ca"])
    todo = [c for c in calls if c["ca"] not in done]
    if limit:
        todo = todo[:limit]
    print("%d calls in corpus, %d already fetched, %d to go (%.1f h at %.1fs x 2 requests)"
          % (len(calls), len(done), len(todo), len(todo) * PAUSE * 2 / 3600.0, PAUSE), flush=True)

    f = io.open(OUT, "a", encoding="utf-8")
    ok = dead = 0
    t0w = time.time()
    for i, c in enumerate(todo):
        pool, err = best_pool(c["ca"])
        if not pool:
            dead += 1
            f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                "dead": err}) + "\n")
            f.flush()
            continue
        t0 = c["call_ts"]
        mins, _e1 = ohlc(pool, "minute", t0 + MIN_H * 3600 + 60)
        pm, cm = grids(mins, t0, MIN_H * 3600, 60)
        if pm is None:
            hrs, _e2 = ohlc(pool, "hour", t0 + HOUR_H * 3600 + 3600)
            ph, ch = grids(hrs, t0, HOUR_H * 3600, 3600)
            if ph is None:
                dead += 1
                f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                    "pool": pool, "dead": "no_path"}) + "\n")
                f.flush()
                continue
            f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                "pool": pool, "peak_h": ph, "close_h": ch}) + "\n")
        else:
            f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                "pool": pool, "peak_m": pm, "close_m": cm}) + "\n")
        f.flush()
        ok += 1
        if (ok + dead) % 50 == 0:
            el = time.time() - t0w
            rate = (ok + dead) / max(el, 1)
            print("  %d/%d  live %d  dead %d  %.0fs  eta %.1fh"
                  % (i + 1, len(todo), ok, dead, el,
                     (len(todo) - i - 1) / max(rate, 1e-9) / 3600.0), flush=True)
    f.close()
    print("DONE live %d, dead %d, %.0fs" % (ok, dead, time.time() - t0w), flush=True)


if __name__ == "__main__":
    main()
