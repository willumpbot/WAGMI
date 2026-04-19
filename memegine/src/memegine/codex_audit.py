"""Codex audit — keep the style codex from rotting.

Codex grows organically as the operator logs winners / flops / voice
notes. Over months it accumulates noise:
- duplicate bullets (operator logged the same winner twice)
- contradictions (one bullet says 'use Portra 400', another 'avoid Portra')
- sections that got heavy (>20 entries) — candidates for compaction via
  distill / graduate

This module reads the codex and reports on those health signals. It
does NOT auto-edit the codex — the operator is the final judge of which
entries stay and which consolidate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import style_codex


@dataclass
class SectionHealth:
    name: str
    entries: int
    duplicates: list[tuple[str, int]] = field(default_factory=list)
    avoid_hits: int = 0
    use_hits: int = 0


@dataclass
class CodexAudit:
    total_entries: int = 0
    sections: list[SectionHealth] = field(default_factory=list)
    global_duplicates: list[tuple[str, int]] = field(default_factory=list)
    contradiction_pairs: list[tuple[str, str]] = field(default_factory=list)
    heavy_sections: list[str] = field(default_factory=list)   # sections with >20 entries

    def as_text(self) -> str:
        lines = [f"=== codex audit — {self.total_entries} entries total ==="]
        for s in self.sections:
            lines.append(f"  {s.name}: {s.entries} entries")
            for body, count in s.duplicates:
                lines.append(f"    dup x{count}: {body[:80]}")
        if self.global_duplicates:
            lines.append("")
            lines.append("cross-section duplicates:")
            for body, count in self.global_duplicates:
                lines.append(f"  x{count}: {body[:80]}")
        if self.contradiction_pairs:
            lines.append("")
            lines.append("potential contradictions:")
            for a, b in self.contradiction_pairs:
                lines.append(f"  {a[:60]}  <->  {b[:60]}")
        if self.heavy_sections:
            lines.append("")
            lines.append(
                "heavy sections (candidates for distill/graduate): "
                + ", ".join(self.heavy_sections)
            )
        if not self.global_duplicates and not self.contradiction_pairs and not self.heavy_sections:
            lines.append("")
            lines.append("codex is clean")
        return "\n".join(lines)


ENTRY_RE = re.compile(r"^-\s*(?:\(\d{4}-\d{2}-\d{2}\)\s*)?(.+)$")


def _parse_sections(text: str) -> list[tuple[str, list[str]]]:
    """Return [(section_name, [entry_body, ...]), ...]."""
    sections: list[tuple[str, list[str]]] = []
    current_name = ""
    current_entries: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_name or current_entries:
                sections.append((current_name, current_entries))
            current_name = line[3:].strip()
            current_entries = []
            continue
        m = ENTRY_RE.match(line)
        if m:
            body = m.group(1).strip()
            if body and body.lower() not in ("(empty)", "(none yet)"):
                current_entries.append(body)
    if current_name or current_entries:
        sections.append((current_name, current_entries))
    return sections


def _normalize(body: str) -> str:
    # Strip surrounding quotes and lowercase for comparison.
    b = body.strip().strip('"').strip("'")
    return b.lower()


def _detect_duplicates(entries: list[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    seen_raw: dict[str, str] = {}
    for e in entries:
        norm = _normalize(e)
        counts[norm] = counts.get(norm, 0) + 1
        seen_raw.setdefault(norm, e)
    return [(seen_raw[k], v) for k, v in counts.items() if v >= 2]


def _detect_contradictions(entries: list[str]) -> list[tuple[str, str]]:
    """Heuristic: find pairs where one line 'uses' some token X and another
    'avoids' X. Rough but catches the common case of operator logging
    conflicting guidance months apart.

    Approach: for each entry, collect the set of non-trivial tokens. Tag
    each entry as 'positive' if it contains 'use|prefer|always|try' and
    'negative' if it contains 'avoid|skip|never|don\\'t|stop'. Report pairs
    of positive/negative entries that share >= 2 non-trivial tokens.
    """
    POSITIVE_RE = re.compile(r"\b(use|prefer|always|try)\b", re.IGNORECASE)
    NEGATIVE_RE = re.compile(r"\b(avoid|skip|never|don'?t|stop)\b", re.IGNORECASE)

    STOPWORDS = {
        "the", "a", "an", "and", "or", "of", "in", "on", "to", "for", "with",
        "use", "avoid", "always", "never", "prefer", "skip", "try", "stop",
        "don", "dont", "scenes", "tones", "shot", "shots", "pieces",
    }

    def _tokens(text: str) -> set[str]:
        raw = re.findall(r"[a-z0-9]+", text.lower())
        return {t for t in raw if t not in STOPWORDS and len(t) >= 3}

    positives: list[tuple[str, set[str]]] = []
    negatives: list[tuple[str, set[str]]] = []
    for e in entries:
        toks = _tokens(e)
        if POSITIVE_RE.search(e):
            positives.append((e, toks))
        if NEGATIVE_RE.search(e):
            negatives.append((e, toks))

    pairs: list[tuple[str, str]] = []
    for pos_line, pos_toks in positives:
        for neg_line, neg_toks in negatives:
            if pos_line == neg_line:
                continue
            shared = pos_toks & neg_toks
            if len(shared) >= 2:
                pairs.append((pos_line, neg_line))
    return pairs


def audit(text: str | None = None) -> CodexAudit:
    """Run the audit over the current codex (or a provided text)."""
    text = text if text is not None else style_codex.read()
    sections_parsed = _parse_sections(text)

    sections: list[SectionHealth] = []
    all_entries: list[str] = []
    heavy: list[str] = []
    for name, entries in sections_parsed:
        all_entries.extend(entries)
        dups = _detect_duplicates(entries)
        avoid_hits = sum(1 for e in entries if re.search(r"\bavoid\b|\bdon'?t\b|\bnever\b|\bskip\b", e, re.IGNORECASE))
        use_hits = sum(1 for e in entries if re.search(r"\buse\b|\bprefer\b|\balways\b", e, re.IGNORECASE))
        sections.append(SectionHealth(
            name=name, entries=len(entries),
            duplicates=dups, avoid_hits=avoid_hits, use_hits=use_hits,
        ))
        if len(entries) > 20:
            heavy.append(name)

    global_dups = _detect_duplicates(all_entries)
    contradictions = _detect_contradictions(all_entries)

    return CodexAudit(
        total_entries=len(all_entries),
        sections=sections,
        global_duplicates=global_dups,
        contradiction_pairs=contradictions,
        heavy_sections=heavy,
    )
