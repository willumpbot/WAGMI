"""twitterapi.io client — paid-but-cheap X data source.

$0.15 per 1,000 tweets. Pay-as-you-go, no monthly fees, $0.10 free
credit at signup. Replaces the Playwright + BlueStacks paths for the
watchlist poller.

API reference: https://docs.twitterapi.io
Base URL:       https://api.twitterapi.io
Auth:           X-API-Key header (HTTP header, NOT a query param)
Key env var:    MEMEGINE_TWITTERAPI_KEY

Only two endpoints are needed for the watcher:
    GET /twitter/user/last_tweets?userName=<handle>
        → returns up to 20 recent tweets (newest first)
    GET /twitter/tweet/by_id?tweetId=<id>
        → single tweet detail (we already have syndication for this
          but keep as fallback when syndication fails)

This client normalizes responses into the TweetData shape memegine's
pipeline already understands (ops_db.tweet_upsert +
telegram_ops.push_new_tweets are both zero-touch).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from . import x_fetch


BASE_URL = "https://api.twitterapi.io"
KEY_ENV_VAR = "MEMEGINE_TWITTERAPI_KEY"


class TwitterapiError(RuntimeError):
    """Any non-success HTTP response or config error."""


@dataclass
class RawResponse:
    status: int
    ok: bool
    payload: dict
    error: str = ""


def _api_key() -> str:
    key = os.environ.get(KEY_ENV_VAR, "").strip()
    if not key:
        raise TwitterapiError(
            f"{KEY_ENV_VAR} is not set in .env — "
            "sign up at https://twitterapi.io and paste your key into .env"
        )
    return key


def _http_get(path: str, params: dict) -> RawResponse:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE_URL}{path}?{qs}" if qs else f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "X-API-Key": _api_key(),
            "Accept": "application/json",
            "User-Agent": "memegine/0.1 (+https://github.com/anthropics/claude-code)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw": body}
            return RawResponse(status=resp.status, ok=True, payload=payload)
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body) if err_body else {}
        except (json.JSONDecodeError, OSError):
            err_json = {}
        return RawResponse(
            status=exc.code, ok=False, payload=err_json,
            error=f"HTTP {exc.code}: {err_json.get('message') or err_body[:200]}",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return RawResponse(status=0, ok=False, payload={}, error=f"network: {exc}")


# ---- timeline ----

def user_last_tweets(handle: str, *, limit: int = 20) -> list[x_fetch.TweetData]:
    """Fetch the newest N tweets from @handle. Returns normalized TweetData list.

    Paginates if the API returns a cursor (up to `limit` total).
    """
    handle = handle.lstrip("@").strip().lower()
    if not handle:
        return []
    collected: list[dict] = []
    cursor: Optional[str] = None
    while len(collected) < limit:
        resp = _http_get(
            "/twitter/user/last_tweets",
            {"userName": handle, "cursor": cursor},
        )
        if not resp.ok:
            # 429 = rate-limited. Caller should back off.
            raise TwitterapiError(
                f"user_last_tweets({handle}) failed: {resp.error or resp.payload}"
            )
        tweets = resp.payload.get("tweets") or resp.payload.get("data") or []
        if not tweets:
            break
        collected.extend(tweets)
        cursor = resp.payload.get("next_cursor") or resp.payload.get("nextCursor")
        if not cursor:
            break
    return [_normalize(t) for t in collected[:limit] if t]


def tweet_by_id(tweet_id: str) -> Optional[x_fetch.TweetData]:
    """Fetch a single tweet. Use as fallback when syndication fails."""
    resp = _http_get("/twitter/tweet/by_id", {"tweetId": tweet_id})
    if not resp.ok:
        return None
    data = resp.payload.get("tweet") or resp.payload.get("data")
    if not data:
        return None
    return _normalize(data)


# ---- normalization ----

def _normalize(raw: dict) -> Optional[x_fetch.TweetData]:
    """Turn a twitterapi.io tweet record into memegine's TweetData shape."""
    if not isinstance(raw, dict):
        return None
    tid = str(raw.get("id") or raw.get("id_str") or raw.get("tweetId") or "")
    if not tid:
        return None
    text = str(raw.get("text") or raw.get("full_text") or "").strip()
    user = raw.get("user") or raw.get("author") or {}
    handle = str(
        user.get("userName") or user.get("screen_name") or user.get("handle") or ""
    ).strip().lstrip("@").lower()
    name = str(user.get("name") or "").strip()
    created = str(raw.get("createdAt") or raw.get("created_at") or "").strip()
    from ._time import now_iso as _now_iso
    entities = raw.get("entities") or {}
    hashtags = [
        h.get("text", "") for h in (entities.get("hashtags") or [])
        if isinstance(h, dict) and h.get("text")
    ]
    mentions = [
        (m.get("screen_name") or m.get("username") or "")
        for m in (entities.get("user_mentions") or entities.get("mentions") or [])
        if isinstance(m, dict)
    ]
    symbols = [
        s.get("text", "") for s in (entities.get("symbols") or [])
        if isinstance(s, dict) and s.get("text")
    ]
    urls = [
        (u.get("expanded_url") or u.get("url") or "")
        for u in (entities.get("urls") or [])
        if isinstance(u, dict)
    ]
    media_urls: list[str] = []
    for m in (entities.get("media") or raw.get("media") or []):
        if isinstance(m, dict):
            mu = m.get("media_url_https") or m.get("url")
            if mu:
                media_urls.append(mu)

    return x_fetch.TweetData(
        id=tid,
        text=text,
        author_handle=handle,
        author_name=name,
        created_at=created,
        url=f"https://x.com/{handle}/status/{tid}" if handle else f"https://x.com/i/status/{tid}",
        favorite_count=int(raw.get("likeCount") or raw.get("favorite_count") or 0),
        reply_count=int(raw.get("replyCount") or raw.get("reply_count") or 0),
        hashtags=[h for h in hashtags if h],
        mentions=[m for m in mentions if m],
        symbols=[s for s in symbols if s],
        urls=[u for u in urls if u],
        media_urls=media_urls,
        lang=str(raw.get("lang") or "en"),
        fetched_at=_now_iso(),
    )


def probe() -> dict:
    """One-call health check. Returns {ok, status, msg}."""
    try:
        tweets = user_last_tweets("jack", limit=1)
        if tweets:
            return {"ok": True, "status": 200,
                    "msg": f"OK — fetched @jack tweet id={tweets[0].id}"}
        return {"ok": False, "status": 200, "msg": "empty response"}
    except TwitterapiError as exc:
        return {"ok": False, "status": 0, "msg": str(exc)}
