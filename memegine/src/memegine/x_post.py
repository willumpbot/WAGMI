"""X posting pre-flight — everything you need to copy-paste into X.

No API. No paid tier. The operator copies the final media + caption into
the X composer. This module does the final validation, packages the
outputs as a clipboard-friendly block, and produces a checklist.

Flow:
  memegine post build final.png --caption "..."   # produces post bundle
  memegine x prepare <post_bundle_id>              # lints + formats for X
  # → operator opens X on their phone, uploads media, pastes caption.

The dry-run deliberately does NOT call the X API. Free-first.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import caption_linter
from .config import settings


@dataclass
class XPostPlan:
    post_bundle_id: str
    media_path: str
    caption: str
    alt_text: str
    reply_hook: str = ""
    media_size_bytes: int = 0
    caption_length: int = 0
    lint_ok: bool = True
    lint_score: int = 0
    lint_errors: list[str] = field(default_factory=list)
    lint_warnings: list[str] = field(default_factory=list)
    alt_length: int = 0
    warnings: list[str] = field(default_factory=list)

    def clipboard_block(self) -> str:
        parts = [
            "=== MEDIA ===",
            self.media_path,
            "",
            "=== CAPTION (copy to X body) ===",
            self.caption,
            "",
            "=== ALT TEXT (click image → Add description) ===",
            self.alt_text or "(none)",
        ]
        if self.reply_hook:
            parts += ["", "=== REPLY HOOK (quote-reply immediately after) ===", self.reply_hook]
        return "\n".join(parts)

    def checklist_text(self) -> str:
        status = "READY" if self.lint_ok and not self.warnings else (
            "READY WITH WARNINGS" if self.lint_ok else "BLOCKED"
        )
        lines = [f"=== X post plan — {status} ==="]
        lines.append(f"  caption: {self.caption_length} chars, lint score {self.lint_score}/100")
        lines.append(f"  alt text: {self.alt_length} chars")
        lines.append(f"  media: {self.media_path}  ({self.media_size_bytes} bytes)")
        if self.lint_errors:
            lines.append("  lint errors:")
            for e in self.lint_errors:
                lines.append(f"    - {e}")
        if self.lint_warnings:
            lines.append("  lint warnings:")
            for w in self.lint_warnings:
                lines.append(f"    - {w}")
        if self.warnings:
            lines.append("  other warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        lines.append("")
        lines.append("Manual posting steps:")
        lines.append("  1. Open X on your phone.")
        lines.append("  2. Start a new post.")
        lines.append("  3. Attach the media file.")
        lines.append("  4. Click the image → 'Add description' → paste alt text.")
        lines.append("  5. Paste the caption into the post body.")
        lines.append("  6. Post.")
        if self.reply_hook:
            lines.append("  7. Immediately quote-reply your own post with the reply hook.")
        return "\n".join(lines)


def _find_bundle(bundle_id: str, posts_dir: Path | None = None) -> Path | None:
    base = Path(posts_dir) if posts_dir else (settings.data_dir / "posts")
    if not base.exists():
        return None
    for folder in base.iterdir():
        if folder.is_dir() and folder.name.endswith(f"_{bundle_id}"):
            return folder
    # Also allow direct folder names (tests may pass exact name).
    direct = base / bundle_id
    return direct if direct.exists() else None


def prepare(
    post_bundle_id: str,
    *,
    posts_dir: Path | None = None,
) -> XPostPlan:
    """Load an export post bundle, lint it, and produce a posting plan."""
    folder = _find_bundle(post_bundle_id, posts_dir=posts_dir)
    if folder is None:
        raise FileNotFoundError(f"no post bundle found for id {post_bundle_id}")

    meta_path = folder / "meta.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    caption_path = folder / "caption.txt"
    alt_path = folder / "alt_text.txt"
    reply_path = folder / "reply_hook.txt"

    caption = caption_path.read_text(encoding="utf-8").strip() if caption_path.exists() else (meta.get("caption") or "")
    alt_text = alt_path.read_text(encoding="utf-8").strip() if alt_path.exists() else (meta.get("alt_text") or "")
    reply_hook = reply_path.read_text(encoding="utf-8").strip() if reply_path.exists() else (meta.get("reply_hook") or "")

    # Media: prefer the meta.media filename, fall back to first "final.*" file.
    media_name = meta.get("media", "")
    media_path = (folder / media_name) if media_name else next(
        (p for p in folder.iterdir() if p.name.startswith("final.")), None,
    )
    if media_path is None or not media_path.exists():
        raise FileNotFoundError(f"no media file in bundle {folder}")

    lint = caption_linter.lint(caption)

    warnings: list[str] = []
    if not alt_text:
        warnings.append("alt text is empty — accessibility matters; add one")
    if len(alt_text) > 1000:
        warnings.append("alt text > 1000 chars — X enforces a 1000-char limit")

    return XPostPlan(
        post_bundle_id=post_bundle_id,
        media_path=str(media_path),
        caption=caption,
        alt_text=alt_text,
        reply_hook=reply_hook,
        media_size_bytes=media_path.stat().st_size,
        caption_length=len(caption),
        lint_ok=lint.ok,
        lint_score=lint.score,
        lint_errors=[i for i in lint.errors],
        lint_warnings=[i for i in lint.warnings],
        alt_length=len(alt_text),
        warnings=warnings,
    )
