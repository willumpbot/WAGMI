"""MISSION 10 — do the four unsigned "size" flags predict a bigger next-day move than the HAR
forecast alone already does?

The scanner grades volume_surge, funding_hot, funding_cold and vol_expanding unsigned (|excess|),
i.e. as SIZING inputs rather than direction calls. The server asks: on HL history, does each flag
predict a bigger next-day |move| than unflagged coins WITH THE SAME HAR FORECAST?

Flag definitions from tools/hivemind/scanner.py:
    vol_expanding   rv5 > 1.4 * rv22
    volume_surge    24h USD volume > 2.5 * its 20-day average
    funding_hot     funding in the top of the scanned coins  -> top quintile per date (cross-sectional)
    funding_cold    funding < 0

DESIGN, carrying mission 3's lesson. That mission produced three different answers depending on what
was controlled, and the convincing middle one (+17.6%, 10/10 deciles, t=6.46) was WRONG because `em`
is a per-coin forecast and cannot absorb market-wide surprise. The only honest control is BOTH:

    compare flagged vs unflagged coins WITHIN the same date AND the same em quintile

and the outcome is the log ratio log(|move|) - log(em), which is bounded (the plain ratio blew up to
229,859x in mission 3 when em neared zero).

POWER FIRST, per the standing rule. A within-cell matched test discards most rows, which is exactly
how mission 3's "decisive" test ended up with an MDE of +10% against a true effect of +4%. So this
script injects a known effect and reports SIZE and POWER before any verdict. If size is not near 5%
the flag is reported "unmeasurable", not "no effect".

Universe: clean perps only -- `_spot`/`_wspot` excluded and any series with >2% stale bars dropped,
the filter bug that invalidated mission 1.
"""
import json, io, os, csv, glob, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
EPS = 1e-8
START = "2023-01-01"
MAX_STALE = 0.02
PLACEBO = 200
rng = np.random.default_rng(20261010)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def load_daily(sym):
    rows = []
    with io.open(os.path.join(HIST, f"{sym}_1d.csv"), encoding="utf-8",
                 errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                             float(r["l"]), float(r["c"]), float(r.get("v") or 0)))
            except (TypeError, ValueError):
                continue
    rows.sort()
    return rows


def load_funding(sym):
    p = os.path.join(HIST, f"{sym}_funding.csv")
    if not os.path.exists(p):
        return {}
    byday = collections.defaultdict(list)
    with io.open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                t = int(r["t_ms"]) // 1000
                byday[datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d")
                      ].append(float(r["rate"]))
            except (TypeError, ValueError):
                continue
    return {d: float(np.mean(v)) for d, v in byday.items() if v}


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


allsyms = sorted({os.path.basename(p).split("_1d")[0] for p in glob.glob(os.path.join(HIST, "*_1d.csv"))})
syms, dropped = [], 0
for s in allsyms:
    if s.endswith("_spot") or s.endswith("_wspot"):
        dropped += 1
        continue
    d = load_daily(s)
    if len(d) < 200:
        dropped += 1
        continue
    if sum(1 for x in d if x[1] == x[2] == x[3] == x[4]) / len(d) > MAX_STALE:
        dropped += 1
        continue
    syms.append(s)
print(f"universe: {len(syms)} clean perps ({dropped} dropped: spot, short or stale)")

rows = []
for s in syms:
    d = load_daily(s)
    fnd = load_funding(s)
    t = [x[0] for x in d]
    c = [x[4] for x in d]
    v = [x[5] for x in d]
    day = [datetime.datetime.fromtimestamp(x, datetime.UTC).strftime("%Y-%m-%d") for x in t]
    rets = [0.0] + [(c[i] / c[i - 1] - 1) * 100 for i in range(1, len(c))]
    vusd = [v[i] * c[i] for i in range(len(c))]
    for i in range(30, len(c) - 2):
        if day[i] < START:
            continue
        rv1, rv5, rv22 = abs(rets[i]), sd(rets[i - 4:i + 1]), sd(rets[i - 21:i + 1])
        if rv22 <= 0 or rv5 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        em = math.exp(z) * Y1S
        if em <= 0:
            continue
        nxt = abs(rets[i + 1])
        if nxt <= 0:
            continue
        avg20 = float(np.mean(vusd[i - 19:i + 1])) if i >= 19 else 0.0
        wk = datetime.date.fromisoformat(day[i]).isocalendar()
        rows.append({
            "sym": s, "day": day[i], "week": f"{wk[0]}-W{wk[1]:02d}",
            "em": em, "move": nxt,
            "vol_expanding": bool(rv5 > 1.4 * rv22),
            "volume_surge": bool(avg20 > 0 and vusd[i] > 2.5 * avg20),
            "funding": fnd.get(day[i]),
        })

df = pd.DataFrame(rows)
df["lr"] = np.log(df["move"] + EPS) - np.log(df["em"] + EPS)
# funding flags: cold is absolute, hot is cross-sectional top quintile per date
df["funding_cold"] = df["funding"].notna() & (df["funding"] < 0)
hot = []
for dy, g in df.groupby("day"):
    f = g["funding"]
    thr = f.quantile(0.80) if f.notna().sum() >= 5 else None
    hot.extend([(idx, bool(thr is not None and pd.notna(val) and val >= thr))
                for idx, val in f.items()])
df["funding_hot"] = False
df.loc[[i for i, b in hot if b], "funding_hot"] = True
df["emq"] = pd.qcut(df["em"], 5, labels=False, duplicates="drop")
df["cell"] = df["day"].astype(str) + "|" + df["emq"].astype(str)
print(f"panel {len(df)} coin-days, {df['sym'].nunique()} perps, "
      f"{df['day'].min()} -> {df['day'].max()}, funding on "
      f"{100*df['funding'].notna().mean():.0f}% of rows\n")

FLAGS = ["vol_expanding", "volume_surge", "funding_hot", "funding_cold"]
cells = {k: g.index.values for k, g in df.groupby("cell")}
lr = df["lr"].values


def matched(flagmask, inject=0.0):
    """Mean within-cell difference (flagged minus unflagged), week-clustered."""
    byw = collections.defaultdict(list)
    for k, idx in cells.items():
        f = flagmask[idx]
        if f.all() or not f.any():
            continue
        a = lr[idx][f] + inject
        b = lr[idx][~f]
        ic = datetime.date.fromisoformat(k.split("|")[0]).isocalendar()
        byw[f"{ic[0]}-W{ic[1]:02d}"].append(a.mean() - b.mean())
    if len(byw) < 8:
        return None
    mus = np.array([np.mean(v) for v in byw.values()])
    se = float(mus.std(ddof=1)) / math.sqrt(len(mus))
    return float(mus.mean()), se, len(mus), sum(len(v) for v in byw.values())


out = {"panel": len(df), "perps": int(df["sym"].nunique()),
       "start": df["day"].min(), "end": df["day"].max(), "flags": {}}

print("=" * 104)
print("POWER FIRST — inject a known effect into the flagged rows, within date x em-quintile")
print("=" * 104)
print(f"  {'flag':<16}{'fired%':>8}{'cells':>8}" + "".join(f"{d:>9.2f}" for d in (0.0, 0.05, 0.10, 0.20)))
print(f"  {'':<16}{'':>8}{'':>8}" + "".join(f"{'size' if d==0 else 'pow':>9}" for d in (0.0, 0.05, 0.10, 0.20)))
print("-" * 104)
power = {}
for fl in FLAGS:
    mask = df[fl].values.astype(bool)
    base = matched(mask)
    if base is None:
        print(f"  {fl:<16}   too few matched cells")
        continue
    m0, se0, nw, nc = base
    det = {}
    for delta in (0.0, 0.05, 0.10, 0.20):
        hits = 0
        for _ in range(PLACEBO):
            perm = mask.copy()
            for k, idx in cells.items():
                sub = perm[idx]
                if sub.any() and not sub.all():
                    perm[idx] = rng.permutation(sub)
            r = matched(perm, inject=delta)
            if r and (r[0] - 1.96 * r[1]) > 0:
                hits += 1
        det[delta] = hits / PLACEBO
    power[fl] = det
    print(f"  {fl:<16}{100*mask.mean():>7.1f}%{nw:>8}" + "".join(f"{det[d]:>9.3f}" for d in (0.0, 0.05, 0.10, 0.20)))
    out["flags"][fl] = {"fired_pct": round(100 * float(mask.mean()), 2), "weeks": nw,
                        "matched_cells": nc,
                        "power": {str(k): round(v, 3) for k, v in det.items()}}

print("\n" + "=" * 104)
print("THE COMPARISON — flagged minus unflagged |move| vs forecast, same date AND em quintile")
print("=" * 104)
print(f"  {'flag':<16}{'week mean(log)':>16}{'= level':>10}{'week se':>10}{'week t':>9}"
      f"{'size':>8}{'MDE':>8}  verdict")
print("-" * 104)
for fl in FLAGS:
    if fl not in out["flags"]:
        continue
    r = matched(df[fl].values.astype(bool))
    if r is None:
        continue
    m, se, nw, nc = r
    det = power[fl]
    size = det[0.0]
    mde = next((d for d in (0.05, 0.10, 0.20) if det[d] >= 0.8), None)
    valid = 0.01 <= size <= 0.12
    sig = (m - 1.96 * se) > 0
    verdict = ("design void" if not valid else
               "REAL sizing input" if sig else
               ("unmeasurable" if (mde is None or abs(m) < mde) else "no bigger move"))
    print(f"  {fl:<16}{m:>+16.4f}{100*(math.exp(m)-1):>+9.1f}%{se:>10.4f}"
          f"{(m/se if se else float('nan')):>9.2f}{size:>8.3f}"
          f"{(str(mde) if mde else '>0.20'):>8}  {verdict}")
    out["flags"][fl].update({
        "week_mean_log": round(m, 4), "level_pct": round(100 * (math.exp(m) - 1), 2),
        "week_se": round(se, 4), "week_t": round(m / se, 2) if se else None,
        "size": size, "mde80": mde, "design_valid": bool(valid),
        "significant": bool(sig), "verdict": verdict})

print("\n" + "=" * 104)
print("VERDICT")
print("=" * 104)
for fl in FLAGS:
    v = out["flags"].get(fl)
    if not v:
        continue
    print(f"  {fl:<16} {v['verdict']:<20} {v.get('level_pct', 0):+.1f}% bigger move, "
          f"t {v.get('week_t')}, detectable from {v.get('mde80') or '>0.20'}")
keep = [f for f, v in out["flags"].items() if v.get("significant")]
out["verdict"] = (f"real sizing inputs: {keep}" if keep
                  else "no flag predicts a bigger move than the forecast alone, at the power available")
print(f"\n  => {out['verdict']}")
with io.open(os.path.join(HERE, "size_flags.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote size_flags.json")
