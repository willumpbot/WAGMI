"""Validate the local OHLCV cache against Hyperliquid, then build a merged store.

bot/data/cache holds 397 CSVs in two schemas (time-first and time-last), many
overlapping windows per symbol, and some degenerate bars. Before any of it is
used to grade signals it must be checked against a trusted source.

Procedure
  1. parse every file, normalise schema, tag degenerate bars (o==h==l==c)
  2. merge per (symbol, interval), newest file wins on timestamp collision
  3. compare the merged 1h series against the Hyperliquid 1h cache on the
     OVERLAP window, per symbol: median |%diff| of close, plus disagreement rate
  4. accept a symbol only if median |%diff| <= 0.25% and >=95% of overlapping
     bars are within 1%
  5. write candles_merged/<SYM>_1h.csv for accepted symbols only

Outputs cache_validation.json with the per-symbol verdicts.
"""
import csv, glob, io, json, os, collections, datetime, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = "C:/Users/vince/WAGMI/bot/data/cache"
HLDIR = os.path.join(HERE, "candles")
OUTDIR = os.path.join(HERE, "candles_merged")
os.makedirs(OUTDIR, exist_ok=True)

TOL_MEDIAN = 0.25   # percent
TOL_BAR = 1.0       # percent
MIN_WITHIN = 95.0   # percent of bars


def parse_ts(s):
    s = (s or "").strip()
    if not s:
        return None
    if s.replace(".", "", 1).isdigit():
        v = float(s)
        return int(v / 1000 if v > 1e11 else v)
    try:
        return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


files = sorted(glob.glob(os.path.join(CACHE, "*.csv")))
store = collections.defaultdict(dict)      # (sym, iv) -> {t: (o,h,l,c,v,degenerate)}
stats = collections.Counter()
per_file = []

for path in files:
    base = os.path.basename(path)
    parts = base[:-4].split("_")
    if len(parts) < 2:
        stats["unparseable_name"] += 1
        continue
    sym, iv = parts[0], parts[1]
    if not sym.isupper():
        stats["skipped_non_symbol"] += 1
        continue
    n = deg = badrow = 0
    tmin = tmax = None
    try:
        with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                t = parse_ts(r.get("time"))
                try:
                    o, h, l, c = (float(r["open"]), float(r["high"]),
                                  float(r["low"]), float(r["close"]))
                    v = float(r.get("volume") or 0)
                except (TypeError, ValueError, KeyError):
                    badrow += 1
                    continue
                if t is None or min(o, h, l, c) <= 0 or h < l:
                    badrow += 1
                    continue
                d = (o == h == l == c)
                if d:
                    deg += 1
                store[(sym, iv)][t] = (o, h, l, c, v, d)
                n += 1
                tmin = t if tmin is None else min(tmin, t)
                tmax = t if tmax is None else max(tmax, t)
    except OSError:
        stats["unreadable"] += 1
        continue
    stats["files_parsed"] += 1
    stats["rows"] += n
    stats["degenerate"] += deg
    stats["bad_rows"] += badrow
    per_file.append({"file": base, "sym": sym, "iv": iv, "rows": n,
                     "degenerate": deg, "bad": badrow,
                     "from": datetime.datetime.utcfromtimestamp(tmin).strftime("%Y-%m-%d") if tmin else None,
                     "to": datetime.datetime.utcfromtimestamp(tmax).strftime("%Y-%m-%d") if tmax else None})

print(f"files parsed      : {stats['files_parsed']} / {len(files)}")
print(f"rows ingested     : {stats['rows']}")
print(f"degenerate bars   : {stats['degenerate']} ({100*stats['degenerate']/max(stats['rows'],1):.1f}%)")
print(f"bad rows dropped  : {stats['bad_rows']}")
print(f"other             : {{k:v for k,v in stats.items()}}" if False else "")

print("\n=== merged coverage per (symbol, interval) ===")
cov = {}
for (sym, iv), rows in sorted(store.items()):
    ts = sorted(rows)
    degs = sum(1 for t in ts if rows[t][5])
    cov[f"{sym}_{iv}"] = {
        "bars": len(ts),
        "from": datetime.datetime.utcfromtimestamp(ts[0]).strftime("%Y-%m-%d"),
        "to": datetime.datetime.utcfromtimestamp(ts[-1]).strftime("%Y-%m-%d"),
        "degenerate_pct": round(100 * degs / len(ts), 1),
    }
for k, v in sorted(cov.items()):
    if v["bars"] >= 100:
        print(f"  {k:<16} {v['bars']:>6} bars  {v['from']} -> {v['to']}  degen {v['degenerate_pct']:>5.1f}%")


def load_hl(sym):
    p = os.path.join(HLDIR, f"{sym}_1h.csv")
    if not os.path.exists(p):
        return {}
    out = {}
    with io.open(p, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                out[int(r["t_ms"]) // 1000] = float(r["c"])
            except (TypeError, ValueError):
                pass
    return out


print("\n" + "=" * 100)
print("VALIDATION vs HYPERLIQUID (1h close, overlap window only)")
print(f"  accept if median |%diff| <= {TOL_MEDIAN}% AND >= {MIN_WITHIN}% of bars within {TOL_BAR}%")
print("=" * 100)
print(f"  {'symbol':<8}{'overlap':>9}{'median%':>10}{'p90%':>9}{'within1%':>10}  verdict")
print("-" * 100)

verdicts = {}
for (sym, iv) in sorted(store):
    if iv != "1h":
        continue
    hl = load_hl(sym)
    if not hl:
        verdicts[sym] = {"verdict": "NO_HL_REFERENCE", "overlap": 0}
        print(f"  {sym:<8}{0:>9}{'-':>10}{'-':>9}{'-':>10}  NO HL REFERENCE (cannot validate)")
        continue
    cache_rows = store[(sym, iv)]
    common = sorted(set(cache_rows) & set(hl))
    if len(common) < 50:
        verdicts[sym] = {"verdict": "INSUFFICIENT_OVERLAP", "overlap": len(common)}
        print(f"  {sym:<8}{len(common):>9}{'-':>10}{'-':>9}{'-':>10}  INSUFFICIENT OVERLAP")
        continue
    diffs = []
    for t in common:
        a, b = cache_rows[t][3], hl[t]
        if b:
            diffs.append(abs(a - b) / b * 100.0)
    diffs.sort()
    med = statistics.median(diffs)
    p90 = diffs[int(0.9 * len(diffs))]
    within = 100.0 * sum(1 for d in diffs if d <= TOL_BAR) / len(diffs)
    ok = med <= TOL_MEDIAN and within >= MIN_WITHIN
    verdicts[sym] = {"verdict": "ACCEPT" if ok else "REJECT", "overlap": len(common),
                     "median_pct": round(med, 4), "p90_pct": round(p90, 4),
                     "within_1pct": round(within, 1)}
    print(f"  {sym:<8}{len(common):>9}{med:>10.4f}{p90:>9.4f}{within:>9.1f}%  "
          f"{'ACCEPT' if ok else 'REJECT'}")

accepted = [s for s, v in verdicts.items() if v["verdict"] == "ACCEPT"]
print(f"\naccepted symbols: {accepted or 'NONE'}")

written = {}
for sym in accepted:
    rows = store[(sym, "1h")]
    hl = load_hl(sym)
    merged = {}
    for t, r in rows.items():
        if not r[5]:                      # drop degenerate bars
            merged[t] = (r[0], r[1], r[2], r[3], r[4])
    hlfull = os.path.join(HLDIR, f"{sym}_1h.csv")
    if os.path.exists(hlfull):
        with io.open(hlfull, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):      # HL wins where both exist
                try:
                    merged[int(r["t_ms"]) // 1000] = (float(r["o"]), float(r["h"]),
                                                      float(r["l"]), float(r["c"]), float(r["v"]))
                except (TypeError, ValueError):
                    pass
    ts = sorted(merged)
    with io.open(os.path.join(OUTDIR, f"{sym}_1h.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("t_ms,o,h,l,c,v\n")
        for t in ts:
            o, h, l, c, v = merged[t]
            fh.write(f"{t*1000},{o},{h},{l},{c},{v}\n")
    written[sym] = {"bars": len(ts),
                    "from": datetime.datetime.utcfromtimestamp(ts[0]).strftime("%Y-%m-%d"),
                    "to": datetime.datetime.utcfromtimestamp(ts[-1]).strftime("%Y-%m-%d")}
    print(f"  merged {sym}: {len(ts)} bars  {written[sym]['from']} -> {written[sym]['to']}")

with io.open(os.path.join(HERE, "cache_validation.json"), "w", encoding="utf-8") as fh:
    json.dump({"files_parsed": stats["files_parsed"], "rows": stats["rows"],
               "degenerate_bars": stats["degenerate"], "bad_rows": stats["bad_rows"],
               "tolerances": {"median_pct": TOL_MEDIAN, "bar_pct": TOL_BAR,
                              "min_within_pct": MIN_WITHIN},
               "coverage": cov, "verdicts": verdicts, "merged": written}, fh, indent=1)
print("\nwrote cache_validation.json + candles_merged/")
