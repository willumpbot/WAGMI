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

# Original 5 majors — unchanged, always collected (superset, never removed).
BASE_SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"]  # NEAR added 2026-10-08: traded but never collected

# Owner's meme-coin watchlist (co-pilot universe, HL-listed perps; see
# data/longtail/universe.json). Config constant — tune the list here.
# NOTE ccxt uppercases HL's "k"-prefixed thousand-denomination tickers
# (kPEPE -> KPEPE/USDC:USDC market symbol); _display_name() below restores the
# lowercase-k form used elsewhere (universe.json, tools/copilot/whats_moving.py)
# for the "symbol" field written to funding_oi_history.jsonl.
MEME_WATCHLIST = ["POPCAT", "WIF", "FARTCOIN", "PENGU", "kPEPE", "kBONK", "kSHIB", "PURR"]
# POPCAT 24h volume is thin (~$270K, verified live) — collected anyway per owner:
# thin-book funding/OI history is itself a risk instrument (how much can he exit).
# PURR added 2026-08-06: it's one of the owner's actively-eyed HL perps (verified
# live in HL meta universe) but had ZERO forward funding/OI/flow tracking - a gap
# in his own arena. Additive; the running collector picks it up on next reload so
# the live bot is untouched. Now his call on PURR can be resolved against real data.

# Small rotating slice of current market movers, pulled from
# tools/copilot/whats_moving.py's own state file, so a trending meme OUTSIDE the
# fixed watchlist above still gets captured. Best-effort / fail-soft only:
# whats_moving.py has no guaranteed collection cadence, so a missing/stale state
# file just yields zero rotating symbols this refresh — never a crash, never
# fewer than BASE_SYMBOLS + MEME_WATCHLIST.
ROTATING_TOP_N = 10
ROTATING_REFRESH_S = 3600  # re-pull movers hourly, not every 15-min tick
ROTATING_MAX_AGE_HOURS = 6.0
MOVING_STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "copilot", "moving_state.json")

_K_DENOM = {"kpepe", "kbonk", "kshib"}  # HL 1000x-denominated memes


def _ccxt_symbol(short_name):
    return f"{short_name.upper()}/USDC:USDC"


def _display_name(short_name):
    """Restore HL's lowercase-k convention (kPEPE, not ccxt's KPEPE) to match
    data/longtail/universe.json / whats_moving.py output."""
    if short_name.lower() in _K_DENOM:
        return "k" + short_name[1:]
    return short_name


def _static_symbol_names():
    seen, out = set(), []
    for s in BASE_SYMBOLS + MEME_WATCHLIST:
        key = s.upper()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _load_rotating_movers(exclude_upper):
    """Best-effort top-N by recent volume from whats_moving.py's state file.
    Fail-soft: any problem (missing file, bad json, stale data) returns []
    and never raises — this is a breadth nice-to-have, not load-bearing."""
    try:
        with open(MOVING_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
        history = state.get("history") or {}
        now = datetime.now(timezone.utc)
        fresh = []
        for sym, rec in history.items():
            if not isinstance(rec, dict) or sym.upper() in exclude_upper:
                continue
            last_ts = rec.get("last_ts")
            try:
                age_h = (now - datetime.fromisoformat(last_ts)).total_seconds() / 3600.0
            except (TypeError, ValueError):
                continue
            if age_h > ROTATING_MAX_AGE_HOURS:
                continue
            fresh.append((sym, rec.get("last_vol_usd") or 0.0))
        fresh.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in fresh[:ROTATING_TOP_N]]
    except Exception:
        return []


def resolve_symbols(ex, include_rotating=True):
    """Build the ccxt-symbol list + short-name map. Static majors+memes are
    always included (strict superset of the original 5); rotating movers are
    validated against ex.symbols when ex is available and dropped silently if
    unknown/unlisted — a bad mover name never breaks collection."""
    names = _static_symbol_names()
    if include_rotating:
        names += _load_rotating_movers({n.upper() for n in names})
    symbols, short = [], {}
    for n in names:
        csym = _ccxt_symbol(n)
        if csym in short:
            continue
        if ex is not None and csym not in ex.symbols:
            continue
        symbols.append(csym)
        short[csym] = _display_name(n)
    return symbols, short


# Initial (pre-exchange-validation) list: static majors+memes only, so module
# import / early logging has something sane before the first collect_tick()
# refresh validates + adds rotating movers against the live market list.
SYMBOLS, SHORT_NAMES = resolve_symbols(None, include_rotating=False)
_last_symbol_refresh_ts = 0.0

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
    global SYMBOLS, SHORT_NAMES, _last_symbol_refresh_ts
    now_ts = time.time()
    if now_ts - _last_symbol_refresh_ts > ROTATING_REFRESH_S:
        try:
            new_symbols, new_short = resolve_symbols(ex, include_rotating=True)
            if new_symbols:
                SYMBOLS, SHORT_NAMES = new_symbols, new_short
        except Exception as e:
            print(f"[WARN] symbol refresh failed, keeping existing list: {e}")
        _last_symbol_refresh_ts = now_ts

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
    recent = history[-(4 * max(len(SYMBOLS), 1)):]  # last 4 ticks * current symbol count
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
