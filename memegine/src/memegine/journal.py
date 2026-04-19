"""Journal — one chronological feed across every memegine store.

Answers "what have I done lately?" with a single reverse-chronological
list. Briefs, refs, post bundles, winners, and session markers are all
folded together so the operator can see their week as a timeline.

Each entry is {kind, at, summary, id}. kinds: brief | ref | post |
winner | session.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from . import archive, export as export_mod, reference_lib, session as session_mod
from ._time import now_naive_utc as _now_naive_utc
from .config import settings


@dataclass
class JournalEntry:
    at: str
    kind: str               # "brief" | "ref" | "winner" | "post" | "session_start" | "session_end"
    summary: str
    id: str = ""

    def as_line(self) -> str:
        stamp = self.at[:19].replace("T", " ")
        return f"{stamp}  [{self.kind:<14}]  {self.summary[:100]}"


def _parse_iso(s: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return dt.datetime(1970, 1, 1)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def collect(days: int | None = None, limit: int | None = None) -> list[JournalEntry]:
    """Return a reverse-chronological journal of all activity.

    days: if given, only include entries within the last N days.
    limit: if given, return at most that many entries.
    """
    now = _now_naive_utc()
    cutoff = now - dt.timedelta(days=days) if days else None
    out: list[JournalEntry] = []

    # Briefs from archive.
    for rec in archive.read_recent(n=500):
        at = rec.get("created_at", "")
        if cutoff and _parse_iso(at) < cutoff:
            continue
        intent = rec.get("intent", "").strip()
        kind = rec.get("kind", "?")
        out.append(JournalEntry(
            at=at,
            kind="brief",
            summary=f"{kind}: {intent[:80]}",
            id=rec.get("id", ""),
        ))

    # Refs.
    for ref in reference_lib._load_index():
        at = ref.get("added_at", "")
        if cutoff and _parse_iso(at) < cutoff:
            continue
        is_winner = "winner" in ref.get("tags", [])
        out.append(JournalEntry(
            at=at,
            kind="winner" if is_winner else "ref",
            summary=ref.get("notes") or ref.get("prompt", "")[:80] or ref["filename"],
            id=ref.get("id", ""),
        ))

    # Posts.
    for p in export_mod.list_recent(n=200):
        at = p.get("created_at", "")
        if cutoff and _parse_iso(at) < cutoff:
            continue
        out.append(JournalEntry(
            at=at, kind="post",
            summary=p.get("caption", "")[:80],
            id=p.get("id", ""),
        ))

    # Session markers.
    for s in session_mod.list_sessions():
        started = s.get("started_at")
        if started and (not cutoff or _parse_iso(started) >= cutoff):
            out.append(JournalEntry(
                at=started,
                kind="session_start",
                summary=f"session '{s.get('name') or s['session_id']}' started",
                id=s.get("session_id", "")[:8],
            ))
        ended = s.get("ended_at")
        if ended and (not cutoff or _parse_iso(ended) >= cutoff):
            dur = s.get("duration_sec")
            dur_str = f" ({dur//60}min)" if dur else ""
            out.append(JournalEntry(
                at=ended,
                kind="session_end",
                summary=f"session '{s.get('name') or s['session_id']}' ended{dur_str}",
                id=s.get("session_id", "")[:8],
            ))

    out.sort(key=lambda e: e.at, reverse=True)
    if limit:
        out = out[:limit]
    return out


def as_text(entries: list[JournalEntry]) -> str:
    if not entries:
        return "(no journal entries)"
    lines = [f"=== journal — {len(entries)} entries ==="]
    for e in entries:
        lines.append(e.as_line())
    return "\n".join(lines)
