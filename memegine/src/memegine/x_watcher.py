"""Watchlist poller — auto-populates the TG feed.

Loop:
    for handle in watchlist:
        ids = x_playwright.timeline_tweet_ids(handle)
        new_ids = [i for i in ids if i not in ops_db]
        for tid in new_ids:
            td = x_fetch.fetch(tid)          # syndication, clean JSON
            ops_db.tweet_upsert(td)
            telegram_ops.push_new_tweets(cfg, [td])

Speed: polls each handle with jittered stagger so every handle hits
within the configured interval without all thundering at once.

Resilience: any failure on a single handle is caught, logged, and the
loop moves on. Continuous 429s / login-loss triggers exponential
backoff up to 30 min before retrying.

Called from `memegine watch start`.
"""
from __future__ import annotations

import datetime as dt
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from . import ops_db, x_fetch, x_playwright
from .config import settings


@dataclass
class WatcherConfig:
    interval_seconds: int = 180           # base poll cycle (3 min)
    jitter_pct: float = 0.15              # ±15% per-handle
    stagger: bool = True                  # spread handle hits across the cycle
    max_backoff_seconds: int = 1800       # 30 min cap
    limit_per_handle: int = 15            # how many timeline IDs to check
    push_to_telegram: bool = True         # call telegram_ops.push on new tweets
    tg_cfg: Optional[object] = None       # BotConfig — required if push_to_telegram


@dataclass
class HandleState:
    """Per-handle runtime state tracked across the poll loop."""
    handle: str
    last_check_at: Optional[float] = None
    last_error: str = ""
    consecutive_errors: int = 0
    backoff_until: float = 0.0           # wall-clock time to resume
    seen_ids: set[str] = field(default_factory=set)


@dataclass
class CycleResult:
    """One cycle over the full watchlist."""
    started_at: str
    handles_checked: int = 0
    new_tweets: int = 0
    errors: int = 0
    tweets_by_handle: dict[str, int] = field(default_factory=dict)

    def as_text(self) -> str:
        lines = [
            f"cycle at {self.started_at}",
            f"  handles checked: {self.handles_checked}",
            f"  new tweets:      {self.new_tweets}",
            f"  errors:          {self.errors}",
        ]
        for h, n in self.tweets_by_handle.items():
            if n:
                lines.append(f"    @{h}: +{n}")
        return "\n".join(lines)


def _now() -> float:
    return time.time()


def _compute_sleep(cfg: WatcherConfig, handles: int) -> float:
    """Per-handle sleep when stagger is on."""
    if not cfg.stagger or handles <= 1:
        return 0.0
    base = cfg.interval_seconds / max(handles, 1)
    return max(0.0, base * random.uniform(1 - cfg.jitter_pct, 1 + cfg.jitter_pct))


def _seed_state_from_db() -> dict[str, HandleState]:
    """Pre-populate seen_ids from ops_db so first cycle doesn't
    re-broadcast every existing tweet."""
    states: dict[str, HandleState] = {}
    entries = ops_db.watchlist_list()
    for w in entries:
        state = HandleState(handle=w.handle)
        for t in ops_db.tweets_recent(limit=50, handle=w.handle):
            state.seen_ids.add(t["id"])
        states[w.handle] = state
    return states


def _check_one(
    state: HandleState, cfg: WatcherConfig,
) -> tuple[list[x_fetch.TweetData], bool]:
    """Poll one handle. Returns (new_tweets, had_error)."""
    try:
        ids = x_playwright.timeline_tweet_ids(
            state.handle, limit=cfg.limit_per_handle,
        )
    except x_playwright.PlaywrightNotInstalled:
        raise
    except Exception as exc:
        state.consecutive_errors += 1
        state.last_error = f"{type(exc).__name__}: {exc}"
        backoff = min(
            cfg.max_backoff_seconds,
            cfg.interval_seconds * (2 ** min(state.consecutive_errors, 6)),
        )
        state.backoff_until = _now() + backoff
        return ([], True)

    # Success — reset error state.
    state.consecutive_errors = 0
    state.last_error = ""
    state.backoff_until = 0.0
    state.last_check_at = _now()

    new_tweets: list[x_fetch.TweetData] = []
    for tid in ids:
        if tid in state.seen_ids:
            continue
        state.seen_ids.add(tid)
        td = x_fetch.fetch(tid, use_cache=True)
        if td is None:
            continue
        # Persist to ops_db (also cached by x_fetch to JSONL).
        ops_db.tweet_upsert(
            id=td.id, handle=td.author_handle or state.handle,
            text=td.text, created_at=td.created_at,
            favorite_count=td.favorite_count, reply_count=td.reply_count,
            payload=td.as_dict(),
        )
        new_tweets.append(td)
    return (new_tweets, False)


def run_once(cfg: Optional[WatcherConfig] = None) -> CycleResult:
    """Single pass over the watchlist."""
    cfg = cfg or WatcherConfig()
    result = CycleResult(started_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat())
    states = _seed_state_from_db()
    handles = list(states.keys())
    if not handles:
        return result

    all_new: list[dict] = []
    for h in handles:
        state = states[h]
        if state.backoff_until > _now():
            continue
        new_tweets, had_error = _check_one(state, cfg)
        result.handles_checked += 1
        if had_error:
            result.errors += 1
        count = len(new_tweets)
        if count:
            result.tweets_by_handle[h] = count
            result.new_tweets += count
            # Collect for TG push.
            for td in new_tweets:
                all_new.append(_tweet_for_push(td))
        sleep_s = _compute_sleep(cfg, len(handles))
        if sleep_s > 0:
            time.sleep(sleep_s)

    if all_new and cfg.push_to_telegram and cfg.tg_cfg is not None:
        try:
            from . import telegram_ops
            telegram_ops.push_new_tweets(cfg.tg_cfg, all_new)
        except Exception as exc:
            # TG push failures should never break the loop.
            result.errors += 1
            print(f"warn: telegram push failed: {exc}")

    return result


def _tweet_for_push(td: x_fetch.TweetData) -> dict:
    """Shape matching what ops_db.tweets_recent returns, so
    telegram_ops._send_tweet_card reads it consistently."""
    d = td.as_dict()
    d["handle"] = td.author_handle
    return d


def run_loop(
    cfg: Optional[WatcherConfig] = None,
    *,
    iterations: Optional[int] = None,
    verbose: bool = True,
) -> None:
    """Blocking poll loop. Ctrl-C to stop. Set iterations=N for finite runs (tests)."""
    cfg = cfg or WatcherConfig()
    n = 0
    while True:
        n += 1
        started = _now()
        result = run_once(cfg)
        if verbose:
            print(result.as_text())
        if iterations is not None and n >= iterations:
            break
        elapsed = _now() - started
        sleep_remaining = max(5.0, cfg.interval_seconds - elapsed)
        if verbose:
            print(f"  next cycle in {int(sleep_remaining)}s")
        time.sleep(sleep_remaining)
