"""J6 -- ingest the four unrecoverable streams into the permanent store.

WHY THIS IS THE MOST IMPORTANT INGEST IN THE LAYER. The server's own SPOF audit identified these
four as streams **no API can re-serve**: a Bybit liquidation websocket, L2 order-book depth, HL
whale nets, and every voice reading. The server keeps a rolling window; once a day rotates out of
it, the only copy anywhere is whatever the laptop kept. There is no backfill for a websocket.

AND ONE OF THEM ANSWERS A QUESTION I HAVE ASKED TWICE. `market_depth` carries top-of-book spread
and depth within 0.1% and 0.5% per symbol. `INTRADAY_DISP.md` section 6 asked for precisely that
and called it "the only missing piece between 'the spread exists' and 'the spread was reachable'";
`SMALLCAP_CORRECTION.md` section 5 still records market impact as SOURCE-MISSING. 76 daily shards
of it exist.

WATERMARKED, deliberately. The shards are written once per completed day and never change, so a
shard already ingested is never re-read. That is not only a speed choice: j1 re-reads every CSV
and every snapshot on every hourly run and accumulates them into one list, which the audit costed
at 3-5 GB resident and ~10 GB/day of pointless writes at one year of data. This job does not
repeat that pattern -- it reads new shards only, and upserts per shard rather than per run.
"""
import glob
import gzip
import io
import json
import os
import time

from common import MINING, db, init_schema, log, record_run, upsert

ARCH = os.path.join(MINING, "server_exports", "archive")


def schema():
    c = db()
    with c:
        c.executescript(
            """
            -- the watermark: which day-shards are already folded in
            CREATE TABLE IF NOT EXISTS arch_shards (
              stream TEXT NOT NULL, day TEXT NOT NULL, rows INTEGER, ingested INTEGER,
              PRIMARY KEY (stream, day)) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS liq_events (
              venue TEXT NOT NULL, symbol TEXT NOT NULL, t INTEGER NOT NULL,
              side TEXT, price REAL, qty_base REAL, notional_usd REAL,
              PRIMARY KEY (venue, symbol, t, price, qty_base)) WITHOUT ROWID;

            -- the one that unblocks the reachability question
            CREATE TABLE IF NOT EXISTS depth (
              symbol TEXT NOT NULL, t INTEGER NOT NULL,
              mid REAL, spread REAL, spread_bps REAL,
              bid_01 REAL, ask_01 REAL, imb_01 REAL,
              bid_05 REAL, ask_05 REAL, imb_05 REAL,
              PRIMARY KEY (symbol, t)) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS whales (
              symbol TEXT NOT NULL, t INTEGER NOT NULL,
              short_usd REAL, long_usd REAL, n_short INTEGER, n_long INTEGER,
              PRIMARY KEY (symbol, t)) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS voices (
              symbol TEXT NOT NULL, t INTEGER NOT NULL, voice TEXT NOT NULL,
              px REAL, r REAL, trust TEXT,
              PRIMARY KEY (symbol, t, voice)) WITHOUT ROWID;
            """
        )
    c.close()


def ms(v):
    """Timestamps arrive as ISO strings in two streams and epoch seconds in the other two."""
    if isinstance(v, (int, float)):
        return int(v) * 1000 if v < 1e11 else int(v)
    if not isinstance(v, str) or not v:
        return None
    s = v.replace("Z", "+00:00")
    try:
        import datetime
        return int(datetime.datetime.fromisoformat(s).timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def rows_of(stream, path):
    """Parse one shard into (table, cols, rows). Unparseable lines are skipped, never guessed."""
    out = []
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
                out.append(d)
    except (OSError, EOFError) as e:
        log("j6", "unreadable shard %s: %s" % (os.path.basename(path), e))
        return None, None, []

    if stream == "liq_events":
        rs = []
        for d in out:
            t = ms(d.get("ts_utc"))
            if t is None or not d.get("symbol"):
                continue
            rs.append((d.get("venue") or "?", d["symbol"], t, d.get("side"),
                       d.get("price"), d.get("qty_base"), d.get("notional_usd")))
        return ("liq_events",
                ["venue", "symbol", "t", "side", "price", "qty_base", "notional_usd"], rs)

    if stream == "market_depth":
        rs = []
        for d in out:
            t = ms(d.get("ts"))
            l2 = d.get("l2") or {}
            if t is None or not d.get("symbol") or not l2:
                continue
            rs.append((d["symbol"], t, l2.get("mid"), l2.get("spread"), l2.get("spread_bps"),
                       l2.get("bid_depth_0_1pct"), l2.get("ask_depth_0_1pct"),
                       l2.get("imbalance_0_1pct"), l2.get("bid_depth_0_5pct"),
                       l2.get("ask_depth_0_5pct"), l2.get("imbalance_0_5pct")))
        return ("depth", ["symbol", "t", "mid", "spread", "spread_bps", "bid_01", "ask_01",
                          "imb_01", "bid_05", "ask_05", "imb_05"], rs)

    if stream == "whales":
        rs = []
        for d in out:
            t = ms(d.get("ts"))
            coins = d.get("coins") or {}
            if t is None or not isinstance(coins, dict):
                continue
            for sym, v in coins.items():
                if not isinstance(v, (list, tuple)) or len(v) < 4:
                    continue
                rs.append((sym, t, v[0], v[1], v[2], v[3]))
        # COLUMN NAMES WERE WRONG AND IT WOULD HAVE INVERTED ANY WHALE RESULT.
        # tools/hivemind/whales.py writes, in this order:
        #     [v["net"], v["gross"], v["long"], v["short"]]
        # net is SIGNED notional (+ = net long); gross is total notional; long/short are TRADER
        # COUNTS off a 60-name leaderboard. This stored them positionally as
        # (short_usd, long_usd, n_short, n_long) -- so every one of the four was mislabelled, and
        # the two notional columns were not even the same quantity as their names.
        #
        # Proven four ways on the 21,495 archived rows before renaming: gross > 0 on every row;
        # |net| <= gross on every row (0 violations); min(gross) = $50,003, matching the producer's
        # `gross > 50_000` filter exactly; and when the long count is 0, net == -gross exactly
        # (4,756 rows), which is only possible if those columns are net and gross.
        return ("whales", ["symbol", "t", "net_usd", "gross_usd", "n_long", "n_short"], rs)

    if stream == "voices":
        rs = []
        for d in out:
            t = ms(d.get("ts"))
            if t is None or not d.get("sym") or not d.get("voice"):
                continue
            rs.append((d["sym"], t, d["voice"], d.get("px"), d.get("r"), d.get("trust")))
        return ("voices", ["symbol", "t", "voice", "px", "r", "trust"], rs)

    return None, None, []


STREAMS = ("liq_events", "market_depth", "whales", "voices")


def main():
    t0 = time.time()
    init_schema()
    schema()
    conn = db()
    total = 0
    try:
        if not os.path.isdir(ARCH):
            log("j6", "SOURCE-MISSING: server_exports/archive/ absent -- the server may not have "
                      "synced it yet. That is not the same as there being nothing to archive.")
            record_run("j6_archive", False, 0, time.time() - t0, "archive dir absent")
            return
        done = {(r[0], r[1]) for r in conn.execute("SELECT stream, day FROM arch_shards")}
        for stream in STREAMS:
            paths = sorted(glob.glob(os.path.join(ARCH, stream, "*.jsonl.gz")))
            fresh = [p for p in paths
                     if (stream, os.path.basename(p)[:10]) not in done]
            if not paths:
                log("j6", "%-13s SOURCE-MISSING (no shards)" % stream)
                continue
            n = 0
            for p in fresh:
                day = os.path.basename(p)[:10]
                tbl, cols, rs = rows_of(stream, p)
                if tbl is None:
                    continue
                n += upsert(conn, tbl, cols, rs)
                upsert(conn, "arch_shards", ["stream", "day", "rows", "ingested"],
                       [(stream, day, len(rs), int(time.time()))])
            total += n
            log("j6", "%-13s %3d shards (%d new), %d rows added"
                % (stream, len(paths), len(fresh), n))
        for tbl in ("liq_events", "depth", "whales", "voices"):
            q = conn.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(t), MAX(t) "
                             "FROM %s" % tbl).fetchone()
            span = (q[3] - q[2]) / 86_400_000.0 if q[2] else 0
            log("j6", "  %-11s %8d rows  %4d symbols  %6.1f days" % (tbl, q[0], q[1], span))
        record_run("j6_archive", True, total, time.time() - t0)
    except Exception as e:
        record_run("j6_archive", False, total, time.time() - t0, str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from common import standalone
    standalone(main, 'j6')
