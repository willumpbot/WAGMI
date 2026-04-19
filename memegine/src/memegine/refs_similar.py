"""Similar refs — "show me refs visually close to this one".

Uses perceptual hash (same as dedup) but returns top-N closest instead
of dup groups. Useful when the operator picks a winner and wants to
see what else in the corpus looks like it — maybe there are other
candidate winners hiding in there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import dedup, reference_lib
from .config import settings


@dataclass
class SimilarHit:
    ref_id: str
    filename: str
    distance: int
    notes: str = ""
    tags: list[str] = field(default_factory=list)


def find_similar(
    ref_id: str,
    *,
    limit: int = 10,
) -> list[SimilarHit]:
    """Return the N refs whose pHash is closest to `ref_id`'s pHash."""
    refs = reference_lib._load_index()
    target = next((r for r in refs if r["id"] == ref_id), None)
    if target is None:
        raise KeyError(f"ref not found: {ref_id}")

    target_path = settings.references_dir / target["filename"]
    if not target_path.exists():
        raise FileNotFoundError(target_path)
    target_hash = dedup._phash(target_path)

    results: list[SimilarHit] = []
    for r in refs:
        if r["id"] == ref_id:
            continue
        path = settings.references_dir / r["filename"]
        if not path.exists():
            continue
        try:
            h = dedup._phash(path)
        except Exception:
            continue
        dist = dedup._hamming(target_hash, h)
        results.append(SimilarHit(
            ref_id=r["id"],
            filename=r["filename"],
            distance=dist,
            notes=r.get("notes", "") or "",
            tags=r.get("tags", []) or [],
        ))

    results.sort(key=lambda h: h.distance)
    return results[:limit]


def find_similar_text(ref_id: str, *, limit: int = 10) -> str:
    try:
        hits = find_similar(ref_id, limit=limit)
    except (KeyError, FileNotFoundError) as exc:
        return f"ERROR: {exc}"
    if not hits:
        return f"no other refs to compare against {ref_id}"
    lines = [f"=== refs similar to {ref_id} — {len(hits)} hits ==="]
    for h in hits:
        tags_preview = ",".join(h.tags[:4])
        lines.append(f"  dist={h.distance:<3}  {h.ref_id}  tags:[{tags_preview}]")
        if h.notes:
            lines.append(f"         {h.notes[:80]}")
    return "\n".join(lines)
