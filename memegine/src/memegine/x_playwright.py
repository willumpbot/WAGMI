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


async def login_async(
    *,
    wait_timeout_sec: int = 600,
    poll_sec: float = 2.0,
) -> Path:
    """Open a headed Chromium, auto-detect successful login, save state.

    No terminal interaction required: polls the open browser for a
    logged-in signal (home timeline visible OR URL redirected to /home
    OR account-menu element present). Saves storage_state when any
    signal fires. Times out after wait_timeout_sec.

    Works whether called in foreground or background — the signal
    source is purely the browser, not stdin.
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
            "========================================================\n"
            " Browser opened. Log into X in that window.\n"
            " Memegine polls for login completion automatically —\n"
            " no terminal input needed. The window will close itself\n"
            f" and the session saved to {SESSION_PATH}\n"
            "========================================================\n",
            flush=True,
        )

        deadline = asyncio.get_event_loop().time() + wait_timeout_sec
        logged_in = False
        while asyncio.get_event_loop().time() < deadline:
            # Several independent signals; any one means we're in.
            try:
                url = page.url or ""
                if "/home" in url and "/i/flow" not in url:
                    logged_in = True
                # Account-menu button appears once logged in.
                has_side_nav = await page.locator(
                    'a[data-testid="AppTabBar_Home_Link"], [data-testid="SideNav_AccountSwitcher_Button"]'
                ).count()
                if has_side_nav > 0:
                    logged_in = True
            except Exception:
                pass
            if logged_in:
                # Give the browser a beat to finish setting cookies.
                await asyncio.sleep(1.5)
                break
            await asyncio.sleep(poll_sec)

        if not logged_in:
            await browser.close()
            raise RuntimeError(
                f"login not detected within {wait_timeout_sec}s — "
                "try again: `memegine watch login`"
            )
        await context.storage_state(path=str(SESSION_PATH))
        await browser.close()
        print(f"✅ session saved to {SESSION_PATH}", flush=True)
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


async def search_handles_async(
    query: str,
    *,
    limit: int = 50,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[str]:
    """X search query → unique list of handles that authored results.

    Uses /search?q={query}&f=live (latest tab). Scrolls a few times to
    pull past the first ~20 results. Returns lowercase handles.
    """
    _require_playwright()
    from playwright.async_api import async_playwright
    import urllib.parse as _up
    if not SESSION_PATH.exists():
        raise RuntimeError(
            f"no saved X session at {SESSION_PATH} — run `memegine watch login`"
        )
    url = f"{BASE_URL}/search?q={_up.quote(query)}&src=typed_query&f=live"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(storage_state=str(SESSION_PATH))
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                await page.wait_for_selector(
                    TIMELINE_SELECTOR, timeout=timeout_ms, state="attached",
                )
            except Exception:
                return []
            seen: list[str] = []
            seen_set: set[str] = set()
            for _ in range(max(1, limit // 10)):
                links = await page.eval_on_selector_all(
                    f"{TIMELINE_SELECTOR} a",
                    "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
                )
                for href in links:
                    m = TWEET_LINK_RE.search(href or "")
                    if m:
                        h = m.group(1).lower()
                        if h and h not in seen_set and not h.startswith("i/"):
                            seen_set.add(h)
                            seen.append(h)
                if len(seen) >= limit:
                    break
                await page.mouse.wheel(0, 2400)
                await page.wait_for_timeout(900)
            return seen[:limit]
        finally:
            await browser.close()


def search_handles(query: str, *, limit: int = 50) -> list[str]:
    """Sync wrapper for search_handles_async."""
    return asyncio.run(search_handles_async(query, limit=limit))


async def profile_picture_url_async(
    handle: str,
    *,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Optional[str]:
    """Return the full-size profile picture URL for @handle, or None."""
    _require_playwright()
    from playwright.async_api import async_playwright
    if not SESSION_PATH.exists():
        raise RuntimeError(
            f"no saved X session at {SESSION_PATH} — run `memegine watch login`"
        )
    handle = handle.lstrip("@").strip().lower()
    if not handle:
        return None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(storage_state=str(SESSION_PATH))
        page = await ctx.new_page()
        try:
            await page.goto(
                f"{BASE_URL}/{handle}",
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            try:
                await page.wait_for_selector(
                    'img[src*="profile_images"]',
                    timeout=timeout_ms, state="attached",
                )
            except Exception:
                return None
            src = await page.eval_on_selector(
                'img[src*="profile_images"]',
                "e => e.getAttribute('src')",
            )
            if not src:
                return None
            # X serves profile_images at _normal (48px), _bigger (73px), _200x200,
            # _400x400, or no suffix (original). Upscale to _400x400.
            import re as _re
            return _re.sub(r"_(normal|bigger|\d+x\d+)\.", "_400x400.", src)
        finally:
            await browser.close()


def profile_picture_url(handle: str) -> Optional[str]:
    """Sync wrapper for profile_picture_url_async."""
    return asyncio.run(profile_picture_url_async(handle))


async def handle_info_async(
    handle: str,
    *,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict:
    """Get {followers, following, bio, joined} for a handle.

    Returns empty dict on any failure. Follower count parsing handles
    K/M suffixes.
    """
    _require_playwright()
    from playwright.async_api import async_playwright
    if not SESSION_PATH.exists():
        raise RuntimeError(
            f"no saved X session at {SESSION_PATH} — run `memegine watch login`"
        )
    handle = handle.lstrip("@").strip().lower()
    if not handle:
        return {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(storage_state=str(SESSION_PATH))
        page = await ctx.new_page()
        try:
            await page.goto(
                f"{BASE_URL}/{handle}",
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            try:
                await page.wait_for_selector(
                    '[data-testid="UserName"]',
                    timeout=timeout_ms, state="attached",
                )
            except Exception:
                return {}
            # Followers/following labels sit in a specific structure.
            data = await page.evaluate("""
                () => {
                    const out = {followers: 0, following: 0, bio: '', verified: false};
                    const userDesc = document.querySelector('[data-testid="UserDescription"]');
                    if (userDesc) out.bio = userDesc.textContent || '';
                    // Followers / following stats
                    const anchors = Array.from(document.querySelectorAll('a[href*="/verified_followers"], a[href*="/followers"], a[href*="/following"]'));
                    for (const a of anchors) {
                        const href = a.getAttribute('href') || '';
                        const spans = Array.from(a.querySelectorAll('span'))
                            .map(s => (s.textContent || '').trim())
                            .filter(Boolean);
                        const first = spans[0] || '';
                        if (href.includes('/following') && !out.following) out.following = first;
                        if ((href.includes('/followers') || href.includes('/verified_followers')) && !out.followers) out.followers = first;
                    }
                    // Verified badge
                    out.verified = !!document.querySelector('[data-testid="UserName"] svg[aria-label="Verified account"]');
                    return out;
                }
            """)
            return {
                "handle": handle,
                "followers": _parse_count(data.get("followers", "")),
                "following": _parse_count(data.get("following", "")),
                "bio": data.get("bio", ""),
                "verified": bool(data.get("verified", False)),
            }
        finally:
            await browser.close()


def handle_info(handle: str) -> dict:
    """Sync wrapper for handle_info_async."""
    return asyncio.run(handle_info_async(handle))


def _parse_count(s: str) -> int:
    """Turn '12.3K' / '4.5M' / '890' into an int."""
    if not s:
        return 0
    s = str(s).strip().upper().replace(",", "")
    if not s:
        return 0
    try:
        if s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("B"):
            return int(float(s[:-1]) * 1_000_000_000)
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def session_exists() -> bool:
    return SESSION_PATH.exists()


def clear_session() -> bool:
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()
        return True
    return False
