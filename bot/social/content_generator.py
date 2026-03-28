"""
Claude-powered content generator for X/Twitter.

Generates scroll-stopping hooks, project updates, and threads
using the existing LLM infrastructure.

Content pillars:
  1. Trading/On-chain — alpha, perp mechanics, market observations
  2. AI/Building — project updates, dev experiments, journey
  3. Motion/Lifestyle — personality, memes, gaming crossover
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger("bot.social.content_generator")

# Use Haiku for cost-efficient content generation (~$0.0001/call)
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

PILLARS = ["trading", "ai_building", "motion_lifestyle"]

HOOK_SYSTEM_PROMPT = """You are a social media content strategist for a crypto/AI builder account (@WillumpOnChain).

Background: Ex-top Nunu (League of Legends) player, EMT/Paramedic, high-volume perp trader, now building AI tools and trading bots.

Your job: Generate scroll-stopping tweet hooks that feel authentic, not corporate. The account has ~250 followers and is growing. Tone should be: confident but not arrogant, technical but accessible, occasionally funny.

Rules:
- Max 280 characters per tweet (unless explicitly told otherwise)
- No hashtags (they look spammy and get deboosted)
- No external links in the main tweet
- Start with something that makes people stop scrolling
- Be specific with numbers and experiences when possible
- Never reveal API keys, wallet addresses, or exact position sizes
- Never make financial advice claims

Output format: Return a JSON array of exactly 3 tweet options. Each should be a string.
Example: ["tweet 1", "tweet 2", "tweet 3"]
Return ONLY the JSON array, no other text."""

THREAD_SYSTEM_PROMPT = """You are a social media content strategist for a crypto/AI builder account (@WillumpOnChain).

Background: Ex-top Nunu (League of Legends) player, EMT/Paramedic, high-volume perp trader, now building AI tools and trading bots.

Your job: Create an engaging Twitter thread. Each tweet should be under 280 characters. The first tweet should be the strongest hook. End with a call to action or takeaway.

Rules:
- 3-7 tweets per thread
- Each tweet stands alone but flows as a narrative
- Use line breaks within tweets for readability
- No hashtags
- No external links (put those in a reply after the thread)
- Be authentic and specific
- Never reveal API keys, wallet addresses, or exact position sizes

Output format: Return a JSON array of strings, each string is one tweet in the thread.
Return ONLY the JSON array, no other text."""

CHRONICLE_SYSTEM_PROMPT = """You are a social media content strategist for a crypto/AI builder account (@WillumpOnChain) that is building an autonomous trading bot called WAGMI.

Your job: Turn development updates and git commit summaries into engaging tweets that show progress without revealing sensitive details.

Rules:
- Make technical progress sound exciting and accessible
- Show the journey, not just results
- Never mention specific file paths, function names, or internal architecture
- Never reveal API keys, trading strategies specifics, or position sizes
- Frame updates as "building in public" content
- Keep it under 280 characters per tweet
- No hashtags

Output format: Return a JSON array of exactly 3 tweet options. Each should be a string.
Return ONLY the JSON array, no other text."""


def _call_llm(system_prompt: str, user_message: str, model: str = DEFAULT_MODEL) -> Optional[str]:
    """Call Claude API using the existing LLM client."""
    try:
        from llm.client import call_llm
        response_text, usage = call_llm(
            system_prompt=system_prompt,
            snapshot_json=user_message,
            model=model,
            max_tokens=1024,
            max_retries=2,
            timeout=30.0,
        )
        if usage:
            logger.debug(f"Content gen LLM usage: {usage}")
        return response_text
    except Exception as e:
        logger.error(f"LLM call failed for content generation: {e}")
        return None


def _parse_json_array(text: str) -> Optional[List[str]]:
    """Parse a JSON array from LLM response, handling common issues."""
    if not text:
        return None

    # Try direct parse
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [str(item) for item in result]
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    for marker in ["```json", "```"]:
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                result = json.loads(text[start:end].strip())
                if isinstance(result, list):
                    return [str(item) for item in result]
            except (json.JSONDecodeError, ValueError):
                pass

    logger.warning(f"Failed to parse JSON array from LLM response: {text[:200]}...")
    return None


def generate_hooks(
    topic: str,
    pillar: str = "trading",
    count: int = 3,
) -> Optional[List[str]]:
    """
    Generate scroll-stopping tweet hooks for a topic.

    Args:
        topic: What to write about (e.g., "BTC breaking 100k", "built a new AI feature")
        pillar: Content pillar - "trading", "ai_building", or "motion_lifestyle"
        count: Number of options to generate (default 3)

    Returns:
        List of tweet text options, or None on failure
    """
    if pillar not in PILLARS:
        logger.warning(f"Unknown pillar '{pillar}', using 'trading'")
        pillar = "trading"

    user_msg = json.dumps({
        "task": "generate_hooks",
        "topic": topic,
        "pillar": pillar,
        "count": count,
        "current_date": datetime.now().strftime("%Y-%m-%d"),
    })

    response = _call_llm(HOOK_SYSTEM_PROMPT, user_msg)
    return _parse_json_array(response)


def generate_thread(
    topic: str,
    pillar: str = "trading",
    key_points: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """
    Generate a Twitter thread on a topic.

    Args:
        topic: Thread subject
        pillar: Content pillar
        key_points: Optional specific points to cover

    Returns:
        List of tweet texts forming the thread, or None on failure
    """
    user_msg = json.dumps({
        "task": "generate_thread",
        "topic": topic,
        "pillar": pillar,
        "key_points": key_points or [],
        "current_date": datetime.now().strftime("%Y-%m-%d"),
    })

    response = _call_llm(THREAD_SYSTEM_PROMPT, user_msg)
    return _parse_json_array(response)


def generate_chronicle(
    days: int = 7,
    repo_path: str = ".",
) -> Optional[List[str]]:
    """
    Generate project update tweets from recent git history.

    Args:
        days: Number of days of git history to summarize
        repo_path: Path to git repo (defaults to current directory)

    Returns:
        List of tweet options about recent progress, or None on failure
    """
    # Get recent git log
    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--since={since_date}",
                "--oneline",
                "--no-merges",
                "--format=%s",
            ],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=10,
        )
        commits = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except Exception as e:
        logger.error(f"Failed to get git log: {e}")
        commits = []

    if not commits:
        logger.info("No recent commits found for chronicle")
        return None

    # Count stats
    try:
        stat_result = subprocess.run(
            [
                "git", "diff",
                f"--stat",
                f"HEAD~{min(len(commits), 50)}..HEAD",
            ],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=10,
        )
        diff_summary = stat_result.stdout.strip().split("\n")[-1] if stat_result.stdout.strip() else ""
    except Exception:
        diff_summary = ""

    user_msg = json.dumps({
        "task": "generate_chronicle",
        "recent_commits": commits[:20],  # Cap to avoid token waste
        "commit_count": len(commits),
        "days_covered": days,
        "diff_summary": diff_summary,
        "current_date": datetime.now().strftime("%Y-%m-%d"),
    })

    response = _call_llm(CHRONICLE_SYSTEM_PROMPT, user_msg)
    return _parse_json_array(response)


def generate_milestone_post(
    milestone: str,
    details: Optional[str] = None,
) -> Optional[List[str]]:
    """
    Generate tweets announcing a project milestone.

    Args:
        milestone: What was achieved (e.g., "First profitable week", "500 trades executed")
        details: Optional additional context

    Returns:
        List of tweet options, or None on failure
    """
    user_msg = json.dumps({
        "task": "generate_milestone",
        "milestone": milestone,
        "details": details or "",
        "current_date": datetime.now().strftime("%Y-%m-%d"),
    })

    response = _call_llm(HOOK_SYSTEM_PROMPT, user_msg)
    return _parse_json_array(response)


def format_for_tweet(text: str, max_length: int = 280) -> str:
    """Ensure text fits in a tweet, truncating with ellipsis if needed."""
    text = text.strip()
    if len(text) <= max_length:
        return text
    return text[:max_length - 3].rsplit(" ", 1)[0] + "..."
