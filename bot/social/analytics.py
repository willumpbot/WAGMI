"""
Analytics tracker — measures what content actually drives impressions.

Tracks engagement by:
- Content pillar (ai_signals, build_public, education, receipts)
- Hook type (data-lead, hot take, story)
- Time of day (UTC hour)
- Day of week
- Format (single tweet, thread, with image)
- Character length bucket

Uses the same feedback loop philosophy as the trading bot:
measure → learn → adapt → repeat
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("social.analytics")

DATA_DIR = Path(__file__).parent.parent / "data" / "social"
ANALYTICS_FILE = DATA_DIR / "analytics.json"
PERFORMANCE_FILE = DATA_DIR / "content_performance.json"


class EngagementTracker:
    """Track and analyze tweet engagement to optimize content strategy."""

    def __init__(self, x_client=None):
        self.x_client = x_client
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        if ANALYTICS_FILE.exists():
            try:
                return json.loads(ANALYTICS_FILE.read_text())
            except Exception:
                pass
        return {
            "tweets": [],
            "baseline": None,
            "weekly_snapshots": [],
        }

    def _save(self):
        ANALYTICS_FILE.write_text(json.dumps(self.data, indent=2, default=str))

    def record_post(self, tweet_id: str, text: str, pillar: str,
                     hook_type: str = "unknown", is_thread: bool = False,
                     metadata: Optional[dict] = None):
        """Record a posted tweet for later metrics tracking."""
        entry = {
            "tweet_id": tweet_id,
            "text": text,
            "pillar": pillar,
            "hook_type": hook_type,
            "is_thread": is_thread,
            "char_count": len(text),
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "hour_utc": datetime.now(timezone.utc).hour,
            "day_of_week": datetime.now(timezone.utc).strftime("%A"),
            "metrics": None,  # Filled in by pull_metrics
            "metadata": metadata or {},
        }
        self.data["tweets"].append(entry)
        self._save()
        logger.info(f"Recorded post {tweet_id} [{pillar}]")

    def pull_metrics(self, hours_old: int = 24) -> int:
        """Pull metrics for tweets that are at least hours_old old."""
        if not self.x_client:
            logger.warning("No X client — can't pull metrics")
            return 0

        updated = 0
        now = datetime.now(timezone.utc)
        for entry in self.data["tweets"]:
            if entry.get("metrics"):
                continue
            posted = datetime.fromisoformat(entry["posted_at"])
            age_hours = (now - posted).total_seconds() / 3600
            if age_hours < hours_old:
                continue
            metrics = self.x_client.get_tweet_metrics(entry["tweet_id"])
            if metrics:
                entry["metrics"] = metrics
                updated += 1

        if updated:
            self._save()
        logger.info(f"Updated metrics for {updated} tweets")
        return updated

    def save_baseline(self) -> dict:
        """Save current account metrics as baseline for growth tracking."""
        if not self.x_client:
            return {"error": "X client not connected"}
        info = self.x_client.verify_credentials()
        if info.get("status") == "connected":
            self.data["baseline"] = {
                **info,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save()
        return info

    def weekly_snapshot(self) -> dict:
        """Take a weekly growth snapshot."""
        if not self.x_client:
            return {"error": "X client not connected"}
        info = self.x_client.verify_credentials()
        if info.get("status") == "connected":
            snapshot = {
                **info,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "tweets_this_week": len([
                    t for t in self.data["tweets"]
                    if self._is_this_week(t["posted_at"])
                ]),
            }
            self.data["weekly_snapshots"].append(snapshot)
            self._save()
            return snapshot
        return info

    # --- Analysis methods ---

    def get_performance_report(self) -> dict:
        """Analyze content performance across all dimensions."""
        tweets_with_metrics = [
            t for t in self.data["tweets"] if t.get("metrics")
        ]

        if not tweets_with_metrics:
            return {"status": "no_data", "message": "No tweets with metrics yet. Post some content and wait 24h."}

        report = {
            "total_tracked": len(tweets_with_metrics),
            "by_pillar": self._analyze_by("pillar", tweets_with_metrics),
            "by_hook_type": self._analyze_by("hook_type", tweets_with_metrics),
            "by_hour": self._analyze_by("hour_utc", tweets_with_metrics),
            "by_day": self._analyze_by("day_of_week", tweets_with_metrics),
            "by_format": self._analyze_format(tweets_with_metrics),
            "top_tweets": self._top_tweets(tweets_with_metrics, n=5),
            "worst_tweets": self._worst_tweets(tweets_with_metrics, n=3),
            "growth": self._growth_summary(),
            "recommendations": [],
        }

        # Generate recommendations
        report["recommendations"] = self._generate_recommendations(report)
        return report

    def _analyze_by(self, field: str, tweets: list) -> dict:
        """Analyze engagement by a specific field."""
        groups = defaultdict(list)
        for t in tweets:
            key = str(t.get(field, "unknown"))
            groups[key].append(t)

        result = {}
        for key, group in groups.items():
            metrics = [t["metrics"] for t in group]
            result[key] = {
                "count": len(group),
                "avg_impressions": self._avg(metrics, "impressions"),
                "avg_likes": self._avg(metrics, "likes"),
                "avg_bookmarks": self._avg(metrics, "bookmarks"),
                "avg_replies": self._avg(metrics, "replies"),
                "avg_retweets": self._avg(metrics, "retweets"),
                "algo_score": self._algo_score(metrics),  # Weighted by X algorithm
            }
        return dict(sorted(result.items(), key=lambda x: x[1]["algo_score"], reverse=True))

    def _analyze_format(self, tweets: list) -> dict:
        """Analyze by tweet format (single vs thread, with/without image)."""
        groups = {"single": [], "thread": []}
        for t in tweets:
            key = "thread" if t.get("is_thread") else "single"
            groups[key].append(t)

        result = {}
        for key, group in groups.items():
            if not group:
                continue
            metrics = [t["metrics"] for t in group]
            result[key] = {
                "count": len(group),
                "avg_impressions": self._avg(metrics, "impressions"),
                "algo_score": self._algo_score(metrics),
            }
        return result

    def _top_tweets(self, tweets: list, n: int = 5) -> list:
        """Get top performing tweets by algorithm score."""
        scored = []
        for t in tweets:
            m = t["metrics"]
            score = (
                m.get("impressions", 0) * 1.0 +
                m.get("bookmarks", 0) * 20 +
                m.get("replies", 0) * 27 +
                m.get("retweets", 0) * 40 +
                m.get("likes", 0) * 0.5
            )
            scored.append({
                "text": t["text"][:120] + "..." if len(t["text"]) > 120 else t["text"],
                "pillar": t["pillar"],
                "impressions": m.get("impressions", 0),
                "bookmarks": m.get("bookmarks", 0),
                "replies": m.get("replies", 0),
                "algo_score": round(score, 1),
            })
        return sorted(scored, key=lambda x: x["algo_score"], reverse=True)[:n]

    def _worst_tweets(self, tweets: list, n: int = 3) -> list:
        """Get worst performing tweets to learn from."""
        scored = self._top_tweets(tweets, n=len(tweets))
        return scored[-n:] if len(scored) >= n else scored

    def _growth_summary(self) -> dict:
        """Summarize growth from baseline to now."""
        baseline = self.data.get("baseline")
        snapshots = self.data.get("weekly_snapshots", [])

        if not baseline:
            return {"status": "no_baseline", "message": "Run 'analytics baseline' to set starting point"}

        latest = snapshots[-1] if snapshots else baseline
        return {
            "baseline_followers": baseline.get("followers", 0),
            "current_followers": latest.get("followers", 0),
            "follower_growth": latest.get("followers", 0) - baseline.get("followers", 0),
            "baseline_date": baseline.get("captured_at"),
            "latest_date": latest.get("captured_at"),
            "snapshots_count": len(snapshots),
        }

    def _generate_recommendations(self, report: dict) -> list[str]:
        """Generate actionable recommendations from data."""
        recs = []

        # Best pillar recommendation
        by_pillar = report.get("by_pillar", {})
        if by_pillar:
            best_pillar = max(by_pillar.items(), key=lambda x: x[1]["algo_score"])
            recs.append(f"Best performing pillar: '{best_pillar[0]}' (algo score: {best_pillar[1]['algo_score']:.0f}). Post more of this.")

        # Best time recommendation
        by_hour = report.get("by_hour", {})
        if by_hour:
            best_hour = max(by_hour.items(), key=lambda x: x[1]["algo_score"])
            recs.append(f"Best posting hour: {best_hour[0]}:00 UTC. Schedule key content here.")

        # Format recommendation
        by_format = report.get("by_format", {})
        if "thread" in by_format and "single" in by_format:
            thread_score = by_format["thread"]["algo_score"]
            single_score = by_format["single"]["algo_score"]
            if thread_score > single_score * 1.3:
                recs.append("Threads significantly outperform single tweets. Post more threads.")

        return recs

    # --- Helpers ---

    @staticmethod
    def _avg(metrics: list, field: str) -> float:
        vals = [m.get(field, 0) for m in metrics]
        return round(sum(vals) / len(vals), 1) if vals else 0

    @staticmethod
    def _algo_score(metrics: list) -> float:
        """Calculate average X algorithm score for a group of tweets."""
        scores = []
        for m in metrics:
            score = (
                m.get("impressions", 0) * 1.0 +
                m.get("bookmarks", 0) * 20 +
                m.get("replies", 0) * 27 +
                m.get("retweets", 0) * 40 +
                m.get("likes", 0) * 0.5
            )
            scores.append(score)
        return round(sum(scores) / len(scores), 1) if scores else 0

    @staticmethod
    def _is_this_week(iso_date: str) -> bool:
        try:
            dt = datetime.fromisoformat(iso_date)
            now = datetime.now(timezone.utc)
            return (now - dt).days < 7
        except Exception:
            return False
