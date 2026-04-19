"""Morning briefer — Claude-powered 3-intent suggester.

Higher-intelligence cousin of `next_action`. Where `next_action` uses
heuristics to surface queue/winner/perf state, this module actually
asks Claude to synthesize the state into 3 concrete, ready-to-brief
intents for the day, informed by the codex + recent perf + last
winners.

Needs ANTHROPIC_API_KEY. Typical cost: ~$0.003 per call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import performance, reference_lib, style_codex, topics


BRIEFER_SYSTEM = """You are the morning brief writer for a single
operator running a crypto-native photo/video project on X.

Given the current state of their memegine environment (style codex,
topic queue, recent winners, top-performing formats), produce 3 CONCRETE
INTENTS the operator should seriously consider shooting today.

Each intent must:
- Be specific: name the subject, the emotion, the setting. No
  abstractions ("something cool", "vibes", "the market").
- Feel like it belongs to THIS project (match the voice in the codex —
  earned cynicism, tired-coded smart, specific nouns).
- Lean on what has already worked (top formats, recurring patterns in
  Core Patterns / Compounded Patterns).
- Be actionable today — no "make a brand campaign" scale, just one
  piece.

One of the three should take a QUEUED topic and sharpen it. One should
be a variant on a recent winner. One should be net-new (something the
archive hasn't seen, but that fits the codex).

Return ONLY JSON:

{
  "intents": [
    {
      "label": "sharpened-from-queue" | "winner-variant" | "net-new",
      "intent": "<one sentence, ready to paste into `memegine piece`>",
      "why": "<one sentence, why this is worth the 30 minutes today>",
      "suggested_format": "<format slug from the operator's library>"
    },
    ...3 total
  ],
  "note": "<one sentence editorial overview>"
}
"""


@dataclass
class MorningBrief:
    intents: list[dict] = field(default_factory=list)
    note: str = ""
    cost_hint: str = "~$0.003 via Sonnet"
    error: str = ""

    def as_text(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        lines = ["=== Claude morning brief ==="]
        if self.note:
            lines.append(f"  {self.note}")
            lines.append("")
        for i, intent in enumerate(self.intents, 1):
            label = intent.get("label", "?")
            text = intent.get("intent", "")
            why = intent.get("why", "")
            slug = intent.get("suggested_format", "")
            lines.append(f"{i}. [{label}] {text}")
            if slug:
                lines.append(f"   format: {slug}")
            if why:
                lines.append(f"   why:    {why}")
        lines.append("")
        lines.append(f"(cost: {self.cost_hint})")
        return "\n".join(lines)


def _gather_state(
    *, max_winners: int = 5, max_queue: int = 5, max_perf: int = 5,
) -> dict:
    codex_text = style_codex.read()
    queued = topics.list_queued(limit=max_queue)
    refs = reference_lib._load_index()
    winners = sorted(
        [r for r in refs if "winner" in r.get("tags", [])],
        key=lambda r: r.get("added_at", ""), reverse=True,
    )[:max_winners]
    by_fmt = performance.by_format()[:max_perf]

    return {
        "codex": codex_text,
        "queued_topics": [
            {"id": t.get("id"), "text": t.get("text", ""),
             "priority": t.get("priority", 3),
             "tags": t.get("tags", [])}
            for t in queued
        ],
        "recent_winners": [
            {
                "id": w.get("id"),
                "prompt": w.get("prompt", ""),
                "notes": w.get("notes", ""),
                "tags": w.get("tags", []),
            }
            for w in winners
        ],
        "top_formats": [
            {"slug": slug, "n_posts": n, "avg_score": round(avg, 1)}
            for slug, n, avg in by_fmt
        ],
    }


def generate(*, model: str | None = None) -> MorningBrief:
    from . import executor
    if not executor.api_key_available():
        return MorningBrief(error="ANTHROPIC_API_KEY not set")

    client = executor.get_client()
    state = _gather_state()

    user_msg = (
        "## Current state\n\n"
        f"### Style codex (first 4000 chars)\n{state['codex'][:4000] or '(empty)'}\n\n"
        f"### Queued topics ({len(state['queued_topics'])})\n"
        + json.dumps(state["queued_topics"], ensure_ascii=False, indent=2)
        + "\n\n"
        f"### Recent winners ({len(state['recent_winners'])})\n"
        + json.dumps(state["recent_winners"], ensure_ascii=False, indent=2)
        + "\n\n"
        f"### Top-performing formats (by engagement)\n"
        + json.dumps(state["top_formats"], ensure_ascii=False, indent=2)
        + "\n\n## Task\n"
        "Produce 3 concrete intents per the system rules. JSON only."
    )

    try:
        data = client.complete_json(
            system=BRIEFER_SYSTEM, user=user_msg, model=model,
            max_tokens=1500, temperature=0.7,
        )
    except Exception as exc:
        return MorningBrief(error=f"{type(exc).__name__}: {exc}")

    if not isinstance(data, dict):
        return MorningBrief(error="unexpected response shape")

    return MorningBrief(
        intents=data.get("intents", []) or [],
        note=data.get("note", "") or "",
    )
