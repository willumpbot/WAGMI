"""Shared plumbing for the laptop crunch layer.

DESIGN RULES, because this runs unattended every hour with nobody watching:
  - NO Claude tokens. Plain python, stdlib plus numpy. Nothing here calls a model.
  - IDEMPOTENT. Every write is an upsert keyed on its natural key, so a re-run after a crash
    or a double-scheduled run cannot duplicate or corrupt anything.
  - sqlite, not parquet. The server brief suggested parquet, but the job`s real requirement is
    append-with-dedup on (coin, t), which a PRIMARY KEY gives for free, inside a transaction
    that survives a partial write. pyarrow is also not installed and this must not depend on a
    heavy wheel staying importable on a machine nobody is watching.
  - NEVER push to a branch that is not the laptop branch. Asserted, not trusted.
"""
import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MINING = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(MINING)))
DB = os.path.join(HERE, "panels.sqlite")
LAPTOP_BRANCH = "laptop-mining-2026-10"
FORBIDDEN = ("main", "master", "desktop-overdrive-2026-05-30")
API = "https://api.hyperliquid.xyz/info"


def log(job, msg):
    print("[%s] %s %s" % (time.strftime("%H:%M:%S"), job, msg), flush=True)


def db():
    c = sqlite3.connect(DB, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init_schema():
    c = db()
    with c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS candles_1h (
              coin TEXT NOT NULL, t INTEGER NOT NULL,
              o REAL, h REAL, l REAL, c REAL, v REAL,
              PRIMARY KEY (coin, t)) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS candles_5m (
              coin TEXT NOT NULL, t INTEGER NOT NULL,
              o REAL, h REAL, l REAL, c REAL, v REAL,
              PRIMARY KEY (coin, t)) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS ctx (
              coin TEXT NOT NULL, t INTEGER NOT NULL,
              mark REAL, oi REAL, funding REAL, premium REAL, ib REAL, ia REAL, dayvlm REAL,
              PRIMARY KEY (coin, t)) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS funding_hist (
              coin TEXT NOT NULL, t INTEGER NOT NULL, rate REAL, premium REAL,
              PRIMARY KEY (coin, t)) WITHOUT ROWID;

            -- append-only run ledger, so a human can see what ran without reading git
            CREATE TABLE IF NOT EXISTS runs (
              started INTEGER, job TEXT, ok INTEGER, rows INTEGER, secs REAL, note TEXT);

            -- J3 replication log: observations only, never verdicts
            CREATE TABLE IF NOT EXISTS replications (
              asof TEXT NOT NULL, metric TEXT NOT NULL, n INTEGER, value REAL, note TEXT,
              PRIMARY KEY (asof, metric));
            """
        )
    c.close()


def upsert(conn, table, cols, rows):
    """Insert-or-replace. Returns rows offered (not rows changed -- sqlite does not
    distinguish cheaply, and the count is only used for the run ledger)."""
    if not rows:
        return 0
    q = "INSERT OR REPLACE INTO %s (%s) VALUES (%s)" % (
        table, ",".join(cols), ",".join("?" * len(cols)))
    with conn:
        conn.executemany(q, rows)
    return len(rows)


def record_run(job, ok, rows, secs, note=""):
    c = db()
    with c:
        c.execute("INSERT INTO runs (started,job,ok,rows,secs,note) VALUES (?,?,?,?,?,?)",
                  (int(time.time()), job, 1 if ok else 0, rows, round(secs, 1), note[:400]))
    c.close()


def post(body, tries=4, pause=0.8):
    """Hyperliquid info endpoint, throttled and retried.

    The 0.8s pause and the backoff are not decoration: an unthrottled sweep of the perp
    universe returned HTTP 429 after 37 coins on 2026-10-11. This job sweeps ~180.
    """
    last = None
    for k in range(tries):
        try:
            rq = urllib.request.Request(
                API, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            out = json.load(urllib.request.urlopen(rq, timeout=45))
            time.sleep(pause)
            return out
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as e:
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError("API failed after %d tries: %s" % (tries, last))


def git(*args, check=True):
    r = subprocess.run(["git"] + list(args), cwd=REPO, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr.strip()[:300]))
    return r.stdout.strip()


def assert_laptop_branch():
    """The hard rule: this machine never writes to the live branches. Checked, not assumed."""
    b = git("rev-parse", "--abbrev-ref", "HEAD")
    if b in FORBIDDEN:
        raise RuntimeError("REFUSING: on forbidden branch %r. The laptop never pushes here." % b)
    if b != LAPTOP_BRANCH:
        raise RuntimeError("REFUSING: on %r, expected %r." % (b, LAPTOP_BRANCH))
    return b
