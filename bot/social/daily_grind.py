"""
Daily Grind Engine — generates your ENTIRE day's content in one shot.

Run once in the morning: python -m social.cli grind
Get back: 8-12 ready-to-post tweets scheduled across the day.

Output: bot/data/social/daily_grind.md (human-readable, copy-paste ready)
Also: bot/data/social/daily_grind.json (structured, for queue integration)

Content mix per day:
- 2-3 market/signal calls (what my AI sees)
- 2-3 community coin bags (organic weaving + direct)
- 2-3 engagement drivers (polls, hot takes, questions that get replies)
- 1-2 build-in-public updates
- 1 educational alpha drop or framework
- Reply targets: 5-10 larger accounts to reply to throughout the day

The goal: 250 → 1000+ followers through CONSISTENT daily posting.
Every day. No days off. The algorithm rewards consistency above all.
"""
import json
import logging
import os
import random
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("social.daily_grind")

DATA_DIR = Path(__file__).parent.parent / "data" / "social"


class DailyGrind:
    """Generate a full day's worth of content in one shot."""

    def __init__(self, content_config, bags=None):
        self.config = content_config
        self.bags = bags or content_config.bags or []
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            try:
                from anthropic import Anthropic
                self._llm = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            except ImportError:
                logger.error("anthropic not installed")
        return self._llm

    def generate_daily_plan(self, market_context: str = "",
                            extra_topics: list = None) -> dict:
        """
        Generate the full day's content plan.
        Returns dict with all posts, reply targets, and schedule.
        """
        llm = self._get_llm()
        if not llm:
            return self._fallback_plan()

        # Gather context
        git_changes = self._get_recent_git()
        bag_info = self._format_bags()
        now = datetime.now(timezone.utc)
        day_name = now.strftime("%A")

        system_prompt = self._build_grind_system_prompt()
        user_prompt = f"""Generate my FULL day's Twitter content plan for {day_name}, {now.strftime('%B %d')}.

MARKET CONTEXT (if any):
{market_context or "No specific market context provided — use general crypto market awareness"}

COMMUNITY COINS I'M BAGWORKING:
{bag_info or "No bags configured yet — skip bag posts for now"}

RECENT BUILD ACTIVITY (for build-in-public posts):
{chr(10).join(git_changes[:8]) if git_changes else "No recent changes"}

EXTRA TOPICS TO COVER:
{chr(10).join('- ' + t for t in (extra_topics or [])) or "None specified"}

Generate EXACTLY this content mix:
1. SIGNAL_POSTS (2-3): Market calls, what my AI bot sees, macro reads. Be specific with levels and directions.
2. BAG_POSTS (2-3): Community coin promotion. Mix organic (natural mention in market context) and direct (focused post about the coin). Make these NOT look like paid shills — weave them into genuine market analysis.
3. ENGAGEMENT_POSTS (2-3): Polls, hot takes, provocative questions, "what are you watching?" type posts. These exist PURELY to drive replies (27x algorithm weight) and conversations (150x).
4. BUILD_POST (1): What I'm building, progress update, behind-the-scenes of the AI bot.
5. ALPHA_DROP (1): Quick educational insight, framework, or non-obvious take. Bookmark-worthy.
6. REPLY_TARGETS (5-8): Suggest types of tweets to reply to on larger accounts (not specific accounts, but the TYPE of tweet to look for and a template reply approach).

For each post, provide:
- "text": The actual tweet text (under 280 chars, ready to copy-paste)
- "type": signal/bag/engagement/build/alpha
- "slot": morning/midday/afternoon/evening
- "priority": 1 (must post) / 2 (post if time) / 3 (bonus)
- "algo_note": Why this post should perform well (1 sentence)

For reply targets, provide:
- "target_type": What kind of tweet to reply to
- "reply_template": A customizable reply approach (not exact text, but the angle)
- "why": Why this reply strategy drives profile visits

Output as JSON with keys: "posts", "reply_targets", "day_summary"
The day_summary should be a 1-sentence theme for the day.
"""

        try:
            response = llm.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            raw = response.content[0].text
            plan = self._parse_plan(raw)
            plan["generated_at"] = now.isoformat()
            plan["day"] = day_name

            # Save both formats
            self._save_plan(plan)
            return plan

        except Exception as e:
            logger.error(f"Daily grind generation failed: {e}")
            return self._fallback_plan()

    def _build_grind_system_prompt(self) -> str:
        """System prompt optimized for daily content factory."""
        banned = self.config.banned_phrases[:20]
        return f"""You are a content factory for a crypto trader's X/Twitter account. You generate an ENTIRE day's worth of ready-to-post tweets.

PERSONA: Crypto trader building an autonomous AI trading bot with 9 specialist agents (Regime, Trade, Risk, Critic, Learning, Exit, Scout, Overseer, Quant). You make macro calls for your community. You're in the grind phase — 250 followers, building to 1000+.

VOICE:
- Confident, specific, data-driven
- Short sentences. Line breaks. One idea per line.
- Use specific numbers always ("$BTC holding 67.2k" not "BTC looking strong")
- Mix of quant precision and degen energy
- Occasional profanity is fine (authentic on CT)
- NEVER hedge everything — have conviction
- NEVER sound corporate or AI-generated

X ALGORITHM RULES (follow these EXACTLY):
- Optimize for BOOKMARKS (20x) and REPLIES (27x), NOT likes (0.5x)
- NO links in tweets (30-50% penalty). If referencing something, describe it.
- MAX 1 hashtag per tweet. Prefer $CASHTAGS over #hashtags.
- NO engagement bait ("like if you agree"). The algo penalizes it.
- End engagement posts with QUESTIONS — questions drive replies
- Keep single tweets under 280 chars
- Use line breaks for readability

BANNED PHRASES (AI tells — never use these):
{chr(10).join('- ' + p for p in banned)}

BAG PROMOTION RULES:
- NEVER make it look like a paid shill
- Organic bags: mention the coin naturally in broader market analysis ("watching $X along with the SOL ecosystem move")
- Direct bags: focus on the community, the chart, or a catalyst — not "buy this coin"
- Mix cashtags naturally: "$BTC $ETH and some $COINNAME for the degen play"
- Max 2 bag-focused posts per day, rest should be organic mentions

ENGAGEMENT POST RULES:
- Polls get 1.5-3% engagement (highest of any format)
- Questions in tweets drive replies (27x algo weight)
- Hot takes drive quote tweets (40x algo weight)
- "What are you watching?" type posts build community
- Contrarian takes during consensus = engagement magnet

OUTPUT: Valid JSON only. No markdown, no explanation. Just the JSON object."""

    def _format_bags(self) -> str:
        """Format bag configs for the prompt."""
        if not self.bags:
            return ""
        lines = []
        for b in self.bags:
            if hasattr(b, 'ticker'):
                lines.append(f"- ${b.ticker} ({b.full_name}): {b.why_bullish} | Chain: {b.chain} | Style: {b.style}")
            elif isinstance(b, dict):
                lines.append(f"- ${b.get('ticker', '???')} ({b.get('full_name', '')}): {b.get('why_bullish', '')} | Chain: {b.get('chain', '')} | Style: {b.get('style', 'organic')}")
        return "\n".join(lines)

    def _get_recent_git(self) -> list[str]:
        """Get recent git changes for build-in-public content."""
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-10", "--no-merges"],
                capture_output=True, text=True, timeout=5,
                cwd=str(Path(__file__).parent.parent.parent),
            )
            return [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        except Exception:
            return []

    def _parse_plan(self, raw: str) -> dict:
        """Parse LLM output into structured plan."""
        import re
        try:
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                plan = json.loads(json_match.group())
                # Humanize all post texts
                for post in plan.get("posts", []):
                    post["text"] = self._humanize(post.get("text", ""))
                return plan
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse daily plan: {e}")

        # Fallback: return raw as single-post plan
        return {
            "posts": [{"text": raw[:280], "type": "signal", "slot": "morning", "priority": 1}],
            "reply_targets": [],
            "day_summary": "Content generation partially failed — edit manually",
        }

    def _humanize(self, text: str) -> str:
        """Strip AI tells from generated content."""
        import re
        if not text:
            return text

        for phrase in self.config.banned_phrases:
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            text = pattern.sub("", text)

        text = re.sub(r'^\d+[/\.]\s*', '', text)
        text = text.strip('"\'')
        text = re.sub(r'  +', ' ', text).strip()
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    def _save_plan(self, plan: dict):
        """Save plan as both JSON and human-readable markdown."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # JSON for programmatic access
        json_file = DATA_DIR / "daily_grind.json"
        json_file.write_text(json.dumps(plan, indent=2, default=str))

        # Markdown for easy copy-paste
        md = self._plan_to_markdown(plan)
        md_file = DATA_DIR / "daily_grind.md"
        md_file.write_text(md)

        logger.info(f"Daily grind saved: {json_file} and {md_file}")

    def _plan_to_markdown(self, plan: dict) -> str:
        """Convert plan to copy-paste-ready markdown."""
        lines = [
            f"# Daily Grind — {plan.get('day', 'Today')}, {datetime.now().strftime('%B %d')}",
            f"*{plan.get('day_summary', '')}*",
            "",
        ]

        posts = plan.get("posts", [])

        # Group by time slot
        for slot in ["morning", "midday", "afternoon", "evening"]:
            slot_posts = [p for p in posts if p.get("slot") == slot]
            if not slot_posts:
                continue

            slot_emoji = {"morning": "AM", "midday": "NOON", "afternoon": "PM", "evening": "EVE"}.get(slot, slot.upper())
            lines.append(f"## [{slot_emoji}] {slot.title()}")
            lines.append("")

            for i, post in enumerate(slot_posts, 1):
                ptype = post.get("type", "general").upper()
                priority = post.get("priority", 2)
                star = "***" if priority == 1 else "**" if priority == 2 else "*"
                text = post.get("text", "")
                note = post.get("algo_note", "")

                lines.append(f"### {star} [{ptype}] Post {i}")
                lines.append(f"```")
                lines.append(text)
                lines.append(f"```")
                if note:
                    lines.append(f"*Algo: {note}*")
                lines.append("")

        # Reply targets
        targets = plan.get("reply_targets", [])
        if targets:
            lines.append("## Reply Game (do this throughout the day)")
            lines.append("")
            for t in targets:
                target_type = t.get("target_type", "")
                template = t.get("reply_template", "")
                why = t.get("why", "")
                lines.append(f"- **{target_type}**: {template}")
                if why:
                    lines.append(f"  *({why})*")
            lines.append("")

        lines.append("---")
        lines.append(f"*Generated {datetime.now().strftime('%H:%M')} UTC | Copy-paste ready | Edit before posting*")
        return "\n".join(lines)

    def _fallback_plan(self) -> dict:
        """Fallback plan when LLM is unavailable."""
        return {
            "posts": [
                {"text": "Morning market scan running\n\nBot's regime agent processing overnight data\n\nUpdates incoming", "type": "signal", "slot": "morning", "priority": 1},
                {"text": "What's everyone watching today?", "type": "engagement", "slot": "morning", "priority": 1},
                {"text": "Shipped some updates to the bot overnight\n\nThe grind never stops", "type": "build", "slot": "midday", "priority": 2},
            ],
            "reply_targets": [
                {"target_type": "Larger account's market take", "reply_template": "Add your own data point or contrarian view", "why": "Profile visits from their audience"},
            ],
            "day_summary": "LLM unavailable — use these templates and customize",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # --- Bag management ---

    @staticmethod
    def add_bag(ticker: str, full_name: str, chain: str,
                why_bullish: str, ca: str = "", style: str = "organic"):
        """Add a community coin to the bag rotation."""
        bags_file = DATA_DIR / "bags.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        bags = []
        if bags_file.exists():
            try:
                bags = json.loads(bags_file.read_text())
            except Exception:
                pass

        # Check for duplicate
        for b in bags:
            if b.get("ticker", "").upper() == ticker.upper():
                b.update({
                    "full_name": full_name,
                    "chain": chain,
                    "why_bullish": why_bullish,
                    "ca": ca,
                    "style": style,
                    "hashtag": f"${ticker.upper()}",
                })
                bags_file.write_text(json.dumps(bags, indent=2))
                return {"status": "updated", "ticker": ticker}

        bags.append({
            "ticker": ticker.upper(),
            "full_name": full_name,
            "chain": chain,
            "why_bullish": why_bullish,
            "ca": ca,
            "hashtag": f"${ticker.upper()}",
            "style": style,
        })
        bags_file.write_text(json.dumps(bags, indent=2))
        return {"status": "added", "ticker": ticker, "total_bags": len(bags)}

    @staticmethod
    def remove_bag(ticker: str):
        """Remove a coin from bag rotation."""
        bags_file = DATA_DIR / "bags.json"
        if not bags_file.exists():
            return {"status": "not_found"}
        bags = json.loads(bags_file.read_text())
        bags = [b for b in bags if b.get("ticker", "").upper() != ticker.upper()]
        bags_file.write_text(json.dumps(bags, indent=2))
        return {"status": "removed", "remaining": len(bags)}

    @staticmethod
    def list_bags() -> list:
        """List all bags."""
        bags_file = DATA_DIR / "bags.json"
        if bags_file.exists():
            try:
                return json.loads(bags_file.read_text())
            except Exception:
                pass
        return []
