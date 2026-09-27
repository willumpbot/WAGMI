"""
HLNative — standalone Hyperliquid public-API client for research scripts.
=============================================================================

STANDALONE, READ-ONLY. Only depends on `requests` + stdlib. Does NOT import
from `data/fetcher.py`, `data/db.py`, or any other live-bot module, and does
NOT write to any live-bot state file. Safe to use from research scripts at
any time, from any machine, with zero risk to the running paper/live bot.

Wraps two POST https://api.hyperliquid.xyz/info endpoints needed by the
Long-Tail Alpha data pipeline:
    - candleSnapshot   (OHLCV candles, paginated for long ranges)
    - fundingHistory   (per-coin funding rate history, paginated)

Pagination
----------
Both endpoints cap how many records they return per request, and the cap
differs by endpoint (`candleSnapshot` tolerates large windows in practice;
`fundingHistory` was confirmed live to cap at 500 records/request — well
under what a naive "assume 5000, like candles" guess would predict). Rather
than guessing a per-endpoint cap, both `candles()` and `funding_history()`
unconditionally re-page: after every response they advance `start_ms` to
just past the last record returned (`last_candle["T"] + 1` for candles,
`last_record["time"] + 1` for funding) and issue another request, and only
stop when a page comes back empty, no forward progress is made (stuck), or
the window bound (`end_ms`) is reached. This trades one extra "confirm we're
done" request per series for correctness — never silently truncating a long
range because a page happened to come back shorter than an assumed cap.
Records are deduped by their timestamp key and returned sorted ascending.

Rate limiting / retries
------------------------
~5 req/s to the public HL API, 15s request timeout, exponential backoff
retry (up to 4 tries) on HTTP 429/5xx or network error. Fail-soft: if a coin
exhausts its retries, the error is logged to stderr and whatever data was
already accumulated for that call is returned (possibly an empty list) —
one bad symbol/page never raises out of a bulk backfill loop.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional

import requests

HL_INFO_URL = "https://api.hyperliquid.xyz/info"

REQ_TIMEOUT_S = 15
RATE_LIMIT_RPS = 5.0
MIN_REQ_INTERVAL_S = 1.0 / RATE_LIMIT_RPS
MAX_RETRIES = 4
RETRY_BACKOFF_BASE_S = 1.5

class RateLimiter:
    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last_call = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_call = time.monotonic()


class HLNative:
    """Minimal standalone Hyperliquid public info-API client.

    Only uses `requests` + stdlib. No dependency on the live bot package.
    """

    def __init__(
        self,
        base_url: str = HL_INFO_URL,
        timeout_s: float = REQ_TIMEOUT_S,
        rate_limit_rps: float = RATE_LIMIT_RPS,
        max_retries: int = MAX_RETRIES,
    ):
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._limiter = RateLimiter(1.0 / rate_limit_rps)
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Low-level POST with rate limiting + retry/backoff
    # ------------------------------------------------------------------
    def _post(self, payload: Dict[str, Any]) -> Optional[Any]:
        """POST to the HL info API. Returns parsed JSON, or None on
        persistent failure (logged to stderr, never raises)."""
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            self._limiter.wait()
            try:
                resp = self._session.post(
                    self.base_url, json=payload, timeout=self.timeout_s
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = RuntimeError(
                        f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    time.sleep(RETRY_BACKOFF_BASE_S * (2 ** attempt))
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                time.sleep(RETRY_BACKOFF_BASE_S * (2 ** attempt))
        print(
            f"[HLNative] persistent failure for payload type="
            f"{payload.get('type')} coin={payload.get('coin') or (payload.get('req') or {}).get('coin')}: "
            f"{last_exc}",
            file=sys.stderr,
        )
        return None

    # ------------------------------------------------------------------
    # meta (exchange asset universe - NOT paginated, single request)
    # ------------------------------------------------------------------
    def meta(self) -> Optional[Dict[str, Any]]:
        """Fetch Hyperliquid's perp asset universe metadata via
        POST {"type": "meta"}: for each coin, its real `maxLeverage`,
        `marginTableId`, `szDecimals`, etc, plus the shared `marginTables`
        (tiered maintenance-margin brackets by notional, keyed by
        marginTableId). Read-only, no side effects, no pagination needed
        (single response). Returns the parsed JSON dict, or None on
        persistent failure (logged to stderr, never raises) - callers must
        degrade gracefully (e.g. fall back to a flat maintenance-margin
        assumption) if this returns None.
        """
        return self._post({"type": "meta"})

    # ------------------------------------------------------------------
    # candleSnapshot (paginated)
    # ------------------------------------------------------------------
    def candles(
        self, coin: str, interval: str, start_ms: int, end_ms: int
    ) -> List[Dict[str, Any]]:
        """Fetch OHLCV candles for `coin` at `interval` over [start_ms, end_ms].

        Paginates automatically past HL's ~5000-candle-per-request cap by
        advancing start_ms to the last returned candle's close time (T) + 1
        and re-requesting, until the window is exhausted. Deduped by open
        time (t), sorted ascending. Fail-soft: on persistent error for a
        page, logs and returns whatever was accumulated so far.
        """
        out: Dict[int, Dict[str, Any]] = {}
        cur_start = start_ms
        seen_empty_or_stuck = False
        while cur_start < end_ms and not seen_empty_or_stuck:
            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": cur_start,
                    "endTime": end_ms,
                },
            }
            page = self._post(payload)
            if page is None:
                # persistent failure on this page — fail soft, stop here
                break
            if not isinstance(page, list) or len(page) == 0:
                break
            for c in page:
                t = c.get("t")
                if t is not None:
                    out[t] = c
            last_t_close = page[-1].get("T")
            if last_t_close is None:
                break
            next_start = last_t_close + 1
            if next_start <= cur_start:
                # no progress — avoid infinite loop
                seen_empty_or_stuck = True
                break
            cur_start = next_start
            # NOTE: do NOT infer "done" from len(page) < PAGE_CAP — HL's
            # actual per-request page cap for this endpoint is not
            # reliably known/stable (observed smaller than the assumed
            # 5000 cap on other endpoints), so a short page is not proof
            # there's no more data. Only stop on an empty page, no
            # progress, or reaching end_ms (loop condition above).
        return sorted(out.values(), key=lambda c: c["t"])

    # ------------------------------------------------------------------
    # fundingHistory (paginated)
    # ------------------------------------------------------------------
    def funding_history(
        self, coin: str, start_ms: int, end_ms: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch funding-rate history for `coin` from start_ms to now (or
        end_ms if given). Paginates past the page cap by advancing start_ms
        to the last returned record's time + 1. Deduped by time, sorted
        ascending. Fail-soft on persistent error.
        """
        out: Dict[int, Dict[str, Any]] = {}
        cur_start = start_ms
        while True:
            payload: Dict[str, Any] = {
                "type": "fundingHistory",
                "coin": coin,
                "startTime": cur_start,
            }
            if end_ms is not None:
                payload["endTime"] = end_ms
            page = self._post(payload)
            if page is None:
                break
            if not isinstance(page, list) or len(page) == 0:
                break
            for r in page:
                t = r.get("time")
                if t is not None:
                    out[t] = r
            last_t = page[-1].get("time")
            if last_t is None:
                break
            next_start = last_t + 1
            if next_start <= cur_start:
                break
            cur_start = next_start
            if end_ms is not None and cur_start >= end_ms:
                break
            # NOTE: do NOT infer "done" from len(page) < PAGE_CAP. Confirmed
            # live that HL's fundingHistory page cap is 500 records, well
            # under the 5000 candleSnapshot cap this constant was modeled
            # on — treating a 500-record page as "the whole range" silently
            # truncated 200d of funding history down to ~21d. Only stop on
            # an empty page, no progress, or reaching end_ms.
        return sorted(out.values(), key=lambda r: r["time"])
