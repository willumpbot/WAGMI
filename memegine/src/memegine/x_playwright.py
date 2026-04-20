"""Playwright-backed X timeline reader.

Two things it does and nothing else:
1. `login()` — opens a headed Chromium so the operator signs in once;
   storage state is persisted so subsequent runs stay authenticated.
2. `timeline_tweet_ids(handle)` — navigates to x.com/<handle> in headless
   mode, waits for tweets to render, returns the latest ~20 tweet IDs.

We DO NOT use Playwright to extract tweet content. That's done via
`x_fetch` (syndication endpoint, clean JSON, no DOM fragility). This
keeps the Playwright surface tiny, so when X changes its CSS we only
need to fix the ID extractor.

Session state lives in  ~/.memegine/x_session.json  — outside of any
project's data/ dir so switching brands doesn't affect auth.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional


# Per-user session state, independent of project.
SESSION_PATH = Path.home() / ".memegine" / "x_session.json"

# Playwright selectors / URLs.
BASE_URL = "https://x.com"
TIMELINE_SELECTOR = 'article[data-testid="tweet"]'
TWEET_LINK_RE = re.compile(r"/([^/]+)/status/(\d+)")

# Polite defaults — X rate-limits hard.
DEFAULT_TIMEOUT_MS = 15_000


class PlaywrightNotInstalled(RuntimeError):
    pass


def _require_playwright():
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise PlaywrightNotInstalled(
            "Playwright not installed. Run:\n"
            "  python -m pip install 'memegine[watch]'\n"
            "  python -m playwright install chromium"
        )


async def login_async() -> Path:
    """Open a headed Chromium, wait for manual login, save storage state.

    Blocks (from Playwright's perspective) on a 120s grace window; the
    operator signs in manually, then presses Enter in the terminal to
    persist state. Returns the path where state was written.
    """
    _require_playwright()
    from playwright.async_api import async_playwright
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
        print(
            "\n"
            "=========================================================\n"
            " Browser opened. Log into X in that window.\n"
            " When you're fully logged in and can see your timeline,\n"
            " come back here and press Enter to save the session.\n"
            "=========================================================\n"
        )
        # Read Enter from stdin without blocking the asyncio loop.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input)
        await context.storage_state(path=str(SESSION_PATH))
        await browser.close()
    return SESSION_PATH


def login() -> Path:
    """Sync wrapper for login_async."""
    return asyncio.run(login_async())


async def timeline_tweet_ids_async(
    handle: str,
    *,
    limit: int = 20,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[str]:
    """Return the N most-recent tweet IDs from @handle's main timeline.

    Only reads the timeline DOM to extract IDs — no engagement scraping,
    no content scraping. Each ID gets re-fetched via x_fetch after this.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    handle = handle.lstrip("@").strip().lower()
    if not handle:
        return []
    if not SESSION_PATH.exists():
        raise RuntimeError(
            f"no saved X session at {SESSION_PATH} — run `memegine watch login` first"
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(SESSION_PATH))
        page = await context.new_page()
        try:
            await page.goto(
                f"{BASE_URL}/{handle}",
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            # Wait for the first tweet article to render (or timeout).
            try:
                await page.wait_for_selector(
                    TIMELINE_SELECTOR, timeout=timeout_ms, state="attached",
                )
            except Exception:
                return []
            # Scroll once to flush out the initial batch.
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(800)
            # Collect all /status/<id> links on the page.
            links = await page.eval_on_selector_all(
                f"{TIMELINE_SELECTOR} a",
                "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
            )
            ids: list[str] = []
            seen: set[str] = set()
            for href in links:
                m = TWEET_LINK_RE.search(href or "")
                if m and m.group(1).lower() == handle:
                    tid = m.group(2)
                    if tid not in seen:
                        seen.add(tid)
                        ids.append(tid)
                if len(ids) >= limit:
                    break
            return ids
        finally:
            await browser.close()


def timeline_tweet_ids(
    handle: str,
    *,
    limit: int = 20,
    headless: bool = True,
) -> list[str]:
    """Sync wrapper for timeline_tweet_ids_async."""
    return asyncio.run(timeline_tweet_ids_async(handle, limit=limit, headless=headless))


def session_exists() -> bool:
    return SESSION_PATH.exists()


def clear_session() -> bool:
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()
        return True
    return False
