"""
Replay candle seeder — rescues historical windows the exchange chain can't serve.

Why: Hyperliquid's 1h candle depth only reaches back ~208 days (older `since`
is silently clamped), Bybit is geo-blocked (403), Kraken returns only the last
720 candles regardless of `since`. The 2025 campaign windows (C1/C3/C4) are
unreachable through the normal fetcher chain.

Fix (free data first): fetch the window's candles from Coinbase Exchange's
free public API (full multi-year history, no auth) and write them in the
DataFetcher DISK-CACHE format ({SYM}_{tf}_{days}d_{YYYYMMDD}.csv). The replay
harness copies these into the sandbox's data/cache/ BEFORE the run, so the
fetcher serves them as cache hits — zero fetcher/live-path code change.

FIDELITY CAVEAT (must be disclosed in reports): Coinbase SPOT candles are a
proxy for Hyperliquid PERP prices in these windows.

Usage:
    python tools/replay_seed_candles.py --end 2025-07-14 --days 11 \
        --symbols BTC,ETH,SOL --out data/replay/seed_C1
"""
import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CB_BASE = "https://api.exchange.coinbase.com"
PRODUCTS = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}

# tf -> (coinbase granularity seconds, candles to seed back from end, required)
TF_SPECS = {
    "1h": (3600, 320, True),
    "6h": (21600, 55, True),
    "daily": (86400, 66, True),
    "5m": (300, 3520, False),  # best-effort; engine tolerates missing 5m
}
MAX_PER_REQ = 300
REQ_SLEEP_S = 0.3


def _get(url: str, retries: int = 3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "wagmi-replay-seeder/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001 — retry any transient failure
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"coinbase fetch failed after {retries} tries: {last_err}")


def fetch_candles(product: str, granularity: int, start: datetime,
                  end: datetime) -> list:
    """Fetch [time_s, low, high, open, close, volume] rows, paged, ascending."""
    rows = {}
    cursor = start
    step = timedelta(seconds=granularity * MAX_PER_REQ)
    while cursor < end:
        chunk_end = min(cursor + step, end)
        url = (f"{CB_BASE}/products/{product}/candles"
               f"?granularity={granularity}"
               f"&start={cursor.strftime('%Y-%m-%dT%H:%M:%SZ')}"
               f"&end={chunk_end.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        for r in _get(url):
            rows[int(r[0])] = r
        cursor = chunk_end
        time.sleep(REQ_SLEEP_S)
    return [rows[k] for k in sorted(rows)]


def seed_window(end_date: str, days: int, symbols: list, out_dir: Path) -> bool:
    """Write disk-cache CSVs for every symbol/timeframe. True if all
    required timeframes were served for all symbols."""
    out_dir.mkdir(parents=True, exist_ok=True)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_tag = end_dt.strftime("%Y%m%d")
    ok = True

    for sym in symbols:
        product = PRODUCTS.get(sym)
        if not product:
            print(f"[SEED] {sym}: no Coinbase product mapping — skipped")
            ok = False
            continue
        for tf, (gran, n_candles, required) in TF_SPECS.items():
            start_dt = end_dt - timedelta(seconds=gran * n_candles)
            try:
                rows = fetch_candles(product, gran, start_dt, end_dt)
            except RuntimeError as e:
                print(f"[SEED] {sym}/{tf}: {e}")
                rows = []
            min_rows = int(n_candles * 0.6)
            if len(rows) < min_rows:
                print(f"[SEED] {sym}/{tf}: only {len(rows)} candles "
                      f"(< {min_rows}) — {'REQUIRED, window unserved' if required else 'optional, skipped'}")
                if required:
                    ok = False
                continue
            path = out_dir / f"{sym}_{tf}_{days}d_{end_tag}.csv"
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["open", "high", "low", "close", "volume", "time"])
                for ts, low, high, opn, close, vol in rows:
                    t = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    w.writerow([opn, high, low, close, vol,
                                t.strftime("%Y-%m-%d %H:%M:%S+00:00")])
            print(f"[SEED] {sym}/{tf}: {len(rows)} candles -> {path.name}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed replay candle disk cache "
                                             "from Coinbase spot (free)")
    ap.add_argument("--end", required=True, help="window end YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=11,
                    help="fetch depth used by the engine (cache filename key)")
    ap.add_argument("--symbols", default="BTC,ETH,SOL")
    ap.add_argument("--out", required=True, help="output directory for CSVs")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    ok = seed_window(args.end, args.days, symbols, Path(args.out))
    print(f"[SEED] {'COMPLETE' if ok else 'INCOMPLETE (required tf missing)'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
