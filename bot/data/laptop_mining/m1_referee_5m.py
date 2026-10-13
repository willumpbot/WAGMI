"""M1 phase 2 — 5m REFEREE. How often does the 1h engine get the exit wrong?

WHY THIS EXISTS. M1's table is built on 1h bars, and 1h cannot order two touches inside one bar. On
1.66% stops earlier tonight, 1h contradicted 5m on 22% of cases. M1's tightest stops (K=1.0, ~350 bps
average) are in comparable territory, so no K=1.0 number is believable until the disagreement rate is
MEASURED rather than assumed.

DESIGN. Same entries, two referees:
  * entries are taken on 1h boundaries inside the 5m window, so both engines see the SAME entry bar,
    the SAME entry price and the SAME stop/target geometry (K x fitted exp_move);
  * the 1h engine walks 72 one-hour bars; the 5m engine walks 864 five-minute bars over the identical
    wall-clock span;
  * for each entry we ask whether the two agree on WHAT HAPPENED (stop first, target first, or
    neither) and on the realised net bps.

The 5m answer is treated as the truth, because a finer grid can only resolve ordering the coarse grid
had to guess. Where they disagree the 1h engine is wrong by construction.

OUTPUT per (K, rule): ordering-disagreement rate, mean signed bps error of the 1h engine (does 1h
flatter or punish the rule?), and the implied correction. If the error is large and one-signed at
K=1.0, M1's K=1.0 rows must be discarded rather than corrected.

Coverage: candles_5m holds 72 coins, 2026-09-22..2026-10-13 (~21 days), so this is a SMALL window.
It cannot validate M1's magnitudes -- only its refereeing.
"""
import collections
import io
import json
import math
import os
import sqlite3
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
EPS = 1e-8
H1 = 72                 # hours
H5 = 72 * 12            # 5m bars over the same span
FEE_BPS = 9.0
K_SET = (1.0, 1.5, 2.0)
RULES = ("stop_only", "tgt_1R", "tgt_2R")
ENTRIES = 250
rng = np.random.default_rng(20261013)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def fetch(coin, table):
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    rows = c.execute("SELECT t,h,l,c FROM %s WHERE coin=? ORDER BY t" % table, (coin,)).fetchall()
    c.close()
    if not rows:
        return None
    a = np.asarray(rows, float)
    return {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


def em_by_day(b1):
    day = (b1["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    close = np.array([b1["c"][i] for i in np.append(first[1:], len(b1["c"])) - 1])
    if len(close) < 40:
        return None
    rets = np.concatenate(([0.0], (close[1:] / close[:-1] - 1.0) * 100.0))
    em = {}
    for i in range(30, len(uniq)):
        rv1, rv5, rv22 = abs(rets[i]), sd(list(rets[i - 4:i + 1])), sd(list(rets[i - 21:i + 1]))
        if rv5 <= 0 or rv22 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        v = math.exp(z) * Y1S
        if v > 0:
            em[int(uniq[i])] = v
    return em


def first_touch(hi, lo, side, stop_px, tgt_px):
    """Index of first stop touch and first target touch along one path (HORIZON if never)."""
    if side > 0:
        s = np.flatnonzero(lo <= stop_px)
        t = np.flatnonzero(hi >= tgt_px) if tgt_px is not None else np.array([], int)
    else:
        s = np.flatnonzero(hi >= stop_px)
        t = np.flatnonzero(lo <= tgt_px) if tgt_px is not None else np.array([], int)
    return (s[0] if len(s) else 10 ** 9), (t[0] if len(t) else 10 ** 9)


def outcome(sb, tb, tR, last_close, entry, side, Rpx):
    """Gross in R. Same-bar ties resolve to the STOP on the COARSE grid only (see M1)."""
    if sb == 10 ** 9 and tb == 10 ** 9:
        return (last_close - entry) * side / Rpx
    if tb < sb:
        return tR if tR is not None else (last_close - entry) * side / Rpx
    return -1.0


def main():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute(
        "SELECT coin FROM candles_5m GROUP BY coin HAVING COUNT(*)>2000 ORDER BY coin")]
    c.close()
    print("5m referee: %d coins with >2000 five-minute bars" % len(coins))
    agg = collections.defaultdict(lambda: {"n": 0, "disagree": 0, "err": []})
    t0 = time.time()
    for ci, coin in enumerate(coins):
        b5 = fetch(coin, "candles_5m")
        b1 = fetch(coin, "candles_1h")
        if b5 is None or b1 is None or len(b5["c"]) < H5 + 50:
            continue
        em = em_by_day(b1)
        if not em:
            continue
        # 1h bars that sit inside the 5m window and have room for a full 72h path on BOTH grids
        t5_lo, t5_hi = b5["t"][0], b5["t"][-1]
        cand = np.flatnonzero((b1["t"] >= t5_lo) & (b1["t"] + H1 * 3600000 <= t5_hi))
        cand = cand[[int(b1["t"][i] // 86400000) in em for i in cand]]
        if len(cand) < 30:
            continue
        pick = rng.choice(cand, size=min(ENTRIES, len(cand)), replace=False)
        for i in pick:
            entry = b1["c"][i]
            emv = em[int(b1["t"][i] // 86400000)] / 100.0 * entry
            side = 1.0 if rng.random() < 0.5 else -1.0
            # the 5m path over the identical wall-clock span
            j0 = int(np.searchsorted(b5["t"], b1["t"][i], side="right"))
            j1 = j0 + H5
            if j1 >= len(b5["c"]):
                continue
            h1s, l1s, c1s = b1["h"][i + 1:i + 1 + H1], b1["l"][i + 1:i + 1 + H1], b1["c"][i + H1]
            h5s, l5s, c5s = b5["h"][j0:j1], b5["l"][j0:j1], b5["c"][j1 - 1]
            if len(h1s) < H1:
                continue
            for K in K_SET:
                Rpx = K * emv
                stop_px = entry - side * Rpx
                for rule in RULES:
                    tR = None if rule == "stop_only" else float(rule[4:-1])
                    tgt_px = None if tR is None else entry + side * tR * Rpx
                    s1, t1 = first_touch(h1s, l1s, side, stop_px, tgt_px)
                    s5, t5 = first_touch(h5s, l5s, side, stop_px, tgt_px)
                    g1 = outcome(s1, t1, tR, c1s, entry, side, Rpx)
                    g5 = outcome(s5, t5, tR, c5s, entry, side, Rpx)
                    lab1 = "stop" if (s1 < t1 and s1 < 10 ** 9) else (
                        "tgt" if t1 < 10 ** 9 else "none")
                    lab5 = "stop" if (s5 < t5 and s5 < 10 ** 9) else (
                        "tgt" if t5 < 10 ** 9 else "none")
                    k = (K, rule)
                    agg[k]["n"] += 1
                    if lab1 != lab5:
                        agg[k]["disagree"] += 1
                    r_bps = (Rpx / entry) * 1e4
                    agg[k]["err"].append((g1 - g5) * r_bps)
        if (ci + 1) % 15 == 0:
            print("  %d/%d coins (%.1f min)" % (ci + 1, len(coins), (time.time() - t0) / 60),
                  flush=True)
    print("\n%-6s %-12s %8s %12s %14s %14s" % ("K", "rule", "n", "disagree%", "1h bias bps",
                                               "abs err bps"))
    out = []
    for (K, rule) in sorted(agg):
        a = agg[(K, rule)]
        if a["n"] < 100:
            continue
        err = np.asarray(a["err"], float)
        row = {"K": K, "rule": rule, "n": a["n"],
               "disagree_pct": 100.0 * a["disagree"] / a["n"],
               "bias_bps": float(np.mean(err)), "abs_err_bps": float(np.mean(np.abs(err)))}
        out.append(row)
        print("%-6.1f %-12s %8d %11.1f%% %+14.1f %14.1f"
              % (K, rule, row["n"], row["disagree_pct"], row["bias_bps"], row["abs_err_bps"]))
    io.open(os.path.join(HERE, "m1_referee_5m.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote m1_referee_5m.json")
    print("1h bias > 0 means the 1h engine FLATTERS the rule (reports better than 5m truth).")


if __name__ == "__main__":
    main()
