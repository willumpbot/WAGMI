"""Does the live bot pay the reversal tax on its entries?

THE PREDICTION BEING TESTED, and where it comes from. Two independent panels now agree that the
recent short-horizon cross-sectional WINNER gives a little back:
  - `INTRADAY_DISP.md`  5m, 6 coins, 20 days: 16 of 16 cells negative, 0.4-5.2 bps
  - the 42-coin 1h panel (`horizon_wide.json`): bak1h->fwd1h -3.0 bps z -4.8, ->fwd4h -4.1 bps
    z -3.6. These CLEAR Bonferroni, on a different panel and a different timeframe.

As a standalone strategy that is dead -- 3-4 bps against a 36 bps round trip. But it makes a
falsifiable claim about EXECUTION, which is free: a position opened WITH recent short-term
momentum (long after a run-up, short after a slide) should do slightly worse than one opened
against it. The bot pays that tax or it does not, and its own ledger can say which.

DIRECTION IS PRE-SPECIFIED, not read off the result: signed momentum at entry should be
NEGATIVELY related to net PnL. If it comes out positive, the reversal result does not transfer to
the bot`s holding periods and this test fails to confirm -- which is a real outcome, stated here so
it can happen.

POWER FIRST, because 294 trades is not many and the honest answer may be "cannot tell".
"""
import csv
import glob
import io
import json
import os

import numpy as np

rng = np.random.default_rng(20261011)

LEDGER = os.path.join("server_exports", "trade_ledger.csv")
LOOKBACKS = (1, 4, 24)


def load_panel():
    panel = {}
    for p in sorted(glob.glob(os.path.join("history1h", "*_1h.csv"))):
        sym = os.path.basename(p).replace("_1h.csv", "")
        t, c = [], []
        with io.open(p, encoding="utf-8") as f:
            rd = csv.reader(f)
            next(rd, None)
            for r in rd:
                try:
                    t.append(int(r[0]))
                    c.append(float(r[4]))
                except (ValueError, IndexError):
                    continue
        if len(t) > 500:
            o = np.argsort(np.asarray(t))
            panel[sym] = (np.asarray(t)[o], np.asarray(c)[o])
    return panel


def trades():
    out = []
    with io.open(LEDGER, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.append({
                    "sym": r["symbol"], "side": r["side"].upper(),
                    "ts": int(float(r["timestamp"]) * 1000),
                    "net": float(r["net_pnl"]) if r.get("net_pnl") else None,
                    "rr": float(r["realized_rr"]) if r.get("realized_rr") else None,
                    "hold": float(r["hold_hours"]) if r.get("hold_hours") else None,
                })
            except (ValueError, KeyError, TypeError):
                continue
    return [t for t in out if t["net"] is not None]


def trailing(panel, sym, ts, lb):
    """Return of `sym` over the lb hours ENDING at the last bar at or before ts."""
    if sym not in panel:
        return None
    t, c = panel[sym]
    i = int(np.searchsorted(t, ts, side="right")) - 1
    if i < lb or i >= len(c):
        return None
    return float(c[i] / c[i - lb] - 1.0) * 100.0


def xrank(panel, sym, ts, lb):
    """Percentile rank of sym`s trailing return among all coins with data at that bar."""
    vals = []
    me = None
    for s in panel:
        v = trailing(panel, s, ts, lb)
        if v is None:
            continue
        vals.append(v)
        if s == sym:
            me = v
    if me is None or len(vals) < 20:
        return None
    return float(np.mean(np.asarray(vals) < me))


def day_boot(x, y, iters=4000):
    """Bootstrap the slope by resampling DAYS, since several trades share a day."""
    if len(x) < 30:
        return (float("nan"),) * 3
    days = {}
    for i in range(len(x)):
        days.setdefault(int(x[i][1]), []).append(i)
    keys = list(days)
    xs = np.asarray([a for a, _d in x], dtype=float)
    ms = np.empty(iters)
    for b in range(iters):
        pick = rng.integers(0, len(keys), len(keys))
        idx = np.concatenate([days[keys[j]] for j in pick])
        xa, ya = xs[idx], y[idx]
        if xa.std() == 0:
            ms[b] = 0.0
        else:
            ms[b] = np.polyfit(xa, ya, 1)[0]
    ms.sort()
    slope = np.polyfit(xs, y, 1)[0] if xs.std() else float("nan")
    return float(slope), float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


def main():
    panel = load_panel()
    tr = trades()
    print("ENTRY TIMING -- does the bot pay the reversal tax?")
    print("  %d closed trades with net PnL, panel of %d coins" % (len(tr), len(panel)))
    print()
    print("  PRE-SPECIFIED DIRECTION: signed momentum at entry should be NEGATIVELY related to")
    print("  net PnL. A positive slope means the reversal result does not transfer, and that is")
    print("  a real outcome, not a failure of the test.")
    print()

    out = {}
    for lb in LOOKBACKS:
        rows = []
        for t in tr:
            m = trailing(panel, t["sym"], t["ts"], lb)
            if m is None:
                continue
            sgn = 1.0 if t["side"] == "LONG" else -1.0
            rows.append({"signed_mom": m * sgn, "net": t["net"], "rr": t["rr"],
                         "day": t["ts"] // 86_400_000, "sym": t["sym"], "side": t["side"]})
        if len(rows) < 40:
            print("  lb %dh: only %d matched trades, skipping" % (lb, len(rows)))
            continue
        sm = np.asarray([r["signed_mom"] for r in rows])
        net = np.asarray([r["net"] for r in rows])
        x = [(r["signed_mom"], r["day"]) for r in rows]
        slope, lo, hi = day_boot(x, net)
        se = (hi - lo) / 3.92 if hi == hi else float("nan")
        ndays = len({r["day"] for r in rows})
        mde = 2.8 * se if se == se else float("nan")

        # tercile view -- the same thing without assuming linearity
        q = np.quantile(sm, [1 / 3, 2 / 3])
        terc = [net[sm <= q[0]], net[(sm > q[0]) & (sm <= q[1])], net[sm > q[1]]]
        print("  lookback %dh  %d trades, %d distinct days" % (lb, len(rows), ndays))
        print("    with-momentum entries (signed mom > 0): %d of %d = %.0f%%"
              % (int((sm > 0).sum()), len(sm), 100.0 * (sm > 0).mean()))
        print("    slope of net PnL on signed momentum: %+.3f  CI95 [%+.3f, %+.3f]  MDE %.3f"
              % (slope, lo, hi, mde))
        print("    mean net PnL by signed-momentum tercile:")
        for nm, g in zip(("against (lowest)", "middle", "with (highest)"), terc):
            print("      %-18s n=%3d  mean net %+8.2f  median %+8.2f  win %.0f%%"
                  % (nm, len(g), g.mean(), np.median(g), 100.0 * (g > 0).mean()))
        ci_excl = (lo > 0) or (hi < 0)
        print("    CI excludes zero: %s%s" % (ci_excl,
              "  <-- and the sign is as predicted" if ci_excl and slope < 0 else
              ("  <-- but the sign is OPPOSITE to the prediction" if ci_excl else "")))
        print()
        out[f"lb{lb}h"] = {
            "n_trades": len(rows), "n_days": ndays,
            "pct_with_momentum": round(100.0 * float((sm > 0).mean()), 1),
            "slope": round(float(slope), 4), "ci": [round(lo, 4), round(hi, 4)],
            "mde": None if mde != mde else round(float(mde), 4),
            "ci_excludes_zero": bool(ci_excl),
            "sign_as_predicted": bool(ci_excl and slope < 0),
            "terciles": [{"mean": round(float(g.mean()), 2),
                          "median": round(float(np.median(g)), 2),
                          "n": int(len(g)),
                          "winrate": round(100.0 * float((g > 0).mean()), 1)} for g in terc],
        }
    json.dump(out, open("entry_timing.json", "w"), indent=1)
    any_sig = [k for k, v in out.items() if v["ci_excludes_zero"]]
    print("=" * 78)
    print("CI EXCLUDES ZERO AT: %s" % (any_sig or "no lookback"))
    if not any_sig:
        print("With %d trades this cannot resolve an effect of the size the panels imply"
              % len(tr))
        print("(3-4 bps per hour). That is a POWER statement, not evidence of no effect.")
    print("=" * 78)


if __name__ == "__main__":
    main()
