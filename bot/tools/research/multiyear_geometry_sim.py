"""
Multi-year exit-geometry simulation (RQ_MULTIYEAR_SIM, 2026-07-01).

Question: does the RESTORED bread-and-butter exit geometry (MEDIUM 1.0/2.0 ATR
TP, SL 1.0 ATR, BE at 0.3R, profit-lock 0.3R at 0.6R, post-TP1 trail 1.5*ATR
tighten 0.80->0.65, floors 0.15/0.40/0.70) keep its win asymmetry across
2024 chop, the 2024-25 bull, and 2025-26 regimes?

This tests the GEOMETRY, not the entry. Entries are a deliberately dumb,
regime-neutral proxy: EMA20/50 cross on 1h closes (both directions), entered
at next candle open, with an ATR-liveness filter (ATR percentile rank over
trailing 200 bars >= 0.30). One position per symbol at a time. Fixed $100
risk per trade, leverage 1 -> PnL reported in R multiples.

Three exit configs on IDENTICAL entries:
  RESTORED  S3 geometry (BE 0.3R, lock 0.3R@0.6R) — the candidate
  CURRENT   live geometry (BE 1.2R, lock 0.3R@1.8R) — the de-fanged ratchet
  NAIVE     fixed SL 1.0 ATR / TP 2.0 ATR, no partial, no trail — control

Data: Binance spot 1h klines (BTC, ETH, SOL, XRP: 2024-01-01 .. now;
HYPE: Binance spot from listing, fallback Binance USDT-M futures, fallback
Hyperliquid candleSnapshot paginated). Cached in bot/data/cache/multiyear_geom.

Engine is a port of bot/tools/backtest_exit_geometry.py::simulate (which
reproduced golden-era mechanical exits to ~$2 on runners). Same fidelity
limits: 1h candles, intra-candle path green O->L->H->C / red O->H->L->C,
4 bps taker fee per leg, 72h hard hold limit, no funding, no slippage.

READ-ONLY on bot code. Standalone, no bot imports.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]           # bot/
CACHE = ROOT / "data" / "cache" / "multiyear_geom"
CACHE.mkdir(parents=True, exist_ok=True)

TAKER_FEE_BPS = 4
FEE_BUFFER_EXTRA = 0.001
MAX_HOLD_HOURS = 72.0
RISK_USD = 100.0

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "HYPE"]


# ── data ────────────────────────────────────────────────────────────────

def _get(url):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wagmi-research"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as ex:
            if ex.code in (400, 404):
                raise
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed: {url}")


def fetch_klines(symbol, base_url, interval, start_ms, end_ms):
    """Binance-style klines pagination (works for binance.vision and MEXC)."""
    out = []
    cur = start_ms
    while cur < end_ms:
        url = (f"{base_url}?symbol={symbol}&interval={interval}"
               f"&startTime={cur}&endTime={end_ms}&limit=1000")
        data = _get(url)
        if not data:
            cur += 1000 * 3_600_000     # skip empty window (pre-listing)
            if out:                     # gap after data started -> done
                break
            if cur >= end_ms:
                break
            continue
        for k in data:
            if not out or int(k[0]) > out[-1]["t"]:
                out.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                            "l": float(k[3]), "c": float(k[4])})
        nxt = int(data[-1][0]) + 3_600_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    return out


def fetch_hl(coin, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        body = json.dumps({"type": "candleSnapshot",
                           "req": {"coin": coin, "interval": "1h",
                                   "startTime": cur, "endTime": end_ms}}).encode()
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        if not data:
            break
        chunk = [{"t": int(c["t"]), "o": float(c["o"]), "h": float(c["h"]),
                  "l": float(c["l"]), "c": float(c["c"])} for c in data]
        out.extend(c for c in chunk if not out or c["t"] > out[-1]["t"])
        nxt = chunk[-1]["t"] + 3_600_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.3)
    return out


def get_candles(sym):
    cache = CACHE / f"{sym}_1h.json"
    if cache.exists():
        return json.loads(cache.read_text())
    start_ms = int(START.timestamp() * 1000)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    candles, source = [], None
    # api.binance.com is geo-blocked (HTTP 451) from this box; use the
    # official public market-data mirror data-api.binance.vision instead.
    # HYPE has no Binance spot/vision listing -> MEXC (binance-style API),
    # Hyperliquid last (only ~5000 candles ≈ 7 months of 1h depth).
    for name, fn in (
        ("binance-vision", lambda: fetch_klines(f"{sym}USDT",
            "https://data-api.binance.vision/api/v3/klines", "1h", start_ms, end_ms)),
        ("mexc", lambda: fetch_klines(f"{sym}USDT",
            "https://api.mexc.com/api/v3/klines", "60m", start_ms, end_ms)),
        ("hyperliquid", lambda: fetch_hl(sym, start_ms, end_ms)),
    ):
        try:
            candles = fn()
        except Exception as ex:  # noqa: BLE001
            print(f"  {sym}: {name} failed ({ex})", file=sys.stderr)
            candles = []
        if len(candles) > 1000:
            source = name
            break
    if not candles:
        return []
    print(f"  {sym}: {len(candles)} candles from {source} "
          f"({datetime.fromtimestamp(candles[0]['t']/1000, tz=timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(candles[-1]['t']/1000, tz=timezone.utc):%Y-%m-%d})")
    cache.write_text(json.dumps({"source": source, "candles": candles}))
    return {"source": source, "candles": candles}


# ── indicators ──────────────────────────────────────────────────────────

def ema(vals, n):
    k = 2 / (n + 1)
    out, e = [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def atr14(candles):
    out, prev_c, a = [], None, None
    for c in candles:
        tr = c["h"] - c["l"] if prev_c is None else max(
            c["h"] - c["l"], abs(c["h"] - prev_c), abs(c["l"] - prev_c))
        a = tr if a is None else (a * 13 + tr) / 14
        out.append(a)
        prev_c = c["c"]
    return out


def pct_rank(window, v):
    if not window:
        return 0.5
    return sum(1 for x in window if x <= v) / len(window)


# ── entry proxy ─────────────────────────────────────────────────────────

def gen_entries(candles):
    """EMA20/50 cross, both directions, ATR-liveness filter, entry next open."""
    closes = [c["c"] for c in candles]
    e20, e50, atrs = ema(closes, 20), ema(closes, 50), atr14(candles)
    entries = []
    for i in range(200, len(candles) - 1):
        d_prev = e20[i - 1] - e50[i - 1]
        d_now = e20[i] - e50[i]
        if d_prev == 0 or (d_prev > 0) == (d_now > 0) or d_now == 0:
            continue
        side = "LONG" if d_now > 0 else "SHORT"
        atr = atrs[i]
        if atr <= 0:
            continue
        if pct_rank(atrs[i - 200:i], atr) < 0.30:   # dead-market filter
            continue
        entry_px = candles[i + 1]["o"]
        if atr / entry_px < 0.0008:                 # sub-fee noise guard
            continue
        entries.append({"idx": i + 1, "side": side, "entry": entry_px, "atr": atr,
                        "t": candles[i + 1]["t"]})
    return entries


# ── exit engine (port of backtest_exit_geometry.simulate) ───────────────

@dataclass
class Cfg:
    name: str
    be_trigger: float
    lock_trigger: float
    lock_frac: float = 0.3
    trail_mult: float = 1.5
    tighten_start: float = 0.80
    tighten_end: float = 0.65
    floor_progress: float = 0.15
    floor_start: float = 0.40
    floor_max: float = 0.70
    tp1_close_pct: float = 0.50
    naive: bool = False


CFGS = [
    Cfg("RESTORED", 0.3, 0.6),
    Cfg("CURRENT", 1.2, 1.8),
    Cfg("NAIVE", 99, 99, naive=True),
]


import os
PATH_MODE = os.environ.get("PATH_MODE", "chrono")   # chrono | pessimistic


def candle_points(c, sgn=1):
    if PATH_MODE == "pessimistic":
        # adverse extreme first relative to the position (worst-case ordering)
        if sgn > 0:
            return [c["o"], c["l"], c["h"], c["c"]]
        return [c["o"], c["h"], c["l"], c["c"]]
    if c["c"] >= c["o"]:
        return [c["o"], c["l"], c["h"], c["c"]]
    return [c["o"], c["h"], c["l"], c["c"]]


def simulate(ent, cfg, candles):
    is_long = ent["side"] == "LONG"
    entry, atr = ent["entry"], ent["atr"]
    sgn = 1 if is_long else -1
    sl0 = entry - sgn * atr * 1.0
    tp1 = entry + sgn * atr * 1.0
    tp2 = entry + sgn * atr * 2.0
    sl_dist = abs(entry - sl0)
    qty = RISK_USD / sl_dist
    fee = TAKER_FEE_BPS / 10000.0
    fee_buffer = entry * (fee * 2 + FEE_BUFFER_EXTRA)
    trailing_distance = atr * cfg.trail_mult

    state = "OPEN"
    sl, pos_qty = sl0, qty
    realized = -(entry * qty * fee)
    peak = entry
    tp1_hit = False
    open_t = ent["t"]
    deadline_idx = ent["idx"] + int(MAX_HOLD_HOURS)

    def fav(px):
        return sgn * (px - entry)

    def leg(px, q):
        return sgn * (px - entry) * q

    def close_all(px, action, i):
        nonlocal realized, pos_qty
        realized += leg(px, pos_qty) - px * pos_qty * fee
        pos_qty = 0.0
        return {"pnl": realized, "r": realized / RISK_USD, "action": action,
                "tp1": tp1_hit, "hold_h": i - ent["idx"] + 1}

    def update_trailing(px):
        nonlocal peak, sl
        peak = max(peak, px) if is_long else min(peak, px)
        total_range = sgn * (tp2 - entry)
        peak_move = sgn * (peak - entry)
        progress = min(peak_move / total_range, 1.0) if total_range > 0 else 0.0
        tighten = max(cfg.tighten_start - progress * (cfg.tighten_start - cfg.tighten_end),
                      cfg.tighten_end)
        trailing_sl = peak - sgn * trailing_distance * tighten
        floor_sl = None
        if progress > cfg.floor_progress and peak_move > 0:
            lock_pct = min(cfg.floor_start + (progress - cfg.floor_progress) * 0.5,
                           cfg.floor_max)
            floor_sl = entry + sgn * peak_move * lock_pct
        elif peak_move > 0:
            floor_sl = entry + sgn * entry * fee * 2
        new_sl = trailing_sl
        if floor_sl is not None:
            new_sl = max(trailing_sl, floor_sl) if is_long else min(trailing_sl, floor_sl)
        if (is_long and new_sl > sl) or (not is_long and new_sl < sl):
            sl = new_sl

    for i in range(ent["idx"], min(deadline_idx, len(candles))):
        c = candles[i]
        for px in candle_points(c, sgn):
            if not cfg.naive and state == "OPEN":
                r_now = fav(px) / sl_dist
                if r_now >= cfg.be_trigger:
                    be_sl = entry + sgn * fee_buffer
                    if sgn * (be_sl - sl) > 0:
                        sl = be_sl
                if r_now >= cfg.lock_trigger:
                    lock_sl = entry + sgn * sl_dist * cfg.lock_frac
                    if sgn * (lock_sl - sl) > 0:
                        sl = lock_sl
            if (is_long and px <= sl) or (not is_long and px >= sl):
                action = "TRAIL" if state == "TRAILING" else "SL"
                return close_all(sl, action, i)
            if not cfg.naive and state == "OPEN" and sgn * (px - tp1) >= 0:
                tp1_hit = True
                cq = pos_qty * cfg.tp1_close_pct
                realized += leg(tp1, cq) - tp1 * cq * fee
                pos_qty -= cq
                if pos_qty > 0:
                    cushion = realized / pos_qty
                    sl = entry - sgn * (cushion - fee_buffer)
                peak = tp1
                state = "TRAILING"
            if state == "TRAILING":
                update_trailing(px)
            if sgn * (px - tp2) >= 0:
                return close_all(tp2, "TP2", i)
    i_end = min(deadline_idx, len(candles)) - 1
    return close_all(candles[i_end]["c"], "HOLD_LIMIT", i_end)


# ── regime tagging ──────────────────────────────────────────────────────

def tag_regime(candles, atrs, idx):
    """Efficiency ratio over prior 100 bars: trend vs chop; ATR tercile: vol."""
    j0 = max(0, idx - 100)
    closes = [candles[k]["c"] for k in range(j0, idx)]
    if len(closes) < 20:
        return "unknown", "unknown"
    net = abs(closes[-1] - closes[0])
    path = sum(abs(closes[k] - closes[k - 1]) for k in range(1, len(closes)))
    er = net / path if path > 0 else 0.0
    trend = "trend" if er >= 0.25 else ("mixed" if er >= 0.12 else "chop")
    window = atrs[max(0, idx - 500):idx]
    pr = pct_rank(window, atrs[idx])
    vol = "hi-vol" if pr >= 0.67 else ("mid-vol" if pr >= 0.33 else "lo-vol")
    return trend, vol


# ── metrics ─────────────────────────────────────────────────────────────

def metrics(rs):
    if not rs:
        return None
    pn = [r["r"] for r in rs]
    wins = [p for p in pn if p > 0]
    losses = [p for p in pn if p <= 0]
    cum = peak = dd = 0.0
    for p in pn:
        cum += p
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    mean = sum(pn) / len(pn)
    var = sum((p - mean) ** 2 for p in pn) / (len(pn) - 1) if len(pn) > 1 else 0.0
    t = mean / ((var / len(pn)) ** 0.5) if var > 0 else 0.0
    return {"n": len(pn), "sum_r": sum(pn), "exp_r": mean,
            "wr": len(wins) / len(pn) * 100, "avg_win_r": aw, "avg_loss_r": al,
            "asym": (aw / abs(al)) if al else float("inf"), "max_dd_r": dd,
            "t_stat": t}


def frow(name, m):
    if not m:
        return f"| {name} | 0 | - | - | - | - | - | - | - |"
    return (f"| {name} | {m['n']} | {m['sum_r']:+.1f} | {m['exp_r']:+.3f} "
            f"| {m['wr']:.1f}% | {m['avg_win_r']:+.2f} | {m['avg_loss_r']:+.2f} "
            f"| {m['asym']:.2f} | {m['max_dd_r']:.1f} |")


HDR = ("| slice | n | sumR | expR | WR | avgWinR | avgLossR | asym | maxDD-R |\n"
       "|---|---|---|---|---|---|---|---|---|")


def main():
    all_results = {c.name: [] for c in CFGS}
    sources = {}
    for sym in SYMBOLS:
        data = get_candles(sym)
        if not data:
            print(f"  {sym}: NO DATA, skipped", file=sys.stderr)
            continue
        candles = data["candles"]
        sources[sym] = {"source": data["source"], "n_candles": len(candles),
                        "first": candles[0]["t"], "last": candles[-1]["t"]}
        atrs = atr14(candles)
        entries = gen_entries(candles)
        print(f"  {sym}: {len(entries)} raw cross entries")
        # one position per symbol at a time (use RESTORED hold to gate; apply
        # same entry list to all cfgs so entries are IDENTICAL across cfgs)
        gated, busy_until = [], -1
        for e in entries:
            if e["idx"] <= busy_until:
                continue
            r0 = simulate(e, CFGS[0], candles)
            busy_until = e["idx"] + r0["hold_h"]
            gated.append(e)
        print(f"  {sym}: {len(gated)} non-overlapping entries")
        for e in gated:
            dt = datetime.fromtimestamp(e["t"] / 1000, tz=timezone.utc)
            trend, vol = tag_regime(candles, atrs, e["idx"] - 1)
            meta = {"symbol": sym, "side": e["side"], "year": dt.year,
                    "half": f"{dt.year}H{1 if dt.month <= 6 else 2}",
                    "trend": trend, "vol": vol, "t": e["t"]}
            for cfg in CFGS:
                res = simulate(e, cfg, candles)
                all_results[cfg.name].append({**meta, **res})

    out = {"generated": datetime.now(timezone.utc).isoformat(),
           "sources": sources, "risk_usd": RISK_USD, "tables": {}}

    def report(title, key_fn, keys):
        print(f"\n==== {title} ====")
        for cfg in CFGS:
            print(f"\n-- {cfg.name} --\n{HDR}")
            tab = {}
            for k in keys:
                sub = [r for r in all_results[cfg.name] if key_fn(r) == k]
                m = metrics(sub)
                tab[str(k)] = m
                print(frow(str(k), m))
            out["tables"].setdefault(title, {})[cfg.name] = tab

    years = sorted({r["year"] for r in all_results["RESTORED"]})
    halves = sorted({r["half"] for r in all_results["RESTORED"]})
    report("ALL", lambda r: "all", ["all"])
    report("BY-YEAR", lambda r: r["year"], years)
    report("BY-HALF", lambda r: r["half"], halves)
    report("BY-SYMBOL", lambda r: r["symbol"], SYMBOLS)
    report("BY-SIDE", lambda r: r["side"], ["LONG", "SHORT"])
    report("BY-TREND-REGIME", lambda r: r["trend"], ["trend", "mixed", "chop"])
    report("BY-VOL-REGIME", lambda r: r["vol"], ["hi-vol", "mid-vol", "lo-vol"])
    report("SYMBOL-YEAR", lambda r: (r["symbol"], r["year"]),
           [(s, y) for s in SYMBOLS for y in years])
    report("YEAR-SIDE", lambda r: (r["year"], r["side"]),
           [(y, s) for y in years for s in ("LONG", "SHORT")])

    # fragility: remove single best trade per cfg
    print("\n==== FRAGILITY (drop best single trade) ====")
    for cfg in CFGS:
        rs = sorted(all_results[cfg.name], key=lambda r: r["r"], reverse=True)
        full = sum(r["r"] for r in rs)
        wo = full - rs[0]["r"] if rs else 0
        print(f"{cfg.name}: sumR {full:+.1f} -> {wo:+.1f} without best "
              f"(best={rs[0]['r']:+.2f}R {rs[0]['symbol']} {rs[0]['side']})")
        out["tables"].setdefault("FRAGILITY", {})[cfg.name] = {
            "sum_r": full, "without_best": wo}

    # exit action mix
    print("\n==== EXIT ACTION MIX ====")
    for cfg in CFGS:
        rs = all_results[cfg.name]
        mix = {}
        for r in rs:
            mix[r["action"]] = mix.get(r["action"], 0) + 1
        print(f"{cfg.name}: " + ", ".join(f"{k}={v} ({v/len(rs)*100:.0f}%)"
                                          for k, v in sorted(mix.items())))
        out["tables"].setdefault("EXIT_MIX", {})[cfg.name] = mix

    suffix = "" if PATH_MODE == "chrono" else f"_{PATH_MODE}"
    (CACHE / f"results{suffix}.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nresults -> {CACHE / ('results' + suffix + '.json')} (path={PATH_MODE})")


if __name__ == "__main__":
    main()
