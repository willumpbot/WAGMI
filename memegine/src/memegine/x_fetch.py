"""X (Twitter) tweet fetcher — API-free, zero dependencies.

Uses the public syndication endpoint (cdn.syndication.twimg.com) —
the same endpoint X's own embed widget uses. No bearer token, no rate
limits (beyond what a browser would see), no paid tier. Works as of
April 2026.

Token computation mirrors the formula used by `react-tweet` and the
X embed widget itself:
    token = base36((id / 1e15) * pi).replace('0+|.', '')

On success, returns a `TweetData` with text, author, engagement,
entities, and media URLs. On failure (deleted / age-restricted /
endpoint change) returns None with an error note the operator can act
on.

Tweets are cached to data/projects/<active>/feed/tweets.jsonl so a
second fetch is instant and the operator can replay recent tweets
offline.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import settings


SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
CACHE_SUBDIR = "feed"
CACHE_FILE = "tweets.jsonl"

_TWEET_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[^/]+/status/(\d+)"
)
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


@dataclass
class TweetData:
    """Normalized tweet for downstream matchers / brief generators."""
    id: str
    text: str
    author_handle: str          # without leading @
    author_name: str
    created_at: str             # ISO 8601
    url: str                    # canonical x.com URL
    favorite_count: int = 0
    reply_count: int = 0
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)   # $TICKER-style
    urls: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    author_profile_image_url: str = ""
    lang: str = "en"
    fetched_at: str = ""

    def as_short(self) -> str:
        """One-line summary for tweet lists."""
        ts = self.created_at[:19] if self.created_at else "????"
        body = self.text.replace("\n", " ")[:120]
        return f"[{ts}] @{self.author_handle}: {body}"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "author_handle": self.author_handle,
            "author_name": self.author_name,
            "created_at": self.created_at,
            "url": self.url,
            "favorite_count": self.favorite_count,
            "reply_count": self.reply_count,
            "hashtags": self.hashtags,
            "mentions": self.mentions,
            "symbols": self.symbols,
            "urls": self.urls,
            "media_urls": self.media_urls,
            "author_profile_image_url": self.author_profile_image_url,
            "lang": self.lang,
            "fetched_at": self.fetched_at,
        }


def parse_tweet_id(s: str) -> Optional[str]:
    """Accept a tweet URL, x.com status URL, or raw ID. Return the ID or None."""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return s
    m = _TWEET_URL_RE.search(s)
    if m:
        return m.group(1)
    return None


def _compute_token(tweet_id: str) -> str:
    """Compute the syndication token (see module docstring)."""
    n = (float(tweet_id) / 1e15) * math.pi
    # Convert to base-36 string with a long enough fractional part.
    whole = int(n)
    frac = n - whole
    if whole == 0:
        ws = "0"
    else:
        ws_chars: list[str] = []
        while whole:
            whole, r = divmod(whole, 36)
            ws_chars.append(_BASE36[r])
        ws = "".join(reversed(ws_chars))
    fs_chars: list[str] = []
    for _ in range(15):
        frac *= 36
        d = int(frac)
        fs_chars.append(_BASE36[d])
        frac -= d
    raw = ws + "." + "".join(fs_chars)
    # Strip zeros and dots to match the reference formula.
    return re.sub(r"(0+|\.)", "", raw)


def _http_get_json(url: str, *, timeout: float = 10.0) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            ValueError, ConnectionError):
        return None


def _parse_response(raw: dict, tweet_id: str) -> Optional[TweetData]:
    """Convert the syndication response to TweetData."""
    if not isinstance(raw, dict) or raw.get("__typename") != "Tweet":
        return None
    user = raw.get("user") or {}
    author_handle = str(user.get("screen_name", "")).strip().lstrip("@")
    author_name = str(user.get("name", "")).strip()
    # Upgrade _normal (48px) → _400x400 for higher-res profile pic.
    pfp = str(user.get("profile_image_url_https") or "").strip()
    if pfp:
        pfp = re.sub(r"_normal\.", "_400x400.", pfp)
    text = str(raw.get("text", "")).strip()
    created_at = _normalize_timestamp(raw.get("created_at", ""))
    entities = raw.get("entities") or {}
    hashtags = [h.get("text", "") for h in (entities.get("hashtags") or []) if h.get("text")]
    mentions = [m.get("screen_name", "") for m in (entities.get("user_mentions") or []) if m.get("screen_name")]
    symbols = [s.get("text", "") for s in (entities.get("symbols") or []) if s.get("text")]
    urls = [u.get("expanded_url") or u.get("url") for u in (entities.get("urls") or []) if (u.get("expanded_url") or u.get("url"))]
    # Media entities can live in entities.media OR in a separate `photos`/`video` field.
    media_urls: list[str] = []
    for m in (entities.get("media") or []):
        if m.get("media_url_https"):
            media_urls.append(m["media_url_https"])
    for p in (raw.get("photos") or []):
        if p.get("url"):
            media_urls.append(p["url"])
    if isinstance(raw.get("video"), dict):
        for v in (raw["video"].get("variants") or []):
            if v.get("src"):
                media_urls.append(v["src"])

    url = f"https://x.com/{author_handle}/status/{tweet_id}" if author_handle else f"https://x.com/i/status/{tweet_id}"
    return TweetData(
        id=tweet_id,
        text=text,
        author_handle=author_handle,
        author_name=author_name,
        created_at=created_at,
        url=url,
        favorite_count=int(raw.get("favorite_count", 0) or 0),
        reply_count=int(raw.get("conversation_count", 0) or 0),
        hashtags=hashtags,
        mentions=mentions,
        symbols=symbols,
        urls=urls,
        media_urls=media_urls,
        author_profile_image_url=pfp,
        lang=str(raw.get("lang", "en") or "en"),
        fetched_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    )


def _normalize_timestamp(ts: str) -> str:
    """Convert X's timestamp variants to ISO 8601. Best-effort."""
    if not ts:
        return ""
    try:
        # Modern syndication responses use ISO 8601 with "Z".
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return t.replace(microsecond=0).isoformat()
    except ValueError:
        pass
    try:
        # Legacy: "Wed Oct 10 20:19:24 +0000 2018"
        t = dt.datetime.strptime(ts, "%a %b %d %H:%M:%S %z %Y")
        return t.replace(microsecond=0).isoformat()
    except ValueError:
        return ts  # give up — keep the raw string, downstream can cope.


def _cache_path() -> Path:
    return settings.data_dir / CACHE_SUBDIR / CACHE_FILE


def _append_cache(td: TweetData) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(td.as_dict(), ensure_ascii=False) + "\n")
    except OSError:
        pass  # cache is best-effort


def fetch(url_or_id: str, *, use_cache: bool = True) -> Optional[TweetData]:
    """Fetch a single tweet by URL or ID.

    When use_cache=True, check the local feed cache first — useful for
    replaying tweets the operator already saw without hitting the wire.
    """
    tweet_id = parse_tweet_id(url_or_id)
    if not tweet_id:
        return None

    if use_cache:
        cached = _read_from_cache(tweet_id)
        if cached:
            return cached

    token = _compute_token(tweet_id)
    qs = urllib.parse.urlencode({"id": tweet_id, "token": token, "lang": "en"})
    raw = _http_get_json(f"{SYNDICATION_URL}?{qs}")
    if not raw:
        return None
    td = _parse_response(raw, tweet_id)
    if td:
        _append_cache(td)
    return td


def _read_from_cache(tweet_id: str) -> Optional[TweetData]:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("id") == tweet_id:
                    return TweetData(
                        id=obj["id"],
                        text=obj.get("text", ""),
                        author_handle=obj.get("author_handle", ""),
                        author_name=obj.get("author_name", ""),
                        created_at=obj.get("created_at", ""),
                        url=obj.get("url", ""),
                        favorite_count=obj.get("favorite_count", 0),
                        reply_count=obj.get("reply_count", 0),
                        hashtags=obj.get("hashtags", []),
                        mentions=obj.get("mentions", []),
                        symbols=obj.get("symbols", []),
                        urls=obj.get("urls", []),
                        media_urls=obj.get("media_urls", []),
                        author_profile_image_url=obj.get("author_profile_image_url", ""),
                        lang=obj.get("lang", "en"),
                        fetched_at=obj.get("fetched_at", ""),
                    )
    except OSError:
        pass
    return None


def recent(limit: int = 20) -> list[TweetData]:
    """Return the N most recently cached tweets (newest last in file)."""
    p = _cache_path()
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out: list[TweetData] = []
    for line in lines[-limit:]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(TweetData(
            id=obj["id"],
            text=obj.get("text", ""),
            author_handle=obj.get("author_handle", ""),
            author_name=obj.get("author_name", ""),
            created_at=obj.get("created_at", ""),
            url=obj.get("url", ""),
            favorite_count=obj.get("favorite_count", 0),
            reply_count=obj.get("reply_count", 0),
            hashtags=obj.get("hashtags", []),
            mentions=obj.get("mentions", []),
            symbols=obj.get("symbols", []),
            urls=obj.get("urls", []),
            media_urls=obj.get("media_urls", []),
            lang=obj.get("lang", "en"),
            fetched_at=obj.get("fetched_at", ""),
        ))
    return out
