from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ._time import now_iso as _now_iso
from .config import settings


INDEX_PATH = settings.references_dir / "index.json"


def _index_path() -> Path:
    """Resolve the current index path from settings at call-time.

    This indirection lets tests monkeypatch `settings.references_dir` and
    have _load_index / _save_index pick it up without also patching
    module-level INDEX_PATH.
    """
    return settings.references_dir / "index.json"


@dataclass
class ReferenceEntry:
    id: str
    filename: str
    added_at: str
    tags: list[str] = field(default_factory=list)
    source: str = ""  # "grok", "shot", "web", etc.
    prompt: str = ""  # the prompt that produced it, if known
    notes: str = ""   # why it's a keeper


def _load_index(path: Path | None = None) -> list[dict]:
    path = path or _index_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_index(entries: list[dict], path: Path | None = None) -> None:
    path = path or _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def add(
    image_path: Path,
    tags: list[str] | None = None,
    source: str = "",
    prompt: str = "",
    notes: str = "",
    winner: bool = False,
    auto_variants: bool = False,
    n_variants: int = 0,
) -> ReferenceEntry:
    """Copy an image into the reference library and record it in the index.

    When winner=True AND prompt is non-empty, also appends the prompt as
    a winning pattern to the style codex and auto-extracts the named
    craft tokens (lens, film, lighting, time, composition, camera move)
    into the 'Compounded Patterns' section. This is the main compounding
    loop: every winner tagged as such makes the next brief sharper.

    auto_variants: if True, also enqueue N variant intents as topics so
    the next session inherits the winning thread (e.g., same character,
    same setup, varied time-of-day / lens). Requires winner=True + a
    non-empty prompt. Uses `n_variants` or defaults to 3.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    settings.references_dir.mkdir(parents=True, exist_ok=True)
    ref_id = hashlib.sha256(image_path.read_bytes()).hexdigest()[:12]
    dest = settings.references_dir / f"{ref_id}{image_path.suffix.lower()}"
    if not dest.exists():
        shutil.copy2(image_path, dest)

    tag_list = list(tags or [])
    if winner and "winner" not in tag_list:
        tag_list.append("winner")

    entry = ReferenceEntry(
        id=ref_id,
        filename=dest.name,
        added_at=_now_iso(),
        tags=tag_list,
        source=source,
        prompt=prompt,
        notes=notes,
    )
    entries = _load_index()
    entries = [e for e in entries if e.get("id") != ref_id]
    entries.append(asdict(entry))
    _save_index(entries)

    if winner and prompt.strip():
        # Lazy import — auto_codex depends on style_codex which reads settings.
        from . import auto_codex
        auto_codex.record_winner(prompt, notes or "(marked winner)", tags=tag_list)

    if auto_variants and winner and prompt.strip():
        _enqueue_winner_variants(prompt, ref_id=ref_id, n=n_variants or 3)

    return entry


def _enqueue_winner_variants(prompt: str, *, ref_id: str, n: int = 3) -> list[str]:
    """Enqueue N axis-varied re-shoot intents derived from a winning prompt.

    We don't actually run a variant brief here — we just seed the topic
    queue with short follow-up intents that reference the winner so the
    next session can build on it. Each enqueued topic gets the tag
    `variant_of:<ref_id>` for traceability.
    """
    from . import topics
    axes = ["TIME_OF_DAY", "LENS", "FILM_STOCK", "LIGHTING", "MOOD"]
    # Pick the first N axes deterministically.
    picks = axes[: max(1, min(n, len(axes)))]
    enqueued: list[str] = []
    for axis in picks:
        intent = (
            f"re-shoot of winner {ref_id[:8]} — vary only the {axis} axis. "
            f"Seed prompt: \"{prompt[:200]}\""
        )
        t = topics.add(
            intent,
            tags=[f"variant_of:{ref_id}", "auto_variant", axis.lower()],
            priority=3,
            source="winner_auto_variants",
        )
        enqueued.append(t.id)
    return enqueued


def search(tags: list[str] | None = None, text: str = "") -> list[dict]:
    entries = _load_index()
    out = entries
    if tags:
        tag_set = {t.lower() for t in tags}
        out = [e for e in out if tag_set.issubset({t.lower() for t in e.get("tags", [])})]
    if text:
        needle = text.lower()
        out = [
            e for e in out
            if needle in e.get("notes", "").lower()
            or needle in e.get("prompt", "").lower()
            or needle in " ".join(e.get("tags", [])).lower()
        ]
    return out


def recent(n: int = 10) -> list[dict]:
    entries = _load_index()
    entries.sort(key=lambda e: e.get("added_at", ""), reverse=True)
    return entries[:n]


def reference_notes_for_prompt(tags: list[str] | None = None, limit: int = 5) -> str:
    """Return a short string block summarizing matching references, to feed into
    the prompt engine's user message.
    """
    hits = search(tags=tags) if tags else recent(limit)
    hits = hits[:limit]
    if not hits:
        return ""
    lines = ["Past winners from reference library:"]
    for e in hits:
        tag_str = ", ".join(e.get("tags", []))
        lines.append(f"- {e['filename']} [{tag_str}] — {e.get('notes') or e.get('prompt', '')[:80]}")
    return "\n".join(lines)
