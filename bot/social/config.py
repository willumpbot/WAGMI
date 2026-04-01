"""
Social module configuration — reads from .env, zero coupling to trading config.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class XConfig:
    """X/Twitter API configuration."""
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    access_secret: str = ""
    bearer_token: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.access_token and self.access_secret)


@dataclass
class BagConfig:
    """Community coins you're bagworking."""
    ticker: str = ""          # e.g. "PEPE"
    full_name: str = ""       # e.g. "Pepe"
    chain: str = ""           # e.g. "ETH", "SOL", "BASE"
    why_bullish: str = ""     # 1-liner thesis: "community-driven, 50k holders, major CEX listing soon"
    ca: str = ""              # contract address (optional, for alpha drops)
    hashtag: str = ""         # e.g. "$PEPE" — the cashtag
    style: str = "organic"    # organic (weave naturally) | direct (explicit shill) | alpha (insider feel)


@dataclass
class ContentConfig:
    """Content generation settings optimized for X algorithm."""

    # --- Posting limits ---
    max_posts_per_day: int = 12        # 8-12 for aggressive growth phase
    min_minutes_between_posts: int = 30  # Tight spacing for impression velocity

    # --- Community coins being bagworked ---
    bags: list = field(default_factory=list)  # List of BagConfig dicts

    # --- Content pillar weights for daily grind (must sum to 1.0) ---
    pillar_weights: dict = field(default_factory=lambda: {
        "ai_signals": 0.25,     # "What My AI Sees" — bot calls, market reads
        "bags": 0.25,           # Community coin promotion (organic + direct)
        "engagement": 0.20,     # Polls, hot takes, questions — drives replies (27x)
        "build_public": 0.15,   # "Building in Public"
        "education": 0.10,      # Quick alpha drops, frameworks
        "receipts": 0.05,       # Results when we have them
    })

    # --- Algorithm optimization ---
    # X algo weights: reply-to-reply=150x, retweet=40x, reply=27x, bookmark=20x, like=0.5x
    # Optimize for bookmarks (save-worthy content) and replies (conversation starters)
    target_length_chars: int = 240     # Sweet spot: short enough to read, long enough for substance
    max_thread_tweets: int = 8         # 3-8 optimal per algorithm data
    avoid_links_in_main: bool = True   # Links = 30-50% reach penalty. Put in reply.
    max_hashtags: int = 1              # 3+ hashtags = 40% penalty
    avoid_engagement_bait: bool = True # "Like if you agree" = algorithmic penalty

    # --- Voice profile ---
    voice_style: str = "builder-analyst"  # 60% builder/analyst, 25% teacher, 15% degen energy
    use_numbers_always: bool = True       # "Up 12%" not "up a lot"
    short_paragraphs: bool = True         # One idea per tweet
    occasional_profanity: bool = True     # Reads as authentic on CT

    # --- Anti-bot detection ---
    # These phrases/patterns get flagged as AI-generated
    banned_phrases: list = field(default_factory=lambda: [
        "let's dive in", "let's break it down", "here's the thing",
        "buckle up", "in this thread", "a thread 🧵",
        "game-changer", "revolutionary", "paradigm shift",
        "not financial advice", "DYOR", "this is huge",
        "I'm bullish because", "let me explain",
        "here's why this matters", "unpopular opinion",
        "hot take:", "thread:", "1/", "🧵",
        "in conclusion", "to summarize", "key takeaways",
        "without further ado", "at the end of the day",
        "it goes without saying", "needless to say",
        "the reality is", "the truth is",
        "I've been thinking about", "I want to talk about",
    ])

    # --- Optimal posting times (UTC) ---
    peak_hours_utc: list = field(default_factory=lambda: [
        13, 14, 15, 16,   # US market open (8AM-12PM EST) — HIGHEST
        8, 9, 10,          # European session
        20, 21, 22,        # US evening (threads/long content)
    ])


@dataclass
class AnalyticsConfig:
    """Engagement tracking settings."""
    track_impressions: bool = True
    track_engagement_rate: bool = True
    track_bookmark_rate: bool = True    # Bookmarks = 20x weight in algo
    track_reply_rate: bool = True       # Replies = 27x weight in algo
    report_frequency_days: int = 7
    data_dir: str = "data/social"


def load_bags() -> list:
    """Load community coin bags from data/social/bags.json."""
    import json
    from pathlib import Path
    bags_file = Path(__file__).parent.parent / "data" / "social" / "bags.json"
    if bags_file.exists():
        try:
            raw = json.loads(bags_file.read_text())
            return [BagConfig(**b) if isinstance(b, dict) else b for b in raw]
        except Exception:
            pass
    return []


def load_config() -> tuple[XConfig, ContentConfig, AnalyticsConfig]:
    """Load configuration from environment variables."""
    x = XConfig(
        api_key=os.getenv("X_API_KEY", ""),
        api_secret=os.getenv("X_API_SECRET", ""),
        access_token=os.getenv("X_ACCESS_TOKEN", ""),
        access_secret=os.getenv("X_ACCESS_SECRET", ""),
        bearer_token=os.getenv("X_BEARER_TOKEN", ""),
    )
    content = ContentConfig()
    content.bags = load_bags()
    return x, content, AnalyticsConfig()
