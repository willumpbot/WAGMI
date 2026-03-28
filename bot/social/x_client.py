"""
X/Twitter API v2 client for WAGMI social automation.

Wraps tweepy with:
  - OAuth 1.0a auth for posting (User Context)
  - OAuth 2.0 Bearer for reading metrics
  - Rate limiting and retry logic
  - Graceful degradation (returns None on failure, never crashes)

Required env vars: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
Optional: X_BEARER_TOKEN (for elevated read access)
"""

import logging
import os
import time
from typing import Optional, List, Dict, Any

logger = logging.getLogger("bot.social.x_client")

# Track API usage
_total_posts = 0
_total_reads = 0
_total_failures = 0


def _get_client():
    """Lazy-init the tweepy Client (v2 API)."""
    try:
        import tweepy
    except ImportError:
        logger.warning("tweepy not installed (pip install tweepy)")
        return None

    api_key = os.getenv("X_API_KEY", "")
    api_secret = os.getenv("X_API_SECRET", "")
    access_token = os.getenv("X_ACCESS_TOKEN", "")
    access_secret = os.getenv("X_ACCESS_SECRET", "")
    bearer_token = os.getenv("X_BEARER_TOKEN", "")

    if not all([api_key, api_secret, access_token, access_secret]):
        logger.warning(
            "X API credentials not fully set. "
            "Need: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET"
        )
        return None

    try:
        client = tweepy.Client(
            bearer_token=bearer_token or None,
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
            wait_on_rate_limit=True,
        )
        logger.info("X API client initialized successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to init X API client: {e}")
        return None


def _get_v1_api():
    """Get tweepy v1.1 API for media uploads (v2 doesn't support media upload yet)."""
    try:
        import tweepy
    except ImportError:
        return None

    api_key = os.getenv("X_API_KEY", "")
    api_secret = os.getenv("X_API_SECRET", "")
    access_token = os.getenv("X_ACCESS_TOKEN", "")
    access_secret = os.getenv("X_ACCESS_SECRET", "")

    if not all([api_key, api_secret, access_token, access_secret]):
        return None

    try:
        auth = tweepy.OAuth1UserHandler(
            api_key, api_secret, access_token, access_secret
        )
        return tweepy.API(auth)
    except Exception as e:
        logger.error(f"Failed to init v1 API: {e}")
        return None


# Singleton clients
_client = None
_v1_api = None


def get_client():
    """Get or create the tweepy v2 Client singleton."""
    global _client
    if _client is None:
        _client = _get_client()
    return _client


def get_v1_api():
    """Get or create the tweepy v1.1 API singleton (for media uploads)."""
    global _v1_api
    if _v1_api is None:
        _v1_api = _get_v1_api()
    return _v1_api


def reset_client():
    """Reset client singletons (useful for testing or credential rotation)."""
    global _client, _v1_api
    _client = None
    _v1_api = None


def _retry(func, max_retries: int = 3, base_delay: float = 2.0):
    """Execute with exponential backoff retry."""
    global _total_failures
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries:
                _total_failures += 1
                logger.error(f"X API call failed after {max_retries} retries: {e}")
                return None
            delay = base_delay * (2 ** attempt)
            logger.warning(f"X API call failed (attempt {attempt + 1}), retrying in {delay}s: {e}")
            time.sleep(delay)


def post_tweet(
    text: str,
    reply_to: Optional[str] = None,
    media_paths: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Post a tweet.

    Args:
        text: Tweet text (max 280 chars, or 25000 for Premium)
        reply_to: Tweet ID to reply to (for threads)
        media_paths: List of local file paths to attach as media
        dry_run: If True, log but don't actually post

    Returns:
        Dict with tweet_id and text, or None on failure
    """
    global _total_posts

    if not text or not text.strip():
        logger.warning("Empty tweet text, skipping")
        return None

    if dry_run:
        logger.info(f"[DRY RUN] Would post tweet: {text[:100]}...")
        return {"tweet_id": "dry_run", "text": text}

    client = get_client()
    if client is None:
        logger.warning("X client not available, skipping post")
        return None

    # Upload media if provided
    media_ids = None
    if media_paths:
        media_ids = _upload_media(media_paths)

    kwargs = {}
    if reply_to:
        kwargs["in_reply_to_tweet_id"] = reply_to
    if media_ids:
        kwargs["media_ids"] = media_ids

    def _do_post():
        return client.create_tweet(text=text, **kwargs)

    response = _retry(_do_post)
    if response and response.data:
        _total_posts += 1
        tweet_id = response.data["id"]
        logger.info(f"Posted tweet {tweet_id}: {text[:80]}...")
        return {"tweet_id": tweet_id, "text": text}

    return None


def post_thread(
    tweets: List[str],
    media_per_tweet: Optional[Dict[int, List[str]]] = None,
    dry_run: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """
    Post a thread (series of replies).

    Args:
        tweets: List of tweet texts in order
        media_per_tweet: Optional dict mapping tweet index to media paths
        dry_run: If True, log but don't actually post

    Returns:
        List of posted tweet dicts, or None on failure
    """
    if not tweets:
        return None

    media_per_tweet = media_per_tweet or {}
    results = []
    reply_to = None

    for i, text in enumerate(tweets):
        media = media_per_tweet.get(i)
        result = post_tweet(
            text=text,
            reply_to=reply_to,
            media_paths=media,
            dry_run=dry_run,
        )
        if result is None:
            logger.error(f"Thread broken at tweet {i + 1}/{len(tweets)}")
            break
        results.append(result)
        reply_to = result["tweet_id"]

    return results if results else None


def _upload_media(paths: List[str]) -> Optional[List[str]]:
    """Upload media files and return media IDs."""
    api = get_v1_api()
    if api is None:
        logger.warning("v1 API not available for media upload")
        return None

    media_ids = []
    for path in paths:
        if not os.path.exists(path):
            logger.warning(f"Media file not found: {path}")
            continue
        try:
            media = api.media_upload(filename=path)
            media_ids.append(str(media.media_id))
            logger.info(f"Uploaded media: {path} -> {media.media_id}")
        except Exception as e:
            logger.error(f"Failed to upload media {path}: {e}")

    return media_ids if media_ids else None


def get_tweet_metrics(tweet_id: str) -> Optional[Dict[str, Any]]:
    """
    Get public metrics for a tweet.

    Returns dict with: impressions, likes, replies, reposts, bookmarks, quotes
    """
    global _total_reads
    client = get_client()
    if client is None:
        return None

    def _do_read():
        return client.get_tweet(
            tweet_id,
            tweet_fields=["public_metrics", "created_at", "text"],
        )

    response = _retry(_do_read)
    if response and response.data:
        _total_reads += 1
        metrics = response.data.get("public_metrics", {})
        return {
            "tweet_id": tweet_id,
            "text": response.data.get("text", ""),
            "created_at": str(response.data.get("created_at", "")),
            "impressions": metrics.get("impression_count", 0),
            "likes": metrics.get("like_count", 0),
            "replies": metrics.get("reply_count", 0),
            "reposts": metrics.get("retweet_count", 0),
            "quotes": metrics.get("quote_count", 0),
            "bookmarks": metrics.get("bookmark_count", 0),
        }

    return None


def get_user_metrics() -> Optional[Dict[str, Any]]:
    """Get own account metrics (followers, following, tweet count)."""
    global _total_reads
    client = get_client()
    if client is None:
        return None

    def _do_read():
        return client.get_me(user_fields=["public_metrics", "created_at", "description"])

    response = _retry(_do_read)
    if response and response.data:
        _total_reads += 1
        metrics = response.data.get("public_metrics", {})
        return {
            "username": response.data.get("username", ""),
            "name": response.data.get("name", ""),
            "description": response.data.get("description", ""),
            "followers": metrics.get("followers_count", 0),
            "following": metrics.get("following_count", 0),
            "tweet_count": metrics.get("tweet_count", 0),
            "created_at": str(response.data.get("created_at", "")),
        }

    return None


def get_recent_tweets(max_results: int = 20) -> Optional[List[Dict[str, Any]]]:
    """Get own recent tweets with metrics."""
    client = get_client()
    if client is None:
        return None

    # First get own user ID
    me = get_user_metrics()
    if not me:
        return None

    def _do_read():
        return client.get_users_tweets(
            id=client.get_me().data.id,
            max_results=min(max_results, 100),
            tweet_fields=["public_metrics", "created_at", "text"],
        )

    response = _retry(_do_read)
    if response and response.data:
        tweets = []
        for tweet in response.data:
            metrics = tweet.get("public_metrics", {})
            tweets.append({
                "tweet_id": tweet.id,
                "text": tweet.text,
                "created_at": str(tweet.created_at),
                "impressions": metrics.get("impression_count", 0),
                "likes": metrics.get("like_count", 0),
                "replies": metrics.get("reply_count", 0),
                "reposts": metrics.get("retweet_count", 0),
                "quotes": metrics.get("quote_count", 0),
                "bookmarks": metrics.get("bookmark_count", 0),
            })
        return tweets

    return None


def get_usage_stats() -> Dict[str, int]:
    """Return cumulative API usage stats."""
    return {
        "total_posts": _total_posts,
        "total_reads": _total_reads,
        "total_failures": _total_failures,
    }
