"""MISSION Z -- fetch ONLY pre-call features for each Syndicate call.

DISCIPLINE. Every number here must have been knowable strictly BEFORE call_ts. Concretely:
  - minute OHLCV requested with before_timestamp=call_ts, then filtered to bars that are FULLY
    CLOSED before the call (ts + 60 <= call_ts). A minute bar stamped call_ts-30 is still forming
    at call time and its high/close contain post-call information, so it is dropped. Same rule at
    hourly resolution (ts + 3600 <= call_ts).
  - NO current liquidity, NO FDV, NO holder counts. Those describe the pool today, not at call
    time. GeckoTerminal only exposes them as a current snapshot, so there is no version of them
    that is pre-call for a call made weeks ago. Not fetched, not recorded.

WHY POOLS ARE NOT RE-DERIVED. syndicate_highs.jsonl already carries a pool id per call. Worth
recording that those pool ids were originally chosen by CURRENT reserve_in_usd (best_pool() in
syndicate_fetch_highs.py picks the highest-liquidity pool as of the fetch date). That is a
look-ahead-tainted SELECTION of which pool to measure, inherited from the earlier fetch, and it
cannot be undone here. It does not leak into any feature VALUE below, but a pool that is the
biggest today is more likely to be one that survived -- flagged for the analysis agent.

JOIN KEY. syndicate_highs.jsonl stores no `ca`, only `i` -- and `i` is the index into the
call list sorted by call_ts, which the server has since appended to: only 18 of 199 rows still
align. So `ca` is recovered by joining on call_ts (unique in both files), and the output is keyed
on `key` = ca when recoverable else "pool:<poolid>". Never on list index.

SPARSITY. GeckoTerminal omits minute bars with no trades, so "bars available" conflates pool age
with trading inactivity, and a "5m return" on a quiet pool may really span 40m. Each return
therefore carries the ACTUAL age of the bar used as its anchor (*_anchor_age_s). A window that
reaches back past the first available bar yields null, never 0 -- a missing source is not a zero.
"""
import io
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HIGHS = os.path.join(HERE, "syndicate_highs.jsonl")
SRC = os.path.join(HERE, "server_exports", "syndicate_calls_anon.jsonl")
OUT = os.path.join(HERE, "syndicate_precall.jsonl")
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
# THROTTLE. 2.1s (~28 req/min) sat right ON GeckoTerminal's cap: the first run was silently
# absorbing 429 backoffs inside get() and crawling at 24s/row while recording NO error, because a
# retry eventually succeeded. Actual request latency is ~0.5s, so the 24s was pure rate-limit
# penalty. 3.0s (~20 req/min) keeps us under the cap, and PAUSE now RATCHETS UP permanently after
# any 429 so the run self-corrects instead of thrashing.
PAUSE = [3.0]
# PAGE SIZE. The 6h minute window holds at most 360 bars and the 7d hourly window at most 168,
# so 400/300 covers both requested windows EXACTLY with slack, at ~half the payload. The only
# thing lost vs limit=1000 is the extended (41-day) pool-age proxy; age_proxy_s now censors at
# 300h and age_censored marks it.
LIM_MIN = 400
LIM_HOUR = 300
N429 = [0]


def get(url, tries=5):
    """Returns (json, err, n429). n429 is reported so throttle health is VISIBLE per row."""
    hits = 0
    for k in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json",
                              "User-Agent": "wagmi-research/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                out = json.load(r)
            time.sleep(PAUSE[0])
            return out, None, hits
        except urllib.error.HTTPError as e:
            if e.code == 429:
                hits += 1
                N429[0] += 1
                PAUSE[0] = min(8.0, PAUSE[0] + 0.3)   # ratchet, never relax
                time.sleep(20 * (k + 1))
                continue
            if e.code in (400, 404):
                time.sleep(PAUSE[0])
                return None, "http_%d" % e.code, hits
            time.sleep(4 * (k + 1))
        except Exception:
            time.sleep(4 * (k + 1))
    return None, "exhausted", hits


def ohlc(pool, res, before, limit):
    """Raw bars ascending: (ts, open, high, low, close, volume). Newest-first from the API."""
    d, err, hits = get("%s/pools/%s/ohlcv/%s?limit=%d&before_timestamp=%d"
                       % (GT, pool, res, limit, before))
    if d is None:
        return None, err, hits
    if not isinstance(d, dict):
        return None, "shape", hits
    lst = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    rows = []
    for b in lst:
        try:
            rows.append((int(b[0]), float(b[1]), float(b[2]), float(b[3]),
                         float(b[4]), float(b[5] or 0.0)))
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort()
    return rows, None, hits


def closed_before(rows, t0, bar_s):
    """Bars fully closed strictly before t0."""
    return [r for r in rows if r[0] + bar_s <= t0]


def ret_at_lag(bars, t0, lag_s):
    """Return of last pre-call close vs the close as of (t0 - lag_s).

    Returns (ret, anchor_age_s). null when the window reaches past the first bar we have --
    that is SOURCE-MISSING, not a zero return.

    THE SAME-BAR TRAP. GeckoTerminal omits minute bars with no trades. On a quiet pool the last
    bar before the call can ALSO be the last bar at or before (t0 - lag), in which case
    last/anchor - 1 == 0.0 exactly -- a zero manufactured by construction, not an observed flat
    price. Those were silently filling the 5m column on sparse pools. Same bar => null.
    """
    if len(bars) < 2:
        return None, None
    last_i = len(bars) - 1
    last = bars[last_i][4]
    target = t0 - lag_s
    if bars[0][0] > target:
        return None, None            # window reaches past our first bar: undefined, not 0
    ai = None
    for i, r in enumerate(bars):
        if r[0] <= target:
            ai = i
        else:
            break
    if ai is None or ai == last_i:
        return None, None            # same-bar: a 0.0 by construction, not a measurement
    if bars[ai][4] <= 0 or last <= 0:
        return None, None
    return last / bars[ai][4] - 1.0, int(t0 - bars[ai][0])


def rvol(bars, t0, window_s):
    """Stdev of log returns of bars inside the window. Needs >= 3 returns to be meaningful."""
    sel = [r for r in bars if r[0] >= t0 - window_s]
    if len(sel) < 4:
        return None, len(sel)
    import math
    lr = []
    for a, b in zip(sel, sel[1:]):
        if a[4] > 0 and b[4] > 0:
            lr.append(math.log(b[4] / a[4]))
    if len(lr) < 3:
        return None, len(sel)
    m = sum(lr) / len(lr)
    v = sum((x - m) ** 2 for x in lr) / (len(lr) - 1)
    return v ** 0.5, len(sel)


def vsum(bars, t0, window_s):
    sel = [r for r in bars if r[0] >= t0 - window_s]
    if not sel:
        return None, 0
    return sum(r[5] for r in sel), len(sel)


def features(t0, mins_raw, hrs_raw):
    f = {}
    mb = closed_before(mins_raw or [], t0, 60)
    hb = closed_before(hrs_raw or [], t0, 3600)
    f["n_min_bars_6h_pre"] = len([r for r in mb if r[0] >= t0 - 6 * 3600])
    f["n_min_bars_1h_pre"] = len([r for r in mb if r[0] >= t0 - 3600])
    f["n_hour_bars_7d_pre"] = len([r for r in hb if r[0] >= t0 - 7 * 86400])
    f["n_hour_bars_returned"] = len(hb)
    f["n_min_bars_returned"] = len(mb)

    # POOL AGE PROXY. Oldest bar we can see, across both resolutions. Censored when the API
    # returned a full page (older bars exist that we did not ask for).
    firsts = [b[0][0] for b in (mb, hb) if b]
    f["first_bar_ts_pre"] = min(firsts) if firsts else None
    f["age_proxy_s"] = (t0 - min(firsts)) if firsts else None
    f["age_censored"] = bool(len(hrs_raw or []) >= LIM_HOUR)

    f["last_close_pre"] = mb[-1][4] if mb else (hb[-1][4] if hb else None)
    f["last_min_bar_age_s"] = int(t0 - mb[-1][0]) if mb else None

    # *_stale is PRE-DECLARED here, before any outcome has been looked at: the anchor bar sits
    # more than 2x the nominal lag back, so e.g. a "1h return" actually spans >2h. The value is
    # kept (it is a real pre-call return) but the flag lets the analysis agent filter on a rule
    # that was fixed before it saw a single outcome, rather than tuning a staleness cut later.
    for name, lag in (("5m", 300), ("1h", 3600), ("6h", 6 * 3600)):
        r, age = ret_at_lag(mb, t0, lag)
        f["ret_%s_pre" % name] = None if r is None else round(r, 6)
        f["ret_%s_anchor_age_s" % name] = age
        f["ret_%s_stale" % name] = None if age is None else bool(age > 2 * lag)
    for name, lag in (("24h", 86400), ("7d", 7 * 86400)):
        r, age = ret_at_lag(hb, t0, lag)
        f["ret_%s_pre" % name] = None if r is None else round(r, 6)
        f["ret_%s_anchor_age_s" % name] = age
        f["ret_%s_stale" % name] = None if age is None else bool(age > 2 * lag)

    rv, n = rvol(mb, t0, 3600)
    f["rv_1h_pre"] = None if rv is None else round(rv, 8)
    f["rv_1h_n_bars"] = n
    rv, n = rvol(mb, t0, 6 * 3600)
    f["rv_6h_pre"] = None if rv is None else round(rv, 8)
    f["rv_6h_n_bars"] = n
    rv, n = rvol(hb, t0, 7 * 86400)
    f["rv_7d_pre"] = None if rv is None else round(rv, 8)
    f["rv_7d_n_bars"] = n

    v, n = vsum(mb, t0, 3600)
    f["vol_1h_pre"] = None if v is None else round(v, 4)
    v, n = vsum(mb, t0, 6 * 3600)
    f["vol_6h_pre"] = None if v is None else round(v, 4)
    v, n = vsum(hb, t0, 86400)
    f["vol_24h_pre"] = None if v is None else round(v, 4)
    v, n = vsum(hb, t0, 7 * 86400)
    f["vol_7d_pre"] = None if v is None else round(v, 4)

    # Where the pre-call price sits in its own 6h range. Pre-call by construction.
    sel = [r for r in mb if r[0] >= t0 - 6 * 3600]
    if len(sel) >= 2 and f["last_close_pre"]:
        hi = max(r[2] for r in sel)
        lo = min(r[3] for r in sel)
        f["high_6h_pre"] = hi
        f["low_6h_pre"] = lo
        f["dist_from_6h_high_pre"] = round(f["last_close_pre"] / hi - 1.0, 6) if hi > 0 else None
        f["pct_of_6h_range_pre"] = (round((f["last_close_pre"] - lo) / (hi - lo), 6)
                                    if hi > lo else None)
    else:
        f["high_6h_pre"] = f["low_6h_pre"] = None
        f["dist_from_6h_high_pre"] = f["pct_of_6h_range_pre"] = None
    return f


def main():
    # ---- recover ca by call_ts (unique in both files); i is NOT usable, see docstring ----
    src = {}
    for line in io.open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        src[int(d["call_ts"])] = d["ca"]          # caller_hash/starred deliberately ignored

    targets = []
    for line in io.open(HIGHS, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not d.get("pool"):
            continue                              # no pool -> no pre-call fetch possible
        t0 = int(d["call_ts"])
        ca = src.get(t0)
        targets.append({"key": ca or ("pool:" + d["pool"]), "ca": ca,
                        "ca_source": "joined_on_call_ts" if ca else "SOURCE-MISSING",
                        "call_ts": t0, "pool": d["pool"]})
    targets.sort(key=lambda c: c["call_ts"])

    done = set()
    if os.path.exists(OUT):
        for line in io.open(OUT, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("key"):
                done.add(d["key"])
    todo = [c for c in targets if c["key"] not in done]
    print("%d pooled calls, %d already done, %d to go (~%d requests, ~%.0f min)"
          % (len(targets), len(done), len(todo), 2 * len(todo),
             2 * len(todo) * PAUSE[0] / 60.0),
          flush=True)

    f = io.open(OUT, "a", encoding="utf-8")
    ok = fail = 0
    tw = time.time()
    for n, c in enumerate(todo):
        t0 = c["call_ts"]
        mins, e1, h1 = ohlc(c["pool"], "minute", t0, LIM_MIN)
        hrs, e2, h2 = ohlc(c["pool"], "hour", t0, LIM_HOUR)
        rec = {"key": c["key"], "ca": c["ca"], "ca_source": c["ca_source"],
               "call_ts": t0, "pool": c["pool"],
               "err_minute": e1, "err_hour": e2, "n429": h1 + h2}
        if (mins is None or not mins) and (hrs is None or not hrs):
            rec["status"] = "SOURCE-MISSING"
            fail += 1
        else:
            rec["status"] = "ok"
            rec.update(features(t0, mins, hrs))
            ok += 1
        f.write(json.dumps(rec) + "\n")
        f.flush()
        if (n + 1) % 20 == 0:
            print("  %d/%d  ok %d  missing %d  429s %d  pause %.1fs  %.0fs"
                  % (n + 1, len(todo), ok, fail, N429[0], PAUSE[0], time.time() - tw),
                  flush=True)
    f.close()
    print("DONE ok %d source-missing %d  total429 %d  final pause %.1fs  in %.0fs"
          % (ok, fail, N429[0], PAUSE[0], time.time() - tw), flush=True)


if __name__ == "__main__":
    main()
