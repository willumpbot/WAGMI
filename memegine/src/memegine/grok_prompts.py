"""Grok-Imagine-ready prompts (150-200 words, paste-and-go).

The big `prompt_engine.assemble_offline_prompt` returns a 2000+ word
brief meant for an intermediate LLM (Claude/GPT) that then writes the
final visual prompt. That's wrong for Grok Imagine — it takes a
concise visual prompt directly.

This module fills a format's `prompt_scaffold` with random slot values
and returns a tight, ready-to-paste visual prompt. Adds a brief
reference-tweet footer so the Director ties the art to the raid target.
"""
from __future__ import annotations

import random
import re
from typing import Optional

from . import prompt_engine


_SLOT_RE = re.compile(r"\{([a-z_]+)\}")


def build(
    format_slug: str,
    *,
    intent_override: Optional[str] = None,
    target_tweet: Optional[dict] = None,
    seed: Optional[int] = None,
) -> str:
    """Return a Grok-Imagine-ready prompt for the given format.

    Picks random values from each slot_hints list, fills the scaffold,
    appends a 1-2 line context footer referencing the target tweet
    (if any).

    `target_tweet`: optional dict with 'handle' and 'text' keys — used
    only as context (the prompt never quotes the tweet literally).
    """
    if seed is not None:
        random.seed(seed)

    formats = prompt_engine.load_formats()
    fmt = next((f for f in formats if f.slug == format_slug), None)
    if fmt is None:
        raise ValueError(f"unknown format slug: {format_slug}")

    scaffold = (
        fmt.prompt_scaffold
        or fmt.prompt_scaffold_still
        or fmt.prompt_scaffold_motion
        or ""
    ).strip()
    if not scaffold:
        raise ValueError(f"format {format_slug} has no prompt_scaffold")

    # Fill each {slot} from slot_hints — pick a random option.
    filled = scaffold
    for m in _SLOT_RE.finditer(scaffold):
        slot = m.group(1)
        opts = (fmt.slot_hints or {}).get(slot) or []
        value = random.choice(opts) if opts else f"[{slot}]"
        filled = filled.replace("{" + slot + "}", value)

    # Add a tight footer that connects to the raid target.
    lines = [filled.strip()]
    if target_tweet and target_tweet.get("handle"):
        handle = target_tweet["handle"]
        lines.append(
            f"\nContext (do NOT quote directly, only use for thematic relevance): "
            f"reply to @{handle} — topic: "
            f"{(target_tweet.get('text') or '')[:140].strip()}"
        )
    return "\n".join(lines).strip()


def build_many(
    format_slug: str,
    *,
    count: int = 3,
    target_tweet: Optional[dict] = None,
) -> list[str]:
    """Generate N variant prompts by re-rolling the slot values."""
    return [
        build(format_slug, target_tweet=target_tweet, seed=random.randint(0, 10_000_000))
        for _ in range(count)
    ]
