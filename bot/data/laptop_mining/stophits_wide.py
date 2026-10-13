"""PREREG_STOPHITS_WIDE (sha256 81d016b7) — does `funding_hot -> more stop hits` hold out of sample?

TWO PRIMARIES, because the published claim and the live configuration are different measurements:

    (A) CLAIM-REPLICATION   (c) NEW156 | naive em  | ge | rank   -- does the PUBLISHED claim hold?
    (B) LIVE-CONFIG         (c) NEW156 | fitted em | gt | rank   -- does the LIVE setup hold?

Both reported unconditionally, neither promoted. If (A) replicates and (B) does not, the claim is
real but the live configuration does not inherit it, and the fix is the configuration.

WHY TWO. Found while establishing the canary:
  * funding_stop.py:41-42 HARDCODES Y1B=(0.0,0.35,0.35,0.30), Y1S=1.0 -- no intercept, no smearing --
    where size_flags.py loads the FITTED [-0.3921,0.0521,0.2143,0.5201] with smearing 1.7389. So the
    claim's "1.65 x em stop" is 1.65 x a DIFFERENT em than the bot sets stops from. A fourth
    exp_move variant, inside the evidence for a card that feeds the terminal.
  * the live flag is `value > cut`; the studies use `val >= cut`. Funding is tie-heavy (the HL default
    1.250e-05 is 18.2% of non-null rows), so the two differ on 5.8% of coin-days.

CANARY VERIFIED BEFORE SEALING, not hoped for -- with the naive em, ORIG17/2024+/unfiltered returns
ge: +2.64 pp, t 3.31, 2,269 cells, 145 weeks, fires 26.33%, and gt: +2.68 pp, t 3.04, fires 18.92%,
reproducing FUNDING_STOP.md to the digit. PREREG_FUNDING_WIDE's canary was a hope; it failed and
voided that run.

Everything here was read from funding_stop.py directly: outcome `move > K*em` STRICT, K=1.65,
START=2024-01-01, cells `pd.qcut(em,5)` GLOBAL x day (NOT per date -- that error voided the last run),
flag top quintile per date with len(dropna)>=5. The statistic, placebo and MDE machinery are imported
from size_flags_wide, which selftested against the original matched() at 1e-17.
"""
import datetime
import importlib.util
import io
import json
import math
import os
import warnings

warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location("sfw", os.path.join(HERE, "size_flags_wide.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)          # reuse the selftested statistic, placebo and MDE code

START = "2024-01-01"                 # funding_stop.py's own window
K_SET = (1.00, 1.50, 1.65, 2.00)
K_VERDICT = 1.65
EPS_NAIVE = 1e-9
NAIVE_B, NAIVE_S = (0.0, 0.35, 0.35, 0.30), 1.0        # funding_stop.py:41-42, verbatim
FIT_B, FIT_S = M.Y1B, M.Y1S                             # volatility_forecast.json, what the bot uses
ORIG17 = M.ORIG17


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    mu = sum(xs) / n
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def build(syms, em_kind, vol_filter=True):
    """Panel with `em` from either the naive (claim) or fitted (live) coefficients."""
    beta, smear, eps = ((NAIVE_B, NAIVE_S, EPS_NAIVE) if em_kind == "naive"
                        else (FIT_B, FIT_S, 1e-8))
    rows, removed = [], 0
    for s in syms:
        d = M.load_daily(s)
        if vol_filter:
            fz = next((i for i, x in enumerate(d) if x[5] > 0), None)
            if fz is None:
                continue
            removed += fz
            d = d[fz:]
        fnd = M.load_funding(s)
        c = [x[4] for x in d]
        vol = [x[5] for x in d]
        day = [datetime.datetime.fromtimestamp(x[0], datetime.UTC).strftime("%Y-%m-%d") for x in d]
        rets = [0.0] + [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
        for i in range(30, len(c) - 2):
            if day[i] < START:
                continue
            if vol_filter and (vol[i] == 0 or vol[i + 1] == 0):
                removed += 1
                continue
            rv1, rv5, rv22 = abs(rets[i]), sd(rets[i - 4:i + 1]), sd(rets[i - 21:i + 1])
            if not (rv22 > 0 and rv5 > 0):
                continue
            z = (beta[0] + beta[1] * math.log(rv1 + eps) + beta[2] * math.log(rv5 + eps)
                 + beta[3] * math.log(rv22 + eps))
            em = math.exp(z) * smear
            if em <= 0:
                continue
            nxt = abs(rets[i + 1])
            if nxt <= 0:
                continue
            rows.append({"sym": s, "day": day[i], "em": em, "move": nxt,
                         "funding": fnd.get(day[i])})
    df = pd.DataFrame(rows).reset_index(drop=True)
    df.attrs["removed"] = removed
    return df


def cells_global(sub):
    """date x em-quintile with GLOBAL quintiles -- funding_stop.py:149 / size_flags.py:148."""
    emq = pd.qcut(sub["em"], 5, labels=False, duplicates="drop")
    key = sub["day"].astype(str) + "|" + pd.Series(emq, index=sub.index).fillna(0).astype(int).astype(str)
    codes, uniq = pd.factorize(key)
    cw = [datetime.date.fromisoformat(k.split("|")[0]).isocalendar()[:2] for k in uniq]
    wc, _ = pd.factorize(pd.Series(["%d-W%02d" % (a, b) for a, b in cw]))
    return codes.astype(np.int64), wc.astype(np.int64), len(uniq)


def flag(sub, op):
    """Top funding quintile per date. `op` is 'ge' (studies) or 'gt' (live scanner)."""
    out = np.zeros(len(sub), dtype=bool)
    for _, g in sub.groupby("day"):
        f = g["funding"].dropna()
        if len(f) < 5:
            continue
        thr = f.quantile(0.80)
        if pd.isna(thr):
            continue
        hit = (g["funding"] > thr) if op == "gt" else (g["funding"] >= thr)
        out[g.index.values[hit.fillna(False).values]] = True
    return out


def frozen_cutoffs(df_all):
    cut = {}
    for d, g in df_all[df_all["sym"].isin(ORIG17)].groupby("day"):
        f = g["funding"].dropna()
        if len(f) >= 5:
            t = f.quantile(0.80)
            if not pd.isna(t):
                cut[d] = float(t)
    return cut


def flag_frozen(sub, cut, op):
    out = np.zeros(len(sub), dtype=bool)
    for d, g in sub.groupby("day"):
        thr = cut.get(d)
        if thr is None:
            continue
        hit = (g["funding"] > thr) if op == "gt" else (g["funding"] >= thr)
        out[g.index.values[hit.fillna(False).values]] = True
    return out


def analyse(label, sub, mask, K=K_VERDICT):
    """Placebo size -> MDE -> counts -> effect. Order enforced by construction."""
    cell, cw, nc = cells_global(sub)
    nw = int(cw.max()) + 1 if len(cw) else 0
    y = (sub["move"].values > K * sub["em"].values).astype(float)
    base = M.matched_vec(mask, y, cell, cw, nc, nw)
    if base is None:
        return {"label": label, "verdict": "INSUFFICIENT CELLS"}
    power = {}
    for d in M.DELTAS:
        hits = 0
        for _ in range(M.PLACEBO):
            p = M.permute_in_cells(mask, cell, nc)
            r = M.matched_vec(p, y, cell, cw, nc, nw, inject=d)
            if r and (r[0] - 1.96 * r[1]) > 0:
                hits += 1
        power[d] = hits / M.PLACEBO
    size = power[0.0]
    mde = M.mde_interp(power)
    eff, se = base[0], base[1]
    lo, hi = eff - 1.96 * se, eff + 1.96 * se
    excl = (lo > 0) or (hi < 0)
    powered = (mde is not None) and (abs(eff) >= mde)
    r = {"label": label, "coins": int(sub["sym"].nunique()), "rows": len(sub),
         "baseline_pp": round(100 * float(y.mean()), 2),
         "size_at_0": round(size, 3),
         "size_ok": M.SIZE_OK[0] <= size <= M.SIZE_OK[1],
         "conservative": bool(size < M.CONSERVATIVE_BELOW),
         "power": {str(k): round(v, 3) for k, v in power.items()},
         "mde_pp": None if mde is None else round(100 * mde, 2),
         "weeks": base[2], "cells": base[3],
         "effect_pp": round(100 * eff, 2), "se_pp": round(100 * se, 2),
         "t": round(eff / se, 2) if se else None,
         "ci_pp": [round(100 * lo, 2), round(100 * hi, 2)],
         "fired_pct": round(100 * float(mask.mean()), 2),
         "excludes_zero": bool(excl), "powered": bool(powered)}
    if not r["size_ok"]:
        r["verdict"] = "TEST BROKEN (size %.3f)" % size
    elif excl and eff > 0:
        r["verdict"] = "replicates" if powered else "positive but underpowered"
    elif excl and eff < 0:
        r["verdict"] = ("contradicts: significant NEGATIVE" if powered
                        else "negative but underpowered")
    elif powered:
        r["verdict"] = "does not replicate"
    else:
        r["verdict"] = "unmeasurable"
    return r


def show(r):
    if r.get("verdict") == "INSUFFICIENT CELLS":
        print("  %-46s INSUFFICIENT CELLS" % r["label"])
        return
    print("  %s" % r["label"])
    print("     size@0 %.3f (%s)%s | MDE %s pp | weeks %d | cells %d | fired %.2f%% | baseline %.2f%%"
          % (r["size_at_0"], "ok" if r["size_ok"] else "BROKEN",
             "  CONSERVATIVE" if r["conservative"] else "", r["mde_pp"], r["weeks"], r["cells"],
             r["fired_pct"], r["baseline_pp"]))
    print("     effect %+.2f pp  t %.2f  CI [%+.2f, %+.2f]  ->  %s"
          % (r["effect_pp"], r["t"] or 0, r["ci_pp"][0], r["ci_pp"][1], r["verdict"]))


def main():
    syms, drop = M.universe()
    new = [s for s in syms if s not in ORIG17]
    print("universe: %d qualifying perps %s | NEW=%d ORIG17=%d"
          % (len(syms), dict(drop), len(new), len([s for s in syms if s in ORIG17])))
    print("prereg 81d016b7 | START=%s | K=%s | PLACEBO=%d\n" % (START, K_VERDICT, M.PLACEBO))

    panels = {}
    for kind in ("naive", "fitted"):
        panels[(kind, True)] = build(syms, kind, vol_filter=True)
        panels[(kind, False)] = build(syms, kind, vol_filter=False)
        print("panel %-6s filtered %6d rows | unfiltered %6d rows"
              % (kind, len(panels[(kind, True)]), len(panels[(kind, False)])))

    def sub(kind, filt, which):
        df = panels[(kind, filt)]
        if which == "NEW156":
            d = df[~df["sym"].isin(ORIG17)]
        elif which == "ORIG17":
            d = df[df["sym"].isin(ORIG17)]
        else:
            d = df
        return d.reset_index(drop=True)

    out = {"prereg": "PREREG_STOPHITS_WIDE 81d016b7", "start": START, "K": K_VERDICT,
           "results": []}

    print("\n" + "=" * 100)
    print("CANARY FIRST -- must reproduce funding_stop.py: ge +2.64 pp/t 3.31/2,269 cells, gt +2.68/t 3.04")
    print("=" * 100)
    canary_ok = True
    for op, tgt_e, tgt_t in (("ge", 2.64, 3.31), ("gt", 2.68, 3.04)):
        s = sub("naive", False, "ORIG17")
        r = analyse("CANARY  ORIG17 | naive em | %s | unfiltered" % op, s, flag(s, op))
        r["target"] = {"effect_pp": tgt_e, "t": tgt_t}
        ok = abs(r["effect_pp"] - tgt_e) <= 0.05 and abs((r["t"] or 0) - tgt_t) <= 0.10
        r["canary_ok"] = ok
        canary_ok = canary_ok and ok
        out["results"].append(r)
        show(r)
        print("     target %+.2f pp / t %.2f  ->  %s" % (tgt_e, tgt_t, "MATCH" if ok else "MISMATCH"))
    if not canary_ok:
        print("\nHALTING: the canary did not reproduce. Per the prereg the run is VOID.")
        io.open(os.path.join(HERE, "stophits_wide.json"), "w", encoding="utf-8").write(
            json.dumps(out, indent=1))
        return

    print("\n" + "=" * 100)
    print("THE TWO PRIMARIES -- reported together, neither promoted")
    print("=" * 100)
    for tag, kind, op in (("(A) CLAIM-REPLICATION", "naive", "ge"),
                          ("(B) LIVE-CONFIG      ", "fitted", "gt")):
        s = sub(kind, True, "NEW156")
        r = analyse("%s  NEW156 | %s em | %s | filtered | rank" % (tag, kind, op), s, flag(s, op))
        r["primary"] = tag.strip()
        out["results"].append(r)
        show(r)

    print("\n" + "=" * 100)
    print("THE FULL 2x2 ON (c) -- so em x operator disagreement is legible")
    print("=" * 100)
    for kind in ("naive", "fitted"):
        for op in ("ge", "gt"):
            s = sub(kind, True, "NEW156")
            r = analyse("NEW156 | %-6s em | %s | filtered | rank" % (kind, op), s, flag(s, op))
            out["results"].append(r)
            show(r)

    print("\n" + "=" * 100)
    print("SUPPORTING ARMS")
    print("=" * 100)
    for lbl, kind, filt, which, op in (
            ("(b)     ORIG17 | fitted em | gt | filtered | rank", "fitted", True, "ORIG17", "gt"),
            ("(c_raw) NEW156 | fitted em | gt | UNFILTERED | rank", "fitted", False, "NEW156", "gt"),
            ("(a)     ALL173 | fitted em | gt | filtered | rank  CONTAMINATED", "fitted", True, "ALL", "gt")):
        s = sub(kind, filt, which)
        r = analyse(lbl, s, flag(s, op))
        out["results"].append(r)
        show(r)

    print("\n" + "=" * 100)
    print("FROZEN-CUTOFF ARM (secondary) -- cutoff taken from ORIG17, applied to NEW156")
    print("=" * 100)
    cut = frozen_cutoffs(panels[("fitted", True)])
    s = sub("fitted", True, "NEW156")
    r = analyse("(c)     NEW156 | fitted em | gt | filtered | FROZEN", s, flag_frozen(s, cut, "gt"))
    out["results"].append(r)
    show(r)

    print("\n" + "=" * 100)
    print("K-CURVE on (B), shape only -- the verdict rests on K=1.65 alone")
    print("=" * 100)
    s = sub("fitted", True, "NEW156")
    msk = flag(s, "gt")
    cell, cw, nc = cells_global(s)
    nw = int(cw.max()) + 1
    for K in K_SET:
        y = (s["move"].values > K * s["em"].values).astype(float)
        rr = M.matched_vec(msk, y, cell, cw, nc, nw)
        if rr:
            print("  K=%.2f  baseline %5.2f%%  effect %+.2f pp  t %.2f%s"
                  % (K, 100 * y.mean(), 100 * rr[0], rr[0] / rr[1],
                     "   <- verdict K" if K == K_VERDICT else ""))

    io.open(os.path.join(HERE, "stophits_wide.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote stophits_wide.json")
    print("\nREMINDER: (A) and (B) answer DIFFERENT questions and neither is promoted. (a) ALL173 is")
    print("contaminated by the discovery sample. Verdict rests on K=1.65.")


if __name__ == "__main__":
    main()
