"""Style consistency check — how well does this prompt align with my codex?

Given a prompt, scan the codex's Core Patterns + Compounded Patterns
sections for specific named tokens (lens, film, lighting, etc.). Score
the prompt by how many of those tokens it hits.

Use case: before pasting a new brief's prompt into Grok, check if it
inherited the patterns the project has proven work. A 30% alignment
score probably means the prompt forgot the project's craft DNA.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import codex_audit, style_codex


@dataclass
class ConsistencyReport:
    prompt: str
    score: int                  # 0-100
    matched: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    core_patterns_found: int = 0
    core_patterns_total: int = 0

    def as_text(self) -> str:
        lines = [
            f"=== style consistency — {self.score}/100 ===",
            f"  core patterns hit: {self.core_patterns_found}/{self.core_patterns_total}",
        ]
        if self.matched:
            lines.append("  matched tokens:")
            for m in self.matched[:10]:
                lines.append(f"    + {m}")
        if self.missed:
            lines.append("  missed (codex says these should be here):")
            for m in self.missed[:10]:
                lines.append(f"    - {m}")
        return "\n".join(lines)


# Regex that pulls named craft tokens out of a codex entry line like:
# "lens: 35mm f/1.4 (dominant, 6/10 refs)"
# "lighting: hard window light (×5)"
CODEX_TOKEN_RE = re.compile(r"([a-z_]+):\s*([^(]+?)(?:\s*[\(×]|\s*$)", re.IGNORECASE)


def _extract_codex_tokens() -> list[str]:
    """Pull named tokens from Core Patterns + Visual DNA + Compounded Patterns."""
    text = style_codex.read()
    if not text:
        return []
    sections = codex_audit._parse_sections(text)
    relevant = {"Core Patterns", "Visual DNA", "Compounded Patterns"}
    tokens: list[str] = []
    for name, entries in sections:
        if name not in relevant:
            continue
        for entry in entries:
            for m in CODEX_TOKEN_RE.finditer(entry):
                value = m.group(2).strip()
                if value and len(value) >= 3:
                    tokens.append(value.lower())
    return tokens


def check(prompt: str) -> ConsistencyReport:
    prompt_lower = prompt.lower()
    tokens = _extract_codex_tokens()
    if not tokens:
        return ConsistencyReport(
            prompt=prompt, score=0,
            core_patterns_total=0,
            core_patterns_found=0,
            missed=[], matched=[],
        )

    matched: list[str] = []
    missed: list[str] = []
    for tok in tokens:
        if tok in prompt_lower:
            matched.append(tok)
        else:
            missed.append(tok)

    total = len(tokens)
    found = len(matched)
    # Cap at 100; rarely goes above since tokens is small. Use integer
    # percentage rounded.
    score = int(round(100 * found / total)) if total else 0

    return ConsistencyReport(
        prompt=prompt,
        score=score,
        matched=matched,
        missed=missed,
        core_patterns_found=found,
        core_patterns_total=total,
    )
