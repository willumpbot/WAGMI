"""Fetch hourly FUNDING for the whole 178-coin perp universe. 40 cached files were a cache, not a limit.

Companion to fetch_1d_wide.py, and the same lesson a second time. That script found the 17-coin daily
"universe" was a directory listing; here the cause was even plainer -- mission 10's fetcher had
`TOP_N = 40` and started every coin at 2023-01-01 rather than its listing date. The perp universe is
178, so 138 coins had no funding file at all.

Probed before writing this, on coins with no cached file:

    WIF       500 rows from 2023-12-22, next page advances to 2024-02-02
    FARTCOIN  500 rows from 2024-12-20, next page advances to 2025-01-31

So `fundingHistory` caps a response at 500 rows and pages forward from `startTime` without limit --
the deep cached files were built by walking, and nothing stops us walking the other 138.

RATE LIMITING -- the reason v1 of this script was stopped and rewritten. v1 used PAUSE=0.35s, about
2.9 req/s, which is roughly 3x over what HL's `/info` endpoint tolerates for this request weight. It
generated its own HTTP 429s, spent 45 minutes to add 11 coins, and then sat on one coin for 33
minutes grinding through retry backoff. Three defects, all mine:

    1. PAUSE far too aggressive -> self-inflicted 429s. Now 1.1s, and ADAPTIVE: any 429 permanently
       slows the run (up to 3s/page), so the script settles below the limit instead of fighting it.
    2. main()'s exception branch had NO sleep, so a 429 storm would hammer the API with zero pause --
       a feedback loop that makes throttling worse. fetch_1d_wide.py had that sleep; this lost it.
    3. walk() only wrote the CSV after finishing a coin, so an interruption after 50 pages lost all
       50. Now checkpoints every 15 pages.

DEDUPE. Pages are half-open by t_ms and the file may already hold rows, so writes merge into a dict
keyed on t_ms. Append-only writing without dedupe-by-key has caused two separate bugs in this project
(the fetch re-queue and the fat-tail load); every consumer here keys on t_ms.
"""
import csv
import datetime
import io
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "history")
DB = os.path.join(HERE, "crunch", "panels.sqlite")
PAUSE = 1.1              # ~0.9 req/s; v1 used 0.35 and generated its own 429s
PAUSE_MAX = 3.0
PAGE_CAP = 500           # observed response cap
MAX_PAGES = 200          # ~8.3 years of hourly funding; a longer walk is a bug
CHECKPOINT = 15          # flush to disk every N pages so an interruption keeps the work
HOUR = 3600000

_tp = {"pause": PAUSE, "n429": 0}


def post(body, tries=6):
    """POST with 429-aware backoff. A 429 permanently slows the run rather than retrying blind."""
    for i in range(tries):
        try:
            rq = urllib.request.Request(
                "https://api.hyperliquid.xyz/info",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(rq, timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _tp["n429"] += 1
                _tp["pause"] = min(PAUSE_MAX, _tp["pause"] * 1.3)
                ra = (e.headers.get("Retry-After") or "").strip()
                time.sleep(float(ra) if ra.isdigit() else min(60.0, 5.0 * (i + 1)))
                continue
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
    return None


def universe():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    co = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    c.close()
    return co


def read_cache(path):
    """Existing rows as {t_ms: rate}. A malformed line is skipped, never fatal."""
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    out[int(r["t_ms"])] = float(r["rate"])
                except (TypeError, ValueError, KeyError):
                    continue
    except OSError:
        pass
    return out


def listing_ms(coin):
    """First daily bar = the coin's listing date. Falls back to 4 years if no 1d file."""
    p = os.path.join(OUT, "%s_1d.csv" % coin)
    try:
        with io.open(p, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                return int(r["t_ms"])
    except (OSError, TypeError, ValueError, KeyError):
        pass
    return int((time.time() - 4 * 365 * 86400) * 1000)


def write_cache(path, rows):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_ms", "rate"])
        for t in sorted(rows):
            w.writerow([t, repr(rows[t])])
    os.replace(tmp, path)


def walk(coin, start, have, path):
    """Page forward from start, merging into `have` and checkpointing. Returns pages walked."""
    cur, pages, since_flush = start, 0, 0
    while pages < MAX_PAGES:
        r = post({"type": "fundingHistory", "coin": coin, "startTime": cur})
        pages += 1
        since_flush += 1
        if not r:
            break
        for b in r:
            try:
                have[int(b["time"])] = float(b["fundingRate"])
            except (TypeError, ValueError, KeyError):
                continue
        last = max(int(b["time"]) for b in r)
        if since_flush >= CHECKPOINT:
            write_cache(path, have)
            since_flush = 0
        if len(r) < PAGE_CAP or last <= cur:
            break                      # short page = caught up; no advance = guard against a loop
        cur = last + 1
        time.sleep(_tp["pause"])
    return pages


def main():
    os.makedirs(OUT, exist_ok=True)
    coins = universe()
    now = int(time.time() * 1000)
    fresh = updated = failed = current = 0
    tot_rows = tot_pages = 0
    print("funding walk over %d coins | pause %.2fs, adaptive on 429" % (len(coins), PAUSE),
          flush=True)
    t0 = time.time()
    for i, c in enumerate(coins):
        path = os.path.join(OUT, "%s_funding.csv" % c)
        have = read_cache(path)
        new_coin = not have
        start = (max(have) + 1) if have else listing_ms(c)
        if have and now - max(have) < 2 * HOUR:
            tot_rows += len(have)
            current += 1
            continue
        try:
            pages = walk(c, start, have, path)
        except Exception as e:
            print("  %-12s FAILED %s" % (c, e), flush=True)
            failed += 1
            time.sleep(_tp["pause"])        # defect 2: v1 had no pause here
            continue
        tot_pages += pages
        if have:
            write_cache(path, have)
            if new_coin:
                fresh += 1
                d0 = datetime.datetime.fromtimestamp(min(have) / 1000, datetime.UTC).date()
                print("  NEW %-12s %6d rows from %s (%d pages)" % (c, len(have), d0, pages),
                      flush=True)
            else:
                updated += 1
        tot_rows += len(have)
        if (i + 1) % 10 == 0:
            print("  [%3d/%d] %d new, %d topped up, %d current, %d failed | %d rows | "
                  "%d x 429, pause %.2fs | %.0f min"
                  % (i + 1, len(coins), fresh, updated, current, failed, tot_rows,
                     _tp["n429"], _tp["pause"], (time.time() - t0) / 60), flush=True)
        time.sleep(_tp["pause"])
    print("\nDONE: %d new, %d topped up, %d already current, %d failed | %d pages | "
          "%d x 429 | final pause %.2fs | %.0f min"
          % (fresh, updated, current, failed, tot_pages, _tp["n429"], _tp["pause"],
             (time.time() - t0) / 60), flush=True)
    print("funding panel now ~%d hourly rows" % tot_rows, flush=True)


if __name__ == "__main__":
    main()
