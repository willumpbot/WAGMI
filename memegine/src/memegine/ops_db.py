"""SQLite persistence for the ops console.

Schema:
    watchlist(handle PK, added_at, note, is_active)
    tweets(id PK, handle, text, created_at, fetched_at, payload_json)
    actions(id PK, tweet_id, kind, slug_or_ref_id, note, at)

Per-project, lives at data/projects/<brand>/ops.sqlite3.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    handle TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tweets (
    id TEXT PRIMARY KEY,
    handle TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    favorite_count INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tweets_handle ON tweets(handle);
CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets(created_at DESC);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id TEXT NOT NULL,
    kind TEXT NOT NULL,               -- grab_ref / brief / video / skip / copy
    slug_or_ref_id TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_actions_tweet ON actions(tweet_id);
"""


def _db_path() -> Path:
    return settings.data_dir / "ops.sqlite3"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Project-scoped SQLite connection. Creates the DB + schema on first use."""
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------- watchlist ----------------

@dataclass
class WatchEntry:
    handle: str
    added_at: str
    note: str
    is_active: bool


def watchlist_add(handle: str, note: str = "") -> WatchEntry:
    handle = handle.lstrip("@").strip().lower()
    if not handle:
        raise ValueError("handle is empty")
    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO watchlist(handle, added_at, note) VALUES (?, ?, ?)",
            (handle, _now(), note),
        )
        if note:
            c.execute("UPDATE watchlist SET note = ? WHERE handle = ?", (note, handle))
        row = c.execute(
            "SELECT handle, added_at, note, is_active FROM watchlist WHERE handle = ?",
            (handle,),
        ).fetchone()
    return WatchEntry(
        handle=row["handle"], added_at=row["added_at"],
        note=row["note"], is_active=bool(row["is_active"]),
    )


def watchlist_remove(handle: str) -> bool:
    handle = handle.lstrip("@").strip().lower()
    with connect() as c:
        cur = c.execute("DELETE FROM watchlist WHERE handle = ?", (handle,))
        return cur.rowcount > 0


def watchlist_list(active_only: bool = True) -> list[WatchEntry]:
    with connect() as c:
        if active_only:
            rows = c.execute(
                "SELECT handle, added_at, note, is_active FROM watchlist "
                "WHERE is_active = 1 ORDER BY handle"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT handle, added_at, note, is_active FROM watchlist "
                "ORDER BY handle"
            ).fetchall()
    return [
        WatchEntry(handle=r["handle"], added_at=r["added_at"],
                   note=r["note"], is_active=bool(r["is_active"]))
        for r in rows
    ]


# ---------------- tweets ----------------

def tweet_upsert(
    *,
    id: str,
    handle: str,
    text: str,
    created_at: str,
    favorite_count: int,
    reply_count: int,
    payload: dict,
) -> None:
    """Insert or update a tweet. payload is the full TweetData dict."""
    with connect() as c:
        c.execute(
            """
            INSERT INTO tweets (id, handle, text, created_at, fetched_at,
                                favorite_count, reply_count, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                favorite_count = excluded.favorite_count,
                reply_count = excluded.reply_count,
                fetched_at = excluded.fetched_at,
                payload_json = excluded.payload_json
            """,
            (id, handle.lstrip("@").lower(), text, created_at, _now(),
             favorite_count, reply_count, json.dumps(payload, ensure_ascii=False)),
        )


def tweets_recent(
    *, limit: int = 50, handle: Optional[str] = None,
) -> list[dict]:
    """Newest-first feed, optionally filtered to one handle."""
    with connect() as c:
        if handle:
            rows = c.execute(
                "SELECT * FROM tweets WHERE handle = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (handle.lstrip("@").lower(), limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM tweets ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    out: list[dict] = []
    for r in rows:
        payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
        out.append({
            "id": r["id"],
            "handle": r["handle"],
            "text": r["text"],
            "created_at": r["created_at"],
            "fetched_at": r["fetched_at"],
            "favorite_count": r["favorite_count"],
            "reply_count": r["reply_count"],
            "url": payload.get("url") or f"https://x.com/{r['handle']}/status/{r['id']}",
            "author_name": payload.get("author_name", ""),
            "symbols": payload.get("symbols", []),
            "hashtags": payload.get("hashtags", []),
            "media_urls": payload.get("media_urls", []),
        })
    return out


# ---------------- actions log ----------------

def action_log(
    *, tweet_id: str, kind: str, slug_or_ref_id: str = "", note: str = "",
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO actions(tweet_id, kind, slug_or_ref_id, note, at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tweet_id, kind, slug_or_ref_id, note, _now()),
        )


def actions_for_tweet(tweet_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT id, kind, slug_or_ref_id, note, at FROM actions "
            "WHERE tweet_id = ? ORDER BY at DESC",
            (tweet_id,),
        ).fetchall()
    return [dict(r) for r in rows]
