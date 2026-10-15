"""PRE-REGISTERED re-test (2026-10-16 prereg, run 2026-10-15 at ~260 calls) of CHIEF_GRADEABLE.md's
levels question: are the chief's named INVALIDATION PRICE LEVELS touched LESS often than random levels
at the SAME distance, under the correct TIME-MATCHED null?

Reproduces CHIEF_GRADEABLE's method (which the superseded m9_chief.py only did with the CONFOUNDED
random-TIME null). Definitions confirmed against CHIEF_GRADEABLE.md and m9_chief.py:
  - levels parsed from `invalidation` text, commas stripped, kept if 0.3% <= |d| <= 20% of call price.
  - touch over H in {12,24,48} 1h bars after the call: up level high>=lvl; down level low<=lvl;
    forward window = bars i+1 .. i+H (i = searchsorted(candle t ms, call ts*1000)).
  - TIME-MATCHED NULL: same symbol, SAME signed distance & side, but the reference bar is drawn
    randomly from the LOCAL REGIME around the call (+/- WREG bars). This holds distance/side EXACTLY
    (the whole point) while letting the regime at the call moment stand in for the chief's specific
    level, and is a minimal restriction of the confounded null (which drew from all history).
    NULLDRAW draws per level, averaged.
  - SIDE-FLIP control: same moment (same path, bars i+1..i+H), same |distance|, OPPOSITE side.
  - DAY-CLUSTERED 95% CI (cluster = int(ts//86400)) via cluster bootstrap; MDE = 2.8 * bootstrap SD.
    Equal-weighted day-block mean reported next to the pooled mean (house research standard).
Writes chief_levels_retest.json. Does not commit, does not touch other files.
"""
import io, json, os, re, sqlite3
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
CALLS = os.path.join(HERE, "server_exports", "chief_calls.jsonl")
WINDOWS = [12, 24, 48]
NULLDRAW = 200          # random matched-distance draws per level (matches m9_chief)
WREG = 72              # local-regime half-width in 1h bars (+/-3 days) for the time-matched null
NBOOT = 3000
rng = np.random.default_rng(12345)
numpat = re.compile(r"\d[\d,]*\.?\d*")


def load_candles():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    rows = [json.loads(l) for l in io.open(CALLS, encoding="utf-8") if l.strip()]
    syms = sorted(set(r["symbol"] for r in rows))
    cd = {}
    for s in syms:
        a = np.asarray(c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (s,)).fetchall(), float)
        if len(a) > 200:
            cd[s] = a
    c.close()
    return rows, cd


def parse_levels(inv, px):
    out = []
    for tok in numpat.findall(inv.replace(",", "")):
        try:
            v = float(tok)
        except ValueError:
            continue
        d = v / px - 1.0
        if 0.003 <= abs(d) <= 0.20:
            out.append(v)
    return out


def clus(v, g):
    """Cluster bootstrap over groups g. Returns pooled mean, equal-weighted block mean, ci_lo, ci_hi, sd."""
    v = np.asarray(v, float); g = np.asarray(g)
    u = np.unique(g)
    grp = {x: v[g == x] for x in u}
    block_mean = float(np.mean([grp[x].mean() for x in u]))
    boot = np.empty(NBOOT)
    for b in range(NBOOT):
        pick = u[rng.integers(0, len(u), len(u))]
        boot[b] = np.concatenate([grp[p] for p in pick]).mean()
    return (float(v.mean()), block_mean,
            float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)), float(boot.std()))


def main():
    rows, cd = load_candles()
    result = {"n_calls": len(rows), "windows": {}, "params": {"nulldraw": NULLDRAW, "wreg_bars": WREG,
              "nboot": NBOOT, "level_band": [0.003, 0.20]}}
    n_levels_total = None
    confounded = {}

    for H in WINDOWS:
        chief, nullr, flip, day, sym = [], [], [], [], []
        conf_null = []
        for r in rows:
            s = r["symbol"]
            inv = r.get("invalidation") or ""
            if s not in cd or not inv:
                continue
            a = cd[s]
            i = int(np.searchsorted(a[:, 0], r["ts"] * 1000.0))
            if i < 1 or i + H >= len(a):
                continue
            px = a[i, 3] if a[i, 3] > 0 else r["price"]
            lvls = parse_levels(inv, px)
            if not lvls:
                continue
            hi_w = a[i + 1:i + 1 + H, 1]; lo_w = a[i + 1:i + 1 + H, 2]
            d0 = int(r["ts"] // 86400)
            # local-regime eligible bars (same regime, full forward room)
            lo_b = max(1, i - WREG); hi_b = min(len(a) - H - 1, i + WREG)
            elig_loc = np.arange(lo_b, hi_b)
            # confounded (all-history) pool for the diagnostic
            elig_all = np.arange(1, len(a) - H - 1)
            for v in lvls:
                d = v / px - 1.0
                up = d > 0
                touched = (hi_w.max() >= v) if up else (lo_w.min() <= v)
                # side-flip: opposite side, same |distance|, same path
                vf = px * (1.0 - d)
                flip_t = (hi_w.max() >= vf) if (not up) else (lo_w.min() <= vf)
                # time-matched null: local-regime reference bars, same signed distance
                jj = elig_loc[rng.integers(0, len(elig_loc), NULLDRAW)]
                ln = a[jj, 3] * (1 + d)
                if up:
                    nt = np.fromiter((a[j + 1:j + 1 + H, 1].max() >= ln[k] for k, j in enumerate(jj)), float, NULLDRAW)
                else:
                    nt = np.fromiter((a[j + 1:j + 1 + H, 2].min() <= ln[k] for k, j in enumerate(jj)), float, NULLDRAW)
                # confounded null diagnostic
                ja = elig_all[rng.integers(0, len(elig_all), NULLDRAW)]
                la = a[ja, 3] * (1 + d)
                if up:
                    ca = np.fromiter((a[j + 1:j + 1 + H, 1].max() >= la[k] for k, j in enumerate(ja)), float, NULLDRAW)
                else:
                    ca = np.fromiter((a[j + 1:j + 1 + H, 2].min() <= la[k] for k, j in enumerate(ja)), float, NULLDRAW)
                chief.append(float(touched)); nullr.append(float(nt.mean()))
                flip.append(float(flip_t)); conf_null.append(float(ca.mean()))
                day.append(d0); sym.append(s)

        chief = np.array(chief); nullr = np.array(nullr); flip = np.array(flip)
        conf_null = np.array(conf_null); day = np.array(day)
        n = len(chief)
        if H == 12:
            n_levels_total = n
        excess = chief - nullr
        sflip = chief - flip
        confex = chief - conf_null
        pooled, block, lo, hi, sd = clus(excess, day)
        mde = 2.8 * sd
        cf_pooled, cf_block, cf_lo, cf_hi, _ = clus(confex, day)
        sf_pooled, sf_block, sf_lo, sf_hi, _ = clus(sflip, day)
        verdict = "separates" if (lo > 0 and lo > mde) or (hi < 0 and -hi > mde) else "no difference"
        result["windows"][str(H)] = {
            "n": n, "n_days": int(len(np.unique(day))),
            "chief_rate": round(float(chief.mean()) * 100, 2),
            "null_rate": round(float(nullr.mean()) * 100, 2),
            "diff": round(pooled * 100, 2),
            "diff_dayblock": round(block * 100, 2),
            "ci_lo": round(lo * 100, 2), "ci_hi": round(hi * 100, 2),
            "mde": round(mde * 100, 2),
            "sideflip_rate": round(float(flip.mean()) * 100, 2),
            "sideflip_diff": round(sf_pooled * 100, 2),
            "confounded_null_rate": round(float(conf_null.mean()) * 100, 2),
            "confounded_diff": round(cf_pooled * 100, 2),
            "verdict": verdict,
        }

    # overall
    verds = [result["windows"][str(H)]["verdict"] for H in WINDOWS]
    result["n_levels_total"] = n_levels_total
    result["overall"] = ("still null (indistinguishable from time-matched same-distance levels)"
                         if all(v == "no difference" for v in verds)
                         else "NOW SEPARATES on at least one window")
    io.open(os.path.join(HERE, "chief_levels_retest.json"), "w", encoding="utf-8").write(
        json.dumps(result, indent=2, default=float))

    print("PRE-REGISTERED RE-TEST  n_calls=%d  n_levels(12h)=%d" % (result["n_calls"], n_levels_total))
    print("H   n    nday chief  null  diff  dayblk  [ci_lo, ci_hi]  MDE   sideflip  conf_null conf_diff  verdict")
    for H in WINDOWS:
        w = result["windows"][str(H)]
        print("%-3d %-4d %-4d %5.1f %5.1f %+5.1f %+6.1f  [%+5.1f,%+5.1f] %5.1f  %+7.1f %9.1f %+8.1f  %s"
              % (H, w["n"], w["n_days"], w["chief_rate"], w["null_rate"], w["diff"], w["diff_dayblock"],
                 w["ci_lo"], w["ci_hi"], w["mde"], w["sideflip_diff"], w["confounded_null_rate"],
                 w["confounded_diff"], w["verdict"]))
    print("OVERALL:", result["overall"])


if __name__ == "__main__":
    main()
