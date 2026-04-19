from __future__ import annotations

import datetime as dt
from pathlib import Path

from .config import settings


def read(path: Path | None = None) -> str:
    path = path or settings.codex_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def append_entry(
    section: str,
    body: str,
    path: Path | None = None,
) -> None:
    """Append a timestamped note under the named section.

    Section is matched case-insensitively by the header line (## Section).
    If the section doesn't exist, it's created at the bottom of the file.
    """
    path = path or settings.codex_path
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    stamp = dt.date.today().isoformat()
    entry = f"- ({stamp}) {body.strip()}"

    header = f"## {section}"
    lines = existing.splitlines()
    target_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip().lower() == header.lower()),
        None,
    )

    if target_idx is None:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        new = existing + f"\n{header}\n{entry}\n"
        path.write_text(new, encoding="utf-8")
        return

    insert_at = len(lines)
    for i in range(target_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            insert_at = i
            break
    lines.insert(insert_at, entry)
    path.write_text(
        "\n".join(lines) + ("\n" if not existing.endswith("\n") else ""),
        encoding="utf-8",
    )


def log_winner(prompt: str, why: str, path: Path | None = None) -> None:
    append_entry("Proven Prompt Patterns", f'"{prompt}" — {why}', path)


def log_flop(what: str, why: str, path: Path | None = None) -> None:
    append_entry("Kill List", f"{what} — {why}", path)


DEFAULT_TEMPLATE = """# Style codex

The living style memory for this project. Everything memegine reads
before writing any new brief goes here. This file IS your taste.

## North Star
<!-- 1-3 sentence description of the creative project: who it's for, what
register it lives in, what's off-limits. Example: "An X-native account
for high-craft crypto-native photoreal/meme content. 40k followers.
Tone is deadpan. Never overexplains. Lives in a late-night register." -->
- (empty)

## Voice & Tone
<!-- Observations about the operator's voice. Adjectives, frames,
syntactic patterns that make captions sound like a person, not AI. -->
- (empty)

## Visual DNA
<!-- The non-negotiable visual ingredients: preferred palette, preferred
film stocks, preferred aspect ratios, weather/time-of-day defaults. -->
- (empty)

## Recurring Subjects / Characters
<!-- If a character or motif is central (e.g. Kilroy, a self-avatar), pin
it here. Include a consistent physical descriptor. -->
- (empty)

## Proven Prompt Patterns
<!-- Populated automatically when you run `memegine codex winner` or add
a ref with --winner. Week-over-week, this is where compounding happens. -->
- (empty)

## Compounded Patterns
<!-- Populated automatically from winners' extracted craft tokens. -->
- (empty)

## Core Patterns
<!-- Populated automatically by `memegine codex graduate` when a pattern
crosses the promotion threshold. Top of the pyramid. -->
- (empty)

## Weekly Distill
<!-- Populated automatically by `memegine codex distill`. Week-level
pattern frequencies. -->
- (empty)

## Proven Model Routing (Grok)
<!-- Which Grok engine works for which task? Track empirically:
"aurora > flux for photoreal portraits", "ideogram for all text-in-image",
etc. -->
- (empty)

## Kill List
<!-- Words, formats, topics, aesthetics that don't work for this project.
Never brief these again. -->
- (empty)

## Voice Notes
<!-- Operator notes that don't fit elsewhere: "captions feel better after
3am", "Saturday posts get 3x the engagement", etc. -->
- (empty)
"""


def init_template(path: Path | None = None, *, force: bool = False) -> Path:
    """Seed a fresh codex with the default section template.

    force: if True, overwrite an existing codex. Default is refuse and
    raise FileExistsError — the operator's codex is precious.
    """
    path = path or settings.codex_path
    if path.exists() and not force:
        existing = path.read_text(encoding="utf-8")
        if existing.strip():
            raise FileExistsError(
                f"codex at {path} is not empty; pass force=True to overwrite"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return path
