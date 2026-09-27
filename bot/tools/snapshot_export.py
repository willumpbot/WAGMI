"""
Static snapshot exporter for the crazyonsol.online frontend.

Hits the local API server (bot/api_server.py, http://localhost:8000) for the core
endpoints the site reads, and writes one JSON file per endpoint into
web/public/data/<slug>.json. Those files are the CDN-hosted "last-known" fallback:
when the bot PC or the ngrok tunnel is offline, the frontend fetches these instead
of hanging on "Loading…" (see web/src/api.ts snapshotUrl / apiFetch fallback).

The slug mapping MUST stay in sync with pathToSnapshotSlug() in web/src/api.ts:
  strip query string -> strip leading "v1/" -> replace "/" with "-".
    /v1/summary                 -> summary.json
    /v1/trades/history?limit=50 -> trades-history.json
    /v1/trades/equity-curve     -> trades-equity-curve.json

Fail-soft per endpoint: a failed/empty fetch leaves the previous snapshot untouched,
never writing a broken file. Stdlib + requests only; zero contact with bot runtime.

Driven by its own Windows scheduled task ("WAGMI-Snapshot"):
  python tools/snapshot_export.py --once
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

API_BASE = os.environ.get("WAGMI_API_BASE", "http://localhost:8000")

# web/public/data relative to this file (bot/tools/snapshot_export.py -> ../../web/public/data)
_THIS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.abspath(os.path.join(_THIS, "..", "..", "web", "public", "data"))

# Endpoints the frontend reads. Order doesn't matter. Query strings are dropped from
# the slug (one canonical snapshot per endpoint) EXCEPT where the query distinguishes
# resources (see ohlcv, handled via _dynamic_endpoints). Heavy feeds are capped with
# ?limit= so committed snapshots stay reasonable.
ENDPOINTS = [
    # core (landing + dashboard)
    "/v1/summary",
    "/v1/trades/history?limit=50",
    "/v1/trades/equity-curve",
    "/v1/llm/market-view",
    "/v1/positions",
    "/v1/signals",
    "/v1/strategies",
    "/v1/agents/overview",
    # feeds / intelligence pages
    "/v1/llm/feed?limit=60",
    "/v1/reasoning/feed",
    "/v1/counterfactuals/resolved",
    "/v1/activity/feed",
    "/v1/sniper/recent",
    # agents
    "/v1/agents/debate/history",
    "/v1/agents/team/calibration",
    "/v1/agents/health",
    # thesis + performance + portfolio
    "/v1/thesis/list",
    "/v1/performance/metrics",
    "/v1/portfolio/allocation",
    "/v1/signals/funnel",
    "/v1/account",
    # backtest (results view; "run" is a live-API-only action)
    "/v1/backtest/results",
    "/v1/backtest/results/latest",
    # living courses
    "/v1/lessons?limit=24",
]


def path_to_slug(path: str) -> str:
    """Mirror of pathToSnapshotSlug() in web/src/api.ts."""
    p = path.split("?")[0].lstrip("/")
    if p.startswith("v1/"):
        p = p[len("v1/"):]
    p = p.rstrip("/")
    return p.replace("/", "-")


def export_once(out_dir: str, timeout: float = 10.0) -> int:
    os.makedirs(out_dir, exist_ok=True)
    ok = 0
    for path in ENDPOINTS:
        slug = path_to_slug(path)
        dest = os.path.join(out_dir, f"{slug}.json")
        try:
            r = requests.get(f"{API_BASE}{path}", timeout=timeout)
            r.raise_for_status()
            data = r.json()  # validate it's JSON before touching the file
        except Exception as e:
            print(f"  SKIP {path} -> {slug}.json ({type(e).__name__}: {e})")
            continue
        # Store the RAW payload so a snapshot response is byte-shape-identical to the
        # live API response — the frontend fallback consumes it with no special-casing.
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, dest)  # atomic swap; never leaves a half-written file
        ok += 1
        print(f"  OK   {path} -> {slug}.json")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Export API snapshots for the frontend fallback.")
    ap.add_argument("--once", action="store_true", help="Run a single export pass and exit.")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"Output dir (default: {DEFAULT_OUT})")
    ap.add_argument("--loop", type=int, default=0, help="Seconds between passes (0 = single pass).")
    args = ap.parse_args()

    print(f"Snapshot export: API={API_BASE} -> {args.out}")
    if args.loop and not args.once:
        while True:
            n = export_once(args.out)
            print(f"  wrote {n}/{len(ENDPOINTS)} snapshots @ {datetime.now(timezone.utc).isoformat()}")
            time.sleep(args.loop)
    else:
        n = export_once(args.out)
        print(f"Wrote {n}/{len(ENDPOINTS)} snapshots.")
        return 0 if n > 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
