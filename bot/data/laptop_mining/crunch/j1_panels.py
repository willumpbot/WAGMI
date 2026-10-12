"""J1 -- fold every server export into the laptop's permanent panels.

WHY THIS JOB EXISTS. The server keeps 30 days in its export and Hyperliquid deletes 5m candles
after ~17 days. Both of those facts have already cost this project data once. The laptop has disk
and no retention policy, so the laptop becomes the long-term archive.

WATERMARKED, after an audit costed the previous version at 3-5 GB resident and ~10 GB/day of
pointless writes within a year. It re-read EVERY `history1h/*.csv` and EVERY `ctx_snapshots/*.gz`
on every hourly run, accumulated all of it into one list, and upserted once -- and it would have
died of MemoryError into a gitignored log, under a STATUS.md still reading "All jobs succeeded".

Almost all of that input is STATIC: a finished day's snapshot shard never changes, and the 1h CSVs
only change when the wide fetch reruns. So each source file's (size, mtime) is recorded, and a file
whose stamp is unchanged is skipped entirely. Rows are upserted PER FILE rather than once at the
end, so peak memory is one file rather than the whole archive.

Idempotent either way: every row is keyed (coin, t) and written INSERT OR REPLACE, so a forced
re-read changes nothing. Pass --rescan to ignore the watermark.
"""
import csv
import glob
import gzip
import io
import json
import os
import sys
import time

from common import MINING, db, init_schema, log, record_run, upsert

EXP = os.path.join(MINING, "server_exports")


def ensure_watermark(conn):
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS src_files ("
                     "path TEXT PRIMARY KEY, size INTEGER, mtime REAL, rows INTEGER, seen INTEGER"
                     ") WITHOUT ROWID")


def stamp(p):
    try:
        st = os.stat(p)
        return st.st_size, round(st.st_mtime, 3)
    except OSError:
        return None, None


def unchanged(conn, p):
    sz, mt = stamp(p)
    if sz is None:
        return True                       # unreadable: nothing to do, and not an error here
    r = conn.execute("SELECT size, mtime FROM src_files WHERE path=?", (p,)).fetchone()
    return bool(r and r[0] == sz and abs((r[1] or 0) - mt) < 0.002)


def mark(conn, p, nrows):
    sz, mt = stamp(p)
    with conn:
        conn.execute("INSERT OR REPLACE INTO src_files (path,size,mtime,rows,seen) "
                     "VALUES (?,?,?,?,?)", (p, sz, mt, nrows, int(time.time())))


def ingest_ctx(conn, rescan):
    total = skipped = 0
    for p in sorted(glob.glob(os.path.join(EXP, "ctx_snapshots", "*.jsonl.gz"))):
        if not rescan and unchanged(conn, p):
            skipped += 1
            continue
        rows = []
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    t, coin = d.get("t"), d.get("c")
                    if t is None or not coin:
                        continue
                    # seconds here, milliseconds in the candle files: one time base
                    t = int(t) * 1000 if int(t) < 1e11 else int(t)
                    g = lambda k: (float(d[k]) if d.get(k) not in (None, "") else None)
                    # `orc` (oracle price) is logged by the scanner and was being dropped here.
                    # Mark blends the oracle, so mark-vs-oracle is a free basis measure and it
                    # cannot be back-filled once the snapshot files rotate.
                    rows.append((coin, t, g("mark"), g("oi"), g("fund"), g("prem"),
                                 g("ib"), g("ia"), g("vol"), g("orc")))
        except (OSError, EOFError) as e:
            log("j1", "skipping unreadable %s: %s" % (os.path.basename(p), e))
            continue
        total += upsert(conn, "ctx",
                        ["coin", "t", "mark", "oi", "funding", "premium", "ib", "ia", "dayvlm",
                         "orc"],
                        rows)
        mark(conn, p, len(rows))
    return total, skipped


def ingest_5m(conn, rescan):
    total = skipped = 0
    for p in sorted(glob.glob(os.path.join(EXP, "candles_5m", "*.jsonl"))):
        if not rescan and unchanged(conn, p):
            skipped += 1
            continue
        coin = os.path.basename(p).replace(".jsonl", "")
        rows = []
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                rows.append((coin, int(d["t"]), float(d["o"]), float(d["h"]),
                             float(d["l"]), float(d["c"]), float(d.get("v", 0))))
            except (ValueError, KeyError):
                continue
        total += upsert(conn, "candles_5m", ["coin", "t", "o", "h", "l", "c", "v"], rows)
        mark(conn, p, len(rows))
    return total, skipped


def ingest_history1h(conn, rescan):
    total = skipped = 0
    for p in sorted(glob.glob(os.path.join(MINING, "history1h", "*_1h.csv"))):
        if not rescan and unchanged(conn, p):
            skipped += 1
            continue
        coin = os.path.basename(p).replace("_1h.csv", "")
        rows = []
        with io.open(p, encoding="utf-8") as f:
            rd = csv.reader(f)
            next(rd, None)
            for r in rd:
                try:
                    rows.append((coin, int(r[0]), float(r[1]), float(r[2]),
                                 float(r[3]), float(r[4]), float(r[5])))
                except (ValueError, IndexError):
                    continue
        total += upsert(conn, "candles_1h", ["coin", "t", "o", "h", "l", "c", "v"], rows)
        mark(conn, p, len(rows))
    return total, skipped


def main():
    t0 = time.time()
    rescan = "--rescan" in sys.argv
    init_schema()
    conn = db()
    ensure_watermark(conn)
    n = 0
    try:
        a, sa = ingest_ctx(conn, rescan)
        b, sb = ingest_5m(conn, rescan)
        c, sc = ingest_history1h(conn, rescan)
        n = a + b + c
        log("j1", "ctx %d rows (%d files unchanged), 5m %d (%d), 1h %d (%d)"
            % (a, sa, b, sb, c, sc))
        if not rescan and (sa + sb + sc) and n == 0:
            log("j1", "nothing new: every source file matched its recorded size and mtime")
        for tbl in ("ctx", "candles_5m", "candles_1h"):
            q = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT coin), MIN(t), MAX(t) FROM %s" % tbl).fetchone()
            span = (q[3] - q[2]) / 86_400_000.0 if q[2] else 0
            log("j1", "  %-11s %8d rows  %4d coins  %6.1f days" % (tbl, q[0], q[1], span))
        record_run("j1_panels", True, n, time.time() - t0,
                   "%d source files skipped as unchanged" % (sa + sb + sc))
    except Exception as e:
        record_run("j1_panels", False, n, time.time() - t0, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from common import standalone
    standalone(main, 'j1')
