"""Corpus export — flatten refs + extracted_patterns into CSV.

Lets the operator open the corpus in Excel / Numbers / a pandas
notebook and quickly spot:
- which refs are missing `extracted_patterns` (need reverse)
- which lens / film / lighting values are outliers
- tag-group differences between editors / sub-folders
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import reference_lib
from .corpus_distill import FIELDS


def export(destination: Path) -> int:
    """Write every ref + its extracted_patterns fields to CSV."""
    refs = reference_lib._load_index()
    destination.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "id", "filename", "added_at", "tags", "is_winner", "source",
        "notes", "prompt_first_120",
    ] + list(FIELDS)
    with destination.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in refs:
            tags = r.get("tags", []) or []
            patterns = r.get("extracted_patterns", {}) or {}
            row = [
                r.get("id", ""),
                r.get("filename", ""),
                r.get("added_at", ""),
                "|".join(tags),
                "winner" in tags,
                r.get("source", ""),
                r.get("notes", ""),
                (r.get("prompt", "") or "")[:120],
            ]
            for field_name in FIELDS:
                row.append(patterns.get(field_name, "") if isinstance(patterns, dict) else "")
            writer.writerow(row)
    return len(refs)


def compare_by_tag(
    tag_group_a: str,
    tag_group_b: str,
) -> dict[str, dict]:
    """Return per-field frequency counts for two tag subsets.

    Useful for comparing editors ("editor:alice" vs "editor:bob") or
    sub-genres ("portrait" vs "meme") and seeing which craft tokens
    differ.
    """
    from collections import Counter
    refs = reference_lib._load_index()

    def _collect(tag: str) -> dict[str, Counter]:
        matching = [
            r for r in refs if tag in r.get("tags", [])
            and isinstance(r.get("extracted_patterns"), dict)
        ]
        buckets: dict[str, Counter] = {f: Counter() for f in FIELDS}
        for r in matching:
            for f in FIELDS:
                v = (r.get("extracted_patterns") or {}).get(f, "")
                if isinstance(v, str) and v.strip() and v.lower() not in ("none", "n/a"):
                    buckets[f][v.lower()] += 1
        return buckets

    a = _collect(tag_group_a)
    b = _collect(tag_group_b)
    diff: dict[str, dict] = {}
    for field_name in FIELDS:
        a_top = a[field_name].most_common(5)
        b_top = b[field_name].most_common(5)
        diff[field_name] = {"a": a_top, "b": b_top}
    return diff


def compare_text(tag_a: str, tag_b: str) -> str:
    diff = compare_by_tag(tag_a, tag_b)
    lines = [f"=== corpus compare — '{tag_a}' vs '{tag_b}' ==="]
    for field_name, sides in diff.items():
        a_top = sides["a"]
        b_top = sides["b"]
        if not a_top and not b_top:
            continue
        a_str = ", ".join(f"{v}({c})" for v, c in a_top) or "(none)"
        b_str = ", ".join(f"{v}({c})" for v, c in b_top) or "(none)"
        lines.append(f"  {field_name}")
        lines.append(f"    {tag_a}: {a_str}")
        lines.append(f"    {tag_b}: {b_str}")
    return "\n".join(lines)
