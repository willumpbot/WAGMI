"""
WAGMI Social CLI - X/Twitter growth engine.

=== DAILY WORKFLOW (do this every morning) ===
    python -m social.cli grind                          # Generate full day's content (8-12 posts)
    python -m social.cli grind --context "BTC pumping"  # With market context
    python -m social.cli today                          # View today's content plan

=== BAG MANAGEMENT ===
    python -m social.cli bag add TICKER "Name" CHAIN "why bullish"  # Add community coin
    python -m social.cli bag remove TICKER                          # Remove coin
    python -m social.cli bag list                                   # List all bags

=== CONTENT TOOLS ===
    python -m social.cli generate "topic"    # Generate tweet options
    python -m social.cli thread "topic"      # Generate a thread
    python -m social.cli signal '{json}'     # Generate signal tweet
    python -m social.cli build              # Generate build-in-public from git
    python -m social.cli call "BTC long 68k" # Generate a high-confidence call tweet

=== POSTING ===
    python -m social.cli post "text"         # Post a tweet (or --dry-run)
    python -m social.cli post-thread         # Post saved thread
    python -m social.cli queue add "text"    # Add to post queue
    python -m social.cli queue fire          # Post all due items

=== ANALYTICS & VOICE ===
    python -m social.cli analytics report    # Performance report
    python -m social.cli voice train         # Train voice from timeline
    python -m social.cli status              # Check X API connection
    python -m social.cli plan               # Show growth strategy
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from social.config import load_config
from social.x_client import XClient
from social.content_engine import ContentEngine
from social.analytics import EngagementTracker
from social.voice_trainer import VoiceTrainer
from social.daily_grind import DailyGrind
from social.alpha_feed import AlphaFeed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("social.cli")


def cmd_grind(args, grind_engine, **_):
    """Generate full day's content plan."""
    context = getattr(args, 'context', '') or ''
    topics = []
    if hasattr(args, 'topics') and args.topics:
        topics = [t.strip() for t in args.topics.split(",")]

    print("\n  Generating today's content plan...")
    print("  (This uses Claude Sonnet for quality - ~$0.01)\n")

    plan = grind_engine.generate_daily_plan(
        market_context=context,
        extra_topics=topics,
    )

    # Display the plan
    posts = plan.get("posts", [])
    summary = plan.get("day_summary", "")

    if summary:
        print(f"  Theme: {summary}\n")

    print(f"  Generated {len(posts)} posts across the day:\n")

    slot_order = ["morning", "midday", "afternoon", "evening"]
    for slot in slot_order:
        slot_posts = [p for p in posts if p.get("slot") == slot]
        if not slot_posts:
            continue

        emoji = {"morning": "AM", "midday": "NOON", "afternoon": "PM", "evening": "EVE"}.get(slot, slot.upper())
        print(f"  === [{emoji}] {slot.upper()} ===\n")

        for p in slot_posts:
            ptype = p.get("type", "?").upper()
            priority = p.get("priority", 2)
            star = "!!!" if priority == 1 else "! " if priority == 2 else "  "
            text = p.get("text", "")
            note = p.get("algo_note", "")

            print(f"  {star} [{ptype}] ({len(text)} chars)")
            print(f"  +------------------------------------------")
            for line in text.split("\n"):
                print(f"  | {line}")
            print(f"  +------------------------------------------")
            if note:
                print(f"     algo: {note}")
            print()

    # Reply targets
    targets = plan.get("reply_targets", [])
    if targets:
        print("  === REPLY GAME (throughout the day) ===\n")
        for t in targets:
            print(f"  > {t.get('target_type', '')}")
            print(f"    Approach: {t.get('reply_template', '')}")
            why = t.get("why", "")
            if why:
                print(f"    ({why})")
            print()

    grind_file = Path(__file__).parent.parent / "data" / "social" / "daily_grind.md"
    print(f"  Full plan saved to: {grind_file}")
    print(f"  Copy-paste ready. Edit before posting.\n")


def cmd_today(args, **_):
    """View today's content plan."""
    md_file = Path(__file__).parent.parent / "data" / "social" / "daily_grind.md"
    if md_file.exists():
        print(md_file.read_text())
    else:
        print("\n  No daily plan yet. Run: python -m social.cli grind\n")


def cmd_bag(args, grind_engine, **_):
    """Manage community coin bags."""
    action = args.action

    if action == "add":
        result = DailyGrind.add_bag(
            ticker=args.ticker,
            full_name=args.name,
            chain=args.chain,
            why_bullish=args.thesis,
            ca=getattr(args, 'ca', ''),
            style=getattr(args, 'style', 'organic'),
        )
        print(f"\n  {result['status'].upper()}: ${args.ticker.upper()}")
        print(f"  Thesis: {args.thesis}")
        print(f"  Style: {getattr(args, 'style', 'organic')}")
        if 'total_bags' in result:
            print(f"  Total bags: {result['total_bags']}")
        print()

    elif action == "remove":
        result = DailyGrind.remove_bag(args.ticker)
        print(f"\n  Removed ${args.ticker.upper()} from bags.")
        print(f"  Remaining bags: {result.get('remaining', 0)}\n")

    elif action == "list":
        bags = DailyGrind.list_bags()
        if not bags:
            print("\n  No bags configured. Add one:")
            print("  python -m social.cli bag add TICKER \"Name\" CHAIN \"why bullish\"\n")
            return
        print(f"\n  Community Coins ({len(bags)} bags):\n")
        for b in bags:
            ticker = b.get("ticker", "?")
            name = b.get("full_name", "")
            chain = b.get("chain", "")
            thesis = b.get("why_bullish", "")
            style = b.get("style", "organic")
            print(f"  ${ticker} ({name}) on {chain}")
            print(f"    Thesis: {thesis}")
            print(f"    Style: {style}")
            if b.get("ca"):
                print(f"    CA: {b['ca']}")
            print()


def cmd_call(args, content_engine, **_):
    """Generate a high-confidence trading call tweet."""
    call_text = args.call
    print(f"\n  Generating call tweet for: {call_text}\n")

    options = content_engine.generate_tweet(
        topic=f"Trading call: {call_text}. Make it look like a confident, specific macro call from a real trader. Include entry level, direction, and conviction. This should make my timeline look like I'm making real calls that hit.",
        pillar="ai_signals",
        context="This is a high-conviction call I want to put on my timeline as a receipt. It should be bold, specific, and timestamped by the tweet itself. Format: short, punchy, uses line breaks, includes a specific price level.",
        num_options=3,
    )

    for i, opt in enumerate(options, 1):
        text = opt.get("text", "")
        print(f"  --- Option {i} ({len(text)} chars) ---")
        print(f"  {text}")
        print()

    print("  Pick one, edit it, then post:")
    print("  python -m social.cli post \"<your edited tweet>\"")
    print()


def cmd_alpha(args, alpha_feed, **_):
    """Pull real alpha from bot data - actual trades, signals, stats."""
    hours = getattr(args, 'hours', 24) or 24

    print(f"\n  Pulling alpha from last {hours}h of bot data...\n")
    digest = alpha_feed.generate_alpha_digest(hours=hours)

    # Trade tweets
    trade_tweets = digest.get("trade_tweets", [])
    if trade_tweets:
        print(f"  === TRADE ALERTS ({len(trade_tweets)}) ===\n")
        for t in trade_tweets:
            score = t.get("algo_score", 0)
            rating = "GOOD" if score >= 60 else "FIX"
            print(f"  [{t['type'].upper()}] (algo: {score}/100 {rating})")
            print(f"  +------------------------------------------")
            for line in t["text"].split("\n"):
                print(f"  | {line}")
            print(f"  +------------------------------------------")
            if score < 60:
                for note in t.get("algo_notes", []):
                    print(f"     fix: {note}")
            print()

    # Signal tweets
    signal_tweets = digest.get("signal_tweets", [])
    if signal_tweets:
        print(f"  === SIGNAL INTEL ({len(signal_tweets)}) ===\n")
        for t in signal_tweets[:5]:  # Show top 5
            print(f"  [{t['type'].upper()}] (algo: {t.get('algo_score', 0)}/100)")
            for line in t["text"].split("\n"):
                print(f"    {line}")
            print()

    # Stats tweet
    stats = digest.get("stats_tweet")
    if stats:
        print(f"  === PERFORMANCE RECAP ===\n")
        for line in stats["text"].split("\n"):
            print(f"    {line}")
        print(f"    (algo score: {stats.get('algo_score', 0)}/100)")
        print()

    if not trade_tweets and not signal_tweets and not stats:
        print("  No alpha data available yet. Bot needs to generate trades/signals first.\n")
    else:
        print(f"  Full digest saved to: bot/data/social/alpha_digest.json")
        print(f"  Copy the tweets you like, edit them, then post.\n")


def cmd_score(args, alpha_feed, **_):
    """Score a tweet for X algorithm optimization before posting."""
    text = args.text
    result = alpha_feed.algo_score(text)

    score = result["score"]
    rating = result["rating"]

    # Color the score
    if score >= 80:
        color_word = "EXCELLENT"
    elif score >= 60:
        color_word = "GOOD"
    elif score >= 40:
        color_word = "NEEDS WORK"
    else:
        color_word = "FIX BEFORE POSTING"

    print(f"\n  Tweet Algorithm Score: {score}/100 ({color_word})")
    print(f"  Characters: {result['char_count']}/280\n")
    print(f"  Your tweet:")
    print(f"  +------------------------------------------")
    for line in text.split("\n"):
        print(f"  | {line}")
    print(f"  +------------------------------------------\n")

    print(f"  Analysis:")
    for note in result["notes"]:
        prefix = "  +" if "Good" in note or "Has" in note or "Ends" in note else "  !"
        print(f"  {prefix} {note}")
    print()

    if score < 60:
        print("  Recommendations:")
        if "numbers" in str(result["notes"]):
            print("  - Add a specific number (price, %, count)")
        if not any("question" in n.lower() for n in result["notes"] if "drives" in n.lower()):
            print("  - End with a question to drive replies (27x algo weight)")
        if result["char_count"] < 100:
            print("  - Add more substance - too short loses credibility")
        print()


def cmd_schedule(args, **_):
    """Show the optimal posting schedule for maximum impressions."""
    lines = [
        "",
        "  =====================================================",
        "  OPTIMAL POSTING SCHEDULE - X Algorithm Maximization",
        "  =====================================================",
        "",
        "  YOUR TIMEZONE MATTERS. Convert these UTC times to yours.",
        "  All times below are EST (UTC-4).",
        "",
        "  --- MAIN PAGE POSTS (your original content) ---",
        "",
        "  8:00 AM   First post of the day. Market open energy.",
        "            Best for: market scan, what you're watching, bold call",
        "            WHY: US market open = highest activity window",
        "",
        "  10:00 AM  Second post. Follow up on morning thesis.",
        "            Best for: signal alert, bot data, trade entry",
        "            WHY: Peak engagement window (8-12 EST)",
        "",
        "  12:30 PM  Midday post. Good for engagement content.",
        "            Best for: poll, hot take, question for your audience",
        "            WHY: Lunch scroll. People reply during breaks.",
        "",
        "  3:00 PM   Afternoon post. Markets moving.",
        "            Best for: trade update, receipt, momentum alert",
        "            WHY: Second peak before market close",
        "",
        "  6:00 PM   Evening post. Reflective/educational.",
        "            Best for: recap, lesson learned, build update, thread",
        "            WHY: People scrolling after work. THREADS perform best here.",
        "",
        "  9:00 PM   Night post. Casual, community-focused.",
        "            Best for: 'what are you watching tomorrow?', casual take",
        "            WHY: Before-bed scroll. Good for Asian session overlap.",
        "",
        "  --- COMMUNITY ENGAGEMENT (replies & interactions) ---",
        "",
        "  Reply to bigger accounts:  Morning + Afternoon (2 sessions, 20min each)",
        "  Reply to YOUR replies:     Within 2 HOURS of posting (critical!)",
        "  Community coin replies:    Spread throughout the day (you're doing this)",
        "  Quote-tweet receipts:      Immediately when a call hits",
        "",
        "  --- TIMING RULES (from X algorithm data) ---",
        "",
        "  1. FIRST 30 MINUTES after posting determine EVERYTHING",
        "     > Post when you can engage with replies immediately",
        "     > Don't post and disappear. Post and ENGAGE.",
        "",
        "  2. Reply to EVERY reply on your tweets within 2 hours",
        "     > Reply-to-reply = 150x a like in algorithm weight",
        "     > One good conversation > 300 likes",
        "",
        "  3. Post 6-10 times per day on main page",
        "     > Minimum 30 min between posts (avoid spam detection)",
        "     > Consistency matters more than volume",
        "     > NEVER go a day without posting (algorithm punishes gaps)",
        "",
        "  4. Community engagement is SEPARATE from main posts",
        "     > Reply to 15-20 tweets from bigger accounts daily",
        "     > Smart replies on bigger accounts = #1 growth hack",
        "     > Reply within 15 min of their post for best visibility",
        "",
        "  5. Threads: post between 5-9 PM EST",
        "     > Less competition in evening",
        "     > People have time to read longer content",
        "     > Threads get 40-60% more impressions",
        "",
        "  --- WHAT TO POST WHERE ---",
        "",
        "  MAIN PAGE (your profile):",
        "  - Bold calls with specific levels",
        "  - Bot signals / AI insights",
        "  - Trade receipts (quote your own calls)",
        "  - Market analysis",
        "  - Build updates",
        "  - Engagement polls/questions",
        "  - Threads (2-3 per week)",
        "",
        "  COMMUNITY REPLIES:",
        "  - Support for your bag coins",
        "  - Genuine engagement (not just 'great post')",
        "  - Add value: your data, your bot's take, a contrarian view",
        "  - Reply to BIG accounts in your niche",
        "",
        "  --- FREQUENCY TARGETS ---",
        "",
        "  Activity               | Daily Target | Why",
        "  ---------------------- | ------------ | ----------------------------",
        "  Main page posts        | 6-10         | Consistent presence",
        "  Replies to others      | 15-20        | Profile visits from audiences",
        "  Reply to own replies   | ALL of them  | 150x algorithm weight",
        "  Threads per week       | 2-3          | 40-60% more impressions",
        "  Quote-tweet receipts   | Every win    | Builds caller reputation",
        "",
        "  --- THE #1 RULE ---",
        "",
        "  Post when you can STAY AND ENGAGE for 30 minutes after.",
        "  The algorithm watches engagement velocity in the first",
        "  30-60 minutes. If you post and leave, the tweet dies.",
        "",
        "  =====================================================",
        "",
    ]
    print("\n".join(lines))


def cmd_status(args, x_client, **_):
    """Check X API connection status."""
    info = x_client.verify_credentials()
    if info.get("status") == "connected":
        print(f"\n  Connected as @{info['username']}")
        print(f"  Followers: {info['followers']:,}")
        print(f"  Following: {info['following']:,}")
        print(f"  Tweets: {info['tweets']:,}")
        print(f"  Bio: {info.get('description', 'N/A')[:80]}")
    elif info.get("status") == "disconnected":
        print("\n  Not connected. Add X API keys to .env file:")
        print("  X_API_KEY=...")
        print("  X_API_SECRET=...")
        print("  X_ACCESS_TOKEN=...")
        print("  X_ACCESS_SECRET=...")
        print("\n  Get keys at: https://developer.x.com")
    else:
        print(f"\n  Error: {info.get('reason', 'Unknown')}")
    print()


def cmd_generate(args, content_engine, **_):
    """Generate tweet options."""
    topic = args.topic
    pillar = args.pillar or content_engine.suggest_pillar()

    print(f"\n  Generating tweets about: {topic}")
    print(f"  Pillar: {pillar}\n")

    options = content_engine.generate_tweet(
        topic=topic,
        pillar=pillar,
        context=args.context,
        num_options=3,
    )

    for i, opt in enumerate(options, 1):
        text = opt.get("text", "")
        hook = opt.get("hook_type", "")
        print(f"  --- Option {i} [{hook}] ({len(text)} chars) ---")
        print(f"  {text}")
        print()

    print("  To post one: python -m social.cli post \"<paste tweet text>\"")
    print("  Add --dry-run to preview without posting\n")


def cmd_thread(args, content_engine, **_):
    """Generate a thread."""
    topic = args.topic
    pillar = args.pillar or "education"

    print(f"\n  Generating thread about: {topic}")
    print(f"  Pillar: {pillar}\n")

    tweets = content_engine.generate_thread(
        topic=topic,
        pillar=pillar,
        context=args.context,
    )

    for i, text in enumerate(tweets, 1):
        print(f"  --- Tweet {i}/{len(tweets)} ({len(text)} chars) ---")
        print(f"  {text}")
        print()

    # Save thread for posting
    thread_file = Path(__file__).parent.parent / "data" / "social" / "last_thread.json"
    thread_file.parent.mkdir(parents=True, exist_ok=True)
    thread_file.write_text(json.dumps(tweets, indent=2))
    print(f"  Thread saved to: {thread_file}")
    print("  To post: python -m social.cli post-thread")
    print("  Add --dry-run to preview without posting\n")


def cmd_signal(args, content_engine, **_):
    """Generate a signal tweet from bot data."""
    try:
        signal_data = json.loads(args.data)
    except json.JSONDecodeError:
        print("  Error: Invalid JSON. Provide signal data as JSON string.")
        return

    print("\n  Generating signal tweet...\n")
    tweet = content_engine.generate_signal_tweet(signal_data)
    print(f"  {tweet}")
    print(f"\n  ({len(tweet)} chars)")
    print("  To post: python -m social.cli post \"<paste>\"")
    print()


def cmd_recap(args, content_engine, **_):
    """Generate daily recap tweet."""
    try:
        perf_data = json.loads(args.data)
    except json.JSONDecodeError:
        print("  Error: Invalid JSON. Provide performance data as JSON string.")
        return

    print("\n  Generating daily recap...\n")
    tweet = content_engine.generate_daily_recap(perf_data)
    print(f"  {tweet}")
    print(f"\n  ({len(tweet)} chars)")
    print()


def cmd_build(args, content_engine, **_):
    """Generate build-in-public tweet from recent git changes."""
    print("\n  Scanning recent git changes...\n")
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10", "--no-merges"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        changes = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except Exception as e:
        print(f"  Git error: {e}")
        return

    if not changes:
        print("  No recent git changes found.")
        return

    print("  Recent changes:")
    for c in changes[:5]:
        print(f"    {c}")
    print()

    tweet = content_engine.generate_build_update(changes)
    print(f"  Generated tweet:\n  {tweet}")
    print(f"\n  ({len(tweet)} chars)")
    print("  To post: python -m social.cli post \"<paste>\"")
    print()


def cmd_post(args, x_client, tracker, **_):
    """Post a tweet."""
    text = args.text
    dry_run = args.dry_run

    if len(text) > 280:
        print(f"  Warning: Tweet is {len(text)} chars (max 280)")
        if not dry_run:
            print("  Aborting. Shorten the tweet or use --force")
            return

    mode = "DRY RUN" if dry_run else "POSTING"
    print(f"\n  [{mode}] {text[:100]}{'...' if len(text) > 100 else ''}")

    result = x_client.post_tweet(text, dry_run=dry_run)

    if result.get("status") == "posted":
        print(f"  Posted! URL: {result['url']}")
        tracker.record_post(
            tweet_id=result["tweet_id"],
            text=text,
            pillar=args.pillar or "general",
            hook_type="manual",
        )
    elif result.get("status") == "dry_run":
        print(f"  [DRY RUN] Would post: {text}")
        print(f"  Chars: {result['char_count']}")
    else:
        print(f"  Error: {result.get('reason', 'Unknown')}")
    print()


def cmd_post_thread(args, x_client, tracker, **_):
    """Post a saved thread."""
    thread_file = Path(__file__).parent.parent / "data" / "social" / "last_thread.json"
    if not thread_file.exists():
        print("  No thread saved. Generate one first: python -m social.cli thread \"topic\"")
        return

    tweets = json.loads(thread_file.read_text())
    dry_run = args.dry_run
    mode = "DRY RUN" if dry_run else "POSTING"

    print(f"\n  [{mode}] Thread with {len(tweets)} tweets:\n")
    for i, t in enumerate(tweets, 1):
        print(f"  {i}. {t[:80]}{'...' if len(t) > 80 else ''}")
    print()

    results = x_client.post_thread(tweets, dry_run=dry_run)
    for i, r in enumerate(results, 1):
        status = r.get("status", "unknown")
        print(f"  Tweet {i}: {status}")
        if r.get("url"):
            print(f"    URL: {r['url']}")

    if results and results[0].get("tweet_id"):
        tracker.record_post(
            tweet_id=results[0]["tweet_id"],
            text=tweets[0],
            pillar="thread",
            hook_type="thread",
            is_thread=True,
        )
    print()


def cmd_queue(args, x_client, **_):
    """Manage post queue."""
    action = args.action

    if action == "add":
        entry = x_client.queue_post(
            text=args.text,
            scheduled_time=args.time,
            pillar=args.pillar or "general",
        )
        print(f"\n  Queued: {entry['text'][:80]}...")
        if args.time:
            print(f"  Scheduled for: {args.time}")
        print()

    elif action == "list":
        queue = x_client.get_queue()
        if not queue:
            print("\n  Queue is empty.\n")
            return
        print(f"\n  Queue ({len(queue)} items):\n")
        for i, item in enumerate(queue, 1):
            status = item.get("status", "queued")
            time_str = item.get("scheduled_time", "ASAP")
            print(f"  {i}. [{status}] {item['text'][:60]}... (scheduled: {time_str})")
        print()

    elif action == "fire":
        results = x_client.fire_queue(dry_run=args.dry_run)
        if not results:
            print("\n  No items ready to post.\n")
            return
        mode = "DRY RUN" if args.dry_run else "POSTED"
        print(f"\n  [{mode}] {len(results)} items:")
        for r in results:
            print(f"  - {r['text'][:60]}... ({r['status']})")
        print()

    elif action == "clear":
        x_client._save_queue([])
        print("\n  Queue cleared.\n")


def cmd_analytics(args, tracker, **_):
    """Analytics commands."""
    action = args.action

    if action == "baseline":
        result = tracker.save_baseline()
        if result.get("status") == "connected":
            print(f"\n  Baseline saved!")
            print(f"  Followers: {result['followers']:,}")
            print(f"  Following: {result['following']:,}")
            print(f"  Tweets: {result['tweets']:,}")
        else:
            print(f"\n  Error: {result.get('reason', result.get('error', 'Unknown'))}")
        print()

    elif action == "pull":
        count = tracker.pull_metrics(hours_old=getattr(args, 'hours', 24))
        print(f"\n  Updated metrics for {count} tweets.\n")

    elif action == "report":
        report = tracker.get_performance_report()
        if report.get("status") == "no_data":
            print(f"\n  {report['message']}\n")
            return

        print(f"\n  === Content Performance Report ===")
        print(f"  Tracked tweets: {report['total_tracked']}\n")

        print("  By Pillar:")
        for pillar, data in report.get("by_pillar", {}).items():
            print(f"    {pillar}: {data['count']} tweets, "
                  f"avg {data['avg_impressions']:.0f} impressions, "
                  f"algo score {data['algo_score']:.0f}")

        print("\n  By Hour (UTC):")
        for hour, data in list(report.get("by_hour", {}).items())[:5]:
            print(f"    {hour}:00: algo score {data['algo_score']:.0f} ({data['count']} tweets)")

        print("\n  Top Tweets:")
        for t in report.get("top_tweets", [])[:3]:
            print(f"    [{t['pillar']}] {t['text'][:60]}... "
                  f"(impressions: {t['impressions']}, algo: {t['algo_score']:.0f})")

        print("\n  Recommendations:")
        for r in report.get("recommendations", []):
            print(f"    - {r}")

        growth = report.get("growth", {})
        if growth.get("baseline_followers"):
            print(f"\n  Growth: {growth['baseline_followers']} -> {growth['current_followers']} "
                  f"(+{growth['follower_growth']})")
        print()

    elif action == "snapshot":
        result = tracker.weekly_snapshot()
        if result.get("status") == "connected":
            print(f"\n  Weekly snapshot saved!")
            print(f"  Followers: {result['followers']:,}")
            print(f"  Tweets this week: {result.get('tweets_this_week', 0)}")
        else:
            print(f"\n  Error: {result.get('reason', result.get('error', 'Unknown'))}")
        print()


def cmd_voice(args, voice_trainer, content_engine, **_):
    """Voice training commands."""
    action = args.action

    if action == "train":
        print("\n  Training voice profile from your timeline...\n")
        profile = voice_trainer.train_from_timeline(num_tweets=50)
        if profile.get("error"):
            print(f"  Error: {profile['error']}")
            if profile.get("instructions"):
                for inst in profile["instructions"]:
                    print(f"  {inst}")
        else:
            print(f"  Voice profile trained from {profile.get('sample_size', 0)} tweets!")
            print(f"  Tone: {profile.get('tone', 'N/A')}")
            print(f"  Style rules:")
            for rule in profile.get("style_rules", []):
                print(f"    - {rule}")
            print(f"\n  Signature words: {', '.join(profile.get('signature_words', [])[:10])}")
            content_engine.voice_profile = profile
        print()

    elif action == "train-manual":
        print("\n  Manual voice training.")
        print("  Paste your best tweets, one per line. Enter empty line when done:\n")
        tweets = []
        while True:
            try:
                line = input("  > ").strip()
                if not line:
                    break
                tweets.append(line)
            except (EOFError, KeyboardInterrupt):
                break

        if tweets:
            profile = voice_trainer.train_from_samples(tweets)
            print(f"\n  Trained from {len(tweets)} samples!")
            print(f"  Tone: {profile.get('tone', 'N/A')}")
            content_engine.voice_profile = profile
        else:
            print("  No tweets provided.")
        print()

    elif action == "show":
        profile_file = Path(__file__).parent.parent / "data" / "social" / "voice_profile.json"
        if profile_file.exists():
            profile = json.loads(profile_file.read_text())
            print(f"\n  Voice Profile:")
            print(f"  Persona: {profile.get('persona', 'N/A')}")
            print(f"  Tone: {profile.get('tone', 'N/A')}")
            print(f"  Sample size: {profile.get('sample_size', 'N/A')}")
            print(f"  Trained at: {profile.get('trained_at', 'N/A')}")
            print(f"\n  Style rules:")
            for rule in profile.get("style_rules", []):
                print(f"    - {rule}")
            print(f"\n  Example tweets: {len(profile.get('example_tweets', []))}")
            for t in profile.get("example_tweets", [])[:3]:
                print(f"    \"{t[:80]}{'...' if len(t) > 80 else ''}\"")
        else:
            print("\n  No voice profile yet. Run 'voice train' or 'voice train-manual'")
        print()


def cmd_plan(args, **_):
    """Show the X growth strategy."""
    plan_file = Path(__file__).parent.parent / "social" / "X_GROWTH_STRATEGY.md"
    if not plan_file.exists():
        plan_file = Path(__file__).parent / "X_GROWTH_STRATEGY.md"
    if plan_file.exists():
        print(plan_file.read_text())
    else:
        print("\n  Growth strategy file not found.")
        print("  See X_ALGORITHM_RESEARCH.md in project root for full research.\n")


def main():
    parser = argparse.ArgumentParser(description="WAGMI Social - X Growth Engine")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # === DAILY WORKFLOW (most important) ===
    grind = subparsers.add_parser("grind", help="Generate full day's content (8-12 posts)")
    grind.add_argument("--context", "-c", help="Market context (e.g. 'BTC pumping, ETH lagging')")
    grind.add_argument("--topics", "-t", help="Extra topics, comma-separated")

    # today
    subparsers.add_parser("today", help="View today's content plan")

    # bag management
    bag = subparsers.add_parser("bag", help="Manage community coin bags")
    bag_sub = bag.add_subparsers(dest="action")
    bag_add = bag_sub.add_parser("add", help="Add a bag")
    bag_add.add_argument("ticker", help="Coin ticker (e.g. PEPE)")
    bag_add.add_argument("name", help="Full name (e.g. 'Pepe')")
    bag_add.add_argument("chain", help="Chain (e.g. ETH, SOL, BASE)")
    bag_add.add_argument("thesis", help="Why bullish (1-liner)")
    bag_add.add_argument("--ca", help="Contract address", default="")
    bag_add.add_argument("--style", choices=["organic", "direct", "alpha"], default="organic")
    bag_rm = bag_sub.add_parser("remove", help="Remove a bag")
    bag_rm.add_argument("ticker", help="Coin ticker to remove")
    bag_sub.add_parser("list", help="List all bags")

    # call - quick high-confidence trade call
    call_cmd = subparsers.add_parser("call", help="Generate a trade call tweet")
    call_cmd.add_argument("call", help="The call (e.g. 'BTC long 68k target 72k')")

    # alpha - pull real data from bot
    alpha_cmd = subparsers.add_parser("alpha", help="Pull real alpha from bot data")
    alpha_cmd.add_argument("--hours", type=int, default=24, help="Hours to look back")

    # score - check any tweet before posting
    score_cmd = subparsers.add_parser("score", help="Score a tweet for X algorithm")
    score_cmd.add_argument("text", help="Tweet text to score")

    # schedule - when to post
    subparsers.add_parser("schedule", help="Show optimal posting schedule")

    # status
    subparsers.add_parser("status", help="Check X API connection")

    # generate
    gen = subparsers.add_parser("generate", help="Generate tweet options")
    gen.add_argument("topic", help="Topic to tweet about")
    gen.add_argument("--pillar", choices=["ai_signals", "bags", "engagement", "build_public", "education", "receipts"])
    gen.add_argument("--context", help="Additional context")

    # thread
    thread = subparsers.add_parser("thread", help="Generate a thread")
    thread.add_argument("topic", help="Thread topic")
    thread.add_argument("--pillar", choices=["ai_signals", "bags", "engagement", "build_public", "education", "receipts"])
    thread.add_argument("--context", help="Additional context")

    # signal
    sig = subparsers.add_parser("signal", help="Generate signal tweet")
    sig.add_argument("data", help="Signal data as JSON")

    # recap
    recap = subparsers.add_parser("recap", help="Generate daily recap")
    recap.add_argument("data", help="Performance data as JSON")

    # build
    subparsers.add_parser("build", help="Generate build-in-public tweet from git")

    # post
    post = subparsers.add_parser("post", help="Post a tweet")
    post.add_argument("text", help="Tweet text")
    post.add_argument("--dry-run", action="store_true", help="Preview without posting")
    post.add_argument("--pillar", help="Content pillar tag")

    # post-thread
    pt = subparsers.add_parser("post-thread", help="Post saved thread")
    pt.add_argument("--dry-run", action="store_true", help="Preview without posting")

    # queue
    queue = subparsers.add_parser("queue", help="Manage post queue")
    queue_sub = queue.add_subparsers(dest="action")
    q_add = queue_sub.add_parser("add", help="Add to queue")
    q_add.add_argument("text", help="Tweet text")
    q_add.add_argument("--time", help="Scheduled time (ISO format)")
    q_add.add_argument("--pillar", help="Content pillar")
    queue_sub.add_parser("list", help="View queue")
    q_fire = queue_sub.add_parser("fire", help="Post due items")
    q_fire.add_argument("--dry-run", action="store_true")
    queue_sub.add_parser("clear", help="Clear queue")

    # analytics
    analytics = subparsers.add_parser("analytics", help="Engagement analytics")
    analytics_sub = analytics.add_subparsers(dest="action")
    analytics_sub.add_parser("baseline", help="Save baseline metrics")
    pull = analytics_sub.add_parser("pull", help="Pull tweet metrics")
    pull.add_argument("--hours", type=int, default=24, help="Min hours old")
    analytics_sub.add_parser("report", help="Performance report")
    analytics_sub.add_parser("snapshot", help="Weekly snapshot")

    # voice
    voice = subparsers.add_parser("voice", help="Voice training")
    voice_sub = voice.add_subparsers(dest="action")
    voice_sub.add_parser("train", help="Train from timeline")
    voice_sub.add_parser("train-manual", help="Train from pasted tweets")
    voice_sub.add_parser("show", help="Show voice profile")

    # plan
    subparsers.add_parser("plan", help="Show growth strategy")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Initialize components
    x_config, content_config, analytics_config = load_config()
    x_client = XClient(x_config)
    content_engine = ContentEngine(content_config)
    tracker = EngagementTracker(x_client)
    voice_trainer = VoiceTrainer(x_client)
    grind_engine = DailyGrind(content_config)
    alpha_feed = AlphaFeed()

    # Route to command
    commands = {
        "grind": cmd_grind,
        "today": cmd_today,
        "bag": cmd_bag,
        "call": cmd_call,
        "alpha": cmd_alpha,
        "score": cmd_score,
        "schedule": cmd_schedule,
        "status": cmd_status,
        "generate": cmd_generate,
        "thread": cmd_thread,
        "signal": cmd_signal,
        "recap": cmd_recap,
        "build": cmd_build,
        "post": cmd_post,
        "post-thread": cmd_post_thread,
        "queue": cmd_queue,
        "analytics": cmd_analytics,
        "voice": cmd_voice,
        "plan": cmd_plan,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(
            args=args,
            x_client=x_client,
            content_engine=content_engine,
            tracker=tracker,
            voice_trainer=voice_trainer,
            grind_engine=grind_engine,
            alpha_feed=alpha_feed,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
