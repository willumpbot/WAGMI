#!/usr/bin/env python
"""
WAGMI Co-Pilot CALL LEDGER - call_logger.py
=============================================================================
Logs ONE entry-time-safe snapshot row per co-pilot brief to
data/copilot/call_ledger.jsonl, so that in 60-90 days the co-pilot's own
ADD/HOLD/WAIT calls can be honestly tested against UNSEEN, out-of-sample
forward returns (tools/copilot/resolve_calls.py does the resolving). This is
the CURE for the overfit ceiling on the existing 14mo/25-coin historical
corpus: it manufactures genuinely new, un-mined data going forward instead of
re-slicing the same history again.

READ-ONLY / STANDALONE, same constraints as every tools/copilot/*.py module:
never imports live-bot packages (llm/, execution/, core/, strategies/), never
touches live/.env/data/replay. Writes to exactly ONE new, isolated file this
tool owns: data/copilot/call_ledger.jsonl (append-only). Never reads or
writes any existing live-bot or copilot state file (alert_state.json etc).

FAIL-NEUTRAL BY DESIGN - the whole point of a forward-evidence ledger is that
it must NEVER be the reason a brief breaks. `log_call()` swallows every
exception internally (logs a one-line warning to stderr) and always returns
a bool rather than raising. Callers (copilot.py's format_brief) can call it
unconditionally without a try/except of their own, though format_brief wraps
it in one anyway as a second layer of protection.

GATING: COPILOT_CALL_LOG env var, default "true". Set to "false"/"0"/"no"/
"off" to disable logging entirely (zero file I/O, not just a skipped write).

DEDUP: at most one row per (symbol, UTC calendar day, source). If the same
symbol/source combo is read again the same day (e.g. re-running `cli.py read`
a few times, or the alerter firing twice), the FIRST row of the day wins and
later calls are silently skipped - keeps the ledger from bloating with
near-duplicate intraday snapshots while still capturing one entry-time-safe
reading per symbol per day per source.

ROW SCHEMA (one JSON object per line):
    ts_utc            ISO8601 UTC timestamp of this call, second precision
    epoch             int(ts_utc as Unix epoch SECONDS) - a machine-sortable
                       twin of ts_utc for the resolver's date math. NOTE: this
                       is the plain Unix epoch, NOT the live WAGMI bot's
                       separate "trading epoch" concept (e.g. the Jul-15
                       epoch reset) - this tool is standalone and never reads
                       that state; do not conflate the two.
    symbol            e.g. "SOL"
    price             dip.price - the LIVE/display close the brief was built
                       on (may be a still-forming current-UTC-day candle -
                       kept for human-facing continuity ONLY; the resolver
                       must NOT use this field, see settled_close below)
    ev_schema         int, forward-evidence instrument schema version (see
                       "FORWARD-EVIDENCE ANCHOR FIX" in copilot.py's module
                       docstring). Rows without this field (or < 2) predate
                       the 2026-08-01 fix, lack settled_close/
                       settled_close_date, and are logged with the STILL-
                       FORMING candle as `price` and dated by wall-clock
                       `ts_utc` - resolve_calls.py excludes them from H1/H2
                       rather than silently resolving them on that inflated
                       horizon.
    settled_close     dip.settled_close - close of the last FULLY CLOSED
                       daily candle (entry-time-safe, no look-ahead). THIS is
                       the entry price resolve_calls.py uses for fwd_Nd_pct.
    settled_close_date  dip.settled_close_date, "YYYY-MM-DD" - the settled
                       candle's OPEN date (HL daily-candle convention). THIS
                       is the calendar anchor resolve_calls.py uses to date
                       the N-day close-to-close horizon (NOT ts_utc, which is
                       only the wall-clock time the brief happened to run).
    action            "ADD" / "HOLD" / "WAIT" (DipRead.action, verbatim)
    action_reason_short  truncated DipRead.action_reason (first clause/~140 chars)
    trend             "up" / "chop" / "down" (DipRead.trend_1d)
    adx               DipRead.adx_1d
    bb_pos            DipRead.bb_pos_1d (0=lower band, 1=upper band)
    rsi               DipRead.rsi_1d
    atr_pct           DipRead.atr_pct_1d (fraction, e.g. 0.04 = 4%)
    funding_hourly    DipRead.funding_rate (HL's real per-hour rate)
    weather_regime    MarketWeather.regime ("STORMY"/"HEADWIND"/"WASHED_OUT"/
                       "NEUTRAL"), or null if not supplied/unavailable. Only
                       copilot.py's `read` path currently computes market
                       weather (once per run, market-wide) and threads it
                       through; copilot_alerts.py does not compute it today
                       (it would add an extra network+CSV pass to a job that
                       runs every 2h), so source="alert" rows log this null.
                       See resolve_calls.py's H2 readout for the effect this
                       has on regime-bucketed sample sizes.
    breadth20         MarketWeather.breadth_pct (0-100), or null (same caveat)
    btc_vs_ema50      MarketWeather.btc_above_ema50 (bool: True=above/False=
                       below), or null (same caveat)
    safe_max_lev      LiquidationRead.safe_max_leverage, or null if no
                       liquidation read was available
    source            "read" (tools/copilot/cli.py read / copilot.py main) or
                       "alert" (copilot_alerts.py, only logged when it
                       actually computes+shows a brief, i.e. on a FIRE/
                       FIRE_CLEAR transition - copilot_alerts.py does not
                       build a brief on quiet/unchanged runs, so it does not
                       log one either; this is intentional, not a gap)

No `id` field is stored in the raw ledger - resolve_calls.py derives a stable
id by hashing (ts_utc, symbol, source) itself, so the ledger schema stays
exactly the fields above and the id computation lives in one place.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BOT_DIR, "data", "copilot")
LEDGER_PATH = os.path.join(DATA_DIR, "call_ledger.jsonl")

CALL_LOG_ENV = "COPILOT_CALL_LOG"
_DISABLED_VALUES = {"false", "0", "no", "off"}

MAX_REASON_LEN = 140

# Forward-evidence instrument schema version - bumped 2026-08-01 when
# settled_close/settled_close_date were added (see copilot.py's module
# docstring "FORWARD-EVIDENCE ANCHOR FIX" + PREREGISTRATION.md). Rows logged
# before this (no `ev_schema` key at all, i.e. implicitly schema 1) used the
# still-forming current-day candle as their price and wall-clock `ts_utc` as
# the horizon anchor - both proven wrong. resolve_calls.py gates on this
# field: only ev_schema >= 2 rows are resolved / feed H1/H2.
EV_SCHEMA_VERSION = 2


def _is_enabled() -> bool:
    val = os.environ.get(CALL_LOG_ENV, "true").strip().lower()
    return val not in _DISABLED_VALUES


def _short_reason(reason: Optional[str], max_len: int = MAX_REASON_LEN) -> str:
    """Collapses whitespace and truncates to a short, human-skimmable
    summary of DipRead.action_reason - never raises on odd input."""
    if not reason:
        return ""
    flat = " ".join(str(reason).split())
    if len(flat) <= max_len:
        return flat
    cut = flat[:max_len]
    last_space = cut.rfind(" ")
    if last_space > max_len * 0.6:
        cut = cut[:last_space]
    return cut.rstrip(",;:- ") + "..."


def build_call_row(
    symbol: str,
    dip: Any,
    liq: Optional[Any],
    weather: Optional[Any] = None,
    source: str = "read",
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Builds one ledger row dict from ALREADY-COMPUTED DipRead/
    LiquidationRead/MarketWeather objects - never recomputes/refetches
    anything. Returns None if `dip` isn't a usable, ok read (nothing
    meaningful to log for a NODATA brief)."""
    if dip is None or not getattr(dip, "ok", False):
        return None
    now = now or datetime.now(timezone.utc)

    weather_ok = weather is not None and getattr(weather, "ok", False)

    return {
        "ts_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "epoch": int(now.timestamp()),
        "symbol": symbol,
        "price": getattr(dip, "price", None),
        "ev_schema": EV_SCHEMA_VERSION,
        "settled_close": getattr(dip, "settled_close", None),
        "settled_close_date": getattr(dip, "settled_close_date", None),
        "action": getattr(dip, "action", None),
        "action_reason_short": _short_reason(getattr(dip, "action_reason", None)),
        "trend": getattr(dip, "trend_1d", None),
        "adx": getattr(dip, "adx_1d", None),
        "bb_pos": getattr(dip, "bb_pos_1d", None),
        "rsi": getattr(dip, "rsi_1d", None),
        "atr_pct": getattr(dip, "atr_pct_1d", None),
        "funding_hourly": getattr(dip, "funding_rate", None),
        "weather_regime": getattr(weather, "regime", None) if weather_ok else None,
        "breadth20": getattr(weather, "breadth_pct", None) if weather_ok else None,
        "btc_vs_ema50": getattr(weather, "btc_above_ema50", None) if weather_ok else None,
        "safe_max_lev": getattr(liq, "safe_max_leverage", None) if liq is not None else None,
        "source": source,
    }


def _today_str(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _already_logged_today(symbol: str, source: str, today: str) -> bool:
    """Linear scan of the ledger for an existing (symbol, day, source) row.
    O(n) in ledger size, which is fine at this tool's expected scale (a
    handful of symbols x 2 sources x ~1 row/day - even a full year is only a
    few thousand short lines). Never raises - a corrupt/missing file is
    treated as 'not logged yet' so a logging hiccup never blocks a new row."""
    if not os.path.exists(LEDGER_PATH):
        return False
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    row.get("symbol") == symbol
                    and row.get("source") == source
                    and str(row.get("ts_utc", ""))[:10] == today
                ):
                    return True
    except OSError:
        return False
    return False


def log_call(
    symbol: str,
    dip: Any,
    liq: Optional[Any] = None,
    weather: Optional[Any] = None,
    source: str = "read",
    now: Optional[datetime] = None,
) -> bool:
    """Append one row to the call ledger. FAIL-NEUTRAL: every exception is
    caught here and reported to stderr only - this function must never raise
    out to a caller building a brief. Returns True iff a row was actually
    written (False on: disabled via env flag, no usable dip, or a dedup skip
    because a row for this symbol/day/source already exists)."""
    try:
        if not _is_enabled():
            return False
        row = build_call_row(symbol, dip, liq, weather, source, now)
        if row is None:
            return False
        now_dt = now or datetime.now(timezone.utc)
        today = _today_str(now_dt)
        if _already_logged_today(symbol, source, today):
            return False
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except Exception as e:  # noqa: BLE001 - deliberate catch-all, see FAIL-NEUTRAL above
        print(f"[call_logger] WARNING: failed to log call for {symbol}: {e}", file=sys.stderr)
        return False
