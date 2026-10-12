"""Fetch hourly FUNDING for the whole 178-coin perp universe. 40 cached files were a cache, not a limit.

Companion to fetch_1d_wide.py, and the same lesson a second time. That script found the 17-coin daily
"universe" was a directory listing; this one finds the funding side was too. `history/*_funding.csv`
holds 40 perp files -- kPEPE/LTC/BNB at 29,331 hourly rows each, back to 2023 -- and `SIZE_FLAGS` drew
its 160 week-clusters from them. But the perp universe is 178 coins, so 138 have NO funding cache.

Probed before writing this, on coins with no cached file:

    WIF       500 rows from 2023-12-22, next page advances to 2024-02-02
    FARTCOIN  500 rows from 2024-12-20, next page advances to 2025-01-31

So `fundingHistory` caps a response at 500 rows and pages forward from `startTime` without limit --
the deep cached files were built by walking, and nothing stops us walking the other 138.

EFFICIENCY NOTE. A blind 4-year walk would be ~50 wasted pages for a coin listed 3 months ago. Each
coin's start is seeded from the first bar in its `<COIN>_1d.csv` (written by fetch_1d_wide.py), which
IS its listing date, so every request lands inside real history. Resume uses the last cached t_ms.

DEDUPE. Pages are half-open by t_ms and the file may already hold rows, so writes merge into a dict
keyed on t_ms. Append-only JSONL/CSV without dedupe-by-key has now caused two separate bugs in this
project (the fetch re-queue and the fat-tail load); every consumer here keys on t_ms.
"""
import csv
import datetime
import io
import json
import os
import sqlite3
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "history")
DB = os.path.join(HERE, "crunch", "panels.sqlite")
PAUSE = 0.35
PAGE_CAP = 500           # observed response cap
MAX_PAGES = 200          # ~8.3 years of hourly funding; a walk longer than this is a bug
HOUR = 3600000


def post(body, tries=4):
    for i in range(tries):
        try:
            rq = urllib.request.Request(
                "https://api.hyperliquid.xyz/info",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(rq, timeout=45) as r:
                return json.loads(r.read().decode())
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


def walk(coin, start):
    """Page forward from start. Returns {t_ms: rate}. Stops on a short page or no advance."""
    got, cur, pages = {}, start, 0
    while pages < MAX_PAGES:
        r = post({"type": "fundingHistory", "coin": coin, "startTime": cur})
        pages += 1
        if not r:
            break
        for b in r:
            try:
                got[int(b["time"])] = float(b["fundingRate"])
            except (TypeError, ValueError, KeyError):
                continue
        last = max(int(b["time"]) for b in r)
        if len(r) < PAGE_CAP or last <= cur:
            break                      # short page = caught up; no advance = guard against a loop
        cur = last + 1
        time.sleep(PAUSE)
    return got, pages


def main():
    os.makedirs(OUT, exist_ok=True)
    coins = universe()
    now = int(time.time() * 1000)
    fresh = updated = failed = 0
    tot_rows = tot_pages = 0
    print("funding walk over %d coins (138 with no cache)" % len(coins))
    t0 = time.time()
    for i, c in enumerate(coins):
        path = os.path.join(OUT, "%s_funding.csv" % c)
        have = read_cache(path)
        new_coin = not have
        start = (max(have) + 1) if have else listing_ms(c)
        if have and now - max(have) < 2 * HOUR:
            tot_rows += len(have)
            continue                   # already current
        try:
            got, pages = walk(c, start)
        except Exception as e:
            print("  %-12s FAILED %s" % (c, e))
            failed += 1
            continue
        tot_pages += pages
        if got:
            have.update(got)
            write_cache(path, have)
            if new_coin:
                fresh += 1
                d0 = datetime.datetime.fromtimestamp(min(have) / 1000, datetime.UTC).date()
                print("  NEW %-12s %6d rows from %s (%d pages)" % (c, len(have), d0, pages))
            else:
                updated += 1
        tot_rows += len(have)
        if (i + 1) % 20 == 0:
            el = time.time() - t0
            print("  [%3d/%d] %d new, %d topped up, %d failed | %d rows | %.0fs elapsed"
                  % (i + 1, len(coins), fresh, updated, failed, tot_rows, el))
        time.sleep(PAUSE)
    print("\nDONE: %d new coins, %d topped up, %d failed, %d pages in %.0f min"
          % (fresh, updated, failed, tot_pages, (time.time() - t0) / 60))
    print("funding panel now ~%d hourly rows" % tot_rows)


if __name__ == "__main__":
    main()
