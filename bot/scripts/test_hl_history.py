"""
Diagnostic: test OHLCV data availability across exchanges and historical dates.
Runs outside the bot pipeline -- direct CCXT call only.

Usage: cd bot && python scripts/test_hl_history.py
"""
import time
import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import pandas as pd

print(f"ccxt version: {ccxt.__version__}")

TF = "1h"
LIMIT = 48  # 2 days of 1h candles

TEST_DATES = [
    ("2025-10-15", "Oct 2025"),
    ("2026-01-15", "Jan 2026"),
    ("2026-03-20", "Mar 2026 (crash start)"),
    ("2026-05-01", "May 2026"),
    ("now",        "Current (baseline)"),
]


def test_since(exchange, symbol, since_label, since_ms):
    try:
        candles = exchange.fetch_ohlcv(symbol, TF, since=since_ms, limit=LIMIT)
        if candles:
            first_ts = pd.Timestamp(candles[0][0], unit="ms", tz="UTC").date()
            last_ts  = pd.Timestamp(candles[-1][0], unit="ms", tz="UTC").date()
            print(f"  {since_label:30s} since={pd.Timestamp(since_ms, unit='ms').date()}  "
                  f"got {len(candles):3d} candles  [{first_ts} -> {last_ts}]")
        else:
            print(f"  {since_label:30s} since={pd.Timestamp(since_ms, unit='ms').date()}  EMPTY")
    except Exception as e:
        print(f"  {since_label:30s} ERROR: {e}")


def make_exchange(name):
    if name == "hyperliquid":
        ex = ccxt.hyperliquid({"enableRateLimit": True, "timeout": 15000})
        # Patch out spot market loading to avoid CCXT 4.5.37 NoneType bug
        ex.fetch_spot_markets = lambda params=None: []
        return ex, "BTC/USDC:USDC"
    elif name == "kraken":
        return ccxt.kraken({"enableRateLimit": True, "timeout": 15000}), "BTC/USDT"
    elif name == "bybit":
        return ccxt.bybit({"enableRateLimit": True, "timeout": 15000}), "BTC/USDT"
    raise ValueError(name)


def main():
    tf_ms = 3_600_000  # 1h in ms

    for ex_name in ("hyperliquid", "kraken", "bybit"):
        exchange, symbol = make_exchange(ex_name)
        print(f"\n{ex_name.upper()} -- {TF} x {LIMIT} candles on {symbol}\n")
        for date_str, label in TEST_DATES:
            if date_str == "now":
                since_ms = int(time.time() * 1000) - (LIMIT * tf_ms)
            else:
                end_ms = int(pd.Timestamp(date_str).timestamp() * 1000) + (5 * 24 * tf_ms)
                since_ms = end_ms - (LIMIT * tf_ms)
            test_since(exchange, symbol, label, since_ms)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
