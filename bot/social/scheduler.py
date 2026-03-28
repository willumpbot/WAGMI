"""
Post scheduler for X/Twitter.

Manages a content queue with scheduled posting times,
content type tagging, and optimal timing suggestions.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger("bot.social.scheduler")

DATA_DIR = os.path.join("data", "social")
QUEUE_FILE = os.path.join(DATA_DIR, "post_queue.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_queue() -> List[Dict[str, Any]]:
    """Load the post queue from disk."""
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load queue: {e}")
        return []


def _save_queue(queue: List[Dict[str, Any]]) -> bool:
    """Save the post queue to disk."""
    _ensure_data_dir()
    try:
        with open(QUEUE_FILE, "w") as f:
            json.dump(queue, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save queue: {e}")
        return False


def add_to_queue(
    text: str,
    scheduled_time: Optional[str] = None,
    pillar: str = "",
    content_type: str = "single",
    media_paths: Optional[List[str]] = None,
    thread_texts: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Add a post to the queue.

    Args:
        text: Tweet text (or first tweet if thread)
        scheduled_time: ISO format datetime to post (None = post ASAP when fire_due() is called)
        pillar: Content pillar tag
        content_type: "single", "thread", "chronicle"
        media_paths: Optional media file paths
        thread_texts: If content_type is "thread", the remaining tweets

    Returns:
        Queue item ID, or None on failure
    """
    queue = _load_queue()
    item_id = str(uuid.uuid4())[:8]

    item = {
        "id": item_id,
        "text": text,
        "scheduled_time": scheduled_time,
        "pillar": pillar,
        "content_type": content_type,
        "media_paths": media_paths or [],
        "thread_texts": thread_texts or [],
        "created_at": datetime.now().isoformat(),
        "status": "queued",
    }

    queue.append(item)
    if _save_queue(queue):
        logger.info(f"Added to queue: {item_id} ({content_type}) scheduled={scheduled_time or 'ASAP'}")
        return item_id
    return None


def list_queue(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List items in the queue.

    Args:
        status: Filter by status ("queued", "posted", "failed"). None = all.
    """
    queue = _load_queue()
    if status:
        queue = [item for item in queue if item.get("status") == status]
    return queue


def remove_from_queue(item_id: str) -> bool:
    """Remove an item from the queue by ID."""
    queue = _load_queue()
    original_len = len(queue)
    queue = [item for item in queue if item.get("id") != item_id]
    if len(queue) < original_len:
        _save_queue(queue)
        logger.info(f"Removed from queue: {item_id}")
        return True
    logger.warning(f"Item not found in queue: {item_id}")
    return False


def get_due_items() -> List[Dict[str, Any]]:
    """Get all queued items that are due to be posted (scheduled_time <= now)."""
    queue = _load_queue()
    now = datetime.now().isoformat()
    due = []
    for item in queue:
        if item.get("status") != "queued":
            continue
        scheduled = item.get("scheduled_time")
        if scheduled is None or scheduled <= now:
            due.append(item)
    return due


def fire_due(dry_run: bool = False) -> List[Dict[str, Any]]:
    """
    Post all due items from the queue.

    Args:
        dry_run: If True, mark as posted but don't actually post

    Returns:
        List of results for each attempted post
    """
    from social.x_client import post_tweet, post_thread
    from social.analytics import log_post

    due_items = get_due_items()
    if not due_items:
        logger.info("No due items in queue")
        return []

    results = []
    queue = _load_queue()

    for item in due_items:
        item_id = item["id"]
        text = item["text"]
        content_type = item.get("content_type", "single")
        media_paths = item.get("media_paths")
        pillar = item.get("pillar", "")

        if content_type == "thread":
            thread_texts = [text] + item.get("thread_texts", [])
            result = post_thread(thread_texts, dry_run=dry_run)
            if result:
                _mark_status(queue, item_id, "posted")
                for r in result:
                    log_post(
                        tweet_id=r["tweet_id"],
                        text=r["text"],
                        pillar=pillar,
                        content_type="thread",
                        generated=True,
                    )
                results.append({"id": item_id, "status": "posted", "tweets": len(result)})
            else:
                _mark_status(queue, item_id, "failed")
                results.append({"id": item_id, "status": "failed"})
        else:
            result = post_tweet(
                text=text,
                media_paths=media_paths if media_paths else None,
                dry_run=dry_run,
            )
            if result:
                _mark_status(queue, item_id, "posted")
                log_post(
                    tweet_id=result["tweet_id"],
                    text=result["text"],
                    pillar=pillar,
                    content_type=content_type,
                    generated=True,
                )
                results.append({"id": item_id, "status": "posted", "tweet_id": result["tweet_id"]})
            else:
                _mark_status(queue, item_id, "failed")
                results.append({"id": item_id, "status": "failed"})

    _save_queue(queue)
    return results


def _mark_status(queue: List[Dict], item_id: str, status: str):
    """Update status of an item in the queue list (in memory)."""
    for item in queue:
        if item.get("id") == item_id:
            item["status"] = status
            item["posted_at"] = datetime.now().isoformat()
            break


def suggest_times(count: int = 5) -> List[str]:
    """
    Suggest optimal posting times based on general best practices.

    Returns list of ISO datetime strings for the next `count` posting slots.
    """
    now = datetime.now()
    # Best times for crypto/tech audience (US-centric):
    # Morning: 9-10 AM, Lunch: 12-1 PM, Evening: 6-7 PM, Night: 9-10 PM
    optimal_hours = [9, 12, 18, 21]

    suggestions = []
    current = now

    while len(suggestions) < count:
        for hour in optimal_hours:
            candidate = current.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > now and len(suggestions) < count:
                suggestions.append(candidate.isoformat())
        current += timedelta(days=1)

    return suggestions


def clear_posted(days_old: int = 7) -> int:
    """Remove posted/failed items older than N days. Returns count removed."""
    queue = _load_queue()
    cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()
    original = len(queue)
    queue = [
        item for item in queue
        if item.get("status") == "queued" or item.get("posted_at", item.get("created_at", "")) >= cutoff
    ]
    removed = original - len(queue)
    if removed > 0:
        _save_queue(queue)
        logger.info(f"Cleared {removed} old items from queue")
    return removed
