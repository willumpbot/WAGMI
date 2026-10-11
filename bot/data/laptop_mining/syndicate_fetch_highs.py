"""Re-fetch the Syndicate call paths keeping INTRABAR HIGHS, to settle a live prompt anchor.

WHY. `syndicate_paths.jsonl` stored closes only -- a limit I declared in `SYNDICATE_MOONBAG.md`
("intrabar wicks invisible") and which turned out to be the whole of a 15-point disagreement with
the server: their 61.7% base rate for "touched 1.5x" is measured on intrabar HIGHS, my 47.2% on
closes. Their definition is the right one for a touch, and it is the matched null for a caller
record measured the same way.

THE LIVE PROBLEM THIS FIXES (server reply 61, item 5). Claude's Syndicate verdict prompt anchors
`p_15x` on 62%, but the forward grade is a 1.5x touch WITHIN 24 HOURS -- and 62% is a 7-DAY highs
number. So the prompt is anchored high, and the server's own two forward samples disagree with each
other (86% on 22 calls that had 1-min paths, which is selection because the path mostly exists for
live pools; 53% on 49 calls by peak). An anchor that is too high makes every call look like an
underperformer.

So this stores, per call: the pool id (so pools are never re-derived again), and the running
MAXIMUM HIGH as a multiple of entry at minute resolution to 24h and hourly to 7d. Both horizons,
because the 24h number answers the live ask and the 168h number reconciles with the server's 61.7%.

Throttled and resumable, same as the first fetch. caller_hash and starred remain untouched.
"""
import csv
import io
import json
import os
import time
import urllib.error
import urllib.request

SRC = os.path.join("server_exports", "syndicate_calls_anon.jsonl")
OUT = "syndicate_highs.jsonl"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
PAUSE = 2.1
MIN_H = 24
HOUR_H = 24 * 7


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
                time.sleep(20 * (k + 1))
                continue
            if e.code in (400, 404):
                return None
            time.sleep(4 * (k + 1))
        except Exception:
            time.sleep(4 * (k + 1))
    return None


def best_pool(ca):
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


def ohlc(pool, res, before):
    d = get("%s/pools/%s/ohlcv/%s?limit=1000&before_timestamp=%d" % (GT, pool, res, before))
    if not d or not isinstance(d, dict):
        return []
    lst = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    rows = []
    for b in lst:
        try:
            # [ts, open, HIGH, low, close, volume] -- index 2 is the high, which is the
            # whole point of this refetch
            rows.append((int(b[0]), float(b[2]), float(b[4])))
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort()
    return rows


def peak_series(rows, t0, horizon_s, step_s):
    """Running max of the HIGH as a multiple of the entry close, on a fixed grid.

    Entry base is the CLOSE of the first bar at or after the call -- the same base the earlier
    close-only fetch used, so the two are directly comparable and the only thing that changes is
    whether wicks count.
    """
    rows = [r for r in rows if t0 <= r[0] <= t0 + horizon_s]
    if not rows:
        return None
    base = rows[0][2]
    if base <= 0:
        return None
    out, j, run = [], 0, rows[0][1]
    n = horizon_s // step_s
    for k in range(n + 1):
        tk = t0 + k * step_s
        while j < len(rows) and rows[j][0] <= tk:
            run = max(run, rows[j][1])
            j += 1
        out.append(round(run / base, 6))
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
        calls.append({"ca": d["ca"], "call_ts": int(d["call_ts"])})
    calls.sort(key=lambda c: c["call_ts"])

    # RESUME ON `ca`, NOT ON THE LIST INDEX. The first version keyed on `i`, the position in
    # the sorted list -- and the server then made the anon call list append-only and restored
    # rows that had aged out of its 30-day window. Any row added to the middle shifts every
    # later index, so an index-keyed resume would silently re-fetch some calls and skip others.
    # The contract address is the natural key and is stable under list growth.
    done = set()
    if os.path.exists(OUT):
        for line in io.open(OUT, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("ca"):
                done.add(d["ca"])
            elif isinstance(d.get("i"), int) and d["i"] < len(calls):
                done.add(calls[d["i"]]["ca"])      # migrate old index-keyed rows
    print("%d calls, %d already done, %d to go" % (len(calls), len(done),
                                                   len(calls) - len(done)), flush=True)
    f = io.open(OUT, "a", encoding="utf-8")
    ok = fail = 0
    t0w = time.time()
    for i, c in enumerate(calls):
        if c["ca"] in done:
            continue
        pool = best_pool(c["ca"])
        if not pool:
            fail += 1
            f.write(json.dumps({"i": i, "ca": c["ca"], "call_ts": c["call_ts"], "skip": "no_pool"}) + "\n")
            f.flush()
            continue
        t0 = c["call_ts"]
        mins = ohlc(pool, "minute", t0 + MIN_H * 3600 + 60)
        hrs = ohlc(pool, "hour", t0 + HOUR_H * 3600 + 3600)
        pm = peak_series(mins, t0, MIN_H * 3600, 60)
        ph = peak_series(hrs, t0, HOUR_H * 3600, 3600)
        if not pm and not ph:
            fail += 1
            f.write(json.dumps({"i": i, "ca": c["ca"], "call_ts": t0, "skip": "no_path"}) + "\n")
            f.flush()
            continue
        f.write(json.dumps({"i": i, "ca": c["ca"], "call_ts": t0, "pool": pool,
                            "peak_m": pm, "peak_h": ph}) + "\n")
        f.flush()
        ok += 1
        if (ok + fail) % 20 == 0:
            print("  %d/%d ok %d fail %d  %.0fs"
                  % (i + 1, len(calls), ok, fail, time.time() - t0w), flush=True)
    f.close()
    print("DONE ok %d fail %d in %.0fs" % (ok, fail, time.time() - t0w), flush=True)


if __name__ == "__main__":
    main()
