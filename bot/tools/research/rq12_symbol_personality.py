"""RQ12: Symbol personality — per-symbol character from candles + our trades.

Read-only on bot data. Fetches Hyperliquid candles (ground truth), replays our
trade_ledger.csv trades at 15m resolution to measure MAE/MFE, grids stop widths
and hold caps, computes realized vol by hour-of-day per symbol.

Outputs JSON to stdout for the coordination report.
"""
import csv, json, math, statistics, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

LEDGER = "C:/Users/vince/WAGMI/bot/data/trade_ledger.csv"
HL = "https://api.hyperliquid.xyz/info"
SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "XRP"]
CACHE = {}

def hl_candles(coin, interval, start_ms, end_ms):
    key = (coin, interval, start_ms // 1000, end_ms // 1000)
    if key in CACHE:
        return CACHE[key]
    out = []
    cur = start_ms
    while cur < end_ms:
        body = json.dumps({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval, "startTime": cur, "endTime": end_ms}}).encode()
        req = urllib.request.Request(HL, data=body, headers={"Content-Type": "application/json"})
        for attempt in range(4):
            try:
                d = json.load(urllib.request.urlopen(req, timeout=30))
                break
            except Exception:
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"HL fetch failed {coin} {interval}")
        if not d:
            break
        new = [c for c in d if c["t"] >= cur]
        if not new:
            break
        out.extend(new)
        nxt = new[-1]["t"] + 1
        if nxt <= cur:
            break
        cur = nxt
        if len(d) < 500:
            break
        time.sleep(0.3)
    # dedupe by open time
    seen, ded = set(), []
    for c in out:
        if c["t"] not in seen:
            seen.add(c["t"])
            ded.append({"t": c["t"], "o": float(c["o"]), "h": float(c["h"]),
                        "l": float(c["l"]), "c": float(c["c"])})
    ded.sort(key=lambda x: x["t"])
    CACHE[key] = ded
    return ded

# ---------- load trades ----------
rows = list(csv.DictReader(open(LEDGER)))
trades = []
for r in rows:
    t = float(r["timestamp"])
    hold = float(r["hold_hours"] or 0)
    entry, exitp = float(r["entry_price"]), float(r["exit_price"])
    def f(x):
        return float(x) if x not in ("", None) else 0.0
    gross, fees, net = f(r["gross_pnl"]), f(r["fees"]), f(r["net_pnl"])
    side = 1 if r["side"] in ("LONG", "BUY") else -1
    size = gross / (exitp - entry) if exitp != entry else None  # signed units; sign should match side
    notional = abs(size) * entry if size else None
    trades.append(dict(id=r["trade_id"], ts=t, sym=r["symbol"], side=side,
                       entry=entry, exit=exitp, gross=gross, fees=fees, net=net,
                       hold=hold, exit_type=r["exit_type"], lev=r["leverage"],
                       notional=notional,
                       ret=side * (exitp - entry) / entry))

t0 = min(t["ts"] for t in trades)
t1 = max(t["ts"] for t in trades) + 3 * 86400
START_MS = int((t0 - 20 * 3600) * 1000)   # pad for ATR lookback
END_MS = int(t1 * 1000)

# fee rate estimate (round trip) from actual fees vs notional
fr = [t["fees"] / (t["notional"] * 2) for t in trades if t["notional"] and t["notional"] > 0]
FEE_PER_SIDE = statistics.median(fr) if fr else 0.00045
FEE_RT = 2 * FEE_PER_SIDE

print(f"# fee per side (median est): {FEE_PER_SIDE:.5%}, n_fee={len(fr)}", file=sys.stderr)

# ---------- candles ----------
H1 = {s: hl_candles(s, "1h", START_MS, END_MS) for s in SYMBOLS}
M15 = {s: hl_candles(s, "15m", START_MS, END_MS) for s in SYMBOLS}
for s in SYMBOLS:
    print(f"# {s}: {len(H1[s])} 1h candles, {len(M15[s])} 15m candles", file=sys.stderr)

def atr14_at(sym, ts_ms):
    """ATR(14) on 1h candles as of timestamp (uses candles closed before ts)."""
    cs = [c for c in H1[sym] if c["t"] + 3600_000 <= ts_ms][-15:]
    if len(cs) < 15:
        cs = H1[sym][:15]
    trs = []
    for i in range(1, len(cs)):
        p = cs[i - 1]["c"]
        trs.append(max(cs[i]["h"] - cs[i]["l"], abs(cs[i]["h"] - p), abs(cs[i]["l"] - p)))
    return sum(trs) / len(trs)

def window(sym, start_ms, end_ms):
    return [c for c in M15[sym] if start_ms <= c["t"] < end_ms]

# ---------- per-trade excursion via 15m replay ----------
for tr in trades:
    ent_ms = int(tr["ts"] * 1000)
    exit_ms = int((tr["ts"] + tr["hold"] * 3600) * 1000) + 900_000
    cs = window(tr["sym"], ent_ms - 900_000, exit_ms)
    tr["atr"] = atr14_at(tr["sym"], ent_ms)
    tr["atr_pct"] = tr["atr"] / tr["entry"]
    mae = 0.0  # max adverse move (positive number, in price)
    mfe = 0.0
    mae_before_peak = 0.0
    peak_i = -1
    path = []
    for i, c in enumerate(cs):
        if tr["side"] == 1:
            adv = tr["entry"] - c["l"]
            fav = c["h"] - tr["entry"]
        else:
            adv = c["h"] - tr["entry"]
            fav = tr["entry"] - c["l"]
        mae = max(mae, adv)
        if fav > mfe:
            mfe = fav
            peak_i = i
            mae_before_peak = mae
        path.append((c, adv, fav))
    tr["path"] = path
    tr["mae_atr"] = mae / tr["atr"] if tr["atr"] else None
    tr["mfe_atr"] = mfe / tr["atr"] if tr["atr"] else None
    tr["mae_before_peak_atr"] = (mae_before_peak / tr["atr"]) if (tr["atr"] and peak_i >= 0) else None
    tr["hours_to_peak"] = (peak_i * 0.25) if peak_i >= 0 else None
    tr["win"] = tr["net"] > 0

# ---------- stop-width grid (candle replay) ----------
# Stop at k*ATR from entry. If 15m low/high crosses stop -> exit at stop price
# (conservative: assume stop fill at stop level). Else exit at actual exit.
STOP_GRID = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, None]  # None = actual behavior

def sim_stop(tr, k):
    if k is None:
        return tr["ret"] - FEE_RT * 0  # actual net already includes fees; use ret-fee below uniformly
    stop_dist = k * tr["atr"]
    for c, adv, fav in tr["path"]:
        if adv >= stop_dist:
            return -stop_dist / tr["entry"]
    return tr["ret"]

# hold-cap grid: force exit at close of candle at H hours if still open
HOLD_GRID = [2, 4, 8, 12, 24, 48, None]

def sim_hold(tr, H):
    if H is None or tr["hold"] <= H:
        return tr["ret"]
    idx = int(H * 4)
    if idx >= len(tr["path"]):
        return tr["ret"]
    c = tr["path"][idx][0]
    return tr["side"] * (c["c"] - tr["entry"]) / tr["entry"]

# combined: stop k AND hold cap H
def sim_combo(tr, k, H):
    stop_dist = k * tr["atr"] if k else None
    n = len(tr["path"])
    cap = int(H * 4) if H else n
    for i, (c, adv, fav) in enumerate(tr["path"]):
        if stop_dist and adv >= stop_dist:
            return -stop_dist / tr["entry"]
        if i >= cap:
            return tr["side"] * (c["c"] - tr["entry"]) / tr["entry"]
    return tr["ret"]

# ---------- realized vol by hour of day (1h candles, full window) ----------
volhr = {}
for s in SYMBOLS:
    byh = defaultdict(list)
    for c in H1[s]:
        h = datetime.fromtimestamp(c["t"] / 1000, timezone.utc).hour
        r = abs(math.log(c["c"] / c["o"]))
        byh[h].append(r)
    volhr[s] = {h: (statistics.mean(v) * 100, len(v)) for h, v in sorted(byh.items())}

# ---------- report ----------
ERA_SPLIT = datetime(2026, 6, 16, tzinfo=timezone.utc).timestamp()

def stats(ts_):
    if not ts_:
        return {}
    rets = [t["ret"] for t in ts_]
    nets = [t["net"] for t in ts_]
    return dict(n=len(ts_), wr=sum(1 for t in ts_ if t["win"]) / len(ts_),
                net_usd=sum(nets), fees_usd=sum(t["fees"] for t in ts_),
                gross_usd=sum(t["gross"] for t in ts_),
                avg_ret_pct=statistics.mean(rets) * 100,
                med_hold=statistics.median(t["hold"] for t in ts_))

out = {"fee_per_side": FEE_PER_SIDE, "symbols": {}}
for s in SYMBOLS:
    ts_ = [t for t in trades if t["sym"] == s]
    winners = [t for t in ts_ if t["win"]]
    losers = [t for t in ts_ if not t["win"]]
    d = {"all": stats(ts_),
         "era1_jun1_15": stats([t for t in ts_ if t["ts"] < ERA_SPLIT]),
         "era2_jun16_jul1": stats([t for t in ts_ if t["ts"] >= ERA_SPLIT]),
         "atr_pct_med": statistics.median(t["atr_pct"] for t in ts_) * 100,
         "winners_mae_before_peak_atr": sorted(round(t["mae_before_peak_atr"], 2) for t in winners if t["mae_before_peak_atr"] is not None),
         "winners_hours_to_peak": sorted(t["hours_to_peak"] for t in winners if t["hours_to_peak"] is not None),
         "losers_mfe_atr": sorted(round(t["mfe_atr"], 2) for t in losers if t["mfe_atr"] is not None),
         "mae_atr_all": sorted(round(t["mae_atr"], 2) for t in ts_ if t["mae_atr"] is not None),
         }
    # stop grid
    sg = {}
    for k in STOP_GRID:
        rets = [(sim_stop(t, k) - FEE_RT) for t in ts_]
        stopped = sum(1 for t in ts_ if k and t["mae_atr"] is not None and t["mae_atr"] >= k)
        sg[str(k)] = dict(sum_ret_pct=sum(rets) * 100, avg_ret_pct=statistics.mean(rets) * 100,
                          n_stopped=stopped)
    d["stop_grid_feeadj"] = sg
    hg = {}
    for H in HOLD_GRID:
        rets = [(sim_hold(t, H) - FEE_RT) for t in ts_]
        hg[str(H)] = dict(sum_ret_pct=sum(rets) * 100)
    d["hold_grid_feeadj"] = hg
    # combos
    best = None
    combo = {}
    for k in [0.75, 1.0, 1.25, 1.5, 2.0, 2.5]:
        for H in [4, 8, 12, 24, 48, None]:
            rets = [(sim_combo(t, k, H) - FEE_RT) for t in ts_]
            v = sum(rets) * 100
            combo[f"k{k}_H{H}"] = round(v, 2)
            if best is None or v > best[2]:
                best = (k, H, v)
    d["combo_grid_sum_ret_pct"] = combo
    d["best_combo"] = dict(stop_atr=best[0], hold_cap_h=best[1], sum_ret_pct=round(best[2], 2))
    # fragility: remove single best trade, recompute best combo value
    if len(ts_) > 1:
        k, H = best[0], best[1]
        rets = sorted([(sim_combo(t, k, H) - FEE_RT) for t in ts_])
        d["best_combo_minus_best_trade_pct"] = round((sum(rets) - rets[-1]) * 100, 2)
        d["actual_minus_best_trade_usd"] = round(sum(t["net"] for t in ts_) - max(t["net"] for t in ts_), 2)
    # exit types
    et = defaultdict(lambda: [0, 0.0])
    for t in ts_:
        et[t["exit_type"]][0] += 1
        et[t["exit_type"]][1] += t["net"]
    d["exit_types"] = {k: {"n": v[0], "net_usd": round(v[1], 2)} for k, v in et.items()}
    # vol by hour: top-4 / bottom-4 hours
    vh = volhr[s]
    ranked = sorted(vh.items(), key=lambda kv: -kv[1][0])
    d["vol_by_hour_top4"] = [(h, round(v[0], 3)) for h, v in ranked[:4]]
    d["vol_by_hour_bot4"] = [(h, round(v[0], 3)) for h, v in ranked[-4:]]
    d["vol_hr_mean_pct"] = round(statistics.mean(v[0] for v in vh.values()), 3)
    out["symbols"][s] = d

# HYPE both-sides chop check: overlapping-window long AND short signals -> measure 1h candle reversal freq
def reversal_rate(sym):
    cs = H1[sym]
    flips = 0
    for i in range(1, len(cs)):
        if (cs[i]["c"] - cs[i]["o"]) * (cs[i - 1]["c"] - cs[i - 1]["o"]) < 0:
            flips += 1
    return flips / (len(cs) - 1)

out["reversal_rate_1h"] = {s: round(reversal_rate(s), 3) for s in SYMBOLS}

def r(o):
    if isinstance(o, float):
        return round(o, 4)
    if isinstance(o, dict):
        return {k: r(v) for k, v in o.items()}
    if isinstance(o, list):
        return [r(v) for v in o]
    if isinstance(o, tuple):
        return [r(v) for v in o]
    return o

print(json.dumps(r(out), indent=1))
