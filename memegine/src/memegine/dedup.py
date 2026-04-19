"""Near-duplicate ref detection.

As the corpus grows past a few hundred refs, editors occasionally
double-ingest (same image from a different source, or a lightly-cropped
variant). This module flags likely duplicates using two signals:

1. Content hash collision (identical bytes — the reference_lib already
   dedupes on this during `add`, but a direct detection pass still
   finds historical duplicates).
2. Perceptual hash similarity (pHash via PIL). Catches resized / re-
   encoded versions that have different byte hashes.

Output is a list of ref-id pairs the operator can review and merge or
delete manually. We never auto-delete — the operator decides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import reference_lib
from .config import settings


@dataclass
class DupGroup:
    kind: str                    # "byte" | "perceptual"
    ref_ids: list[str]
    distance: int = 0            # 0 = identical; larger = farther apart

    def as_line(self) -> str:
        return (
            f"[{self.kind}] dist={self.distance}  "
            + ", ".join(self.ref_ids[:6])
        )


def _phash(path: Path, hash_size: int = 16) -> int:
    """Compute a simple perceptual hash.

    Resize → grayscale → DCT-like average → threshold against mean.
    Returns an int where each bit is 1 if that pixel > mean.
    """
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
        pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for i, p in enumerate(pixels):
        if p > avg:
            bits |= (1 << i)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def find_duplicates(
    *,
    perceptual_threshold: int = 10,
) -> list[DupGroup]:
    """Scan refs and return likely-duplicate groups.

    perceptual_threshold: Hamming distance below which two refs are
    flagged (lower = stricter; 0 = identical pHash). Default 10 on a
    256-bit hash ≈ very similar.
    """
    refs = reference_lib._load_index()
    groups: list[DupGroup] = []

    # Byte-hash duplicates: ref ids in memegine are the sha256 prefix,
    # so identical content → identical id → they'd already be merged by
    # `reference_lib.add`. But check paths in case history has strays.
    by_id: dict[str, list[str]] = {}
    for r in refs:
        by_id.setdefault(r["id"], []).append(r["id"])
    for rid, ids in by_id.items():
        if len(ids) > 1:
            groups.append(DupGroup(kind="byte", ref_ids=[rid] * len(ids), distance=0))

    # Perceptual: compute pHash for every ref, then pair-compare.
    hashes: dict[str, int] = {}
    for r in refs:
        path = settings.references_dir / r["filename"]
        if not path.exists():
            continue
        try:
            hashes[r["id"]] = _phash(path)
        except Exception:
            continue

    id_list = list(hashes.keys())
    for i, a in enumerate(id_list):
        for b in id_list[i + 1:]:
            dist = _hamming(hashes[a], hashes[b])
            if dist <= perceptual_threshold:
                groups.append(DupGroup(kind="perceptual", ref_ids=[a, b], distance=dist))

    return groups


def summary_text(groups: list[DupGroup]) -> str:
    if not groups:
        return "=== dedup — no duplicates detected ==="
    lines = [f"=== dedup — {len(groups)} duplicate group(s) ==="]
    for g in groups:
        lines.append(f"  {g.as_line()}")
    lines.append("")
    lines.append("Review each group manually. To remove a duplicate:")
    lines.append("  edit data/references/index.json and delete the duplicate entry")
    lines.append("  (the content file stays — multiple entries may share it)")
    return "\n".join(lines)
