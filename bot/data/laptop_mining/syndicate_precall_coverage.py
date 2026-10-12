"""Coverage audit of syndicate_precall.jsonl. NO feature-outcome relationship is computed here
-- the outcome columns (peak_m / peak_h) are never opened, so nothing below could have been
chosen with an outcome in view.
"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "syndicate_precall.jsonl")

rows = [json.loads(l) for l in io.open(OUT, encoding="utf-8") if l.strip()]
ok = [r for r in rows if r.get("status") == "ok"]
miss = [r for r in rows if r.get("status") != "ok"]

print("rows %d   ok %d   SOURCE-MISSING %d" % (len(rows), len(ok), len(miss)))
print("ca recovered %d   ca SOURCE-MISSING %d"
      % (sum(1 for r in rows if r.get("ca")), sum(1 for r in rows if not r.get("ca"))))
print("unique keys %d (dupes would mean a broken resume key)" % len(set(r["key"] for r in rows)))
errs = {}
for r in rows:
    for k in ("err_minute", "err_hour"):
        if r.get(k):
            errs[(k, r[k])] = errs.get((k, r[k]), 0) + 1
print("request errors:", errs or "none")

FEATS = [
    "ret_5m_pre", "ret_1h_pre", "ret_6h_pre", "ret_24h_pre", "ret_7d_pre",
    "rv_1h_pre", "rv_6h_pre", "rv_7d_pre",
    "vol_1h_pre", "vol_6h_pre", "vol_24h_pre", "vol_7d_pre",
    "n_min_bars_6h_pre", "n_min_bars_1h_pre", "n_hour_bars_7d_pre",
    "age_proxy_s", "last_close_pre", "last_min_bar_age_s",
    "high_6h_pre", "low_6h_pre", "dist_from_6h_high_pre", "pct_of_6h_range_pre",
]


def pct(a, b):
    return 0.0 if not b else 100.0 * a / b


def quant(v, q):
    v = sorted(v)
    if not v:
        return None
    i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[i]


N = len(rows)
print("\nPER-FEATURE COVERAGE (denominator = all %d pooled calls attempted)" % N)
print("%-24s %6s %7s %8s %12s %12s %12s %8s"
      % ("feature", "n", "cov%", "n_zero", "p10", "median", "p90", "stale%"))
for f in FEATS:
    vals = [r[f] for r in rows if isinstance(r.get(f), (int, float))
            and not isinstance(r.get(f), bool)]
    nz = sum(1 for v in vals if v == 0)
    st = ""
    sk = f.replace("_pre", "_stale")
    flags = [r[sk] for r in rows if isinstance(r.get(sk), bool)]
    if flags:
        st = "%.1f" % pct(sum(1 for x in flags if x), len(flags))

    def fm(x):
        if x is None:
            return "-"
        ax = abs(x)
        if ax and (ax < 1e-3 or ax >= 1e7):
            return "%.3e" % x
        return "%.4f" % x
    print("%-24s %6d %7.1f %8d %12s %12s %12s %8s"
          % (f, len(vals), pct(len(vals), N), nz,
             fm(quant(vals, 0.10)), fm(quant(vals, 0.50)), fm(quant(vals, 0.90)), st))

print("\nage_censored (pool older than the 1000-bar hourly page, true age unknown): %d of %d"
      % (sum(1 for r in rows if r.get("age_censored")), N))
nmb = [r["n_min_bars_6h_pre"] for r in ok if r.get("n_min_bars_6h_pre") is not None]
print("minute-bar sparsity in the 6h pre-window (max possible 360): "
      "p10 %s  median %s  p90 %s  max %s"
      % (quant(nmb, .1), quant(nmb, .5), quant(nmb, .9), max(nmb) if nmb else None))
print("calls with FEWER THAN 30 pre-call minute bars (brand-new or near-dead pool): %d of %d"
      % (sum(1 for v in nmb if v < 30), len(nmb)))

print("\nCALLS PER DAY (the clustering unit the analysis agent must equal-weight by)")
import collections
import datetime
day = collections.Counter(
    datetime.datetime.fromtimestamp(r["call_ts"], datetime.timezone.utc).strftime("%Y-%m-%d")
    for r in rows)
sz = sorted(day.values())
print("%d distinct UTC days, calls/day min %d median %s max %d"
      % (len(day), sz[0], quant(sz, .5), sz[-1]))
print("days:", " ".join("%s=%d" % kv for kv in sorted(day.items())))
