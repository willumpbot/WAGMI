"""Walk-forward the geometry finding — the last weakness in our strongest result.

GEOMETRY.md rests on one split (train 2026-02-11..04-15, test 04-16..06-05). A
single split can be lucky, and this is the result we are asking the server to
shadow-trade, so it should face the same expanding-window test that confirmed the
volatility model in 22/22 folds.

Procedure per fold: pick the best (stop_mult, tp_mult) on everything before the
fold, score it on the fold, and compare against (a) the bot's default and (b) the
width-matched fixed control. A finding that survives this is as validated as this
dataset allows.
"""
import json, io, os, csv, gzip, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED, HL = os.path.join(HERE, "candles_merged"), os.path.join(HERE, "candles")
FEE_BPS, HORIZON_H = 9.0, 48
FOLD_DAYS = 14
MIN_TRAIN_DAYS = 25
rng = np.random.default_rng(20261008)
STOPS = (1.0, 2.0, 4.0, 6.0, 8.0, 12.0)
TPS = (0.5, 1.0, 1.5)
DEFAULT = "1.0|1.5"


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


def init(syms):
    for s in syms:
        c = load_candles(s)
        if c:
            CAND[s] = c


def sim(args):
    sym, rows = args
    c = CAND.get(sym)
    if not c:
        return []
    out = []
    for s in rows:
        i0 = ib(c, s["t0"])
        if i0 is None or s["t0"] - c[i0][0] > 7200:
            continue
        entry = c[i0][4]
        base = abs(entry - s["sl"])
        if entry <= 0 or base <= 0:
            continue
        long_ = s["side"] == "LONG"
        bars, k, end = [], i0 + 1, s["t0"] + HORIZON_H * 3600
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if not bars:
            continue
        cells = {}
        for sm in STOPS:
            dist = sm * base
            sl = entry - dist if long_ else entry + dist
            feeR = 2 * (FEE_BPS / 1e4) * entry / dist
            for tm in TPS:
                tp = entry + tm * dist if long_ else entry - tm * dist
                r = None
                for (_, o, h, l, cl) in bars:
                    if (l <= sl) if long_ else (h >= sl):
                        r = -1.0; break
                    if (h >= tp) if long_ else (l <= tp):
                        r = tm; break
                if r is None:
                    last = bars[-1][4]
                    r = ((last - entry) if long_ else (entry - last)) / dist
                cells[f"{sm}|{tm}"] = r - feeR
        out.append({"sym": sym, "day": s["day"], **cells})
    return out


def main():
    sigs = []
    with gzip.open(os.path.join(HERE, "signal_corpus.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            try:
                t0 = pd.Timestamp(d["ts"]).timestamp()
            except Exception:
                continue
            sigs.append({"sym": d["sym"], "side": d["side"], "sl": d["sl"],
                         "t0": t0, "day": d["ts"][:10]})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    n = max(1, min(cpu_count() - 2, len(syms)))
    print(f"{len(sigs)} signals, {len(syms)} symbols, {n} workers", flush=True)
    recs = []
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for out in pool.imap_unordered(sim, [(s, by[s]) for s in syms]):
            recs.extend(out)
    df = pd.DataFrame(recs)
    print(f"simulated {len(df)}", flush=True)

    CELLS = [f"{s}|{t}" for s in STOPS for t in TPS]
    days = sorted(df["day"].unique())
    print(f"days {days[0]} -> {days[-1]} ({len(days)})")

    def paired(sub, a, b, iters=1500):
        cl = collections.defaultdict(list)
        for _, r in sub.iterrows():
            cl[(r["sym"], r["day"])].append(r[a] - r[b])
        keys = list(cl)
        if len(keys) < 3:
            return None, None, None
        point = float(np.mean([x for k in keys for x in cl[k]]))
        ds = np.empty(iters)
        for i in range(iters):
            pick = rng.integers(0, len(keys), len(keys))
            ds[i] = np.mean([x for j in pick for x in cl[keys[j]]])
        ds.sort()
        return point, float(ds[int(.025 * iters)]), float(ds[int(.975 * iters)])

    print("\n" + "=" * 100)
    print(f"WALK-FORWARD GEOMETRY — pick on all prior days, score on the next {FOLD_DAYS}")
    print("=" * 100)
    print(f"  {'fold':<26}{'n':>6}{'picked':>11}{'picked R':>10}{'default R':>11}{'diff':>10}  CI95")
    print("-" * 100)
    folds, wins = [], 0
    i = MIN_TRAIN_DAYS
    while i < len(days):
        trd, ted = set(days[:i]), set(days[i:i + FOLD_DAYS])
        tr, te = df[df["day"].isin(trd)], df[df["day"].isin(ted)]
        i += FOLD_DAYS
        if len(tr) < 500 or len(te) < 100:
            continue
        means = [(float(tr[c].mean()), c) for c in CELLS]
        means.sort(reverse=True)
        pick = means[0][1]
        pr, dr = float(te[pick].mean()), float(te[DEFAULT].mean())
        p, lo, hi = paired(te, pick, DEFAULT)
        if p is None:
            continue
        better = p > 0
        wins += int(better)
        ci = f"[{lo:+.3f},{hi:+.3f}]"
        star = "*" if lo > 0 else " "
        lab = f"{min(ted)}..{max(ted)}"
        print(f"  {lab:<26}{len(te):>6}{pick:>11}{pr:>10.4f}{dr:>11.4f}{p:>+10.4f}{star} {ci}")
        folds.append({"fold": lab, "n": int(len(te)), "picked": pick,
                      "picked_R": round(pr, 4), "default_R": round(dr, 4),
                      "diff_R": round(p, 4), "ci": [round(lo, 4), round(hi, 4)],
                      "better": bool(better), "ci_excludes_0": bool(lo > 0)})
    print("-" * 100)
    if folds:
        d_ = [f["diff_R"] for f in folds]
        sig = sum(1 for f in folds if f["ci_excludes_0"])
        print(f"  folds: {len(folds)}   picked beat default in {wins}/{len(folds)} "
              f"({100*wins/len(folds):.0f}%)   CI excluded 0 in {sig}/{len(folds)}")
        print(f"  mean advantage {np.mean(d_):+.4f}R   median {np.median(d_):+.4f}R   "
              f"worst {min(d_):+.4f}R   best {max(d_):+.4f}R")
        picks = collections.Counter(f["picked"] for f in folds)
        print(f"  cells chosen across folds: {dict(picks)}")
    out = {"fold_days": FOLD_DAYS, "n_folds": len(folds),
           "beat_default": f"{wins}/{len(folds)}" if folds else None,
           "ci_excluded_0": sum(1 for f in folds if f["ci_excludes_0"]) if folds else 0,
           "mean_diff_R": round(float(np.mean([f["diff_R"] for f in folds])), 4) if folds else None,
           "pick_counts": {k: v for k, v in collections.Counter(f["picked"] for f in folds).items()},
           "folds": folds}
    with io.open(os.path.join(HERE, "geometry_walkforward.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote geometry_walkforward.json")


if __name__ == "__main__":
    main()
