"""Exits v2 — the time stop, with a horizon long enough for it to actually fire.

EXITS.md drives a LIVE decision card (TIME_STOP_HOURS -> 48). It has three defects:

 D1  THE 48h CELL WAS A NO-OP. exits.py:31 sets HORIZON_H = 48 and tests time stops
     at (4,12,24,48). A 48h time stop on a 48h horizon can never fire -- it is
     numerically identical to the baseline, so its "-0.0146R, no difference" is a
     mark-to-close artifact, not evidence for 48h. Here HORIZON_H = 120, so every
     time stop tested (4..72) genuinely binds.

 D2  IT WAS MEASURED ON A BRACKET THAT BARELY EXISTS. exits.py:30 sets
     STOP_MULT = 8.0, "the geometry plateau", from the now-refuted GEOMETRY.md.
     geometry_v3 shows x8 binds on only 14.3% of trades -- so in that run the time
     stop WAS the dominant exit, which is close to circular. Here the stop is
     tested at x1 (what the bot runs today) and x2 (what geometry_v3 recommends),
     both of which actually bind.

 D3  NO NULL OF ANY KIND. grep -nE "flip|null|shuffl|placebo" exits.py returns only
     the bootstrap RNG. Given that this project has now produced two reversals from
     tests that could not fail, that is not acceptable. Here: a side-flip null, the
     direction-free (real+flip)/2 decomposition from geometry_v3, AND a synthetic
     control that injects a known effect to prove the test can detect one.

Note on interpreting the null here, stated up front so it is not used dishonestly:
for an EXIT POLICY, a direction-free effect is still actionable. Geometry v1 claimed
"wide stops suit OUR signals" and the flip refuted that. But "cutting early hurts any
bracket" is a perfectly good reason not to cut early, because we must choose some
policy for whatever signals exist. So the null changes the STORY, not the ACTION --
and the direction-free component is the one to trust, since it needs nothing predicted.

The question: does a time stop cost anything once it can actually fire, on a bracket
that actually binds, measured on calendar folds with a test proven to have power?
"""
import json, io, os, gzip, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd
from multiprocessing import Pool, cpu_count

from geometry_v2 import load_candles, first_after, rng, FEE_BPS, HERE

HORIZON_H = 120                      # D1: long enough that a 48h stop binds
STOPS = (1.0, 2.0)                   # D2: the bot today, and geometry_v3's pick
TP = 0.5                             # geometry_v3's recommended target
TIMES = (4, 8, 12, 24, 48, 72, None)  # None = hold to horizon = the baseline
CAND = {}


def init(syms):
    for s in syms:
        c = load_candles(s)
        if c:
            CAND[s] = c


def sim(args):
    """For each signal: R under every (stop, time-stop) combination, real and flipped."""
    sym, rows = args
    c = CAND.get(sym)
    if not c:
        return []
    out = []
    for s in rows:
        i0 = first_after(c, s["t0"])
        if i0 is None or c[i0][0] - s["t0"] > 3600:
            continue
        entry, base = c[i0][1], s["base"]
        if entry <= 0 or base <= 0:
            continue
        bars, k, end = [], i0, s["t0"] + HORIZON_H * 3600
        while k < len(c) and c[k][0] <= end:
            bars.append(c[k]); k += 1
        if len(bars) < 6:
            continue
        t_entry = bars[0][0]
        rec = {"sym": sym, "day": s["day"], "week": s["week"]}
        for flip in (False, True):
            long_ = (s["side"] == "LONG") != flip
            tag = "flip" if flip else "real"
            for sm in STOPS:
                dist = sm * base
                sl = entry - dist if long_ else entry + dist
                tp = entry + TP * dist if long_ else entry - TP * dist
                feeR = 2 * (FEE_BPS / 1e4) * entry / dist
                # walk once; record the hour at which stop/target fired, if ever
                fired_h, fired_r = None, None
                for (t, o, h, l, cl) in bars[1:]:
                    hit_sl = (l <= sl) if long_ else (h >= sl)
                    hit_tp = (h >= tp) if long_ else (l <= tp)
                    if hit_sl:
                        fired_h, fired_r = (t - t_entry) / 3600.0, -1.0; break
                    if hit_tp:
                        fired_h, fired_r = (t - t_entry) / 3600.0, TP; break
                for th in TIMES:
                    if fired_h is not None and (th is None or fired_h <= th):
                        r = fired_r                       # bracket resolved first
                    else:
                        # time stop (or horizon) reached first: mark to that close
                        cut = end if th is None else t_entry + th * 3600
                        mk = bars[0][4]
                        for (t, o, h, l, cl) in bars[1:]:
                            if t > cut:
                                break
                            mk = cl
                        r = ((mk - entry) if long_ else (entry - mk)) / dist
                    key = f"{tag}|{sm}|{'none' if th is None else th}"
                    rec[key] = r - feeR
        out.append(rec)
    return out


def boot_ci(d, wk, iters=4000):
    groups = [d[wk == w] for w in np.unique(wk)]
    groups = [g for g in groups if len(g)]
    if len(groups) < 4:
        return float(d.mean()), None, None
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(groups), len(groups))
        ms[i] = np.concatenate([groups[j] for j in pick]).mean()
    ms.sort()
    return float(d.mean()), float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


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
            base = abs(float(d["entry"]) - float(d["sl"]))
            if base <= 0:
                continue
            day = d["ts"][:10]
            wk = datetime.date.fromisoformat(day).isocalendar()
            sigs.append({"sym": d["sym"], "side": d["side"], "base": base, "t0": t0,
                         "day": day, "week": f"{wk[0]}-W{wk[1]:02d}"})
    by = collections.defaultdict(list)
    for s in sigs:
        by[s["sym"]].append(s)
    syms = sorted(by)
    n = max(1, min(cpu_count() - 2, len(syms)))
    print(f"{len(sigs)} signals, {n} workers, horizon {HORIZON_H}h "
          f"(so a 48h time stop actually fires)", flush=True)
    recs = []
    with Pool(n, initializer=init, initargs=(syms,)) as pool:
        for o in pool.imap_unordered(sim, [(s, by[s]) for s in syms]):
            recs.extend(o)
    df = pd.DataFrame(recs)
    weeks = sorted(df["week"].unique())
    print(f"simulated {len(df)}  weeks {len(weeks)}  days {df['day'].nunique()}")
    wk = df["week"].values

    for sm in STOPS:
        for th in TIMES:
            t = 'none' if th is None else th
            rk, fk = f"real|{sm}|{t}", f"flip|{sm}|{t}"
            if rk in df.columns:
                df[f"sym|{sm}|{t}"] = (df[rk] + df[fk]) / 2.0

    out = {"n": int(len(df)), "weeks": len(weeks), "horizon_h": HORIZON_H,
           "stops": list(STOPS), "tp_R": TP,
           "fixes": ["horizon 120h so a 48h time stop binds (was a no-op at 48h)",
                     "stop x1 and x2, both of which bind (was x8, binding 14.3%)",
                     "side-flip null + direction-free decomposition",
                     "synthetic control proving the test has power",
                     "ISO-week blocks + calendar walk-forward"],
           "by_stop": {}}

    # ---------------- SYNTHETIC CONTROL, before any verdict ----------------
    print("\n" + "=" * 100)
    print("SYNTHETIC CONTROL — can this test detect a known effect?")
    print("  exact-zero-effect dataset, then inject known deltas")
    print("=" * 100)
    probe = (df["sym|2.0|12"] - df["sym|2.0|none"]).values
    m = np.isfinite(probe)
    h0 = probe[m] - probe[m].mean()
    print(f"  probe: stop x2, time 12h vs none. n={m.sum()}, measured {probe[m].mean():+.4f}R")
    print(f"  {'injected':>10}{'detected?':>12}{'CI95':>26}")
    print("-" * 100)
    power, smallest = {}, None
    for delta in (0.0, 0.02, 0.05, 0.08, 0.12, 0.20):
        pt, lo, hi = boot_ci(h0 + delta, wk[m])
        det = lo is not None and lo > 0
        power[str(delta)] = {"detected": bool(det),
                             "ci": [round(lo, 4), round(hi, 4)] if lo is not None else None}
        if det and smallest is None and delta > 0:
            smallest = delta
        print(f"  {delta:>10.3f}{('YES' if det else 'no'):>12}{f'[{lo:+.4f},{hi:+.4f}]':>26}"
              f"{'  <- FALSE POSITIVE' if (delta == 0.0 and det) else ''}")
    out["synthetic_control"] = power
    out["smallest_detectable_R"] = smallest
    if power["0.0"]["detected"]:
        print("\n  ABORT: reports an effect where none exists.")
        return
    print(f"\n  no false positive at zero (good); smallest detectable effect {smallest} R")

    # ---------------- the surface ----------------
    for sm in STOPS:
        bk = f"{sm}|none"
        print("\n" + "=" * 112)
        tag = "the bot today" if sm == 1.0 else "geometry_v3's recommendation"
        print(f"STOP x{sm} | target {TP}R   ({tag})")
        print(f"  baseline = NO time stop (hold to {HORIZON_H}h). negative = the time stop COSTS money")
        print("=" * 112)
        print(f"  {'time stop':>10}{'real R':>10}{'vs none':>10}{'CI95 (week blocks)':>24}"
              f"{'direction-free':>16}{'CI95':>24}")
        print("-" * 112)
        out["by_stop"][str(sm)] = {}
        for th in TIMES:
            t = 'none' if th is None else th
            if f"real|{sm}|{t}" not in df.columns:
                continue
            rm = float(df[f"real|{sm}|{t}"].mean())
            if t == 'none':
                print(f"  {'none':>10}{rm:>10.4f}{'—':>10}{'(baseline)':>24}{'—':>16}{'':>24}")
                out["by_stop"][str(sm)]['none'] = {"real_R": round(rm, 4), "baseline": True}
                continue
            dv = (df[f"real|{sm}|{t}"] - df[f"real|{sm}|none"]).values
            m2 = np.isfinite(dv)
            p, lo, hi = boot_ci(dv[m2], wk[m2])
            sv = (df[f"sym|{sm}|{t}"] - df[f"sym|{sm}|none"]).values
            sp, slo, shi = boot_ci(sv[m2], wk[m2])
            star = "*" if (lo is not None and (lo > 0 or hi < 0)) else " "
            sstar = "*" if (slo is not None and (slo > 0 or shi < 0)) else " "
            print(f"  {str(th)+'h':>10}{rm:>10.4f}{p:>9.4f}{star}"
                  f"{f'[{lo:+.4f},{hi:+.4f}]':>24}{sp:>15.4f}{sstar}"
                  f"{f'[{slo:+.4f},{shi:+.4f}]':>24}")
            out["by_stop"][str(sm)][str(th)] = {
                "real_R": round(rm, 4), "vs_none_R": round(p, 4),
                "ci": [round(lo, 4), round(hi, 4)] if lo is not None else None,
                "significant": bool(lo is not None and (lo > 0 or hi < 0)),
                "direction_free_R": round(sp, 4),
                "direction_free_ci": [round(slo, 4), round(shi, 4)] if slo is not None else None,
                "direction_free_significant": bool(slo is not None and (slo > 0 or shi < 0))}

    # ---------------- calendar walk-forward ----------------
    print("\n" + "=" * 100)
    print("CALENDAR WALK-FORWARD — sign stability of 'time stop vs none' across halves")
    print("=" * 100)
    mid = weeks[len(weeks) // 2]
    print(f"  split at {mid}: {len([w for w in weeks if w < mid])} weeks / "
          f"{len([w for w in weeks if w >= mid])} weeks")
    print(f"  {'stop':>6}{'time':>8}{'first half':>13}{'second half':>14}  stable?")
    print("-" * 100)
    for sm in STOPS:
        for th in TIMES:
            if th is None:
                continue
            a = df[df["week"] < mid]
            b = df[df["week"] >= mid]
            va = float((a[f"real|{sm}|{th}"] - a[f"real|{sm}|none"]).mean())
            vb = float((b[f"real|{sm}|{th}"] - b[f"real|{sm}|none"]).mean())
            stable = (va < 0) == (vb < 0)
            print(f"  {('x'+str(sm)):>6}{str(th)+'h':>8}{va:>13.4f}{vb:>14.4f}  "
                  f"{'yes' if stable else 'NO — sign flips'}")
            out["by_stop"][str(sm)].setdefault(str(th), {}).update(
                {"half1": round(va, 4), "half2": round(vb, 4), "sign_stable": bool(stable)})

    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    for sm in STOPS:
        d = out["by_stop"][str(sm)]
        harmful = [t for t in d if t != 'none'
                   and d[t].get("significant") and d[t].get("vs_none_R", 0) < 0
                   and d[t].get("sign_stable")]
        print(f"  stop x{sm}: time stops that significantly COST money and hold their sign: "
              f"{sorted(harmful, key=lambda x: int(x)) if harmful else 'NONE'}")
        df_harm = [t for t in d if t != 'none' and d[t].get("direction_free_significant")
                   and d[t].get("direction_free_R", 0) < 0]
        print(f"            ... of which direction-free (the trustworthy ones): "
              f"{sorted(df_harm, key=lambda x: int(x)) if df_harm else 'NONE'}")
    with io.open(os.path.join(HERE, "exits_v2.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote exits_v2.json")


if __name__ == "__main__":
    main()
