"""Performance tracker — record actual X engagement for posts.

This module closes the real feedback loop. The operator tells memegine
"my last post got 800 likes and 50 RTs" and memegine records it along
with the post's format, bundle id, codex patterns, and time of day.

Over time, this answers:
- Which formats actually land? (reaction_shot_meme crushes photoreal
  portraits in my timeline)
- Which named patterns land? (35mm f/1.4 + Cinestill 800T consistently
  outperforms 50mm + Portra 400)
- What's the best posting time? (3am pieces always do better than noon)
- Which topics converted best? (price action pieces beat lore pieces)

Storage: append-only JSONL at `data/performance/posts.jsonl`. One entry
per post. The same post can be updated multiple times (24h engagement
is different from 7d). Updates supersede; latest wins per post_id.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Iterable

from ._time import now_iso as _now_iso
from .config import settings


@dataclass
class PostPerformance:
    id: str
    recorded_at: str
    post_bundle_id: str | None = None   # points to export.PostBundle.id
    post_url: str = ""                  # optional X status URL
    format_slug: str | None = None
    patterns: list[str] = field(default_factory=list)   # extracted tokens that appear in the prompt
    posted_at: str = ""                 # when the post actually went live (operator-supplied)
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    quotes: int = 0
    impressions: int = 0
    bookmarks: int = 0
    window: str = "24h"                 # "1h" | "24h" | "7d" | "30d"
    notes: str = ""


def _store_path() -> Path:
    return settings.data_dir / "performance" / "posts.jsonl"


def _all_entries() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def log(
    *,
    post_bundle_id: str | None = None,
    post_url: str = "",
    format_slug: str | None = None,
    patterns: list[str] | None = None,
    posted_at: str = "",
    likes: int = 0,
    reposts: int = 0,
    replies: int = 0,
    quotes: int = 0,
    impressions: int = 0,
    bookmarks: int = 0,
    window: str = "24h",
    notes: str = "",
) -> PostPerformance:
    """Append a new performance entry. Does NOT dedupe — repeated calls
    for the same post_bundle_id with different windows are both kept
    (e.g., 24h entry + 7d entry).
    """
    entry = PostPerformance(
        id=uuid.uuid4().hex[:10],
        recorded_at=_now_iso(),
        post_bundle_id=post_bundle_id,
        post_url=post_url,
        format_slug=format_slug,
        patterns=[p.strip() for p in (patterns or []) if p.strip()],
        posted_at=posted_at,
        likes=likes,
        reposts=reposts,
        replies=replies,
        quotes=quotes,
        impressions=impressions,
        bookmarks=bookmarks,
        window=window,
        notes=notes,
    )
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    return entry


def _score_entry(entry: dict) -> float:
    """Engagement score heuristic. Weights reflect X's ranking priors —
    replies and reposts count more than likes because they're higher-intent.
    Missing fields score 0.
    """
    return (
        float(entry.get("likes", 0))
        + 3.0 * float(entry.get("reposts", 0))
        + 2.0 * float(entry.get("replies", 0))
        + 2.0 * float(entry.get("quotes", 0))
        + 1.5 * float(entry.get("bookmarks", 0))
    )


def _latest_per_bundle(entries: list[dict]) -> list[dict]:
    """If multiple entries exist for the same post_bundle_id, keep only the
    most recent one. Entries without a bundle id are kept as-is.
    """
    out: dict[str, dict] = {}
    unanchored: list[dict] = []
    for e in entries:
        bid = e.get("post_bundle_id")
        if not bid:
            unanchored.append(e)
            continue
        existing = out.get(bid)
        if existing is None or e.get("recorded_at", "") > existing.get("recorded_at", ""):
            out[bid] = e
    return list(out.values()) + unanchored


def by_format(entries: Iterable[dict] | None = None) -> list[tuple[str, int, float]]:
    """Return [(format_slug, n_posts, avg_score), ...] sorted by avg_score desc."""
    entries = list(entries) if entries is not None else _all_entries()
    entries = _latest_per_bundle(entries)
    buckets: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        slug = e.get("format_slug") or "unknown"
        buckets[slug].append(_score_entry(e))
    out: list[tuple[str, int, float]] = []
    for slug, scores in buckets.items():
        out.append((slug, len(scores), mean(scores) if scores else 0.0))
    out.sort(key=lambda x: (-x[2], -x[1]))
    return out


def by_pattern(entries: Iterable[dict] | None = None) -> list[tuple[str, int, float]]:
    """Return [(pattern_token, n_posts, avg_score), ...] sorted by avg_score desc."""
    entries = list(entries) if entries is not None else _all_entries()
    entries = _latest_per_bundle(entries)
    buckets: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        for p in e.get("patterns", []):
            buckets[p].append(_score_entry(e))
    out: list[tuple[str, int, float]] = []
    for pat, scores in buckets.items():
        out.append((pat, len(scores), mean(scores) if scores else 0.0))
    out.sort(key=lambda x: (-x[2], -x[1]))
    return out


def by_hour(entries: Iterable[dict] | None = None) -> list[tuple[int, int, float]]:
    """Return [(hour_of_day_utc, n_posts, avg_score), ...] sorted by hour."""
    entries = list(entries) if entries is not None else _all_entries()
    entries = _latest_per_bundle(entries)
    buckets: dict[int, list[float]] = defaultdict(list)
    for e in entries:
        posted = e.get("posted_at") or e.get("recorded_at")
        if not posted:
            continue
        try:
            hh = dt.datetime.fromisoformat(posted.replace("Z", "+00:00")).hour
        except ValueError:
            continue
        buckets[hh].append(_score_entry(e))
    out: list[tuple[int, int, float]] = []
    for hh, scores in buckets.items():
        out.append((hh, len(scores), mean(scores) if scores else 0.0))
    out.sort()
    return out


def top_n(n: int = 10) -> list[dict]:
    """Return the N highest-scoring entries (most engagement)."""
    entries = _latest_per_bundle(_all_entries())
    entries.sort(key=_score_entry, reverse=True)
    return entries[:n]


def summary_text(entries: Iterable[dict] | None = None) -> str:
    by_fmt = by_format(entries)
    by_pat = by_pattern(entries)
    lines = ["=== performance summary ===", "", "by format (avg engagement score):"]
    for slug, n, avg in by_fmt[:10]:
        lines.append(f"  {slug:<28} n={n:<3}  avg={avg:.1f}")
    lines += ["", "by pattern (avg engagement score):"]
    for pat, n, avg in by_pat[:10]:
        lines.append(f"  {pat:<28} n={n:<3}  avg={avg:.1f}")
    by_hr = by_hour(entries)
    if by_hr:
        lines += ["", "by hour (UTC):"]
        for hh, n, avg in by_hr:
            lines.append(f"  {hh:02d}:00  n={n:<3}  avg={avg:.1f}")
    return "\n".join(lines)
