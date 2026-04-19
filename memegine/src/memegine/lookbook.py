"""Lookbook — Markdown summary of top winners for human review.

When the operator has 20-100 winners, scrolling the codex becomes
noisy. This module produces a single Markdown document that groups
winners by tag/format, shows prompt + notes for each, and ends with a
pattern summary.

Use: `memegine lookbook > lookbook-2026-04-19.md` and open in any
Markdown viewer. Ideal for end-of-week review, for shared context with
editors, or for archiving the project's current taste state.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import reference_lib
from .corpus_distill import FIELDS


def generate_markdown(*, winners_only: bool = True, max_entries: int = 100) -> str:
    refs = reference_lib._load_index()
    if winners_only:
        refs = [r for r in refs if "winner" in r.get("tags", [])]
    refs.sort(key=lambda r: r.get("added_at", ""), reverse=True)
    refs = refs[:max_entries]

    if not refs:
        return "# Lookbook\n\nNo refs yet."

    # Group by most-prominent non-"winner" tag.
    def _group_tag(r: dict) -> str:
        tags = [t for t in r.get("tags", []) if t != "winner"]
        return tags[0] if tags else "untagged"

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in refs:
        groups[_group_tag(r)].append(r)

    lines: list[str] = [
        "# Lookbook",
        "",
        f"_{len(refs)} {'winners' if winners_only else 'refs'} across "
        f"{len(groups)} tag-groups_",
        "",
    ]

    for group_name in sorted(groups):
        entries = groups[group_name]
        lines.append(f"## {group_name}  _({len(entries)})_")
        lines.append("")
        for r in entries:
            date = r.get("added_at", "")[:10]
            lines.append(f"### {r.get('id', '?')}  ·  {date}")
            lines.append("")
            if r.get("prompt"):
                lines.append("**Prompt:**")
                lines.append("")
                lines.append(f"> {r['prompt']}")
                lines.append("")
            if r.get("notes"):
                lines.append(f"**Notes:** {r['notes']}")
                lines.append("")
            patterns = r.get("extracted_patterns")
            if patterns:
                parts = []
                for f in FIELDS:
                    v = patterns.get(f, "")
                    if isinstance(v, str) and v.strip():
                        parts.append(f"`{f}`: {v}")
                if parts:
                    lines.append("**Craft tokens:**")
                    lines.append("")
                    for p in parts:
                        lines.append(f"- {p}")
                    lines.append("")
            tags_left = [t for t in r.get("tags", []) if t != group_name and t != "winner"]
            if tags_left:
                lines.append(f"_tags:_ `{', '.join(tags_left)}`")
                lines.append("")
            lines.append("---")
            lines.append("")

    # Summary footer: aggregate craft tokens across everything.
    from collections import Counter
    ctr: dict[str, Counter] = {f: Counter() for f in FIELDS}
    for r in refs:
        patterns = r.get("extracted_patterns") or {}
        if not isinstance(patterns, dict):
            continue
        for f in FIELDS:
            v = patterns.get(f, "")
            if isinstance(v, str) and v.strip() and v.lower() not in ("none", "n/a"):
                ctr[f][v.lower()] += 1

    lines.append("## Summary — top craft tokens")
    lines.append("")
    for f in FIELDS:
        top = ctr[f].most_common(5)
        if top:
            joined = ", ".join(f"{v} ({c})" for v, c in top)
            lines.append(f"- **{f}**: {joined}")
    lines.append("")

    return "\n".join(lines)


def write(destination: Path | None = None, **kwargs) -> Path:
    """Write the generated lookbook to `destination` (or a default path)."""
    from .config import settings
    if destination is None:
        import datetime as dt
        stamp = dt.date.today().isoformat()
        destination = settings.data_dir / "lookbooks" / f"lookbook-{stamp}.md"
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(generate_markdown(**kwargs), encoding="utf-8")
    return destination
