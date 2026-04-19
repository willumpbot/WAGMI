"""Format suggester — intent string → ranked format slugs.

Keyword heuristics, offline-only. This exists so a Telegram user can say
/piece "trader dumping at 3am" and the bot can auto-pick photoreal_portrait
or reaction_shot_meme without the operator naming a format slug each time.

Ranking is transparent: each format has a list of keyword triggers. Score
is sum of trigger matches, with kind-preference as a tie-break.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import prompt_engine


# Hand-curated trigger lists. Tuned for the kind of content an X/crypto/meme
# operator posts: reactions, portraits, "then vs now", cope charts, lore.
# Keep entries short and lowercase. Order doesn't matter.
FORMAT_TRIGGERS: dict[str, list[str]] = {
    "photoreal_portrait": [
        "portrait", "person", "trader", "face", "headshot", "character",
        "subject", "single subject", "him", "her", "them at",
    ],
    "meme_two_panel": [
        "two panel", "two-panel", "setup payoff", "setup-payoff", "before after",
        "top bottom", "stacked meme", "meme",
    ],
    "drake_yes_no": [
        "drake", "prefer", "rejecting", "approving", "vs", "instead of",
    ],
    "photoreal_scene_motion": [
        "short video", "short clip", "quick clip", "animate", "scene with motion",
        "motion", "push in on", "movement in", "camera move", "img2vid",
    ],
    "lore_drop": [
        "lore", "cryptic", "ominous", "mysterious", "cold open",
        "universe", "mythology", "backstory",
    ],
    "cope_chart": [
        "chart", "graph", "cope", "number go", "bloomberg", "terminal",
        "line chart", "analytics", "analysis",
    ],
    "npc_wojak_row": [
        "npc", "wojak", "consensus", "hive mind", "everyone says", "groupthink",
        "enlightened", "contrarian", "npcs",
    ],
    "split_screen_then_now": [
        "then now", "then vs now", "expectation reality", "expectation vs reality",
        "before vs after", "split screen", "split-screen", "left right",
    ],
    "photoreal_product_shot": [
        "product", "tabletop", "object", "item", "symbol", "magazine shot",
        "studio still", "hero object",
    ],
    "photoreal_street_scene": [
        "street", "candid", "city", "nyc", "tokyo", "shibuya", "sidewalk",
        "passerby", "street photo", "3am", "night out",
    ],
    "reaction_shot_meme": [
        "reaction", "reacting", "expression", "face meme", "side eye",
        "stunned", "confused face", "meme reaction",
    ],
    "fake_news_headline": [
        "headline", "news", "breaking", "article", "broadsheet", "fake news",
        "nyt", "bloomberg article", "bbg",
    ],
    "video_single_take_reaction": [
        "single take", "reaction video", "5 seconds of", "reading",
        "slow reaction", "emotional read", "6-second",
    ],
    "video_kenburns_still": [
        "ken burns", "kenburns", "slow push", "zoom on", "still to video",
        "still push", "photo to video",
    ],
    "photoreal_self_avatar": [
        "self avatar", "self-avatar", "recurring character", "mascot",
        "protagonist", "my avatar", "kilroy", "the operator", "market-anon",
        "same character", "consistent face",
    ],
    "screenshot_terminal": [
        "terminal", "bloomberg", "tradingview", "order book", "exchange ui",
        "hyperliquid", "binance", "dydx", "screenshot terminal", "screen",
        "perps", "positions page",
    ],
    "ticker_scroll_overlay": [
        "chyron", "lower third", "ticker", "news overlay", "breaking news bar",
        "scroll overlay", "wire service", "news crawl",
    ],
    "found_footage_still": [
        "found footage", "archival", "documentary still", "90s doc",
        "vhs still", "tape look", "historical record", "handheld archive",
    ],
    "zine_pullquote": [
        "pullquote", "pull quote", "zine", "magazine layout", "editorial layout",
        "headline piece", "photo plus quote",
    ],
    "vhs_ad_spoof": [
        "infomercial", "vhs ad", "commercial still", "800 number",
        "call now", "19.99", "tv commercial", "rec room ad",
    ],
    "screenshot_dm": [
        "dm thread", "dms", "text thread", "imessage", "telegram dm",
        "text messages", "message exchange", "chat screenshot",
    ],
    "polaroid_stack": [
        "polaroid", "polaroids", "stack of photos", "instant camera",
        "handwritten date", "photo stack",
    ],
    "movie_still_quote": [
        "movie still", "film still", "cinema frame", "subtitle quote",
        "letterboxed", "anamorphic still",
    ],
    "breaking_news_banner": [
        "breaking news", "news banner", "broadcast still", "news chyron",
        "breaking:", "field reporter",
    ],
    "document_scan": [
        "document", "legal notice", "memo", "bank statement",
        "medical form", "lease", "official document", "fake document",
    ],
    "tombstone_meme": [
        "tombstone", "graveyard", "rip", "in memoriam", "gravestone",
        "epitaph",
    ],
    "whiteboard_diagram": [
        "whiteboard", "diagram", "galaxy brain", "explainer diagram",
        "big brain chart", "arrows and boxes",
    ],
    "podcast_clip_still": [
        "podcast clip", "podcast still", "talking head", "podcast subtitle",
        "guy said", "clip said",
    ],
    "magazine_cover": [
        "magazine cover", "cover story", "gq cover", "time cover",
        "wired cover", "masthead",
    ],
    "receipt_photo": [
        "receipt", "itemized", "thermal paper", "bodega receipt",
        "line items",
    ],
    "billboard_roadside": [
        "billboard", "roadside billboard", "highway billboard", "big ad",
        "outdoor advertising",
    ],
}

# Strong intent cues for the "kind" (image vs video) when operator hasn't said.
VIDEO_WORDS = (
    "video", "clip", "motion", "animate", "animated", "animating",
    "scene with motion",
    "push-in", "push in", "pull-out", "pull out", "ken burns", "kenburns",
    "second video", "seconds of", "shot that moves", "reel", "tiktok",
    "camera move", "camera moves", "img2vid",
)
IMAGE_WORDS = (
    "image", "photo", "photograph", "portrait", "headshot",
    "meme image", "chart", "headline", "screenshot",
)


@dataclass
class FormatSuggestion:
    slug: str
    kind: str
    score: int
    reasons: list[str]


def _tokens(text: str) -> str:
    # light normalization: lowercase, collapse whitespace, strip punctuation.
    return re.sub(r"\s+", " ", text.lower()).strip()


def _match_hits(text: str, triggers: list[str]) -> list[str]:
    low = _tokens(text)
    out = []
    for trig in triggers:
        if trig in low:
            out.append(trig)
    return out


def infer_kind(intent: str) -> str:
    """Return 'video' if intent smells like motion work, else 'image'.

    Used when operator says /piece <intent> without --kind.
    """
    low = _tokens(intent)
    v = sum(1 for w in VIDEO_WORDS if w in low)
    i = sum(1 for w in IMAGE_WORDS if w in low)
    if v > i:
        return "video"
    if i > v:
        return "image"
    # tiebreak: default to image; photos outnumber video pieces in the rhythm.
    return "image"


def suggest(
    intent: str,
    *,
    top_n: int = 3,
    kind: str | None = None,
    formats_path: Path | None = None,
) -> list[FormatSuggestion]:
    """Return the top-N format slugs ranked for this intent.

    kind: if provided, filters out formats whose .kind doesn't match.
    """
    formats = prompt_engine.load_formats(formats_path or prompt_engine.FORMATS_PATH)
    kinds = {f.slug: f.kind for f in formats}

    scored: list[FormatSuggestion] = []
    any_hits = False
    for slug, triggers in FORMAT_TRIGGERS.items():
        if slug not in kinds:
            continue
        if kind and kinds[slug] != kind:
            continue
        hits = _match_hits(intent, triggers)
        if hits:
            any_hits = True
        scored.append(
            FormatSuggestion(
                slug=slug,
                kind=kinds[slug],
                score=len(hits),
                reasons=hits,
            )
        )

    # If operator didn't specify kind, bias by inferred kind as a tie-break.
    # We multiply the trigger score by 2 and add 1 for kind alignment so real
    # trigger hits always outrank pure kind-alignment.
    if kind is None:
        inferred = infer_kind(intent)
        for s in scored:
            s.score = s.score * 2 + (1 if s.kind == inferred else 0)

    scored.sort(key=lambda s: (-s.score, s.slug))
    # If at least one format matched a real trigger, return the top of those.
    # Otherwise fall back to curated defaults (kind-alignment alone isn't a
    # real "suggestion" — it's noise).
    if any_hits:
        return [s for s in scored if s.score > 0][:top_n]
    # Defaults: photoreal_portrait for image, video_kenburns_still for video.
    default_kind = kind or infer_kind(intent)
    fallback_slugs = (
        ["video_kenburns_still", "photoreal_scene_motion", "video_single_take_reaction"]
        if default_kind == "video"
        else ["photoreal_portrait", "reaction_shot_meme", "lore_drop"]
    )
    return [
        FormatSuggestion(slug=sl, kind=kinds.get(sl, default_kind), score=0, reasons=["default"])
        for sl in fallback_slugs
        if sl in kinds
    ][:top_n]


def best(intent: str, *, kind: str | None = None, formats_path: Path | None = None) -> str:
    """Return the single best format slug for this intent."""
    top = suggest(intent, top_n=1, kind=kind, formats_path=formats_path)
    return top[0].slug if top else "photoreal_portrait"
