#!/usr/bin/env python
"""
WAGMI Co-Pilot CALL LEDGER RESOLVER - resolve_calls.py
=============================================================================
Reads data/copilot/call_ledger.jsonl (written by call_logger.py, wired into
tools/copilot/copilot.py's format_brief) and, for every row old enough that a
horizon has actually elapsed, fetches the coin's REAL forward price (via the
standalone read-only data/fetchers/hl_native.py HLNative client) and stamps
fwd_1d_pct / fwd_3d_pct / fwd_5d_pct (net of a flat 9bp round-trip fee, for a
hypothetical notional LONG opened at the call's SETTLED-CLOSE anchor) onto a
resolved copy: data/copilot/call_ledger_resolved.jsonl.

FORWARD-EVIDENCE ANCHOR FIX (2026-08-01) - this resolver used to anchor the
N-day horizon on `ts_dt` (the row's wall-clock `ts_utc` log time) and price
on the row's raw `price` field, which copilot.py's build_dip_read() could set
to a STILL-FORMING current-UTC-day candle. Because `ts_utc` carries a
time-of-day (e.g. a 01:01 UTC cron), `target_dt = ts_dt + timedelta(days=d)`
landed mid-day, and `_price_at_or_after()` then rounded UP to the next daily
candle close - systematically INFLATING every horizon (fwd_3d actually
spanning ~3.45 days, fwd_1d up to ~1.96 days), not comparable to the
backtest's clean close-to-close baseline H1/H2 test against. FIX: the
resolver now anchors on `settled_close`/`settled_close_date` (the last FULLY
CLOSED daily candle at call time, logged by call_logger.py - see
copilot.py's "FORWARD-EVIDENCE ANCHOR FIX" docstring section), giving an
EXACT N-day close-to-close return with no look-ahead. Rows logged before this
fix (no `ev_schema` >= 2, i.e. missing settled_close/settled_close_date) are
EXCLUDED here rather than silently resolved on the old inflated horizon - see
`n_excluded_pre_fix` in the returned stats and PREREGISTRATION.md.

WHY THIS EXISTS: the project's historical backtest corpus (14mo/25 coins) is
exhausted for validating the co-pilot's own signals - every cut of it has
already been looked at, so any fit to it is suspect (the "overfit ceiling").
This resolver is the mechanism that turns the call ledger into genuinely
UNSEEN, out-of-sample evidence as calendar time passes: a call logged today
cannot be curve-fit, because its outcome doesn't exist yet when the row is
written.

READ-ONLY / STANDALONE: only imports data/fetchers/hl_native.py (HLNative).
Never imports live-bot packages or touches live/.env/data/replay/. Reads
data/copilot/call_ledger.jsonl (append-only, owned by call_logger.py) and
reads+rewrites data/copilot/call_ledger_resolved.jsonl (owned by this file
alone - copilot.py/copilot_alerts.py never touch it).

IDEMPOTENT / RE-RUNNABLE: each raw ledger row's identity is a hash of
(ts_utc, symbol, source) - see `_row_id()`. On each run, every raw row is
looked up by that id in the resolved file; already-fully-resolved rows
(all 3 horizons stamped) are left untouched, immature rows are skipped, and
rows that are NOW mature for a horizon they didn't have yet get that horizon
filled in-place (a row logged 2 days ago gets fwd_1d_pct today, then
fwd_3d_pct two days later, etc - the SAME row/id, not a duplicate). Safe to
run as often as you like; running before a candle closes is a no-op for that
row's next horizon, not an error.

HYPOTHESES (see data/copilot/PREREGISTRATION.md for the full pre-registration
- horizons, success bar, and creation date, written BEFORE any resolved data
existed):
  H1: mean fwd_3d_pct for action=ADD > mean fwd_3d_pct for action=WAIT
  H2: weather_regime=STORMY calls have worse (or more dispersed) forward
      long returns than weather_regime=WASHED_OUT calls
Both are printed as a running summary once n>=30 RESOLVED calls (i.e. with a
non-null fwd_3d_pct) exist - and are explicitly labeled "not yet significant"
below that bar, and even above it the p-value here is a light normal-
approximation Welch's t-test (no scipy dependency), meant as an honest early
read, NOT a final verdict. Do not over-read an early readout - that defeats
the entire point of pre-registering H1/H2 on unseen data.

INDEPENDENCE (same-symbol-day collapse): a symbol can be logged twice the
same UTC calendar day - once by `source="read"` (cli.py read / a manual run)
and once by `source="alert"` (copilot_alerts.py firing) - and those two rows
are NOT independent trials (same underlying market state, same DipRead
inputs to within minutes). Before H1/H2 bucketing, `print_summary()` collapses
resolved rows to at most one per (symbol, calendar day), preferring
`source="read"` (the richer row - it alone carries weather_regime/breadth20/
btc_vs_ema50) over `source="alert"` - see `_collapse_same_symbol_day()`.

CLI:
    python tools/copilot/resolve_calls.py             # resolve what's mature, print summary
    python tools/copilot/resolve_calls.py --quiet      # resolve only, skip the H1/H2 summary print
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
FETCHERS_DIR = os.path.join(BOT_DIR, "data", "fetchers")
DATA_DIR = os.path.join(BOT_DIR, "data", "copilot")
LEDGER_PATH = os.path.join(DATA_DIR, "call_ledger.jsonl")
RESOLVED_PATH = os.path.join(DATA_DIR, "call_ledger_resolved.jsonl")

HORIZONS_DAYS: Tuple[int, ...] = (1, 3, 5)
ROUND_TRIP_FEE_PCT = 0.09  # 9bps flat, net-of-fee assumption for a notional long (see module docstring)
SIGNIFICANCE_N = 30        # minimum n PER BUCKET before even attempting a p-value readout
CANDLE_FETCH_BUFFER_DAYS = 2  # pad the fetch window past `now` so a just-matured horizon's candle is included


# ---------------------------------------------------------------------------
# HL client (standalone, read-only)
# ---------------------------------------------------------------------------

def _get_hl_client():
    if FETCHERS_DIR not in sys.path:
        sys.path.insert(0, FETCHERS_DIR)
    from hl_native import HLNative  # standalone, read-only, no live-bot deps
    return HLNative()


# ---------------------------------------------------------------------------
# JSONL I/O
# ---------------------------------------------------------------------------

def _load_jsonl(path: str) -> List[dict]:
    rows: List[dict] = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a corrupt line is skipped, never fatal
    return rows


def _write_jsonl(path: str, rows: List[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Row identity + timestamp parsing
# ---------------------------------------------------------------------------

def _row_id(row: dict) -> str:
    """Stable id for a raw ledger row = hash of (ts_utc, symbol, source).
    Deliberately NOT stored in the raw ledger (keeps call_logger.py's schema
    exactly the documented fields) - recomputed here on every run so a raw
    row and its resolved counterpart always line up."""
    key = f"{row.get('ts_utc', '')}|{row.get('symbol', '')}|{row.get('source', '')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _parse_settled_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parses `settled_close_date` ("YYYY-MM-DD") into a UTC-midnight
    datetime - the OPEN time of the settled daily candle. Returns None on any
    malformed/missing input (caller treats that row as pre-fix/unresolvable)."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _has_valid_ev_schema(row: dict) -> bool:
    """True iff `row` was logged post-FIX (2026-08-01) with a usable
    settled-close anchor - see call_logger.py's EV_SCHEMA_VERSION /
    "FORWARD-EVIDENCE ANCHOR FIX". Pre-fix rows (ev_schema missing/<2, or
    missing/malformed settled_close/settled_close_date) are never resolved
    under the new anchor logic - see resolve_ledger()'s n_excluded_pre_fix."""
    schema = row.get("ev_schema")
    if not isinstance(schema, (int, float)) or schema < 2:
        return False
    settled_close = row.get("settled_close")
    if not isinstance(settled_close, (int, float)) or settled_close <= 0:
        return False
    return _parse_settled_date(row.get("settled_close_date")) is not None


# ---------------------------------------------------------------------------
# Candle fetch + forward-price lookup
# ---------------------------------------------------------------------------

def _fetch_daily_closes(client, symbol: str, start_ms: int, end_ms: int) -> Dict[date, float]:
    """Returns {utc_open_date: close_price} keyed by each daily candle's OPEN
    date (UTC). Fails soft (empty dict) on any fetch problem - caller must skip
    that symbol's rows this run rather than raise.

    HORIZON-ANCHOR NOTE (2026-08-01, second fix): we key by the candle's OPEN
    time `c["t"]` (a clean UTC-midnight date), NOT its close time `c["T"]`.
    HL daily candles close at 23:59:59.999 UTC (T = t + 86_399_999), one ms
    BEFORE the next midnight - so a previous version that matched `T >= (an
    exact-midnight target)` silently skipped the correct candle for the next
    one, inflating every fwd_Nd by one day. Date-keyed open-time lookup is
    exact AND gap-safe: a missing target-date candle yields no match (skip),
    never a stretched horizon."""
    try:
        candles = client.candles(symbol, "1d", start_ms, end_ms)
    except Exception as e:
        print(f"[resolve_calls] {symbol} candle fetch failed: {e}", file=sys.stderr)
        return {}
    out: Dict[date, float] = {}
    for c in candles or []:
        try:
            open_date = datetime.fromtimestamp(int(c["t"]) / 1000.0, tz=timezone.utc).date()
            out[open_date] = float(c["c"])
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            continue
    return out


# ---------------------------------------------------------------------------
# Core resolve
# ---------------------------------------------------------------------------

def resolve_ledger(now: Optional[datetime] = None) -> dict:
    """Idempotently updates data/copilot/call_ledger_resolved.jsonl in place.
    Returns a small stats dict for the caller to report/print.

    ANCHOR (post-FIX, 2026-08-01): each row's N-day horizon is anchored on
    its SETTLED daily candle, not its wall-clock `ts_utc`. `settled_close_date`
    ("YYYY-MM-DD") is the settled candle's OPEN date; that candle's CLOSE (the
    `settled_close` price, i.e. the "entry") occurred at `settled_close_date`
    + 1 day, 00:00 UTC. So the exact N-day-forward instant is
    `settled_close_date` + (N+1) days, 00:00 UTC - a UTC daily-candle
    boundary, which `_price_at_or_after()` then matches EXACTLY (no
    time-of-day rounding, unlike the old ts_utc anchor - see module
    docstring "FORWARD-EVIDENCE ANCHOR FIX").

    Pre-fix rows (ev_schema < 2 / missing settled_close fields - see
    `_has_valid_ev_schema()`) are never added to `pending_by_symbol`; they
    are simply never resolved and are counted in `n_excluded_pre_fix`."""
    now = now or datetime.now(timezone.utc)
    raw_rows = _load_jsonl(LEDGER_PATH)
    resolved_rows = _load_jsonl(RESOLVED_PATH)
    resolved_by_id: Dict[str, dict] = {r.get("id"): r for r in resolved_rows if r.get("id")}

    n_total = len(raw_rows)
    n_already_fully_resolved = 0
    n_not_old_enough = 0
    n_excluded_pre_fix = 0
    min_horizon = min(HORIZONS_DAYS)

    pending_by_symbol: Dict[str, List[Tuple[dict, str, datetime]]] = {}
    for raw in raw_rows:
        if not _has_valid_ev_schema(raw):
            n_excluded_pre_fix += 1
            continue
        anchor_dt = _parse_settled_date(raw.get("settled_close_date"))
        if anchor_dt is None:  # belt-and-braces; _has_valid_ev_schema already checked this
            n_excluded_pre_fix += 1
            continue
        rid = _row_id(raw)
        existing = resolved_by_id.get(rid)
        fully_done = existing is not None and all(
            existing.get(f"fwd_{d}d_pct") is not None for d in HORIZONS_DAYS
        )
        if fully_done:
            n_already_fully_resolved += 1
            continue
        # anchor_dt is the settled candle's OPEN date; its CLOSE (the entry
        # instant) is anchor_dt + 1 day - the min horizon must elapse AFTER
        # that entry instant, not after the open date itself.
        if now < anchor_dt + timedelta(days=min_horizon + 1):
            n_not_old_enough += 1
            continue
        pending_by_symbol.setdefault(raw.get("symbol", ""), []).append((raw, rid, anchor_dt))

    n_pending = sum(len(v) for v in pending_by_symbol.values())
    if n_pending == 0:
        return {
            "resolved_now": 0,
            "total_raw": n_total,
            "already_fully_resolved": n_already_fully_resolved,
            "not_old_enough": n_not_old_enough,
            "excluded_pre_fix": n_excluded_pre_fix,
        }

    client = _get_hl_client()
    n_resolved_now = 0
    n_skipped_no_data = 0

    for symbol, items in pending_by_symbol.items():
        min_ts = min(ts for _, _, ts in items)
        start_ms = int(min_ts.timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000) + CANDLE_FETCH_BUFFER_DAYS * 24 * 3600 * 1000
        closes = _fetch_daily_closes(client, symbol, start_ms, end_ms)
        if not closes:
            print(f"[resolve_calls] no candle data for {symbol} - skipping {len(items)} row(s) this run", file=sys.stderr)
            n_skipped_no_data += len(items)
            continue

        for raw, rid, anchor_dt in items:
            entry_price = raw.get("settled_close")
            if not isinstance(entry_price, (int, float)) or entry_price <= 0:
                continue
            out_row = dict(resolved_by_id.get(rid) or {})
            out_row.update(raw)  # always keep the resolved row's raw fields in sync with the source row
            out_row["id"] = rid

            any_new_horizon = False
            for d in HORIZONS_DAYS:
                key = f"fwd_{d}d_pct"
                if out_row.get(key) is not None:
                    continue  # this horizon already stamped - never overwritten
                # Close-to-close: fwd_Nd compares the SETTLED candle's close
                # (entry_price) to the close of the candle that OPENED N days
                # later (settled_date + N). That target candle has fully closed
                # once `now` is past the midnight AFTER it, i.e. anchor + (N+1)
                # days. Lookup is EXACT by open-date (see _fetch_daily_closes'
                # HORIZON-ANCHOR NOTE): a data gap on the target date yields no
                # match -> skip and retry, never a silently-stretched horizon.
                if now < anchor_dt + timedelta(days=d + 1):
                    continue  # target candle not closed yet - not mature
                target_date = (anchor_dt + timedelta(days=d)).date()
                px = closes.get(target_date)
                if px is None:
                    continue  # mature by clock, but the target-date candle isn't in yet / a gap - try next run
                raw_pct = (px / entry_price - 1.0) * 100.0
                net_pct = raw_pct - ROUND_TRIP_FEE_PCT
                out_row[key] = round(net_pct, 4)
                any_new_horizon = True

            if any_new_horizon:
                resolved_by_id[rid] = out_row
                n_resolved_now += 1

    resolved_list = sorted(resolved_by_id.values(), key=lambda r: r.get("ts_utc", ""))
    _write_jsonl(RESOLVED_PATH, resolved_list)

    return {
        "resolved_now": n_resolved_now,
        "total_raw": n_total,
        "already_fully_resolved": n_already_fully_resolved,
        "not_old_enough": n_not_old_enough,
        "excluded_pre_fix": n_excluded_pre_fix,
        "skipped_no_data": n_skipped_no_data,
        "resolved_file_rows": len(resolved_list),
    }


# ---------------------------------------------------------------------------
# Lightweight Welch's t-test (normal approximation, no scipy dependency) -
# ONLY used for the honest-early-read summary below, never to gate anything.
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _welch_p_value(a: List[float], b: List[float]) -> Optional[float]:
    """Two-sided p-value via Welch's t-statistic with a NORMAL approximation
    (valid-ish once both n are >=30ish per the CLT; deliberately not exact -
    this is an early-warning number, not a publication-grade test). Returns
    None if either sample has <2 points or zero variance in both."""
    if len(a) < 2 or len(b) < 2:
        return None
    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    var_a, var_b = statistics.variance(a), statistics.variance(b)
    se2 = var_a / len(a) + var_b / len(b)
    if se2 <= 0:
        return None
    z = (mean_a - mean_b) / math.sqrt(se2)
    return 2.0 * (1.0 - _normal_cdf(abs(z)))


# ---------------------------------------------------------------------------
# Same-(symbol, calendar-day) collapse - H1/H2 INDEPENDENCE fix (see module
# docstring "INDEPENDENCE"). A symbol logged twice the same UTC day (once by
# source="read", once by source="alert") is NOT two independent trials for
# the H1/H2 bucketed means/p-values - collapse to one row per (symbol, day)
# before any bucketing, preferring source="read".
# ---------------------------------------------------------------------------

_SOURCE_RANK = {"read": 0, "alert": 1}  # lower = preferred; unknown sources rank last


def _collapse_same_symbol_day(rows: List[dict]) -> List[dict]:
    """Collapses `rows` to at most one per (symbol, UTC calendar day of
    ts_utc), keeping the source="read" row when both exist for that day
    (falls back to whichever row sorts first if neither is "read"/"alert").
    Never mutates the input list; order of the output is unspecified (the
    caller only aggregates it, never prints it in ledger order)."""
    best: Dict[Tuple[str, str], dict] = {}
    for r in rows:
        symbol = r.get("symbol") or "?"
        day = str(r.get("ts_utc") or "")[:10]
        key = (symbol, day)
        rank = _SOURCE_RANK.get(r.get("source"), 2)
        existing = best.get(key)
        if existing is None or rank < _SOURCE_RANK.get(existing.get("source"), 2):
            best[key] = r
    return list(best.values())


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _bucket_line(label: str, vals: List[float]) -> str:
    if not vals:
        return f"    {label:<10s} n=0"
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return f"    {label:<10s} n={len(vals):<4d} mean fwd-3d = {mean:+7.2f}%   sd={sd:5.2f}"


def print_summary(resolved_rows: List[dict], n_excluded_pre_fix: int = 0) -> None:
    # ev_schema>=2 gate (defensive - resolve_ledger() never resolves pre-fix
    # rows in the first place, so this should be a no-op in practice) +
    # same-(symbol, day) collapse for H1/H2 independence (see module
    # docstring "INDEPENDENCE" / _collapse_same_symbol_day above).
    schema_ok = [r for r in resolved_rows if r.get("fwd_3d_pct") is not None and _has_valid_ev_schema(r)]
    have_3d = _collapse_same_symbol_day(schema_ok)
    n = len(have_3d)
    print(f"\n=== FORWARD-EVIDENCE SUMMARY (n={n} resolved calls with fwd_3d_pct, post same-symbol-day collapse) ===")
    if n_excluded_pre_fix:
        print(
            f"({n_excluded_pre_fix} pre-fix row(s) excluded - logged before the 2026-08-01 settled-close anchor "
            f"fix, no settled_close/settled_close_date; see PREREGISTRATION.md.)"
        )
    if n < SIGNIFICANCE_N:
        print(
            f"n={n}, not yet significant (need n>={SIGNIFICANCE_N} before ANY H1/H2 readout is "
            f"attempted - see data/copilot/PREREGISTRATION.md). Skipping H1/H2 for now."
        )
        return

    by_action: Dict[str, List[float]] = {}
    for r in have_3d:
        by_action.setdefault(r.get("action") or "?", []).append(r["fwd_3d_pct"])

    print("\nH1 (pre-registered): mean fwd-3d(ADD) > mean fwd-3d(WAIT)")
    for action in ("ADD", "HOLD", "WAIT"):
        print(_bucket_line(action, by_action.get(action, [])))
    n_add, n_wait = len(by_action.get("ADD", [])), len(by_action.get("WAIT", []))
    if n_add >= SIGNIFICANCE_N and n_wait >= SIGNIFICANCE_N:
        p = _welch_p_value(by_action["ADD"], by_action["WAIT"])
        p_bit = f"approx p={p:.3f} (normal-approx Welch t-test)" if p is not None else "p unavailable (degenerate variance)"
        print(f"    -> n=ADD:{n_add}, WAIT:{n_wait}; {p_bit}. Early read only - do not over-interpret a single p-value.")
    else:
        print(
            f"    -> n=ADD:{n_add}, WAIT:{n_wait}; NOT YET SIGNIFICANT "
            f"(need n>={SIGNIFICANCE_N}-50 PER BUCKET per the pre-registration). Do not over-read."
        )

    by_regime: Dict[str, List[float]] = {}
    for r in have_3d:
        wr = r.get("weather_regime")
        if wr:
            by_regime.setdefault(wr, []).append(r["fwd_3d_pct"])

    print("\nH2 (pre-registered): weather=STORMY has wider/worse realized long returns than WASHED_OUT")
    for regime in ("STORMY", "HEADWIND", "WASHED_OUT", "NEUTRAL"):
        print(_bucket_line(regime, by_regime.get(regime, [])))
    n_stormy, n_washed = len(by_regime.get("STORMY", [])), len(by_regime.get("WASHED_OUT", []))
    if n_stormy >= SIGNIFICANCE_N and n_washed >= SIGNIFICANCE_N:
        p = _welch_p_value(by_regime["STORMY"], by_regime["WASHED_OUT"])
        p_bit = f"approx p={p:.3f} (normal-approx Welch t-test)" if p is not None else "p unavailable (degenerate variance)"
        print(f"    -> n=STORMY:{n_stormy}, WASHED_OUT:{n_washed}; {p_bit}. Early read only - do not over-interpret a single p-value.")
    else:
        print(
            f"    -> n=STORMY:{n_stormy}, WASHED_OUT:{n_washed}; NOT YET SIGNIFICANT "
            f"(need n>={SIGNIFICANCE_N}-50 PER BUCKET per the pre-registration). Note: source=\"alert\" rows "
            f"currently log weather_regime=null (see call_logger.py docstring) - only source=\"read\" rows "
            f"feed H2 today."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="WAGMI Co-Pilot CALL LEDGER resolver - stamps forward returns onto call_ledger.jsonl rows once mature (read-only, idempotent)."
    )
    ap.add_argument("--quiet", action="store_true", help="Resolve only; skip the H1/H2 summary print")
    args = ap.parse_args()

    stats = resolve_ledger()
    excluded_bit = f" excluded_pre_fix={stats.get('excluded_pre_fix', 0)}" if stats.get("excluded_pre_fix") else ""
    if stats["resolved_now"] == 0 and stats.get("total_raw", 0) == 0:
        print("0 rows in the call ledger yet (data/copilot/call_ledger.jsonl is empty/missing).")
    elif stats["resolved_now"] == 0:
        print(
            f"0 rows old enough to resolve this run "
            f"(total={stats['total_raw']}, already_resolved={stats['already_fully_resolved']}, "
            f"immature={stats['not_old_enough']}{excluded_bit})."
        )
    else:
        print(
            f"Resolved/updated {stats['resolved_now']} row(s) this run "
            f"(total raw={stats['total_raw']}, resolved-file rows={stats.get('resolved_file_rows', '?')}, "
            f"already_fully_resolved={stats['already_fully_resolved']}, immature={stats['not_old_enough']}"
            + (f", skipped_no_data={stats['skipped_no_data']}" if stats.get("skipped_no_data") else "")
            + excluded_bit
            + ")."
        )
    if stats.get("excluded_pre_fix"):
        print(
            f"[resolve_calls] {stats['excluded_pre_fix']} row(s) excluded as pre-FORWARD-EVIDENCE-ANCHOR-FIX "
            f"(logged before 2026-08-01, lack settled_close/settled_close_date) - never resolved under the new "
            f"anchor logic, per PREREGISTRATION.md."
        )

    if not args.quiet:
        resolved_rows = _load_jsonl(RESOLVED_PATH)
        print_summary(resolved_rows, n_excluded_pre_fix=stats.get("excluded_pre_fix", 0))


if __name__ == "__main__":
    main()
