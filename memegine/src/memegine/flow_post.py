"""Flow post — high-volume reply-guy pipeline.

The counterpart to flow_video, optimized for stills + speed:

    `memegine post "<intent>"`      one-liner: brief → clipboard → browser
    `memegine batch N`              N briefs from the topic queue, sequenced
    `memegine raid "<theme>"`       one theme across 5+ formats at once

All skip the watch-folder step — you're posting replies in rapid-fire,
not babysitting a video render. Clipboard holds everything, numbered.
"""
from __future__ import annotations

import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import (
    _clipboard,
    format_suggest,
    pipeline as pipeline_mod,
    prompt_engine,
    topics as topics_mod,
)
from .config import settings


# Per-brand default reply format when --format isn't specified.
BRAND_DEFAULT_REPLY_FORMAT: dict[str, str] = {
    "motion": "motion_reply_square",
    "kilroy": "kilroy_reply_square",
    "spong": "spong_reply_square",
}

GROK_IMAGINE_URL = "https://grok.com/imagine"


@dataclass
class PostResult:
    intent: str
    brand: str
    format_slug: str
    brief_folder: Path
    brief_prompt: str
    clipboard_ok: bool
    browser_opened: bool
    notes: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            "=== post ===",
            f"brand:      {self.brand}",
            f"intent:     {self.intent}",
            f"format:     {self.format_slug}",
            f"brief:      {self.brief_folder}",
            f"clipboard:  {'OK' if self.clipboard_ok else 'FAILED'}",
            f"browser:    {'opened' if self.browser_opened else 'skipped'}",
        ]
        for n in self.notes:
            lines.append(f"note: {n}")
        return "\n".join(lines)


@dataclass
class BatchResult:
    count: int
    brand: str
    briefs: list[tuple[str, str, Path]] = field(default_factory=list)
    clipboard_ok: bool = False
    clipboard_chars: int = 0

    def as_text(self) -> str:
        lines = [
            "=== batch ===",
            f"brand:      {self.brand}",
            f"briefs:     {self.count}",
            f"clipboard:  {'OK' if self.clipboard_ok else 'FAILED'} "
            f"({self.clipboard_chars:,} chars)",
        ]
        for i, (intent, slug, folder) in enumerate(self.briefs, 1):
            lines.append(f"  [{i:>2}] {slug:<28} {intent[:60]}")
            lines.append(f"        {folder}")
        return "\n".join(lines)


def _pick_format(intent: str, kind: str = "image") -> str:
    """Return the best format slug for a reply-shaped post.

    Rule: when the active brand has a default reply format, use it
    UNLESS the suggested format is already brand-scoped (kilroy_*,
    motion_*, spong_*) for the current project. This keeps the reply-
    square flowing for generic intents ("ftx anniversary") while still
    honoring explicit brand keywords ("kilroy polaroid of the FTX").
    """
    default = BRAND_DEFAULT_REPLY_FORMAT.get(settings.project)
    suggested = format_suggest.best(intent, kind=kind)
    if default and not suggested.startswith(f"{settings.project}_"):
        return default
    return suggested


def _assemble_full_prompt(intent: str, format_slug: str) -> tuple[str, str, Path]:
    """Build the pipeline bundle + return (system+user prompt, slug, folder)."""
    bundle = pipeline_mod.build(intent, kind="image", format_slug=format_slug)
    system, user = prompt_engine.assemble_offline_prompt(intent, format_slug)
    full = f"{system}\n\n---\n\n{user}"
    return full, bundle.format_slug or format_slug, bundle.folder


def post(
    intent: str,
    *,
    format_slug: Optional[str] = None,
    open_browser: bool = True,
) -> PostResult:
    """One-shot: pick format → write brief → clipboard → browser."""
    slug = format_slug or _pick_format(intent)
    full, resolved_slug, folder = _assemble_full_prompt(intent, slug)

    copied = _clipboard.copy(full)
    browser_ok = False
    if open_browser:
        try:
            webbrowser.open(GROK_IMAGINE_URL)
            browser_ok = True
        except webbrowser.Error:
            pass

    notes = []
    if copied:
        notes.append("brief on your clipboard — paste into Grok")
    else:
        notes.append("clipboard copy failed — full brief saved to the brief folder")
    return PostResult(
        intent=intent,
        brand=settings.project,
        format_slug=resolved_slug,
        brief_folder=folder,
        brief_prompt=full,
        clipboard_ok=copied,
        browser_opened=browser_ok,
        notes=notes,
    )


def batch(
    n: int = 10,
    *,
    only_priority: Optional[int] = None,
    copy_clipboard: bool = True,
) -> BatchResult:
    """Generate N briefs from the active project's topic queue.

    Drains the top N queued topics (priority-sorted), writes a brief
    for each, and concatenates all briefs into one clipboard payload
    numbered 1..N so the operator can paste → Grok → next → paste.

    Does NOT mark topics as used — that happens when the operator
    actually posts via `memegine topics mark-used <id>`.
    """
    queued = topics_mod.list_queued()
    if only_priority is not None:
        queued = [t for t in queued if int(t.get("priority", 3)) == only_priority]
    # Priority 1 = highest.
    queued.sort(key=lambda t: (int(t.get("priority", 3)), t.get("created_at", "")))
    picked = queued[:n]

    briefs: list[tuple[str, str, Path]] = []
    sections: list[str] = []
    for i, t in enumerate(picked, 1):
        intent = t.get("text", "").strip()
        hint = t.get("format_hint") or None
        slug = hint or _pick_format(intent)
        try:
            full, resolved_slug, folder = _assemble_full_prompt(intent, slug)
        except ValueError:
            # Unknown format hint — fall back to keyword pick.
            slug = _pick_format(intent)
            full, resolved_slug, folder = _assemble_full_prompt(intent, slug)
        briefs.append((intent, resolved_slug, folder))
        header = (
            f"\n\n{'=' * 70}\n"
            f"BRIEF {i}/{len(picked)} — topic_id={t.get('id', '?')} — "
            f"format={resolved_slug}\n"
            f"intent: {intent}\n"
            f"{'=' * 70}\n\n"
        )
        sections.append(header + full)

    payload = "".join(sections).strip()
    copied = False
    if copy_clipboard and payload:
        copied = _clipboard.copy(payload)

    return BatchResult(
        count=len(briefs),
        brand=settings.project,
        briefs=briefs,
        clipboard_ok=copied,
        clipboard_chars=len(payload),
    )


def raid(
    theme: str,
    *,
    formats: Optional[list[str]] = None,
    copy_clipboard: bool = True,
) -> BatchResult:
    """Generate 5+ coordinated briefs around a single theme.

    Default format mix is brand-aware:
      motion  → motion_reply_square, motion_film_still_serif,
                motion_vertical_letterbox, motion_archival_press_celebrity,
                motion_collage_6panel_bw
      kilroy  → kilroy_reply_square, kilroy_cinema_still_tag,
                kilroy_vhs_rip_tag, kilroy_tabloid_cover_tag,
                kilroy_polaroid_stack_tag, kilroy_tags_news_photo
      spong   → spong_reply_square, spong_solo_scene,
                spong_quiznos_ad_parody, spong_duet_trio

    Each brief riffs on the SAME theme but in a different format — so
    the raid feels coordinated, not duplicative.
    """
    if formats is None:
        formats = _default_raid_formats()
    briefs: list[tuple[str, str, Path]] = []
    sections: list[str] = []
    for i, slug in enumerate(formats, 1):
        # Intent adds the theme + a format-specific angle cue.
        intent = f"{theme} — rendered as format '{slug}'"
        try:
            full, resolved_slug, folder = _assemble_full_prompt(intent, slug)
        except ValueError:
            continue
        briefs.append((intent, resolved_slug, folder))
        header = (
            f"\n\n{'=' * 70}\n"
            f"RAID ASSET {i}/{len(formats)} — theme: {theme}\n"
            f"format: {resolved_slug}\n"
            f"{'=' * 70}\n\n"
        )
        sections.append(header + full)
    payload = "".join(sections).strip()
    copied = False
    if copy_clipboard and payload:
        copied = _clipboard.copy(payload)
    return BatchResult(
        count=len(briefs),
        brand=settings.project,
        briefs=briefs,
        clipboard_ok=copied,
        clipboard_chars=len(payload),
    )


def _default_raid_formats() -> list[str]:
    p = settings.project
    if p == "motion":
        return [
            "motion_reply_square",
            "motion_film_still_serif",
            "motion_vertical_letterbox",
            "motion_archival_press_celebrity",
            "motion_collage_6panel_bw",
        ]
    if p == "kilroy":
        return [
            "kilroy_reply_square",
            "kilroy_cinema_still_tag",
            "kilroy_vhs_rip_tag",
            "kilroy_tabloid_cover_tag",
            "kilroy_polaroid_stack_tag",
            "kilroy_tags_news_photo",
        ]
    if p == "spong":
        return [
            "spong_reply_square",
            "spong_solo_scene",
            "spong_quiznos_ad_parody",
            "spong_duet_trio",
        ]
    return ["photoreal_portrait", "reaction_shot_meme", "meme_two_panel"]
