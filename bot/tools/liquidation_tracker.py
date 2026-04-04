"""Liquidation Level Tracker — estimates liq clusters from OI + leverage tiers.
Tracks drift, funding bias, and "magnetic zones" (price sweeps through nearby clusters).
Writes to data/liquidation_levels.jsonl every 5 minutes.
"""
import json, time, os, sys, logging
from datetime import datetime, timezone
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None
import ccxt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("liq_tracker")

BASE = os.path.dirname(os.path.abspath(__file__))
OI_FILE = os.path.join(BASE, "..", "data", "funding_oi_history.jsonl")
OUT_FILE = os.path.join(BASE, "..", "data", "liquidation_levels.jsonl")
INTERVAL = 300  # 5 min

SYMBOLS = ["BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC", "HYPE/USDC:USDC"]

# Leverage tiers: leverage -> base weight (fraction of OI at that tier)
LEV_DIST = {2: 0.15, 3: 0.15, 5: 0.25, 10: 0.20, 20: 0.15, 50: 0.10}

# Track previous OI per symbol for delta detection
prev_oi: dict[str, float] = {}
# Track previous levels for drift detection
prev_levels: dict[str, dict] = {}
# Magnetic zone state: symbol -> {side, lev, entered_at}
magnetic_active: dict[str, dict] = {}


def load_recent_oi(symbol: str, lookback: int = 20) -> list[dict]:
    """Load last N OI records for a symbol from funding_oi_history."""
    if not os.path.exists(OI_FILE):
        return []
    records = []
    for line in open(OI_FILE):
        try:
            r = json.loads(line)
            if r.get("symbol") == symbol:
                records.append(r)
        except json.JSONDecodeError:
            continue
    return records[-lookback:]


def oi_weight_modifier(symbol: str) -> tuple[float, str]:
    """OI delta -> weight modifier. Rising OI = positions building = denser clusters."""
    records = load_recent_oi(symbol, 10)
    if len(records) < 2:
        return 1.0, "stable"
    first_oi, last_oi = records[0].get("open_interest", 0), records[-1].get("open_interest", 0)
    if first_oi <= 0:
        return 1.0, "stable"
    d = (last_oi - first_oi) / first_oi * 100
    if d > 2:   return 1.3, f"building(+{d:.1f}%)"
    elif d < -2: return 0.7, f"closing({d:.1f}%)"
    return 1.0, f"stable({d:+.1f}%)"


def funding_bias(symbol: str) -> str:
    """Positive funding = longs pay shorts = long-heavy market."""
    records = load_recent_oi(symbol, 5)
    if not records:
        return "neutral"
    avg = sum(r.get("funding_rate", 0) for r in records) / len(records)
    if avg > 5e-6:  return "long_heavy"
    if avg < -5e-6: return "short_heavy"
    return "neutral"


def estimate_levels(symbol: str, price: float) -> dict:
    """Estimate liquidation clusters weighted by OI trends + funding bias."""
    oi_mult, oi_trend = oi_weight_modifier(symbol)
    bias = funding_bias(symbol)

    long_liqs, short_liqs = [], []
    for lev, base_w in LEV_DIST.items():
        # Adjust weights: if longs are heavy, long liqs are denser
        lw = base_w * (oi_mult if bias in ("long_heavy", "neutral") else base_w)
        sw = base_w * (oi_mult if bias in ("short_heavy", "neutral") else base_w)

        # Maintenance margin ~90% of initial margin
        long_liq = round(price * (1 - 0.9 / lev), 4)
        short_liq = round(price * (1 + 0.9 / lev), 4)

        long_liqs.append({
            "lev": lev, "price": long_liq, "weight": round(lw, 3),
            "dist_pct": round((price - long_liq) / price * 100, 2),
        })
        short_liqs.append({
            "lev": lev, "price": short_liq, "weight": round(sw, 3),
            "dist_pct": round((short_liq - price) / price * 100, 2),
        })

    return {
        "long_liqs": sorted(long_liqs, key=lambda x: x["dist_pct"]),
        "short_liqs": sorted(short_liqs, key=lambda x: x["dist_pct"]),
        "oi_trend": oi_trend,
        "funding_bias": bias,
    }


def detect_drift(symbol: str, levels: dict) -> str | None:
    """Compare current vs previous levels — detect if clusters are tightening."""
    old = prev_levels.get(symbol)
    if not old:
        return None
    old_nearest_l = old["long_liqs"][0]["dist_pct"]
    new_nearest_l = levels["long_liqs"][0]["dist_pct"]
    old_nearest_s = old["short_liqs"][0]["dist_pct"]
    new_nearest_s = levels["short_liqs"][0]["dist_pct"]
    if new_nearest_l < old_nearest_l and new_nearest_s < old_nearest_s:
        return "TIGHTENING — both sides closer"
    if new_nearest_l < old_nearest_l - 0.5:
        return "LONG_LIQS_CLOSER"
    if new_nearest_s < old_nearest_s - 0.5:
        return "SHORT_LIQS_CLOSER"
    return None


def check_magnetic_zones(symbol: str, price: float, levels: dict) -> list[str]:
    """Magnetic zone: once price enters <1% of a heavy cluster, it tends to sweep."""
    alerts = []
    for side, liqs in [("long", levels["long_liqs"]), ("short", levels["short_liqs"])]:
        # Only check high-weight clusters (5x-20x = most OI)
        heavy = [l for l in liqs if l["weight"] >= 0.15 and l["lev"] <= 20]
        for lv in heavy:
            key = f"{symbol}_{side}_{lv['lev']}x"
            if lv["dist_pct"] < 1.0:
                if key not in magnetic_active:
                    magnetic_active[key] = {"ts": time.time(), "entry_price": price}
                    alerts.append(
                        f"MAGNETIC ZONE {symbol} {side.upper()} {lv['lev']}x "
                        f"@ ${lv['price']:.2f} ({lv['dist_pct']:.1f}% away) — "
                        f"sweep likely"
                    )
            elif key in magnetic_active:
                del magnetic_active[key]  # exited zone
    return alerts


def run():
    ex = ccxt.hyperliquid({"enableRateLimit": True, "timeout": 15000})
    key, secret = os.getenv("HL_API_KEY", ""), os.getenv("HL_API_SECRET", "")
    if key and secret:
        ex.apiKey, ex.secret, ex.walletAddress = key, secret, key
    ex.load_markets()

    logger.info(f"Liquidation tracker started — {len(SYMBOLS)} symbols, {INTERVAL}s interval")

    while True:
        try:
            for sym in SYMBOLS:
                name = sym.split("/")[0]
                ticker = ex.fetch_ticker(sym)
                price = ticker["last"]

                levels = estimate_levels(name, price)
                drift = detect_drift(name, levels)
                mag_alerts = check_magnetic_zones(name, price, levels)

                nearest_l = levels["long_liqs"][0]
                nearest_s = levels["short_liqs"][0]

                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "sym": name, "price": price,
                    "nearest_long": nearest_l, "nearest_short": nearest_s,
                    "oi_trend": levels["oi_trend"], "bias": levels["funding_bias"],
                    "drift": drift, "magnetic": len(mag_alerts) > 0,
                }
                with open(OUT_FILE, "a") as f:
                    f.write(json.dumps(record) + "\n")

                # Logging
                parts = [f"{name} ${price:.2f}"]
                parts.append(f"L-liq ${nearest_l['price']:.2f}({nearest_l['dist_pct']:.1f}%dn)")
                parts.append(f"S-liq ${nearest_s['price']:.2f}({nearest_s['dist_pct']:.1f}%up)")
                parts.append(f"OI:{levels['oi_trend']} bias:{levels['funding_bias']}")
                if drift:
                    parts.append(f"DRIFT:{drift}")
                logger.info(" | ".join(parts))

                for a in mag_alerts:
                    logger.warning(a)
                if nearest_l["dist_pct"] < 2.0:
                    logger.warning(f"{name} NEAR LONG LIQ: {nearest_l['lev']}x @ ${nearest_l['price']:.2f} ({nearest_l['dist_pct']:.1f}%)")
                if nearest_s["dist_pct"] < 2.0:
                    logger.warning(f"{name} NEAR SHORT LIQ: {nearest_s['lev']}x @ ${nearest_s['price']:.2f} ({nearest_s['dist_pct']:.1f}%)")

                prev_levels[name] = levels

            time.sleep(INTERVAL)
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    run()
