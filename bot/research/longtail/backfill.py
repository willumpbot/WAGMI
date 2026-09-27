"""
Long-Tail Alpha Program — Historical Data Backfill (v1)
==================================================================

STANDALONE, READ-ONLY research script. Hits the PUBLIC Hyperliquid info API
via `data/fetchers/hl_native.py` (HLNative — requests + stdlib only, no
live-bot imports). Does NOT import anything from the live bot package
(strategies/, execution/, llm/, etc.) and does NOT write to any live-bot
state file, `data/replay/`, or `.env`. Safe to run at any time, from any
machine, with zero risk to the running paper/live bot.

Reads the coin universe from `data/longtail/universe.json` (built by
`research/longtail/universe_screener.py`) and backfills, per coin:
    - Daily candles,  ~400 days back -> now   (interval "1d")
    - 1h candles,     last 200 days -> now    (interval "1h")
    - Funding history, last 200 days -> now

Outputs (append-only, dedupe-on-timestamp so re-runs are idempotent):
    data/longtail/ohlc/{coin}_{interval}.csv
        columns: open_time_ms, dt_utc_iso, o, h, l, c, v
    data/longtail/funding/{coin}.csv
        columns: time_ms, dt_utc_iso, fundingRate, premium
    data/longtail/data_quality.jsonl
        one line per (coin, series) with hygiene checks (see below)

Hygiene (the moat — this data feeds a backtest; bad data = false edge):
For each coin/interval we validate and log:
    - monotonic increasing timestamps
    - expected-vs-actual candle count (flag >2% gaps against interval*range)
    - any zero-volume candle with nonzero (h - l) range
    - any null/NaN OHLC value
A coin with >2% missing 1h candles gets "data_suspect": true in the quality
log, as does a coin with >5% zero-volume-nonzero-range candles (a real hole
found live: ZEC had 98/401 daily rows at v=0 with h!=l and was NOT being
flagged before this check was wired into the data_suspect verdict). We do
NOT interpolate missing candles — the series is left exactly as returned by
HL and just flagged for the backtest to quarantine/handle.

Forming/partial daily candle guard (2026-08-01 fix): `HLNative.candles()`
returns whatever HL has up to `end_ms`, including a still-forming/partial
bar for the current UTC day if `end_ms` falls mid-day — the live bot's
`data/fetcher.py` already guards against this (`_drop_forming`) but this
backfill script did not, so every `data/longtail/ohlc/*_1d.csv` carried a
partial last row (~0.5x a full day's volume) whenever backfill ran mid-day
(confirmed on AAVE/ADA/AVAX/APT, last row 2026-07-31). `_drop_forming_daily`
below drops that row before it's ever written or validated.

Usage:
    python research/longtail/backfill.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from data.fetchers.hl_native import HLNative  # noqa: E402

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

UNIVERSE_JSON = REPO_ROOT / "data" / "longtail" / "universe.json"
OHLC_DIR = REPO_ROOT / "data" / "longtail" / "ohlc"
FUNDING_DIR = REPO_ROOT / "data" / "longtail" / "funding"
QUALITY_LOG = REPO_ROOT / "data" / "longtail" / "data_quality.jsonl"

DAILY_LOOKBACK_DAYS = 400
HOURLY_LOOKBACK_DAYS = 200
FUNDING_LOOKBACK_DAYS = 200

MS_PER_DAY = 24 * 60 * 60 * 1000
MS_PER_HOUR = 60 * 60 * 1000
# HL funding settles hourly on most perps.
MS_PER_FUNDING = 60 * 60 * 1000

INTERVAL_MS = {
    "1d": MS_PER_DAY,
    "1h": MS_PER_HOUR,
}

GAP_FLAG_THRESHOLD = 0.02  # >2% missing candles => data_suspect
ZERO_VOL_FLAG_THRESHOLD = 0.05  # >5% zero-vol-nonzero-range candles => data_suspect

# HL "k"-prefixed coins (kSHIB, kPEPE, kBONK, etc.) are already the exact
# ticker HL lists on its perp exchange (1000x-denominated contracts) — no
# translation needed, `coin` from universe.json is used as-is in API calls.


def now_ms() -> int:
    return int(time.time() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


# --------------------------------------------------------------------------
# CSV I/O — append-only, dedupe-on-timestamp
# --------------------------------------------------------------------------

def load_existing_keys(path: Path, key_col: str) -> set:
    if not path.exists():
        return set()
    keys = set()
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                keys.add(int(row[key_col]))
            except (KeyError, ValueError):
                continue
    return keys


def write_ohlc_csv(path: Path, candles: List[Dict[str, Any]]) -> int:
    """Merge `candles` into `path`, dedupe on open_time_ms, sort ascending.
    Returns the total row count after merge."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: Dict[int, Tuple] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    t = int(row["open_time_ms"])
                    rows[t] = (
                        t,
                        row["dt_utc_iso"],
                        row["o"],
                        row["h"],
                        row["l"],
                        row["c"],
                        row["v"],
                    )
                except (KeyError, ValueError):
                    continue
    for c in candles:
        t = c.get("t")
        if t is None:
            continue
        rows[t] = (
            t,
            iso(t),
            c.get("o"),
            c.get("h"),
            c.get("l"),
            c.get("c"),
            c.get("v"),
        )
    ordered = sorted(rows.values(), key=lambda r: r[0])
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["open_time_ms", "dt_utc_iso", "o", "h", "l", "c", "v"])
        writer.writerows(ordered)
    return len(ordered)


def write_funding_csv(path: Path, records: List[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: Dict[int, Tuple] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    t = int(row["time_ms"])
                    rows[t] = (
                        t,
                        row["dt_utc_iso"],
                        row["fundingRate"],
                        row["premium"],
                    )
                except (KeyError, ValueError):
                    continue
    for r in records:
        t = r.get("time")
        if t is None:
            continue
        rows[t] = (
            t,
            iso(t),
            r.get("fundingRate"),
            r.get("premium"),
        )
    ordered = sorted(rows.values(), key=lambda r: r[0])
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_ms", "dt_utc_iso", "fundingRate", "premium"])
        writer.writerows(ordered)
    return len(ordered)


# --------------------------------------------------------------------------
# Hygiene checks
# --------------------------------------------------------------------------

def _is_nan_or_none(x: Any) -> bool:
    if x is None:
        return True
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def _drop_forming_daily(candles: List[Dict[str, Any]], now_ms_val: int) -> List[Dict[str, Any]]:
    """Drop the last daily candle if it is not yet a fully-settled UTC day.

    Mirrors the intent of `data/fetcher.py`'s `_drop_forming` guard (the
    live bot already drops any candle whose close time hasn't elapsed) —
    this research backfill had no equivalent, so its most recent daily row
    was a forming/partial bar (about half a full day's volume) whenever
    backfill last ran mid-UTC-day. HL daily candles have open `t` and close
    `T = t + 86_399_999` (23:59:59.999 later); a bar is settled only once
    `now_ms_val > T`. We check BOTH the close-time field (authoritative
    when present) and the open date vs. `now_ms_val`'s UTC date
    (belt-and-suspenders in case `T` is ever missing/malformed) — either
    condition being true is enough to drop the row. Only ever drops at most
    the single last candle; every other row is untouched. No-op on an
    empty list.
    """
    if not candles:
        return candles
    last = candles[-1]
    t = last.get("t")
    if t is None:
        return candles
    close_t = last.get("T")
    still_forming_by_close = close_t is not None and now_ms_val <= close_t
    now_date = datetime.fromtimestamp(now_ms_val / 1000, tz=timezone.utc).date()
    open_date = datetime.fromtimestamp(t / 1000, tz=timezone.utc).date()
    still_forming_by_date = open_date >= now_date
    if still_forming_by_close or still_forming_by_date:
        return candles[:-1]
    return candles


def validate_ohlc(
    coin: str,
    interval: str,
    candles: List[Dict[str, Any]],
    expected_start_ms: int,
    expected_end_ms: int,
) -> Dict[str, Any]:
    interval_ms = INTERVAL_MS[interval]
    n = len(candles)
    result: Dict[str, Any] = {
        "coin": coin,
        "series": interval,
        "n_candles": n,
        "checked_at": iso(now_ms()),
    }

    if n == 0:
        result.update(
            {
                "monotonic": True,
                "expected_count": 0,
                "actual_count": 0,
                "gap_pct": None,
                "zero_vol_nonzero_range_count": 0,
                "null_ohlc_count": 0,
                "first_date": None,
                "last_date": None,
                "short_history": True,
                "data_suspect": True,
                "note": "no candles returned",
            }
        )
        return result

    ts = [c["t"] for c in candles]
    monotonic = all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))

    first_t = ts[0]
    last_t = ts[-1]
    # Expected count based on the ACTUAL span returned (accounts for
    # coins listed more recently than the requested lookback window —
    # that's a short-history condition, not a gap).
    span_ms = max(last_t - first_t, 0)
    expected_in_span = int(round(span_ms / interval_ms)) + 1
    gap_pct = 0.0
    if expected_in_span > 0:
        gap_pct = max(0.0, (expected_in_span - n) / expected_in_span)

    # Short-history flag: coin's earliest candle is well after the
    # requested backfill start (e.g. recent listing like PUMP/XPL/PENGU/
    # FARTCOIN) — expected, not an error.
    short_history = first_t > expected_start_ms + interval_ms * 3

    # Tail-coverage: does the series actually reach the requested end?
    # A span-only gap check is blind to a truncation that cut the series
    # short at the END (e.g. a mid-pagination 429 that failed-soft) —
    # last_date sits months before "now" yet the observed span looks
    # dense. Flag that explicitly; it's a real hole, not short history.
    tail_gap_ms = max(expected_end_ms - last_t, 0)
    incomplete_tail = tail_gap_ms > interval_ms * 3

    zero_vol_nonzero_range = 0
    null_ohlc = 0
    for c in candles:
        o, h, l, cl, v = c.get("o"), c.get("h"), c.get("l"), c.get("c"), c.get("v")
        if any(_is_nan_or_none(x) for x in (o, h, l, cl)):
            null_ohlc += 1
            continue
        try:
            of, hf, lf, clf = float(o), float(h), float(l), float(cl)
            vf = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            null_ohlc += 1
            continue
        if vf == 0.0 and (hf - lf) != 0.0:
            zero_vol_nonzero_range += 1

    # Zero-vol-nonzero-range gate: a candle with v=0 but h!=l is exchange-
    # reported "no trades" alongside a wick that shouldn't exist without a
    # trade — a real data hole. Previously computed but NOT included in the
    # data_suspect verdict (confirmed live: ZEC had 98/401 daily rows like
    # this and was reported data_suspect=false). >5% of the series flips it.
    zero_vol_pct = (zero_vol_nonzero_range / n) if n > 0 else 0.0
    zero_vol_flag = zero_vol_pct > ZERO_VOL_FLAG_THRESHOLD

    data_suspect = (
        (not monotonic)
        or (gap_pct > GAP_FLAG_THRESHOLD)
        or (null_ohlc > 0)
        or incomplete_tail
        or zero_vol_flag
    )

    result.update(
        {
            "monotonic": monotonic,
            "expected_count": expected_in_span,
            "actual_count": n,
            "gap_pct": round(gap_pct * 100, 3),
            "zero_vol_nonzero_range_count": zero_vol_nonzero_range,
            "zero_vol_pct": round(zero_vol_pct * 100, 3),
            "null_ohlc_count": null_ohlc,
            "first_date": iso(first_t),
            "last_date": iso(last_t),
            "short_history": short_history,
            "incomplete_tail": incomplete_tail,
            "tail_gap_hours": round(tail_gap_ms / MS_PER_HOUR, 1),
            "data_suspect": data_suspect,
        }
    )
    return result


def validate_funding(
    coin: str,
    records: List[Dict[str, Any]],
    expected_start_ms: int,
    expected_end_ms: int,
) -> Dict[str, Any]:
    n = len(records)
    result: Dict[str, Any] = {
        "coin": coin,
        "series": "funding",
        "n_records": n,
        "checked_at": iso(now_ms()),
    }
    if n == 0:
        result.update(
            {
                "monotonic": True,
                "first_date": None,
                "last_date": None,
                "short_history": True,
                "data_suspect": True,
                "note": "no funding records returned",
            }
        )
        return result
    ts = [r["time"] for r in records]
    monotonic = all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))
    first_t, last_t = ts[0], ts[-1]
    short_history = first_t > expected_start_ms + MS_PER_FUNDING * 3
    null_count = sum(
        1
        for r in records
        if _is_nan_or_none(r.get("fundingRate")) or _is_nan_or_none(r.get("premium"))
    )
    # expected ~hourly funding settlement over the observed span
    span_ms = max(last_t - first_t, 0)
    expected_in_span = int(round(span_ms / MS_PER_FUNDING)) + 1
    gap_pct = 0.0
    if expected_in_span > 0:
        gap_pct = max(0.0, (expected_in_span - n) / expected_in_span)
    # Tail-coverage: same blind spot as OHLC — a failed-soft truncation
    # can end the series months early while the observed span looks dense.
    tail_gap_ms = max(expected_end_ms - last_t, 0)
    incomplete_tail = tail_gap_ms > MS_PER_FUNDING * 3
    data_suspect = (
        (not monotonic)
        or (null_count > 0)
        or (gap_pct > GAP_FLAG_THRESHOLD)
        or incomplete_tail
    )
    result.update(
        {
            "monotonic": monotonic,
            "expected_count": expected_in_span,
            "gap_pct": round(gap_pct * 100, 3),
            "null_count": null_count,
            "first_date": iso(first_t),
            "last_date": iso(last_t),
            "short_history": short_history,
            "incomplete_tail": incomplete_tail,
            "tail_gap_hours": round(tail_gap_ms / MS_PER_HOUR, 1),
            "data_suspect": data_suspect,
        }
    )
    return result


def append_quality_log(entries: List[Dict[str, Any]]) -> None:
    QUALITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(QUALITY_LOG, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


# --------------------------------------------------------------------------
# Main backfill loop
# --------------------------------------------------------------------------

def load_universe_coins() -> List[str]:
    with open(UNIVERSE_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [n["coin"] for n in data.get("names", [])]


def backfill_coin(hl: HLNative, coin: str, t_now: int) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"coin": coin}
    quality_entries: List[Dict[str, Any]] = []

    # --- Daily candles: ~400d back -> now ---
    daily_start = t_now - DAILY_LOOKBACK_DAYS * MS_PER_DAY
    try:
        daily_candles = hl.candles(coin, "1d", daily_start, t_now)
    except Exception:
        print(f"[{coin}] daily candle fetch raised unexpectedly:", file=sys.stderr)
        traceback.print_exc()
        daily_candles = []
    # Drop a still-forming/partial last daily row BEFORE it's written or
    # validated — see _drop_forming_daily docstring / module docstring.
    daily_candles = _drop_forming_daily(daily_candles, t_now)
    daily_path = OHLC_DIR / f"{coin}_1d.csv"
    daily_total = write_ohlc_csv(daily_path, daily_candles)
    daily_q = validate_ohlc(coin, "1d", daily_candles, daily_start, t_now)
    quality_entries.append(daily_q)
    summary["n_daily"] = daily_total
    summary["daily_first"] = daily_q.get("first_date")
    summary["daily_last"] = daily_q.get("last_date")
    summary["daily_gap_pct"] = daily_q.get("gap_pct")
    summary["daily_suspect"] = daily_q.get("data_suspect")
    summary["daily_short_history"] = daily_q.get("short_history")

    # --- 1h candles: last 200d -> now ---
    hourly_start = t_now - HOURLY_LOOKBACK_DAYS * MS_PER_DAY
    try:
        hourly_candles = hl.candles(coin, "1h", hourly_start, t_now)
    except Exception:
        print(f"[{coin}] 1h candle fetch raised unexpectedly:", file=sys.stderr)
        traceback.print_exc()
        hourly_candles = []
    hourly_path = OHLC_DIR / f"{coin}_1h.csv"
    hourly_total = write_ohlc_csv(hourly_path, hourly_candles)
    hourly_q = validate_ohlc(coin, "1h", hourly_candles, hourly_start, t_now)
    quality_entries.append(hourly_q)
    summary["n_1h"] = hourly_total
    summary["hourly_first"] = hourly_q.get("first_date")
    summary["hourly_last"] = hourly_q.get("last_date")
    summary["hourly_gap_pct"] = hourly_q.get("gap_pct")
    summary["hourly_suspect"] = hourly_q.get("data_suspect")
    summary["hourly_short_history"] = hourly_q.get("short_history")

    # --- Funding history: last 200d -> now ---
    funding_start = t_now - FUNDING_LOOKBACK_DAYS * MS_PER_DAY
    try:
        funding_records = hl.funding_history(coin, funding_start, t_now)
    except Exception:
        print(f"[{coin}] funding fetch raised unexpectedly:", file=sys.stderr)
        traceback.print_exc()
        funding_records = []
    funding_path = FUNDING_DIR / f"{coin}.csv"
    funding_total = write_funding_csv(funding_path, funding_records)
    funding_q = validate_funding(coin, funding_records, funding_start, t_now)
    quality_entries.append(funding_q)
    summary["n_funding"] = funding_total
    summary["funding_first"] = funding_q.get("first_date")
    summary["funding_last"] = funding_q.get("last_date")
    summary["funding_suspect"] = funding_q.get("data_suspect")

    append_quality_log(quality_entries)
    return summary


def print_summary_table(summaries: List[Dict[str, Any]]) -> None:
    header = (
        f"{'coin':<10}{'#daily':>8}{'#1h':>7}{'#fund':>7}  "
        f"{'first_1h':<22}{'last_1h':<22}{'1h_gap%':>8}  suspect?"
    )
    print(header)
    print("-" * len(header))
    for s in summaries:
        suspect_flags = []
        if s.get("daily_suspect"):
            suspect_flags.append("daily")
        if s.get("hourly_suspect"):
            suspect_flags.append("1h")
        if s.get("funding_suspect"):
            suspect_flags.append("funding")
        short_flags = []
        if s.get("daily_short_history") or s.get("hourly_short_history"):
            short_flags.append("short-history")
        suspect_str = ",".join(suspect_flags) if suspect_flags else "-"
        if short_flags:
            suspect_str += f" ({','.join(short_flags)})"
        gap = s.get("hourly_gap_pct")
        gap_str = f"{gap:.2f}" if gap is not None else "n/a"
        print(
            f"{s['coin']:<10}{s.get('n_daily', 0):>8}{s.get('n_1h', 0):>7}"
            f"{s.get('n_funding', 0):>7}  "
            f"{str(s.get('hourly_first')):<22}{str(s.get('hourly_last')):<22}"
            f"{gap_str:>8}  {suspect_str}"
        )


def main() -> None:
    coins = load_universe_coins()
    print(f"Loaded {len(coins)} coins from {UNIVERSE_JSON}")
    hl = HLNative()
    t_now = now_ms()
    summaries: List[Dict[str, Any]] = []
    for i, coin in enumerate(coins, 1):
        print(f"[{i}/{len(coins)}] backfilling {coin} ...")
        try:
            s = backfill_coin(hl, coin, t_now)
        except Exception:
            print(f"[{coin}] backfill_coin raised unexpectedly:", file=sys.stderr)
            traceback.print_exc()
            s = {"coin": coin, "error": True}
        summaries.append(s)

    print()
    print("=" * 100)
    print("Long-Tail Alpha backfill — hygiene summary")
    print("=" * 100)
    print_summary_table(summaries)
    print()
    n_suspect = sum(
        1
        for s in summaries
        if s.get("daily_suspect") or s.get("hourly_suspect") or s.get("funding_suspect")
    )
    print(f"Coins with >=1 suspect series: {n_suspect}/{len(summaries)}")
    print(f"Quality log: {QUALITY_LOG}")


if __name__ == "__main__":
    main()
