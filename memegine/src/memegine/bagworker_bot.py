"""Telegram bot handler for bagworker raids.

Handles:
- /post <text> — create a raid post
- Forward tweets — auto-create raid from tweet text
- /miniapp — send link to Mini App
"""
from __future__ import annotations

from html import unescape
from urllib.parse import quote

from .bagworker_api import db


async def handle_post_command(update, context):
    """Handle /post command to create a raid.

    Usage: /post "tweet text here"
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /post \"tweet text\"\n\n"
            "Example: /post \"just realized i'm actually a genius trader\""
        )
        return

    # Get the tweet text
    text = " ".join(context.args)
    text = text.strip('\'"')  # Remove quotes if present

    if not text:
        await update.message.reply_text("Tweet text cannot be empty")
        return

    # Create the post in database
    post_id = f"post_{update.message.message_id}_{update.message.from_user.id}"
    post = db.post_create(
        post_id=post_id,
        text=text,
        created_by_tg_id=update.message.from_user.id,
    )

    # Send confirmation
    await update.message.reply_text(
        f"✅ **New Raid Posted!**\n\n"
        f"_\"{text[:100]}...\"_\n\n"
        f"Bagworkers can raid this on the mini app now!\n\n"
        f"[Open Raid Dashboard](https://your-domain.com/miniapp)"
    )


async def handle_forward_message(update, context):
    """Handle forwarded messages (tweets) to auto-create raids.

    When someone forwards a tweet or paste text, create a raid from it.
    """
    if not update.message:
        return

    # Get the message text
    text = update.message.text or update.message.caption or ""
    if not text:
        return

    # Skip if it's a command
    if text.startswith("/"):
        return

    # Extract tweet-like text (first 280 chars)
    text = text[:280].strip()

    if len(text) < 10:
        return  # Skip very short messages

    # Create post from forwarded message
    post_id = f"post_{update.message.message_id}_{update.message.from_user.id}"
    post = db.post_create(
        post_id=post_id,
        text=text,
        created_by_tg_id=update.message.from_user.id,
    )

    # Send confirmation reaction or reply
    await update.message.reply_text(
        f"🎯 Added to raids!\n\n"
        f"Bagworkers can raid this now.",
        reply_to_message_id=update.message.message_id,
    )


async def handle_miniapp_command(update, context):
    """Handle /miniapp command to send Mini App link."""
    tg_id = update.message.from_user.id
    username = update.message.from_user.username or f"user_{tg_id}"

    # Generate deep link to Mini App
    miniapp_url = (
        "https://t.me/willumpssnowballbot/bagworkers"  # Replace with your bot name
    )

    await update.message.reply_text(
        f"🎯 **Bagworker Raid Dashboard**\n\n"
        f"[Open Mini App]({miniapp_url})\n\n"
        f"Your account: @{username}\n"
        f"TG ID: `{tg_id}`",
        parse_mode="Markdown",
    )


async def handle_stats_command(update, context):
    """Handle /stats command to show user stats."""
    tg_id = update.message.from_user.id
    user = db.user_get(tg_id)

    if not user:
        await update.message.reply_text(
            "You don't have an account yet. "
            "Use /miniapp to create one!"
        )
        return

    leaderboard = db.leaderboard(limit=1000)
    rank = next(
        (i + 1 for i, u in enumerate(leaderboard) if u["tg_id"] == tg_id),
        len(leaderboard) + 1,
    )

    stats = (
        f"📊 **Your Stats**\n\n"
        f"👤 @{user['username']}\n"
        f"🏆 Rank: #{rank}\n"
        f"💰 Points: {user.get('points', 0)}\n\n"
        f"📈 Engagements:\n"
        f"  🔄 Retweets: {user.get('retweets', 0)}\n"
        f"  ❤️ Likes: {user.get('likes', 0)}\n"
        f"  💬 Replies: {user.get('replies', 0)}"
    )

    await update.message.reply_text(stats, parse_mode="Markdown")


async def handle_leaderboard_command(update, context):
    """Handle /leaderboard command to show top users."""
    leaderboard = db.leaderboard(limit=10)

    lines = ["🏆 **Top Bagworkers**\n"]
    for i, user in enumerate(leaderboard, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
        lines.append(
            f"{medal} @{user['username']} — {user.get('points', 0)} pts "
            f"({user.get('retweets', 0)}🔄 {user.get('likes', 0)}❤️)"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_help_command(update, context):
    """Handle /help command."""
    help_text = (
        "🎯 **Bagworker Raid System**\n\n"
        "**Commands:**\n"
        "/post \"text\" — Create a raid\n"
        "/miniapp — Open dashboard\n"
        "/stats — Your stats\n"
        "/leaderboard — Top 10\n"
        "/help — This message\n\n"
        "**How it works:**\n"
        "1. Post raids with /post or forward messages\n"
        "2. Bagworkers raid on Twitter/X\n"
        "3. Earn points for engagement\n"
        "4. Climb the leaderboard\n"
        "5. Win rewards!"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


def register_bagworker_handlers(app):
    """Register handlers with the TG bot application.

    Usage in your main telegram_ops.py:
        from memegine.bagworker_bot import register_bagworker_handlers
        register_bagworker_handlers(app)
    """
    from telegram import filters
    from telegram.ext import CommandHandler, MessageHandler

    # Command handlers
    app.add_handler(CommandHandler("post", handle_post_command))
    app.add_handler(CommandHandler("miniapp", handle_miniapp_command))
    app.add_handler(CommandHandler("stats", handle_stats_command))
    app.add_handler(CommandHandler("leaderboard", handle_leaderboard_command))
    app.add_handler(CommandHandler("help", handle_help_command))

    # Message handler for auto-raiding (forward tweets)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_forward_message,
        )
    )
