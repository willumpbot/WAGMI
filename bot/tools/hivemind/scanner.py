"""Swing scanner: the top ~60 Hyperliquid perps by volume, every hivemind cycle, flagged for the setups our
evidence actually supports (and honestly labelled where it doesn't).

Per coin, from free HL data (daily candles + asset contexts): expected move tomorrow (the HAR model the
hivemind uses, volforecast.py), trend (20 vs 50-day average), distance to the 50-day average and the 20-day
range in expected-move units, funding, open interest, volume surge, and a rough safe leverage (liquidation beyond
the coin's own 99th-percentile 1-day adverse move over the last year, divided by 1.5; capped at HL's max).

Flag evidence levels:
  tested   - backed by an out-of-sample test (LEVELS.md, VOL forecast walk-forward)
  context  - useful to know, no tested directional edge
Writes data/hivemind/scan.json.
"""
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import hl
import volforecast

BOT = Path(__file__).resolve().parents[2]
OUT = BOT / "data" / "hivemind" / "scan.json"
TOP_N = 60

FLAGS = {
    "ma50_pullback": ("50d avg pullback", "tested",
                      "Price is above the 50-day average and within half an expected daily move of it. From above, "
                      "the 50-day average held more often than a random line (LEVELS.md, 2,955 touches)."),
    "on_20d_low": ("On the 20d low", "tested",
                   "Within half an expected move above the 20-day low. That low breaks MORE often than chance and "
                   "keeps going (LEVELS.md): a breakdown watch, not a bounce buy."),
    "vol_expanding": ("Moves getting bigger", "tested",
                      "Recent 5-day volatility is well above its 22-day level. Move size is forecastable (beat the "
                      "naive forecast 22/22 periods): expect bigger days, size down."),
    "funding_hot": ("Longs paying a lot", "context", "Funding in the top of the scanned coins: longs are crowded. "
                    "Crowding alone has not predicted direction in our tests."),
    "funding_cold": ("Shorts paying", "context", "Negative funding: shorts are paying longs. Context only."),
    "volume_surge": ("Volume surge", "context", "24h volume over 2.5x its 20-day average. Attention, not direction."),
    "squeeze": ("Tight range", "context", "The 20-day range is under 4 expected daily moves wide: coiled. "
                "Breakout direction is not predictable from this."),
    "above_20d_high": ("Above 20d high", "context", "Trading above the 20-day high. In testing the 20-day high "
                       "meant nothing either way."),
}


def _ema(v, n):
    k, e, out = 2 / (n + 1), None, []
    for x in v:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def scan_coin(name, ctx, max_lev, now_ms):
    raw = hl.candles(name, "1d", now_ms - 400 * 864e5, now_ms, ttl=600)
    if not raw or len(raw) < 60:
        return None
    day_ms = 864e5
    closed = [b for b in raw if b["t"] + day_ms <= now_ms]
    o = [float(b["o"]) for b in closed]
    h = [float(b["h"]) for b in closed]
    l = [float(b["l"]) for b in closed]
    c = [float(b["c"]) for b in closed]
    vol_usd = [float(b["v"]) * float(b["c"]) for b in closed]
    px = float(ctx.get("markPx") or c[-1])
    prev = float(ctx.get("prevDayPx") or 0) or c[-1]
    fc = volforecast.forecast(c) or {}
    em = fc.get("next_day_move_pct")
    e20, e50 = _ema(c, 20), _ema(c, 50)
    hi20, lo20 = max(h[-20:]), min(l[-20:])
    adv_long = [(o[i] - l[i]) / o[i] * 100 for i in range(max(0, len(o) - 365), len(o))]
    adv_short = [(h[i] - o[i]) / o[i] * 100 for i in range(max(0, len(o) - 365), len(o))]
    p99l, p99s = _pct(adv_long, 0.99), _pct(adv_short, 0.99)
    lev = lambda p: round(min(max_lev, 100 / (p * 1.5)), 1) if p else None
    d50 = (px / e50[-1] - 1) * 100
    funding = float(ctx.get("funding") or 0)
    vol24 = float(ctx.get("dayNtlVlm") or 0)
    avg20 = statistics.mean(vol_usd[-20:]) if vol_usd[-20:] else 0
    r = {"coin": name, "px": px, "chg_24h": round((px / prev - 1) * 100, 2),
         "ret_7d": round((px / c[-7] - 1) * 100, 2) if len(c) >= 7 else None,
         "exp_move": em, "rv5": fc.get("rv5"), "rv22": fc.get("rv22"),
         "trend_up": e20[-1] > e50[-1], "ema50": e50[-1], "d50_pct": round(d50, 2),
         "d50_moves": round(d50 / em, 2) if em else None,
         "hi20": hi20, "lo20": lo20, "range_pos": round((px - lo20) / (hi20 - lo20), 3) if hi20 > lo20 else None,
         "range_moves": round((hi20 / lo20 - 1) * 100 / em, 1) if em else None,
         "funding_h": funding, "oi_usd": round(float(ctx.get("openInterest") or 0) * px),
         "vol24_usd": round(vol24), "vol_ratio": round(vol24 / avg20, 2) if avg20 else None,
         "safe_lev_long": lev(p99l), "safe_lev_short": lev(p99s), "max_lev": max_lev,
         "spark": [round(x, 8) for x in c[-30:]] + [px]}
    f = []
    if em:
        if 0 <= d50 <= 0.5 * em:
            f.append("ma50_pullback")
        if lo20 <= px and (px / lo20 - 1) * 100 <= 0.5 * em:
            f.append("on_20d_low")
        if r["range_moves"] is not None and r["range_moves"] < 4:
            f.append("squeeze")
    if fc.get("rv5") and fc.get("rv22") and fc["rv5"] > 1.4 * fc["rv22"]:
        f.append("vol_expanding")
    if funding < 0:
        f.append("funding_cold")
    if r["vol_ratio"] and r["vol_ratio"] > 2.5:
        f.append("volume_surge")
    if px > hi20:
        f.append("above_20d_high")
    r["flags"] = f
    return r


def run():
    meta, ctxs = hl.post({"type": "metaAndAssetCtxs"}, ttl=60)
    uni = []
    for u, cx in zip(meta["universe"], ctxs):
        if u.get("isDelisted"):
            continue
        uni.append((u["name"], cx, int(u.get("maxLeverage") or 3), float(cx.get("dayNtlVlm") or 0)))
    uni.sort(key=lambda x: -x[3])
    now_ms = int(time.time() * 1000)
    rows, errors = [], 0
    for name, cx, ml, _ in uni[:TOP_N]:
        try:
            r = scan_coin(name, cx, ml, now_ms)
            if r:
                rows.append(r)
        except Exception:
            errors += 1
    hot = sorted((r["funding_h"] for r in rows), reverse=True)
    cut = hot[max(0, len(hot) // 10 - 1)] if hot else None
    for r in rows:
        if cut is not None and r["funding_h"] >= cut and r["funding_h"] > 1.25e-5:
            r["flags"].append("funding_hot")
        r["n_tested"] = sum(FLAGS[k][1] == "tested" for k in r["flags"])
    rows.sort(key=lambda r: (-r["n_tested"], -len(r["flags"]), -r["vol24_usd"]))
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n": len(rows), "errors": errors,
           "flags": {k: {"label": v[0], "evidence": v[1], "why": v[2]} for k, v in FLAGS.items()}, "coins": rows}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(OUT)
    return out


if __name__ == "__main__":
    t = time.time()
    o = run()
    print(f"{o['n']} coins in {time.time() - t:.0f}s, {o['errors']} errors")
    for r in o["coins"][:15]:
        print(f"{r['coin']:>8} {r['px']:>12.6g} em±{r['exp_move']} d50 {r['d50_moves']}m lev {r['safe_lev_long']}/{r['safe_lev_short']} {r['flags']}")
