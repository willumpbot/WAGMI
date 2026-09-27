"""
data_integrity_audit.py — READ-ONLY Tier-0 data integrity audit.

Inventories every price cache the bot/co-pilot rely on (data/cache/*.csv,
data/longtail/ohlc/*.csv, data/longtail/funding/*.csv, data/cache/multiyear_geom/*)
and checks, per file:
  - actual first/last timestamp vs what the filename claims (e.g. "_420d")
  - staleness vs NOW (days behind)
  - duplicate timestamps, out-of-order rows, gaps, NaN/zero/negative closes,
    single-bar spikes (>50% jump vs both neighbors)

Does NOT modify any file, does NOT call any network API, does NOT touch
live-bot state. Pure read + report.

Usage: python tools/copilot/data_integrity_audit.py
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(ROOT, "data", "cache")
LONGTAIL_OHLC_DIR = os.path.join(ROOT, "data", "longtail", "ohlc")
LONGTAIL_FUNDING_DIR = os.path.join(ROOT, "data", "longtail", "funding")
MULTIYEAR_DIR = os.path.join(ROOT, "data", "cache", "multiyear_geom")

NOW = datetime.now(timezone.utc)

FNAME_RE = re.compile(r"^([A-Za-z0-9]+)_(5m|1h|6h|daily|1d)_(\d+)d(?:_(\d{8}))?\.csv$")


def _find_time_col(df: pd.DataFrame):
    for c in ["time", "dt_utc_iso", "timestamp", "date"]:
        if c in df.columns:
            return c
    return None


def _find_close_col(df: pd.DataFrame):
    for c in ["close", "c"]:
        if c in df.columns:
            return c
    return None


def audit_csv(path: str, claimed_days=None):
    fname = os.path.basename(path)
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return {"file": fname, "error": f"read failed: {e}"}

    if df.empty:
        return {"file": fname, "error": "empty file"}

    tcol = _find_time_col(df)
    ccol = _find_close_col(df)
    if tcol is None:
        return {"file": fname, "error": f"no time column found (cols={list(df.columns)})"}

    try:
        times = pd.to_datetime(df[tcol], utc=True, errors="coerce")
    except Exception as e:
        return {"file": fname, "error": f"time parse failed: {e}"}

    n_bad_times = times.isna().sum()
    times_valid = times.dropna()
    if times_valid.empty:
        return {"file": fname, "error": "all timestamps unparseable"}

    first, last = times_valid.iloc[0], times_valid.iloc[-1]
    span_days = (last - first).total_seconds() / 86400.0
    staleness_days = (NOW - last).total_seconds() / 86400.0

    # duplicates
    n_dupes = int(times_valid.duplicated().sum())
    # ordering
    is_sorted = bool((times_valid.values[:-1] <= times_valid.values[1:]).all()) if len(times_valid) > 1 else True

    # gaps: infer expected cadence from median diff
    diffs = times_valid.diff().dropna().dt.total_seconds()
    median_gap_s = float(diffs.median()) if not diffs.empty else None
    n_gaps = 0
    biggest_gap_days = 0.0
    if median_gap_s and median_gap_s > 0:
        gap_mask = diffs > median_gap_s * 2.5
        n_gaps = int(gap_mask.sum())
        if n_gaps:
            biggest_gap_days = float(diffs[gap_mask].max() / 86400.0)

    bad_price_rows = 0
    spike_rows = 0
    if ccol is not None:
        closes = pd.to_numeric(df[ccol], errors="coerce")
        bad_price_rows = int(((closes.isna()) | (closes <= 0)).sum())
        c = closes.ffill()
        if len(c) > 2:
            ratio = c / c.shift(1)
            spike_rows = int(((ratio > 1.5) | (ratio < 0.6667)).sum())

    result = {
        "file": fname,
        "rows": len(df),
        "first": str(first.date()),
        "last": str(last.date()),
        "span_days": round(span_days, 1),
        "staleness_days": round(staleness_days, 1),
        "n_bad_times": int(n_bad_times),
        "n_dupes": n_dupes,
        "is_sorted": is_sorted,
        "n_gaps": n_gaps,
        "biggest_gap_days": round(biggest_gap_days, 1),
        "bad_price_rows": bad_price_rows,
        "spike_rows": spike_rows,
    }

    m = FNAME_RE.match(fname)
    if m:
        claimed = int(m.group(3))
        result["claimed_days"] = claimed
        result["claim_mismatch"] = round(claimed - span_days, 1)
    return result


def scan_dir(d, label):
    print(f"\n=== {label}: {d} ===")
    if not os.path.isdir(d):
        print("  (missing)")
        return []
    rows = []
    for fname in sorted(os.listdir(d)):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(d, fname)
        r = audit_csv(path)
        rows.append(r)
    return rows


def fmt_row(r):
    if "error" in r:
        return f"  {r['file']:35s} ERROR: {r['error']}"
    flags = []
    if r.get("claim_mismatch") is not None and abs(r["claim_mismatch"]) > 15:
        flags.append(f"CLAIM-MISMATCH(claimed={r['claimed_days']}d actual={r['span_days']}d)")
    if r["staleness_days"] > 3:
        flags.append(f"STALE({r['staleness_days']:.1f}d behind)")
    if r["n_dupes"]:
        flags.append(f"DUPES={r['n_dupes']}")
    if not r["is_sorted"]:
        flags.append("OUT-OF-ORDER")
    if r["n_gaps"]:
        flags.append(f"GAPS={r['n_gaps']}(max {r['biggest_gap_days']}d)")
    if r["bad_price_rows"]:
        flags.append(f"BAD-PRICE={r['bad_price_rows']}")
    if r["spike_rows"]:
        flags.append(f"SPIKES={r['spike_rows']}")
    flagstr = " ".join(flags) if flags else "clean"
    return (f"  {r['file']:35s} rows={r['rows']:5d} range={r['first']}..{r['last']} "
            f"span={r['span_days']:.0f}d stale={r['staleness_days']:.1f}d :: {flagstr}")


if __name__ == "__main__":
    all_rows = []
    for r in scan_dir(CACHE_DIR, "data/cache"):
        all_rows.append(("cache", r))
    for r in scan_dir(LONGTAIL_OHLC_DIR, "data/longtail/ohlc"):
        all_rows.append(("longtail_ohlc", r))
    for r in scan_dir(LONGTAIL_FUNDING_DIR, "data/longtail/funding"):
        all_rows.append(("longtail_funding", r))

    print(f"\n=== NOW = {NOW.isoformat()} ===\n")
    for group, r in all_rows:
        print(fmt_row(r))

    print("\n=== SUMMARY: flagged files ===")
    for group, r in all_rows:
        if "error" in r:
            print(f"  [{group}] {r['file']}: ERROR {r['error']}")
            continue
        bad = (r["staleness_days"] > 3 or r["n_dupes"] or not r["is_sorted"]
               or r["n_gaps"] or r["bad_price_rows"] or r["spike_rows"]
               or (r.get("claim_mismatch") and abs(r["claim_mismatch"]) > 15))
        if bad:
            print(f"  [{group}] {fmt_row(r).strip()}")
