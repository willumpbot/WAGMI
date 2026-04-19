"""Batch — generate N briefs for one theme across varied formats.

When the operator has a theme (e.g., "the last ETF flow update") they
often want multiple angles fast: a photoreal take, a meme take, a chart
take, an avatar-character take. `memegine batch 4 "<theme>"` produces a
folder of briefs, one per format, all in one call — so the operator can
pick the angle that lands best in the first try of each.

This is the offline path. If the Anthropic key is set, see `batch_execute`
for the key-powered variant that runs each brief through Claude.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import archive, pipeline as pipeline_mod, prompt_engine
from .config import settings


# Curated rotation of formats that cover very different visual registers.
# When batch is asked for N briefs, take the first N from this rotation
# (skipping any not in the current library).
DEFAULT_ROTATION: list[str] = [
    "photoreal_portrait",
    "meme_two_panel",
    "reaction_shot_meme",
    "lore_drop",
    "photoreal_self_avatar",
    "screenshot_terminal",
    "cope_chart",
    "split_screen_then_now",
    "ticker_scroll_overlay",
    "zine_pullquote",
    "photoreal_street_scene",
    "found_footage_still",
]


@dataclass
class BatchItem:
    format_slug: str
    intent: str
    brief_path: str
    bundle_id: str


@dataclass
class BatchResult:
    id: str
    created_at: str
    theme: str
    folder: str
    items: list[BatchItem] = field(default_factory=list)


def _pick_rotation(n: int, formats_available: set[str]) -> list[str]:
    picks: list[str] = []
    for slug in DEFAULT_ROTATION:
        if slug in formats_available:
            picks.append(slug)
        if len(picks) >= n:
            break
    # If we still need more, append any remaining formats we haven't used.
    if len(picks) < n:
        for slug in sorted(formats_available):
            if slug not in picks:
                picks.append(slug)
            if len(picks) >= n:
                break
    return picks[:n]


def build(
    theme: str,
    *,
    n: int,
    formats: list[str] | None = None,
    outputs_dir: Path | None = None,
) -> BatchResult:
    """Produce N briefs for a single theme across varied formats.

    formats: optional explicit list of format slugs. If None, uses a
    curated rotation that covers different visual registers.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    all_formats = prompt_engine.load_formats()
    image_formats = {f.slug for f in all_formats if f.kind == "image"}
    # Filter requested formats to image-kind only (video requires shot lists).
    requested = [f for f in (formats or []) if f in image_formats]
    if not requested:
        requested = _pick_rotation(n, image_formats)

    base = Path(outputs_dir) if outputs_dir else settings.outputs_dir
    base.mkdir(parents=True, exist_ok=True)
    bid = uuid.uuid4().hex[:10]
    stamp = dt.date.today().isoformat()
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in theme).strip().replace(" ", "-")[:40]
    folder = base / f"{stamp}_batch_{slug}_{bid}"
    folder.mkdir(parents=True, exist_ok=True)

    items: list[BatchItem] = []
    for i, fmt in enumerate(requested[:n]):
        system, user = prompt_engine.assemble_offline_prompt(theme, fmt)
        archive.save(
            kind="batch", intent=theme, system=system, user=user,
            format_=fmt, extra={"batch_id": bid, "index": i},
        )
        brief_path = folder / f"{i+1:02d}-{fmt}.md"
        brief_path.write_text(
            f"# batch item {i+1}/{len(requested)} — format: {fmt}\n\n"
            "## SYSTEM\n\n```\n" + system + "\n```\n\n"
            "## USER\n\n```\n" + user + "\n```\n",
            encoding="utf-8",
        )
        items.append(
            BatchItem(
                format_slug=fmt, intent=theme,
                brief_path=str(brief_path), bundle_id=bid,
            )
        )

    result = BatchResult(
        id=bid,
        created_at=dt.datetime.utcnow().isoformat() + "Z",
        theme=theme,
        folder=str(folder),
        items=items,
    )
    (folder / "batch.json").write_text(
        json.dumps(asdict(result), indent=2, default=str),
        encoding="utf-8",
    )
    (folder / "README.md").write_text(
        f"# Batch — {theme}\n\n"
        f"- id: `{bid}`\n"
        f"- generated {len(items)} briefs across formats: "
        + ", ".join(it.format_slug for it in items) + "\n\n"
        "## Workflow\n\n"
        "1. Open each `.md` in order, paste into Claude Code.\n"
        "2. Pick 1-2 that resonate with this week's style codex.\n"
        "3. Execute in Grok; discard the ones that don't land.\n"
        "4. `memegine refs add <file> --winner --prompt \"...\" --notes \"why\"`\n",
        encoding="utf-8",
    )
    return result
