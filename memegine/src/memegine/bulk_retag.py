"""Bulk retag — rename / remove / add tags across many refs at once.

Phone-friendly operator ops like:
- "change every 'portraits' tag to 'portrait'" (rename)
- "remove the 'old_import_batch' tag from every ref" (remove)
- "add 'winner' to every ref currently tagged 'hero'" (add-by-selector)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import reference_lib


@dataclass
class RetagResult:
    changed: int = 0
    details: list[tuple[str, list[str], list[str]]] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [f"=== retag — {self.changed} refs changed ==="]
        for rid, before, after in self.details[:20]:
            lines.append(f"  {rid}  {before}  →  {after}")
        if len(self.details) > 20:
            lines.append(f"  (... {len(self.details) - 20} more)")
        return "\n".join(lines)


def rename(from_tag: str, to_tag: str, *, dry_run: bool = False) -> RetagResult:
    """Replace every occurrence of `from_tag` with `to_tag`."""
    refs = reference_lib._load_index()
    result = RetagResult()
    for r in refs:
        tags = r.get("tags", []) or []
        if from_tag not in tags:
            continue
        new_tags = [to_tag if t == from_tag else t for t in tags]
        # De-dupe while preserving order.
        seen: list[str] = []
        for t in new_tags:
            if t not in seen:
                seen.append(t)
        if seen != tags:
            result.changed += 1
            result.details.append((r["id"], list(tags), seen))
            if not dry_run:
                r["tags"] = seen
    if not dry_run and result.changed:
        reference_lib._save_index(refs)
    return result


def remove(tag: str, *, dry_run: bool = False) -> RetagResult:
    """Strip `tag` from every ref that has it."""
    refs = reference_lib._load_index()
    result = RetagResult()
    for r in refs:
        tags = r.get("tags", []) or []
        if tag not in tags:
            continue
        new_tags = [t for t in tags if t != tag]
        result.changed += 1
        result.details.append((r["id"], list(tags), new_tags))
        if not dry_run:
            r["tags"] = new_tags
    if not dry_run and result.changed:
        reference_lib._save_index(refs)
    return result


def add_where(selector_tag: str, new_tag: str, *, dry_run: bool = False) -> RetagResult:
    """Add `new_tag` to every ref currently tagged with `selector_tag`."""
    refs = reference_lib._load_index()
    result = RetagResult()
    for r in refs:
        tags = r.get("tags", []) or []
        if selector_tag not in tags or new_tag in tags:
            continue
        new_tags = list(tags) + [new_tag]
        result.changed += 1
        result.details.append((r["id"], list(tags), new_tags))
        if not dry_run:
            r["tags"] = new_tags
    if not dry_run and result.changed:
        reference_lib._save_index(refs)
    return result
