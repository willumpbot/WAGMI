"""RQ10: Regime-label accuracy audit.

Compares the Regime agent's labels (agent_performance.jsonl, agent_role=regime)
against:
  A) a mechanical nowcast classifier (ADX14 / ATR-percentile / trend-slope) computed
     from HL 1h candles using data up to the label timestamp only
  B) a hindsight "realized" regime from the NEXT 24h of candles
     (efficiency ratio for trendiness, forward realized-vol percentile for high-vol)
Then joins to trade_ledger.csv to test whether agent-vs-mechanical disagreement at
entry correlates with losing trades.

Read-only on bot code/data; writes only rq10_* artifacts in this directory.
"""
import json
import math
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "..", "data"))
CANDLE_CACHE = os.path.join(HERE, "rq10_candles_1h.json")
SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "XRP"]

# ---------------- candles ----------------

def fetch_candles(coin, start_ms, end_ms):
    body = json.dumps({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1h", "startTime": start_ms, "endTime": end_ms},
    }).encode()
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_candles(refresh=False):
    if os.path.exists(CANDLE_CACHE) and not refresh:
        return json.load(open(CANDLE_CACHE))
    out = {}
    start = int(datetime(2026, 5, 10, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(time.time() * 1000)
    for s in SYMBOLS:
        out[s] = fetch_candles(s, start, end)
        print(s, len(out[s]), "candles", file=sys.stderr)
        time.sleep(0.4)
    json.dump(out, open(CANDLE_CACHE, "w"))
    return out

# ---------------- indicators ----------------

def wilder(vals, n):
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    s = sum(vals[:n]) / n
    out[n - 1] = s
    for i in range(n, len(vals)):
        s = (s * (n - 1) + vals[i]) / n
        out[i] = s
    return out


def indicators(candles, n=14):
    """Returns list of dicts per bar: t, c, adx, dip, dim, atr_pct, atr_ptile, ema20_slope."""
    T = [int(c["t"]) for c in candles]
    O = [float(c["o"]) for c in candles]
    H = [float(c["h"]) for c in candles]
    L = [float(c["l"]) for c in candles]
    C = [float(c["c"]) for c in candles]
    m = len(C)
    tr, pdm, ndm = [0.0], [0.0], [0.0]
    for i in range(1, m):
        tr.append(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])))
        up, dn = H[i] - H[i - 1], L[i - 1] - L[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        ndm.append(dn if (dn > up and dn > 0) else 0.0)
    atr = wilder(tr[1:], n)
    spdm = wilder(pdm[1:], n)
    sndm = wilder(ndm[1:], n)
    dip = [None] * m
    dim = [None] * m
    dx = [None] * m
    for i in range(1, m):
        a, p, q = atr[i - 1], spdm[i - 1], sndm[i - 1]
        if a and a > 0 and p is not None:
            dip[i] = 100 * p / a
            dim[i] = 100 * q / a
            den = dip[i] + dim[i]
            dx[i] = 100 * abs(dip[i] - dim[i]) / den if den > 0 else 0.0
    adx = [None] * m
    dxv = [dx[i] for i in range(m) if dx[i] is not None]
    first = next((i for i in range(m) if dx[i] is not None), None)
    if first is not None and len(dxv) >= n:
        s = sum(dx[first:first + n]) / n
        adx[first + n - 1] = s
        for i in range(first + n, m):
            s = (s * (n - 1) + dx[i]) / n
            adx[i] = s
    # ATR% and rolling percentile over trailing 336 bars (14d)
    atr_pct = [None] * m
    for i in range(1, m):
        if atr[i - 1] and C[i] > 0:
            atr_pct[i] = atr[i - 1] / C[i]
    atr_ptile = [None] * m
    win = 336
    hist = []
    for i in range(m):
        v = atr_pct[i]
        if v is not None:
            lo = max(0, i - win)
            past = [atr_pct[j] for j in range(lo, i) if atr_pct[j] is not None]
            if len(past) >= 100:
                atr_ptile[i] = sum(1 for p in past if p <= v) / len(past)
    # EMA20 slope (per-bar, normalized by ATR)
    ema = [None] * m
    k = 2 / 21
    e = C[0]
    for i in range(m):
        e = C[i] * k + e * (1 - k)
        ema[i] = e
    slope = [None] * m
    for i in range(6, m):
        if atr[i - 1]:
            slope[i] = (ema[i] - ema[i - 6]) / (atr[i - 1] * 6)
    rows = []
    for i in range(m):
        rows.append(dict(t=T[i], c=C[i], adx=adx[i], dip=dip[i], dim=dim[i],
                         atr=atr[i - 1] if i >= 1 else None,
                         atr_pct=atr_pct[i], atr_ptile=atr_ptile[i], slope=slope[i]))
    return rows

# ---------------- classifiers ----------------

def mech_label(row, adx_hi=25.0, vol_ptile=0.90):
    """Mechanical nowcast from data up to and including this closed bar."""
    if row["adx"] is None or row["atr_ptile"] is None:
        return None
    if row["atr_ptile"] >= vol_ptile:
        return "high_vol"
    if row["adx"] >= adx_hi:
        return "trending_bull" if (row["dip"] or 0) >= (row["dim"] or 0) else "trending_bear"
    return "ranging"


def coarse(label):
    if label in ("trend", "trending_bull", "trending_bear"):
        return "trending"
    if label in ("high_volatility", "panic", "high_vol"):
        return "high_vol"
    if label in ("range", "consolidation", "low_liquidity", "ranging"):
        return "ranging"
    return None


def realized_label(rows, i, fwd=24, er_thresh=0.35, volp=0.90, fwd_vol_dist=None):
    """Hindsight regime over (i, i+fwd]. Requires full forward window."""
    if i + fwd >= len(rows):
        return None
    c0 = rows[i]["c"]
    cs = [rows[j]["c"] for j in range(i, i + fwd + 1)]
    net = abs(cs[-1] - cs[0])
    path = sum(abs(cs[j + 1] - cs[j]) for j in range(len(cs) - 1))
    er = net / path if path > 0 else 0.0
    rets = [math.log(cs[j + 1] / cs[j]) for j in range(len(cs) - 1)]
    mu = sum(rets) / len(rets)
    rv = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
    hv = False
    if fwd_vol_dist:
        rank = sum(1 for v in fwd_vol_dist if v <= rv) / len(fwd_vol_dist)
        hv = rank >= volp
    if hv:
        return "high_vol", (cs[-1] - cs[0]) / c0, er, rv
    if er >= er_thresh:
        return ("trending_bull" if cs[-1] > cs[0] else "trending_bear"), (cs[-1] - cs[0]) / c0, er, rv
    return "ranging", (cs[-1] - cs[0]) / c0, er, rv

# ---------------- main ----------------

def main():
    refresh = "--refresh" in sys.argv
    candles = load_candles(refresh=refresh)
    ind = {s: indicators(candles[s]) for s in SYMBOLS}
    index = {s: {r["t"]: i for i, r in enumerate(ind[s])} for s in SYMBOLS}

    # forward realized-vol distribution per symbol (for high_vol hindsight rank)
    fwd_vol = {}
    for s in SYMBOLS:
        rows = ind[s]
        dist = []
        for i in range(0, len(rows) - 25):
            cs = [rows[j]["c"] for j in range(i, i + 25)]
            rets = [math.log(cs[j + 1] / cs[j]) for j in range(24)]
            mu = sum(rets) / 24
            dist.append(math.sqrt(sum((r - mu) ** 2 for r in rets) / 24))
        fwd_vol[s] = dist

    # ---- load agent regime labels ----
    labels = []
    with open(os.path.join(DATA, "llm", "agent_performance.jsonl"), encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("agent_role") != "regime":
                continue
            sym = r.get("symbol")
            if sym not in SYMBOLS:
                continue
            labels.append(dict(ts=r["timestamp"], sym=sym, lab=r["decision"],
                               conf=r.get("confidence"), model=r.get("model_used")))
    labels.sort(key=lambda x: x["ts"])

    def bar_at(sym, ts):
        """Index of last CLOSED 1h bar at wall-clock ts."""
        t_open = (int(ts * 1000) // 3600000) * 3600000 - 3600000
        return index[sym].get(t_open)

    # ---- build joined table ----
    joined = []
    for L in labels:
        i = bar_at(L["sym"], L["ts"])
        if i is None:
            continue
        rows = ind[L["sym"]]
        mech = mech_label(rows[i])
        real = realized_label(rows, i, fwd_vol_dist=fwd_vol[L["sym"]])
        rec = dict(L)
        rec["mech"] = mech
        rec["mech_c"] = coarse(mech) if mech else None
        rec["agent_c"] = coarse(L["lab"])
        if real:
            rec["real"] = real[0]
            rec["real_c"] = coarse(real[0])
            rec["fwd_ret"] = real[1]
            rec["er"] = real[2]
        joined.append(rec)

    out = {"n_labels_total": len(labels), "n_joined": len(joined)}

    # ---- A: confusion matrix agent vs mechanical nowcast ----
    def cmatrix(pairs):
        cm = defaultdict(Counter)
        for a, b in pairs:
            cm[a][b] += 1
        return {k: dict(v) for k, v in cm.items()}

    ab = [(r["agent_c"], r["mech_c"]) for r in joined if r["agent_c"] and r["mech_c"]]
    out["agent_vs_mech_coarse"] = cmatrix(ab)
    out["agent_vs_mech_agree"] = sum(1 for a, b in ab if a == b) / len(ab) if ab else None

    # fine matrix (raw agent label vs mech label)
    fine = [(r["lab"], r["mech"]) for r in joined if r["mech"]]
    out["agent_raw_vs_mech_fine"] = cmatrix(fine)

    # ---- B: accuracy vs hindsight realized ----
    hj = [r for r in joined if r.get("real_c") and r["agent_c"] and r["mech_c"]]
    out["n_hindsight"] = len(hj)

    def acc(pairs):
        return sum(1 for a, b in pairs if a == b) / len(pairs) if pairs else None

    out["agent_acc_vs_realized"] = acc([(r["agent_c"], r["real_c"]) for r in hj])
    out["mech_acc_vs_realized"] = acc([(r["mech_c"], r["real_c"]) for r in hj])
    out["always_ranging_acc"] = acc([("ranging", r["real_c"]) for r in hj])
    out["realized_base_rates"] = dict(Counter(r["real_c"] for r in hj))
    out["agent_cm_vs_realized"] = cmatrix([(r["agent_c"], r["real_c"]) for r in hj])
    out["mech_cm_vs_realized"] = cmatrix([(r["mech_c"], r["real_c"]) for r in hj])

    # per-class recall/precision for both
    def prf(pairs, cls):
        tp = sum(1 for a, b in pairs if a == cls and b == cls)
        fp = sum(1 for a, b in pairs if a == cls and b != cls)
        fn = sum(1 for a, b in pairs if a != cls and b == cls)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        return {"precision": prec, "recall": rec, "n_pred": tp + fp, "n_true": tp + fn}

    for cls in ("trending", "ranging", "high_vol"):
        out[f"agent_{cls}"] = prf([(r["agent_c"], r["real_c"]) for r in hj], cls)
        out[f"mech_{cls}"] = prf([(r["mech_c"], r["real_c"]) for r in hj], cls)

    # direction accuracy when agent says trending_bull/bear
    dir_pairs = [(r["lab"], r["fwd_ret"]) for r in hj if r["lab"] in ("trending_bull", "trending_bear")]
    dir_ok = sum(1 for l, fr in dir_pairs if (fr > 0) == (l == "trending_bull"))
    out["agent_direction"] = {"n": len(dir_pairs), "acc": dir_ok / len(dir_pairs) if dir_pairs else None}
    mdir = [(r["mech"], r["fwd_ret"]) for r in hj if r["mech"] in ("trending_bull", "trending_bear")]
    mok = sum(1 for l, fr in mdir if (fr > 0) == (l == "trending_bull"))
    out["mech_direction"] = {"n": len(mdir), "acc": mok / len(mdir) if mdir else None}

    # era split (June 1-15 vs June 16-Jul 2)
    cut = datetime(2026, 6, 16, tzinfo=timezone.utc).timestamp()
    for name, sel in (("era1_pre0616", lambda r: r["ts"] < cut), ("era2_post0616", lambda r: r["ts"] >= cut)):
        sub = [r for r in hj if sel(r)]
        out[name] = {
            "n": len(sub),
            "agent_acc": acc([(r["agent_c"], r["real_c"]) for r in sub]),
            "mech_acc": acc([(r["mech_c"], r["real_c"]) for r in sub]),
            "always_ranging": acc([("ranging", r["real_c"]) for r in sub]),
            "agree_rate": acc([(r["agent_c"], r["mech_c"]) for r in sub]),
        }

    # per-symbol split
    out["per_symbol"] = {}
    for s in SYMBOLS:
        sub = [r for r in hj if r["sym"] == s]
        if not sub:
            continue
        out["per_symbol"][s] = {
            "n": len(sub),
            "agent_acc": acc([(r["agent_c"], r["real_c"]) for r in sub]),
            "mech_acc": acc([(r["mech_c"], r["real_c"]) for r in sub]),
            "always_ranging": acc([("ranging", r["real_c"]) for r in sub]),
        }

    # sensitivity: ER threshold for trending hindsight
    for er_t in (0.25, 0.45):
        pairs_a, pairs_m = [], []
        for r in joined:
            if not (r["agent_c"] and r["mech_c"]):
                continue
            i = bar_at(r["sym"], r["ts"])
            real = realized_label(ind[r["sym"]], i, er_thresh=er_t, fwd_vol_dist=fwd_vol[r["sym"]])
            if not real:
                continue
            rc = coarse(real[0])
            pairs_a.append((r["agent_c"], rc))
            pairs_m.append((r["mech_c"], rc))
        out[f"sens_er{er_t}"] = {"agent_acc": acc(pairs_a), "mech_acc": acc(pairs_m),
                                "always_ranging": acc([("ranging", b) for _, b in pairs_a])}

    # confidence calibration: does agent confidence predict being right (vs realized)?
    bins = defaultdict(lambda: [0, 0])
    for r in hj:
        if r.get("conf") is None:
            continue
        b = "lo<0.7" if r["conf"] < 0.7 else ("mid0.7-0.8" if r["conf"] < 0.8 else "hi>=0.8")
        bins[b][0] += 1
        bins[b][1] += 1 if r["agent_c"] == r["real_c"] else 0
    out["conf_calibration"] = {k: {"n": v[0], "acc": v[1] / v[0]} for k, v in bins.items()}

    # ---- C: trades join ----
    import csv
    trades = []
    with open(os.path.join(DATA, "trade_ledger.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts = float(row["timestamp"])
                pnl = float(row["net_pnl"])
            except Exception:
                continue
            trades.append(dict(ts=ts, sym=row["symbol"], side=row["side"],
                               reg=row.get("regime_1h", ""), pnl=pnl,
                               hold=row.get("hold_hours"), exit=row.get("exit_type")))
    # entry ts = timestamp - hold_hours (ledger timestamp is at close)
    tr_stats = {"n_total": len(trades)}
    rowsj = []
    for t in trades:
        if t["sym"] not in SYMBOLS:
            continue
        try:
            entry_ts = t["ts"] - float(t["hold"] or 0) * 3600
        except Exception:
            entry_ts = t["ts"]
        i = bar_at(t["sym"], entry_ts)
        if i is None:
            continue
        rows = ind[t["sym"]]
        mech = mech_label(rows[i])
        if mech is None:
            continue
        agent_c = coarse(t["reg"]) or t["reg"]
        real = realized_label(rows, i, fwd_vol_dist=fwd_vol[t["sym"]])
        rowsj.append(dict(sym=t["sym"], pnl=t["pnl"], agent=agent_c, mech=coarse(mech),
                          real=coarse(real[0]) if real else None, side=t["side"]))
    tr_stats["n_joined"] = len(rowsj)

    def bucket(rows_):
        n = len(rows_)
        if n == 0:
            return {"n": 0}
        wins = sum(1 for r in rows_ if r["pnl"] > 0)
        return {"n": n, "wr": round(wins / n, 3), "pnl": round(sum(r["pnl"] for r in rows_), 2),
                "avg": round(sum(r["pnl"] for r in rows_) / n, 2)}

    ag = [r for r in rowsj if r["agent"] and r["agent"] == r["mech"]]
    dis = [r for r in rowsj if r["agent"] and r["mech"] and r["agent"] != r["mech"]]
    tr_stats["agent_mech_agree"] = bucket(ag)
    tr_stats["agent_mech_disagree"] = bucket(dis)
    # vs realized
    ac = [r for r in rowsj if r["agent"] and r["real"] and r["agent"] == r["real"]]
    aw = [r for r in rowsj if r["agent"] and r["real"] and r["agent"] != r["real"]]
    tr_stats["agent_correct_vs_realized"] = bucket(ac)
    tr_stats["agent_wrong_vs_realized"] = bucket(aw)
    mc = [r for r in rowsj if r["mech"] and r["real"] and r["mech"] == r["real"]]
    mw = [r for r in rowsj if r["mech"] and r["real"] and r["mech"] != r["real"]]
    tr_stats["mech_correct_vs_realized"] = bucket(mc)
    tr_stats["mech_wrong_vs_realized"] = bucket(mw)
    # by agent regime label at entry
    byreg = {}
    for reg in set(r["agent"] for r in rowsj if r["agent"]):
        byreg[reg] = bucket([r for r in rowsj if r["agent"] == reg])
    tr_stats["by_agent_regime"] = byreg
    out["trades"] = tr_stats

    # where does the agent misclassify most (fine-grained, vs realized)
    mis = Counter()
    for r in hj:
        if r["agent_c"] != r["real_c"]:
            mis[f"{r['lab']}->{r['real_c']}"] += 1
    out["top_misclassifications"] = mis.most_common(10)

    json.dump(out, open(os.path.join(HERE, "rq10_results.json"), "w"), indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
