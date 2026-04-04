"""
Funding Rate & Open Interest Collector for Hyperliquid.
Runs standalone alongside the bot, collecting time-series data every 15 minutes.
Hourly summary with anomaly detection. Scans all symbols for extreme funding.
"""

import json, time, os, sys
from datetime import datetime, timezone

# Force unbuffered output for logging
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

import ccxt

SYMBOLS = ["BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC", "HYPE/USDC:USDC"]
SHORT_NAMES = {s: s.split("/")[0] for s in SYMBOLS}
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "funding_oi_history.jsonl")
INTERVAL = 15 * 60  # 15 minutes
EXTREME_FUNDING = 0.0001  # |rate| > 0.01%/hr flagged

def init_exchange():
    hl_config = {"enableRateLimit": True, "timeout": 15000}
    key = os.getenv("HL_API_KEY", "")
    secret = os.getenv("HL_API_SECRET", "")
    if key and secret:
        hl_config["apiKey"] = key
        hl_config["secret"] = secret
        hl_config["walletAddress"] = key
    ex = ccxt.hyperliquid(hl_config)
    ex.load_markets()
    return ex

def collect_tick(ex):
    """Fetch funding, OI, price for tracked symbols. Returns list of records."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    records = []
    for sym in SYMBOLS:
        try:
            funding = ex.fetch_funding_rate(sym)
            oi = ex.fetch_open_interest(sym)
            ticker = ex.fetch_ticker(sym)
            info = oi.get("info") or {}
            oi_base = float(oi.get("openInterestAmount", 0) or 0)
            vol_24h = float(info.get("dayNtlVlm", 0) or 0)
            premium = float(info.get("premium", 0) or 0)
            mark = float(info.get("markPx", 0) or 0)
            price = ticker.get("last", 0) or mark
            oi_val = oi_base * price  # convert to notional USD
            rec = {
                "timestamp": ts,
                "symbol": SHORT_NAMES[sym],
                "funding_rate": funding.get("fundingRate", 0),
                "open_interest": round(oi_val, 0),
                "premium": premium,
                "volume_24h": vol_24h,
                "price": price,
                "oi_volume_ratio": round(oi_val / vol_24h, 2) if vol_24h > 0 else 0,
            }
            records.append(rec)
        except Exception as e:
            print(f"[WARN] {SHORT_NAMES[sym]}: {e}")
    return records

def save_records(records):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

def scan_extreme_funding(ex):
    """Scan ALL Hyperliquid symbols for extreme funding rates."""
    try:
        rates = ex.fetch_funding_rates()
        extremes = []
        for sym, data in rates.items():
            rate = data.get("fundingRate") or 0
            if abs(rate) > EXTREME_FUNDING:
                extremes.append((sym.split("/")[0], rate, rate * 24 * 365 * 100))
        extremes.sort(key=lambda x: abs(x[1]), reverse=True)
        return extremes
    except Exception as e:
        print(f"[WARN] Funding scan failed: {e}")
        return []

def hourly_summary(history):
    """Print summary from last hour of data."""
    if len(history) < 4:
        return
    print(f"\n{'='*60}")
    print(f"  HOURLY SUMMARY — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    # Group last ~4 ticks (1 hour) by symbol
    recent = history[-16:]  # last 4 ticks * 4 symbols
    by_sym = {}
    for r in recent:
        by_sym.setdefault(r["symbol"], []).append(r)

    for sym, ticks in sorted(by_sym.items()):
        latest = ticks[-1]
        fr = latest["funding_rate"]
        fr_ann = fr * 24 * 365 * 100
        print(f"\n  {sym:>5}  price=${latest['price']:,.0f}  funding={fr:+.6f} ({fr_ann:+.1f}%/yr)")
        print(f"         OI={latest['open_interest']:,.0f}  premium={latest['premium']:+.6f}  OI/Vol={latest['oi_volume_ratio']:.1f}x")
        if len(ticks) >= 2:
            oi_old, oi_new = ticks[0]["open_interest"], ticks[-1]["open_interest"]
            if oi_old > 0:
                oi_chg = (oi_new - oi_old) / oi_old * 100
                arrow = "UP" if oi_chg > 0 else "DOWN"
                print(f"         OI 1h change: {oi_chg:+.2f}% ({arrow})")

        # Flag extremes
        flags = []
        if abs(fr) > EXTREME_FUNDING * 2:
            flags.append(f"EXTREME FUNDING {fr_ann:+.0f}%/yr")
        if abs(latest["premium"]) > 0.001:
            flags.append(f"PREMIUM DIVERGENCE {latest['premium']:+.4f}")
        if latest["oi_volume_ratio"] > 5:
            flags.append(f"HIGH OI/VOL RATIO {latest['oi_volume_ratio']:.1f}x")
        if flags:
            print(f"         *** {'  |  '.join(flags)} ***")

    print(f"\n{'='*60}\n")

def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Funding/OI Collector starting...")
    ex = init_exchange()
    print(f"  Tracking: {', '.join(SHORT_NAMES.values())}")
    print(f"  Interval: {INTERVAL//60}min | Data: {DATA_FILE}")

    history = []
    tick_count = 0

    while True:
        try:
            records = collect_tick(ex)
            save_records(records)
            history.extend(records)
            tick_count += 1

            # Brief per-tick status
            for r in records:
                fr = r["funding_rate"]
                print(f"  [{r['timestamp']}] {r['symbol']:>5} ${r['price']:>10,.1f}  "
                      f"FR={fr:+.6f}  OI={r['open_interest']:>14,.0f}  prem={r['premium']:+.6f}")

            # Hourly summary (every 4 ticks)
            if tick_count % 4 == 0:
                hourly_summary(history)
                extremes = scan_extreme_funding(ex)
                if extremes:
                    print(f"  EXTREME FUNDING SCAN ({len(extremes)} symbols):")
                    for sym, rate, ann in extremes[:10]:
                        direction = "SHORT-SQUEEZE" if rate > 0 else "LONG-SQUEEZE"
                        print(f"    {sym:>10}  {rate:+.6f}  ({ann:+.0f}%/yr)  [{direction}]")
                    print()

            # Keep last 2 hours in memory
            history = history[-(8 * len(SYMBOLS)):]

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
