"""Next action — one-screen "what should I make?" dashboard.

Looks across the entire memegine state (queue, refs, perf, codex) and
produces a ranked list of concrete next moves for the operator. Not a
decision-maker; a recommender that makes the state legible in five
seconds.

Output is a `Dashboard` struct the CLI prints and the bot sends as a
single message.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import (
    performance,
    reference_lib,
    session as session_mod,
    stats as stats_mod,
    style_codex,
    topics,
)
from ._time import now_iso as _now_iso


@dataclass
class Dashboard:
    now: str
    current_session: str | None = None
    queue_count: int = 0
    top_topics: list[dict] = field(default_factory=list)
    last_winner: dict | None = None
    top_format: tuple[str, int, float] | None = None
    recent_codex_sections: dict[str, int] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [f"=== memegine — next moves ({self.now[:19]} UTC) ==="]
        if self.current_session:
            lines.append(f"  session in progress: {self.current_session}")
        else:
            lines.append("  no session open — run `memegine session start` to mark this block")
        lines.append("")
        lines.append(f"topic queue: {self.queue_count} queued")
        for t in self.top_topics[:3]:
            lines.append(f"  p={t.get('priority', 3)}  {t.get('text', '')[:70]}")
        lines.append("")
        if self.last_winner:
            lines.append(
                f"last winner: {self.last_winner.get('added_at', '')[:10]}  "
                f"{(self.last_winner.get('notes') or self.last_winner.get('prompt', ''))[:60]}"
            )
        else:
            lines.append("last winner: none yet — tag a ref with --winner to start compounding")
        lines.append("")
        if self.top_format:
            slug, n, avg = self.top_format
            lines.append(f"top-performing format: {slug}  n={n}  avg_score={avg:.1f}")
        else:
            lines.append("no performance data yet — log engagement with `memegine perf log`")
        lines.append("")
        lines.append("codex sections:")
        for section, count in list(self.recent_codex_sections.items())[:8]:
            lines.append(f"  {section:<28} {count} entries")
        lines.append("")
        lines.append("suggested moves:")
        for i, r in enumerate(self.recommendations, 1):
            lines.append(f"  {i}. {r}")
        return "\n".join(lines)


def compute() -> Dashboard:
    now_iso = _now_iso()

    # Session.
    sess = session_mod.current()
    current_session_str = None
    if sess:
        name = sess.get("name") or sess["session_id"][:8]
        current_session_str = f"{name} (started {sess.get('at', '')[:19]})"

    # Topics.
    queued = topics.list_queued()
    queue_count = len(queued)
    top_topics = queued[:5]

    # Last winner.
    refs = reference_lib._load_index()
    winners = sorted(
        [r for r in refs if "winner" in r.get("tags", [])],
        key=lambda r: r.get("added_at", ""), reverse=True,
    )
    last_winner = winners[0] if winners else None

    # Top format by performance.
    by_fmt = performance.by_format()
    top_format = by_fmt[0] if by_fmt else None

    # Codex sections.
    codex_text = style_codex.read()
    sections = stats_mod._count_codex_sections(codex_text)

    # Recommendations — generated from the state.
    recs: list[str] = []
    if queue_count == 0:
        recs.append("queue is empty -- drop 3 topics with `memegine topics add` before anything else")
    elif queue_count >= 3:
        topic = queued[0]
        recs.append(
            f"pop the highest-priority topic and pipeline it: "
            f"`memegine from-topic {topic['id']}`"
        )
    if last_winner and last_winner.get("prompt"):
        recs.append(
            "mine the last winner: `memegine variants-last -n 6` — 6 single-axis tweaks from your strongest prompt"
        )
    if top_format:
        recs.append(
            f"your top format is `{top_format[0]}` — bias today's pieces that way if intent allows"
        )
    if not sections.get("Core Patterns"):
        brief_count = sum(stats_mod._count_codex_sections(codex_text).values())
        if brief_count >= 10:
            recs.append(
                "run `memegine codex graduate --threshold 5` — enough history to promote patterns"
            )
    if not current_session_str:
        recs.append(
            "mark the start of this working block: `memegine session start \"<name>\"`"
        )
    # Always include an idea-grader prompt.
    recs.append(
        "before briefing any intent today, run `memegine grade-idea \"<intent>\"` — kill vague ones fast"
    )

    return Dashboard(
        now=now_iso,
        current_session=current_session_str,
        queue_count=queue_count,
        top_topics=top_topics,
        last_winner=last_winner,
        top_format=top_format,
        recent_codex_sections=sections,
        recommendations=recs,
    )
