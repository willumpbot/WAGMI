#!/usr/bin/env python
"""
test_forward_evidence_horizon.py - proving test for the FORWARD-EVIDENCE
ANCHOR FIX (2026-08-01, see copilot.py's module docstring "FORWARD-EVIDENCE
ANCHOR FIX", call_logger.py's EV_SCHEMA_VERSION, and PREREGISTRATION.md).

Confirmed bug: `build_dip_read()` used to set `r.price` (logged to the call
ledger as the forward-evidence entry) to the LAST daily candle's close, which
can be a STILL-FORMING current-UTC-day bar, and `resolve_calls.py` anchored
the N-day horizon on the row's wall-clock `ts_utc` rather than a settled
candle date - both together systematically INFLATED every horizon.

This test proves, with fully synthetic/deterministic data (no network calls,
no live-bot imports - matches every tools/copilot/*.py module's read-only/
standalone contract):
  1. `build_dip_read()` drops a still-forming current-UTC-day candle and
     anchors `settled_close`/`settled_close_date` on the prior, fully-closed
     candle - while leaving the display `r.price` untouched.
  2. `resolve_calls.py` resolves fwd_1d/3d/5d to the EXACT close-to-close
     N-day return from the settled anchor - no drift from time-of-day.
  3. Pre-fix rows (missing ev_schema/settled_close) are excluded from
     resolution entirely, not silently resolved on the old horizon.
  4. Same-(symbol, day) rows collapse to one before H1/H2 bucketing,
     preferring source="read" over source="alert".

Run: pytest tools/copilot/test_forward_evidence_horizon.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from copilot import build_dip_read, DAYS_1D, MIN_ROWS_1D  # noqa: E402
import resolve_calls  # noqa: E402
from resolve_calls import (  # noqa: E402
    ROUND_TRIP_FEE_PCT,
    _collapse_same_symbol_day,
    _has_valid_ev_schema,
    resolve_ledger,
)


# ---------------------------------------------------------------------------
# Part 1: build_dip_read() drops the still-forming candle
# ---------------------------------------------------------------------------

class _FakeHLClient:
    """Minimal stand-in for HLNative - only implements what fetch_ohlc()/
    fetch_funding() call. `candles()` ignores start/end and always returns
    the full synthetic series (fetch_ohlc does its own filtering-by-df, not
    by re-querying with different bounds), matching real client semantics
    closely enough for this deterministic test."""

    def __init__(self, daily_candles):
        self._daily = daily_candles

    def candles(self, symbol, interval, start_ms, end_ms):
        if interval == "1d":
            return self._daily
        return []  # no 1h candles - build_dip_read() degrades gracefully

    def funding_history(self, symbol, start_ms):
        return []  # no funding data - fetch_funding() fails soft to None


def _mk_candle(dt: datetime, close: float) -> dict:
    """One synthetic daily candle opened at `dt` (UTC midnight), closing 24h
    later, with a flat O=H=L=C=`close` body (fine for this test - it only
    exercises which candle gets treated as 'settled', not OHLC math)."""
    t_ms = int(dt.timestamp() * 1000)
    T_ms = int((dt + timedelta(days=1)).timestamp() * 1000)
    return {"t": t_ms, "T": T_ms, "o": close, "h": close, "l": close, "c": close, "v": 100.0}


def _synthetic_daily_series(n_rows: int, today_utc_midnight: datetime, base: float = 100.0, step: float = 1.0):
    """n_rows candles ending TODAY (the last row's open date == today UTC,
    i.e. still-forming), closes = base, base+step, base+2*step, ... so the
    settled (second-to-last) close is easy to predict."""
    start = today_utc_midnight - timedelta(days=n_rows - 1)
    candles = []
    for i in range(n_rows):
        dt = start + timedelta(days=i)
        candles.append(_mk_candle(dt, base + i * step))
    return candles


def test_still_forming_candle_is_dropped_for_settled_anchor():
    """(1) With the last fetched candle opening TODAY (UTC), build_dip_read()
    must use the PRIOR (fully-closed) candle for settled_close/
    settled_close_date, while r.price (display) stays the raw last close -
    unchanged human-facing behavior."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    n = max(MIN_ROWS_1D + 10, 40)
    candles = _synthetic_daily_series(n, today, base=100.0, step=1.0)
    client = _FakeHLClient(candles)

    dip = build_dip_read(client, "TESTCOIN")

    assert dip.ok
    # Last row (today, still-forming): close = 100 + (n-1)*1.0
    expected_live_price = 100.0 + (n - 1) * 1.0
    assert dip.price == pytest.approx(expected_live_price)

    # Settled row (yesterday, fully closed): close = 100 + (n-2)*1.0
    expected_settled_close = 100.0 + (n - 2) * 1.0
    assert dip.settled_close == pytest.approx(expected_settled_close)
    expected_settled_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    assert dip.settled_close_date == expected_settled_date

    # The still-forming candle must NOT have been used as the anchor.
    assert dip.settled_close != pytest.approx(dip.price)


def test_last_candle_already_settled_is_used_directly():
    """Sanity/no-regression: if the last fetched candle's open date is
    already in the past (e.g. the fetch ran slightly stale, or clock skew),
    build_dip_read() must NOT drop an extra row - settled_close should equal
    the last row directly, not the one before it."""
    yesterday_open = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    n = max(MIN_ROWS_1D + 10, 40)
    candles = _synthetic_daily_series(n, yesterday_open, base=50.0, step=0.5)
    client = _FakeHLClient(candles)

    dip = build_dip_read(client, "TESTCOIN2")
    assert dip.ok
    expected_last_close = 50.0 + (n - 1) * 0.5
    assert dip.price == pytest.approx(expected_last_close)
    assert dip.settled_close == pytest.approx(expected_last_close)
    assert dip.settled_close_date == yesterday_open.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Part 2: resolve_calls.py resolves EXACT close-to-close N-day returns
# ---------------------------------------------------------------------------

class _FakeResolverClient:
    """Stand-in for resolve_calls._get_hl_client()'s HLNative - only
    `.candles()` is used (via _fetch_daily_closes, which reads "T"/"c")."""

    def __init__(self, candles):
        self._candles = candles

    def candles(self, symbol, interval, start_ms, end_ms):
        return self._candles


def _mk_ledger_row(symbol: str, anchor_date: datetime, settled_close: float, ts_utc: str,
                    source: str = "read", action: str = "ADD", ev_schema: int = 2,
                    fwd_overrides: dict | None = None) -> dict:
    row = {
        "ts_utc": ts_utc,
        "epoch": int(datetime.fromisoformat(ts_utc.replace("Z", "+00:00")).timestamp()),
        "symbol": symbol,
        "price": settled_close + 999.0,  # deliberately DIFFERENT from settled_close - proves resolver ignores it
        "ev_schema": ev_schema,
        "settled_close": settled_close,
        "settled_close_date": anchor_date.strftime("%Y-%m-%d"),
        "action": action,
        "action_reason_short": "",
        "trend": "chop",
        "adx": 10.0,
        "bb_pos": 0.5,
        "rsi": 50.0,
        "atr_pct": 0.02,
        "funding_hourly": 0.0,
        "weather_regime": "NEUTRAL",
        "breadth20": 50.0,
        "btc_vs_ema50": True,
        "safe_max_lev": 10.0,
        "source": source,
    }
    if fwd_overrides:
        row.update(fwd_overrides)
    return row


def test_resolver_gives_exact_close_to_close_horizon_no_drift(tmp_path, monkeypatch):
    """(2) THE core proving test: with a known daily-close series anchored on
    `settled_close_date`, fwd_1d/3d/5d must equal EXACTLY the N-day
    close-to-close return (net of the flat fee), regardless of what
    time-of-day `ts_utc` carries - no drift toward ~1.96d/~3.45d etc."""
    anchor_date = datetime(2024, 1, 1, tzinfo=timezone.utc)  # settled candle's OPEN date
    # C(k) = close of the candle opened on anchor_date + k days. Entry (the
    # settled_close) = C(0). The settled candle's CLOSE occurs at
    # anchor_date + 1 day - forward closes at anchor_date + (k+1) days.
    C = {0: 100.0, 1: 110.0, 2: 120.0, 3: 130.0, 4: 140.0, 5: 150.0, 6: 160.0}
    candles = [
        {"t": int((anchor_date + timedelta(days=k)).timestamp() * 1000),
         "T": int((anchor_date + timedelta(days=k)).timestamp() * 1000) + 86_399_999,  # HL real close = open + 86399999ms (23:59:59.999 UTC, NOT next midnight) - regression guard for the 2026-08-01 second fix
         "c": C[k]}
        for k in C
    ]
    fake_client = _FakeResolverClient(candles)
    monkeypatch.setattr(resolve_calls, "_get_hl_client", lambda: fake_client)

    ledger_path = tmp_path / "call_ledger.jsonl"
    resolved_path = tmp_path / "call_ledger_resolved.jsonl"
    monkeypatch.setattr(resolve_calls, "LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(resolve_calls, "RESOLVED_PATH", str(resolved_path))

    # Deliberately use a NON-midnight, off-anchor-day ts_utc (e.g. a 13:13
    # UTC alert-cron the next calendar day) to prove the resolver ignores
    # wall-clock ts_utc entirely and anchors purely on settled_close_date.
    row = _mk_ledger_row("SYNTH", anchor_date, settled_close=C[0], ts_utc="2024-01-02T13:13:00Z")
    with open(ledger_path, "w", encoding="utf-8") as f:
        import json
        f.write(json.dumps(row) + "\n")

    now = anchor_date + timedelta(days=10)  # comfortably matures all horizons
    stats = resolve_ledger(now=now)

    assert stats["resolved_now"] == 1
    assert stats["excluded_pre_fix"] == 0

    resolved = resolve_calls._load_jsonl(str(resolved_path))
    assert len(resolved) == 1
    r = resolved[0]

    expected_fwd_1d = (C[1] / C[0] - 1.0) * 100.0 - ROUND_TRIP_FEE_PCT
    expected_fwd_3d = (C[3] / C[0] - 1.0) * 100.0 - ROUND_TRIP_FEE_PCT
    expected_fwd_5d = (C[5] / C[0] - 1.0) * 100.0 - ROUND_TRIP_FEE_PCT

    assert r["fwd_1d_pct"] == pytest.approx(round(expected_fwd_1d, 4))
    assert r["fwd_3d_pct"] == pytest.approx(round(expected_fwd_3d, 4))
    assert r["fwd_5d_pct"] == pytest.approx(round(expected_fwd_5d, 4))

    # Sanity: these are EXACT (integer %) modulo the fee, not the old
    # inflated ~1.96d/~3.45d-equivalent numbers - confirms no drift.
    assert expected_fwd_1d == pytest.approx(10.0 - ROUND_TRIP_FEE_PCT)
    assert expected_fwd_3d == pytest.approx(30.0 - ROUND_TRIP_FEE_PCT)
    assert expected_fwd_5d == pytest.approx(50.0 - ROUND_TRIP_FEE_PCT)


# ---------------------------------------------------------------------------
# Part 3: pre-fix rows are excluded, never resolved on the old horizon
# ---------------------------------------------------------------------------

def test_pre_fix_rows_are_excluded_not_resolved(tmp_path, monkeypatch):
    """(3) A row logged before the fix (no ev_schema / no settled_close) must
    be counted in `excluded_pre_fix` and NEVER show up in the resolved file,
    even though it's old enough by wall-clock ts_utc and candle data exists."""
    anchor_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        {"t": int((anchor_date + timedelta(days=k)).timestamp() * 1000),
         "T": int((anchor_date + timedelta(days=k)).timestamp() * 1000) + 86_399_999,  # HL real close = open + 86399999ms (23:59:59.999 UTC, NOT next midnight) - regression guard for the 2026-08-01 second fix
         "c": 100.0 + 10.0 * k}
        for k in range(8)
    ]
    fake_client = _FakeResolverClient(candles)
    monkeypatch.setattr(resolve_calls, "_get_hl_client", lambda: fake_client)

    ledger_path = tmp_path / "call_ledger.jsonl"
    resolved_path = tmp_path / "call_ledger_resolved.jsonl"
    monkeypatch.setattr(resolve_calls, "LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(resolve_calls, "RESOLVED_PATH", str(resolved_path))

    # Pre-fix row: old schema, has `price` but NOT ev_schema/settled_close.
    pre_fix_row = {
        "ts_utc": "2024-01-01T01:01:00Z",
        "epoch": int(anchor_date.timestamp()),
        "symbol": "OLDCOIN",
        "price": 100.0,
        "action": "ADD",
        "action_reason_short": "",
        "trend": "chop",
        "adx": 10.0,
        "bb_pos": 0.5,
        "rsi": 50.0,
        "atr_pct": 0.02,
        "funding_hourly": 0.0,
        "weather_regime": "NEUTRAL",
        "breadth20": 50.0,
        "btc_vs_ema50": True,
        "safe_max_lev": 10.0,
        "source": "read",
        # no ev_schema, no settled_close, no settled_close_date
    }
    # Post-fix row: same symbol, proper schema.
    post_fix_row = _mk_ledger_row("OLDCOIN", anchor_date, settled_close=100.0, ts_utc="2024-01-02T01:01:00Z")

    import json
    with open(ledger_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(pre_fix_row) + "\n")
        f.write(json.dumps(post_fix_row) + "\n")

    assert not _has_valid_ev_schema(pre_fix_row)
    assert _has_valid_ev_schema(post_fix_row)

    now = anchor_date + timedelta(days=10)
    stats = resolve_ledger(now=now)

    assert stats["total_raw"] == 2
    assert stats["excluded_pre_fix"] == 1
    assert stats["resolved_now"] == 1

    resolved = resolve_calls._load_jsonl(str(resolved_path))
    assert len(resolved) == 1
    assert resolved[0]["ts_utc"] == "2024-01-02T01:01:00Z"  # the post-fix row, not the pre-fix one


# ---------------------------------------------------------------------------
# Part 4: same-(symbol, day) collapse
# ---------------------------------------------------------------------------

def test_same_symbol_day_collapse_prefers_read_over_alert():
    """(4) Two rows for the same symbol + calendar day (one source="read",
    one source="alert") must collapse to exactly one, keeping the "read"
    row's own data, before H1/H2 would ever bucket them."""
    read_row = {"symbol": "SOL", "ts_utc": "2024-05-01T01:01:00Z", "source": "read", "fwd_3d_pct": 5.0}
    alert_row = {"symbol": "SOL", "ts_utc": "2024-05-01T13:13:00Z", "source": "alert", "fwd_3d_pct": -3.0}
    other_symbol = {"symbol": "BTC", "ts_utc": "2024-05-01T01:01:00Z", "source": "read", "fwd_3d_pct": 1.0}
    other_day = {"symbol": "SOL", "ts_utc": "2024-05-02T01:01:00Z", "source": "read", "fwd_3d_pct": 2.0}

    collapsed = _collapse_same_symbol_day([read_row, alert_row, other_symbol, other_day])

    assert len(collapsed) == 3  # (SOL, 05-01) collapsed to 1; BTC 05-01 and SOL 05-02 both kept
    sol_may1 = [r for r in collapsed if r["symbol"] == "SOL" and r["ts_utc"].startswith("2024-05-01")]
    assert len(sol_may1) == 1
    assert sol_may1[0]["source"] == "read"
    assert sol_may1[0]["fwd_3d_pct"] == 5.0  # the read row's value, not the alert row's


def test_same_symbol_day_collapse_is_order_independent():
    """Collapse must prefer "read" regardless of which row appears first in
    the input list (a real resolved-file ordering isn't guaranteed to put
    "read" first)."""
    alert_row = {"symbol": "POPCAT", "ts_utc": "2024-06-01T13:13:00Z", "source": "alert", "fwd_3d_pct": -9.0}
    read_row = {"symbol": "POPCAT", "ts_utc": "2024-06-01T01:01:00Z", "source": "read", "fwd_3d_pct": 4.0}

    collapsed = _collapse_same_symbol_day([alert_row, read_row])
    assert len(collapsed) == 1
    assert collapsed[0]["source"] == "read"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
