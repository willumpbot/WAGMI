"""Fetch DAILY candles for the whole 178-coin perp universe. The 17-coin limit was a cache, not data.

WHY THIS EXISTS. I told the owner the deep-history universe was 17 perps, because `history/*_1d.csv`
holds 17 perp files and `SIZE_FLAGS` used all of them. He pushed back -- "there's probably always
another angle or a way around a problem" -- and he was right: the 17 files are a local cache someone
built, not the limit of what Hyperliquid will serve.

Probed before writing this, on coins with no cached file:

    WIF       1,026 daily bars   from 2023-12-22
    PENGU       665              from 2024-12-17
    FARTCOIN    662              from 2024-12-20
    0G          391              from 2025-09-17
    CASHCAT      94              from 2026-07-11

Every coin serves daily history back to its own listing date. So the deep panel is not 17 coins x
1,168 dates -- it is up to 178 coins, each back to listing, and the binding constraint becomes
listing age rather than cache coverage.

1d is cheap where 1h is not: HL caps a candleSnapshot response at ~5,000 bars, which is ~208 days of
1h (hence the 210-date hourly panel) but ~13.7 YEARS of 1d. One request per coin covers everything.
"""
import csv
import io
import json
import os
import sqlite3
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "history")
DB = os.path.join(HERE, "crunch", "panels.sqlite")
PAUSE = 0.6


def post(body, tries=4):
    for i in range(tries):
        try:
            rq = urllib.request.Request(
                "https://api.hyperliquid.xyz/info",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(rq, timeout=45) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
    return None


def universe():
    """The coins the hourly panel already tracks -- the live perp universe."""
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    co = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    c.close()
    return co


def main():
    os.makedirs(OUT, exist_ok=True)
    coins = universe()
    now = int(time.time() * 1000)
    start = now - 2500 * 86400000          # ~6.8 years; coins return from their listing date
    got = skipped = failed = 0
    total_rows = 0
    print("fetching 1d for %d coins (one request each, ~%.0f s)" % (len(coins), len(coins) * PAUSE))
    for i, c in enumerate(coins):
        path = os.path.join(OUT, "%s_1d.csv" % c)
        # refetch anything thinner than a year -- a stale partial cache is worse than none
        if os.path.exists(path):
            try:
                n = sum(1 for _ in io.open(path, encoding="utf-8")) - 1
            except OSError:
                n = 0
            if n > 365:
                skipped += 1
                total_rows += n
                continue
        try:
            rows = post({"type": "candleSnapshot",
                         "req": {"coin": c, "interval": "1d",
                                 "startTime": start, "endTime": now}})
        except Exception as e:
            print("  %-12s FAILED %s" % (c, e))
            failed += 1
            time.sleep(PAUSE)
            continue
        if not rows:
            failed += 1
            time.sleep(PAUSE)
            continue
        with io.open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t_ms", "o", "h", "l", "c", "v"])
            for b in rows:
                w.writerow([b["t"], b["o"], b["h"], b["l"], b["c"], b.get("v", 0)])
        got += 1
        total_rows += len(rows)
        if got % 25 == 0:
            print("  %d fetched, %d cached, %d failed (%d/%d)" % (got, skipped, failed, i + 1, len(coins)))
        time.sleep(PAUSE)
    print("\nDONE: %d fetched, %d already cached, %d failed" % (got, skipped, failed))
    print("daily panel now ~%d coin-days across %d coins" % (total_rows, got + skipped))


if __name__ == "__main__":
    main()
