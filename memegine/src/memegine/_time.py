"""Small datetime helpers.

Python 3.14 deprecates dt.datetime.utcnow(). We wrap the replacement
in one place so every module uses a consistent, future-proof ISO UTC
timestamp string.
"""
from __future__ import annotations

import datetime as dt


def now_utc() -> dt.datetime:
    """Return an offset-aware UTC datetime."""
    return dt.datetime.now(dt.timezone.utc)


def now_naive_utc() -> dt.datetime:
    """Return a naive UTC datetime (for compatibility with older callers
    that compare against naive datetimes)."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def now_iso() -> str:
    """Return the current UTC time as an ISO string ending in 'Z'."""
    return now_naive_utc().isoformat() + "Z"
