"""Mission 10 - do the bot's size-flags predict a bigger next-day |move| than unflagged coins with the
SAME HAR forecast? If yes the flag is a real sizing input; if not (it just picks volatile coins), demote.
Value-add over the server's scan_grades.json (which reports flagged |move| but NO HAR-matched baseline):
the flag's EXCESS over HAR. Method: pooled regression realised_1d_|move| ~ a + b*HAR + c*flag, per flag,
day-block-clustered CI on c. c>0 & CI excludes 0 -> adds beyond HAR. HAR proxy = mean(|ret|_1d,
mean|ret|_5d, mean|ret|_22d) at the firing bar (point-in-time). Only 8 days of firings -> day-cluster CI
is thin; UNDERPOWERED is a legitimate verdict.
"""
import io, json, os, sqlite3, datetime
import numpy as np
from m30_run import rng

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
SCAN = os.path.join(HERE, "server_exports", "scan_log.jsonl")
FLAGS = ["volume_surge", "funding_hot", "funding_cold", "vol_expanding", "on_20d_low", "above_20d_high", "ma50_pullback", "momentum_small"]


def main():
    firings = [json.loads(l) for l in io.open(SCAN, encoding="utf-8") if l.strip()]
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    have = set(r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h"))
    cand = {}
    for coin in set(f["coin"] for f in firings):
        if coin in have:
            cand[coin] = np.asarray(c.execute("SELECT t,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall(), float)
    c.close()

    def har_and_realised(coin, ts_ms):
        a = cand.get(coin)
        if a is None:
            return None, None
        t, cl = a[:, 0], a[:, 1]
        i = int(np.searchsorted(t, ts_ms))
        if i < 22 * 24 or i + 24 >= len(t):
            return None, None
        px = cl[i]
        realised = abs(cl[i + 24] / px - 1.0) * 100.0
        # daily |returns| from hourly closes sampled every 24 bars, trailing
        d1 = abs(cl[i] / cl[i - 24] - 1.0) * 100.0
        d5 = np.mean([abs(cl[i - k * 24] / cl[i - (k + 1) * 24] - 1.0) for k in range(5)]) * 100.0
        d22 = np.mean([abs(cl[i - k * 24] / cl[i - (k + 1) * 24] - 1.0) for k in range(22)]) * 100.0
        har = (d1 + d5 + d22) / 3.0
        return har, realised

    # build the per-(coin,day) panel: for each firing day, each scanned coin is flagged or not for each flag.
    # scan_log gives one row per (coin,flag,ts); a coin's universe that day = the 'universe' dict keys.
    by_day = {}
    for f in firings:
        by_day.setdefault(f["day"], {"universe": set(), "flagged": {}, "ts": f["ts"]})
        by_day[f["day"]]["universe"].update(f.get("universe", {}).keys())
        by_day[f["day"]]["flagged"].setdefault(f["flag"], set()).add(f["coin"])
        by_day[f["day"]]["ts"] = f["ts"]

    # rows: coin, day, har, realised, {flag: 0/1}
    rows = []
    for day, d in by_day.items():
        ts_ms = d["ts"] * 1000.0
        for coin in d["universe"]:
            har, real = har_and_realised(coin, ts_ms)
            if har is None or not np.isfinite(har) or not np.isfinite(real):
                continue
            rr = {"coin": coin, "day": day, "har": har, "real": real}
            for fl in FLAGS:
                rr[fl] = 1.0 if coin in d["flagged"].get(fl, set()) else 0.0
            rows.append(rr)
    har = np.array([r["har"] for r in rows]); real = np.array([r["real"] for r in rows])
    days = np.array([r["day"] for r in rows])
    print("Mission 10: size-flags excess over HAR. coin-days=%d, days=%d, coins with candles=%d"
          % (len(rows), len(set(days)), len(cand)))
    print("  (pooled: realised_1d|move| ~ a + b*HAR + c*flag; c = EXCESS over HAR; day-block CI)\n")

    out = {"n_coindays": len(rows), "n_days": len(set(days)), "flags": {}}
    for fl in FLAGS:
        x = np.array([r[fl] for r in rows])
        if x.sum() < 10:
            print("  %-15s n_flag=%-3d  (too few, skip)" % (fl, int(x.sum()))); continue
        X = np.column_stack([np.ones(len(har)), har, x])
        beta = np.linalg.lstsq(X, real, rcond=None)[0]
        ud = np.unique(days)
        bc = []
        for _ in range(3000):
            pick = ud[rng.integers(0, len(ud), len(ud))]
            idx = np.concatenate([np.flatnonzero(days == p) for p in pick])
            try:
                bc.append(np.linalg.lstsq(X[idx], real[idx], rcond=None)[0][2])
            except Exception:
                pass
        bc = np.array(bc); lo, hi = np.percentile(bc, [2.5, 97.5])
        fm = real[x > 0.5].mean(); um = real[x < 0.5].mean()
        verdict = "REAL sizing input (adds over HAR)" if lo > 0 else "worse than HAR" if hi < 0 else "NO excess over HAR -> DEMOTE/size-neutral" if abs((hi - lo)) < 2.0 else "UNDERPOWERED"
        print("  %-15s n_flag=%-3d | flagged|move| %.2f%% vs unflagged %.2f%% | EXCESS c=%+.2f%% [%+.2f,%+.2f] -> %s"
              % (fl, int(x.sum()), fm, um, beta[2], lo, hi, verdict))
        out["flags"][fl] = {"n_flag": int(x.sum()), "flagged_move": float(fm), "unflagged_move": float(um),
                            "excess_over_har": float(beta[2]), "lo": float(lo), "hi": float(hi), "verdict": verdict}
    io.open(os.path.join(HERE, "m10_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("\nwrote m10_result.json. Note: 8 firing-days -> day-block CIs are wide; treat positives as")
    print("candidates needing more days, and a tight CI around 0 as a real DEMOTE.")


if __name__ == "__main__":
    main()
