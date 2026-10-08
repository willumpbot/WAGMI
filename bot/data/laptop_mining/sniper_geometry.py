"""Independent replication: does the geometry finding hold on the sniper corpus?

The geometry result came from paper_trades/signals_*.csv. manual/sniper_signals.jsonl
is a separate system (tiers SNIPER/PREMIUM/MICRO_SNIPER/STANDARD, its own entries,
stops and leverage, 2026-03-24 -> 06-05, 40,891 rows) that has never been graded at
all. If the same stop/target shape appears there, it is a property of the market and
this stop-placement style rather than of one logger.

Same machinery as sweep_geometry/sweep_oos: paired re-simulation on validated
candles, conservative tie rule, fees both legs, no lookahead, train/test split,
per-symbol breakdown, monotonicity.
"""
import json, io, os, csv, collections, random, math, datetime
from multiprocessing import Pool, cpu_count

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(HERE, "candles_merged")
HL = os.path.join(HERE, "candles")
SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/manual/sniper_signals.jsonl"
FEE_BPS = 9.0
HORIZON_H = 48
CUTOFF = "2026-05-01"
random.seed(20261008)

STOP_MULTS = (1.0, 2.0, 4.0, 6.0, 8.0, 12.0)
TP_MULTS = (0.5, 1.0, 1.5)
DEFAULT = (1.0, 1.5)


def load_candles(sym):
    for d in (MERGED, HL):
        p = os.path.join(d, f"{sym}_1h.csv")
        if os.path.exists(p):
            out = []
            with io.open(p, encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        out.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                                    float(r["l"]), float(r["c"])))
                    except (TypeError, ValueError):
                        continue
            out.sort()
            return out
    return None


def ib(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] <= t:
            best = m; lo = m + 1
        else:
            hi = m - 1
    return best


CAND = {}


def init_worker(syms):
    for s in syms:
        c = load_candles(s)
        if c:
            CAND[s] = c


def run_symbol(args):
    sym, sigs = args
    c = CAND.get(sym)
    if not c:
        return sym, []
    out = []
    for s in sigs:
        t0 = s["t0"]
        i0 = ib(c, t0)
        if i0 is None or t0 - c[i0][0] > 7200:
            continue
        entry = c[i0][4]
        base = abs(entry - s["sl"])
        if entry <= 0 or base <= 0:
            continue
        # guard against degenerate stops from this logger
        if not (0.0005 <= base / entry <= 0.30):
            continue
        long_ = s["side"] == "LONG"
        bars = []
        k = i0 + 1
        end = t0 + HORIZON_H * 3600
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if not bars:
            continue
        cells = {}
        for sm in STOP_MULTS:
            dist = sm * base
            sl = entry - dist if long_ else entry + dist
            feeR = 2 * (FEE_BPS / 1e4) * entry / dist
            for tm in TP_MULTS:
                tp = entry + tm * dist if long_ else entry - tm * dist
                r = None
                for (_, o, h, l, cl) in bars:
                    if long_:
                        hit_sl, hit_tp = l <= sl, h >= tp
                    else:
                        hit_sl, hit_tp = h >= sl, l <= tp
                    if hit_sl:
                        r = -1.0; break
                    if hit_tp:
                        r = tm; break
                if r is None:
                    last = bars[-1][4]
                    r = ((last - entry) if long_ else (entry - last)) / dist
                cells[f"{sm}|{tm}"] = r - feeR
        out.append({"sym": sym, "day": s["day"], "tier": s["tier"], "cells": cells})
    return sym, out


def mean_of(recs, key):
    v = [r["cells"][key] for r in recs if key in r["cells"]]
    return (sum(v) / len(v)) if v else None


def boot_diff(recs, a, b, iters=2500):
    cl = collections.defaultdict(list)
    for r in recs:
        if a in r["cells"] and b in r["cells"]:
            cl[(r["sym"], r["day"])].append(r["cells"][a] - r["cells"][b])
    keys = list(cl)
    if len(keys) < 3:
        return None, None, None
    allv = [x for k in keys for x in cl[k]]
    point = sum(allv) / len(allv)
    ds = []
    for _ in range(iters):
        pool = []
        for _ in range(len(keys)):
            pool.extend(cl[keys[random.randrange(len(keys))]])
        if pool:
            ds.append(sum(pool) / len(pool))
    ds.sort()
    return point, ds[int(.025 * len(ds))], ds[int(.975 * len(ds))]


def spearman(xs, ys):
    def rk(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for p, i in enumerate(o):
            r[i] = p
        return r
    a, b = rk(xs), rk(ys)
    n = len(xs)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((x - mb) ** 2 for x in b))
    return num / den if den else 0.0


def main():
    raw = seen = 0
    sigs, bad = [], collections.Counter()
    keep = set()
    with io.open(SRC, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.replace("\x00", "").strip()
            if not line:
                continue
            raw += 1
            try:
                d = json.loads(line)
            except Exception:
                bad["unparseable"] += 1
                continue
            sym = d.get("symbol")
            side = (d.get("side") or "").upper()
            ts = d.get("timestamp")
            try:
                e, sl = float(d["entry"]), float(d["sl"])
            except (TypeError, ValueError, KeyError):
                bad["bad_prices"] += 1
                continue
            if not sym or side not in ("BUY", "SELL", "LONG", "SHORT") or not ts:
                bad["bad_fields"] += 1
                continue
            if e <= 0 or sl <= 0:
                bad["nonpositive"] += 1
                continue
            L = side in ("BUY", "LONG")
            if (L and sl >= e) or ((not L) and sl <= e):
                bad["geometry"] += 1
                continue
            try:
                t0 = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            except Exception:
                bad["bad_ts"] += 1
                continue
            day = str(ts)[:10]
            # de-dupe: one per (symbol, side, tier, entry, hour)
            k = (sym, side, d.get("tier"), round(e, 8), str(ts)[:13])
            if k in keep:
                bad["duplicate"] += 1
                continue
            keep.add(k)
            sigs.append({"sym": sym, "side": "LONG" if L else "SHORT", "sl": sl,
                         "t0": t0, "day": day, "tier": d.get("tier")})
    print(f"raw rows {raw} -> usable after validation+dedupe: {len(sigs)}")
    print(f"dropped: {dict(bad)}")
    if not sigs:
        raise SystemExit("nothing usable")

    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    nproc = max(1, min(cpu_count() - 2, len(syms)))
    print(f"symbols {len(syms)}, workers {nproc}/{cpu_count()}", flush=True)

    recs = []
    with Pool(nproc, initializer=init_worker, initargs=(syms,)) as pool:
        for sym, out in pool.imap_unordered(run_symbol, [(s, by[s]) for s in syms]):
            recs.extend(out)
    print(f"simulated {len(recs)} signals")
    if not recs:
        raise SystemExit("none simulated (no candle coverage)")
    days = sorted({r["day"] for r in recs})
    print(f"span {days[0]} -> {days[-1]} ({len(days)} days)")

    dk = f"{DEFAULT[0]}|{DEFAULT[1]}"
    print("\n" + "=" * 92)
    print(f"SNIPER CORPUS — mean R per setup, {HORIZON_H}h horizon, net of fees")
    print("=" * 92)
    print(f"  {'stop x':>7}{'tp 0.5R':>11}{'tp 1.0R':>11}{'tp 1.5R':>11}")
    print("-" * 92)
    for sm in STOP_MULTS:
        row = f"  {sm:>7}"
        for tm in TP_MULTS:
            m = mean_of(recs, f"{sm}|{tm}")
            row += f"{m:>11.4f}" if m is not None else f"{'n/a':>11}"
        row += "   <= bot default at tp1.5R" if sm == 1.0 else ""
        print(row)

    train = [r for r in recs if r["day"] < CUTOFF]
    test = [r for r in recs if r["day"] >= CUTOFF]
    cells = [f"{sm}|{tm}" for sm in STOP_MULTS for tm in TP_MULTS]
    out = {"source": SRC, "usable": len(sigs), "simulated": len(recs),
           "span": [days[0], days[-1]], "dropped": dict(bad)}

    if len(train) > 200 and len(test) > 200:
        tr = sorted(((mean_of(train, c), c) for c in cells), key=lambda x: -(x[0] or -9))
        picked = tr[0][1]
        pt, pd_ = mean_of(test, picked), mean_of(test, dk)
        p, lo, hi = boot_diff(test, picked, dk)
        print(f"\n  OOS: picked on train = stop x{picked.split('|')[0]} tp {picked.split('|')[1]}R")
        print(f"       test picked {pt:+.4f}R vs default {pd_:+.4f}R")
        if p is not None:
            verdict = "HOLDS out of sample" if lo > 0 else "not confirmed (CI spans 0)"
            print(f"       paired diff {p:+.4f}R CI95 [{lo:+.4f},{hi:+.4f}]  <= {verdict}")
            out["oos"] = {"picked": picked, "test_picked_R": round(pt, 4),
                          "test_default_R": round(pd_, 4), "diff_R": round(p, 4),
                          "ci": [round(lo, 4), round(hi, 4)], "holds": bool(lo > 0)}
    else:
        print(f"\n  OOS skipped: train {len(train)} / test {len(test)} too small")

    print("\n  per symbol (stop x8 tp 1.0R vs default):")
    persym = {}
    for sym in sorted({r["sym"] for r in recs}):
        sub = [r for r in recs if r["sym"] == sym]
        if len(sub) < 100:
            continue
        p, lo, hi = boot_diff(sub, "8.0|1.0", dk)
        if p is None:
            continue
        star = "*" if lo > 0 else " "
        print(f"    {sym:<6} n={len(sub):>5}  diff {p:+.4f}R{star} [{lo:+.4f},{hi:+.4f}]")
        persym[sym] = {"n": len(sub), "diff_R": round(p, 4),
                       "ci": [round(lo, 4), round(hi, 4)], "significant": bool(lo > 0)}
    out["per_symbol"] = persym

    xs = [sm for sm in STOP_MULTS if mean_of(recs, f"{sm}|1.0") is not None]
    ys = [mean_of(recs, f"{sm}|1.0") for sm in xs]
    rho = spearman(xs, ys)
    print(f"\n  monotonicity rho(stop_mult, mean_R) = {rho:+.4f}")
    out["monotonicity_rho"] = round(rho, 4)

    with io.open(os.path.join(HERE, "sniper_geometry.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote sniper_geometry.json")


if __name__ == "__main__":
    main()
