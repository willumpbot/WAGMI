"""Telegram bot — brief delivery on your phone.

The vision: you're walking, some news hits, you pull out your phone,
send `/piece trader dumping at 3am` to your private Memegine bot. Bot
picks a format, assembles the brief, and sends the SYSTEM + USER blocks
back in chat. You paste into Grok (which is already in X on your phone).
You iterate, you post, you screenshot the winner and send it back to the
bot with `/winner` to log it to the codex.

Dependencies: python-telegram-bot (installed via the `telegram` extra).
Without the extra, this module imports fine but raises on bot start.

Auth: allowlist of Telegram user IDs from env var
MEMEGINE_TELEGRAM_ALLOWED_USER_IDS (comma-separated). If empty, bot
refuses to start — no accidental open bots.

Commands:
  /help                              list commands
  /piece <intent>                    auto-picks format + kind, full bundle
  /brief <intent> [f:<slug>]         image brief with optional format
  /shots <intent>                    shot-list brief for video
  /caption <concept>                 X caption brief
  /variants <n> <prompt>             variant brief, n between 3-8
  /formats                           list all format slugs
  /suggest <intent>                  top 3 format suggestions
  /lint <prompt>                     deep lint with score
  /grade <intent>                    idea grader 0-100 (landability)
  /execute <intent>                  run brief via Claude API (if key set)
  /topic <text>                      append to topic queue
  /topics                            list queued topics (top 10)
  /codex                             show style codex head
  /winner <prompt ||| why>           append winner + auto-extract patterns
  /flop <what ||| why>               append flop to kill list
  /refs                              list 10 most recent refs
  /status                            queue + counts
  /reverse <caption>                 reverse-brief the next photo you send

Photo upload: bot keeps a per-user "mode" (default = add to refs). If you
sent /reverse as the last command, the next photo is instead handled as a
reverse-engineer brief.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ._time import now_iso as _now_iso
from .config import settings


# ---- config ----------------------------------------------------------------


@dataclass
class BotConfig:
    token: str
    allowed_user_ids: set[int]
    chat_id_for_scheduler: Optional[int] = None  # default chat for scheduled deliveries

    @classmethod
    def from_env(cls) -> "BotConfig":
        token = os.environ.get("MEMEGINE_TELEGRAM_BOT_TOKEN", "").strip()
        raw = os.environ.get("MEMEGINE_TELEGRAM_ALLOWED_USER_IDS", "")
        ids = {int(x) for x in raw.split(",") if x.strip().isdigit()}
        chat = os.environ.get("MEMEGINE_TELEGRAM_CHAT_ID", "").strip()
        chat_id = int(chat) if chat.isdigit() or (chat.startswith("-") and chat[1:].isdigit()) else None
        return cls(token=token, allowed_user_ids=ids, chat_id_for_scheduler=chat_id)


class BotConfigError(RuntimeError):
    """Raised when config is missing or invalid."""


def _require_telegram():
    try:
        import telegram  # noqa: F401
        from telegram.ext import Application  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "python-telegram-bot not installed. Run: pip install -e '.[telegram]'"
        ) from exc


# ---- per-user session state (in memory) -----------------------------------


@dataclass
class UserSession:
    # When non-empty, the next photo upload is processed with this mode.
    pending_photo_action: str = ""   # "reverse" | "ref_add" | ""
    pending_context: str = ""        # e.g. operator note for reverse


SESSIONS: dict[int, UserSession] = {}


def _session(uid: int) -> UserSession:
    sess = SESSIONS.get(uid)
    if sess is None:
        sess = UserSession()
        SESSIONS[uid] = sess
    return sess


# ---- helpers ---------------------------------------------------------------


MAX_TELEGRAM_MSG = 3800  # stay under the 4096 limit with headroom


def _chunks(text: str, size: int = MAX_TELEGRAM_MSG) -> list[str]:
    """Split long text into telegram-safe chunks, preferring newline breaks."""
    if len(text) <= size:
        return [text]
    out: list[str] = []
    remaining = text
    while len(remaining) > size:
        cut = remaining.rfind("\n", 0, size)
        if cut == -1:
            cut = size
        out.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        out.append(remaining)
    return out


async def _reply_long(update, text: str) -> None:
    for chunk in _chunks(text):
        await update.message.reply_text(chunk)


def _parse_prompt_with_format(argstring: str) -> tuple[str, Optional[str]]:
    """Parse "<intent> [f:<slug>]" — returns (intent, slug or None).

    This is a minimal hand-parser so we don't force the operator to quote
    anything while typing on a phone.
    """
    if not argstring:
        return "", None
    parts = argstring.rsplit(" f:", 1)
    if len(parts) == 2 and parts[1].strip():
        return parts[0].strip(), parts[1].strip().split()[0]
    return argstring.strip(), None


def _is_allowed(update, cfg: BotConfig) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if not cfg.allowed_user_ids:
        # We refuse at startup if allowlist is empty, but double-check here.
        return False
    return int(user.id) in cfg.allowed_user_ids


# ---- handlers --------------------------------------------------------------


HELP_TEXT = """Memegine bot — brief delivery

/piece <intent>         auto-pick format, full bundle
/brief <intent>         image brief (add ' f:<slug>' to force a format)
/shots <intent>         shot-list brief for video
/caption <concept>      X caption brief
/variants <n> <prompt>  N variants of a winning prompt
/variants-last [n]      N variants from your latest winner
/batch <n> <theme>      N briefs across varied formats for one theme
/formats                list all formats
/fragments              list fragment library categories
/suggest <intent>       top 3 format suggestions
/lint <prompt>          deep lint with 0-100 score
/caption-lint <cap>     validate an X caption
/grade <intent>         idea grader 0-100 (landability)
/execute <intent>       run brief via Claude API (if key set)
/topic <text>           append to topic queue
/topics                 list queued topics (top 10)
/codex                  show head of style codex
/distill                mine recent briefs for recurring patterns
/graduate               promote patterns seen >=5 times to Core Patterns
/winner <prompt ||| why>  log winner + extract patterns
/flop <what ||| why>    log flop
/refs                   10 most recent refs
/stats [daily|weekly]   activity report
/perf_summary           engagement summary by format/pattern/hour
/perf_paste <block>     parse pasted X stats and log to performance
/doctor                 run health check
/journal [days]         chronological feed across all stores
/next                   one-screen "what should I make?" dashboard
/session_start [name]   mark start of a working block
/session_end            close current session
/x_prepare <post_id>    X post pre-flight (lint + clipboard block)
/codex_audit            duplicates / contradictions in the codex
/fix_prompt <prompt>    auto-insert fragments to plug missing craft
/like_winner <intent>   clone last winner's craft for a new subject
/last                   last brief/winner/post/session in one view
/search <query>         search across briefs/refs/posts/codex/topics
/format_health          classify formats by performance
/quick <intent>         grade + queue an idea (phone capture)
/cheatsheet             top 20 commands
/status                 queue + counts
/reverse [context]      reverse-brief the next photo you send
Photo upload (no command) → added to the reference library.
"""


def _build_handlers(cfg: BotConfig):
    from telegram import Update
    from telegram.ext import ContextTypes

    # Lazy imports of memegine modules so unit tests can import this file
    # without pulling in every dep.
    from . import (
        archive,
        auto_codex,
        batch as batch_mod,
        caption_linter,
        codex_audit as codex_audit_mod,
        copy_writer,
        deep_linter,
        doctor as doctor_mod,
        executor as ex_mod,
        format_suggest,
        fragments as fragments_mod,
        idea_grader,
        journal as journal_mod,
        next_action,
        performance,
        pipeline as pipeline_mod,
        prompt_engine,
        reference_lib,
        reverse_engineer,
        session as session_mod,
        shot_list as shot_list_mod,
        stats as stats_mod,
        style_codex,
        topics as topics_mod,
        variants as variants_mod,
        x_post as x_post_mod,
    )

    async def guard(update: "Update") -> bool:
        if not _is_allowed(update, cfg):
            try:
                if update.message:
                    await update.message.reply_text("unauthorized")
            except Exception:
                pass
            return False
        return True

    async def help_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        await update.message.reply_text(HELP_TEXT)

    async def piece_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = " ".join(context.args or []).strip()
        intent, forced_slug = _parse_prompt_with_format(args)
        if not intent:
            await update.message.reply_text("usage: /piece <intent> [f:<slug>]")
            return
        kind = format_suggest.infer_kind(intent)
        slug = forced_slug or format_suggest.best(intent, kind=kind)
        try:
            bundle = pipeline_mod.build(
                intent,
                kind=kind,
                format_slug=slug if kind == "image" else None,
            )
        except Exception as exc:
            await update.message.reply_text(f"pipeline failed: {exc}")
            return
        # Send each brief's user body (the thing operator pastes).
        header = f"bundle {bundle.id}  kind={kind}  format={slug if kind == 'image' else '-'}"
        await update.message.reply_text(header)
        for name, brief in bundle.briefs.items():
            body = f"--- {name} --- (paste both blocks into Claude Code)\n\n## SYSTEM\n{brief['system']}\n\n## USER\n{brief['user']}"
            await _reply_long(update, body)
        await update.message.reply_text(f"bundle saved: {bundle.folder}")

    async def brief_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = " ".join(context.args or []).strip()
        intent, forced_slug = _parse_prompt_with_format(args)
        if not intent:
            await update.message.reply_text("usage: /brief <intent> [f:<slug>]")
            return
        slug = forced_slug or format_suggest.best(intent, kind="image")
        try:
            system, user = prompt_engine.assemble_offline_prompt(intent, slug)
        except Exception as exc:
            await update.message.reply_text(f"brief failed: {exc}")
            return
        archive.save(kind="prompt", intent=intent, system=system, user=user, format_=slug)
        await _reply_long(update, f"format: {slug}\n\n## SYSTEM\n{system}\n\n## USER\n{user}")

    async def shots_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        intent = " ".join(context.args or []).strip()
        if not intent:
            await update.message.reply_text("usage: /shots <intent>")
            return
        system, user = shot_list_mod.assemble_offline_shot_list_prompt(intent)
        archive.save(kind="shots", intent=intent, system=system, user=user)
        await _reply_long(update, f"## SYSTEM\n{system}\n\n## USER\n{user}")

    async def caption_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        concept = " ".join(context.args or []).strip()
        if not concept:
            await update.message.reply_text("usage: /caption <concept>")
            return
        system, user = copy_writer.assemble_offline_copy_prompt(concept, "image")
        archive.save(kind="copy", intent=concept, system=system, user=user)
        await _reply_long(update, f"## SYSTEM\n{system}\n\n## USER\n{user}")

    async def variants_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = context.args or []
        if len(args) < 2 or not args[0].isdigit():
            await update.message.reply_text("usage: /variants <n> <winning prompt...>")
            return
        n = max(3, min(8, int(args[0])))
        prompt = " ".join(args[1:]).strip()
        if not prompt:
            await update.message.reply_text("missing prompt")
            return
        vb = variants_mod.build_variant_brief(prompt, n_variants=n)
        archive.save(kind="variants", intent=prompt, system=vb.system, user=vb.user, extra={"n": n})
        await _reply_long(update, f"## SYSTEM\n{vb.system}\n\n## USER\n{vb.user}")

    async def variants_last_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = context.args or []
        n = 6
        if args and args[0].isdigit():
            n = max(3, min(8, int(args[0])))
        try:
            vb = variants_mod.build_from_last_winner(n_variants=n)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        archive.save(kind="variants_last", intent="last_winner", system=vb.system, user=vb.user, extra={"n": n})
        await _reply_long(update, f"## SYSTEM\n{vb.system}\n\n## USER\n{vb.user}")

    async def batch_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = context.args or []
        if len(args) < 2 or not args[0].isdigit():
            await update.message.reply_text("usage: /batch <n> <theme>")
            return
        n = max(1, min(8, int(args[0])))
        theme = " ".join(args[1:]).strip()
        if not theme:
            await update.message.reply_text("missing theme")
            return
        result = batch_mod.build(theme, n=n)
        lines = [f"batch {result.id}  n={n}  folder={result.folder}"]
        for item in result.items:
            lines.append(f"  {item.format_slug}")
        await update.message.reply_text("\n".join(lines))

    async def fragments_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        lines = []
        for cat in fragments_mod.list_categories():
            names = fragments_mod.list_names(cat)
            lines.append(f"{cat} ({len(names)}): {', '.join(names)}")
        await _reply_long(update, "\n".join(lines) or "(no fragments)")

    async def caption_lint_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        text = " ".join(context.args or []).strip()
        if not text:
            await update.message.reply_text("usage: /caption-lint <caption>")
            return
        r = caption_linter.lint(text)
        await _reply_long(update, r.as_text())

    async def distill_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        recent = archive.read_recent(n=200)
        prompts = [r.get("user", "") for r in recent]
        dist = auto_codex.distill_to_codex(prompts, min_frequency=2)
        nonempty = {k: v for k, v in dist.items() if v}
        if not nonempty:
            await update.message.reply_text("no recurring patterns yet")
            return
        lines = []
        for cat, items in nonempty.items():
            lines.append(f"{cat}: " + ", ".join(f"{v}×{c}" for v, c in items[:5]))
        await _reply_long(update, "\n".join(lines))

    async def graduate_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        recent = archive.read_recent(n=500)
        prompts = [r.get("user", "") for r in recent]
        promoted = auto_codex.graduate_patterns(prompts, promotion_threshold=5)
        if not promoted:
            await update.message.reply_text("no patterns crossed threshold=5 yet")
            return
        lines = []
        for cat, items in promoted.items():
            lines.append(f"{cat}: " + ", ".join(f"{v}×{c}" for v, c in items[:5]))
        await _reply_long(update, "promoted to Core Patterns:\n" + "\n".join(lines))

    async def stats_cmd_handler(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = context.args or []
        window = args[0] if args else "daily"
        if window not in ("daily", "weekly", "all"):
            await update.message.reply_text("usage: /stats [daily|weekly|all]")
            return
        report = stats_mod.compute(window=window)
        await _reply_long(update, report.as_text())

    async def perf_summary_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        await _reply_long(update, performance.summary_text())

    async def perf_paste_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        text = " ".join(context.args or []).strip()
        if not text:
            await update.message.reply_text(
                "usage: /perf_paste <paste your X stats block>"
            )
            return
        from . import engagement_parser
        entry, parsed = engagement_parser.log_from_paste(text)
        if entry is None:
            await update.message.reply_text("nothing parsed — no fields detected")
            return
        await update.message.reply_text(
            f"logged {entry.id}  likes={parsed.likes} rt={parsed.reposts} "
            f"replies={parsed.replies} views={parsed.impressions}"
        )

    async def doctor_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        report = doctor_mod.run()
        await _reply_long(update, report.as_text())

    async def journal_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = context.args or []
        days = None
        if args and args[0].isdigit():
            days = int(args[0])
        entries = journal_mod.collect(days=days, limit=30)
        await _reply_long(update, journal_mod.as_text(entries))

    async def next_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        dash = next_action.compute()
        await _reply_long(update, dash.as_text())

    async def session_start_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        name = " ".join(context.args or []).strip() or "telegram session"
        event = session_mod.start(name=name)
        await update.message.reply_text(
            f"started session {event.session_id}  name={event.name}"
        )

    async def session_end_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        event = session_mod.end()
        if event is None:
            await update.message.reply_text("no open session")
            return
        await update.message.reply_text(f"ended session {event.session_id}")

    async def x_prepare_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = context.args or []
        if not args:
            await update.message.reply_text("usage: /x_prepare <post_bundle_id>")
            return
        try:
            plan = x_post_mod.prepare(args[0])
        except FileNotFoundError as exc:
            await update.message.reply_text(str(exc))
            return
        await _reply_long(update, plan.checklist_text())
        await _reply_long(update, plan.clipboard_block())

    async def codex_audit_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        audit = codex_audit_mod.audit()
        await _reply_long(update, audit.as_text())

    async def fix_prompt_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        prompt = " ".join(context.args or []).strip()
        if not prompt:
            await update.message.reply_text("usage: /fix_prompt <prompt>")
            return
        from . import prompt_fixer
        result = prompt_fixer.fix(prompt)
        await _reply_long(update, result.as_text())

    async def like_winner_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        intent = " ".join(context.args or []).strip()
        if not intent:
            await update.message.reply_text("usage: /like_winner <new intent>")
            return
        from . import like_winner
        try:
            result = like_winner.build(intent)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        await _reply_long(update, result.as_text())

    async def last_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        from . import last
        await _reply_long(update, last.compute().as_text())

    async def search_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        query = " ".join(context.args or []).strip()
        if not query:
            await update.message.reply_text("usage: /search <query>")
            return
        from . import search as search_mod
        result = search_mod.run(query, limit=30)
        await _reply_long(update, result.as_text())

    async def format_health_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        from . import format_health
        await _reply_long(update, format_health.evaluate().as_text())

    async def quick_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        intent = " ".join(context.args or []).strip()
        if not intent:
            await update.message.reply_text("usage: /quick <intent>")
            return
        g = idea_grader.grade(intent)
        if g.letter in ("D", "F"):
            tips = "\n".join(f"- {s}" for s in g.suggestions[:3])
            await update.message.reply_text(
                f"grade: {g.letter}  score: {g.score}/100\n\ntighten before queuing:\n{tips}"
            )
            return
        t = topics_mod.add(intent, priority=3, source="telegram_quick")
        await update.message.reply_text(
            f"grade: {g.letter}  score: {g.score}/100\nqueued {t.id}"
        )

    async def cheatsheet_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        from . import cheatsheet
        await _reply_long(update, cheatsheet.render())

    async def formats_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        lines = []
        for f in prompt_engine.load_formats():
            lines.append(f"{f.slug}  ({f.kind})")
        await update.message.reply_text("\n".join(lines))

    async def suggest_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        intent = " ".join(context.args or []).strip()
        if not intent:
            await update.message.reply_text("usage: /suggest <intent>")
            return
        picks = format_suggest.suggest(intent, top_n=3)
        lines = [f"kind inferred: {format_suggest.infer_kind(intent)}"]
        for p in picks:
            lines.append(f"  {p.slug}  ({p.kind})  score={p.score}  hits={p.reasons}")
        await update.message.reply_text("\n".join(lines))

    async def lint_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        prompt = " ".join(context.args or []).strip()
        if not prompt:
            await update.message.reply_text("usage: /lint <prompt>")
            return
        sc = deep_linter.score(prompt)
        letter = deep_linter.grade(sc.score)
        await _reply_long(update, f"grade {letter}\n{sc.as_text()}")

    async def grade_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        intent = " ".join(context.args or []).strip()
        if not intent:
            await update.message.reply_text("usage: /grade <intent>")
            return
        g = idea_grader.grade(intent)
        body = g.as_text()
        if g.format_hits:
            body += "\n  matches: " + ", ".join(g.format_hits)
        await _reply_long(update, body)

    async def execute_cmd_handler(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        args = " ".join(context.args or []).strip()
        intent, forced_slug = _parse_prompt_with_format(args)
        if not intent:
            await update.message.reply_text("usage: /execute <intent> [f:<slug>]")
            return
        if not ex_mod.api_key_available():
            await update.message.reply_text(
                "ANTHROPIC_API_KEY not set — use /piece or /brief for offline mode."
            )
            return
        slug = forced_slug or format_suggest.best(intent, kind="image")
        try:
            brief = ex_mod.execute_prompt_brief(intent, slug)
        except Exception as exc:
            await update.message.reply_text(f"execute failed: {exc}")
            return
        await _reply_long(update, ex_mod.summarize(brief))

    async def topic_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        text = " ".join(context.args or []).strip()
        if not text:
            await update.message.reply_text("usage: /topic <text>")
            return
        t = topics_mod.add(text, source="telegram")
        await update.message.reply_text(f"queued {t.id}: {t.text[:60]}")

    async def topics_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        lst = topics_mod.list_queued(limit=10)
        if not lst:
            await update.message.reply_text("(queue empty)")
            return
        lines = [f"{t['id']}  p={t.get('priority', 3)}  {t.get('text', '')[:70]}" for t in lst]
        await update.message.reply_text("\n".join(lines))

    async def codex_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        txt = style_codex.read()
        if not txt:
            await update.message.reply_text("(codex empty)")
            return
        await _reply_long(update, txt[:6000])

    async def winner_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        raw = " ".join(context.args or []).strip()
        if "|||" not in raw:
            await update.message.reply_text("usage: /winner <prompt> ||| <why it worked>")
            return
        prompt, why = (s.strip() for s in raw.split("|||", 1))
        if not prompt or not why:
            await update.message.reply_text("both prompt and why required")
            return
        patterns = auto_codex.record_winner(prompt, why)
        line = patterns.as_codex_line() if not patterns.is_empty() else "(no pattern tokens)"
        await update.message.reply_text(f"logged. extracted: {line}")

    async def flop_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        raw = " ".join(context.args or []).strip()
        if "|||" not in raw:
            await update.message.reply_text("usage: /flop <what> ||| <why>")
            return
        what, why = (s.strip() for s in raw.split("|||", 1))
        style_codex.log_flop(what, why)
        await update.message.reply_text("flop logged")

    async def refs_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        recent = reference_lib.recent(10)
        if not recent:
            await update.message.reply_text("(refs empty)")
            return
        lines = [
            f"{e['id']}  {e['filename']}  tags=[{', '.join(e.get('tags', []))}]  {(e.get('notes') or '')[:50]}"
            for e in recent
        ]
        await update.message.reply_text("\n".join(lines))

    async def status_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        st = topics_mod.stats()
        recent_briefs = archive.read_recent(1)
        last = "-"
        if recent_briefs:
            last = recent_briefs[0].get("created_at", "-")[:19]
        await update.message.reply_text(
            f"topics: total={st['total']} queued={st['queued']} used={st['used']}\n"
            f"last brief: {last}\n"
            f"time: {_now_iso()}"
        )

    async def reverse_cmd(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        uid = update.effective_user.id
        ctx_note = " ".join(context.args or []).strip()
        sess = _session(uid)
        sess.pending_photo_action = "reverse"
        sess.pending_context = ctx_note
        await update.message.reply_text(
            "ok — send the photo you want me to reverse-engineer."
            + (f" context: {ctx_note}" if ctx_note else "")
        )

    async def photo_handler(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not await guard(update):
            return
        uid = update.effective_user.id
        sess = _session(uid)

        photo = update.message.photo[-1] if update.message.photo else None
        if photo is None:
            await update.message.reply_text("no photo in that message")
            return

        file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".jpg", dir=str(settings.data_dir)
        ) as tmp:
            tmp_path = Path(tmp.name)
        await file.download_to_drive(str(tmp_path))

        try:
            if sess.pending_photo_action == "reverse":
                context_note = sess.pending_context or ""
                sess.pending_photo_action = ""
                sess.pending_context = ""
                system, user = reverse_engineer.build_reverse_brief(tmp_path, context=context_note)
                archive.save(kind="reverse", intent=f"photo:{tmp_path.name}", system=system, user=user)
                await _reply_long(update, f"## SYSTEM\n{system}\n\n## USER\n{user}")
            else:
                # Default: add to refs. Caption is used as notes if provided.
                note = (update.message.caption or "").strip()
                entry = reference_lib.add(
                    tmp_path, tags=["telegram"], source="telegram", notes=note
                )
                await update.message.reply_text(f"added ref {entry.id} → {entry.filename}")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    return {
        "help": help_cmd,
        "start": help_cmd,
        "piece": piece_cmd,
        "brief": brief_cmd,
        "shots": shots_cmd,
        "caption": caption_cmd,
        "variants": variants_cmd,
        "variants_last": variants_last_cmd,
        "batch": batch_cmd,
        "formats": formats_cmd,
        "fragments": fragments_cmd,
        "suggest": suggest_cmd,
        "lint": lint_cmd,
        "caption_lint": caption_lint_cmd,
        "grade": grade_cmd,
        "execute": execute_cmd_handler,
        "topic": topic_cmd,
        "topics": topics_cmd,
        "codex": codex_cmd,
        "distill": distill_cmd,
        "graduate": graduate_cmd,
        "winner": winner_cmd,
        "flop": flop_cmd,
        "refs": refs_cmd,
        "stats": stats_cmd_handler,
        "perf_summary": perf_summary_cmd,
        "perf_paste": perf_paste_cmd,
        "doctor": doctor_cmd,
        "journal": journal_cmd,
        "next": next_cmd,
        "session_start": session_start_cmd,
        "session_end": session_end_cmd,
        "x_prepare": x_prepare_cmd,
        "codex_audit": codex_audit_cmd,
        "fix_prompt": fix_prompt_cmd,
        "like_winner": like_winner_cmd,
        "last": last_cmd,
        "search": search_cmd,
        "format_health": format_health_cmd,
        "quick": quick_cmd,
        "cheatsheet": cheatsheet_cmd,
        "status": status_cmd,
        "reverse": reverse_cmd,
        "_photo": photo_handler,
    }


def build_application(cfg: BotConfig):
    _require_telegram()
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    if not cfg.token:
        raise BotConfigError("missing MEMEGINE_TELEGRAM_BOT_TOKEN")
    if not cfg.allowed_user_ids:
        raise BotConfigError(
            "MEMEGINE_TELEGRAM_ALLOWED_USER_IDS is empty — refusing to run an open bot"
        )

    app = Application.builder().token(cfg.token).build()
    handlers = _build_handlers(cfg)
    for name, fn in handlers.items():
        if name.startswith("_"):
            continue
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.PHOTO, handlers["_photo"]))
    return app


def run_bot(cfg: BotConfig | None = None) -> None:
    """Blocking entry point. Boots the bot and polls until stopped."""
    cfg = cfg or BotConfig.from_env()
    app = build_application(cfg)
    app.run_polling(allowed_updates=None)


# ---- scheduler → telegram delivery hook -----------------------------------


async def _send_scheduler_result_async(cfg: BotConfig, job: dict, result) -> None:
    """Called by the scheduler (via a sync adapter) to push a result to chat."""
    from telegram import Bot
    if not cfg.chat_id_for_scheduler or not cfg.token:
        return
    bot = Bot(cfg.token)
    msg = (
        f"[scheduler] job {job.get('name')} fired at {result.fired_at}\n"
        f"action={result.action}\n"
        f"bundles={result.bundles}\n"
        f"topics_used={result.topics_used}\n"
        f"note={result.note}"
    )
    for chunk in _chunks(msg):
        await bot.send_message(chat_id=cfg.chat_id_for_scheduler, text=chunk)


def send_scheduler_result(cfg: BotConfig, job: dict, result) -> None:
    """Sync wrapper around the async sender — safe to call from scheduler.run_loop."""
    try:
        _require_telegram()
    except ImportError:
        return
    try:
        asyncio.run(_send_scheduler_result_async(cfg, job, result))
    except RuntimeError:
        # Already inside an event loop — fall back to schedule_coroutine.
        loop = asyncio.get_event_loop()
        loop.create_task(_send_scheduler_result_async(cfg, job, result))
