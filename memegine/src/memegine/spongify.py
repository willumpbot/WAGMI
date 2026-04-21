"""Spongify — turn any X profile picture into a Spongmonkey reply asset.

This is the canonical Joel Veitch / rathergood move: take a real photo,
paste a blurry photo-cutout monkey head with huge googly eyes over the
head. Applied to crypto-twitter profile pictures it becomes raid
ammunition — you reply to a trader with a spongified version of their
own face.

Workflow:
    handles → fetch profile pic URLs → download images → write per-pic
    prompt that tells Grok (with attached reference image) to spongify
    the subject → bundle everything into data/projects/spong/spongify/
    <date>/<handle>.{jpg,prompt.txt}

In TG / bot flow, the bot sends:
    photo: downloaded profile pic
    text:  "paste into Grok Imagine + attach this image"
    text:  the spongify prompt (code block for easy copy)

Grok Imagine accepts image inputs, so the operator uploads the pic +
pastes the prompt → Grok renders the spongified version → operator
downloads + replies on X.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import x_fetch, x_playwright
from .config import settings


def _profile_pic_url(handle: str) -> Optional[str]:
    """Get a user's profile picture URL using the FREE syndication path.

    Strategy:
      1. Find any cached tweet by this handle in ops_db / x_fetch cache
         — if present, read author_profile_image_url.
      2. If not cached, fetch a known-recent tweet by this handle
         (requires at least one URL they've been seen on), OR use the
         Playwright fallback if available.

    For the common case where we saw this handle via a card (operator
    pasted a URL → card → ops_db has the tweet → pfp is already there),
    this is instant and zero-cost.
    """
    # Try ops_db first — every tweet we've cached has the author's pfp.
    try:
        from . import ops_db
        tweets = ops_db.tweets_recent(limit=10, handle=handle.lstrip("@").lower())
        for t in tweets:
            pfp = t.get("author_profile_image_url") or ""
            if pfp:
                return pfp
    except Exception:
        pass
    # Try x_fetch cache
    for td in x_fetch.recent(limit=100):
        if td.author_handle == handle.lstrip("@").lower() and td.author_profile_image_url:
            return td.author_profile_image_url
    # Final fallback: Playwright (may fail if no session)
    try:
        return x_playwright.profile_picture_url(handle)
    except Exception:
        return None


# Prompt template applied to every spongify target. Slot-substituted
# per handle. Keeps body/scene photo-real; only the head gets swapped.
SPONGIFY_PROMPT = """\
Using the attached reference photo of @{handle}, produce a SPONGIFIED
portrait: keep the subject's BODY, clothing, pose, and background
EXACTLY as they appear in the reference. Replace ONLY the head with a
spongmonkey — a blurry photo-cutout of a real monkey head with
{fur_color} fur, HUGE white googly eyes nearly touching each other with
tiny black pinpoint pupils, open singing mouth showing cream buck teeth
and red gums. Size the monkey head to match the original head's
placement exactly.

Style constraints:
- The head layer carries deliberate 2003 Joel Veitch / rathergood.com
  jpeg compression — visible macroblocks, slight chromatic aberration,
  matte cutout edges (obviously pasted, NOT blended).
- The body, clothing, and background stay PHOTO-REAL — no illustration,
  no stylization, no cartoon shading on anything besides the head.
- Aspect ratio: 1:1 square (Twitter reply-compatible).
- Hand-scrawled lowercase caption at the bottom in marker or childlike
  Comic Sans: "{lyric}".

The gap between a real photo and a cursed 2003 monkey head IS the
joke. Sincerity, not irony.

NEGATIVES: no clean/smooth head-blend; no full-body illustration; no
modern typography; no smirking expression (mouth is always OPEN
singing); no corrections to "wrong" eye proportions (they SHOULD be
comically oversized); no bearded monkey or smiling monkey.
"""


@dataclass
class SpongifyTarget:
    handle: str
    pfp_url: str
    local_pfp_path: Path
    prompt: str
    prompt_path: Path


@dataclass
class SpongifyBatch:
    folder: Path
    targets: list[SpongifyTarget] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            "=== spongify batch ===",
            f"folder:   {self.folder}",
            f"success:  {len(self.targets)}",
            f"failures: {len(self.failures)}",
        ]
        for t in self.targets:
            lines.append(f"  ✓ @{t.handle}")
            lines.append(f"    pfp:    {t.local_pfp_path}")
            lines.append(f"    brief:  {t.prompt_path}")
        for handle, why in self.failures:
            lines.append(f"  ✗ @{handle}  — {why}")
        return "\n".join(lines)


def _batch_folder() -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    root = settings.data_dir / "spongify" / stamp
    root.mkdir(parents=True, exist_ok=True)
    return root


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                f.write(resp.read())
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False


# Rotation pool — default variety across a batch so a raid doesn't look
# identical across 10 replies.
DEFAULT_FUR = ["normal peach-brown", "pink", "neon green", "rainbow",
               "blue", "purple"]
DEFAULT_LYRICS = [
    "we like the moon.",
    "we like the bag.",
    "we are on the moon now.",
    "we love the subs.",
    "we like the chart.",
    "we like the floor.",
]


def spongify_handles(
    handles: list[str],
    *,
    fur_rotation: Optional[list[str]] = None,
    lyric_rotation: Optional[list[str]] = None,
    batch_folder: Optional[Path] = None,
) -> SpongifyBatch:
    """For each handle: fetch profile pic URL, download, write prompt.

    Returns a SpongifyBatch with per-target paths + any failures. Good
    for:
        - one-at-a-time from a tweet card's spongify button
        - mass (raid mode) via CLI: pass all 10 handles at once
    """
    folder = batch_folder or _batch_folder()
    fur_pool = fur_rotation or DEFAULT_FUR
    lyric_pool = lyric_rotation or DEFAULT_LYRICS
    batch = SpongifyBatch(folder=folder)

    for i, raw in enumerate(handles):
        handle = raw.lstrip("@").strip().lower()
        if not handle:
            continue
        pfp_url = _profile_pic_url(handle)
        if not pfp_url:
            batch.failures.append((handle, "no profile picture found (no cached tweet for this handle)"))
            continue

        # Determine extension from URL.
        suffix = ".jpg"
        parsed = urllib.parse.urlparse(pfp_url).path.lower()
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            if parsed.endswith(ext):
                suffix = ".jpg" if ext == ".jpeg" else ext
                break

        local = folder / f"{handle}{suffix}"
        if not _download(pfp_url, local):
            batch.failures.append((handle, "download failed"))
            continue

        fur = fur_pool[i % len(fur_pool)]
        lyric = lyric_pool[i % len(lyric_pool)]
        prompt_text = SPONGIFY_PROMPT.format(
            handle=handle, fur_color=fur, lyric=lyric,
        )
        prompt_path = folder / f"{handle}.prompt.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        batch.targets.append(SpongifyTarget(
            handle=handle, pfp_url=pfp_url,
            local_pfp_path=local, prompt=prompt_text,
            prompt_path=prompt_path,
        ))

    # Write a batch README summarizing the whole raid pack.
    readme = folder / "README.md"
    readme_lines = [
        "# Spongify batch",
        f"- folder: `{folder}`",
        f"- generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- targets: {len(batch.targets)}",
        "",
        "## How to use",
        "For each target below:",
        "1. Open Grok Imagine",
        "2. Upload the `<handle>.jpg` profile pic as reference",
        "3. Paste the matching `<handle>.prompt.txt` as the prompt",
        "4. Generate, download, reply to a @<handle> tweet with it",
        "",
        "## Targets",
    ]
    for t in batch.targets:
        readme_lines.append(f"- @{t.handle}")
        readme_lines.append(f"  - pfp: `{t.local_pfp_path.name}`")
        readme_lines.append(f"  - prompt: `{t.prompt_path.name}`")
    readme.write_text("\n".join(readme_lines), encoding="utf-8")

    return batch
