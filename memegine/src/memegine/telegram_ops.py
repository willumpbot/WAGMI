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

# Two-step button flow:
#   Step 1: pick BRAND for the reply (kilroy / motion / spong)
#   Step 2: pick ACTION to produce
# Clearer labels so the operator knows exactly what each button does.
BRAND_BUTTONS = [
    ("kilroy", "🖼 Kilroy"),
    ("motion", "🎬 Motion"),
    ("spong",  "🟢 Spong"),
]

# Actions grouped into rows — each button's label makes the output
# concrete, not jargon.
ACTION_ROWS = {
    "kilroy": [
        [("image",    "🖼 Make image")],
        [("video",    "🎥 Make video"), ("caption", "💬 Caption")],
        [("raid",     "🎯 5-asset raid pack"), ("refs", "📎 Library refs")],
        [("kpfp",     "🖼 Kilroy their pfp")],
        [("spong",    "🟢 Spongify their pfp")],
        [("back",     "⬅ change brand")],
    ],
    "motion": [
        [("image",    "🎬 Make image")],
        [("video",    "🎥 Make video"), ("caption", "💬 Caption")],
        [("raid",     "🎯 5-asset raid pack"), ("refs", "📎 Library refs")],
        [("back",     "⬅ change brand")],
    ],
    "spong": [
        [("image",    "🟢 Make image")],
        [("video",    "🎥 Make video"), ("caption", "💬 Caption")],
        [("raid",     "🎯 4-asset raid pack"), ("refs", "📎 Library refs")],
        [("spong",    "🟢 Spongify their pfp")],
        [("back",     "⬅ change brand")],
    ],
}


def _keyboard_brand_select(tweet_id: str):
    """Step 1: operator picks which brand to raid with."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    row = [
        InlineKeyboardButton(label, callback_data=f"t:b:{brand}:{tweet_id}")
        for brand, label in BRAND_BUTTONS
    ]
    return InlineKeyboardMarkup([row])


def _keyboard_action_select(brand: str, tweet_id: str):
    """Step 2: operator picks what to produce for the chosen brand."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for row_defs in ACTION_ROWS.get(brand, ACTION_ROWS["kilroy"]):
        buttons = []
        for action, label in row_defs:
            buttons.append(InlineKeyboardButton(
                label, callback_data=f"t:a:{brand}:{action}:{tweet_id}",
            ))
        rows.append(buttons)
    return InlineKeyboardMarkup(rows)


# Legacy shim — old pushes / one-shots still call this. Keep the 2-row
# layout so existing callers keep working.
def _keyboard_for_tweet(tweet_id: str):
    return _keyboard_brand_select(tweet_id)


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
    Always starts in step-1 mode (brand selector).
    """
    from telegram import Bot
    bot = update_or_context.bot if hasattr(update_or_context, "bot") else update_or_context
    caption = _format_tweet_caption(t) + "\n\n👇 Pick a brand for the reply:"
    kb = _keyboard_brand_select(t["id"])
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

    async def gallery_cmd(update, context):
        """Show recent refs from the active brand's library.

        Usage:
          /gallery              — 5 most recent images (default)
          /gallery 10           — 10 most recent
          /gallery motion       — switch brand
          /gallery motion video — return video files from known
                                  video sources (motion = drive-folder/MOTION)
        """
        if not await guard(update):
            return
        from . import reference_lib as _rl, projects as _projects
        chat_id = update.effective_chat.id
        args = context.args or []
        n = 5
        brand = settings.project
        want_video = False
        filter_tags: list[str] = []
        for tok in args:
            if tok.isdigit():
                n = max(1, min(20, int(tok)))
            elif tok.lower() in ("motion", "kilroy", "spong"):
                brand = tok.lower()
            elif tok.lower() in ("video", "videos", "v"):
                want_video = True
            else:
                # any other token → tag filter
                filter_tags.append(tok.lower())
        n = min(n, 10)
        if brand != settings.project:
            try:
                _projects.set_active(brand)
                settings.refresh_project(brand)
            except Exception as exc:
                await context.bot.send_message(chat_id=chat_id, text=f"error: {exc}")
                return

        # Video mode — bypass refs index, stream from known video source folder
        if want_video:
            from pathlib import Path as _P
            # Known motion video source from earlier corpus ingest
            candidates = [
                _P(r"C:\Users\vince\WAGMI\memegine-inbox\drive-folder") / brand.upper(),
                settings.references_dir.parent / "videos",
                settings.references_dir,
            ]
            vids: list[_P] = []
            for cand in candidates:
                if cand.exists():
                    for f in sorted(cand.iterdir()):
                        if f.is_file() and f.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
                            vids.append(f)
                    if vids:
                        break
            if not vids:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🎬 no videos found for {brand}. expected at "
                         f"memegine-inbox/drive-folder/{brand.upper()}/ or "
                         f"data/projects/{brand}/videos/",
                )
                return

            # If filter_tags specified, cross-reference videos to refs by
            # matching video stem ↔ ref source field
            if filter_tags:
                all_refs = _rl.search()
                filter_set = {t.lower() for t in filter_tags}
                # source like "video:01a92a41..." contains the hash stem
                matching_stems: set[str] = set()
                for e in all_refs:
                    e_tags = {t.lower() for t in (e.get("tags") or [])}
                    if not (filter_set & e_tags):
                        continue
                    src = str(e.get("source") or "")
                    # Extract hash from source
                    for part in src.replace(":", " ").replace("/", " ").split():
                        stem = part.split(".")[0]
                        if len(stem) >= 16:
                            matching_stems.add(stem)
                filtered = [
                    v for v in vids
                    if any(stem in v.stem for stem in matching_stems)
                ]
                if filtered:
                    vids = filtered
                    header = (
                        f"🎬 {brand} videos — filter: {','.join(filter_tags)} — "
                        f"{min(n, len(vids))} of {len(vids)} matches"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🎬 no videos matched tags {filter_tags} — "
                             f"showing recent instead",
                    )
                    header = f"🎬 {brand} — {min(n, len(vids))} recent videos"
            else:
                header = f"🎬 {brand} videos — {min(n, len(vids))} of {len(vids)} total"

            await context.bot.send_message(chat_id=chat_id, text=header)
            for v in vids[-n:]:
                try:
                    with open(v, "rb") as fh:
                        await context.bot.send_video(
                            chat_id=chat_id, video=fh,
                            caption=f"{v.name} · {v.stat().st_size // 1024}KB",
                            supports_streaming=True,
                        )
                except Exception as exc:
                    await context.bot.send_message(
                        chat_id=chat_id, text=f"⚠ {v.name}: {exc}",
                    )
            return

        # Filter by tags if specified
        all_entries = _rl.search()
        if filter_tags:
            filter_set = {t.lower() for t in filter_tags}
            entries = [
                e for e in all_entries
                if filter_set & {t.lower() for t in (e.get("tags") or [])}
            ]
            # Dedupe by source video so we don't send 5 frames of same video
            seen = set()
            dedup = []
            for e in entries:
                src = e.get("source") or e.get("id")
                if src in seen:
                    continue
                seen.add(src)
                dedup.append(e)
            entries = dedup[:n]
            header = (
                f"📂 {brand} library — filter: {','.join(filter_tags)} — "
                f"{len(entries)} of {len(dedup)} unique matches"
            )
        else:
            entries = _rl.recent(n)
            header = f"📂 {brand} library — {n} most recent of {len(all_entries)} total"
        if not entries:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"📂 {brand}{' tag=' + ','.join(filter_tags) if filter_tags else ''}: "
                    f"no matches. try /gallery {brand} without filter."
                ),
            )
            return
        await context.bot.send_message(chat_id=chat_id, text=header)
        for e in entries[:n]:
            # The ref-lib index stores `filename`, not full `path`.
            # Compute path from references_dir + filename.
            path = e.get("path")
            if not path:
                fname = e.get("filename")
                if fname:
                    path = str(settings.references_dir / fname)
            if not path:
                continue
            caption = (
                f"id: {e.get('id','?')}\n"
                f"tags: {', '.join(e.get('tags', [])[:5])}\n"
                f"notes: {(e.get('notes') or '')[:100]}"
            )
            try:
                with open(path, "rb") as fh:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=fh, caption=caption[:1000],
                    )
            except (OSError, FileNotFoundError):
                await context.bot.send_message(
                    chat_id=chat_id, text=f"⚠ can't read {path}",
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
        parts = data.split(":")
        # New format:
        #   t:b:{brand}:{tweet_id}                 — brand chosen, show actions
        #   t:a:{brand}:{action}:{tweet_id}        — action fired
        # Legacy format (still handled for any in-flight messages):
        #   t:{action}:{tweet_id}
        if len(parts) == 4 and parts[1] == "b":
            # Brand pick — swap keyboard to action menu
            _, _, brand, tweet_id = parts
            if brand in ACTION_ROWS:
                try:
                    await q.edit_message_reply_markup(
                        reply_markup=_keyboard_action_select(brand, tweet_id)
                    )
                except Exception:
                    pass
            return
        if len(parts) == 5 and parts[1] == "a":
            _, _, brand, action, tweet_id = parts
            if action == "back":
                try:
                    await q.edit_message_reply_markup(
                        reply_markup=_keyboard_brand_select(tweet_id)
                    )
                except Exception:
                    pass
                return
        elif len(parts) == 3:
            # legacy path — treat as action=parts[1], no brand change
            _, action, tweet_id = parts
            brand = settings.project
        else:
            return

        # Switch active project to the chosen brand for this tap
        if brand and brand != settings.project:
            try:
                from . import projects as _projects
                _projects.set_active(brand)
                settings.refresh_project(brand)
            except Exception:
                pass

        tweets = ops_db.tweets_recent(limit=500)
        t = next((x for x in tweets if x["id"] == tweet_id), None)
        if t is None:
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠ tweet not in cache — paste the URL again.",
            )
            return

        if action == "refs":
            await _send_refs_action(update, context, t)
        elif action in ("brief", "image"):
            await _send_brief_action(update, context, t, kind="image")
        elif action == "video":
            await _send_brief_action(update, context, t, kind="video")
        elif action == "raid":
            await _send_raid_action(update, context, t)
        elif action == "spong":
            await _send_spongify_action(update, context, t)
        elif action == "kpfp":
            await _send_kilroy_pfp_action(update, context, t)
        elif action == "caption":
            await _send_caption_action(update, context, t)

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

    async def _send_kilroy_pfp_action(update, context, t):
        """Turn the author's pfp INTO a Kilroy-was-here peek pose.

        This is NOT a small overlay — it's an image-to-image transform:
        the subject's face becomes the peeking character, with just
        eyes + hair showing above a wall, hands gripping the wall,
        '[handle] was here' caption below.

        Works like Spongify: we send the pfp + a Grok-ready prompt so
        the operator pastes both into Grok Imagine, which renders the
        transformation. Free (uses X Premium's Grok access).
        """
        chat_id = update.effective_chat.id
        handle = t["handle"]
        await context.bot.send_message(
            chat_id=chat_id, text=f"🖼 building kilroy-ify prompt for @{handle}…",
        )
        pfp_url = (t.get("author_profile_image_url") or "").strip()
        if not pfp_url:
            from . import spongify as _sp
            pfp_url = _sp._profile_pic_url(handle) or ""
        if not pfp_url:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ no pfp cached — paste a tweet from them first.",
            )
            return

        prompt = f"""Using the attached reference image of @{handle}, transform it into a \
Kilroy-was-here peek pose:

- KEEP the subject's face, hair, eyes, skin tone, and stylistic \
treatment EXACTLY as in the reference. Do not change their identity.
- CROP to show ONLY the top third of the face: the eyes, eyebrows, \
forehead, and hair. Everything from the nose down should be hidden \
behind a wall.
- ADD two hands at the bottom of the frame with fingers gripping \
the top of a wall. CRITICAL: the hands must match the subject's \
own art style (anime → anime hands, pepe/cracked-texture → same \
texture hands, cartoon → cartoon, photoreal → photoreal). Do NOT \
render generic default-cartoon hands that clash with the subject.
- BACKGROUND: simple — either plain pale color (light pink / cream / \
gray), or the subject's original background but heavily blurred. \
Keep the focus on the subject's face + the hands + the caption.
- CAPTION: hand-lettered marker-style text BELOW the wall line \
reading exactly: "{handle.lower()} was here"
- OUTPUT: 1:1 square aspect.
- STYLE: clean cartoon outline + subject's original art style. NO \
photoreal rendering, NO AI-smooth skin, NO extra characters.

Reference the classic "Kilroy was here" WWII peek-over-wall meme for \
pose and composition, but the face/character stays as the original \
subject."""

        import io, urllib.request
        # Download the pfp for attachment
        try:
            req = urllib.request.Request(pfp_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                pfp_bytes = r.read()
        except Exception as exc:
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ pfp download failed: {exc}",
            )
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Grok", url=GROK_URL),
            InlineKeyboardButton("🔗 tweet", url=t["url"]),
            InlineKeyboardButton("🔁 reroll", callback_data=f"t:a:kilroy:kpfp:{t['id']}"),
        ]])
        await context.bot.send_photo(
            chat_id=chat_id, photo=io.BytesIO(pfp_bytes),
            caption=(
                f"@{handle} profile pic — upload this to Grok Imagine + "
                f"paste the prompt below. Output: their face peeking "
                f"over a wall with '{handle.lower()} was here' caption."
            ),
            reply_markup=kb,
        )
        # The prompt as code-block for easy copy
        await context.bot.send_message(
            chat_id=chat_id, text=f"```\n{prompt}\n```",
            parse_mode="Markdown",
        )
        ops_db.action_log(
            tweet_id=t["id"], kind="kilroy_pfp_transform",
            slug_or_ref_id=handle,
        )

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

        Dispatches based on terse raid syntax:
            <url> raid kilroy                → run raid pack for kilroy brand
            <url> spongify                   → spongify the tweet author
            <url> motion video + caption     → motion video brief + caption
            <url>  (bare)                    → old behavior: tap-card
        See raid_parser.parse() for the full grammar.
        """
        if not await guard(update):
            return
        msg = update.message
        if msg is None or not msg.text:
            return
        from . import raid_parser
        cmd = raid_parser.parse_and_normalize(
            msg.text, default_brand=settings.project,
        )
        chat_id = update.effective_chat.id
        if not cmd.url:
            return

        # Fetch + upsert the tweet (shared between all paths).
        td = x_fetch.fetch(cmd.url, use_cache=False)
        if td is None:
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ could not fetch {cmd.url}",
            )
            return
        ops_db.tweet_upsert(
            id=td.id, handle=td.author_handle, text=td.text,
            created_at=td.created_at,
            favorite_count=td.favorite_count,
            reply_count=td.reply_count,
            payload=td.as_dict(),
        )
        if td.author_handle:
            ops_db.watchlist_add(td.author_handle)
        # Switch to the target brand if the command specified one.
        if cmd.brand and cmd.brand != settings.project:
            try:
                from . import projects as _projects
                _projects.set_active(cmd.brand)
                settings.refresh_project(cmd.brand)
            except Exception:
                pass

        # ---- If bare URL (no raid keywords), show the tap card ----
        if not cmd.is_raid_command:
            recent = ops_db.tweets_recent(limit=1, handle=td.author_handle)
            if recent:
                await _send_tweet_card(context, chat_id, recent[0])
            return

        # ---- Route based on actions ----
        tweet_dict = ops_db.tweets_recent(limit=1, handle=td.author_handle)[0]
        did_anything = False

        if "spongify" in cmd.actions:
            await _send_spongify_action(update, context, tweet_dict)
            did_anything = True
        if "raid" in cmd.actions:
            await _send_raid_action(update, context, tweet_dict)
            did_anything = True
        if "video" in cmd.actions:
            await _send_brief_action(update, context, tweet_dict, kind="video")
            did_anything = True
        if "still" in cmd.actions or "brief" in cmd.actions:
            await _send_brief_action(update, context, tweet_dict, kind="image")
            did_anything = True
        if cmd.include_caption:
            await _send_caption_action(update, context, tweet_dict)
            did_anything = True
        if not did_anything:
            # Brand specified but no action — default to a brief.
            await _send_brief_action(update, context, tweet_dict, kind="image")

    async def _send_caption_action(update, context, t):
        """Simple caption suggestions based on brand tagline + tweet theme."""
        chat_id = update.effective_chat.id
        plate = brand_mod.current_plate()
        tagline = plate.tagline or ""
        # Three caption options at escalating tightness.
        opts = []
        if tagline:
            opts.append(tagline.rstrip("."))
        opts.append(f"{t['handle']} cooked")
        opts.append(f"kilroy was here when @{t['handle']} posted this" if settings.project == "kilroy" else f"@{t['handle']}")
        opts.append("we like the moon" if settings.project == "spong" else "god forbid")
        text = "💬 caption options for this reply:\n\n" + "\n".join(f"• {o}" for o in opts[:4])
        await context.bot.send_message(chat_id=chat_id, text=text)

    return {
        "feed": feed_cmd,
        "watch": watch_cmd,
        "unwatch": unwatch_cmd,
        "watchlist": watchlist_cmd,
        "brand": brand_cmd,
        "fetchtweet": fetchtweet_cmd,
        "gallery": gallery_cmd,
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
