"""
Voice trainer — learns YOUR writing style from your actual tweets.

This is the anti-bot-detection layer. Instead of generating generic AI content,
we train the content engine to match YOUR exact voice by:
1. Pulling your recent tweets from the X API
2. Analyzing patterns: sentence length, vocabulary, emoji usage, formatting
3. Creating few-shot examples for the content generator
4. Detecting and filtering AI-sounding output
"""
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

logger = logging.getLogger("social.voice_trainer")

DATA_DIR = Path(__file__).parent.parent / "data" / "social"


class VoiceTrainer:
    """Analyze and replicate the user's authentic writing voice."""

    def __init__(self, x_client=None):
        self.x_client = x_client
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def train_from_timeline(self, num_tweets: int = 50) -> dict:
        """
        Pull your recent tweets and analyze your voice patterns.
        Returns a voice profile dict.
        """
        if not self.x_client or not self.x_client.is_connected:
            logger.warning("X client not connected. Use manual voice training instead.")
            return self._manual_training_instructions()

        tweets = self.x_client.get_recent_tweets(limit=num_tweets)
        if not tweets:
            return {"error": "No tweets found. Post some tweets first, then train."}

        texts = [t["text"] for t in tweets if not t["text"].startswith("RT @")]
        return self._analyze_voice(texts, tweets)

    def train_from_samples(self, sample_tweets: list[str]) -> dict:
        """Train voice profile from manually provided tweet samples."""
        return self._analyze_voice(sample_tweets)

    def _analyze_voice(self, texts: list[str], tweet_data: Optional[list] = None) -> dict:
        """Analyze writing patterns from tweet texts."""
        if not texts:
            return {"error": "No text samples provided"}

        # --- Structural patterns ---
        avg_length = sum(len(t) for t in texts) / len(texts)
        uses_line_breaks = sum(1 for t in texts if "\n" in t) / len(texts)
        uses_emojis = sum(1 for t in texts if re.search(r'[\U00010000-\U0010FFFF]', t)) / len(texts)
        uses_numbers = sum(1 for t in texts if re.search(r'\d+', t)) / len(texts)
        uses_caps = sum(1 for t in texts if re.search(r'[A-Z]{3,}', t)) / len(texts)
        uses_hashtags = sum(1 for t in texts if '#' in t) / len(texts)

        # --- Word patterns ---
        all_words = []
        for t in texts:
            words = re.findall(r'\b\w+\b', t.lower())
            all_words.extend(words)
        word_freq = Counter(all_words).most_common(50)
        # Filter common words to find signature vocabulary
        common_words = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "in",
                       "and", "or", "for", "on", "at", "by", "it", "this", "that", "with",
                       "i", "you", "we", "my", "your", "its", "be", "have", "has", "had",
                       "do", "does", "did", "will", "would", "can", "could", "should",
                       "not", "no", "but", "if", "so", "just", "like", "from", "up",
                       "out", "about", "more", "than", "very", "all", "also", "been",
                       "get", "got", "going", "one", "what", "how", "when", "who",
                       "now", "here", "there", "some", "any", "into", "them", "then"}
        signature_words = [w for w, c in word_freq if w not in common_words and c >= 2][:20]

        # --- Sentence structure ---
        sentences = []
        for t in texts:
            sents = re.split(r'[.!?\n]+', t)
            sentences.extend([s.strip() for s in sents if s.strip()])
        avg_sentence_length = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)

        # --- Top performing tweets (for few-shot examples) ---
        best_tweets = []
        if tweet_data:
            scored = sorted(tweet_data, key=lambda t: (
                t.get("impressions", 0) +
                t.get("bookmarks", 0) * 20 +
                t.get("replies", 0) * 27
            ), reverse=True)
            best_tweets = [t["text"] for t in scored[:10] if not t["text"].startswith("RT @")]

        # --- Build voice profile ---
        profile = {
            "persona": "crypto trader building an autonomous AI trading bot with 9 specialist agents",
            "tone": self._infer_tone(texts, avg_sentence_length, uses_emojis, uses_caps),
            "style_rules": self._infer_style_rules(
                avg_length, uses_line_breaks, uses_emojis,
                uses_numbers, uses_caps, uses_hashtags, avg_sentence_length
            ),
            "signature_words": signature_words[:15],
            "example_tweets": best_tweets[:10] if best_tweets else texts[:10],
            "structural_patterns": {
                "avg_tweet_length": round(avg_length),
                "line_break_rate": round(uses_line_breaks, 2),
                "emoji_rate": round(uses_emojis, 2),
                "number_rate": round(uses_numbers, 2),
                "caps_rate": round(uses_caps, 2),
                "hashtag_rate": round(uses_hashtags, 2),
                "avg_sentence_words": round(avg_sentence_length, 1),
            },
            "never_say": [
                "let's dive in", "let's break it down", "here's the thing",
                "buckle up", "game-changer", "revolutionary", "paradigm shift",
                "in this thread", "a thread 🧵", "thread:",
                "not financial advice", "DYOR",
                "I've been thinking about", "I want to talk about",
                "in conclusion", "to summarize", "key takeaways",
            ],
            "trained_at": __import__("datetime").datetime.now().isoformat(),
            "sample_size": len(texts),
        }

        # Save profile
        profile_path = DATA_DIR / "voice_profile.json"
        profile_path.write_text(json.dumps(profile, indent=2))
        logger.info(f"Voice profile trained from {len(texts)} tweets. Saved to {profile_path}")

        return profile

    def _infer_tone(self, texts: list, avg_sent_len: float,
                    emoji_rate: float, caps_rate: float) -> str:
        """Infer the dominant tone from tweet patterns."""
        traits = []

        if avg_sent_len < 8:
            traits.append("punchy, short sentences")
        elif avg_sent_len < 15:
            traits.append("moderate sentence length")
        else:
            traits.append("longer, analytical sentences")

        if caps_rate > 0.3:
            traits.append("uses emphasis caps")

        if emoji_rate > 0.5:
            traits.append("emoji-friendly")
        elif emoji_rate < 0.1:
            traits.append("minimal emoji usage")

        # Check for profanity
        profanity_count = sum(
            1 for t in texts
            if re.search(r'\b(fuck|shit|damn|hell|ass)\b', t, re.IGNORECASE)
        )
        if profanity_count / max(len(texts), 1) > 0.1:
            traits.append("casual/raw language")

        # Check for question usage
        question_rate = sum(1 for t in texts if "?" in t) / max(len(texts), 1)
        if question_rate > 0.3:
            traits.append("conversational, asks questions")

        return ", ".join(traits) if traits else "confident, data-driven"

    def _infer_style_rules(self, avg_len: float, lb_rate: float, emoji_rate: float,
                           num_rate: float, caps_rate: float, hash_rate: float,
                           sent_len: float) -> list[str]:
        """Generate style rules from observed patterns."""
        rules = []

        if avg_len < 200:
            rules.append(f"keep tweets short (~{int(avg_len)} chars)")
        elif avg_len > 250:
            rules.append(f"longer tweets work (~{int(avg_len)} chars)")

        if lb_rate > 0.4:
            rules.append("use line breaks frequently for readability")
        else:
            rules.append("minimal line breaks, dense format")

        if num_rate > 0.5:
            rules.append("always include specific numbers and data")

        if emoji_rate < 0.2:
            rules.append("minimal emojis, let the text speak")
        elif emoji_rate > 0.5:
            rules.append("use emojis for emphasis and visual breaks")

        if hash_rate < 0.1:
            rules.append("avoid hashtags entirely")
        elif hash_rate < 0.3:
            rules.append("use max 1 hashtag, sparingly")

        if caps_rate > 0.3:
            rules.append("use ALL CAPS for emphasis on key words")

        if sent_len < 8:
            rules.append("short, punchy sentences. one idea per line.")
        elif sent_len > 12:
            rules.append("slightly longer analytical sentences are fine")

        # Always include these for crypto Twitter optimization
        rules.append("be opinionated, don't hedge everything")
        rules.append("show the work, not just the conclusion")

        return rules

    def _manual_training_instructions(self) -> dict:
        """Return instructions for manual voice training without API."""
        return {
            "status": "manual_training_needed",
            "instructions": [
                "Without X API connection, you can manually train voice profile.",
                "Option 1: Run 'voice train-manual' and paste 10-20 of your best tweets",
                "Option 2: Connect X API and run 'voice train' to auto-pull your tweets",
                "Option 3: Edit bot/data/social/voice_profile.json directly",
            ],
        }
