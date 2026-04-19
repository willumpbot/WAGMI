"""Prompt fixer — take a weak prompt and insert fragments to hit missing
craft categories.

This is the auto-formatter the operator wishes they had after pasting a
rough prompt into memegine. It:

1. Scores the prompt with deep_linter
2. For each missing category that has fragments available, injects one
3. Re-scores the improved prompt
4. Returns the before/after + what was added

The operator can accept the improved version or iterate manually. The
fixer is deliberately conservative — it only appends fragment bodies,
never rewrites the operator's original text.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import deep_linter, fragments


# Mapping from craft-score category to fragment-library category and preferred
# fragment names (first match wins). When multiple fragments could work, the
# first on this list is the default insert.
CATEGORY_FRAGMENTS: dict[str, list[tuple[str, str]]] = {
    "lens_or_stock": [("LENS", "35mm_1_4"), ("FILM", "portra_400")],
    "lighting":      [("LIGHTING", "harsh_window"), ("LIGHTING", "practical_neon")],
    "time_or_condition": [("TIME_OF_DAY", "dusk"), ("TIME_OF_DAY", "3am")],
    "composition":   [("COMPOSITION", "thirds_left"), ("COMPOSITION", "centered_medium")],
    "negative_terms": [("NEGATIVE", "photoreal_defaults")],
}


@dataclass
class FixResult:
    original: str
    fixed: str
    inserted: list[str] = field(default_factory=list)       # "LENS.35mm_1_4" tokens inserted
    expanded_bodies: list[str] = field(default_factory=list)  # expanded text
    original_score: int = 0
    fixed_score: int = 0
    improvement: int = 0

    def as_text(self) -> str:
        lines = [
            f"original score: {self.original_score}/100",
            f"fixed score:    {self.fixed_score}/100  (+{self.improvement})",
        ]
        if self.inserted:
            lines.append("inserted fragments:")
            for tok in self.inserted:
                lines.append(f"  {tok}")
        lines.append("")
        lines.append("=== fixed prompt ===")
        lines.append(self.fixed)
        return "\n".join(lines)


def fix(prompt: str, *, kind: str = "image") -> FixResult:
    """Score the prompt, insert fragments for missing categories, re-score."""
    before = deep_linter.score(prompt, kind=kind)
    lib = fragments.load()

    inserted_tokens: list[str] = []
    inserted_bodies: list[str] = []
    for cat, satisfied in before.hits.items():
        if satisfied:
            continue
        candidates = CATEGORY_FRAGMENTS.get(cat, [])
        for frag_cat, frag_name in candidates:
            if lib.get(frag_cat, {}).get(frag_name):
                token = f"{frag_cat}.{frag_name}"
                body = lib[frag_cat][frag_name]
                inserted_tokens.append(token)
                inserted_bodies.append(body)
                break

    # Build the fixed prompt by appending the bodies to the original. Don't
    # rewrite the operator's words — just extend with what was missing.
    if inserted_bodies:
        # Keep a clean separator.
        suffix = ", " + ", ".join(inserted_bodies)
        fixed_prompt = prompt.rstrip(" .,") + suffix
    else:
        fixed_prompt = prompt

    after = deep_linter.score(fixed_prompt, kind=kind)

    return FixResult(
        original=prompt,
        fixed=fixed_prompt,
        inserted=inserted_tokens,
        expanded_bodies=inserted_bodies,
        original_score=before.score,
        fixed_score=after.score,
        improvement=after.score - before.score,
    )
