"""Weekly report — Claude-powered end-of-week synthesis.

Consumes: last 7 days of journal entries, performance entries,
codex diff (new entries since last week), and recent winners.
Produces a narrative Markdown report covering:
- What got made this week
- What landed (top 3)
- What flopped (bottom 3)
- Pattern observations (which lens / film / mood outperformed)
- Next-week recommendations

Needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

from . import journal, performance, reference_lib, style_codex


REPORT_SYSTEM = """You are the weekly-report writer for a single
operator running a crypto-native photo/video project on X.

Given the week's activity state (journal, performance logs, codex
entries, recent winners), produce a concise narrative Markdown report
with these sections in order:

## This week in pieces
3-4 sentences. What themes dominated? How many pieces shipped?

## Top 3 performers
For each, one line citing engagement + format + what made it land.

## Bottom 3
For each, one line citing engagement + format + a candid guess at why.

## Pattern observations
2-3 observations about lens / film / mood / time-of-day that over- or
under-performed. Cite numbers.

## Recommendations for next week
3 concrete moves (format to lean on, topic theme to try, pattern to
experiment with). Each actionable: the operator should be able to
turn it into a topic or brief without more thinking.

Keep it tight. Zero fluff. Never use "cinematic", "epic", "stunning"
— match the project's tired-coded-smart voice."""


@dataclass
class WeeklyReport:
    markdown: str = ""
    error: str = ""

    def as_text(self) -> str:
        return self.markdown if not self.error else f"ERROR: {self.error}"


def _gather(days: int = 7) -> dict:
    entries = journal.collect(days=days, limit=200)
    perf_entries = performance._latest_per_bundle(performance._all_entries())
    refs = reference_lib._load_index()
    winners = [r for r in refs if "winner" in r.get("tags", [])]
    winners.sort(key=lambda r: r.get("added_at", ""), reverse=True)
    winners = winners[:20]

    return {
        "days": days,
        "journal": [
            {"at": e.at, "kind": e.kind, "summary": e.summary}
            for e in entries
        ],
        "performance": [
            {
                "format": e.get("format_slug"),
                "likes": e.get("likes", 0),
                "reposts": e.get("reposts", 0),
                "replies": e.get("replies", 0),
                "patterns": e.get("patterns", []),
                "posted_at": e.get("posted_at"),
            }
            for e in perf_entries
        ],
        "codex": style_codex.read()[:3000],
        "recent_winners": [
            {
                "id": w.get("id"),
                "notes": w.get("notes", ""),
                "prompt_first_120": (w.get("prompt", "") or "")[:120],
                "tags": w.get("tags", []),
            }
            for w in winners
        ],
    }


def generate(*, days: int = 7, model: str | None = None) -> WeeklyReport:
    from . import executor
    if not executor.api_key_available():
        return WeeklyReport(error="ANTHROPIC_API_KEY not set")

    client = executor.get_client()
    state = _gather(days)
    user_msg = (
        f"## Week snapshot ({days} days)\n\n"
        f"### Journal ({len(state['journal'])} entries)\n"
        + json.dumps(state["journal"][:50], ensure_ascii=False, indent=2)
        + "\n\n"
        f"### Performance ({len(state['performance'])} posts)\n"
        + json.dumps(state["performance"][:30], ensure_ascii=False, indent=2)
        + "\n\n"
        f"### Recent winners ({len(state['recent_winners'])})\n"
        + json.dumps(state["recent_winners"], ensure_ascii=False, indent=2)
        + "\n\n"
        "### Codex head\n\n"
        + state["codex"]
        + "\n\n## Task\nProduce the weekly report per the system rules. "
        "Return raw Markdown (no code fences around the whole thing)."
    )

    try:
        # Use the raw complete() since we want text back, not JSON.
        resp = client.complete(
            system=REPORT_SYSTEM, user=user_msg, model=model,
            max_tokens=2000, temperature=0.5,
        )
    except Exception as exc:
        return WeeklyReport(error=f"{type(exc).__name__}: {exc}")

    text = resp.text.strip()
    # Strip any outer code fences Claude might add.
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("markdown"):
                text = text[8:]
            text = text.strip()
    return WeeklyReport(markdown=text)
