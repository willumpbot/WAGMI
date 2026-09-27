"""Shared setup-identity dedup — the canonical fix for scanner re-log inflation.

The live scanner re-logs the SAME skipped/vetoed setup every scan cycle
(~10x-33x duplicate rows per real setup) into data/llm/counterfactual_resolved.jsonl,
data/llm/counterfactual_pending.jsonl, and data/missed_trades.jsonl. Any code that
counts rows or sums a field over the RAW rows without deduping by setup identity
inflates n and totals by that factor (verified 2026-07-30).

This is a byte-for-byte port of tools/resolve_missed_trades.py:_dedupe_setups
(same clustering rule: symbol+side, entry within 0.4%, timestamp within 3h, keep
the EARLIEST row per cluster) generalized with configurable field names, since
different logs key entry/timestamp differently (e.g. "entry_price" vs "entry",
"timestamp" vs "created_at"). Do not change the clustering constants (0.4% / 3h)
without re-verifying against tools/resolve_missed_trades.py — downstream
consumers assume identical semantics.
"""
from typing import Any, Dict, List, Sequence

ENTRY_TOL_PCT = 0.004  # 0.4%
TS_TOL_SECONDS = 3 * 3600  # 3h


def _parse_ts(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        try:
            import datetime as dt
            return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except Exception:
            return None


def is_same_setup(a: Dict[str, Any], b: Dict[str, Any], *,
                   entry_key: str = "entry_price", ts_key: str = "timestamp",
                   sym_key: str = "symbol", side_key: str = "side") -> bool:
    """True if two rows represent the SAME real-world setup per the canonical rule.

    Fail-neutral: any parse error (missing/unparseable symbol, side, entry, or
    timestamp) returns False rather than raising, so callers never crash.
    """
    try:
        sym_a = str(a.get(sym_key, "")).upper()
        sym_b = str(b.get(sym_key, "")).upper()
        if not sym_a or sym_a != sym_b:
            return False
        side_a = str(a.get(side_key, "")).upper()
        side_b = str(b.get(side_key, "")).upper()
        if side_a != side_b:
            return False
        entry_a = float(a.get(entry_key))
        entry_b = float(b.get(entry_key))
        if entry_b == 0:
            return False
        if abs(entry_a - entry_b) / entry_b > ENTRY_TOL_PCT:
            return False
        ts_a = _parse_ts(a.get(ts_key))
        ts_b = _parse_ts(b.get(ts_key))
        if ts_a is None or ts_b is None:
            return False
        if abs(ts_a - ts_b) > TS_TOL_SECONDS:
            return False
        return True
    except Exception:
        return False


def dedupe_setups(rows: Sequence[Dict[str, Any]], *, entry_key: str = "entry_price",
                   ts_key: str = "timestamp", sym_key: str = "symbol",
                   side_key: str = "side") -> List[Dict[str, Any]]:
    """Collapse duplicate re-logs of the SAME setup, keeping the EARLIEST row
    per cluster (closest to the real decision).

    Same setup = same symbol+side (case-insensitive), entry within 0.4%,
    timestamp within 3h — identical to tools/resolve_missed_trades.py's
    _dedupe_setups. Rows with a missing/unparseable symbol, side, entry, or
    timestamp cannot be clustered and are kept standalone (never dropped,
    never crash) — this is the one deliberate behavior difference from the
    original (which drops rows lacking a parseable entry_price).

    Fail-neutral: any unexpected error returns `rows` unchanged (as a list).
    """
    try:
        rows = list(rows)
    except Exception:
        return rows  # type: ignore[return-value]

    try:
        srt = sorted(rows, key=lambda r: _parse_ts(r.get(ts_key)) or 0)
    except Exception:
        return rows

    clusters: List[Dict[str, Any]] = []  # representative row per cluster
    out: List[Dict[str, Any]] = []
    try:
        for r in srt:
            # A row that fails is_same_setup's own parsing against itself
            # (missing entry/ts) can't be clustered — keep it standalone.
            try:
                float(r.get(entry_key))
                if _parse_ts(r.get(ts_key)) is None:
                    raise ValueError("unparseable timestamp")
            except Exception:
                out.append(r)
                continue

            matched = False
            for c in clusters:
                if is_same_setup(r, c, entry_key=entry_key, ts_key=ts_key,
                                  sym_key=sym_key, side_key=side_key):
                    matched = True
                    break
            if not matched:
                clusters.append(r)
                out.append(r)
        return out
    except Exception:
        return rows
