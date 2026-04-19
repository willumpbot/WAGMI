"""Corpus — bulk ingest a folder of confirmed-good work.

The operator has a folder (Google Drive sync, Dropbox sync, or any
local path) full of pieces that real editors have signed off on. This
module walks the folder, copies each piece into the reference library,
and auto-infers tags from filename + folder structure.

This is the bootstrapping path. Instead of starting with an empty
codex, the operator points at their archive and memegine extracts
100+ confirmed pieces worth of ground-truth style.

Supported file types:
- Images: .png .jpg .jpeg .webp .gif  → added as a ref directly
- Videos: .mp4 .mov .m4v .webm        → N frames extracted via ffmpeg,
                                        each frame added as a ref with
                                        `source=video:<filename>` tag

Sidecar text:
- A `.txt` file with the same basename as an image/video is read and
  the contents stored as the ref's `prompt` field. Useful when the
  editor has already written a prompt next to each file.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import reference_lib


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


@dataclass
class IngestResult:
    folder: str
    images_seen: int = 0
    videos_seen: int = 0
    images_imported: int = 0
    video_frames_imported: int = 0
    skipped_duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    imported_ref_ids: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"=== corpus ingest — {self.folder} ===",
            f"  images seen:            {self.images_seen}",
            f"  videos seen:            {self.videos_seen}",
            f"  images imported:        {self.images_imported}",
            f"  video frames imported:  {self.video_frames_imported}",
            f"  skipped (dupes):        {self.skipped_duplicates}",
        ]
        if self.errors:
            lines.append(f"  errors ({len(self.errors)}):")
            for e in self.errors[:10]:
                lines.append(f"    - {e}")
        return "\n".join(lines)


def _infer_tags(file_path: Path, base_folder: Path) -> list[str]:
    """Turn filename + folder hierarchy into tags.

    Example: /Dropbox/memegine-ingest/photoreal/portraits/3am_trader.png
    → ["photoreal", "portraits", "3am", "trader"]
    """
    tags: list[str] = []
    # Folders between base_folder and the file → tags.
    try:
        rel = file_path.relative_to(base_folder)
        for part in rel.parts[:-1]:   # skip filename itself
            clean = part.lower().replace("-", "_").replace(" ", "_")
            # Skip conventional "ingest" / "memegine" wrapper dirs.
            if clean in ("memegine_ingest", "ingest", "memegine", "refs", "assets"):
                continue
            tags.append(clean)
    except ValueError:
        pass

    # Split stem on common separators → tags. Keep only word-ish tokens.
    stem = file_path.stem.lower()
    tokens = re.split(r"[\s\-_.]+", stem)
    for tok in tokens:
        if len(tok) >= 2 and tok.isalnum() and not tok.isdigit():
            if tok not in tags:
                tags.append(tok)

    # De-dupe and cap.
    return tags[:10]


def _read_sidecar(file_path: Path) -> str:
    """Look for a .txt with the same stem as the media file."""
    sidecar = file_path.with_suffix(".txt")
    if sidecar.exists():
        try:
            return sidecar.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
    return ""


def _iter_media(folder: Path):
    """Yield media files recursively."""
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTS or suffix in VIDEO_EXTS:
            yield path


def ingest(
    folder: str | Path,
    *,
    frames_per_video: int = 5,
    tag_prefix: str | None = None,
    source: str = "corpus",
    generate_thumbs: bool = True,
) -> IngestResult:
    """Walk `folder`, import every image and video frame into refs.

    frames_per_video: number of stills to extract per video. 0 disables
    video processing.
    tag_prefix: if set, prepended to every ref's tag list (useful for
    marking "imported on 2026-04-19" or similar).
    generate_thumbs: if True (default), generate 256px thumbnails for
    every ref after ingest so the library is immediately phone-ready.
    """
    folder = Path(folder)
    result = IngestResult(folder=str(folder))
    if not folder.exists():
        result.errors.append(f"folder does not exist: {folder}")
        return result
    if not folder.is_dir():
        result.errors.append(f"not a directory: {folder}")
        return result

    # Lazy import so video ingest is optional.
    from . import video_frames

    prefix_tags = [tag_prefix] if tag_prefix else []

    for media in _iter_media(folder):
        suffix = media.suffix.lower()
        tags = prefix_tags + _infer_tags(media, folder)
        prompt = _read_sidecar(media)

        try:
            if suffix in IMAGE_EXTS:
                result.images_seen += 1
                entry = reference_lib.add(
                    media, tags=tags, source=source, prompt=prompt,
                    notes="corpus ingest",
                )
                # reference_lib.add dedupes by content-hash; if the file
                # was already in refs, the index entry is replaced but
                # the file isn't duplicated. Count once per unique id.
                if entry.id in result.imported_ref_ids:
                    result.skipped_duplicates += 1
                else:
                    result.imported_ref_ids.append(entry.id)
                    result.images_imported += 1

            elif suffix in VIDEO_EXTS:
                result.videos_seen += 1
                if frames_per_video <= 0:
                    continue
                try:
                    frame_paths = video_frames.extract(
                        media, n_frames=frames_per_video,
                    )
                except Exception as exc:
                    result.errors.append(f"video frames failed for {media.name}: {exc}")
                    continue
                try:
                    video_tag = f"video:{media.stem}"
                    for i, frame in enumerate(frame_paths):
                        entry = reference_lib.add(
                            frame,
                            tags=tags + [video_tag, f"frame:{i+1}"],
                            source=f"video:{media.name}",
                            prompt=prompt,
                            notes=f"frame {i+1}/{len(frame_paths)} from {media.name}",
                        )
                        if entry.id in result.imported_ref_ids:
                            result.skipped_duplicates += 1
                        else:
                            result.imported_ref_ids.append(entry.id)
                            result.video_frames_imported += 1
                finally:
                    # Clean up temp frame files; reference_lib already
                    # copied them to the library.
                    for frame in frame_paths:
                        try:
                            frame.unlink(missing_ok=True)
                        except OSError:
                            pass
        except Exception as exc:
            result.errors.append(f"{media.name}: {type(exc).__name__}: {exc}")

    if generate_thumbs and (result.images_imported or result.video_frames_imported):
        try:
            from . import thumbnails
            thumbnails.generate_all()
        except Exception as exc:
            result.errors.append(f"thumbnails: {type(exc).__name__}: {exc}")

    return result
