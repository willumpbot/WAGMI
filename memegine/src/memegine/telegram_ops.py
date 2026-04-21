"""Telegram ops console — the phone UI for the reply-guy/raid-lead loop.

Design goals:
- Tap-driven, zero typing for the common path
- Every tweet shows up as a CARD with 4 inline buttons:
    [📎 Refs]  [✍ Brief]  [🎬 Video]  [🎯 Raid]
- Works in 1:1 chat with the bot OR pushed from a watchlist poller
- Piggybacks on the existing `ops_db` + `reply_for` + `flow_post` modules

Callback-data format (Telegram limits to 64 bytes):
    t:{action}:{tweet_id}
where action ∈ {refs, brief, video, raid, close}

Registered from telegram_bot.build_application:
    register_ops_handlers(app, cfg)
Adds: /feed, /watch, /unwatch, /watchlist, /brand, /fetchtweet
plus the callback dispatcher for tweet-card buttons.
"""
from __future__ import annotations

from typing import Any, Optional

from . import (
    brand as brand_mod,
    flow_post,
    ops_db,
    projects as projects_mod,
    reply_for as reply_for_mod,
    x_fetch,
)
from .config import settings


GROK_URL = "https://grok.com/imagine"

# Short button labels optimize for narrow mobile rows.
# Two rows to keep each row at 3-4 buttons — comfortable on mobile.
ACTIONS_ROW1 = [
    ("refs", "📎 Refs"),
    ("brief", "✍ Brief"),
    ("video", "🎬 Video"),
]
ACTIONS_ROW2 = [
    ("raid", "🎯 Raid"),
    ("spong", "🟢 Spongify"),
]
ACTIONS = ACTIONS_ROW1 + ACTIONS_ROW2


def _keyboard_for_tweet(tweet_id: str):
    """Build the inline keyboard for a tweet card (2 rows)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    row1 = [
        InlineKeyboardButton(label, callback_data=f"t:{act}:{tweet_id}")
        for act, label in ACTIONS_ROW1
    ]
    row2 = [
        InlineKeyboardButton(label, callback_data=f"t:{act}:{tweet_id}")
        for act, label in ACTIONS_ROW2
    ]
    return InlineKeyboardMarkup([row1, row2])


def _format_tweet_caption(t: dict, *, max_chars: int = 900) -> str:
    """Render a tweet for a TG message caption."""
    header = f"@{t['handle']}"
    if t.get("author_name"):
        header = f"{t['author_name']} · @{t['handle']}"
    created = (t.get("created_at") or "").replace("T", " ")[:16]
    body = t.get("text", "")
    if len(body) > max_chars - 200:
        body = body[: max_chars - 200].rstrip() + "…"
    likes = t.get("favorite_count", 0)
    replies = t.get("reply_count", 0)
    symbols = " ".join(f"${s}" for s in (t.get("symbols") or []))
    stats = f"♥ {likes:,}  💬 {replies:,}"
    if symbols:
        stats += f"   {symbols}"
    url = t.get("url") or f"https://x.com/{t['handle']}/status/{t['id']}"
    return f"{header}\n{created}\n\n{body}\n\n{stats}\n{url}"


async def _send_tweet_card(update_or_context, chat_id: int, t: dict) -> None:
    """Send one tweet as a card with inline buttons.

    Uses the first media URL if present (send_photo), else send_message.
    """
    from telegram import Bot
    bot = update_or_context.bot if hasattr(update_or_context, "bot") else update_or_context
    caption = _format_tweet_caption(t)
    kb = _keyboard_for_tweet(t["id"])
    media_urls = t.get("media_urls") or []
    # Only attach photo media (TG's send_photo doesn't handle .mp4 directly here).
    photo_url = next(
        (u for u in media_urls if any(u.lower().endswith(e)
                                      for e in (".jpg", ".jpeg", ".png", ".webp"))),
        None,
    )
    if photo_url:
        try:
            await bot.send_photo(
                chat_id=chat_id, photo=photo_url,
                caption=caption[:1020], reply_markup=kb,
            )
            return
        except Exception:
            pass  # fall through to text-only
    await bot.send_message(
        chat_id=chat_id, text=caption, reply_markup=kb,
        disable_web_page_preview=False,
    )


# ---- command handlers -------------------------------------------------------


def _build_ops_handlers(cfg):
    """Construct the ops command handlers bound to cfg.

    cfg is the BotConfig instance from telegram_bot.py. We don't import
    BotConfig directly to avoid circular import; duck-typed via attrs.
    """

    async def guard(update) -> bool:
        """Mirror telegram_bot._is_allowed — user OR chat allowlist."""
        chat = update.effective_chat
        allowed_chat_ids = getattr(cfg, "allowed_chat_ids", set()) or set()
        if chat is not None and chat.id in allowed_chat_ids:
            return True
        user = update.effective_user
        if user is None:
            return False
        return user.id in cfg.allowed_user_ids

    async def feed_cmd(update, context):
        if not await guard(update):
            return
        args = context.args
        handle = None
        if args:
            handle = args[0].lstrip("@").lower()
        tweets = ops_db.tweets_recent(limit=10, handle=handle)
        if not tweets:
            await update.message.reply_text(
                "(no tweets cached yet — use /fetchtweet <url> to add one)"
            )
            return
        for t in tweets:
            await _send_tweet_card(context, update.effective_chat.id, t)

    async def watch_cmd(update, context):
        if not await guard(update):
            return
        if not context.args:
            await update.message.reply_text("usage: /watch @handle")
            return
        handle = context.args[0]
        try:
            entry = ops_db.watchlist_add(handle)
        except ValueError as exc:
            await update.message.reply_text(f"error: {exc}")
            return
        await update.message.reply_text(
            f"✅ watching @{entry.handle}\n"
            f"(project: {settings.project})"
        )

    async def unwatch_cmd(update, context):
        if not await guard(update):
            return
        if not context.args:
            await update.message.reply_text("usage: /unwatch @handle")
            return
        ok = ops_db.watchlist_remove(context.args[0])
        msg = "✅ removed" if ok else "⚠ handle not on watchlist"
        await update.message.reply_text(msg)

    async def watchlist_cmd(update, context):
        if not await guard(update):
            return
        entries = ops_db.watchlist_list()
        if not entries:
            await update.message.reply_text("(no handles on watchlist)")
            return
        lines = [f"Watchlist for `{settings.project}`:"]
        for e in entries:
            lines.append(f"  @{e.handle}")
        await update.message.reply_text("\n".join(lines))

    async def brand_cmd(update, context):
        if not await guard(update):
            return
        plate = brand_mod.current_plate()
        if not context.args:
            projects = [p[0] for p in projects_mod.list_projects()]
            lines = [
                f"active brand: *{settings.project}*",
                f'tagline: "{plate.tagline}"' if plate.tagline else "",
                "",
                "projects: " + ", ".join(projects),
                "",
                "switch with: /brand <name>",
            ]
            await update.message.reply_text("\n".join(l for l in lines if l))
            return
        name = context.args[0].lstrip("@").lower()
        try:
            projects_mod.set_active(name)
        except (FileNotFoundError, ValueError) as exc:
            await update.message.reply_text(f"error: {exc}")
            return
        settings.refresh_project(name)
        new_plate = brand_mod.current_plate()
        await update.message.reply_text(
            f"✅ switched to *{name}*\n"
            f'tagline: "{new_plate.tagline}"' if new_plate.tagline else
            f"✅ switched to {name}"
        )

    async def fetchtweet_cmd(update, context):
        if not await guard(update):
            return
        if not context.args:
            await update.message.reply_text("usage: /fetchtweet <url-or-id>")
            return
        td = x_fetch.fetch(context.args[0], use_cache=False)
        if td is None:
            await update.message.reply_text("❌ could not fetch tweet")
            return
        ops_db.tweet_upsert(
            id=td.id, handle=td.author_handle, text=td.text,
            created_at=td.created_at,
            favorite_count=td.favorite_count, reply_count=td.reply_count,
            payload=td.as_dict(),
        )
        if td.author_handle:
            ops_db.watchlist_add(td.author_handle)
        # Send the card immediately.
        recent = ops_db.tweets_recent(limit=1)
        if recent:
            await _send_tweet_card(context, update.effective_chat.id, recent[0])

    # -------- callback dispatcher --------

    async def callback_dispatcher(update, context):
        if not await guard(update):
            return
        q = update.callback_query
        if q is None:
            return
        await q.answer()  # ack button press
        data = q.data or ""
        if not data.startswith("t:"):
            return
        parts = data.split(":", 2)
        if len(parts) < 3:
            return
        _, action, tweet_id = parts
        tweets = ops_db.tweets_recent(limit=500)
        t = next((x for x in tweets if x["id"] == tweet_id), None)
        if t is None:
            await q.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠ tweet not in cache — refetch with /fetchtweet",
            )
            return
        if action == "refs":
            await _send_refs_action(update, context, t)
        elif action == "brief":
            await _send_brief_action(update, context, t, kind="image")
        elif action == "video":
            await _send_brief_action(update, context, t, kind="video")
        elif action == "raid":
            await _send_raid_action(update, context, t)
        elif action == "spong":
            await _send_spongify_action(update, context, t)

    async def _send_refs_action(update, context, t):
        plan = reply_for_mod.plan(t["url"], generate_brief=False, open_browser=False)
        chat_id = update.effective_chat.id
        if plan is None:
            await context.bot.send_message(chat_id=chat_id, text="❌ plan failed")
            return
        refs = plan.ref_matches[:3]
        if not refs:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "No library refs matched this tweet.\n"
                    f"Top format suggestion: *{plan.format_matches[0].slug_or_id}*\n"
                    "Tap ✍ Brief to generate one."
                ),
            )
            return
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Top {len(refs)} matches for @{t['handle']}:",
        )
        for m in refs:
            caption = (
                f"[{m.score}] {m.description[:140]}\n"
                f"hits: {', '.join(m.trigger_hits[:5])}"
            )
            if m.media_path and str(m.media_path):
                try:
                    with open(m.media_path, "rb") as fh:
                        await context.bot.send_photo(
                            chat_id=chat_id, photo=fh, caption=caption,
                        )
                    ops_db.action_log(
                        tweet_id=t["id"], kind="grab_ref", slug_or_ref_id=m.slug_or_id,
                    )
                    continue
                except (OSError, FileNotFoundError):
                    pass
            await context.bot.send_message(chat_id=chat_id, text=caption)

    async def _send_brief_action(update, context, t, *, kind: str):
        """Emit a Grok-Imagine-ready visual prompt (~100-200 words),
        not the long meta-brief. Paste straight into Grok."""
        from . import grok_prompts
        intent = (
            f"reply art tied to tweet by @{t['handle']}: "
            f"\"{(t['text'] or '')[:180]}\""
        )
        if kind == "image":
            slug = flow_post._pick_format(intent, kind="image")
        else:
            from . import format_suggest
            slug = format_suggest.best(intent, kind="video")
        chat_id = update.effective_chat.id
        try:
            prompt_text = grok_prompts.build(slug, target_tweet=t)
        except ValueError as exc:
            await context.bot.send_message(chat_id=chat_id, text=f"error: {exc}")
            return
        header = (
            f"📝 *{slug}* ({'video' if kind == 'video' else 'image'})\n"
            f"Paste into Grok Imagine — tap code block to copy."
        )
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Grok", url=GROK_URL),
            InlineKeyboardButton("🔗 tweet", url=t["url"]),
            InlineKeyboardButton("🔄 reroll", callback_data=f"t:{kind}:{t['id']}"),
        ]])
        await context.bot.send_message(
            chat_id=chat_id, text=header,
            reply_markup=kb, parse_mode="Markdown",
        )
        await context.bot.send_message(
            chat_id=chat_id, text=f"```\n{prompt_text}\n```",
            parse_mode="Markdown",
        )
        ops_db.action_log(tweet_id=t["id"], kind=kind, slug_or_ref_id=slug)

    async def _send_spongify_action(update, context, t):
        chat_id = update.effective_chat.id
        handle = t["handle"]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🟢 spongifying @{handle} …",
        )
        try:
            from . import spongify
            batch = spongify.spongify_handles([handle])
        except RuntimeError as exc:
            await context.bot.send_message(chat_id=chat_id, text=f"error: {exc}")
            return
        except Exception as exc:
            await context.bot.send_message(
                chat_id=chat_id, text=f"error: {type(exc).__name__}: {exc}",
            )
            return
        if not batch.targets:
            reason = batch.failures[0][1] if batch.failures else "no pfp available"
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ spongify failed: {reason}",
            )
            return
        target = batch.targets[0]
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 open Grok", url=GROK_URL),
            InlineKeyboardButton("🔗 open tweet", url=t["url"]),
        ]])
        # Send the downloaded profile pic so the operator can forward
        # it straight into Grok Imagine's image input.
        try:
            with open(target.local_pfp_path, "rb") as fh:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=fh,
                    caption=(
                        f"@{handle} profile pic\n"
                        f"↓ upload this to Grok Imagine + paste the prompt below"
                    ),
                    reply_markup=kb,
                )
        except OSError as exc:
            await context.bot.send_message(chat_id=chat_id, text=f"pfp read error: {exc}")
            return
        # Send the prompt as a code block for easy copy on mobile.
        for chunk in _chunks(target.prompt, size=3800):
            await context.bot.send_message(
                chat_id=chat_id, text=f"```\n{chunk}\n```",
                parse_mode="Markdown",
            )
        ops_db.action_log(
            tweet_id=t["id"], kind="spongify", slug_or_ref_id=handle,
            note=str(target.local_pfp_path),
        )

    async def _send_raid_action(update, context, t):
        chat_id = update.effective_chat.id
        theme = (t.get("text") or "")[:200]
        result = flow_post.raid(theme, copy_clipboard=False)
        if not result.briefs:
            await context.bot.send_message(
                chat_id=chat_id, text="❌ raid produced no briefs",
            )
            return
        header = (
            f"🎯 raid pack for @{t['handle']} — {len(result.briefs)} briefs\n"
            f"brand: *{result.brand}*\n"
            f"👉 Grok: {GROK_URL}"
        )
        await context.bot.send_message(chat_id=chat_id, text=header)
        for i, (intent, slug, folder) in enumerate(result.briefs, 1):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"*[{i}/{len(result.briefs)}] {slug}*\n{intent[:200]}",
                parse_mode="Markdown",
            )
        ops_db.action_log(tweet_id=t["id"], kind="raid",
                          slug_or_ref_id=",".join(b[1] for b in result.briefs))

    async def on_url_message(update, context):
        """Auto-process any X URL pasted or forwarded into the chat.

        Triggered by the filters.Regex handler in register_ops_handlers.
        Fetches the tweet + upserts to ops_db + sends a card with the
        full action-button set. Works in DMs and in allowlisted groups.
        """
        if not await guard(update):
            return
        msg = update.message
        if msg is None or not msg.text:
            return
        import re as _re
        urls = _re.findall(
            r"https?://(?:www\.)?(?:twitter|x)\.com/[^/\s]+/status/\d+",
            msg.text,
            _re.IGNORECASE,
        )
        if not urls:
            return
        # Process up to 3 URLs per message to avoid flooding.
        for url in urls[:3]:
            td = x_fetch.fetch(url, use_cache=False)
            if td is None:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ could not fetch {url}",
                )
                continue
            ops_db.tweet_upsert(
                id=td.id, handle=td.author_handle, text=td.text,
                created_at=td.created_at,
                favorite_count=td.favorite_count,
                reply_count=td.reply_count,
                payload=td.as_dict(),
            )
            if td.author_handle:
                ops_db.watchlist_add(td.author_handle)
            recent = ops_db.tweets_recent(limit=1, handle=td.author_handle)
            if recent:
                await _send_tweet_card(context, update.effective_chat.id, recent[0])

    return {
        "feed": feed_cmd,
        "watch": watch_cmd,
        "unwatch": unwatch_cmd,
        "watchlist": watchlist_cmd,
        "brand": brand_cmd,
        "fetchtweet": fetchtweet_cmd,
        "_callback": callback_dispatcher,
        "_on_url": on_url_message,
    }


def _chunks(text: str, *, size: int = 3800):
    """Split long text at line boundaries to fit TG message limit."""
    if len(text) <= size:
        yield text
        return
    acc = ""
    for line in text.splitlines(keepends=True):
        if len(acc) + len(line) > size:
            if acc:
                yield acc
            acc = line
        else:
            acc += line
    if acc:
        yield acc


def register_ops_handlers(app, cfg) -> None:
    """Attach all ops command handlers + the callback dispatcher to the app."""
    from telegram.ext import (
        CommandHandler, CallbackQueryHandler, MessageHandler, filters,
    )
    handlers = _build_ops_handlers(cfg)
    for name, fn in handlers.items():
        if name.startswith("_"):
            continue
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(handlers["_callback"], pattern=r"^t:"))
    # Auto-catch X URLs pasted or forwarded into chat. Triggers on plain
    # text messages that contain a twitter.com or x.com /status/<id> URL.
    # Lets the operator scroll X on their phone or BlueStacks, tap
    # Share → Copy link, paste into the bot — zero typing, full card
    # with action buttons back instantly.
    import re as _re
    url_re = _re.compile(
        r"https?://(?:www\.)?(?:twitter|x)\.com/[^/\s]+/status/\d+",
        _re.IGNORECASE,
    )
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(url_re),
        handlers["_on_url"],
    ))


# ---- push hook for the (future) watchlist poller ---------------------------


def push_new_tweets(cfg, tweets: list[dict]) -> None:
    """Call from a watchlist poller when new tweets arrive.

    Sends each tweet as a card with inline buttons to cfg.chat_id_for_scheduler.
    Noop if chat_id isn't configured.
    """
    if not cfg.chat_id_for_scheduler or not cfg.token:
        return
    try:
        from telegram import Bot
    except ImportError:
        return
    import asyncio
    bot = Bot(cfg.token)
    async def _go():
        for t in tweets:
            await _send_tweet_card(bot, cfg.chat_id_for_scheduler, t)
    try:
        asyncio.run(_go())
    except RuntimeError:
        # Already-running loop (e.g. called from inside another coroutine).
        loop = asyncio.get_event_loop()
        loop.create_task(_go())
