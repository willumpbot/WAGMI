"""
X/Twitter analytics tracker.

Pulls metrics for recent posts, stores them in JSONL,
and generates growth reports with weekly deltas.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger("bot.social.analytics")

DATA_DIR = os.path.join("data", "social")
METRICS_FILE = os.path.join(DATA_DIR, "x_metrics.jsonl")
BASELINE_FILE = os.path.join(DATA_DIR, "x_baseline.json")


def _ensure_data_dir():
    """Create data directory if it doesn't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)


def _append_jsonl(filepath: str, record: Dict[str, Any]) -> bool:
    """Append a JSON record to a JSONL file."""
    _ensure_data_dir()
    try:
        with open(filepath, "a") as f:
            f.write(json.dumps(record) + "\n")
        return True
    except Exception as e:
        logger.error(f"Failed to write to {filepath}: {e}")
        return False


def _read_jsonl(filepath: str) -> List[Dict[str, Any]]:
    """Read all records from a JSONL file."""
    if not os.path.exists(filepath):
        return []
    records = []
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception as e:
        logger.error(f"Failed to read {filepath}: {e}")
    return records


def pull_metrics() -> Optional[Dict[str, Any]]:
    """
    Pull current metrics from X API and store them.

    Returns summary dict or None on failure.
    """
    from social.x_client import get_user_metrics, get_recent_tweets

    # Get account-level metrics
    user_metrics = get_user_metrics()
    if not user_metrics:
        logger.warning("Could not pull user metrics from X API")
        return None

    # Get recent tweet metrics
    tweets = get_recent_tweets(max_results=20)

    # Calculate aggregate stats
    total_impressions = 0
    total_likes = 0
    total_replies = 0
    total_reposts = 0
    tweet_count = 0

    if tweets:
        for t in tweets:
            total_impressions += t.get("impressions", 0)
            total_likes += t.get("likes", 0)
            total_replies += t.get("replies", 0)
            total_reposts += t.get("reposts", 0)
            tweet_count += 1

    avg_impressions = total_impressions / tweet_count if tweet_count > 0 else 0
    avg_likes = total_likes / tweet_count if tweet_count > 0 else 0
    engagement_rate = (
        (total_likes + total_replies + total_reposts) / total_impressions * 100
        if total_impressions > 0
        else 0
    )

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "followers": user_metrics.get("followers", 0),
        "following": user_metrics.get("following", 0),
        "tweet_count_total": user_metrics.get("tweet_count", 0),
        "recent_tweets_sampled": tweet_count,
        "total_impressions": total_impressions,
        "avg_impressions": round(avg_impressions, 1),
        "total_likes": total_likes,
        "avg_likes": round(avg_likes, 1),
        "total_replies": total_replies,
        "total_reposts": total_reposts,
        "engagement_rate_pct": round(engagement_rate, 2),
    }

    # Store snapshot
    _append_jsonl(METRICS_FILE, snapshot)
    logger.info(f"Stored metrics snapshot: {snapshot['followers']} followers, {avg_impressions:.0f} avg impressions")

    return snapshot


def save_baseline() -> Optional[Dict[str, Any]]:
    """Save current metrics as the baseline for tracking growth."""
    snapshot = pull_metrics()
    if not snapshot:
        return None

    snapshot["baseline_date"] = datetime.now().isoformat()
    _ensure_data_dir()

    try:
        with open(BASELINE_FILE, "w") as f:
            json.dump(snapshot, f, indent=2)
        logger.info("Saved baseline metrics")
        return snapshot
    except Exception as e:
        logger.error(f"Failed to save baseline: {e}")
        return None


def get_baseline() -> Optional[Dict[str, Any]]:
    """Load the saved baseline metrics."""
    if not os.path.exists(BASELINE_FILE):
        return None
    try:
        with open(BASELINE_FILE) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load baseline: {e}")
        return None


def log_post(
    tweet_id: str,
    text: str,
    pillar: str = "",
    content_type: str = "single",
    generated: bool = False,
) -> bool:
    """
    Log a posted tweet for later analysis.

    Args:
        tweet_id: The posted tweet's ID
        text: Tweet text
        pillar: Content pillar tag
        content_type: "single", "thread", "reply", "chronicle"
        generated: Whether it was AI-generated
    """
    record = {
        "timestamp": datetime.now().isoformat(),
        "tweet_id": tweet_id,
        "text": text[:300],
        "pillar": pillar,
        "content_type": content_type,
        "generated": generated,
        "char_count": len(text),
    }
    return _append_jsonl(
        os.path.join(DATA_DIR, "x_posts.jsonl"),
        record,
    )


def generate_report(days: int = 7) -> str:
    """
    Generate a text growth report comparing current metrics to baseline and recent history.

    Args:
        days: Number of days to analyze

    Returns:
        Formatted text report
    """
    baseline = get_baseline()
    snapshots = _read_jsonl(METRICS_FILE)

    # Filter to requested time window
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    recent = [s for s in snapshots if s.get("timestamp", "") >= cutoff]

    lines = [
        f"=== X Growth Report ({days}d) ===",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    if not recent:
        lines.append("No metrics data yet. Run 'analytics pull' first.")
        return "\n".join(lines)

    latest = recent[-1]
    lines.append(f"Current Followers: {latest.get('followers', '?')}")
    lines.append(f"Avg Impressions/Post: {latest.get('avg_impressions', '?')}")
    lines.append(f"Avg Likes/Post: {latest.get('avg_likes', '?')}")
    lines.append(f"Engagement Rate: {latest.get('engagement_rate_pct', '?')}%")
    lines.append(f"Snapshots in Period: {len(recent)}")

    if baseline:
        lines.append("")
        lines.append("--- vs Baseline ---")
        b_followers = baseline.get("followers", 0)
        c_followers = latest.get("followers", 0)
        follower_delta = c_followers - b_followers
        lines.append(f"Follower Change: {'+' if follower_delta >= 0 else ''}{follower_delta}")
        lines.append(f"Baseline Date: {baseline.get('baseline_date', '?')[:10]}")

        b_imp = baseline.get("avg_impressions", 0)
        c_imp = latest.get("avg_impressions", 0)
        if b_imp > 0:
            imp_change = ((c_imp - b_imp) / b_imp) * 100
            lines.append(f"Impressions Change: {'+' if imp_change >= 0 else ''}{imp_change:.1f}%")

    # Check post log
    posts = _read_jsonl(os.path.join(DATA_DIR, "x_posts.jsonl"))
    recent_posts = [p for p in posts if p.get("timestamp", "") >= cutoff]
    if recent_posts:
        lines.append("")
        lines.append("--- Posting Activity ---")
        lines.append(f"Posts in Period: {len(recent_posts)}")

        # Break down by pillar
        pillar_counts = {}
        for p in recent_posts:
            pillar = p.get("pillar", "untagged") or "untagged"
            pillar_counts[pillar] = pillar_counts.get(pillar, 0) + 1
        for pillar, count in sorted(pillar_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {pillar}: {count}")

        # Generated vs manual
        gen_count = sum(1 for p in recent_posts if p.get("generated"))
        lines.append(f"  AI-generated: {gen_count}")
        lines.append(f"  Manual: {len(recent_posts) - gen_count}")

    lines.append("")
    return "\n".join(lines)


def get_top_posts(days: int = 7, limit: int = 5) -> List[Dict[str, Any]]:
    """Get top performing posts by impressions in the given period."""
    snapshots = _read_jsonl(METRICS_FILE)
    # This would need per-tweet metrics stored separately
    # For now, pull fresh from API
    from social.x_client import get_recent_tweets

    tweets = get_recent_tweets(max_results=50)
    if not tweets:
        return []

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    recent = [t for t in tweets if t.get("created_at", "") >= cutoff]
    recent.sort(key=lambda t: t.get("impressions", 0), reverse=True)
    return recent[:limit]
