"""Stop/target geometry sweep — the one lever the data actually supports.

Finding from REGRADE/VALIDATION: SL-first 53.8% vs TP1-first 17.2% at a designed
R:R of 1.50, i.e. roughly -0.40R per setup from geometry alone, which is larger
than any directional effect measured. That is a parameter problem, so search it.

For every graded signal, re-simulate the trade under a grid of
(stop_mult, tp_mult) applied to the ORIGINAL stop distance, walking real
candles forward bar by bar. Realised R is net of fees on both legs.

  stop_dist' = stop_mult * |entry - sl_original|
  tp'        = entry +/- tp_mult * stop_dist'      (so tp_mult IS the R multiple)

Resolution rules (no lookahead):
  * bars strictly after the signal bar
  * if a bar's range covers both stop and target, count it as a STOP (conservative)
  * unresolved at the horizon -> mark to the close (a time stop)

Parallel across cores; each worker holds its own candle slice.
"""
import json, io, os, gzip, csv, collections, math, random, sys
from multiprocessing import Pool, cpu_count

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(HERE, "candles_merged")
HL = os.path.join(HERE, "candles")
FEE_BPS = 9.0
random.seed(20261008)

# Grid is overridable so the search can be extended without editing code.
# The first pass (stop 0.5-4.0, tp 1.0-4.0) was monotonic right to its boundary
# at stop x4 / tp 1.0R, so the optimum lies outside it -- hence pass 2.
STOP_MULTS = tuple(float(x) for x in
                   (os.environ.get("SWEEP_STOPS") or "0.5,0.75,1.0,1.5,2.0,2.5,3.0,4.0").split(","))
TP_MULTS = tuple(float(x) for x in
                 (os.environ.get("SWEEP_TPS") or "1.0,1.5,2.0,3.0,4.0").split(","))
OUTNAME = os.environ.get("SWEEP_OUT", "geometry_sweep.json")
HORIZON_H = int(os.environ.get("SWEEP_HORIZON", "48"))


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


def to_epoch(ts):
    import datetime
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def idx_at_or_before(c, t):
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
    """Simulate every (stop_mult, tp_mult) for all signals of one symbol."""
    sym, sigs = args
    c = CAND.get(sym)
    if not c:
        return sym, {}, 0
    # key -> list of (day, R)
    acc = collections.defaultdict(list)
    used = 0
    for s in sigs:
        t0 = s["t0"]
        i0 = idx_at_or_before(c, t0)
        if i0 is None or t0 - c[i0][0] > 7200:
            continue
        entry = c[i0][4]
        if entry <= 0:
            continue
        base = abs(entry - s["sl"])
        if base <= 0:
            continue
        long_ = s["side"] == "LONG"
        end = t0 + HORIZON_H * 3600
        # pre-slice the forward bars once per signal
        bars = []
        k = i0 + 1
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if not bars:
            continue
        used += 1
        day = s["day"]
        for sm in STOP_MULTS:
            dist = sm * base
            sl = entry - dist if long_ else entry + dist
            for tm in TP_MULTS:
                tp = entry + tm * dist if long_ else entry - tm * dist
                r = None
                for (_, o, h, l, cl) in bars:
                    if long_:
                        hit_sl, hit_tp = l <= sl, h >= tp
                    else:
                        hit_sl, hit_tp = h >= sl, l <= tp
                    if hit_sl:            # conservative: stop wins ties
                        r = -1.0
                        break
                    if hit_tp:
                        r = tm
                        break
                if r is None:             # time stop at the horizon close
                    last = bars[-1][4]
                    r = ((last - entry) if long_ else (entry - last)) / dist
                # fees: entry + exit, expressed in R
                r -= 2 * (FEE_BPS / 1e4) * entry / dist
                acc[(sm, tm)].append((day, r))
    return sym, {k: v for k, v in acc.items()}, used


def main():
    sigs = []
    with gzip.open(os.path.join(HERE, "signal_corpus.jsonl.gz"), "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            t0 = to_epoch(d["ts"])
            if t0 is None:
                continue
            sigs.append({"sym": d["sym"], "side": d["side"], "sl": d["sl"],
                         "t0": t0, "day": d["ts"][:10]})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    print(f"signals {len(sigs)} across {len(syms)} symbols", flush=True)

    nproc = max(1, min(cpu_count() - 2, len(syms)))
    print(f"workers: {nproc} (of {cpu_count()} logical cores)", flush=True)

    merged = collections.defaultdict(list)
    total_used = 0
    with Pool(nproc, initializer=init_worker, initargs=(syms,)) as pool:
        for sym, acc, used in pool.imap_unordered(run_symbol, [(s, by[s]) for s in syms]):
            total_used += used
            for k, v in acc.items():
                merged[k].extend(v)
            print(f"  done {sym}: {used} signals simulated", flush=True)

    print(f"\nsignals actually simulated: {total_used}")
    if not merged:
        raise SystemExit("nothing simulated")

    def boot(rows, iters=1500):
        cl = collections.defaultdict(list)
        for day, r in rows:
            cl[day].append(r)
        keys = list(cl)
        if len(keys) < 3:
            return None, None
        ms = []
        for _ in range(iters):
            pool_ = []
            for _ in range(len(keys)):
                pool_.extend(cl[keys[random.randrange(len(keys))]])
            if pool_:
                ms.append(sum(pool_) / len(pool_))
        ms.sort()
        return ms[int(.025 * len(ms))], ms[int(.975 * len(ms))]

    rows_out = []
    for (sm, tm), v in merged.items():
        rs = [r for _, r in v]
        n = len(rs)
        mean = sum(rs) / n
        wins = sum(1 for x in rs if x > 0)
        rows_out.append({"stop_mult": sm, "tp_mult": tm, "n": n,
                         "mean_R": mean, "win_rate": 100 * wins / n,
                         "total_R": sum(rs),
                         "n_days": len({d for d, _ in v})})
    rows_out.sort(key=lambda x: -x["mean_R"])

    print("\n" + "=" * 92)
    print(f"GEOMETRY SWEEP — mean realised R per setup, {HORIZON_H}h horizon, net of fees")
    print("  baseline = the bot's own geometry (stop_mult 1.0, tp_mult 1.5)")
    print("=" * 92)
    print(f"  {'stop x':>7}{'tp (R)':>8}{'n':>8}{'days':>6}{'mean R':>10}{'win%':>8}{'total R':>11}")
    print("-" * 92)
    for r in rows_out:
        mark = "  <= bot default" if (r["stop_mult"] == 1.0 and r["tp_mult"] == 1.5) else ""
        print(f"  {r['stop_mult']:>7}{r['tp_mult']:>8}{r['n']:>8}{r['n_days']:>6}"
              f"{r['mean_R']:>10.4f}{r['win_rate']:>8.1f}{r['total_R']:>11.0f}{mark}")

    best = rows_out[0]
    bl = next((r for r in rows_out if r["stop_mult"] == 1.0 and r["tp_mult"] == 1.5), None)
    key = (best["stop_mult"], best["tp_mult"])
    lo, hi = boot(merged[key])
    print(f"\nbest cell: stop x{best['stop_mult']} tp {best['tp_mult']}R -> "
          f"mean {best['mean_R']:+.4f}R  CI95 [{lo:+.4f}, {hi:+.4f}]" if lo is not None
          else f"\nbest cell: {key}")
    if bl:
        blo, bhi = boot(merged[(1.0, 1.5)])
        print(f"bot default: mean {bl['mean_R']:+.4f}R  CI95 [{blo:+.4f}, {bhi:+.4f}]")
        print(f"improvement: {best['mean_R'] - bl['mean_R']:+.4f}R per setup")
    print("\nNOTE: 40 cells scanned; the best cell is selected IN SAMPLE, so its CI is "
          "optimistically biased. Treat as a hypothesis to re-test forward, not a result.")

    with io.open(os.path.join(HERE, OUTNAME), "w", encoding="utf-8") as fh:
        json.dump({"horizon_h": HORIZON_H, "fee_bps": FEE_BPS,
                   "signals_simulated": total_used,
                   "cells": rows_out,
                   "best": best, "bot_default": bl,
                   "caveat": "best cell chosen in-sample across 40 cells; CI optimistic"},
                  fh, indent=1)
    print("\nwrote geometry_sweep.json")


if __name__ == "__main__":
    main()
