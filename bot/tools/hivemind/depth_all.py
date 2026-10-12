"""L2 depth for EVERY Hyperliquid perp, every cycle (laptop Mission Y tier 1, item 2).

HL serves l2Book as a snapshot only, so book depth can never be backfilled; the bot's own collector covers 30 symbols.
Per coin per run: mid, spread (bps), bid/ask USD depth within 0.1% / 0.5% / 1% of mid, imbalance at each band, and how
far the 20 returned levels reach (a band beyond that reach is reported as None, never as a full band).
Appends one row per coin to data/hivemind/depth_all.jsonl (archived daily by laptop_sync as gz shards).
"""
import json
import time
from pathlib import Path

import hl

BOT = Path(__file__).resolve().parents[2]
OUT = BOT / "data" / "hivemind" / "depth_all.jsonl"
BANDS = (0.1, 0.5, 1.0)


def _levels(book):
    lv = book.get("levels") or [[], []]
    return [(float(x["px"]), float(x["sz"])) for x in lv[0]], [(float(x["px"]), float(x["sz"])) for x in lv[1]]


def _wide(coin, bids, asks, mid, ts):
    """Fill the 0.5%/1% bands from a book aggregated to 3 significant figures (the fine book's 20 levels often stop
    short of 1%). The fine book keeps the spread and the 0.1% band."""
    return _levels(hl.post({"type": "l2Book", "coin": coin, "nSigFigs": 3}, ttl=0) or {})


def _row(coin, book, ts):
    lv = book.get("levels") or [[], []]
    bids = [(float(x["px"]), float(x["sz"])) for x in lv[0]]
    asks = [(float(x["px"]), float(x["sz"])) for x in lv[1]]
    if not bids or not asks:
        return None
    mid = (bids[0][0] + asks[0][0]) / 2
    r = {"ts": ts, "coin": coin, "mid": mid, "spread_bps": round((asks[0][0] - bids[0][0]) / mid * 1e4, 3),
         "reach_bid_pct": round((mid - bids[-1][0]) / mid * 100, 3), "reach_ask_pct": round((asks[-1][0] - mid) / mid * 100, 3)}
    fine = (bids, asks, r["reach_bid_pct"], r["reach_ask_pct"])
    wide = None
    if r["reach_bid_pct"] < max(BANDS) or r["reach_ask_pct"] < max(BANDS):
        wb, wa = _wide(coin, bids, asks, mid, ts)
        if wb and wa:
            wide = (wb, wa, round((mid - wb[-1][0]) / mid * 100, 3), round((wa[-1][0] - mid) / mid * 100, 3))
            r["wide_reach_bid_pct"], r["wide_reach_ask_pct"] = wide[2], wide[3]
    for b in BANDS:
        # each band from the FINEST book that actually reaches it on both sides; None if neither does
        src = next((x for x in (fine, wide) if x and x[2] >= b and x[3] >= b), None)
        r[f"band_src_{b}"] = None if src is None else ("fine" if src is fine else "sig3")
        if src is None:
            r[f"bid_usd_{b}"] = r[f"ask_usd_{b}"] = r[f"imb_{b}"] = None
            continue
        lo, hi = mid * (1 - b / 100), mid * (1 + b / 100)
        bd = sum(p * q for p, q in src[0] if p >= lo)
        ad = sum(p * q for p, q in src[1] if p <= hi)
        r[f"bid_usd_{b}"], r[f"ask_usd_{b}"] = round(bd), round(ad)
        r[f"imb_{b}"] = round((bd - ad) / (bd + ad), 4) if bd + ad else None
    return r


def run():
    ts = int(time.time())
    try:
        uni = (hl.post({"type": "meta"}, ttl=3600) or {}).get("universe") or []
    except Exception:
        return 0
    coins = sorted(u["name"] for u in uni if not u.get("isDelisted"))   # live perps only (allMids also lists spot)
    rows = []
    for c in coins:
        try:
            r = _row(c, hl.post({"type": "l2Book", "coin": c}, ttl=0) or {}, ts)
        except Exception:
            continue
        if r:
            rows.append(r)
    if rows:
        with open(OUT, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + chr(10))
    return len(rows)


if __name__ == "__main__":
    t = time.time()
    print(run(), "coins", round(time.time() - t, 1), "s")
