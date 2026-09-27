#!/usr/bin/env python
"""
test_data_integrity_fixes.py - proving tests for two Tier-0 data bugs fixed
2026-08-01 in the co-pilot's research-data collector + a co-pilot read guard.

CONFIRMED BUGS (real data):
  1. research/longtail/backfill.py fetched daily candles via HLNative with
     no forming-candle filter, so the LAST row of every
     data/longtail/ohlc/*_1d.csv was a partial/forming bar (~0.5x a full
     day's volume) whenever backfill ran mid-UTC-day (confirmed on
     AAVE/ADA/AVAX/APT, last row 2026-07-31). Fixed by
     `backfill._drop_forming_daily`.
  2. backfill.py computed `zero_vol_nonzero_range_count` per series but
     never included it in the `data_suspect` verdict (ZEC had 98/401 daily
     rows at v=0 with h!=l, reported data_suspect=false). Fixed by gating
     `data_suspect` on `zero_vol_pct > ZERO_VOL_FLAG_THRESHOLD` inside
     `backfill.validate_ohlc`.

This test also proves the matching read-time hardening in
tools/copilot/weather.py's `_closed_daily_df` (defense-in-depth: drops a
same-UTC-day row by DATE, not just by wall-clock-elapsed-since-open, OR'd
alongside the original check).

READ-ONLY / STANDALONE: fully synthetic data, no network calls, no
live-bot imports. Run: pytest tools/copilot/test_data_integrity_fixes.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from weather import _closed_daily_df  # noqa: E402

LONGTAIL_DIR = os.path.join(THIS_DIR, "..", "..", "research", "longtail")
LONGTAIL_DIR = os.path.abspath(LONGTAIL_DIR)
if LONGTAIL_DIR not in sys.path:
    sys.path.insert(0, LONGTAIL_DIR)

import backfill  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers - build synthetic HL-shaped daily candles ("t" open, "T" close)
# ---------------------------------------------------------------------------

MS_PER_DAY = 24 * 60 * 60 * 1000


def _hl_candle(open_dt: datetime, close_offset_ms: int = MS_PER_DAY - 1, v: float = 1000.0,
               o: float = 100.0, h: float = 101.0, l: float = 99.0, c: float = 100.5):
    t_ms = int(open_dt.timestamp() * 1000)
    return {"t": t_ms, "T": t_ms + close_offset_ms, "o": o, "h": h, "l": l, "c": c, "v": v}


def _hl_series(n: int, last_open_dt: datetime, **kw):
    """n daily candles, evenly spaced 1 day apart, ending at last_open_dt."""
    start = last_open_dt - timedelta(days=n - 1)
    return [_hl_candle(start + timedelta(days=i), **kw) for i in range(n)]


def _today_utc_midnight() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Bug 1a: backfill._drop_forming_daily
# ---------------------------------------------------------------------------

def test_backfill_drops_still_forming_last_daily_candle():
    """A last candle opened TODAY (UTC) - still forming, HL close time T is
    in the future relative to `now_ms` - must be dropped."""
    today = _today_utc_midnight()
    candles = _hl_series(10, today)
    now_ms = int((today + timedelta(hours=6)).timestamp() * 1000)  # mid-day today

    out = backfill._drop_forming_daily(candles, now_ms)

    assert len(out) == 9
    assert out[-1]["t"] == candles[-2]["t"]


def test_backfill_keeps_settled_last_daily_candle():
    """A last candle opened YESTERDAY (fully closed, T already elapsed)
    must be kept untouched."""
    yesterday = _today_utc_midnight() - timedelta(days=1)
    candles = _hl_series(10, yesterday)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    out = backfill._drop_forming_daily(candles, now_ms)

    assert len(out) == 10
    assert out[-1]["t"] == candles[-1]["t"]


def test_backfill_drop_forming_daily_handles_empty_and_missing_t():
    assert backfill._drop_forming_daily([], now_ms_val=123) == []
    weird = [{"o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]  # no "t" key
    assert backfill._drop_forming_daily(weird, now_ms_val=123) == weird


def test_backfill_drop_forming_daily_catches_missing_T_via_date_check():
    """If HL ever omits "T" (close time), the belt-and-suspenders date
    check alone must still catch a same-day forming candle."""
    today = _today_utc_midnight()
    candles = _hl_series(5, today)
    del candles[-1]["T"]
    now_ms = int((today + timedelta(hours=12)).timestamp() * 1000)

    out = backfill._drop_forming_daily(candles, now_ms)

    assert len(out) == 4


# ---------------------------------------------------------------------------
# Bug 1b: weather._closed_daily_df (read-time hardening)
# ---------------------------------------------------------------------------

def _df_from_hl_candles(candles):
    rows = [{"t": pd.Timestamp(c["t"], unit="ms", tz="UTC"), "c": c["c"]} for c in candles]
    return pd.DataFrame(rows)


def test_weather_closed_daily_df_drops_still_forming_row():
    today = _today_utc_midnight()
    df = _df_from_hl_candles(_hl_series(10, today))

    out = _closed_daily_df(df)

    assert len(out) == 9
    assert out["t"].iloc[-1] < pd.Timestamp(today)


def test_weather_closed_daily_df_keeps_settled_row():
    yesterday = _today_utc_midnight() - timedelta(days=1)
    df = _df_from_hl_candles(_hl_series(10, yesterday))

    out = _closed_daily_df(df)

    assert len(out) == 10
    assert out["t"].iloc[-1] == df["t"].iloc[-1]


def test_weather_closed_daily_df_none_and_empty_passthrough():
    assert _closed_daily_df(None) is None
    empty = pd.DataFrame({"t": [], "c": []})
    out = _closed_daily_df(empty)
    assert out.empty


def test_weather_hardening_date_check_drops_same_day_row():
    """Direct confirmation of the added OR branch: a row opened at TODAY's
    UTC midnight is dropped. For a well-formed, UTC-midnight-aligned
    candle this is mathematically equivalent to the original wall-clock
    check (both true whenever "now" is still within that same calendar
    day) - the date check's value is being the simpler, more auditable of
    the two, and catching a same-day row even if a future refactor ever
    feeds this function a non-midnight-aligned or malformed timestamp
    where the two checks could disagree."""
    today_midnight = _today_utc_midnight()
    settled_rows = _hl_series(9, today_midnight - timedelta(days=1))
    forming_row = _hl_candle(today_midnight)  # opened at today's midnight
    df = _df_from_hl_candles(settled_rows + [forming_row])

    out = _closed_daily_df(df)

    assert len(out) == 9
    assert out["t"].iloc[-1] == df["t"].iloc[-2]


# ---------------------------------------------------------------------------
# Bug 2: backfill.validate_ohlc zero-vol gate now flips data_suspect
# ---------------------------------------------------------------------------

def _make_candles_with_zero_vol_rows(n: int, zero_vol_frac: float, start_dt: datetime):
    """n daily candles, ~zero_vol_frac of them zero-volume with a nonzero
    (h - l) range (the ZEC-shaped hole)."""
    out = []
    n_zero = int(round(n * zero_vol_frac))
    for i in range(n):
        dt = start_dt + timedelta(days=i)
        if i < n_zero:
            out.append(_hl_candle(dt, v=0.0, o=100.0, h=101.0, l=99.0, c=100.0))
        else:
            out.append(_hl_candle(dt, v=1000.0, o=100.0, h=101.0, l=99.0, c=100.0))
    return out


def test_zero_vol_gate_flips_data_suspect_true_past_threshold():
    """~24% zero-vol-nonzero-range rows (well past the 5% threshold) must
    flip data_suspect true, mirroring the real ZEC hole (98/401 = ~24%)."""
    start = _today_utc_midnight() - timedelta(days=400)
    candles = _make_candles_with_zero_vol_rows(400, zero_vol_frac=0.245, start_dt=start)

    result = backfill.validate_ohlc(
        "ZECLIKE", "1d", candles,
        expected_start_ms=int(start.timestamp() * 1000),
        expected_end_ms=int(candles[-1]["t"]) + MS_PER_DAY,
    )

    assert result["zero_vol_nonzero_range_count"] == 98
    assert result["data_suspect"] is True


def test_zero_vol_gate_stays_false_under_threshold():
    """A small, sub-5% smattering of zero-vol rows must NOT alone flip
    data_suspect (keeps the check from being trigger-happy on noise)."""
    start = _today_utc_midnight() - timedelta(days=100)
    candles = _make_candles_with_zero_vol_rows(100, zero_vol_frac=0.02, start_dt=start)

    result = backfill.validate_ohlc(
        "CLEANCOIN", "1d", candles,
        expected_start_ms=int(start.timestamp() * 1000),
        expected_end_ms=int(candles[-1]["t"]) + MS_PER_DAY,
    )

    assert result["zero_vol_nonzero_range_count"] == 2
    assert result["data_suspect"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
