"""Ops Console — FastAPI server.

Serves the single-page dashboard at /, plus the JSON API the dashboard
uses. Everything is local; no remote auth; safe on localhost.

Run with: `memegine console` (launches uvicorn + opens browser).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:  # pragma: no cover — optional extras
    FastAPI = None

from . import (
    brand as brand_mod,
    format_suggest,
    ops_db,
    pipeline as pipeline_mod,
    projects as projects_mod,
    prompt_engine,
    reference_lib,
    reply_for as reply_for_mod,
    x_fetch,
)
from .config import settings


STATIC_DIR = Path(__file__).parent / "static"


# ---------------- request models ----------------

if FastAPI is not None:

    class AddWatchBody(BaseModel):
        handle: str
        note: str = ""

    class FetchTweetBody(BaseModel):
        url_or_id: str

    class ReplyForBody(BaseModel):
        url_or_id: str
        generate_brief: bool = True

    class BriefBody(BaseModel):
        intent: str
        format_slug: Optional[str] = None
        kind: str = "image"           # "image" | "video"

    class ActionBody(BaseModel):
        tweet_id: str
        kind: str                     # grab_ref / brief / video / skip / copy
        slug_or_ref_id: str = ""
        note: str = ""

    class SwitchBrandBody(BaseModel):
        name: str


def build_app():
    """Construct the FastAPI app. Raises clearly if fastapi isn't installed."""
    if FastAPI is None:
        raise RuntimeError(
            "FastAPI not installed. Run: `pip install 'memegine[console]'`"
        )

    app = FastAPI(title="memegine ops console", version="0.1.0")

    # -------- static root --------
    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        idx = STATIC_DIR / "index.html"
        if not idx.exists():
            return HTMLResponse("<h1>memegine</h1><p>static/index.html missing</p>")
        return HTMLResponse(idx.read_text(encoding="utf-8"))

    # -------- brand --------
    @app.get("/api/brand")
    def api_brand_get() -> dict:
        plate = brand_mod.current_plate()
        return {
            "active": settings.project,
            "name": plate.name,
            "tagline": plate.tagline,
            "projects": [p[0] for p in projects_mod.list_projects()] or ["default"],
        }

    @app.post("/api/brand")
    def api_brand_switch(body: SwitchBrandBody) -> dict:
        try:
            projects_mod.set_active(body.name)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        settings.refresh_project(body.name)
        return api_brand_get()

    # -------- watchlist --------
    @app.get("/api/watchlist")
    def api_watchlist_list() -> list[dict]:
        return [
            {"handle": w.handle, "added_at": w.added_at,
             "note": w.note, "is_active": w.is_active}
            for w in ops_db.watchlist_list()
        ]

    @app.post("/api/watchlist")
    def api_watchlist_add(body: AddWatchBody) -> dict:
        try:
            entry = ops_db.watchlist_add(body.handle, body.note)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "handle": entry.handle, "added_at": entry.added_at,
            "note": entry.note, "is_active": entry.is_active,
        }

    @app.delete("/api/watchlist/{handle}")
    def api_watchlist_remove(handle: str) -> dict:
        ok = ops_db.watchlist_remove(handle)
        return {"removed": ok, "handle": handle}

    # -------- tweets --------
    @app.get("/api/tweets")
    def api_tweets_feed(limit: int = 50, handle: Optional[str] = None) -> list[dict]:
        return ops_db.tweets_recent(limit=limit, handle=handle)

    @app.post("/api/tweets/fetch")
    def api_tweet_fetch(body: FetchTweetBody) -> dict:
        td = x_fetch.fetch(body.url_or_id, use_cache=False)
        if td is None:
            raise HTTPException(status_code=404, detail="tweet not found or unavailable")
        ops_db.tweet_upsert(
            id=td.id, handle=td.author_handle, text=td.text,
            created_at=td.created_at,
            favorite_count=td.favorite_count, reply_count=td.reply_count,
            payload=td.as_dict(),
        )
        # Auto-add author to watchlist so future fetches on this handle
        # nest nicely.
        if td.author_handle:
            ops_db.watchlist_add(td.author_handle)
        return td.as_dict()

    # -------- reply-for --------
    @app.post("/api/reply-for")
    def api_reply_for(body: ReplyForBody) -> dict:
        plan = reply_for_mod.plan(
            body.url_or_id,
            generate_brief=body.generate_brief,
            open_browser=False,
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="tweet fetch failed")
        return {
            "tweet": plan.tweet.as_dict(),
            "brand": plan.brand,
            "keywords": plan.keywords,
            "ref_matches": [
                {
                    "score": m.score, "id": m.slug_or_id,
                    "description": m.description,
                    "media_path": str(m.media_path) if m.media_path else None,
                    "hits": m.trigger_hits,
                }
                for m in plan.ref_matches[:5]
            ],
            "format_matches": [
                {
                    "score": m.score, "slug": m.slug_or_id,
                    "description": m.description, "hits": m.trigger_hits,
                }
                for m in plan.format_matches[:5]
            ],
            "chosen_format": plan.chosen_format,
            "brief": plan.brief_prompt,
            "notes": plan.notes,
        }

    # -------- refs --------
    @app.get("/api/refs")
    def api_refs_list(q: str = "", limit: int = 30) -> list[dict]:
        entries = reference_lib.search(text=q) if q else reference_lib.recent(limit)
        return [
            {
                "id": e.get("id"),
                "prompt": e.get("prompt", "")[:200],
                "notes": e.get("notes", ""),
                "tags": e.get("tags", []),
                "path": e.get("path"),
                "added_at": e.get("added_at"),
            }
            for e in entries[:limit]
        ]

    @app.get("/api/refs/{ref_id}/media")
    def api_ref_media(ref_id: str) -> Any:
        for e in reference_lib.search():
            if e.get("id") == ref_id:
                p = e.get("path")
                if p and Path(p).exists():
                    return FileResponse(p)
                raise HTTPException(status_code=404, detail="media file missing")
        raise HTTPException(status_code=404, detail="ref not found")

    # -------- brief generation --------
    @app.post("/api/brief")
    def api_brief(body: BriefBody) -> dict:
        slug = body.format_slug or format_suggest.best(body.intent, kind=body.kind)
        try:
            bundle = pipeline_mod.build(body.intent, kind=body.kind, format_slug=slug)
            system, user = prompt_engine.assemble_offline_prompt(body.intent, slug)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "bundle_id": bundle.id,
            "folder": str(bundle.folder),
            "format_slug": bundle.format_slug or slug,
            "kind": bundle.kind,
            "system": system,
            "user": user,
            "full_prompt": f"{system}\n\n---\n\n{user}",
        }

    # -------- actions --------
    @app.post("/api/actions")
    def api_action_log(body: ActionBody) -> dict:
        ops_db.action_log(
            tweet_id=body.tweet_id, kind=body.kind,
            slug_or_ref_id=body.slug_or_ref_id, note=body.note,
        )
        return {"ok": True}

    # -------- static files --------
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


def run(host: str = "127.0.0.1", port: int = 8080, *, open_browser: bool = True) -> None:
    """Start uvicorn + optionally open the browser."""
    try:
        import uvicorn
    except ImportError:
        raise RuntimeError(
            "uvicorn not installed. Run: `pip install 'memegine[console]'`"
        )
    app = build_app()
    if open_browser:
        import threading, time, webbrowser
        def _open():
            time.sleep(0.8)
            try:
                webbrowser.open(f"http://{host}:{port}/")
            except webbrowser.Error:
                pass
        threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")
