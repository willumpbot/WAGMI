"""Does the HAR volatility model transfer from Hyperliquid majors to DEX memes?

VOLATILITY.md fitted HAR-RV on 10 majors and validated it 22/22 walk-forward
folds. Mission 12 asks whether that calibration holds on DEX memes, and for a
correction factor if it does not.

Sampling, and its honest limit: pools are drawn across several networks and many
pages, deliberately including low-liquidity ones, because taking only today's
top pools would select survivors. **Tokens that rugged hard enough to be
delisted from GeckoTerminal cannot be sampled at all.** That bias is one-sided --
the missing tokens are the most volatile ones -- so any under-prediction measured
here is a LOWER bound on the true under-prediction.
"""
import json, io, os, math, time, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GT = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "wagmi-research/1.0"}
NETWORKS = ["solana", "eth", "base", "bsc"]
PAGES = (1, 2, 3, 4, 5)
MIN_DAYS = 60
EPS = 1e-8


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as e:
            if k == tries - 1:
                return {"__err__": str(e)}
            time.sleep(1.2 * (k + 1))
    return {"__err__": "unreachable"}


# ---- HAR coefficients as fitted on the majors (loaded, never refitted) ----
vf = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
beta = vf.get("y1_beta")
sm = float(vf.get("y1_smearing") or 1.0)
print(f"HAR coefficients from the majors: {beta}, smearing {sm:.4f}")


def har(rv1, rv5, rv22):
    x = [1.0, math.log(rv1 + EPS), math.log(rv5 + EPS), math.log(rv22 + EPS)]
    return math.exp(sum(b * xi for b, xi in zip(beta, x))) * sm


pools = []
seen = set()
for net in NETWORKS:
    for pg in PAGES:
        d = get(f"{GT}/networks/{net}/pools?page={pg}")
        if "__err__" in d:
            continue
        for p in (d.get("data") or []):
            a = p.get("attributes") or {}
            addr = a.get("address")
            if not addr or addr in seen:
                continue
            seen.add(addr)
            try:
                liq = float(a.get("reserve_in_usd") or 0)
            except (TypeError, ValueError):
                liq = 0.0
            pools.append({"net": net, "addr": addr, "name": a.get("name"), "liq": liq})
        time.sleep(0.25)
print(f"candidate pools sampled: {len(pools)} across {len(NETWORKS)} networks")

rows, used = [], 0
for i, pl in enumerate(pools):
    if used >= 120:
        break
    o = get(f"{GT}/networks/{pl['net']}/pools/{pl['addr']}/ohlcv/day?limit=200")
    time.sleep(0.2)
    if "__err__" in o:
        continue
    lst = ((o.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    lst = list(reversed(lst))
    closes = [float(r[4]) for r in lst if r and len(r) >= 5 and r[4]]
    if len(closes) < MIN_DAYS:
        continue
    rets = [(closes[j] / closes[j - 1] - 1) * 100
            for j in range(1, len(closes)) if closes[j - 1] > 0]
    if len(rets) < MIN_DAYS - 1:
        continue
    used += 1
    def sd(xs):
        if len(xs) < 2:
            return 0.0
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    # walk the series, predicting each day from the 22 before it
    for t in range(22, len(rets) - 1):
        rv1 = abs(rets[t - 1])
        rv5 = sd(rets[t - 5:t])
        rv22 = sd(rets[t - 22:t])
        if rv22 <= 0:
            continue
        pred = har(rv1, rv5, rv22)
        act = abs(rets[t])
        if not (np.isfinite(pred) and np.isfinite(act)) or pred <= 0:
            continue
        rows.append({"pool": pl["name"], "net": pl["net"], "liq": pl["liq"],
                     "pred": pred, "act": act})
    if used % 20 == 0:
        print(f"  {used} pools with >={MIN_DAYS}d history ...", flush=True)

print(f"\npools used: {used}   prediction rows: {len(rows)}")
if len(rows) < 500:
    raise SystemExit("not enough meme history sampled")

pred = np.array([r["pred"] for r in rows])
act = np.array([r["act"] for r in rows])
ratio = act / pred
print("\n" + "=" * 92)
print("DOES THE MAJORS' HAR MODEL TRANSFER TO DEX MEMES?")
print("=" * 92)
print(f"  mean predicted move   {pred.mean():>8.3f}%")
print(f"  mean actual move      {act.mean():>8.3f}%")
print(f"  mean actual/predicted {ratio.mean():>8.3f}x   median {np.median(ratio):>6.3f}x")
print(f"  correlation(pred, act) {np.corrcoef(pred, act)[0,1]:>7.3f}")

# the correction factor that makes the model unbiased in the mean
mult = float(act.mean() / pred.mean())
print(f"\n  CORRECTION FACTOR (mean-matching): {mult:.3f}x")

print("\n  by predicted decile — is the error flat or size-dependent?")
order = np.argsort(pred)
print(f"    {'decile':<8}{'n':>7}{'pred':>9}{'actual':>9}{'ratio':>8}")
cal = []
for d in range(10):
    idx = order[d * len(order) // 10:(d + 1) * len(order) // 10]
    if len(idx) < 20:
        continue
    pm, am = float(pred[idx].mean()), float(act[idx].mean())
    print(f"    {d+1:<8}{len(idx):>7}{pm:>9.3f}{am:>9.3f}{am/pm:>8.3f}")
    cal.append({"decile": d + 1, "n": int(len(idx)), "pred": round(pm, 4),
                "actual": round(am, 4), "ratio": round(am / pm, 3)})

print("\n  by liquidity bucket:")
liq = np.array([r["liq"] for r in rows])
for lab, m in (("< $100k", liq < 1e5), ("$100k-$1M", (liq >= 1e5) & (liq < 1e6)),
               (">= $1M", liq >= 1e6)):
    if m.sum() < 50:
        continue
    print(f"    {lab:<12} n={int(m.sum()):>6}  pred {pred[m].mean():>6.3f}%  "
          f"actual {act[m].mean():>6.3f}%  ratio {act[m].mean()/pred[m].mean():>5.3f}x")

out = {"har_source": "fitted on 10 Hyperliquid majors (VOLATILITY.md)",
       "pools_used": used, "rows": len(rows), "min_days": MIN_DAYS,
       "mean_pred_pct": round(float(pred.mean()), 4),
       "mean_actual_pct": round(float(act.mean()), 4),
       "mean_ratio": round(float(ratio.mean()), 4),
       "median_ratio": round(float(np.median(ratio)), 4),
       "correlation": round(float(np.corrcoef(pred, act)[0, 1]), 4),
       "correction_factor": round(mult, 4),
       "calibration_by_decile": cal,
       "survivorship_note":
           "pools are sampled from GeckoTerminal's CURRENT listings across 4 networks and 5 "
           "pages each, deliberately including low-liquidity pools. Tokens that rugged hard "
           "enough to be delisted cannot be sampled, and those are the most volatile ones, so "
           "the measured under-prediction is a LOWER bound."}
with io.open(os.path.join(HERE, "meme_calibration.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote meme_calibration.json")
