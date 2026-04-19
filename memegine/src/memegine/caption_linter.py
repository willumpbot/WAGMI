"""Caption linter — validates X captions before they ship.

The prompt linter catches AI-slop in Grok prompts. But the caption is
what the audience actually reads. A bad caption kills a good image.

This linter enforces the rules from `copy_writer`:
- No emojis. No hashtags. No engagement-bait.
- No "gm/wagmi/lfg/this is the way/massive".
- Length sanity: 0-280 chars (X limit), with bonuses for being actually
  short (the best captions are <= 20 words).
- No "AI voice": "let me know", "thoughts?", "which one?", "tag a friend".
- No lowercase-hashtags hiding as words ("nocoiner" is fine, "#nocoiner" is not).

Returns a 0-100 score so export.build() can refuse to ship bad captions
(configurable threshold).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


EMOJI_RE = re.compile(
    r"["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002500-\U00002BEF"  # chinese chars
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\U00010000-\U0010ffff"
    "\u2640-\u2642"
    "\u2600-\u2B55"
    "\u200d"
    "\u23cf"
    "\u23e9"
    "\u231a"
    "\ufe0f"
    "\u3030"
    "]+",
    flags=re.UNICODE,
)

BANNED_PHRASES = (
    # Engagement bait
    "who else", "tag a friend", "let me know", "thoughts?", "which one",
    "what do you think", "agree?", "am i wrong", "drop a",
    # Dead crypto dialect
    "gm", "wagmi", "lfg", "this is the way", "massive", "bullish on",
    "moon soon", "to the moon", "make it", "probably nothing",
    # AI-voice tells
    "in this piece", "here we see", "captures the essence", "evokes",
    "embodies the spirit of", "speaks to",
    # Obvious slop
    "epic", "cinematic", "stunning", "beautiful", "breathtaking",
)

# Short-form dead phrases we only want to match as whole words.
BANNED_WORDS = (
    "epic", "cinematic", "stunning", "beautiful", "breathtaking", "gm",
    "wagmi", "lfg", "massive", "evokes",
)


@dataclass
class CaptionLintResult:
    ok: bool
    score: int                       # 0-100
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    length: int = 0                  # chars
    words: int = 0

    def as_text(self) -> str:
        lines = [
            f"caption lint: {'PASS' if self.ok else 'FAIL'}  score {self.score}/100  "
            f"len={self.length} words={self.words}"
        ]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  warn:  {w}")
        return "\n".join(lines)


def _find_hashtags(text: str) -> list[str]:
    return re.findall(r"(?<!\w)#\w+", text)


def _find_word(text: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text.lower()) is not None


def lint(caption: str) -> CaptionLintResult:
    errors: list[str] = []
    warnings: list[str] = []

    length = len(caption)
    words = len(re.findall(r"\S+", caption))

    # Hard failures.
    emojis = EMOJI_RE.findall(caption)
    if emojis:
        errors.append(f"contains emoji(s): {emojis}")

    hashtags = _find_hashtags(caption)
    if hashtags:
        errors.append(f"contains hashtag(s): {hashtags}")

    for phrase in BANNED_PHRASES:
        if phrase in caption.lower():
            errors.append(f"banned phrase: '{phrase}'")

    for w in BANNED_WORDS:
        if _find_word(caption, w):
            errors.append(f"banned word: '{w}'")

    if length > 280:
        errors.append(f"exceeds X's 280 char limit (got {length})")

    # Warnings — don't fail but reduce score.
    if length == 0:
        warnings.append("empty caption — either post with no caption at all, or write something")
    elif words > 30:
        warnings.append(f"caption is {words} words — consider a one-liner")

    if caption.count("!") > 1:
        warnings.append("multiple exclamation marks — reads as AI-enthusiasm")

    # Score: start at 100, subtract 25 per error, 10 per warning, then
    # clamp to 0. Perfect caption (no errors, no warnings) = 100.
    score = 100 - 25 * len(errors) - 10 * len(warnings)
    score = max(0, min(100, score))

    return CaptionLintResult(
        ok=len(errors) == 0,
        score=score,
        errors=errors,
        warnings=warnings,
        length=length,
        words=words,
    )
