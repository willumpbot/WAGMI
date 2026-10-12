"""J7 -- fold the bot's whole history into the permanent store. The laptop is the archive now.

WHY. The owner moved all heavy research here ("send everything to the laptop"), and the server
shipped `server_exports/bulk/` -- 835,223 rows across 16 streams, 43 MB gzipped from ~420 MB raw,
covering 2026-06 onward. The server keeps a rolling window; the laptop keeps everything.

Streams and what each is good for:
    trade_events            154,850  SIGNAL_GENERATED / TRADE_OPENED / SL_HIT / TP_HIT with
                                     entry, sl, tp1, tp2, atr -- the bot's stop GEOMETRY
    sniper_rejections       279,306  what the bot declined
    counterfactual_resolved 145,595  what would have happened
    agent_performance        59,231
    microcap_wash/liquidity/flow/discovery  ~133k combined
    missed_trades (+resolved) 30,075
    graded_decisions         16,024  carries `pid`
    decisions                10,092
    exit_closes               2,257  decision_id, entry, exit_price, exit_type, hold_time_s,
                                     MFE_PCT -- the best exit-analysis table in the project
    signal_outcomes, thesis_history, exit_regret  ~4,200

WATERMARKED on (stream, shard, size, mtime), the same pattern as j6 and for the same reason: the
audit costed j1's re-read-everything approach at 3-5 GB resident, and this input is an order of
magnitude bigger. A shard already folded in is never re-read. The server appends new shards daily
(each shard = bytes appended since its last run), so steady-state cost is one new shard per stream.

STORED AS RECEIVED. Each row goes into a generic table keyed (stream, rowhash) with the original
JSON intact, rather than into 16 bespoke schemas. Reason: these streams are the server's shapes,
not mine, and they change -- `trade_events` alone carries 7 event types with different fields. A
bespoke schema would silently drop a field the day they add one. The hash makes re-ingest
idempotent without needing a natural key I do not control.
"""
import glob
import gzip
import hashlib
import io
import json
import os
import time

from common import MINING, db, init_schema, log, record_run, upsert

BULK = os.path.join(MINING, "server_exports", "bulk")
CHUNK = 20000          # rows per upsert, so peak memory is a chunk and not a stream


def schema():
    c = db()
    with c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS bulk_rows (
              stream TEXT NOT NULL,
              rowhash TEXT NOT NULL,
              ts REAL,
              sym TEXT,
              kind TEXT,
              body TEXT NOT NULL,
              PRIMARY KEY (stream, rowhash)) WITHOUT ROWID;

            CREATE INDEX IF NOT EXISTS ix_bulk_stream_ts ON bulk_rows(stream, ts);
            CREATE INDEX IF NOT EXISTS ix_bulk_sym ON bulk_rows(sym);

            CREATE TABLE IF NOT EXISTS bulk_shards (
              stream TEXT NOT NULL, shard TEXT NOT NULL,
              size INTEGER, mtime REAL, rows INTEGER, ingested INTEGER,
              PRIMARY KEY (stream, shard)) WITHOUT ROWID;
            """
        )
    c.close()


def as_ts(d):
    """These streams stamp time under several names and in both epoch and ISO form."""
    for k in ("ts", "timestamp", "time", "call_ts", "created_at"):
        v = d.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return float(v) / 1000.0 if v > 1e11 else float(v)
        try:
            import datetime
            return datetime.datetime.fromisoformat(
                str(v).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
    return None


def ingest_shard(conn, stream, path):
    rows, n = [], 0
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                body = json.dumps(d, sort_keys=True, separators=(",", ":"))
                h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:20]
                rows.append((stream, h, as_ts(d),
                             d.get("symbol") or d.get("sym") or d.get("coin"),
                             d.get("event") or d.get("kind") or d.get("action"),
                             body))
                if len(rows) >= CHUNK:
                    n += upsert(conn, "bulk_rows",
                                ["stream", "rowhash", "ts", "sym", "kind", "body"], rows)
                    rows = []
    except (OSError, EOFError) as e:
        log("j7", "unreadable %s/%s: %s" % (stream, os.path.basename(path), e))
        return None
    if rows:
        n += upsert(conn, "bulk_rows",
                    ["stream", "rowhash", "ts", "sym", "kind", "body"], rows)
    return n


def main():
    t0 = time.time()
    init_schema()
    schema()
    conn = db()
    total = 0
    try:
        if not os.path.isdir(BULK):
            log("j7", "SOURCE-MISSING: server_exports/bulk/ absent -- the server may not have "
                      "synced it yet, which is not the same as there being nothing to archive")
            record_run("j7_bulk", False, 0, time.time() - t0, "bulk dir absent")
            return
        done = {(r[0], r[1]): (r[2], r[3])
                for r in conn.execute("SELECT stream, shard, size, mtime FROM bulk_shards")}
        streams = sorted(d for d in os.listdir(BULK)
                         if os.path.isdir(os.path.join(BULK, d)))
        fresh = skipped = 0
        for st in streams:
            for p in sorted(glob.glob(os.path.join(BULK, st, "*.jsonl.gz"))):
                shard = os.path.basename(p)
                try:
                    sz = os.path.getsize(p)
                    mt = round(os.path.getmtime(p), 3)
                except OSError:
                    continue
                prev = done.get((st, shard))
                if prev and prev[0] == sz and abs((prev[1] or 0) - mt) < 0.002:
                    skipped += 1
                    continue
                n = ingest_shard(conn, st, p)
                if n is None:
                    continue
                total += n
                fresh += 1
                upsert(conn, "bulk_shards",
                       ["stream", "shard", "size", "mtime", "rows", "ingested"],
                       [(st, shard, sz, mt, n, int(time.time()))])
                log("j7", "  %-24s %-28s %7d rows" % (st, shard[:28], n))
        log("j7", "%d shards ingested, %d unchanged, %d rows" % (fresh, skipped, total))
        q = conn.execute("SELECT COUNT(*), COUNT(DISTINCT stream) FROM bulk_rows").fetchone()
        log("j7", "bulk_rows now %d rows across %d streams" % (q[0], q[1]))
        for r in conn.execute("SELECT stream, COUNT(*) FROM bulk_rows "
                              "GROUP BY stream ORDER BY COUNT(*) DESC LIMIT 6"):
            log("j7", "    %-26s %8d" % (r[0], r[1]))
        record_run("j7_bulk", True, total, time.time() - t0,
                   "%d shards new, %d unchanged" % (fresh, skipped))
    except Exception as e:
        record_run("j7_bulk", False, total, time.time() - t0, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from common import standalone
    standalone(main, 'j7')
