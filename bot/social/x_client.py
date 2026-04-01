"""
X/Twitter API client — posting, reading analytics, managing content.
Uses tweepy v2 (Twitter API v2). Graceful degradation if not configured.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("social.x_client")

# Data directory for social module
DATA_DIR = Path(__file__).parent.parent / "data" / "social"
QUEUE_FILE = DATA_DIR / "post_queue.json"
POSTED_FILE = DATA_DIR / "posted_history.json"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class XClient:
    """Twitter/X API client with algorithm-aware posting."""

    def __init__(self, x_config):
        self.config = x_config
        self.client = None
        self.api = None  # v1.1 for media uploads
        self._setup_client()

    def _setup_client(self):
        """Initialize tweepy client if credentials are available."""
        if not self.config.is_configured:
            logger.warning("X API credentials not configured. Running in dry-run mode.")
            return

        try:
            import tweepy
            # v2 client for posting
            self.client = tweepy.Client(
                consumer_key=self.config.api_key,
                consumer_secret=self.config.api_secret,
                access_token=self.config.access_token,
                access_token_secret=self.config.access_secret,
                bearer_token=self.config.bearer_token or None,
                wait_on_rate_limit=True,
            )
            # v1.1 API for media uploads (images/video)
            auth = tweepy.OAuth1UserHandler(
                self.config.api_key, self.config.api_secret,
                self.config.access_token, self.config.access_secret,
            )
            self.api = tweepy.API(auth, wait_on_rate_limit=True)
            logger.info("X API client initialized successfully")
        except ImportError:
            logger.error("tweepy not installed. Run: pip install tweepy>=4.14.0")
        except Exception as e:
            logger.error(f"Failed to initialize X client: {e}")

    @property
    def is_connected(self) -> bool:
        return self.client is not None

    def verify_credentials(self) -> dict:
        """Test API connection and return account info."""
        if not self.is_connected:
            return {"status": "disconnected", "reason": "credentials not configured"}
        try:
            me = self.client.get_me(
                user_fields=["public_metrics", "description", "created_at"]
            )
            if me.data:
                metrics = me.data.public_metrics
                return {
                    "status": "connected",
                    "username": me.data.username,
                    "name": me.data.name,
                    "followers": metrics["followers_count"],
                    "following": metrics["following_count"],
                    "tweets": metrics["tweet_count"],
                    "description": me.data.description,
                }
            return {"status": "error", "reason": "no data returned"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    def post_tweet(self, text: str, reply_to: Optional[str] = None,
                   media_path: Optional[str] = None, dry_run: bool = False) -> dict:
        """
        Post a tweet. Returns tweet data or dry-run preview.

        Algorithm optimization applied:
        - No links in main tweet (put in reply)
        - Short, punchy format
        - No engagement bait
        """
        if dry_run or not self.is_connected:
            result = {
                "status": "dry_run",
                "text": text,
                "char_count": len(text),
                "reply_to": reply_to,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(f"[DRY RUN] Would post: {text[:80]}...")
            self._save_to_history(result)
            return result

        try:
            kwargs = {"text": text}
            if reply_to:
                kwargs["in_reply_to_tweet_id"] = reply_to

            # Upload media if provided
            if media_path and self.api:
                media = self.api.media_upload(media_path)
                kwargs["media_ids"] = [media.media_id]

            response = self.client.create_tweet(**kwargs)
            tweet_id = response.data["id"]
            result = {
                "status": "posted",
                "tweet_id": tweet_id,
                "text": text,
                "char_count": len(text),
                "reply_to": reply_to,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "url": f"https://x.com/i/web/status/{tweet_id}",
            }
            logger.info(f"Posted tweet {tweet_id}: {text[:80]}...")
            self._save_to_history(result)
            return result
        except Exception as e:
            logger.error(f"Failed to post tweet: {e}")
            return {"status": "error", "reason": str(e), "text": text}

    def post_thread(self, tweets: list[str], dry_run: bool = False) -> list[dict]:
        """Post a thread (list of tweets). Each replies to the previous."""
        results = []
        reply_to = None
        for i, text in enumerate(tweets):
            result = self.post_tweet(text, reply_to=reply_to, dry_run=dry_run)
            results.append(result)
            if result.get("tweet_id"):
                reply_to = result["tweet_id"]
            elif dry_run:
                reply_to = f"dry_run_{i}"
        return results

    def post_with_link_reply(self, main_text: str, link: str,
                              link_context: str = "", dry_run: bool = False) -> list[dict]:
        """
        Algorithm-optimized posting: main tweet clean, link in self-reply.
        Links in main tweet = 30-50% reach penalty.
        """
        main_result = self.post_tweet(main_text, dry_run=dry_run)
        reply_text = f"{link_context}\n{link}" if link_context else link
        reply_id = main_result.get("tweet_id") or "dry_run_0"
        reply_result = self.post_tweet(reply_text, reply_to=reply_id, dry_run=dry_run)
        return [main_result, reply_result]

    def get_tweet_metrics(self, tweet_id: str) -> Optional[dict]:
        """Fetch engagement metrics for a specific tweet."""
        if not self.is_connected:
            return None
        try:
            tweet = self.client.get_tweet(
                tweet_id,
                tweet_fields=["public_metrics", "created_at", "organic_metrics"],
            )
            if tweet.data:
                metrics = tweet.data.public_metrics
                return {
                    "tweet_id": tweet_id,
                    "impressions": metrics.get("impression_count", 0),
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "bookmarks": metrics.get("bookmark_count", 0),
                    "quotes": metrics.get("quote_count", 0),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            return None
        except Exception as e:
            logger.error(f"Failed to fetch metrics for {tweet_id}: {e}")
            return None

    def get_recent_tweets(self, limit: int = 20) -> list[dict]:
        """Fetch your recent tweets with metrics."""
        if not self.is_connected:
            return []
        try:
            me = self.client.get_me()
            if not me.data:
                return []
            tweets = self.client.get_users_tweets(
                me.data.id,
                max_results=min(limit, 100),
                tweet_fields=["public_metrics", "created_at", "text"],
            )
            results = []
            if tweets.data:
                for t in tweets.data:
                    m = t.public_metrics
                    results.append({
                        "tweet_id": t.id,
                        "text": t.text,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "impressions": m.get("impression_count", 0),
                        "likes": m.get("like_count", 0),
                        "retweets": m.get("retweet_count", 0),
                        "replies": m.get("reply_count", 0),
                        "bookmarks": m.get("bookmark_count", 0),
                    })
            return results
        except Exception as e:
            logger.error(f"Failed to fetch recent tweets: {e}")
            return []

    # --- Queue management ---

    def queue_post(self, text: str, scheduled_time: Optional[str] = None,
                   pillar: str = "ai_signals", metadata: Optional[dict] = None):
        """Add a post to the queue for later review/posting."""
        _ensure_data_dir()
        queue = self._load_queue()
        entry = {
            "text": text,
            "pillar": pillar,
            "scheduled_time": scheduled_time,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "queued",
            "metadata": metadata or {},
        }
        queue.append(entry)
        self._save_queue(queue)
        logger.info(f"Queued post [{pillar}]: {text[:60]}...")
        return entry

    def get_queue(self) -> list[dict]:
        return self._load_queue()

    def fire_queue(self, dry_run: bool = False) -> list[dict]:
        """Post all queued items that are due."""
        queue = self._load_queue()
        now = datetime.now(timezone.utc)
        results = []
        remaining = []

        for item in queue:
            if item["status"] != "queued":
                remaining.append(item)
                continue

            scheduled = item.get("scheduled_time")
            if scheduled and datetime.fromisoformat(scheduled) > now:
                remaining.append(item)
                continue

            result = self.post_tweet(item["text"], dry_run=dry_run)
            item["status"] = "posted" if result.get("status") == "posted" else "dry_run"
            item["result"] = result
            results.append(item)

        self._save_queue(remaining)
        return results

    # --- Persistence helpers ---

    def _load_queue(self) -> list:
        _ensure_data_dir()
        if QUEUE_FILE.exists():
            try:
                return json.loads(QUEUE_FILE.read_text())
            except Exception:
                return []
        return []

    def _save_queue(self, queue: list):
        _ensure_data_dir()
        QUEUE_FILE.write_text(json.dumps(queue, indent=2))

    def _save_to_history(self, entry: dict):
        _ensure_data_dir()
        history = []
        if POSTED_FILE.exists():
            try:
                history = json.loads(POSTED_FILE.read_text())
            except Exception:
                pass
        history.append(entry)
        # Keep last 500 posts
        if len(history) > 500:
            history = history[-500:]
        POSTED_FILE.write_text(json.dumps(history, indent=2))
