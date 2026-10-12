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

COST, measured rather than estimated. The first estimate of "21 hours at 2.1s" was wrong: the free
tier 429s even at 2.1s with a single consumer, the adaptive throttle settles at its 12s cap with a
~21% rejection rate still, and EVM tokens cost extra probes. Measured ETA for the full corpus is
therefore about **7 days**, not one. It is resumable and unattended, so that is acceptable -- but
it is stated here because an optimistic ETA in a docstring is how a multi-day job gets mistaken
for an overnight one.

ORDER: stratified round-robin across chats, newest-first within each -- NOT pure newest-first.
Newest-first was wrong for the question: the headline test is cross-chat transfer (fit on DTN,
test on Syndicate), DTN runs 2025-03 to 2026-06 and Syndicate 2026-08 to 10, so newest-first
delivered the whole HOLDOUT before any of the FIT set and the test could not run until the job
finished. Interleaved, every prefix is balanced (first 300 rows = 100 per chat) and the test is
runnable on partial output.

caller_hash is carried through UNUSED. Z2 (caller form) is a separate question with its own
constraint, and nothing here grades a caller.
"""
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# GeckoTerminal's free tier serves OHLCV only for roughly the last 180 days; older windows return
# HTTP 401, not empty data. Probed both timeframes on a 2025 call whose pool is demonstrably alive:
#
#     hour bars @ call+7d   -> 401 Unauthorized
#     day  bars @ call+7d   -> 401 Unauthorized      (so day bars do not rescue it either)
#     hour bars @ now       -> 200 with data         (control: pool and endpoint are fine)
#
# So a call older than the window cannot be priced at any aggregation, and fetching it spends the
# same 2 requests and 24s of throttle to learn nothing. 15,952 of the 18,437 calls are in that
# region -- 87% of the corpus -- so without this floor roughly six of the pull's seven days buy
# nothing. The floor carries 10 days of headroom because the window slides forward while the pull
# runs: a call 179 days old today is 185 days old when a week-long fetch reaches it.
FLOOR_DAYS = 170
SRC = os.path.join("server_exports", "tg_calls_history_anon.jsonl.gz")
OUT = "megacalls_paths.jsonl"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
PAUSE = 2.1              # starting guess only -- see adapt() below, it self-tunes
APILOCK = "geckoterminal.lock"
_state = {"pause": PAUSE, "n": 0, "n429": 0}


def _holder_alive():
    """Is the pid recorded in the lock file still running?

    Age alone cannot answer "is the holder dead", and treating it as though it could is what
    made the old stale-break dangerous. On Windows OpenProcess is the honest check; if we
    cannot tell, we say ALIVE -- refusing to break a lock we are unsure about is the safe
    direction, since the failure mode of breaking wrongly is two consumers hammering one API.
    """
    try:
        txt = io.open(APILOCK, encoding="utf-8").read()
        pid = int(re.search(r"pid (\d+)", txt).group(1))
    except Exception:
        return True
    if pid == os.getpid():
        return True
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False                      # no such process
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        STILL_ACTIVE = 259
        return (not ok) or code.value == STILL_ACTIVE
    except Exception:
        return True


def heartbeat():
    """Touch the lock so its mtime tracks liveness rather than creation."""
    try:
        os.utime(APILOCK, None)
    except OSError:
        pass


def api_lock_wait():
    """ONE GeckoTerminal consumer at a time, and WAIT rather than collide.

    I caused this. I told a nine-agent swarm "only one agent may call
    api.geckoterminal.com, a parallel sweep will 429 and poison the run for everybody", then
    started this 18k pull against the same API while the swarm's fetch agent was running.
    Measured consequence: 7 of 8 requests returned 429, and each one costs 25-75s of backoff,
    so observed throughput was ~60s per call against the 4.2s the throttle implies -- a 14x
    self-inflicted slowdown.

    So this waits for the lock instead of racing for it: a long resumable job should start the
    moment the API is free, not give up.
    """
    waited = 0
    while True:
        try:
            fd = os.open(APILOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write("pid %d %s" % (os.getpid(), time.strftime("%H:%M:%S")))
            return
        except OSError:
            age = 0
            try:
                age = time.time() - os.path.getmtime(APILOCK)
            except OSError:
                pass
            if age > 600 and not _holder_alive():
                print("breaking API lock: holder is gone (%.0fs since its last "
                      "heartbeat)" % age, flush=True)
                try:
                    os.unlink(APILOCK)
                except OSError:
                    pass
                continue
            if waited % 300 == 0:
                print("waiting for the GeckoTerminal lock (%.0fs)" % waited, flush=True)
            time.sleep(30)
            waited += 30


def adapt(got429):
    """Self-tune the pause from the MEASURED 429 rate instead of guessing it.

    A fixed 2.1s was a guess and it was wrong: the free tier 429s at that rate even with a
    single consumer. Backing off on evidence costs less than a 25s penalty per collision.
    """
    _state["n"] += 1
    if got429:
        _state["n429"] += 1
        _state["pause"] = min(_state["pause"] * 1.35, 12.0)
    elif _state["n"] % 40 == 0 and _state["n429"] / max(_state["n"], 1) < 0.02:
        _state["pause"] = max(_state["pause"] * 0.92, 2.0)   # creep back down when clean
    return _state["pause"]
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
            time.sleep(adapt(False))
            return out, None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(adapt(True) * 2)
                continue
            if e.code in (400, 404):
                return None, "http_%d" % e.code
            time.sleep(4 * (k + 1))
        except Exception:
            time.sleep(4 * (k + 1))
    return None, "unreachable"


GT_BASE = "https://api.geckoterminal.com/api/v2/networks"

# 2.8% of the corpus is EVM (0x, 42 chars) -- but 32% of the SYNDICATE subset is, and Syndicate
# is the cross-chat holdout. A Solana-only fetcher marks every one of them dead, which is the
# same silent-exclusion bias that cost a retraction today, in a new place. So an EVM address is
# probed against the networks it is plausibly on and the answer is recorded on the row.
# Trimmed from 5 to the 3 that actually hit in the first 88 calls (bsc 11, eth 1,
# base 1; arbitrum and polygon_pos hit zero). Each dropped network saves one request
# on every EVM token, and 10 tokens had already burned all five probes for nothing.
EVM_NETWORKS = ("bsc", "eth", "base")


def network_for(ca):
    """Which GeckoTerminal network holds this token? Solana by address shape, else probe."""
    s = str(ca)
    if not (s.startswith("0x") and len(s) == 42):
        return "solana", None
    for net in EVM_NETWORKS:
        d, _err = get("%s/%s/tokens/%s/pools" % (GT_BASE, net, ca))
        if d and (d.get("data") or []):
            return net, None
    return None, "evm_no_network"


def created_ts(a):
    """`pool_created_at` is ISO8601 with a Z suffix."""
    v = a.get("pool_created_at")
    if not v:
        return None
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def best_pool(ca, call_ts, net="solana"):
    """The deepest pool THAT EXISTED AT THE CALL -- not the deepest pool today.

    THIS IS THE FIX FOR THE ERROR THAT CAUSED TODAY'S RETRACTION. The old rule took the deepest
    pool by reserve *today*, which is survivorship-biased twice: a pool that exists today exists
    BECAUSE it survived, and the rule could pick a pool CREATED AFTER THE CALL. For pump.fun
    tokens that migrate it selects the post-migration successor, so the bonding curve that
    actually ran and died is never read. Measured consequence: my take-profit figure came out
    +14%/call against the server's -33%, and the gap was mine.

    One token in this corpus has 13 pools created across nine days, so this is not a corner case.

    KNOWN GAP, stated rather than hidden: the server also MERGES a pump bonding curve with the
    pool it migrated into (their `pool_rule` = "pump->migrated", 38 of their calls). This does
    not. It reads only the pre-existing pool, so a migrated token's path is TRUNCATED at
    migration -- which is conservative: it misses post-migration upside rather than inventing it.
    """
    d, err = get("%s/%s/tokens/%s/pools" % (GT_BASE, net, ca))
    if not d or not isinstance(d, dict):
        return None, err or "no_pool_response"
    pools = d.get("data") or []
    if not pools:
        return None, "no_pools_listed"
    best, bestliq, n_after = None, -1.0, 0
    for p in pools:
        a = p.get("attributes") or {}
        c = created_ts(a)
        if c is not None and c > call_ts:
            n_after += 1
            continue                   # created AFTER the call: could not have been traded then
        try:
            liq = float(a.get("reserve_in_usd") or 0)
        except (TypeError, ValueError):
            liq = 0.0
        pid = (p.get("id") or "").split("_", 1)[-1]
        if pid and liq > bestliq:
            best, bestliq = pid, liq
    if best:
        return best, None
    return None, ("all_%d_pools_created_after_call" % n_after) if n_after else "no_pools_listed"


def ohlc(pool, res, before, net="solana"):
    d, err = get("%s/%s/pools/%s/ohlcv/%s?limit=1000&before_timestamp=%d"
                 % (GT_BASE, net, pool, res, before))
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

    # Drop what the free tier cannot price, and SAY how much -- a silent 87% cut would read as
    # "the corpus is 2,485 calls" to whoever reads the log next.
    floor = time.time() - FLOOR_DAYS * 86400
    walled = [c for c in calls if c["call_ts"] < floor]
    calls = [c for c in calls if c["call_ts"] >= floor]
    if walled:
        wc = {}
        for c in walled:
            wc[c["chat"]] = wc.get(c["chat"], 0) + 1
        print("  PAYWALL FLOOR %s: skipping %d of %d calls (%.0f%%) older than %d days -- they "
              "return 401 at every aggregation, not empty data"
              % (time.strftime("%Y-%m-%d", time.gmtime(floor)), len(walled),
                 len(walled) + len(calls), 100.0 * len(walled) / (len(walled) + len(calls)),
                 FLOOR_DAYS), flush=True)
        print("    unpriceable by chat: %s" % wc, flush=True)
        print("    those calls remain usable for anything price-free (cadence, re-call structure, "
              "and the bot's own x-alert multiples, which are outcomes Phanes reports for free)",
              flush=True)
    # STRATIFIED INTERLEAVE, not pure newest-first.
    #
    # Newest-first was wrong for the question. The headline test is CROSS-CHAT TRANSFER -- fit on
    # the DTN chats, test on Syndicate -- and DTN runs 2025-03 to 2026-06 while Syndicate is
    # 2026-08 to 10. So newest-first would have delivered the entire HOLDOUT before any of the
    # FIT set, and the test would not be runnable until the very end of a multi-day fetch.
    #
    # Round-robin across chats, newest-first within each, so every prefix of the output is
    # balanced across all three and the cross-chat test is runnable on partial data.
    per = {}
    for c in calls:
        per.setdefault(c["chat"], []).append(c)
    for k in per:
        per[k].sort(key=lambda c: -c["call_ts"])
    # ERA INTERLEAVE, added after measuring the corpus rather than assuming it.
    #
    # Round-robin across chats alone was still newest-first WITHIN each chat, and the corpus is
    # not spread evenly in time: dtn_hitters is 93% a 2025 chat (7,295 of 7,821 calls) and
    # syndicate exists only in 2026-08..10. So chat-balanced-but-newest-first delivered an
    # all-2026 prefix -- 211 of 211 fetched calls were 2026 -- and the 2025 bulk, which is most
    # of the corpus, would have arrived days later.
    #
    # That mattered once the holdout turned out to be confounded: syndicate sits 421 days after
    # dtn_hitters' median call, so the cross-chat test is also a 14-month forward test, and the
    # clean comparison is instead WITHIN 2025 (both DTN chats ran concurrently on 277 shared
    # days). Interleaving half-year buckets inside each chat makes BOTH tests runnable on a
    # partial pull instead of only the confounded one.
    def era(c):
        t = time.gmtime(c["call_ts"])
        return (t.tm_year, 1 if t.tm_mon <= 6 else 2)

    buckets = {}
    for k in per:
        for c in per[k]:
            buckets.setdefault((k, era(c)), []).append(c)
    for b in buckets:
        buckets[b].sort(key=lambda c: -c["call_ts"])

    order = sorted(buckets, key=lambda b: (-len(buckets[b]), str(b)))
    out, i = [], 0
    while any(buckets[b] for b in order):
        b = order[i % len(order)]
        if buckets[b]:
            out.append(buckets[b].pop(0))
        i += 1
    return out


def main():
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    calls = load_calls()
    api_lock_wait()
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
    # Report the OPTIMISTIC FLOOR and the MEASURED expectation separately. The old line printed
    # only "21.4 h at 2.1s", which is the floor at the starting pause and nothing like reality:
    # the throttle settles at 12s with ~21% rejections, so the real figure is ~7 days. Printing
    # the floor alone is how a week-long job gets read as an overnight one -- the same mistake
    # the docstring warns about, left in the log by me.
    floor_h = len(todo) * PAUSE * 2 / 3600.0
    real_h = len(todo) * 12.0 * 2 * 1.21 / 3600.0
    print("%d calls in corpus, %d already fetched, %d to go" % (len(calls), len(done), len(todo)),
          flush=True)
    print("  optimistic floor %.1f h (at the %.1fs starting pause); MEASURED expectation "
          "~%.0f h / %.1f days once the throttle settles at its 12s cap with ~21%% rejections"
          % (floor_h, PAUSE, real_h, real_h / 24.0), flush=True)
    print("  order is round-robin across (chat x half-year). The within-2025 test it was built "
          "for is dead -- the free tier paywalls 2025 at 401 -- but the bucketing is kept because "
          "the surviving window still spans two half-years and three chats", flush=True)

    f = io.open(OUT, "a", encoding="utf-8")
    ok = dead = 0
    t0w = time.time()
    for i, c in enumerate(todo):
        heartbeat()                           # the lock's mtime must mean "still alive"
        net, neterr = network_for(c["ca"])
        if not net:
            dead += 1
            f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                "dead": neterr}) + "\n")
            f.flush()
            continue
        pool, err = best_pool(c["ca"], c["call_ts"], net)
        if not pool:
            dead += 1
            f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                "net": net, "dead": err}) + "\n")
            f.flush()
            continue
        t0 = c["call_ts"]
        mins, _e1 = ohlc(pool, "minute", t0 + MIN_H * 3600 + 60, net)
        pm, cm = grids(mins, t0, MIN_H * 3600, 60)
        if pm is None:
            hrs, _e2 = ohlc(pool, "hour", t0 + HOUR_H * 3600 + 3600, net)
            ph, ch = grids(hrs, t0, HOUR_H * 3600, 3600)
            if ph is None:
                dead += 1
                f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                    "pool": pool, "net": net, "dead": "no_path"}) + "\n")
                f.flush()
                continue
            f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                "pool": pool, "net": net,
                                "peak_h": ph, "close_h": ch}) + "\n")
        else:
            f.write(json.dumps({"ca": c["ca"], "chat": c["chat"], "call_ts": c["call_ts"],
                                "pool": pool, "net": net,
                                "peak_m": pm, "close_m": cm}) + "\n")
        f.flush()
        ok += 1
        if (ok + dead) % 50 == 0:
            print("    pause %.1fs, 429 rate %.1f%%"
                  % (_state["pause"], 100.0 * _state["n429"] / max(_state["n"], 1)), flush=True)
            el = time.time() - t0w
            rate = (ok + dead) / max(el, 1)
            print("  %d/%d  live %d  dead %d  %.0fs  eta %.1fh"
                  % (i + 1, len(todo), ok, dead, el,
                     (len(todo) - i - 1) / max(rate, 1e-9) / 3600.0), flush=True)
    f.close()
    try:
        os.unlink(APILOCK)
    except OSError:
        pass
    print("DONE live %d, dead %d, %.0fs. 429 rate %.1f%%, final pause %.1fs"
          % (ok, dead, time.time() - t0w,
             100.0 * _state["n429"] / max(_state["n"], 1), _state["pause"]), flush=True)


if __name__ == "__main__":
    main()
