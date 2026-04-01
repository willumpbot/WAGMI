"""
Content generation engine — uses Claude to create X-algorithm-optimized content.

Key algorithm facts baked into every generation:
- Bookmarks = 20x a like, replies = 27x, retweets = 40x, reply-to-reply = 150x
- Links in main tweet = 30-50% reach penalty (put in self-reply)
- 3+ hashtags = 40% penalty
- Threads get 40-60% more impressions than standalone tweets
- First 30-60 minutes of engagement velocity determine everything
- Text outperforms video on X (0.48% vs 0.41% engagement rate)
- Optimal tweet length ~240 chars for single tweets
"""
import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("social.content_engine")

# Voice samples directory
VOICE_DIR = Path(__file__).parent.parent / "data" / "social" / "voice_samples"
DATA_DIR = Path(__file__).parent.parent / "data" / "social"


class ContentEngine:
    """Generate algorithm-optimized content using Claude."""

    def __init__(self, content_config, voice_profile: Optional[dict] = None):
        self.config = content_config
        self.voice_profile = voice_profile or self._load_voice_profile()
        self._llm_client = None

    def _get_llm_client(self):
        """Lazy-load LLM client to avoid circular imports."""
        if self._llm_client is None:
            try:
                from anthropic import Anthropic
                self._llm_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            except ImportError:
                logger.error("anthropic package not installed")
                return None
        return self._llm_client

    def _load_voice_profile(self) -> dict:
        """Load voice profile from saved samples."""
        profile_file = DATA_DIR / "voice_profile.json"
        if profile_file.exists():
            try:
                return json.loads(profile_file.read_text())
            except Exception:
                pass
        return self._default_voice_profile()

    def _default_voice_profile(self) -> dict:
        """Default voice profile for WAGMI bot builder persona."""
        return {
            "persona": "crypto trader and builder. building an AI trading bot with 9 specialist agents. makes macro calls for his community. genuine person who cares about helping people win. builder first, trader second.",
            "tone": "real, genuine, confident but not arrogant. talks to people like friends. shares alpha because he wants his boys to eat. builder energy — always working on something. mixes insight with personality.",
            "style_rules": [
                "always use specific numbers (up 12%, not 'up a lot')",
                "short paragraphs, one idea per line",
                "line breaks for readability",
                "talk like a real person, not a finance bro or AI",
                "never use corporate language",
                "show the work, not just the conclusion",
                "be opinionated but not reckless with people's money",
                "genuinely care about the community — this comes through in the writing",
                "mix technical builder content with human moments",
                "when making calls, be specific and own it — no wishy-washy hedging",
            ],
            "never_say": self.config.banned_phrases,
            "signature_formats": [
                "calls for the boys: 'flagging $X here, bot sees [setup]. entry and targets in thread'",
                "agent decision reveals: 'Trade agent wanted to long X but Critic vetoed. Critic was right.'",
                "builder updates: 'shipped [feature] at 3am. couldn't sleep until it worked.'",
                "alpha drops: 'ran the numbers on 500 trades. the edge is in [insight].'",
                "receipts: quote your own call tweet when it hits",
                "community love: 'hope everyone caught that move. more coming.'",
            ],
            "example_tweets": [],  # Populated from your actual tweets later
        }

    def save_voice_profile(self, profile: dict):
        """Save updated voice profile."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "voice_profile.json").write_text(json.dumps(profile, indent=2))
        self.voice_profile = profile

    def add_voice_samples(self, tweets: list[str]):
        """Add real tweets as voice samples for few-shot prompting."""
        self.voice_profile["example_tweets"] = (
            self.voice_profile.get("example_tweets", []) + tweets
        )[-20:]  # Keep last 20 samples
        self.save_voice_profile(self.voice_profile)

    # --- Core generation methods ---

    def generate_tweet(self, topic: str, pillar: str = "ai_signals",
                       context: Optional[str] = None, num_options: int = 3) -> list[dict]:
        """
        Generate tweet options optimized for X algorithm.
        Returns list of {text, pillar, hook_type, estimated_engagement} dicts.
        """
        client = self._get_llm_client()
        if not client:
            return [{"text": f"[LLM unavailable] {topic}", "pillar": pillar}]

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_tweet_prompt(topic, pillar, context, num_options)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",  # Sonnet for quality content
                max_tokens=1500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return self._parse_tweet_options(response.content[0].text, pillar)
        except Exception as e:
            logger.error(f"Content generation failed: {e}")
            return []  # Return empty so callers use their own fallbacks

    def generate_thread(self, topic: str, pillar: str = "education",
                        context: Optional[str] = None) -> list[str]:
        """
        Generate a thread (3-8 tweets) optimized for algorithm boost.
        First tweet = hook (gets 80% of impressions). Must be strong.
        """
        client = self._get_llm_client()
        if not client:
            return [f"[LLM unavailable] Thread about: {topic}"]

        system_prompt = self._build_system_prompt()
        user_prompt = f"""Generate a Twitter THREAD about: {topic}

THREAD RULES (from X algorithm data):
- Threads get 40-60% more impressions than standalone tweets
- First tweet gets 80% of impressions — the hook MUST be strong
- Optimal length: 4-7 tweets
- Each tweet should be self-contained enough to screenshot
- NO "1/" or "Thread 🧵" or "In this thread" — these are AI tells
- Last tweet should be a call-to-action (follow for more, save this, what do you think?)
- Use line breaks within tweets for readability

PILLAR: {pillar}
{"CONTEXT: " + context if context else ""}

Output as JSON array of strings, each string is one tweet in the thread.
Example: ["Hook tweet here", "Second point...", "Third point...", "CTA tweet"]
"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            tweets = self._parse_thread(response.content[0].text)
            # Humanize each tweet
            return [self._humanize(t) for t in tweets]
        except Exception as e:
            logger.error(f"Thread generation failed: {e}")
            return [f"[Generation failed] {topic}"]

    def generate_signal_tweet(self, signal_data: dict) -> str:
        """
        Generate a tweet about a bot signal. This is the core "What My AI Sees" content.
        Uses signal data from the trading bot.
        """
        client = self._get_llm_client()
        if not client:
            return self._fallback_signal_tweet(signal_data)

        system_prompt = self._build_system_prompt()
        user_prompt = f"""Generate a tweet about this trading bot signal. Make it sound like a real trader sharing a live call, NOT a bot announcement.

SIGNAL DATA:
{json.dumps(signal_data, indent=2, default=str)}

RULES:
- Lead with the call: symbol, direction, key level
- Include the AI angle: "My 9-agent system flagged this" or "Bot's Regime agent sees X"
- Use specific numbers from the signal (confidence, entry, targets)
- Keep under 280 chars
- NO "not financial advice" or hedging language
- Be confident but not reckless
- If there's an interesting agent disagreement, highlight it (great engagement driver)

Output just the tweet text, nothing else."""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # Haiku for fast signal tweets
                max_tokens=400,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return self._humanize(response.content[0].text.strip())
        except Exception as e:
            logger.error(f"Signal tweet generation failed: {e}")
            return self._fallback_signal_tweet(signal_data)

    def generate_daily_recap(self, performance_data: dict) -> str:
        """Generate daily performance recap tweet."""
        client = self._get_llm_client()
        if not client:
            return self._fallback_recap(performance_data)

        system_prompt = self._build_system_prompt()
        user_prompt = f"""Generate a daily performance recap tweet for my AI trading bot.

PERFORMANCE DATA:
{json.dumps(performance_data, indent=2, default=str)}

RULES:
- Lead with the headline number (PnL, win rate, or notable trade)
- Include 2-3 key stats
- If there's a notable win or loss, highlight it
- End with something forward-looking or a lesson learned
- Keep under 280 chars
- Be honest about losses (builds credibility)
- Use line breaks for readability

Output just the tweet text."""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return self._humanize(response.content[0].text.strip())
        except Exception as e:
            logger.error(f"Recap generation failed: {e}")
            return self._fallback_recap(performance_data)

    def generate_build_update(self, changes: list[str]) -> str:
        """Generate a 'building in public' tweet from recent code changes."""
        client = self._get_llm_client()
        if not client:
            return f"Shipped some updates to the bot today. {len(changes)} changes."

        system_prompt = self._build_system_prompt()
        user_prompt = f"""Generate a "building in public" tweet about these recent code changes to my AI trading bot:

CHANGES:
{chr(10).join('- ' + c for c in changes[:10])}

RULES:
- Pick the most interesting 1-2 changes to highlight
- Make it sound exciting but grounded
- Explain WHY the change matters for trading performance
- Under 280 chars
- Builder energy: "just shipped", "new feature dropped", "been working on"
- If a change involves the AI agents, highlight that (people love AI angle)

Output just the tweet text."""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return self._humanize(response.content[0].text.strip())
        except Exception as e:
            logger.error(f"Build update generation failed: {e}")
            return f"Shipped {len(changes)} updates to the bot today."

    # --- System prompt construction ---

    def _build_system_prompt(self) -> str:
        """Build the master system prompt with voice profile and algorithm rules."""
        vp = self.voice_profile
        examples = ""
        if vp.get("example_tweets"):
            examples = "\n\nVOICE SAMPLES (match this style):\n" + "\n".join(
                f'- "{t}"' for t in vp["example_tweets"][:5]
            )

        return f"""You are ghostwriting for a crypto trader's X/Twitter account. The content should sound like it was written by a REAL PERSON, not an AI assistant. Write AS the person, in first person.

PERSONA: {vp['persona']}
TONE: {vp['tone']}

STYLE RULES:
{chr(10).join('- ' + r for r in vp['style_rules'])}

NEVER USE THESE PHRASES (they flag content as AI-generated):
{chr(10).join('- "' + p + '"' for p in vp['never_say'][:15])}

X ALGORITHM OPTIMIZATION:
- Optimize for BOOKMARKS (20x like weight) and REPLIES (27x like weight)
- Write save-worthy content (data, insights, frameworks people want to reference)
- End with implicit conversation starters (questions, hot takes, "what are you seeing?")
- NO links in main tweet (30-50% reach penalty). Links go in self-reply.
- MAX 1 hashtag (3+ = 40% penalty). Prefer zero hashtags.
- NO engagement bait ("like if you agree", "RT this"). Algorithm penalizes it.
- Keep tweets under 280 chars for single tweets
- Use line breaks for readability
{examples}

OUTPUT FORMAT: Always output ONLY the tweet text. No explanations, no metadata, no quotes around it."""

    def _build_tweet_prompt(self, topic: str, pillar: str, context: Optional[str],
                             num_options: int) -> str:
        """Build the user prompt for tweet generation."""
        pillar_guidance = {
            "ai_signals": "Focus on what the AI trading bot sees/detected. Use specific data points. Make it feel like insider alpha.",
            "build_public": "Focus on what was built/shipped/fixed. Show the craft. Make people excited about AI trading.",
            "education": "Teach something specific about AI + trading. Give a framework or insight. Make it bookmark-worthy.",
            "receipts": "Show results with specific numbers. Be honest about both wins and losses. Build track record credibility.",
        }

        return f"""Generate {num_options} tweet options about: {topic}

CONTENT PILLAR: {pillar}
GUIDANCE: {pillar_guidance.get(pillar, 'General crypto/trading content')}
{"CONTEXT: " + context if context else ""}

For each option, try a different hook style:
1. Data-lead (start with a number or stat)
2. Hot take / opinion (start with a bold claim)
3. Story / reveal (start with a result or discovery)

Output as JSON array of objects: [{{"text": "tweet text", "hook_type": "data/opinion/story"}}]"""

    # --- Parsing and humanization ---

    def _parse_tweet_options(self, raw_text: str, pillar: str) -> list[dict]:
        """Parse LLM output into tweet options."""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if json_match:
                options = json.loads(json_match.group())
                for opt in options:
                    opt["pillar"] = pillar
                    opt["text"] = self._humanize(opt.get("text", ""))
                return options
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse tweet options as JSON: {e}")

        # Fallback: treat entire response as a single tweet
        return [{"text": self._humanize(raw_text.strip()), "pillar": pillar, "hook_type": "unknown"}]

    def _parse_thread(self, raw_text: str) -> list[str]:
        """Parse LLM output into thread tweets."""
        try:
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if json_match:
                tweets = json.loads(json_match.group())
                if isinstance(tweets, list) and all(isinstance(t, str) for t in tweets):
                    return tweets
        except Exception:
            pass

        # Fallback: split by double newlines
        parts = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
        return parts if len(parts) > 1 else [raw_text.strip()]

    def _humanize(self, text: str) -> str:
        """
        Remove AI tells and humanize the text.
        This is the anti-detection layer.
        """
        if not text:
            return text

        # Remove banned phrases (case-insensitive)
        for phrase in self.config.banned_phrases:
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            text = pattern.sub("", text)

        # Remove thread numbering (AI tell)
        text = re.sub(r'^\d+[/\.]\s*', '', text)
        text = re.sub(r'^Thread:?\s*', '', text, flags=re.IGNORECASE)

        # Remove excessive hashtags (keep max 1)
        hashtags = re.findall(r'#\w+', text)
        if len(hashtags) > self.config.max_hashtags:
            for tag in hashtags[self.config.max_hashtags:]:
                text = text.replace(tag, "")

        # Remove quotes around the tweet (LLM artifact)
        text = text.strip('"\'')

        # Remove leading/trailing whitespace and collapse multiple spaces
        text = re.sub(r'  +', ' ', text).strip()

        # Remove multiple consecutive newlines (keep max 2)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text

    # --- Fallback generators (no LLM needed) ---

    def _fallback_signal_tweet(self, signal: dict) -> str:
        """Generate a signal tweet without LLM."""
        symbol = signal.get("symbol", "???")
        side = signal.get("side", "???")
        confidence = signal.get("confidence", 0)
        entry = signal.get("entry", 0)
        return f"{symbol} {side} signal at {entry}\n\nBot confidence: {confidence}%\n9-agent pipeline consensus"

    def _fallback_recap(self, perf: dict) -> str:
        """Generate a recap without LLM."""
        pnl = perf.get("daily_pnl", 0)
        trades = perf.get("trades_today", 0)
        prefix = "+" if pnl > 0 else ""
        return f"Bot daily recap\n\nPnL: {prefix}{pnl:.2f}%\nTrades: {trades}\n\nBuilding."

    # --- Content pillar selection ---

    def suggest_pillar(self) -> str:
        """Suggest which content pillar to post based on weights and recent history."""
        weights = self.config.pillar_weights
        pillars = list(weights.keys())
        probs = list(weights.values())

        # Load recent history to avoid repeating same pillar
        history_file = DATA_DIR / "posted_history.json"
        recent_pillars = []
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text())
                recent_pillars = [h.get("pillar", "") for h in history[-5:]]
            except Exception:
                pass

        # Reduce weight of recently used pillars
        adjusted = list(probs)
        for i, pillar in enumerate(pillars):
            count = recent_pillars.count(pillar)
            adjusted[i] = max(0.05, adjusted[i] - count * 0.1)

        # Normalize
        total = sum(adjusted)
        adjusted = [w / total for w in adjusted]

        return random.choices(pillars, weights=adjusted, k=1)[0]
