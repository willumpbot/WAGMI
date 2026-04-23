"""Bagworker engagement platform backend.

FastAPI server for TG Mini App:
- User authentication (via TG)
- Post management
- Points tracking
- Leaderboard
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


# ===== Data Models =====

class User(BaseModel):
    tg_id: int
    username: str
    first_name: str
    last_name: Optional[str] = None
    points: int = 0
    retweets: int = 0
    likes: int = 0
    replies: int = 0
    created_at: datetime = datetime.now()


class Post(BaseModel):
    post_id: str
    text: str
    created_by_tg_id: int
    created_at: datetime = datetime.now()
    raid_count: int = 0


class EngagementAction(BaseModel):
    post_id: str
    user_tg_id: int
    action_type: str  # "retweet", "like", "reply"
    points_earned: int
    timestamp: datetime = datetime.now()


# ===== Database (SQLite-backed) =====

class BagworkerDB:
    """Simple file-based database for bagworker platform."""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path("data/bagworker_db")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_file = self.data_dir / "users.jsonl"
        self.posts_file = self.data_dir / "posts.jsonl"
        self.actions_file = self.data_dir / "actions.jsonl"

    def _append_jsonl(self, path: Path, obj: dict):
        """Append JSON object to JSONL file."""
        with open(path, "a") as f:
            f.write(json.dumps(obj) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict]:
        """Read all objects from JSONL file."""
        if not path.exists():
            return []
        with open(path, "r") as f:
            return [json.loads(line) for line in f if line.strip()]

    # ===== Users =====

    def user_get_or_create(self, tg_id: int, username: str, first_name: str, last_name: str = "") -> dict:
        """Get user or create if doesn't exist."""
        users = self._read_jsonl(self.users_file)
        user = next((u for u in users if u.get("tg_id") == tg_id), None)

        if user:
            return user

        # Create new user
        user = {
            "tg_id": tg_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name or "",
            "points": 0,
            "retweets": 0,
            "likes": 0,
            "replies": 0,
            "created_at": datetime.now().isoformat(),
        }
        self._append_jsonl(self.users_file, user)
        return user

    def user_add_points(self, tg_id: int, points: int, action_type: str = ""):
        """Add points to user and update action count."""
        users = self._read_jsonl(self.users_file)
        for user in users:
            if user["tg_id"] == tg_id:
                user["points"] = user.get("points", 0) + points
                # Update action counters
                if action_type == "retweet":
                    user["retweets"] = user.get("retweets", 0) + 1
                elif action_type == "like":
                    user["likes"] = user.get("likes", 0) + 1
                elif action_type == "reply":
                    user["replies"] = user.get("replies", 0) + 1
                break

        # Rewrite file
        self.users_file.write_text("\n".join(json.dumps(u) for u in users) + "\n")

    def user_get(self, tg_id: int) -> Optional[dict]:
        """Get user by TG ID."""
        users = self._read_jsonl(self.users_file)
        return next((u for u in users if u["tg_id"] == tg_id), None)

    def leaderboard(self, limit: int = 10) -> list[dict]:
        """Get top users by points."""
        users = self._read_jsonl(self.users_file)
        return sorted(users, key=lambda u: u.get("points", 0), reverse=True)[:limit]

    # ===== Posts =====

    def post_create(self, post_id: str, text: str, created_by_tg_id: int):
        """Create a new post."""
        post = {
            "post_id": post_id,
            "text": text,
            "created_by_tg_id": created_by_tg_id,
            "created_at": datetime.now().isoformat(),
            "raid_count": 0,
        }
        self._append_jsonl(self.posts_file, post)
        return post

    def posts_recent(self, limit: int = 10) -> list[dict]:
        """Get recent posts."""
        posts = self._read_jsonl(self.posts_file)
        return sorted(posts, key=lambda p: p["created_at"], reverse=True)[:limit]

    # ===== Engagement =====

    def action_record(self, post_id: str, user_tg_id: int, action_type: str) -> int:
        """Record engagement action, return points earned."""
        points_map = {
            "retweet": 5,
            "like": 2,
            "reply": 10,
        }
        points = points_map.get(action_type, 0)

        action = {
            "post_id": post_id,
            "user_tg_id": user_tg_id,
            "action_type": action_type,
            "points_earned": points,
            "timestamp": datetime.now().isoformat(),
        }
        self._append_jsonl(self.actions_file, action)

        # Update user points
        self.user_add_points(user_tg_id, points, action_type)

        return points


# Global DB instance
db = BagworkerDB()
