"""Export — pack a finished piece into a post-ready folder.

The operator has executed the brief in Grok, landed a final, written a
caption. Now they need ONE folder with everything ready to post — the
media, the caption as a .txt so they can copy it on phone, alt text, and a
README with the recommended posting order.

Folder layout produced:

    data/posts/<YYYY-MM-DD>_<slug>_<id>/
      final.<ext>               # the posted media
      caption.txt               # body of the post
      alt_text.txt              # accessibility text
      reply_hook.txt            # optional follow-up reply
      README.md                 # reminder notes for posting
      meta.json                 # source brief id, source ref id, tags

The point: you can open this folder on your phone, long-press caption.txt
to copy, upload final.png or final.mp4, paste the caption, and post. Zero
mental overhead at the moment of posting.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import settings


@dataclass
class PostBundle:
    id: str
    created_at: str
    folder: str
    media_path: str
    caption: str
    alt_text: str
    reply_hook: str = ""
    tags: list[str] = field(default_factory=list)
    source_bundle_id: str | None = None
    source_ref_id: str | None = None


def _posts_dir() -> Path:
    return settings.data_dir / "posts"


def _slug_for(caption: str, fallback: str = "piece") -> str:
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in caption).strip()
    slug = slug.replace(" ", "-")[:40]
    return slug or fallback


def build(
    *,
    media_path: Path,
    caption: str,
    alt_text: str = "",
    reply_hook: str = "",
    tags: list[str] | None = None,
    source_bundle_id: str | None = None,
    source_ref_id: str | None = None,
    posts_dir: Path | None = None,
    strict_caption: bool = False,
) -> PostBundle:
    """Assemble a post-ready folder. Copies media in (never moves).

    media_path must exist and be readable.

    strict_caption: when True, raises ValueError if the caption fails the
    caption linter. When False (default), lint result is written to
    caption_lint.txt but the bundle still builds — operator's call.
    """
    media_path = Path(media_path)
    if not media_path.exists():
        raise FileNotFoundError(media_path)

    base = Path(posts_dir) if posts_dir else _posts_dir()
    base.mkdir(parents=True, exist_ok=True)

    pid = uuid.uuid4().hex[:10]
    stamp = dt.date.today().isoformat()
    slug = _slug_for(caption)
    folder = base / f"{stamp}_{slug}_{pid}"
    folder.mkdir(parents=True, exist_ok=True)

    # Media: keep original extension so x/tweet client auto-detects type.
    final_ext = media_path.suffix.lower() or ".bin"
    final_path = folder / f"final{final_ext}"
    shutil.copy2(media_path, final_path)

    from . import caption_linter
    lint_result = caption_linter.lint(caption)
    if strict_caption and not lint_result.ok:
        raise ValueError(
            "caption fails lint (strict_caption=True): "
            + "; ".join(lint_result.errors)
        )

    (folder / "caption.txt").write_text(caption.strip() + "\n", encoding="utf-8")
    (folder / "alt_text.txt").write_text(alt_text.strip() + "\n", encoding="utf-8")
    (folder / "caption_lint.txt").write_text(lint_result.as_text() + "\n", encoding="utf-8")
    if reply_hook.strip():
        (folder / "reply_hook.txt").write_text(reply_hook.strip() + "\n", encoding="utf-8")

    tags_list = [t.strip() for t in (tags or []) if t.strip()]

    readme = (
        f"# Post bundle — {stamp}\n\n"
        f"- id: `{pid}`\n"
        f"- media: `{final_path.name}`\n"
        f"- tags: {', '.join(tags_list) if tags_list else '-'}\n\n"
        "## Posting order (X / Twitter)\n\n"
        "1. Open X, start a new post.\n"
        "2. Attach `" + final_path.name + "` from this folder.\n"
        "3. Tap the image → 'Add description' → paste `alt_text.txt`.\n"
        "4. Paste `caption.txt` into the post body.\n"
        "5. Post.\n"
        + ("6. Immediately quote-reply with `reply_hook.txt`.\n" if reply_hook.strip() else "")
        + "\n## After posting\n\n"
        "- If it lands: `memegine refs add " + final_path.name + " --winner --notes 'why it landed'`\n"
        "- If it flops: `memegine codex flop \"<what>\" \"<why>\"`\n"
    )
    (folder / "README.md").write_text(readme, encoding="utf-8")

    meta = {
        "id": pid,
        "created_at": dt.datetime.utcnow().isoformat() + "Z",
        "media": final_path.name,
        "caption": caption,
        "alt_text": alt_text,
        "reply_hook": reply_hook,
        "tags": tags_list,
        "source_bundle_id": source_bundle_id,
        "source_ref_id": source_ref_id,
    }
    (folder / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return PostBundle(
        id=pid,
        created_at=meta["created_at"],
        folder=str(folder),
        media_path=str(final_path),
        caption=caption,
        alt_text=alt_text,
        reply_hook=reply_hook,
        tags=tags_list,
        source_bundle_id=source_bundle_id,
        source_ref_id=source_ref_id,
    )


def list_recent(n: int = 20, posts_dir: Path | None = None) -> list[dict]:
    base = Path(posts_dir) if posts_dir else _posts_dir()
    if not base.exists():
        return []
    folders = [p for p in base.iterdir() if p.is_dir()]
    folders.sort(key=lambda p: p.name, reverse=True)
    out = []
    for f in folders[:n]:
        meta_path = f / "meta.json"
        if meta_path.exists():
            try:
                out.append(json.loads(meta_path.read_text()))
                continue
            except json.JSONDecodeError:
                pass
        out.append({"id": f.name, "folder": str(f), "caption": "(meta missing)"})
    return out
