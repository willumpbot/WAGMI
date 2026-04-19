"""Stats — daily / weekly activity report.

Combines signal from:
- brief archive (briefs by kind)
- reference library (refs added, winners)
- style codex (entries by section)
- topic queue (queued / used / skipped)
- post bundles (posts made)

Output is a structured `ActivityReport` the operator can print via
`memegine stats` or pipe to the Telegram bot via /stats.

Cadence: `daily` = today only. `weekly` = last 7 full days. `all` = everything.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import export as export_mod, reference_lib, style_codex, topics
from ._time import now_naive_utc as _now_naive_utc
from .config import settings


@dataclass
class ActivityReport:
    window: str                          # "daily" | "weekly" | "all"
    started_at: str
    ended_at: str
    briefs_by_kind: dict[str, int] = field(default_factory=dict)
    briefs_total: int = 0
    refs_total: int = 0
    refs_winners: int = 0
    refs_added_in_window: int = 0
    codex_sections: dict[str, int] = field(default_factory=dict)   # section → # bullets
    topics_stats: dict[str, int] = field(default_factory=dict)
    posts_in_window: int = 0
    posts_total: int = 0
    top_tags: list[tuple[str, int]] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"=== memegine activity — {self.window} ({self.started_at[:10]} → {self.ended_at[:10]}) ===",
            "",
            "briefs:",
            f"  total in window: {self.briefs_total}",
        ]
        for kind, n in sorted(self.briefs_by_kind.items(), key=lambda x: -x[1]):
            lines.append(f"  {kind:<18} {n}")
        lines += [
            "",
            "refs:",
            f"  total:                {self.refs_total}",
            f"  winners:              {self.refs_winners}",
            f"  added in window:      {self.refs_added_in_window}",
        ]
        if self.top_tags:
            lines.append("  top tags:             " + ", ".join(
                f"{t}×{c}" for t, c in self.top_tags
            ))
        lines += [
            "",
            "codex:",
        ]
        for section, count in self.codex_sections.items():
            lines.append(f"  {section:<28} {count} entries")
        lines += [
            "",
            "topic queue:",
            f"  total={self.topics_stats.get('total', 0)}  "
            f"queued={self.topics_stats.get('queued', 0)}  "
            f"used={self.topics_stats.get('used', 0)}  "
            f"skipped={self.topics_stats.get('skipped', 0)}",
            "",
            "posts:",
            f"  in window: {self.posts_in_window}",
            f"  total:     {self.posts_total}",
        ]
        return "\n".join(lines)


def _window_bounds(window: str, now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    if window == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if window == "weekly":
        start = (now - dt.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if window == "all":
        return dt.datetime(1970, 1, 1), now
    raise ValueError(f"unknown window: {window}")


def _iter_archive_lines(logs_dir: Path) -> list[dict]:
    if not logs_dir.exists():
        return []
    rows: list[dict] = []
    for f in sorted(logs_dir.glob("briefs-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _count_codex_sections(codex_text: str) -> dict[str, int]:
    """Return a map of section header → number of bullet entries (lines starting with '-')."""
    sections: dict[str, int] = {}
    current: str | None = None
    for line in codex_text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = 0
        elif current and line.lstrip().startswith("- "):
            if not line.strip().startswith("- ("):
                # Treat stub-example lines "- (empty)" as placeholder
                if "(empty)" in line or "(none yet)" in line:
                    continue
            sections[current] += 1
    return sections


def _parse_iso(s: str) -> dt.datetime:
    """Parse an ISO-formatted string and return a naive UTC datetime.

    We compare against naive UTC-ish datetimes from _window_bounds so
    both sides must be naive. Strip timezone info after parsing.
    """
    try:
        parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return dt.datetime(1970, 1, 1)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def compute(
    *,
    window: str = "daily",
    now: dt.datetime | None = None,
    logs_dir: Path | None = None,
) -> ActivityReport:
    now = now or _now_naive_utc()
    start, end = _window_bounds(window, now)
    base = Path(logs_dir) if logs_dir else settings.logs_dir

    # Briefs in window.
    rows = _iter_archive_lines(base)
    in_window = [r for r in rows if start <= _parse_iso(r.get("created_at", "")) <= end]
    by_kind = Counter(r.get("kind", "?") for r in in_window)

    # Refs.
    all_refs = reference_lib._load_index()
    winners = [r for r in all_refs if "winner" in r.get("tags", [])]
    refs_added_in_window = [
        r for r in all_refs
        if start <= _parse_iso(r.get("added_at", "")) <= end
    ]
    tag_counter: Counter[str] = Counter()
    for r in all_refs:
        for t in r.get("tags", []):
            tag_counter[t] += 1
    top_tags = tag_counter.most_common(8)

    # Codex.
    codex_text = style_codex.read()
    sections = _count_codex_sections(codex_text)

    # Topics.
    topic_stats = topics.stats()

    # Posts.
    all_posts = export_mod.list_recent(n=1000)
    posts_in_window = [
        p for p in all_posts
        if start <= _parse_iso(p.get("created_at", "")) <= end
    ]

    return ActivityReport(
        window=window,
        started_at=start.isoformat() + "Z",
        ended_at=end.isoformat() + "Z",
        briefs_by_kind=dict(by_kind),
        briefs_total=sum(by_kind.values()),
        refs_total=len(all_refs),
        refs_winners=len(winners),
        refs_added_in_window=len(refs_added_in_window),
        codex_sections=sections,
        topics_stats=topic_stats,
        posts_in_window=len(posts_in_window),
        posts_total=len(all_posts),
        top_tags=top_tags,
    )
