#!/usr/bin/env python
"""
Cache a MARKET-ATTENTION snapshot for the status dashboard.

WHY THIS EXISTS
---------------
The co-pilot already computes everything needed to notice "this coin is sitting
at the bottom of its 90-day range." It has been pushing that to Discord on a
schedule for weeks - 89 briefings, 9 genuine alerts, all confirmed delivered.
None of it was read, because the owner was working 12-hour shifts.

The dashboard (tools/dashboard.py) IS looked at - it is the one surface built for
that. But it only answers "is the machine healthy." It says nothing about the
market, so a coin sitting at a range low is invisible on the surface the owner
actually opens.

This job closes that gap. It computes range position for a small universe and
writes a tiny JSON the dashboard renders at the top. No new channel, no 11th
notification - the same measured facts, moved to where they will be seen.

DESIGN
------
- The dashboard rebuilds every MINUTE. It must never make network calls, so this
  runs on its own slower schedule (~30 min) and leaves a cached file behind.
- Reuses eye._structural_state_for_symbol (verified machinery: eye_deep candles,
  swings, cluster_levels). Nothing is reimplemented.
- Read-only. Touches no live bot state, no position files, no ledger.
- Fail-soft per symbol: one bad fetch never loses the whole snapshot, and a total
  failure leaves the previous file in place rather than writing a broken one.

HONESTY (the house rule)
------------------------
Range position is a MEASUREMENT, not a prediction. A coin at the bottom of its
range is not therefore going up. This file records where price sits inside a
window and nothing else - the directional read stays the owner's, exactly as
SIGNAL_SCORECARD.md requires.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_PATH = os.path.join("data", "copilot", "attention.json")

# Small, deliberate universe: the majors the bot actually trades plus the names
# the liquidation collector already tracks (so H3's three survivors are covered).
UNIVERSE: List[str] = [
    "BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR",
    "FARTCOIN", "kPEPE", "PENGU", "WIF", "kBONK", "POPCAT",
]

# Decile edges of the 90d range. Purely descriptive labels - never a signal.
LOW_EDGE = 15.0
HIGH_EDGE = 85.0


def _zone(range_pos: Optional[float]) -> str:
    """Descriptive band only. Deliberately NOT named 'buy'/'sell'/'accumulate' -
    range position has no validated directional edge on this data."""
    if range_pos is None:
        return "unknown"
    if range_pos <= LOW_EDGE:
        return "bottom of 90d range"
    if range_pos >= HIGH_EDGE:
        return "top of 90d range"
    return "mid-range"


def collect(universe: List[str]) -> Dict[str, object]:
    import eye  # local import so an import error cannot break the scheduler

    rows: List[dict] = []
    errors: List[str] = []
    for sym in universe:
        try:
            st = eye._structural_state_for_symbol(sym)
        except Exception as e:  # noqa: BLE001 - one symbol must never sink the run
            errors.append(f"{sym}: {type(e).__name__}: {e}")
            continue
        if not st:
            errors.append(f"{sym}: no candles")
            continue
        rows.append({
            "symbol": sym,
            "price": st.get("price"),
            "range_pos": st.get("range_pos"),
            "zone": _zone(st.get("range_pos")),
            "vol_ratio": st.get("vol_ratio"),
            "level": st.get("level"),
            "level_kind": st.get("level_kind"),
            "level_dist_pct": st.get("level_dist_pct"),
            "level_touch": st.get("level_touch"),
            "flags": st.get("flags") or [],
        })
        time.sleep(0.4)  # be polite to the public HL endpoint

    # Sort so the extremes surface first: furthest from mid-range at the top.
    def _extremity(r: dict) -> float:
        rp = r.get("range_pos")
        return abs((rp if rp is not None else 50.0) - 50.0)

    rows.sort(key=_extremity, reverse=True)

    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": 90,
        "low_edge_pct": LOW_EDGE,
        "high_edge_pct": HIGH_EDGE,
        "rows": rows,
        "errors": errors,
        "honesty": (
            "Range position is a MEASUREMENT of where price sits in its 90-day "
            "window, not a prediction. Nothing here says which way a coin goes."
        ),
    }


def write_atomic(path: str, payload: Dict[str, object]) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".attention.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    payload = collect(UNIVERSE)
    if not payload["rows"]:
        # Total failure: leave any previous snapshot alone rather than publishing
        # an empty one that the dashboard would render as "nothing to see."
        print("[attention] no rows collected; leaving existing snapshot in place",
              file=sys.stderr)
        for e in payload["errors"][:5]:
            print(f"[attention]   {e}", file=sys.stderr)
        return 1
    write_atomic(OUT_PATH, payload)
    n_edge = sum(1 for r in payload["rows"] if r["zone"] != "mid-range")
    print(f"[attention] wrote {OUT_PATH}: {len(payload['rows'])} symbols, "
          f"{n_edge} at a range edge, {len(payload['errors'])} error(s)")
    for r in payload["rows"]:
        if r["zone"] != "mid-range":
            rp = r["range_pos"]
            print(f"[attention]   {r['symbol']:<9} {rp:5.1f}%  {r['zone']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
