"""Archive Hyperliquid 5-minute candles so studies aren't capped at HL's last-5000-bars (~17 days) window.

Each run fetches the recent 5m bars per coin and merges them into data/candles_5m/<COIN>.jsonl (one bar per line,
keyed by open time, append-only, deduplicated). Run from the hivemind cycle; cheap (one request per coin).
Started 2026-10-09 for the liquidation-magnet re-check (data/copilot/LIQ_MAGNET_RECHECK.md).
"""
import json
import time
from pathlib import Path

import hl

BOT = Path(__file__).resolve().parents[2]
DIR = BOT / "data" / "candles_5m"
COINS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"]


def _last_t(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", "ignore").strip().splitlines()
        return json.loads(tail[-1])["t"] if tail else 0
    except (OSError, ValueError, IndexError, KeyError):
        return 0


def run():
    DIR.mkdir(parents=True, exist_ok=True)
    now = int(time.time() * 1000)
    added = {}
    for coin in COINS:
        path = DIR / f"{coin}.jsonl"
        last = _last_t(path)
        start = max(last + 1, now - 17 * 86400 * 1000)
        try:
            bars = hl.candles(coin, "5m", start, now, ttl=60) or []
        except Exception:
            continue
        closed = [b for b in bars if b["t"] > last and b["t"] + 300000 <= now]
        with open(path, "a", encoding="utf-8") as f:
            for b in closed:
                f.write(json.dumps({"t": b["t"], "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
                                    "c": float(b["c"]), "v": float(b["v"])}) + "\n")
        added[coin] = len(closed)
    return added


if __name__ == "__main__":
    print(run())
