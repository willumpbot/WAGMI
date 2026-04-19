"""Sessions — mark the start and end of a working block.

An operator working late produces briefs from 9pm to 1am. Another working
the morning produces briefs from 7am to 9am. These shouldn't be bucketed
as "today's activity" as if they were one session — they're different
energy.

Memegine sessions are pure markers. `start` writes a session-start event
with an optional name; `end` closes the most recent open session. The
stats module can group by session by reading the events file.

Events are JSONL at `data/sessions/events.jsonl`. One line per event
(start | end). Session boundaries are defined by the start/end pairs;
if `end` is called without an open session, it's a no-op.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ._time import now_iso as _now_iso
from .config import settings


@dataclass
class SessionEvent:
    id: str
    session_id: str
    kind: str              # "start" | "end"
    at: str                # ISO timestamp, UTC
    name: str = ""
    notes: str = ""
    metadata: dict = field(default_factory=dict)


def _events_path() -> Path:
    return settings.data_dir / "sessions" / "events.jsonl"


def _read_events() -> list[dict]:
    p = _events_path()
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append_event(event: SessionEvent) -> None:
    p = _events_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")


def _open_session() -> dict | None:
    """Return the most recent unclosed session (or None)."""
    events = _read_events()
    # Walk chronologically; track currently-open session_id.
    open_session: dict | None = None
    for e in events:
        if e.get("kind") == "start":
            open_session = e
        elif e.get("kind") == "end" and open_session and e.get("session_id") == open_session.get("session_id"):
            open_session = None
    return open_session


def start(name: str = "", notes: str = "") -> SessionEvent:
    """Start a new session. If another is already open, close it first."""
    existing = _open_session()
    if existing:
        end(notes="auto-closed on new session start")
    session_id = uuid.uuid4().hex[:10]
    event = SessionEvent(
        id=uuid.uuid4().hex[:8],
        session_id=session_id,
        kind="start",
        at=_now_iso(),
        name=name,
        notes=notes,
    )
    _append_event(event)
    return event


def end(notes: str = "") -> SessionEvent | None:
    """Close the current session. No-op if none is open."""
    open_s = _open_session()
    if not open_s:
        return None
    event = SessionEvent(
        id=uuid.uuid4().hex[:8],
        session_id=open_s["session_id"],
        kind="end",
        at=_now_iso(),
        name=open_s.get("name", ""),
        notes=notes,
    )
    _append_event(event)
    return event


def current() -> dict | None:
    """Return info about the currently-open session, or None."""
    return _open_session()


def list_sessions() -> list[dict]:
    """Return [{session_id, name, started_at, ended_at, duration_sec}, ...]."""
    events = _read_events()
    sessions: dict[str, dict] = {}
    for e in events:
        sid = e.get("session_id")
        if not sid:
            continue
        entry = sessions.setdefault(sid, {
            "session_id": sid, "name": e.get("name", ""),
            "started_at": None, "ended_at": None,
        })
        if e.get("kind") == "start" and not entry["started_at"]:
            entry["started_at"] = e["at"]
            if e.get("name"):
                entry["name"] = e["name"]
        elif e.get("kind") == "end":
            entry["ended_at"] = e["at"]

    out = []
    for s in sessions.values():
        if not s["started_at"]:
            continue
        if s["ended_at"]:
            try:
                a = dt.datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
                b = dt.datetime.fromisoformat(s["ended_at"].replace("Z", "+00:00"))
                s["duration_sec"] = int((b - a).total_seconds())
            except ValueError:
                s["duration_sec"] = None
        else:
            s["duration_sec"] = None
        out.append(s)
    out.sort(key=lambda s: s.get("started_at", ""), reverse=True)
    return out


def session_window(session_id: str) -> tuple[str, str] | None:
    """Return (started_at, ended_at or 'now'-ish) for a session."""
    for s in list_sessions():
        if s["session_id"].startswith(session_id):
            ended = s["ended_at"] or _now_iso()
            return s["started_at"], ended
    return None
