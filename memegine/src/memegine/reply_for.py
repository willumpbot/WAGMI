"""Reply-for — given a target tweet, suggest matching refs + a brief.

The reply-guy core loop:

    tweet-url → fetch → analyze → match refs + suggest formats →
    write brief → clipboard → Grok → reply on X

This is the on-demand counterpart to the (future) auto-watchlist. The
operator pastes a URL they just saw, memegine returns:

  1. The tweet itself (so they know we parsed it right)
  2. Top 3 library refs matching the tweet's topic (images they can
     attach directly — fastest path)
  3. Top 3 format suggestions + a full brief for the top one,
     clipboarded + Grok URL opened (if no library match is strong
     enough)
"""
from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import (
    _clipboard,
    format_suggest,
    pipeline as pipeline_mod,
    prompt_engine,
    reference_lib,
    x_fetch,
)
from .config import settings
from .flow_post import BRAND_DEFAULT_REPLY_FORMAT, GROK_IMAGINE_URL


# Crypto-twitter topic expansion: tweet keyword → additional tags to
# look up. Makes generic tweets match themed motion/spong/kilroy refs.
TOPIC_EXPANSIONS: dict[str, list[str]] = {
    # Emotional states
    "cope":      ["cope", "trader", "night", "3am"],
    "dump":      ["cope", "trader", "night", "red"],
    "rug":       ["cope", "trader", "night", "aftermath"],
    "liquidated": ["cope", "trader", "night"],
    "rekt":      ["cope", "trader"],
    # Excitement / flex
    "pump":      ["wealth", "flex", "cash", "wildlife", "apex"],
    "moon":      ["wealth", "flex", "cash", "cosmic"],
    "mooning":   ["wealth", "flex", "cash", "cosmic"],
    "printed":   ["wealth", "flex", "cash"],
    "rich":      ["wealth", "flex", "cash"],
    "wagmi":     ["wealth", "flex", "prestige"],
    # Aggression / power
    "apex":      ["apex", "predator", "wildlife"],
    "king":      ["apex", "predator", "wildlife"],
    "alpha":     ["apex", "predator", "prestige"],
    "dominance": ["apex", "predator"],
    "kill":      ["apex", "predator", "wildlife"],
    # Market
    "ath":       ["wealth", "flex", "cosmic"],
    "pumping":   ["wealth", "flex"],
    "candles":   ["trader", "night"],
    "chart":     ["trader"],
    "trading":   ["trader"],
    "long":      ["trader"],
    "short":     ["trader"],
    # Subjects
    "whale":     ["wealth", "cash", "flex"],
    "degen":     ["trader", "night"],
    "ape":       ["trader", "flex"],
    "bag":       ["wealth", "cash", "bag"],
    "stack":     ["wealth", "cash"],
    "bricks":    ["cash", "wealth", "cartel"],
    "cash":      ["cash", "wealth", "money"],
    # Crypto ecosystem
    "pump.fun":  ["trader", "degen"],
    "fomo":      ["trader", "cope"],
    "sol":       ["trader"],
    "eth":       ["trader"],
    "btc":       ["trader", "wealth"],
    "bonk":      ["degen", "trader"],
    "wif":       ["degen", "trader"],
    # Food / sustenance (matches spong quiznos / sub imagery)
    "sandwich":  ["food", "sub-sandwich", "eating", "quiznos"],
    "sub":       ["food", "sub-sandwich", "quiznos"],
    "quiznos":   ["quiznos", "sub-sandwich", "food"],
    "eat":       ["food", "eating"],
    "ate":       ["food", "eating"],
    "hungry":    ["food", "eating"],
    "burger":    ["food", "eating"],
    "pizza":     ["food", "eating"],
    "coffee":    ["coffee-mug", "gm"],
    "breakfast": ["coffee-mug", "gm", "food"],
    # Political / celebrity
    "trump":     ["political", "politician", "president", "white-house"],
    "biden":     ["political", "politician", "president"],
    "president": ["political", "politician", "white-house"],
    "potus":     ["political", "president", "white-house"],
    "election":  ["political", "politician"],
    "vote":      ["political"],
    # Horror / cursed / closeup
    "scary":     ["horror", "cursed", "cursed-closeup"],
    "nightmare": ["horror", "cursed"],
    "creepy":    ["horror", "cursed"],
    "cursed":    ["cursed", "horror"],
    "closeup":   ["closeup", "extreme-closeup"],
    # Sports
    "sports":    ["sports", "arena"],
    "basketball":["sports", "arena"],
    "football":  ["sports", "arena"],
    # Media
    "tv":        ["tv-screen", "news"],
    "news":      ["news", "newsroom", "news-anchor"],
    "broadcast": ["news", "newsroom"],
    "podcast":   ["podcast", "microphone"],
    # Luxury / lifestyle
    "mansion":   ["mansion", "luxury", "wealth"],
    "yacht":     ["yacht", "luxury", "wealth"],
    "lambo":     ["lamborghini", "car", "luxury"],
    "private":   ["private-jet", "luxury"],
    "tropical":  ["tropical", "luxury", "palm-tree"],
    # Gaming / retro
    "gta":       ["retro-game", "pixelart", "videogame"],
    "game":      ["retro-game", "videogame"],
    # People composition
    "solo":      ["solo", "portrait"],
    "alone":     ["solo", "portrait"],
    "group":     ["crowd", "pair"],
    "together":  ["pair", "crowd"],
    # Typography / text-heavy
    "quote":     ["has-text", "textpost"],
    "saying":    ["has-text"],
    "caption":   ["has-text"],
    # Spong specific (canonical character poses)
    "eyes":      ["spong-eyes", "face"],
    "headphones":["headphones", "music"],
    "hat":       ["bowler-hat", "hoodie", "hat"],
    "bowler":    ["bowler-hat"],
    "hoodie":    ["hoodie"],
    "suit":      ["suit", "politician"],
    "astronaut": ["astronaut", "space", "moon"],
    "space":     ["space", "cosmic", "moon"],
    "cosmic":    ["cosmic", "space"],
    # Additional crypto-twitter cope
    "dead":      ["cope", "horror"],
    "dying":     ["cope", "horror"],
    "pain":      ["cope"],
    "loss":      ["cope"],
    "lost":      ["cope"],
}


# Words that ARE topic hints. Anything matching a library tag or a
# format trigger qualifies.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "this", "that", "be", "been", "being",
    "at", "by", "from", "as", "it", "its", "if", "but", "so", "not", "no",
    "just", "like", "now", "then", "than", "up", "down", "out", "into",
    "you", "your", "i", "my", "we", "our", "they", "them", "he", "she",
    "get", "got", "going", "gonna", "about", "all", "any", "can",
    "will", "would", "could", "should", "do", "does", "did", "have",
    "has", "had", "me", "over", "after", "before",
}

_TOKEN_RE = re.compile(r"[a-z0-9$#@]+")


def _keywords(text: str) -> list[str]:
    """Crude but effective topic extractor: lowercase, tokenize, drop
    stopwords, dedupe, expand via TOPIC_EXPANSIONS.

    For each keyword found in the tweet that appears in TOPIC_EXPANSIONS,
    add its related tags to the keyword list. So tweet "eth dumping"
    expands to ['eth', 'dumping', 'trader', 'cope', 'night', 'red'].
    """
    low = text.lower()
    raw = _TOKEN_RE.findall(low)
    out: list[str] = []
    seen: set[str] = set()
    for w in raw:
        if len(w) < 3:
            continue
        if w in _STOPWORDS:
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        # Expand to related tags
        for expansion in TOPIC_EXPANSIONS.get(w, []):
            if expansion not in seen:
                seen.add(expansion)
                out.append(expansion)
    return out


@dataclass
class ReplyMatch:
    """One suggested way to reply — either an existing ref or a format."""
    kind: str                       # "ref" | "format"
    score: int                      # higher = better
    slug_or_id: str
    description: str
    media_path: Optional[Path] = None    # filled for refs
    trigger_hits: list[str] = field(default_factory=list)


@dataclass
class ReplyPlan:
    tweet: x_fetch.TweetData
    brand: str
    keywords: list[str]
    ref_matches: list[ReplyMatch] = field(default_factory=list)
    format_matches: list[ReplyMatch] = field(default_factory=list)
    chosen_format: Optional[str] = None
    brief_folder: Optional[Path] = None
    brief_prompt: str = ""
    clipboard_ok: bool = False
    browser_opened: bool = False
    notes: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        t = self.tweet
        lines = [
            "=== reply-for ===",
            f"brand:    {self.brand}",
            f"tweet:    {t.url}",
            f"author:   @{t.author_handle} ({t.author_name})",
            f"text:     {t.text[:200]}",
            f"engage:   likes={t.favorite_count:,}  replies={t.reply_count:,}",
        ]
        if t.symbols:
            lines.append(f"symbols:  {', '.join('$' + s for s in t.symbols)}")
        if t.media_urls:
            lines.append(f"media:    {len(t.media_urls)} attached")
        lines.append(f"keywords: {', '.join(self.keywords[:10])}")
        lines.append("")

        if self.ref_matches:
            lines.append("Top library refs (attach directly, zero generation):")
            for m in self.ref_matches[:3]:
                lines.append(f"  [{m.score:>2}] {m.slug_or_id}  {m.description[:70]}")
                if m.media_path:
                    lines.append(f"       {m.media_path}")
        else:
            lines.append("Top library refs: (none matched — falling back to new-brief)")
        lines.append("")

        if self.format_matches:
            lines.append("Top format suggestions for a new piece:")
            for m in self.format_matches[:3]:
                hits = ', '.join(m.trigger_hits[:4]) if m.trigger_hits else "(brand default)"
                lines.append(f"  [{m.score:>2}] {m.slug_or_id:<30}  hits: {hits}")
        lines.append("")

        if self.chosen_format:
            lines.append(f"Generated brief for: {self.chosen_format}")
            lines.append(f"  folder:    {self.brief_folder}")
            lines.append(f"  clipboard: {'OK' if self.clipboard_ok else 'FAILED'}")
            lines.append(f"  browser:   {'opened' if self.browser_opened else 'skipped'}")
        for n in self.notes:
            lines.append(f"note: {n}")
        return "\n".join(lines)


def _score_refs(tweet: x_fetch.TweetData, keywords: list[str]) -> list[ReplyMatch]:
    """Rank library refs by keyword overlap with the tweet.

    Scoring (keyword-heavy because motion's auto-ingest tags are
    filename hashes, not semantic — we lean on prompt + notes):
      +2 per matching tag (excluding hash-like tags)
      +1 per matching word in prompt (the content description)
      +1 per matching word in notes
      +3 bonus if marked `winner`
      +1 bonus for each ticker match ($ETH, $BTC, etc.)
    """
    out: list[ReplyMatch] = []
    key_set = set(keywords)
    symbols = {s.lower() for s in tweet.symbols}
    try:
        entries = reference_lib.search()
    except (FileNotFoundError, OSError):
        return []
    for e in entries:
        # Filter out hash-ID tags (32+ hex chars) — those are auto-tags
        # from corpus ingest and don't represent semantic content.
        raw_tags = [str(t).lower() for t in e.get("tags", [])]
        semantic_tags = {
            t for t in raw_tags
            if len(t) < 24 and not all(c in "0123456789abcdef" for c in t)
        }
        score = 0
        hits: list[str] = []
        tag_hits = semantic_tags & key_set
        score += 2 * len(tag_hits)
        hits.extend(sorted(tag_hits))
        prompt_blob = str(e.get("prompt", "")).lower()
        notes_blob = str(e.get("notes", "")).lower()
        for k in key_set:
            if k in prompt_blob and k not in tag_hits:
                score += 1
                hits.append(k)
            elif k in notes_blob and k not in tag_hits and k not in hits:
                score += 1
                hits.append(k)
        # Ticker bonus
        for sym in symbols:
            if sym in prompt_blob or sym in notes_blob:
                score += 1
                hits.append(f"${sym}")
        if "winner" in raw_tags:
            score += 3
            hits.append("winner")
        if score == 0:
            continue
        # Reference index stores filename (not full path). Compose.
        media_path = e.get("path")
        if not media_path:
            fname = e.get("filename")
            if fname:
                media_path = str(settings.references_dir / fname)
        out.append(ReplyMatch(
            kind="ref",
            score=score,
            slug_or_id=str(e.get("id", "?")),
            description=(e.get("notes") or e.get("prompt") or "").strip()[:120],
            media_path=Path(media_path) if media_path else None,
            trigger_hits=hits,
        ))
    out.sort(key=lambda m: -m.score)
    return out


def _score_formats(tweet: x_fetch.TweetData) -> list[ReplyMatch]:
    """Rank formats via format_suggest, biased to the active brand.

    Rules:
      - Real trigger-hit matches outrank everything.
      - Brand-scoped formats (kilroy_* / motion_* / spong_*) get +2.
      - Brand default (reply_square) gets +3 if it's in the list.
      - If no brand format appears at all, prepend the brand default at
        score=1 so it shows up in the ranked list (non-zero score).
    """
    suggestions = format_suggest.suggest(tweet.text, top_n=8, kind="image")
    brand_default = BRAND_DEFAULT_REPLY_FORMAT.get(settings.project)
    project = settings.project
    out: list[ReplyMatch] = []
    seen_brand_scoped = False
    for s in suggestions:
        bonus = 0
        is_brand_scoped = s.slug.startswith(f"{project}_")
        if is_brand_scoped:
            bonus += 2
            seen_brand_scoped = True
        if brand_default and s.slug == brand_default:
            bonus += 3
        has_real_hits = bool(s.reasons) and s.reasons != ["default"]
        out.append(ReplyMatch(
            kind="format",
            score=(s.score + bonus) if has_real_hits else (bonus or s.score),
            slug_or_id=s.slug,
            description=f"kind={s.kind}",
            trigger_hits=s.reasons if has_real_hits else [],
        ))
    if brand_default and not seen_brand_scoped:
        # Force the brand default in so the generated brief is on-brand
        # even when the tweet text has zero recognizable triggers.
        out.insert(0, ReplyMatch(
            kind="format",
            score=1,
            slug_or_id=brand_default,
            description="kind=image (brand default)",
            trigger_hits=[],
        ))
    out.sort(key=lambda m: -m.score)
    return out


def _intent_for(tweet: x_fetch.TweetData, keywords: list[str]) -> str:
    """Turn the target tweet into a new-brief intent — anchors the
    generated piece to the reply's target."""
    topic = " ".join(keywords[:6])
    # Keep the author handle + a short excerpt so the Director can tailor.
    snippet = tweet.text.replace("\n", " ")[:180]
    return (
        f"reply art tied to tweet by @{tweet.author_handle}: \"{snippet}\" — "
        f"topic hints: {topic}"
    )


def plan(
    url_or_id: str,
    *,
    generate_brief: bool = True,
    open_browser: bool = True,
) -> Optional[ReplyPlan]:
    """Fetch the tweet, rank matches, optionally generate a brief."""
    tweet = x_fetch.fetch(url_or_id)
    if tweet is None:
        return None
    keywords = _keywords(tweet.text) + [s.lower() for s in tweet.symbols]
    keywords = list(dict.fromkeys(keywords))  # dedupe preserving order
    ref_matches = _score_refs(tweet, keywords)
    format_matches = _score_formats(tweet)

    plan = ReplyPlan(
        tweet=tweet,
        brand=settings.project,
        keywords=keywords,
        ref_matches=ref_matches,
        format_matches=format_matches,
    )

    if not generate_brief:
        return plan
    if ref_matches and ref_matches[0].score >= 5:
        # Strong library match — skip generation, operator can just attach.
        plan.notes.append(
            f"strong library match (score={ref_matches[0].score}) — "
            f"consider attaching ref {ref_matches[0].slug_or_id} directly"
        )
        return plan

    # Otherwise: generate a brief for the top-ranked format.
    chosen = format_matches[0].slug_or_id if format_matches else (
        BRAND_DEFAULT_REPLY_FORMAT.get(settings.project) or "photoreal_portrait"
    )
    intent = _intent_for(tweet, keywords)
    try:
        bundle = pipeline_mod.build(intent, kind="image", format_slug=chosen)
        system, user = prompt_engine.assemble_offline_prompt(intent, chosen)
        full = f"{system}\n\n---\n\n{user}"
        plan.chosen_format = bundle.format_slug or chosen
        plan.brief_folder = bundle.folder
        plan.brief_prompt = full
        plan.clipboard_ok = _clipboard.copy(full)
        if open_browser:
            try:
                webbrowser.open(GROK_IMAGINE_URL)
                plan.browser_opened = True
            except webbrowser.Error:
                pass
    except ValueError as exc:
        plan.notes.append(f"brief generation failed: {exc}")
    return plan
