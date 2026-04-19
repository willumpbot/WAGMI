"""Topic queue — append-only feed of ideas, trends, and news hooks.

This is the raw input to the scheduler: operator (or a manual trend-scraper)
drops topics into this queue during the day, and the scheduler pulls from it
to build daily/weekly brief batches.

Storage: YAML at data/topics/queue.yaml so it's easy to hand-edit on your
phone or copy-paste from a note. Each entry is dict-shaped, no DB needed.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from ._time import now_iso as _now_iso
from .config import settings


@dataclass
class Topic:
    id: str
    created_at: str
    text: str                       # the raw intent/observation ("trader dumping at 3am")
    tags: list[str] = field(default_factory=list)   # e.g. ["reaction", "night"]
    kind: str = "any"               # "image" | "video" | "any" — operator preference
    format_hint: str | None = None  # optional format slug override
    priority: int = 3               # 1 (drop first) .. 5 (urgent)
    status: str = "queued"          # "queued" | "used" | "skipped"
    used_at: str | None = None
    used_bundle_id: str | None = None
    source: str = ""                # "operator" | "telegram" | "scraper" | ...


def _queue_path() -> Path:
    return settings.data_dir / "topics" / "queue.yaml"


def _ensure_dir() -> None:
    p = _queue_path().parent
    p.mkdir(parents=True, exist_ok=True)


def _load(path: Path | None = None) -> list[dict]:
    path = path or _queue_path()
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    topics = raw.get("topics", []) if isinstance(raw, dict) else raw
    return list(topics or [])


def _save(topics: list[dict], path: Path | None = None) -> None:
    path = path or _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"topics": topics}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def add(
    text: str,
    *,
    tags: Iterable[str] | None = None,
    kind: str = "any",
    format_hint: str | None = None,
    priority: int = 3,
    source: str = "operator",
    path: Path | None = None,
) -> Topic:
    """Append a topic to the queue. Returns the created Topic."""
    _ensure_dir()
    tid = uuid.uuid4().hex[:8]
    topic = Topic(
        id=tid,
        created_at=_now_iso(),
        text=text.strip(),
        tags=[t.strip() for t in (tags or []) if t.strip()],
        kind=kind,
        format_hint=format_hint,
        priority=max(1, min(5, int(priority))),
        source=source,
    )
    topics = _load(path)
    topics.append(asdict(topic))
    _save(topics, path)
    return topic


def list_queued(
    *,
    limit: int | None = None,
    status: str = "queued",
    path: Path | None = None,
) -> list[dict]:
    """Return queued topics sorted by priority desc then created_at asc."""
    topics = [t for t in _load(path) if t.get("status") == status]
    topics.sort(key=lambda t: (-int(t.get("priority", 3)), t.get("created_at", "")))
    return topics[:limit] if limit else topics


def pop(
    n: int = 1,
    *,
    mark_used: bool = True,
    path: Path | None = None,
) -> list[dict]:
    """Take the top N queued topics.

    If mark_used=True, update their status to 'used' in the queue file. That
    way a scheduled batch is idempotent — rerunning won't reuse topics.
    """
    topics = _load(path)
    queued = sorted(
        [t for t in topics if t.get("status") == "queued"],
        key=lambda t: (-int(t.get("priority", 3)), t.get("created_at", "")),
    )
    picked = queued[:n]
    if mark_used and picked:
        ids = {p["id"] for p in picked}
        now = _now_iso()
        for t in topics:
            if t.get("id") in ids:
                t["status"] = "used"
                t["used_at"] = now
        _save(topics, path)
    return picked


def mark_used(topic_id: str, bundle_id: str | None = None, path: Path | None = None) -> bool:
    topics = _load(path)
    hit = False
    now = _now_iso()
    for t in topics:
        if t.get("id") == topic_id:
            t["status"] = "used"
            t["used_at"] = now
            if bundle_id:
                t["used_bundle_id"] = bundle_id
            hit = True
    if hit:
        _save(topics, path)
    return hit


def skip(topic_id: str, path: Path | None = None) -> bool:
    topics = _load(path)
    hit = False
    for t in topics:
        if t.get("id") == topic_id:
            t["status"] = "skipped"
            hit = True
    if hit:
        _save(topics, path)
    return hit


def remove(topic_id: str, path: Path | None = None) -> bool:
    topics = _load(path)
    before = len(topics)
    topics = [t for t in topics if t.get("id") != topic_id]
    if len(topics) != before:
        _save(topics, path)
        return True
    return False


def clear(path: Path | None = None) -> int:
    topics = _load(path)
    n = len(topics)
    _save([], path)
    return n


def stats(path: Path | None = None) -> dict[str, int]:
    topics = _load(path)
    out: dict[str, int] = {"total": len(topics), "queued": 0, "used": 0, "skipped": 0}
    for t in topics:
        s = t.get("status", "queued")
        out[s] = out.get(s, 0) + 1
    return out
