"""CORRECTED volatility validation. Supersedes VOLATILITY.md and walkforward_vol.py.

RETRACTION.md records three faults, all confirmed:

FAULT 1 (fatal) -- the 1-day walk-forward NEVER RAN. walkforward_vol.py lines
  114, 159 and 168 all call fit(tr, "y5"); `grep -o y1 walkforward_vol.json`
  returns 0. "22/22 folds at both horizons" was false. Here BOTH horizons run.

FAULT 2 (fatal) -- "beats naive" beat a degenerate baseline. naive1 =
  |today's return| is a single-draw proxy that is often near zero, and QLIKE
  diverges as the forecast approaches 0, so 51.7% of naive's test loss came from
  its own tail. Here HAR is scored against THREE baselines, including an honest
  one-parameter EWMA fitted on train only.

FAULT 3 (major) -- no significance test anywhere. "22/22 folds" was presented as
  evidence while the folds use nested expanding windows and the y5 targets overlap
  in blocks of five. Here each comparison gets a Diebold-Mariano test on the loss
  differential with a Newey-West correction for the overlap.

The question this answers: does the HAR forecast beat an honest baseline, or did
it only ever beat a broken one?
"""
import json, io, os, glob, time, math, collections, warnings
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
EPS = 1e-8
FOLD_DAYS = 90
MIN_TRAIN = 1500
COINS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "DOGE", "AVAX", "LINK", "ARB", "SUI"]


def daily(sym):
    p = os.path.join(HIST, f"{sym}_1d.csv")
    if not os.path.exists(p):
        return None
    out = []
    with io.open(p, encoding="utf-8", newline="") as fh:
        import csv
        for r in csv.DictReader(fh):
            try:
                out.append((int(r["t_ms"]) // 1000, float(r["c"])))
            except (TypeError, ValueError):
                continue
    out.sort()
    if out and out[-1][0] + 86400 > time.time():
        out = out[:-1]
    return out or None


def sd(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


rows = []
for s in COINS:
    d = daily(s)
    if not d or len(d) < 160:
        continue
    import datetime
    closes = [c for _, c in d]
    days = [datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d") for t, _ in d]
    rets = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
    # EWMA variance recursion, lambda fitted on train later; carry the state
    for i in range(30, len(rets) - 6):
        rv1 = abs(rets[i - 1])
        rv5 = sd(rets[i - 5:i])
        rv22 = sd(rets[i - 22:i]) if i >= 22 else sd(rets[:i])
        if rv22 <= 0:
            continue
        y1 = abs(rets[i])
        y5 = sd(rets[i:i + 5])
        if y1 <= 0 or y5 <= 0:
            continue
        rows.append({"sym": s, "day": days[i + 1], "rv1": rv1, "rv5": rv5,
                     "rv22": rv22, "y1": y1, "y5": y5,
                     "hist": rets[max(0, i - 120):i]})
rows.sort(key=lambda r: r["day"])
print(f"panel {len(rows)} coin-days, {len({r['sym'] for r in rows})} coins, "
      f"{rows[0]['day']} -> {rows[-1]['day']}")

F = ["rv1", "rv5", "rv22"]


def fit_har(sub, tgt):
    X = np.column_stack([np.ones(len(sub))] + [np.log(np.array([r[f] for r in sub]) + EPS) for f in F])
    y = np.log(np.array([r[tgt] for r in sub]) + EPS)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    sm = float(np.mean(np.exp(y - X @ b)))
    return b, sm


def pred_har(b, sm, sub):
    X = np.column_stack([np.ones(len(sub))] + [np.log(np.array([r[f] for r in sub]) + EPS) for f in F])
    return np.exp(X @ b) * sm


def fit_lambda(sub, tgt):
    """One-parameter EWMA, lambda chosen on TRAIN by QLIKE. The honest baseline."""
    best, bl = None, 0.94
    for lam in (0.88, 0.90, 0.92, 0.94, 0.96, 0.97):
        p = ewma_pred(sub, lam, tgt)
        a = np.array([r[tgt] for r in sub])
        m = np.isfinite(p) & (p > 0) & (a > 0)
        if m.sum() < 50:
            continue
        q = float(np.mean(a[m] / p[m] - np.log(a[m] / p[m]) - 1))
        if best is None or q < best:
            best, bl = q, lam
    return bl


def ewma_pred(sub, lam, tgt):
    """EWMA sigma from each row's own trailing history. Scaled for the target."""
    out = np.empty(len(sub))
    for i, r in enumerate(sub):
        h = r["hist"]
        if len(h) < 10:
            out[i] = np.nan
            continue
        v = float(np.var(h[:10]))
        for x in h[10:]:
            v = lam * v + (1 - lam) * x * x
        s = math.sqrt(max(v, EPS))
        # |return| has mean sigma*sqrt(2/pi); a 5-day stdev is ~sigma
        out[i] = s * math.sqrt(2 / math.pi) if tgt == "y1" else s
    return out


def qlike(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p) & (a > 0) & (p > 0)
    a, p = a[m], p[m]
    if len(a) < 30:
        return None, 0
    return float(np.mean(a / p - np.log(a / p) - 1)), int(len(a))


def dm_test(a, p1, p2, lag):
    """Diebold-Mariano on the QLIKE differential, Newey-West for overlap."""
    a, p1, p2 = (np.asarray(x, float) for x in (a, p1, p2))
    m = np.isfinite(a) & np.isfinite(p1) & np.isfinite(p2) & (a > 0) & (p1 > 0) & (p2 > 0)
    a, p1, p2 = a[m], p1[m], p2[m]
    if len(a) < 60:
        return None, None
    l1 = a / p1 - np.log(a / p1) - 1
    l2 = a / p2 - np.log(a / p2) - 1
    d = l1 - l2
    n = len(d)
    dbar = float(d.mean())
    g0 = float(np.var(d, ddof=1))
    s = g0
    for k in range(1, min(lag, n - 1) + 1):
        g = float(np.cov(d[:-k], d[k:])[0, 1])
        s += 2 * (1 - k / (lag + 1)) * g
    se = math.sqrt(max(s, 1e-12) / n)
    return dbar, (dbar / se if se > 0 else None)


days = sorted({r["day"] for r in rows})
folds, i = [], MIN_TRAIN // 11
while i < len(days):
    trd, ted = set(days[:i]), set(days[i:i + FOLD_DAYS])
    tr = [r for r in rows if r["day"] in trd]
    te = [r for r in rows if r["day"] in ted]
    i += FOLD_DAYS
    if len(tr) >= MIN_TRAIN and len(te) >= 150:
        folds.append((min(ted), max(ted), tr, te))
print(f"folds: {len(folds)}  ({FOLD_DAYS}-day test blocks, expanding train)\n")

out = {"folds": len(folds), "fold_days": FOLD_DAYS, "horizons": {}}
for tgt in ("y1", "y5"):
    lag = 1 if tgt == "y1" else 5
    print("=" * 100)
    print(f"{tgt.upper()} — HAR vs THREE baselines, {len(folds)} folds"
          f"   (FAULT 1: y1 was never walk-forwarded before)")
    print("=" * 100)
    print(f"  {'baseline':<22}{'HAR wins':>10}{'HAR QLIKE':>11}{'base QLIKE':>12}"
          f"{'DM t':>8}  verdict")
    print("-" * 100)
    tally = collections.defaultdict(lambda: [0, 0, [], [], []])
    for a, b, tr, te in folds:
        bh, smh = fit_har(tr, tgt)
        ph = pred_har(bh, smh, te)
        lam = fit_lambda(tr, tgt)
        act = np.array([r[tgt] for r in te])
        bases = {
            "naive |yesterday|": np.array([r["rv1"] * (1.0 if tgt == "y1" else 1.0) for r in te]),
            "rolling 22d stdev": np.array([r["rv22"] * (math.sqrt(2 / math.pi) if tgt == "y1" else 1.0)
                                           for r in te]),
            f"EWMA (lam={lam})": ewma_pred(te, lam, tgt),
        }
        qh, _ = qlike(act, ph)
        for name, pb in bases.items():
            qb, _ = qlike(act, pb)
            if qh is None or qb is None:
                continue
            key = name.split(" (")[0]
            tally[key][0] += int(qh < qb)
            tally[key][1] += 1
            tally[key][2].append(qh)
            tally[key][3].append(qb)
            dbar, t = dm_test(act, ph, pb, lag)
            if t is not None:
                tally[key][4].append(t)
    for name, (w, n, qhs, qbs, ts) in tally.items():
        if not n:
            continue
        tmean = float(np.mean(ts)) if ts else float("nan")
        beats = (w == n and tmean < -1.96)
        verdict = ("HAR clearly better" if beats else
                   ("HAR better on folds, not significant" if w > n / 2 else "no better"))
        print(f"  {name:<22}{w}/{n:<9}{np.mean(qhs):>11.4f}{np.mean(qbs):>12.4f}"
              f"{tmean:>8.2f}  {verdict}")
        out["horizons"].setdefault(tgt, {})[name] = {
            "har_wins": f"{w}/{n}", "har_qlike": round(float(np.mean(qhs)), 5),
            "base_qlike": round(float(np.mean(qbs)), 5),
            "dm_t_mean": round(tmean, 3) if ts else None,
            "clearly_better": bool(beats)}
    print()

print("=" * 100)
print("VERDICT")
print("=" * 100)
hon = [(t, n, v) for t, d in out["horizons"].items() for n, v in d.items()
       if "EWMA" in n or "rolling" in n]
clear = [x for x in hon if x[2]["clearly_better"]]
if clear:
    for t, n, v in clear:
        print(f"  {t} beats {n}: {v['har_wins']} folds, DM t {v['dm_t_mean']}")
    out["verdict"] = "HAR beats at least one honest baseline"
else:
    print("  HAR does NOT clearly beat either honest baseline at either horizon.")
    print("  The original '22/22 folds' was against the degenerate |yesterday| proxy only,")
    print("  and the 1-day horizon was never walk-forwarded at all.")
    out["verdict"] = "HAR does not beat an honest baseline"
    naive = [(t, v) for t, d in out["horizons"].items() for n, v in d.items() if "naive" in n]
    for t, v in naive:
        print(f"    (vs the degenerate naive at {t}: {v['har_wins']} folds — the old claim)")
with io.open(os.path.join(HERE, "volatility_v2.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote volatility_v2.json")
