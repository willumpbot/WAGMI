"""Thumbnails — generate small previews for every ref.

When the corpus hits hundreds of refs, browsing them on a phone via
the Telegram bot (or a file-sync view) needs fast previews. This
module writes 256px-wide JPEG thumbnails into
`data/references/thumbs/<ref_id>.jpg`.

Uses PIL (already a hard dep for image_ops). Idempotent: skips refs
whose thumbnail already exists and is newer than the source.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import reference_lib
from .config import settings


@dataclass
class ThumbResult:
    generated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _thumbs_dir() -> Path:
    return settings.references_dir / "thumbs"


def generate_all(*, max_width: int = 256, force: bool = False) -> ThumbResult:
    """Write a thumbnail per ref. Skip unchanged if force=False."""
    from PIL import Image, ImageOps

    result = ThumbResult()
    dest_dir = _thumbs_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    refs = reference_lib._load_index()
    for r in refs:
        source = settings.references_dir / r["filename"]
        if not source.exists():
            result.errors.append(f"missing source: {r['filename']}")
            continue
        dest = dest_dir / f"{r['id']}.jpg"
        if dest.exists() and not force:
            if dest.stat().st_mtime >= source.stat().st_mtime:
                result.skipped += 1
                continue
        try:
            with Image.open(source) as img:
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                # Calculate height preserving aspect.
                w, h = img.size
                if w > max_width:
                    new_h = int(h * max_width / w)
                    img = img.resize((max_width, new_h), Image.LANCZOS)
                img.save(dest, "JPEG", quality=82, optimize=True)
            result.generated += 1
        except Exception as exc:
            result.errors.append(f"{r['filename']}: {type(exc).__name__}: {exc}")
    return result


def thumb_path_for(ref_id: str) -> Path | None:
    """Return the path to a ref's thumbnail, or None if not generated."""
    p = _thumbs_dir() / f"{ref_id}.jpg"
    return p if p.exists() else None


def summary_text(result: ThumbResult) -> str:
    lines = [
        f"=== thumbnails — {result.generated} generated, {result.skipped} skipped ===",
    ]
    if result.errors:
        lines.append(f"  {len(result.errors)} errors (first 5):")
        for e in result.errors[:5]:
            lines.append(f"    - {e}")
    return "\n".join(lines)
