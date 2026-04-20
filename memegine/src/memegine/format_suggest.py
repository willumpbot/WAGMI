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
    # $MOTION-specific formats (tokens that signal the brand context)
    "motion_film_still_serif": [
        "motion", "$motion", "film still", "cinematic still", "movie still",
        "scarface", "dark knight", "war dogs", "american psycho", "casino",
        "sopranos", "goodfellas", "enter the dragon",
    ],
    "motion_wildlife_doc_grain": [
        "lion", "shark", "hyena", "wolf", "predator", "wildlife",
        "savanna", "apex predator", "nature doc",
    ],
    "motion_vertical_letterbox": [
        "letterbox", "letterboxed", "vertical letterbox", "cinematic crop",
        "black bars", "9:16 cinematic",
    ],
    "motion_collage_6panel_bw": [
        "collage", "6 panel", "six panel", "anthology", "montage grid",
        "multi-panel", "3x2 grid",
    ],
    "motion_cartel_wealth_striped": [
        "cartel cash", "vacuum sealed", "cash brick", "money brick",
        "shrink wrapped bills", "money stacks", "bill counter", "bill bricks",
    ],
    "motion_archival_press_celebrity": [
        "press photo", "archival celebrity", "press flash", "80s photo",
        "90s archive", "young trump", "tupac", "archival",
    ],
    "motion_hypercar_cosmic": [
        "hypercar", "bugatti", "cosmic", "nebula", "galactic",
        "galaxy car", "starfield",
    ],
    "motion_comedy_emoji": [
        "meme shitpost", "rooster", "absurd meme", "comedy motion",
        "shitpost piece", "absurd subject",
    ],
    # Kilroy formats — triggered by Kilroy-specific language.
    "kilroy_tags_news_photo": [
        "kilroy", "kilroy was here", "mr chad", "tag a news photo",
        "graffiti on a photo", "chalk tag", "gi graffiti",
        "wwii graffiti", "archival with tag",
    ],
    "kilroy_tags_crypto_moment": [
        "kilroy trading", "kilroy terminal", "tag a terminal",
        "graffiti on monitor", "kilroy chart", "kilroy at 3am",
        "sharpie on monitor",
    ],
    "kilroy_wheat_paste_poster": [
        "wheat paste", "wheat-paste", "street poster", "poster on wall",
        "peeling poster", "missing person poster", "kilroy poster",
    ],
    # Kilroy motion-tier formats — bring $MOTION-grade craft to Kilroy.
    "kilroy_cinema_still_tag": [
        "kilroy cinema still", "kilroy film still", "kilroy heat",
        "kilroy collateral", "kilroy godfather", "kilroy blade runner",
        "kilroy motion-tier", "kilroy cinema", "cinematic kilroy",
        "kilroy american psycho", "kilroy dark knight", "kilroy casino",
    ],
    "kilroy_vhs_rip_tag": [
        "kilroy vhs", "kilroy broadcast", "kilroy 480p",
        "kilroy cnbc", "kilroy news anchor", "kilroy tape rip",
        "kilroy on a crt", "kilroy chyron", "80s broadcast kilroy",
    ],
    "kilroy_tabloid_cover_tag": [
        "kilroy tabloid", "kilroy cover", "kilroy magazine",
        "kilroy enquirer", "kilroy post cover", "kilroy time cover",
        "kilroy wired", "kilroy vanity fair", "kilroy newsstand",
    ],
    "kilroy_polaroid_stack_tag": [
        "kilroy polaroid", "kilroy sx-70", "kilroy sx70",
        "kilroy instant photo", "polaroid kilroy", "kilroy on polaroid",
    ],
    # Reply-shaped squares (1:1, reply-guy volume)
    "kilroy_reply_square": [
        "kilroy reply", "kilroy quick", "kilroy square", "reply image kilroy",
        "thumbnail kilroy", "quote tweet kilroy", "qt bait kilroy",
    ],
    "motion_reply_square": [
        "motion reply", "motion quick", "motion square", "reply image motion",
        "thumbnail motion", "quote tweet motion", "$motion reply",
    ],
    "spong_reply_square": [
        "spong reply", "spong quick", "spong square", "spongmonkey reply",
        "thumbnail spong", "quote tweet spong", "$spong reply",
    ],
    # Spong (spongmonkeys lineage)
    "spong_solo_scene": [
        "spong", "spongmonkey", "spongmonkeys", "we like the moon",
        "rathergood", "joel veitch", "googly eyes", "cursed 2003",
        "cursed meme", "flash animation still",
    ],
    "spong_quiznos_ad_parody": [
        "quiznos", "we love the subs", "super bowl 2004", "cursed ad",
        "broadcast tv parody", "cursed commercial", "quiznos parody",
    ],
    "spong_duet_trio": [
        "spong duet", "spong trio", "multiple spongmonkeys",
        "spongmonkeys in unison", "chorus of spong",
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
