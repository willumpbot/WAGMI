"""
CLI for X/Twitter social automation.

Usage (from bot/ directory):
    python -m social.cli post "your tweet text here"
    python -m social.cli post "tweet" --dry-run
    python -m social.cli generate --topic "BTC structure" --pillar trading
    python -m social.cli thread --topic "my trading journey"
    python -m social.cli chronicle [--days 7]
    python -m social.cli milestone "First profitable week"
    python -m social.cli analytics pull
    python -m social.cli analytics report [--days 7]
    python -m social.cli analytics baseline
    python -m social.cli analytics top [--days 7]
    python -m social.cli queue list
    python -m social.cli queue add "tweet text" [--time "2026-03-29T09:00:00"]
    python -m social.cli queue fire [--dry-run]
    python -m social.cli queue remove <id>
    python -m social.cli queue suggest
    python -m social.cli queue clear [--days 7]
    python -m social.cli status
"""

import argparse
import json
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot.social.cli")


def cmd_post(args):
    """Post a tweet immediately."""
    from social.x_client import post_tweet
    from social.analytics import log_post

    result = post_tweet(
        text=args.text,
        media_paths=args.media.split(",") if args.media else None,
        dry_run=args.dry_run,
    )
    if result:
        print(f"Posted: {result['tweet_id']}")
        print(f"Text: {result['text']}")
        if not args.dry_run:
            log_post(
                tweet_id=result["tweet_id"],
                text=result["text"],
                pillar=args.pillar or "",
                content_type="single",
                generated=False,
            )
    else:
        print("Failed to post tweet")
        sys.exit(1)


def cmd_generate(args):
    """Generate tweet hooks using Claude."""
    from social.content_generator import generate_hooks

    print(f"Generating hooks for: {args.topic} (pillar: {args.pillar})")
    hooks = generate_hooks(topic=args.topic, pillar=args.pillar)
    if hooks:
        print(f"\n--- {len(hooks)} options ---")
        for i, hook in enumerate(hooks, 1):
            print(f"\n[{i}] ({len(hook)} chars)")
            print(hook)
        print()
    else:
        print("Failed to generate hooks")
        sys.exit(1)


def cmd_thread(args):
    """Generate a thread using Claude."""
    from social.content_generator import generate_thread

    print(f"Generating thread for: {args.topic} (pillar: {args.pillar})")
    tweets = generate_thread(
        topic=args.topic,
        pillar=args.pillar,
        key_points=args.points.split("|") if args.points else None,
    )
    if tweets:
        print(f"\n--- Thread ({len(tweets)} tweets) ---")
        for i, tweet in enumerate(tweets, 1):
            print(f"\n[{i}/{len(tweets)}] ({len(tweet)} chars)")
            print(tweet)
        print()

        if args.post:
            from social.x_client import post_thread as do_post_thread
            print("Posting thread...")
            results = do_post_thread(tweets, dry_run=args.dry_run)
            if results:
                print(f"Posted {len(results)} tweets")
            else:
                print("Failed to post thread")
    else:
        print("Failed to generate thread")
        sys.exit(1)


def cmd_chronicle(args):
    """Generate project update from git history."""
    from social.content_generator import generate_chronicle

    print(f"Generating chronicle from last {args.days} days...")
    options = generate_chronicle(days=args.days, repo_path=args.repo or "..")
    if options:
        print(f"\n--- {len(options)} options ---")
        for i, option in enumerate(options, 1):
            print(f"\n[{i}] ({len(option)} chars)")
            print(option)
        print()
    else:
        print("No commits found or generation failed")
        sys.exit(1)


def cmd_milestone(args):
    """Generate milestone announcement."""
    from social.content_generator import generate_milestone_post

    print(f"Generating milestone post: {args.milestone}")
    options = generate_milestone_post(
        milestone=args.milestone,
        details=args.details,
    )
    if options:
        print(f"\n--- {len(options)} options ---")
        for i, option in enumerate(options, 1):
            print(f"\n[{i}] ({len(option)} chars)")
            print(option)
        print()
    else:
        print("Failed to generate milestone post")
        sys.exit(1)


def cmd_analytics(args):
    """Analytics subcommands."""
    from social import analytics

    if args.action == "pull":
        print("Pulling metrics from X API...")
        snapshot = analytics.pull_metrics()
        if snapshot:
            print(json.dumps(snapshot, indent=2))
        else:
            print("Failed to pull metrics (check X API credentials)")

    elif args.action == "report":
        report = analytics.generate_report(days=args.days)
        print(report)

    elif args.action == "baseline":
        print("Saving current metrics as baseline...")
        baseline = analytics.save_baseline()
        if baseline:
            print(json.dumps(baseline, indent=2))
        else:
            print("Failed to save baseline")

    elif args.action == "top":
        print(f"Top posts (last {args.days} days):")
        top = analytics.get_top_posts(days=args.days, limit=args.limit)
        if top:
            for i, t in enumerate(top, 1):
                print(f"\n[{i}] {t.get('impressions', 0)} impressions | "
                      f"{t.get('likes', 0)} likes | {t.get('reposts', 0)} reposts")
                print(f"    {t.get('text', '')[:100]}")
        else:
            print("No posts found")

    else:
        print(f"Unknown analytics action: {args.action}")
        sys.exit(1)


def cmd_queue(args):
    """Queue subcommands."""
    from social import scheduler

    if args.action == "list":
        items = scheduler.list_queue(status=args.status)
        if not items:
            print("Queue is empty")
            return
        print(f"Queue ({len(items)} items):")
        for item in items:
            status = item.get("status", "?")
            scheduled = item.get("scheduled_time", "ASAP")
            text_preview = item.get("text", "")[:60]
            print(f"  [{item['id']}] {status} | {scheduled} | {text_preview}...")

    elif args.action == "add":
        item_id = scheduler.add_to_queue(
            text=args.text,
            scheduled_time=args.time,
            pillar=args.pillar or "",
            content_type=args.type or "single",
        )
        if item_id:
            print(f"Added to queue: {item_id}")
        else:
            print("Failed to add to queue")

    elif args.action == "fire":
        results = scheduler.fire_due(dry_run=args.dry_run)
        if results:
            for r in results:
                print(f"  {r['id']}: {r['status']}")
        else:
            print("Nothing to fire")

    elif args.action == "remove":
        if scheduler.remove_from_queue(args.item_id):
            print(f"Removed: {args.item_id}")
        else:
            print(f"Not found: {args.item_id}")

    elif args.action == "suggest":
        times = scheduler.suggest_times(count=args.count)
        print("Suggested posting times:")
        for t in times:
            print(f"  {t}")

    elif args.action == "clear":
        removed = scheduler.clear_posted(days_old=args.days)
        print(f"Cleared {removed} old items")

    else:
        print(f"Unknown queue action: {args.action}")
        sys.exit(1)


def cmd_status(args):
    """Show current status: API connectivity, queue, and recent activity."""
    from social.x_client import get_user_metrics, get_usage_stats

    print("=== WAGMI Social Status ===\n")

    # API check
    print("X API:")
    user = get_user_metrics()
    if user:
        print(f"  Connected as: @{user.get('username', '?')}")
        print(f"  Followers: {user.get('followers', '?')}")
        print(f"  Total Tweets: {user.get('tweet_count', '?')}")
    else:
        print("  Not connected (check credentials)")

    # Usage stats
    stats = get_usage_stats()
    print(f"\n  Session Posts: {stats['total_posts']}")
    print(f"  Session Reads: {stats['total_reads']}")
    print(f"  Session Failures: {stats['total_failures']}")

    # Queue
    from social.scheduler import list_queue
    queued = list_queue(status="queued")
    print(f"\nQueue: {len(queued)} items pending")

    # Recent posts
    from social.analytics import _read_jsonl
    import os
    posts = _read_jsonl(os.path.join("data", "social", "x_posts.jsonl"))
    print(f"Logged Posts: {len(posts)} total")

    print()


def main():
    parser = argparse.ArgumentParser(
        prog="social",
        description="WAGMI X/Twitter social automation",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # post
    p_post = subparsers.add_parser("post", help="Post a tweet")
    p_post.add_argument("text", help="Tweet text")
    p_post.add_argument("--media", help="Comma-separated media file paths")
    p_post.add_argument("--pillar", help="Content pillar tag")
    p_post.add_argument("--dry-run", action="store_true", help="Don't actually post")
    p_post.set_defaults(func=cmd_post)

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate tweet hooks")
    p_gen.add_argument("--topic", required=True, help="Topic to write about")
    p_gen.add_argument("--pillar", default="trading", help="Content pillar")
    p_gen.set_defaults(func=cmd_generate)

    # thread
    p_thread = subparsers.add_parser("thread", help="Generate a thread")
    p_thread.add_argument("--topic", required=True, help="Thread topic")
    p_thread.add_argument("--pillar", default="trading", help="Content pillar")
    p_thread.add_argument("--points", help="Key points separated by |")
    p_thread.add_argument("--post", action="store_true", help="Post immediately after generating")
    p_thread.add_argument("--dry-run", action="store_true", help="Don't actually post")
    p_thread.set_defaults(func=cmd_thread)

    # chronicle
    p_chron = subparsers.add_parser("chronicle", help="Generate project update from git")
    p_chron.add_argument("--days", type=int, default=7, help="Days of history")
    p_chron.add_argument("--repo", help="Repo path (default: parent dir)")
    p_chron.set_defaults(func=cmd_chronicle)

    # milestone
    p_mile = subparsers.add_parser("milestone", help="Generate milestone announcement")
    p_mile.add_argument("milestone", help="What was achieved")
    p_mile.add_argument("--details", help="Additional context")
    p_mile.set_defaults(func=cmd_milestone)

    # analytics
    p_analytics = subparsers.add_parser("analytics", help="X analytics")
    p_analytics.add_argument("action", choices=["pull", "report", "baseline", "top"])
    p_analytics.add_argument("--days", type=int, default=7, help="Days to analyze")
    p_analytics.add_argument("--limit", type=int, default=5, help="Number of top posts")
    p_analytics.set_defaults(func=cmd_analytics)

    # queue
    p_queue = subparsers.add_parser("queue", help="Post queue management")
    p_queue.add_argument("action", choices=["list", "add", "fire", "remove", "suggest", "clear"])
    p_queue.add_argument("text", nargs="?", help="Tweet text (for 'add')")
    p_queue.add_argument("--time", help="Scheduled time ISO format (for 'add')")
    p_queue.add_argument("--pillar", help="Content pillar (for 'add')")
    p_queue.add_argument("--type", help="Content type (for 'add')")
    p_queue.add_argument("--status", help="Filter by status (for 'list')")
    p_queue.add_argument("--item-id", help="Item ID (for 'remove')")
    p_queue.add_argument("--count", type=int, default=5, help="Number of suggestions")
    p_queue.add_argument("--days", type=int, default=7, help="Days old to clear")
    p_queue.add_argument("--dry-run", action="store_true", help="Don't actually post")
    p_queue.set_defaults(func=cmd_queue)

    # status
    p_status = subparsers.add_parser("status", help="Show social module status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
