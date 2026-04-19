"""Auto-codex — extract compound-able patterns from winning prompts.

When the operator marks a reference as a winner (either via `refs add
--winner` or via the Telegram /winner flow), this module pulls out the
craft tokens that made it land — named lens, film stock, lighting, time of
day, composition — and appends them to the style codex so future briefs
inherit them without manual copy-paste.

The goal is compounding: week 10 briefs should be sharper than week 1
because every winner mined its own patterns.

No LLM needed. Pattern extraction is regex + keyword match over the same
hint tables the linter uses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import linter, style_codex


@dataclass
class ExtractedPatterns:
    lens: list[str] = field(default_factory=list)
    film: list[str] = field(default_factory=list)
    lighting: list[str] = field(default_factory=list)
    time_of_day: list[str] = field(default_factory=list)
    composition: list[str] = field(default_factory=list)
    camera_move: list[str] = field(default_factory=list)
    wardrobe: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [self.lens, self.film, self.lighting, self.time_of_day,
             self.composition, self.camera_move, self.wardrobe]
        )

    def as_codex_line(self) -> str:
        parts = []
        if self.lens:
            parts.append("lens=" + "/".join(self.lens))
        if self.film:
            parts.append("film=" + "/".join(self.film))
        if self.lighting:
            parts.append("lighting=" + "/".join(self.lighting))
        if self.time_of_day:
            parts.append("time=" + "/".join(self.time_of_day))
        if self.composition:
            parts.append("composition=" + "/".join(self.composition))
        if self.camera_move:
            parts.append("move=" + "/".join(self.camera_move))
        if self.wardrobe:
            parts.append("wardrobe=" + "/".join(self.wardrobe))
        return ", ".join(parts)


# A curated set of explicit lens patterns (focal + aperture) — regex catches
# things like "35mm f/1.4" or "85mm f/1.2 GM" or "28mm f/1.7".
LENS_RE = re.compile(
    r"\b(\d{1,3})\s*mm(?:\s*f\s*/?\s*\d+(?:\.\d+)?)?",
    re.IGNORECASE,
)

CAMERA_MOVE_TOKENS = (
    "push-in", "push in", "pull-out", "pull out", "dolly", "rack focus",
    "orbit", "lockoff", "lock-off", "ken burns", "whip pan", "tilt",
    "crane", "truck", "handheld", "steadicam", "slow pan",
)

# Lighting tokens: use the same list the linter uses, so patterns we find
# are consistent with what the linter considers "named".
LIGHTING_TOKENS = linter.LIGHTING_HINTS
FILM_TOKENS = linter.FILM_STOCK_HINTS
TIME_TOKENS = linter.TIME_OR_CONDITION_HINTS
COMPOSITION_TOKENS = linter.COMPOSITION_HINTS

WARDROBE_TOKENS = (
    "hoodie", "leather jacket", "trench", "button-up", "suit", "tie",
    "dress shirt", "overcoat", "puffer", "windbreaker", "scarf",
    "cap", "baseball cap", "sunglasses", "glasses", "watch",
)


def _find_all(text: str, tokens) -> list[str]:
    low = text.lower()
    out = []
    for t in tokens:
        if t in low and t not in out:
            out.append(t)
    return out


def extract(prompt: str) -> ExtractedPatterns:
    """Pull craft tokens from a prompt string."""
    lens = [m.group(0).strip().lower() for m in LENS_RE.finditer(prompt)]
    # de-dupe while preserving order
    lens = list(dict.fromkeys(lens))

    return ExtractedPatterns(
        lens=lens,
        film=_find_all(prompt, FILM_TOKENS),
        lighting=_find_all(prompt, LIGHTING_TOKENS),
        time_of_day=_find_all(prompt, TIME_TOKENS),
        composition=_find_all(prompt, COMPOSITION_TOKENS),
        camera_move=_find_all(prompt, CAMERA_MOVE_TOKENS),
        wardrobe=_find_all(prompt, WARDROBE_TOKENS),
    )


def record_winner(
    prompt: str,
    why: str,
    *,
    tags: list[str] | None = None,
) -> ExtractedPatterns:
    """Record a winner to the codex: appends the raw winner line AND a
    machine-extracted pattern line under the 'Compounded Patterns' section.

    Returns the extracted patterns so the caller can log/display them.
    """
    tag_str = f" [{', '.join(tags)}]" if tags else ""
    style_codex.log_winner(prompt, why + tag_str)

    patterns = extract(prompt)
    if not patterns.is_empty():
        style_codex.append_entry(
            "Compounded Patterns",
            patterns.as_codex_line(),
        )
    return patterns


def distill(
    prompts: list[str],
    *,
    min_frequency: int = 2,
) -> dict[str, list[tuple[str, int]]]:
    """Given a set of past winning prompts, return the token frequencies per
    category. Useful for periodic 'weekly distill' runs that find which
    lenses/films/lighting setups keep working.
    """
    cat_counts: dict[str, dict[str, int]] = {
        "lens": {},
        "film": {},
        "lighting": {},
        "time_of_day": {},
        "composition": {},
        "camera_move": {},
        "wardrobe": {},
    }
    for p in prompts:
        pat = extract(p)
        for cat, vals in (
            ("lens", pat.lens),
            ("film", pat.film),
            ("lighting", pat.lighting),
            ("time_of_day", pat.time_of_day),
            ("composition", pat.composition),
            ("camera_move", pat.camera_move),
            ("wardrobe", pat.wardrobe),
        ):
            for v in vals:
                cat_counts[cat][v] = cat_counts[cat].get(v, 0) + 1

    # Filter by min_frequency and sort desc.
    out: dict[str, list[tuple[str, int]]] = {}
    for cat, counts in cat_counts.items():
        kept = [(v, c) for v, c in counts.items() if c >= min_frequency]
        kept.sort(key=lambda x: (-x[1], x[0]))
        out[cat] = kept
    return out


def distill_to_codex(prompts: list[str], *, min_frequency: int = 2) -> dict[str, list[tuple[str, int]]]:
    """Run distill and write its output to the codex under 'Weekly Distill'."""
    dist = distill(prompts, min_frequency=min_frequency)
    body_parts = []
    for cat, kept in dist.items():
        if not kept:
            continue
        body_parts.append(
            f"{cat}: " + ", ".join(f"{v}×{c}" for v, c in kept[:5])
        )
    if body_parts:
        style_codex.append_entry("Weekly Distill", "; ".join(body_parts))
    return dist


def graduate_patterns(
    prompts: list[str],
    *,
    promotion_threshold: int = 5,
) -> dict[str, list[tuple[str, int]]]:
    """Promote patterns that appear N+ times to the 'Core Patterns' section.

    This is the compounding endgame: once a specific lens / film / lighting
    setup has been used and worked across 5+ winners, it's canon. It
    belongs at the top of every future brief — not buried in a weekly
    distill.

    Writes exactly one line per category (the cleaner the codex stays, the
    better the next brief). Returns the promoted entries so a caller can
    report what graduated this run.
    """
    dist = distill(prompts, min_frequency=promotion_threshold)
    promoted: dict[str, list[tuple[str, int]]] = {
        k: v for k, v in dist.items() if v
    }
    if not promoted:
        return {}

    lines: list[str] = []
    for cat, kept in promoted.items():
        top_list = ", ".join(f"{v}" for v, _ in kept[:5])
        lines.append(f"{cat}: {top_list}")
    style_codex.append_entry(
        "Core Patterns",
        "promoted at threshold=" + str(promotion_threshold) + " — "
        + "; ".join(lines),
    )
    return promoted
