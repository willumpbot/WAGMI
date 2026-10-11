"""J5 -- keep 1h candles and funding history current for EVERY Hyperliquid perp.

This is the research base for everything else. It paginates backwards in 5000-bar windows until
either the API stops returning new bars or MAX_WINDOWS is hit, then on later runs only fetches
forward from the newest bar it already holds -- so the first run is slow and every run after it
is cheap.

THROTTLING IS NOT OPTIONAL. An unthrottled sweep returned HTTP 429 after 37 of 125 coins on
2026-10-11. common.post sleeps 0.8s per call and backs off on failure; a ~180-coin sweep is
therefore a few minutes, which is fine for an hourly job.
"""
import time

from common import db, init_schema, log, post, record_run, upsert

MAX_WINDOWS = 4          # 4 x 5000 bars ~ 2.3 years of 1h history per coin
BAR_MS = 3_600_000
MIN_BARS = 200


def universe():
    d = post({"type": "metaAndAssetCtxs"})
    out = []
    for u, c in zip(d[0]["universe"], d[1]):
        if u.get("isDelisted"):
            continue
        try:
            v = float(c.get("dayNtlVlm") or 0)
        except (TypeError, ValueError):
            v = 0.0
        out.append((u["name"], v))
    out.sort(key=lambda r: -r[1])
    return out


def newest(conn, table, coin):
    r = conn.execute("SELECT MAX(t) FROM %s WHERE coin=?" % table, (coin,)).fetchone()
    return r[0] if r and r[0] else None


def fetch_1h(conn, coin):
    """Forward-fill if we already hold history, else paginate backwards from now."""
    have = newest(conn, "candles_1h", coin)
    now = int(time.time() * 1000)
    rows = []
    if have:
        c = post({"type": "candleSnapshot",
                  "req": {"coin": coin, "interval": "1h", "startTime": have, "endTime": now}})
        for b in c or []:
            rows.append((coin, int(b["t"]), float(b["o"]), float(b["h"]),
                         float(b["l"]), float(b["c"]), float(b.get("v", 0))))
    else:
        end = now
        for _ in range(MAX_WINDOWS):
            start = end - 5000 * BAR_MS
            c = post({"type": "candleSnapshot",
                      "req": {"coin": coin, "interval": "1h",
                              "startTime": start, "endTime": end}})
            if not c:
                break
            for b in c:
                rows.append((coin, int(b["t"]), float(b["o"]), float(b["h"]),
                             float(b["l"]), float(b["c"]), float(b.get("v", 0))))
            oldest = min(int(b["t"]) for b in c)
            if oldest >= end - BAR_MS or len(c) < 1000:
                break      # the API has no more history for this coin
            end = oldest
    return upsert(conn, "candles_1h", ["coin", "t", "o", "h", "l", "c", "v"], rows)


def fetch_funding(conn, coin):
    have = newest(conn, "funding_hist", coin)
    start = have if have else int(time.time() * 1000) - 365 * 86_400_000
    try:
        h = post({"type": "fundingHistory", "coin": coin, "startTime": start})
    except RuntimeError:
        return 0
    rows = []
    for r in h or []:
        try:
            rows.append((coin, int(r["time"]), float(r["fundingRate"]),
                         float(r.get("premium") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return upsert(conn, "funding_hist", ["coin", "t", "rate", "premium"], rows)


def main():
    t0 = time.time()
    init_schema()
    conn = db()
    total = 0
    done = 0
    failed = []
    try:
        uni = universe()
        log("j5", "%d live perps to keep current" % len(uni))
        for coin, vol in uni:
            try:
                total += fetch_1h(conn, coin)
                total += fetch_funding(conn, coin)
                done += 1
            except Exception as e:
                failed.append("%s:%s" % (coin, str(e)[:40]))
            if done and done % 40 == 0:
                log("j5", "  %d/%d coins, %d rows, %.0fs" % (done, len(uni), total,
                                                             time.time() - t0))
        note = "%d coins ok, %d failed" % (done, len(failed))
        if failed:
            note += " | " + ", ".join(failed[:6])
        log("j5", note)
        record_run("j5_backfill", not failed, total, time.time() - t0, note)
    except Exception as e:
        record_run("j5_backfill", False, total, time.time() - t0, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
