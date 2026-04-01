"""
Social Telegram Bot - Fully automated X/Twitter growth engine.

YOU DO NOTHING except copy-paste to Twitter and reply to people.

Every 1-2 hours, this bot sends you a ready-to-post tweet.
It pulls real data from your trading bot, generates content,
and tells you exactly what to post and WHY it'll perform well.

Each message includes:
  - The tweet (copy-paste ready)
  - Algo score (so you know it's optimized)
  - A quick algo tip (so you learn the game over time)
  - What kind of engagement to do after posting

Usage:
    cd bot && python -m social.telegram_bot

That's it. It runs forever. You just post what it sends you.

Optional commands (if you ever want them):
    /xscore <text>   - Score a tweet before posting
    /xnow            - Give me a tweet right now
    /xpause          - Pause notifications
    /xresume         - Resume notifications
"""
import json
import logging
import os
import random
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("social.telegram")

# Algo tips - one gets attached to each notification so you learn over time
ALGO_TIPS = [
    "ALGO TIP: Reply-to-reply = 150x a like. When someone replies to your tweet, ALWAYS reply back. That conversation is worth more than 300 likes.",
    "ALGO TIP: First 30 minutes after posting determine everything. Post when you can stay and engage, not when you're about to leave.",
    "ALGO TIP: Links in main tweet = -50% reach. If you need to share a link, put it in a SELF-REPLY, not the main tweet.",
    "ALGO TIP: Bookmarks are 20x a like. Write tweets people want to SAVE - data, frameworks, specific numbers, actionable insight.",
    "ALGO TIP: 3+ hashtags = -40% reach. Use max 1 hashtag, and prefer $CASHTAGS over #hashtags. $BTC > #Bitcoin.",
    "ALGO TIP: Threads get 40-60% more impressions than standalone tweets. Post threads in the evening (5-9 PM) when people have time to read.",
    "ALGO TIP: Text tweets outperform video on X (0.48% vs 0.41% engagement). Don't feel pressured to make videos.",
    "ALGO TIP: Engagement bait ('like if you agree') gets PENALIZED by the algorithm. Never do it. Ask genuine questions instead.",
    "ALGO TIP: Questions drive replies (27x). End tweets with a question when possible. 'What levels are you watching?' works every time.",
    "ALGO TIP: Replying to bigger accounts within 15 minutes of their post = maximum visibility. Their audience sees YOUR reply.",
    "ALGO TIP: Never go a day without posting. The algorithm punishes gaps. Even one tweet on a busy day keeps your distribution alive.",
    "ALGO TIP: Quote-tweeting your own calls when they hit is THE credibility builder on CT. Always save your call tweets for receipts.",
    "ALGO TIP: Polls get 1.5-3% engagement rate - highest of any format. Use them for midday engagement.",
    "ALGO TIP: Your TweepCred score (hidden 0-100) determines distribution. Engage with larger accounts to improve it.",
    "ALGO TIP: Contrarian takes during extreme sentiment get massive engagement. When everyone's bearish, post your bull case (if you have one).",
    "ALGO TIP: X Premium gives ~10x reach boost. If you don't have it, get it. It's the single biggest lever for impressions.",
    "ALGO TIP: Retweets = 40x a like. Write tweets so good that people want to share them with THEIR audience. Data + bold take = RT magnet.",
    "ALGO TIP: Specific numbers build trust. '$BTC at 67.2k' beats 'BTC looking strong'. Always include prices, percentages, counts.",
    "ALGO TIP: Post at 8-12 EST for maximum reach (US market open). Second peak is 3-5 PM EST. Evenings are best for threads.",
    "ALGO TIP: One genuine conversation thread on your tweet is worth more to the algorithm than 300 likes. Engage with every reply.",
    "MONETIZATION: At 1K followers, start a free Telegram group with your bot signals. Build community before charging.",
    "MONETIZATION: At 5K followers, exchange referral links ($20-50 per signup) become real money. Add them to your pinned tweet self-reply.",
    "MONETIZATION: At 15K+, paid signal groups ($50-300/month) work. 200 members at $100/month = $20K/month.",
    "MONETIZATION: Your AI trading bot IS a product. At scale, let others subscribe to its signals or use it. SaaS is the endgame.",
    "MONETIZATION: KOL rounds - projects give early token allocations to influential accounts. $50K-500K per cycle at scale.",
]


class SocialTelegramBot:
    """
    Fully automated X growth assistant.
    Sends ready-to-post tweets at optimal times. You just copy-paste.
    """

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.allowed_user = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", "0"))
        self.tz_offset = int(os.getenv("X_TIMEZONE_OFFSET", "-4"))

        if not self.token:
            logger.error("TELEGRAM_TOKEN not set in .env")
        if not self.chat_id:
            logger.error("TELEGRAM_CHAT_ID not set in .env")

        self._base_url = f"https://api.telegram.org/bot{self.token}"
        self._offset = 0
        self._running = False
        self._paused = False
        self._sent_today = {}
        self._tip_index = 0

        self._alpha_feed = None
        self._content_engine = None

    @property
    def alpha_feed(self):
        if self._alpha_feed is None:
            from social.alpha_feed import AlphaFeed
            self._alpha_feed = AlphaFeed()
        return self._alpha_feed

    @property
    def content_engine(self):
        if self._content_engine is None:
            from social.config import load_config
            from social.content_engine import ContentEngine
            _, content_config, _ = load_config()
            self._content_engine = ContentEngine(content_config)
        return self._content_engine

    # ==========================================
    # CORE
    # ==========================================

    def start(self):
        if not self.token:
            logger.error("Cannot start: no Telegram token")
            return

        self._running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._schedule_loop, daemon=True).start()
        logger.info("Social Telegram bot started")

        self._send(
            "X Growth Bot online.\n\n"
            "I'll send you ready-to-post tweets throughout the day.\n"
            "Just copy-paste to Twitter and engage with replies.\n\n"
            "You don't need to do anything. Tweets come to you.\n\n"
            f"{self._next_tip()}"
        )

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self._running = False
            logger.info("Bot stopped")

    def _send(self, text: str):
        import requests
        if not self.token or not self.chat_id:
            return
        # Split long messages
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            try:
                requests.post(
                    f"{self._base_url}/sendMessage",
                    json={"chat_id": self.chat_id, "text": chunk},
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"Send failed: {e}")

    def _reply(self, chat_id: int, text: str):
        import requests
        try:
            requests.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Reply failed: {e}")

    def _next_tip(self) -> str:
        tip = ALGO_TIPS[self._tip_index % len(ALGO_TIPS)]
        self._tip_index += 1
        return tip

    def _local_hour(self) -> int:
        return (datetime.now(timezone.utc).hour + self.tz_offset) % 24

    # ==========================================
    # COMMAND POLLING (minimal - mostly automated)
    # ==========================================

    def _poll_loop(self):
        import requests
        while self._running:
            try:
                resp = requests.get(
                    f"{self._base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 10},
                    timeout=15,
                )
                if resp.status_code != 200:
                    time.sleep(5)
                    continue
                for update in resp.json().get("result", []):
                    self._offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    self._handle_message(msg)
            except Exception:
                time.sleep(5)

    def _handle_message(self, msg: dict):
        chat_id = msg.get("chat", {}).get("id")
        user_id = msg.get("from", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not text or not chat_id:
            return
        if self.allowed_user and user_id != self.allowed_user:
            return

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "/xscore":
            if not args:
                self._reply(chat_id, "Send: /xscore <your tweet text>")
                return
            result = self.alpha_feed.algo_score(args)
            score = result["score"]
            lines = [
                f"SCORE: {score}/100 ({result['rating']})",
                f"Chars: {result['char_count']}/280\n",
                args, "",
            ]
            for n in result["notes"]:
                lines.append(f"{'+ ' if any(w in n for w in ['Good','Has','Ends']) else '! '}{n}")
            self._reply(chat_id, "\n".join(lines))

        elif cmd == "/xnow":
            self._reply(chat_id, "Generating tweet...")
            tweet = self._generate_tweet_for_slot(self._current_slot())
            self._reply(chat_id, tweet)

        elif cmd == "/xpause":
            self._paused = True
            self._reply(chat_id, "Notifications paused. Send /xresume to restart.")

        elif cmd == "/xresume":
            self._paused = False
            self._reply(chat_id, "Notifications resumed.")

        elif cmd == "/xhelp" or cmd == "/x":
            self._reply(chat_id,
                "X GROWTH BOT\n\n"
                "This bot is mostly automated. Tweets come to you.\n\n"
                "/xscore <text> - Score a tweet before posting\n"
                "/xnow - Give me a tweet right now\n"
                "/xpause - Pause notifications\n"
                "/xresume - Resume\n\n"
                "Everything else is automatic."
            )

    # ==========================================
    # SCHEDULED TWEET DELIVERY
    # ==========================================

    def _schedule_loop(self):
        """Send ready tweets at optimal times. Fully automated."""
        # Schedule: (local_hour, local_min, slot_name)
        schedule = [
            (8,  0,  "morning_1"),     # Market open - first post
            (10, 0,  "morning_2"),     # Follow-up / signal
            (12, 30, "midday"),        # Engagement post
            (15, 0,  "afternoon"),     # Trade update / receipt
            (18, 0,  "evening"),       # Recap / thread / build
            (21, 0,  "night"),         # Casual community post
        ]

        while self._running:
            try:
                if self._paused:
                    time.sleep(60)
                    continue

                now_utc = datetime.now(timezone.utc)
                local_h = (now_utc.hour + self.tz_offset) % 24
                local_m = now_utc.minute
                today = now_utc.strftime("%Y-%m-%d")

                for target_h, target_m, slot in schedule:
                    key = f"{today}_{slot}"
                    if key in self._sent_today:
                        continue
                    if local_h == target_h and abs(local_m - target_m) <= 2:
                        self._sent_today[key] = True
                        # Clean old entries
                        for k in list(self._sent_today):
                            if not k.startswith(today):
                                del self._sent_today[k]
                        # Generate and send
                        self._send_scheduled_tweet(slot)

                time.sleep(45)
            except Exception as e:
                logger.warning(f"Schedule error: {e}")
                time.sleep(60)

    def _current_slot(self) -> str:
        h = self._local_hour()
        if h < 9:
            return "morning_1"
        elif h < 12:
            return "morning_2"
        elif h < 14:
            return "midday"
        elif h < 17:
            return "afternoon"
        elif h < 20:
            return "evening"
        else:
            return "night"

    def _send_scheduled_tweet(self, slot: str):
        """Generate and send a ready-to-post tweet for the given time slot."""
        try:
            tweet_msg = self._generate_tweet_for_slot(slot)
            self._send(tweet_msg)
        except Exception as e:
            logger.error(f"Failed to generate tweet for {slot}: {e}")
            self._send(f"Tweet generation failed for {slot}. Post something manually!")

    def _generate_tweet_for_slot(self, slot: str) -> str:
        """Generate a complete ready-to-post message for a time slot."""

        # Try to get real bot data first
        digest = self.alpha_feed.generate_alpha_digest(hours=12)
        trade_tweets = digest.get("trade_tweets", [])
        stats = digest.get("stats_tweet")
        signal_tweets = digest.get("signal_tweets", [])

        # Get recent git changes for build content
        git_changes = self._get_git_changes()

        tweet_text = ""
        post_type = ""
        after_action = ""

        if slot == "morning_1":
            # Morning: market scan or bold call from real data
            post_type = "MORNING POST (8 AM - peak window)"
            after_action = "Stay and engage for 30 min. Reply to every reply."

            if trade_tweets:
                # Use real trade data
                best = max(trade_tweets, key=lambda t: t.get("algo_score", 0))
                tweet_text = best["text"]
            else:
                # Generate a market-aware tweet
                tweet_text = self._generate_with_llm(
                    "morning market scan",
                    "Write a morning market scan tweet. Include specific price levels for BTC/ETH/SOL. "
                    "Be opinionated about direction. End with what you're watching today."
                )

        elif slot == "morning_2":
            # Second morning post: signal or call
            post_type = "MID-MORNING (10 AM - still peak)"
            after_action = "If this is a call, SAVE it. You'll quote-tweet it later as a receipt."

            if signal_tweets:
                best = max(signal_tweets, key=lambda t: t.get("algo_score", 0))
                tweet_text = best["text"]
            elif trade_tweets:
                # Use a trade we haven't used yet
                tweet_text = trade_tweets[-1]["text"]
            else:
                tweet_text = self._generate_with_llm(
                    "trading signal or setup",
                    "Write a tweet about a trading setup or signal you're watching. "
                    "Include specific entry, target, and why. Be bold and specific."
                )

        elif slot == "midday":
            # Midday: ENGAGEMENT post (polls, questions, hot takes)
            post_type = "MIDDAY ENGAGEMENT (12:30 PM)"
            after_action = "This post is for REPLIES. Engage with every response for 30 min."

            tweet_text = self._generate_with_llm(
                "engagement post",
                "Write a crypto Twitter engagement post. Choose ONE format:\n"
                "1. A poll question about market direction\n"
                "2. A hot take that will make people respond\n"
                "3. A 'what are you watching?' community question\n"
                "4. A contrarian take on current market consensus\n\n"
                "The goal is REPLIES, not likes. End with a question. Keep it punchy."
            )

        elif slot == "afternoon":
            # Afternoon: receipts, trade updates, momentum
            post_type = "AFTERNOON (3 PM - second peak)"
            after_action = "If any morning calls hit, QUOTE-TWEET them now with the result."

            if trade_tweets:
                # Prioritize winning trades for receipts
                winners = [t for t in trade_tweets if "+$" in t.get("text", "")]
                if winners:
                    tweet_text = winners[0]["text"]
                else:
                    tweet_text = trade_tweets[0]["text"]
            elif stats:
                tweet_text = stats["text"]
            else:
                tweet_text = self._generate_with_llm(
                    "afternoon market update",
                    "Write an afternoon market update tweet. Cover what happened today, "
                    "key levels that held or broke, and what you're watching into close."
                )

        elif slot == "evening":
            # Evening: recap, build update, or thread hook
            post_type = "EVENING (6 PM - best for threads & build updates)"
            after_action = "If you have time, post a thread (3-5 tweets). Threads get 40-60% more impressions."

            if git_changes:
                tweet_text = self._generate_with_llm(
                    "build in public",
                    f"Write a 'building in public' tweet about these recent code changes to my AI trading bot:\n"
                    f"{chr(10).join(git_changes[:5])}\n\n"
                    "Pick the most interesting change. Make it sound exciting but real. "
                    "Show you're actually building something, not just talking."
                )
            elif stats:
                tweet_text = stats["text"] + "\n\nGrinding. More tomorrow."
            else:
                tweet_text = self._generate_with_llm(
                    "evening recap or lesson",
                    "Write an evening recap tweet. Either:\n"
                    "1. What you learned today from the markets\n"
                    "2. A lesson from your AI trading bot development\n"
                    "3. A framework or insight worth saving\n"
                    "Make it bookmark-worthy. People save evening content."
                )

        elif slot == "night":
            # Night: casual, community, tomorrow setup
            post_type = "NIGHT (9 PM - casual)"
            after_action = "Keep it light. This sets up tomorrow's engagement."

            tweet_text = self._generate_with_llm(
                "night casual post",
                "Write a casual night tweet. Options:\n"
                "1. 'What's everyone watching tomorrow?'\n"
                "2. Quick market thought for overnight\n"
                "3. Something personal about the grind\n"
                "Keep it short and genuine. Under 150 chars ideally."
            )

        # Score the tweet
        if tweet_text:
            score_result = self.alpha_feed.algo_score(tweet_text)
            score = score_result["score"]
            rating = score_result["rating"]
        else:
            tweet_text = "Could not generate tweet. Post something manually!"
            score = 0
            rating = "N/A"

        # Build the full message
        tip = self._next_tip()

        fixes = ""
        if score < 60 and tweet_text:
            fix_notes = [n for n in score_result.get("notes", [])
                        if not any(w in n for w in ["Good", "Has", "Ends"])]
            if fix_notes:
                fixes = "\nFIX BEFORE POSTING:\n" + "\n".join(f"! {n}" for n in fix_notes[:3]) + "\n"

        msg = (
            f"--- {post_type} ---\n\n"
            f"COPY THIS TWEET:\n\n"
            f"{tweet_text}\n\n"
            f"---\n"
            f"Algo score: {score}/100 ({rating})\n"
            f"Chars: {len(tweet_text)}/280\n"
            f"{fixes}\n"
            f"AFTER POSTING: {after_action}\n\n"
            f"{tip}"
        )

        return msg

    def _generate_with_llm(self, topic: str, instruction: str) -> str:
        """Generate a tweet using Claude. Falls back to template if unavailable."""
        try:
            options = self.content_engine.generate_tweet(
                topic=topic,
                pillar="ai_signals",
                context=instruction,
                num_options=1,
            )
            if options and options[0].get("text"):
                text = options[0]["text"]
                # Verify it's under 280 chars
                if len(text) <= 280:
                    return text
                # Truncate intelligently
                return text[:277] + "..."
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")

        # Fallback templates
        fallbacks = {
            "morning market scan": "Markets waking up. Scanning for setups.\n\nWhat's on your radar today?",
            "trading signal or setup": "Running the 9-agent system. Will share if anything triggers.\n\nPatience > FOMO.",
            "engagement post": "What's your highest conviction play right now?\n\nGenuinely curious what everyone's watching.",
            "afternoon market update": "Afternoon scan complete. Watching key levels into close.\n\nAnyone catch a good move today?",
            "build in public": "Still building the AI trading bot. Every day it gets sharper.\n\nThe grind is the edge.",
            "evening recap or lesson": "Market lesson of the day: discipline beats conviction.\n\nWhat did you learn today?",
            "night casual post": "Calling it a night. Markets never sleep but we should.\n\nWhat's on the watchlist tomorrow?",
        }
        return fallbacks.get(topic, "What's everyone watching? Drop your plays below.")

    def _get_git_changes(self) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-5", "--no-merges"],
                capture_output=True, text=True, timeout=5,
                cwd=str(Path(__file__).parent.parent.parent),
            )
            return [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        except Exception:
            return []


def main():
    bot = SocialTelegramBot()
    bot.start()


if __name__ == "__main__":
    main()
