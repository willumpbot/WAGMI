"""ADX_MIN_TRENDING — the last live, never-examined knob. POWER FIRST.

CONFIG_AUDIT.md established that of the three knobs the July swarm recommended, two are closed:
ENSEMBLE_CONFIDENCE_FLOOR is backtest-only (the live floor is AdaptiveConfidenceFloor) and
TIME_STOP_HOURS should be left alone. ADX_MIN_TRENDING is the only one that is BOTH live and never
tested. Its consumers are in bot/strategies/, not bot/backtest/:

    bot/strategies/regime_trend.py:271        if adx_val < self.adx_min_trending: (penalty)
    bot/strategies/confidence_scorer.py:556   _adx_thresh = _TC().adx_min_trending
    bot/strategies/multi_tier_quality.py:226  _adx_thresh = _TC().adx_min_trending

Currently 10.0 (trading_config.py:263). The in-code comment says it was LOWERED 15 -> 10 because
"crypto ranges with ADX 10-15 very frequently" and "ADX 15 was blocking too many" (needed 30+ trades
for walk-forward validity). The July swarm recommended raising it to gate >60. Those two rationales
point in opposite directions, which is exactly why it needs a number.

ADX replicated from the bot's own definition, bot/core/quant_regime.py:62 -- note it uses EMA
smoothing of +DM/-DM/TR (NOT Wilder's), period 14, on 1h candles (quant_regime.py:19 passes
candles_1h). Matching the bot matters more than matching the textbook.

=== WHY THIS SCRIPT LEADS WITH POWER ===
Five findings today needed revision and three of them failed the same way: a test with no power
reported as "no effect". The signal corpus is only 14 ISO weeks (2026-02-11 -> 06-05), so
week-clustered inference on bucketed subsets is weak by construction.

So this script computes the MINIMUM DETECTABLE EFFECT **before** it computes the comparison, using a
lag placebo (shift each coin's signal times within that coin, preserving count and clustering).
If the MDE is larger than any plausible effect, the honest output is "UNMEASURABLE" and the
comparison is reported as descriptive only, with that label attached. The script says so itself
rather than leaving it to the write-up.
"""
import json, io, os, gzip, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

from geometry_v2 import load_candles, first_after, FEE_BPS, HERE

HORIZON_H = 48
ADX_PERIOD = 14
PLACEBO_SETS = 150
rng = np.random.default_rng(20261009)
CAND = {}


def ema_list(v, n):
    """EMA as bot/core/quant_regime.py uses it (seeded on the first value)."""
    if not v:
        return []
    k = 2.0 / (n + 1)
    out, e = [], v[0]
    for x in v:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def adx_series(c, period=ADX_PERIOD):
    """ADX at every bar, replicating quant_regime._adx (EMA-smoothed, not Wilder).
    c = list of (t, o, h, l, close). Returns a list the same length, None before warm-up."""
    n = len(c)
    tr, pdm, mdm = [0.0], [0.0], [0.0]
    for i in range(1, n):
        h, l, pc = c[i][2], c[i][3], c[i - 1][4]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        up = c[i][2] - c[i - 1][2]
        dn = c[i - 1][3] - c[i][3]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
    sp, sm, st = ema_list(pdm[1:], period), ema_list(mdm[1:], period), ema_list(tr[1:], period)
    out = [None] * n
    dx = []
    for j in range(len(st)):
        if st[j] <= 0:
            dx.append(None)
            continue
        pdi = 100.0 * sp[j] / st[j]
        mdi = 100.0 * sm[j] / st[j]
        s = pdi + mdi
        dx.append(100.0 * abs(pdi - mdi) / s if s > 0 else None)
    good = [x for x in dx if x is not None]
    if len(good) < period * 2:
        return out
    sdx = ema_list(dx, period) if all(x is not None for x in dx) else None
    if sdx is None:
        # fall back: smooth only the contiguous valid tail
        vals, idx = [], []
        for j, x in enumerate(dx):
            if x is not None:
                vals.append(x); idx.append(j)
        sm2 = ema_list(vals, period)
        for k, j in enumerate(idx):
            out[j + 1] = sm2[k]
        return out
    for j in range(len(sdx)):
        out[j + 1] = sdx[j]
    return out


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
    adx = adx_series(c)
    out = []
    for s in rows:
        i0 = first_after(c, s["t0"])
        if i0 is None or c[i0][0] - s["t0"] > 3600:
            continue
        a = adx[i0 - 1] if i0 >= 1 else None        # ADX known BEFORE the entry bar
        if a is None or not np.isfinite(a):
            continue
        entry = c[i0][1]
        base = s["base"]
        if entry <= 0 or base <= 0:
            continue
        long_ = s["side"] == "LONG"
        sl = entry - base if long_ else entry + base
        tp = s["tp"]
        if tp is None or (long_ and tp <= entry) or ((not long_) and tp >= entry):
            tp = entry + (1.0 if long_ else -1.0) * base      # fall back to 1R
        feeR = 2 * (FEE_BPS / 1e4) * entry / base
        end = s["t0"] + HORIZON_H * 3600
        r = None
        k = i0 + 1
        while k < len(c) and c[k][0] <= end:
            _, o, h, l, cl = c[k]
            hs = (l <= sl) if long_ else (h >= sl)
            ht = (h >= tp) if long_ else (l <= tp)
            if hs:
                r = -1.0; break
            if ht:
                r = abs(tp - entry) / base; break
            k += 1
        if r is None:
            last = c[min(k, len(c) - 1)][4]
            r = ((last - entry) if long_ else (entry - last)) / base
        out.append({"sym": sym, "day": s["day"], "week": s["week"], "adx": float(a),
                    "r": r - feeR, "conf": s["conf"], "strategy": s["strategy"]})
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
                base = abs(float(d["entry"]) - float(d["sl"]))
            except Exception:
                continue
            if base <= 0:
                continue
            day = d["ts"][:10]
            w = datetime.date.fromisoformat(day).isocalendar()
            try:
                tp = float(d.get("tp1"))
            except (TypeError, ValueError):
                tp = None
            sigs.append({"sym": d["sym"], "side": d["side"], "base": base, "t0": t0, "tp": tp,
                         "day": day, "week": f"{w[0]}-W{w[1]:02d}",
                         "conf": float(d.get("conf") or 0), "strategy": d.get("strategy") or "?"})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    n = max(1, min(cpu_count() - 2, len(syms)))
    print(f"{len(sigs)} signals, {len(syms)} symbols, ADX(14) EMA-smoothed on 1h "
          f"(matching quant_regime._adx)", flush=True)
    recs = []
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for o in pool.imap_unordered(sim, [(s, by[s]) for s in syms]):
            recs.extend(o)
    df = pd.DataFrame(recs)
    print(f"usable: {len(df)} signals with ADX + outcome, {df['week'].nunique()} ISO weeks, "
          f"{df['day'].min()} -> {df['day'].max()}\n")

    out = {"n": int(len(df)), "weeks": int(df["week"].nunique()),
           "adx_period": ADX_PERIOD, "horizon_h": HORIZON_H,
           "current_setting": 10.0, "swarm_proposal": 60.0}

    print("=" * 100)
    print("ADX DISTRIBUTION — can the proposed gate even be reached?")
    print("=" * 100)
    qs = [0, 10, 25, 50, 75, 90, 95, 99, 100]
    pv = np.percentile(df["adx"], qs)
    print("  " + "  ".join(f"p{q}={v:.1f}" for q, v in zip(qs, pv)))
    for thr in (10, 15, 20, 25, 40, 60):
        share = 100 * float((df["adx"] >= thr).mean())
        print(f"  ADX >= {thr:<3} keeps {share:>5.1f}% of signals  ({int(share/100*len(df))} of {len(df)})")
        out.setdefault("share_kept_pct", {})[str(thr)] = round(share, 2)

    def wk(v, w):
        byw = collections.defaultdict(list)
        for a, b in zip(v, w):
            byw[b].append(a)
        mus = np.array([np.mean(x) for x in byw.values()])
        if len(mus) < 4:
            return float("nan"), float("nan"), len(mus)
        se = float(mus.std(ddof=1)) / math.sqrt(len(mus))
        return float(mus.mean()), se, len(mus)

    # ---------------- POWER FIRST ----------------
    print("\n" + "=" * 100)
    print("POWER FIRST — what difference in mean R could this sample detect?")
    print("  lag placebo: shift each coin's signal times within that coin (count + clustering kept)")
    print("=" * 100)
    pos = {s: list(range(len(by[s]))) for s in syms}
    bysym = collections.defaultdict(list)
    for r in recs:
        bysym[r["sym"]].append(r)
    det = collections.Counter()
    for _ in range(PLACEBO_SETS):
        hi, lo = [], []
        for s, rows in bysym.items():
            if len(rows) < 20:
                continue
            L = int(rng.integers(5, len(rows)))
            sh = rows[L:] + rows[:L]
            # assign the REAL adx ordering to SHIFTED outcomes -> no real relationship
            a = np.array([x["adx"] for x in rows])
            med = np.median(a)
            for x, av in zip(sh, a):
                (hi if av >= med else lo).append(x)
        for delta in (0.0, 0.05, 0.10, 0.20, 0.40):
            hv = [x["r"] + delta for x in hi]
            lv = [x["r"] for x in lo]
            hw = [x["week"] for x in hi]
            lw = [x["week"] for x in lo]
            m1, s1, _ = wk(hv, hw)
            m0, s0, _ = wk(lv, lw)
            if not np.isfinite(s1) or not np.isfinite(s0):
                continue
            se = math.sqrt(s1 ** 2 + s0 ** 2)
            if (m1 - m0) - 1.96 * se > 0:
                det[delta] += 1
    print(f"  {'injected R':>12}{'detection rate':>18}")
    for delta in (0.0, 0.05, 0.10, 0.20, 0.40):
        rate = det[delta] / PLACEBO_SETS
        tag = "   <- SIZE (want ~0.05)" if delta == 0 else ""
        print(f"  {delta:>12.2f}{rate:>18.3f}{tag}")
        out.setdefault("power", {})[str(delta)] = round(rate, 3)
    size = det[0.0] / PLACEBO_SETS
    mde = next((d for d in (0.05, 0.10, 0.20, 0.40) if det[d] / PLACEBO_SETS >= 0.8), None)
    ok = 0.01 <= size <= 0.12
    print(f"\n  size {size:.3f} -> {'calibrated' if ok else 'MISCALIBRATED, design void'}")
    print(f"  80%-power MDE: {str(mde)+'R' if mde else 'NOT REACHED within 0.40R'}")
    out["size"] = size
    out["mde80_R"] = mde
    out["design_valid"] = bool(ok)

    # ---------------- the comparison, labelled by what the power allows ----------------
    print("\n" + "=" * 100)
    print("THE COMPARISON — mean R by ADX bucket (bot's own bracket, net 9bps, 48h)")
    print("=" * 100)
    edges = [0, 10, 15, 20, 25, 40, 1e9]
    print(f"  {'ADX bucket':>14}{'n':>7}{'mean R':>10}{'week mean':>11}{'week se':>10}{'week t':>9}")
    print("-" * 100)
    rowsout = {}
    for a, b in zip(edges[:-1], edges[1:]):
        sub = df[(df["adx"] >= a) & (df["adx"] < b)]
        if len(sub) < 50:
            continue
        m, se, nw = wk(sub["r"].values, sub["week"].values)
        lab = f"{a:.0f}-{b:.0f}" if b < 1e8 else f"{a:.0f}+"
        print(f"  {lab:>14}{len(sub):>7}{sub['r'].mean():>+10.4f}{m:>+11.4f}{se:>10.4f}"
              f"{(m/se if se else float('nan')):>9.2f}")
        rowsout[lab] = {"n": int(len(sub)), "mean_r": round(float(sub["r"].mean()), 4),
                        "week_mean": round(m, 4), "week_se": round(se, 4),
                        "week_t": round(m / se, 2) if se else None, "weeks": nw}
    out["buckets"] = rowsout

    # the actual decision: gate at 10 (now) vs higher
    print(f"\n  {'gate':>8}{'kept':>8}{'mean R kept':>13}{'mean R blocked':>16}"
          f"{'difference':>12}{'week se':>10}{'week t':>9}  verdict")
    print("-" * 100)
    for thr in (15, 20, 25, 40, 60):
        kept = df[df["adx"] >= thr]
        blocked = df[(df["adx"] >= 10) & (df["adx"] < thr)]
        if len(kept) < 50 or len(blocked) < 50:
            print(f"  {thr:>8}{len(kept):>8}   too few on one side")
            continue
        m1, s1, _ = wk(kept["r"].values, kept["week"].values)
        m0, s0, _ = wk(blocked["r"].values, blocked["week"].values)
        se = math.sqrt(s1 ** 2 + s0 ** 2)
        d = m1 - m0
        sig = (d - 1.96 * se) > 0
        v = ("gate HELPS" if sig else
             ("unmeasurable" if (mde is None or abs(d) < mde) else "no help"))
        print(f"  {thr:>8}{len(kept):>8}{m1:>+13.4f}{m0:>+16.4f}{d:>+12.4f}{se:>10.4f}"
              f"{(d/se if se else float('nan')):>9.2f}  {v}")
        out.setdefault("gates", {})[str(thr)] = {
            "n_kept": int(len(kept)), "n_blocked": int(len(blocked)),
            "mean_r_kept": round(m1, 4), "mean_r_blocked": round(m0, 4),
            "difference": round(d, 4), "week_se": round(se, 4),
            "week_t": round(d / se, 2) if se else None, "significant": bool(sig)}

    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    anysig = any(v.get("significant") for v in out.get("gates", {}).values())
    if not ok:
        out["verdict"] = "design void (placebo size miscalibrated)"
    elif anysig:
        out["verdict"] = "at least one higher gate significantly improves mean R"
    elif mde is None:
        out["verdict"] = ("UNMEASURABLE: 14 weeks of signals cannot resolve a gate effect "
                          "even at 0.40R, so no recommendation either way")
    else:
        out["verdict"] = (f"no gate beats the current 10 by more than the {mde}R this sample "
                          f"can detect; raising it is unsupported, not disproven")
    print(f"  {out['verdict']}")
    print(f"\n  (current setting 10.0; the July swarm proposed >60, which keeps "
          f"{out['share_kept_pct'].get('60')}% of signals)")
    with io.open(os.path.join(HERE, "adx_gate.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote adx_gate.json")


if __name__ == "__main__":
    main()
