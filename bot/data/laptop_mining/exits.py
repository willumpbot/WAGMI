"""Proposal C: exits -- the other half of geometry.

GEOMETRY.md optimised WHERE THE STOP GOES. Nothing has optimised WHEN TO LEAVE A
WINNER, and three results point at it:
  * near targets (0.5R) beat far ones at EVERY stop width, monotonically
  * the server's exit agent showed +$574 vs holding at a 69% hit rate -- but 28 of
    29 were loser-cuts, so the winner side is untested
  * the geometry surface plateaus at ~0, so what is left is in the PATH, not entry

So: hold the stop width fixed at the geometry winner and vary only the exit rule.
A policy counts only if it beats the flat 0.5R target AT THE SAME STOP WIDTH,
paired on identical signals, train-selected and test-scored.

Policies swept:
  fixed target      0.5R / 1.0R / 1.5R / 2.0R
  time stop         exit at 4h / 12h / 24h / 48h regardless
  trail-after       run a trailing stop once +X R is reached (X = 0.25/0.5/1.0)
  breakeven-after   move the stop to entry once +Y R is reached (Y = 0.5/1.0)
  scale-out         half off at 0.5R, remainder trails at 1R distance
"""
import json, io, os, csv, gzip, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED, HL = os.path.join(HERE, "candles_merged"), os.path.join(HERE, "candles")
FEE_BPS = 9.0
STOP_MULT = 8.0           # the geometry plateau; GEOMETRY.md
HORIZON_H = 48
CUTOFF = "2026-04-16"
BASE = "target_0.5R"
rng = np.random.default_rng(20261008)


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


def run_policies(bars, entry, long_, dist):
    """Return {policy: R} for one trade. Stop wins ties; mark to close at horizon."""
    feeR = 2 * (FEE_BPS / 1e4) * entry / dist
    sgn = 1.0 if long_ else -1.0
    res = {}

    def excursion(h, l):
        """R in favour at the bar's best, and R against at its worst."""
        best = (h - entry) / dist if long_ else (entry - l) / dist
        worst = (l - entry) / dist if long_ else (entry - h) / dist
        return best, worst

    # ---- fixed targets ----
    for tm in (0.5, 1.0, 1.5, 2.0):
        r = None
        for (_, o, h, l, cl) in bars:
            b, w = excursion(h, l)
            if w <= -1.0:
                r = -1.0; break
            if b >= tm:
                r = tm; break
        if r is None:
            r = (bars[-1][4] - entry) / dist * sgn
        res[f"target_{tm}R"] = r - feeR

    # ---- pure time stops, stop still active ----
    for hrs in (4, 12, 24, 48):
        r = None
        n = min(hrs, len(bars))
        for (_, o, h, l, cl) in bars[:n]:
            _, w = excursion(h, l)
            if w <= -1.0:
                r = -1.0; break
        if r is None:
            r = (bars[n - 1][4] - entry) / dist * sgn
        res[f"time_{hrs}h"] = r - feeR

    # ---- trail after +X R ----
    for x in (0.25, 0.5, 1.0):
        armed, peak, r = False, 0.0, None
        for (_, o, h, l, cl) in bars:
            b, w = excursion(h, l)
            if not armed and w <= -1.0:
                r = -1.0; break
            if armed:
                # trailing stop sits 1R below the running peak, in R terms
                if w <= peak - 1.0:
                    r = peak - 1.0; break
            if b >= x:
                armed = True
                peak = max(peak, b)
            elif armed:
                peak = max(peak, b)
        if r is None:
            r = (bars[-1][4] - entry) / dist * sgn
        res[f"trail_after_{x}R"] = r - feeR

    # ---- breakeven stop after +Y R ----
    for y in (0.5, 1.0):
        armed, r = False, None
        for (_, o, h, l, cl) in bars:
            b, w = excursion(h, l)
            if not armed and w <= -1.0:
                r = -1.0; break
            if armed and w <= 0.0:
                r = 0.0; break
            if b >= y:
                armed = True
        if r is None:
            r = (bars[-1][4] - entry) / dist * sgn
        res[f"breakeven_after_{y}R"] = r - feeR

    # ---- scale out: half at 0.5R, remainder trails 1R below the peak ----
    half_done, peak, rest, r = False, 0.0, None, None
    for (_, o, h, l, cl) in bars:
        b, w = excursion(h, l)
        if not half_done and w <= -1.0:
            r = -1.0; break
        if half_done:
            peak = max(peak, b)
            if w <= peak - 1.0:
                rest = peak - 1.0; break
        if b >= 0.5 and not half_done:
            half_done = True
            peak = max(peak, b)
    if r is None:
        if not half_done:
            r = (bars[-1][4] - entry) / dist * sgn
        else:
            if rest is None:
                rest = (bars[-1][4] - entry) / dist * sgn
            r = 0.5 * 0.5 + 0.5 * rest
    res["scaleout_half_0.5R"] = r - feeR
    return res


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
        dist = STOP_MULT * base
        bars, k, end = [], i0 + 1, s["t0"] + HORIZON_H * 3600
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if not bars:
            continue
        res = run_policies(bars, entry, s["side"] == "LONG", dist)
        res.update({"sym": sym, "day": s["day"]})
        out.append(res)
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
    print(f"{len(sigs)} signals, stop fixed at x{STOP_MULT}, {n} workers", flush=True)
    recs = []
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for out in pool.imap_unordered(sim, [(s, by[s]) for s in syms]):
            recs.extend(out)
    df = pd.DataFrame(recs)
    print(f"simulated {len(df)}")
    POL = [c for c in df.columns if c not in ("sym", "day")]
    df["half"] = np.where(df["day"] < CUTOFF, "train", "test")
    tr, te = df[df["half"] == "train"], df[df["half"] == "test"]
    print(f"train {len(tr)}  test {len(te)}")

    def paired(sub, a, b, iters=2000):
        cl = collections.defaultdict(list)
        for _, r in sub.iterrows():
            if np.isfinite(r[a]) and np.isfinite(r[b]):
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

    print("\n" + "=" * 104)
    print(f"EXIT POLICY SWEEP — stop fixed at x{STOP_MULT}; baseline = {BASE}")
    print("=" * 104)
    print(f"  {'policy':<24}{'train R':>10}{'test R':>10}{'vs baseline on test':>24}{'verdict':>20}")
    print("-" * 104)
    out = {"stop_mult": STOP_MULT, "baseline": BASE, "cutoff": CUTOFF,
           "n": int(len(df)), "policies": {}}
    rows = []
    for p in sorted(POL):
        a, b = float(tr[p].mean()), float(te[p].mean())
        if p == BASE:
            print(f"  {p:<24}{a:>10.4f}{b:>10.4f}{'(baseline)':>24}{'':>20}")
            out["policies"][p] = {"train_R": round(a, 4), "test_R": round(b, 4),
                                  "baseline": True}
            continue
        d_, lo, hi = paired(te, p, BASE)
        if d_ is None:
            continue
        sig = lo > 0 or hi < 0
        verdict = ("BEATS baseline" if (sig and d_ > 0) else
                   ("worse" if (sig and d_ < 0) else "no difference"))
        print(f"  {p:<24}{a:>10.4f}{b:>10.4f}"
              + f"{d_:>+9.4f} [{lo:+.3f},{hi:+.3f}]".rjust(24)
              + f"{verdict:>20}")
        out["policies"][p] = {"train_R": round(a, 4), "test_R": round(b, 4),
                              "vs_baseline_R": round(d_, 4),
                              "ci": [round(lo, 4), round(hi, 4)],
                              "significant": bool(sig), "verdict": verdict}
        rows.append((p, a, b, d_, sig))

    winners = [r for r in rows if r[4] and r[3] > 0]
    print("\n" + "=" * 104)
    print("VERDICT")
    print("=" * 104)
    if winners:
        for p, a, b, d_, _ in sorted(winners, key=lambda x: -x[3]):
            print(f"  {p}: test {b:+.4f}R, {d_:+.4f}R better than {BASE}")
        out["verdict"] = f"{len(winners)} policy(ies) beat the baseline on test"
    else:
        print(f"  Nothing beats {BASE}. The near target found by GEOMETRY is already the")
        print("  best exit available on this corpus; cleverer exits do not add to it.")
        out["verdict"] = "no exit policy beats the flat 0.5R target"
    print(f"\n  policies compared: {len(rows)}  "
          f"(expect ~{0.05*len(rows):.1f} false positives at p<0.05)")
    with io.open(os.path.join(HERE, "exits.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote exits.json")


if __name__ == "__main__":
    main()
