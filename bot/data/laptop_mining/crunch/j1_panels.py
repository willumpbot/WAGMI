"""J1 -- fold every server export into the laptop`s permanent panels.

WHY THIS JOB EXISTS. The server keeps 30 days in its export and Hyperliquid deletes 5m candles
after ~17 days. Both of those facts have already cost this project data once. The laptop has disk
and no retention policy, so the laptop becomes the long-term archive. Today there are 2 days of
ctx_snapshots sitting locally; in a year there should be 365.

Idempotent by construction: every row is keyed (coin, t) and written INSERT OR REPLACE, so running
this twice in an hour, or re-running after a crash, changes nothing.
"""
import glob
import gzip
import io
import json
import os
import time

from common import MINING, db, init_schema, log, record_run, upsert

EXP = os.path.join(MINING, "server_exports")


def ingest_ctx(conn):
    rows = []
    for p in sorted(glob.glob(os.path.join(EXP, "ctx_snapshots", "*.jsonl.gz"))):
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
                    t = d.get("t")
                    coin = d.get("c")
                    if t is None or not coin:
                        continue
                    # the export stamps SECONDS here and MILLISECONDS in the candle files;
                    # normalise to ms so every table shares one time base
                    t = int(t) * 1000 if int(t) < 1e11 else int(t)
                    g = lambda k: (float(d[k]) if d.get(k) not in (None, "") else None)
                    rows.append((coin, t, g("mark"), g("oi"), g("fund"), g("prem"),
                                 g("ib"), g("ia"), g("vol")))
        except (OSError, EOFError) as e:
            log("j1", "skipping unreadable %s: %s" % (os.path.basename(p), e))
    return upsert(conn, "ctx",
                  ["coin", "t", "mark", "oi", "funding", "premium", "ib", "ia", "dayvlm"], rows)


def ingest_5m(conn):
    rows = []
    for p in sorted(glob.glob(os.path.join(EXP, "candles_5m", "*.jsonl"))):
        coin = os.path.basename(p).replace(".jsonl", "")
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
    return upsert(conn, "candles_5m", ["coin", "t", "o", "h", "l", "c", "v"], rows)


def ingest_history1h(conn):
    """The 1h research panel built on 2026-10-11 (169 coins). J5 keeps it current from the
    API; this folds whatever CSVs exist into the db so both paths converge on one store."""
    rows = []
    import csv
    for p in sorted(glob.glob(os.path.join(MINING, "history1h", "*_1h.csv"))):
        coin = os.path.basename(p).replace("_1h.csv", "")
        with io.open(p, encoding="utf-8") as f:
            rd = csv.reader(f)
            next(rd, None)
            for r in rd:
                try:
                    rows.append((coin, int(r[0]), float(r[1]), float(r[2]),
                                 float(r[3]), float(r[4]), float(r[5])))
                except (ValueError, IndexError):
                    continue
    return upsert(conn, "candles_1h", ["coin", "t", "o", "h", "l", "c", "v"], rows)


def main():
    t0 = time.time()
    init_schema()
    conn = db()
    n = 0
    try:
        a = ingest_ctx(conn)
        b = ingest_5m(conn)
        c = ingest_history1h(conn)
        n = a + b + c
        log("j1", "ctx %d rows, 5m %d rows, 1h %d rows" % (a, b, c))
        for tbl in ("ctx", "candles_5m", "candles_1h"):
            q = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT coin), MIN(t), MAX(t) FROM %s" % tbl).fetchone()
            span = (q[3] - q[2]) / 86_400_000.0 if q[2] else 0
            log("j1", "  %-11s %8d rows  %4d coins  %6.1f days" % (tbl, q[0], q[1], span))
        record_run("j1_panels", True, n, time.time() - t0)
    except Exception as e:
        record_run("j1_panels", False, n, time.time() - t0, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from common import standalone
    standalone(main, 'j1')
