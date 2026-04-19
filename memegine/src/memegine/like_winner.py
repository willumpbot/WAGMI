"""Like-winner — clone your last winner's craft for a new subject.

This is the "do it again, a little different" command. The operator
says "a CEO at 3am" and memegine stitches together:
- the LENS, FILM, LIGHTING, TIME_OF_DAY, COMPOSITION tokens from the
  most recent ref tagged `winner`
- the new intent as the subject / action
- any existing linter fallbacks (negative terms, etc.)

Output: a complete prompt ready to paste into Grok, plus the deep_linter
score.

This is the most practical form of compounding — week-10 pieces inherit
the craft the operator has already proven out instead of rebuilding
every brief from scratch.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import auto_codex, deep_linter, reference_lib


@dataclass
class LikeWinnerResult:
    new_intent: str
    source_ref_id: str | None
    source_prompt: str
    patterns: list[str] = field(default_factory=list)
    prompt: str = ""
    score: int = 0
    grade: str = ""
    note: str = ""

    def as_text(self) -> str:
        lines = [
            f"source ref: {self.source_ref_id or '-'}",
            f"patterns inherited: {', '.join(self.patterns) or '-'}",
            f"new intent: {self.new_intent}",
            f"score: {self.score}/100  grade {self.grade}",
        ]
        if self.note:
            lines.append(f"note: {self.note}")
        lines.append("")
        lines.append("=== prompt ===")
        lines.append(self.prompt)
        return "\n".join(lines)


def _find_latest_winner_with_prompt() -> dict | None:
    refs = reference_lib._load_index()
    winners = sorted(
        [r for r in refs if "winner" in r.get("tags", []) and r.get("prompt", "").strip()],
        key=lambda r: r.get("added_at", ""), reverse=True,
    )
    return winners[0] if winners else None


def build(new_intent: str) -> LikeWinnerResult:
    """Produce a new prompt that inherits the craft of the last winner."""
    if not new_intent.strip():
        raise ValueError("intent is required")

    winner = _find_latest_winner_with_prompt()
    if winner is None:
        raise ValueError(
            "no winner with a saved prompt found — "
            "tag a ref with `--winner --prompt \"...\"` first"
        )
    source_prompt = winner["prompt"]
    patterns = auto_codex.extract(source_prompt)

    parts: list[str] = [new_intent.strip().rstrip(" .,")]

    # Inherit in a priority order: lens, film, lighting, time, composition,
    # camera_move. Wardrobe is omitted — it's subject-specific and usually
    # doesn't transfer cleanly to a new intent.
    for vals in (
        patterns.lens, patterns.film, patterns.lighting,
        patterns.time_of_day, patterns.composition, patterns.camera_move,
    ):
        for v in vals:
            parts.append(v)

    # Always add photoreal negatives at the end.
    negatives = "no extra fingers, no warped text, no logo watermarks, no lens flares unless specified"

    prompt = ", ".join(parts) + ", " + negatives

    score = deep_linter.score(prompt)
    grade = deep_linter.grade(score.score)

    return LikeWinnerResult(
        new_intent=new_intent.strip(),
        source_ref_id=winner.get("id"),
        source_prompt=source_prompt,
        patterns=[
            p for vs in (
                patterns.lens, patterns.film, patterns.lighting,
                patterns.time_of_day, patterns.composition, patterns.camera_move,
            ) for p in vs
        ],
        prompt=prompt,
        score=score.score,
        grade=grade,
        note="",
    )
