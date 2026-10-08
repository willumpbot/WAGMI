"""Second-line validation for symbols with NO Hyperliquid overlap.

ARB, AVAX, PEPE, WIF cache 2025-11-11 -> 2026-02-18, which is entirely before
Hyperliquid's public 1h history (starts 2026-03-14), so there is no external
reference. Instead test internal consistency: the 1h bars and the 6h bars are
separate files from separate API pulls, so if 1h aggregates to 6h the two agree
independently.

For each 6h bar: open == first 1h open, close == last 1h close,
high == max(1h highs), low == min(1h lows), over the 6 constituent hours.
Accept if >= 95% of complete 6h windows agree within 0.25% on all four.

Also applies the same test to the HL-accepted symbols as a control -- they
should pass, which is what makes a pass meaningful.
"""
import csv, io, json, os, glob, collections, datetime, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = "C:/Users/vince/WAGMI/bot/data/cache"
OUTDIR = os.path.join(HERE, "candles_merged")
os.makedirs(OUTDIR, exist_ok=True)
TOL = 0.25          # percent
MIN_AGREE = 95.0    # percent of windows


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


def load(sym, iv):
    rows = {}
    for path in glob.glob(os.path.join(CACHE, f"{sym}_{iv}_*.csv")) + \
                glob.glob(os.path.join(CACHE, f"{sym}_{iv}.csv")):
        try:
            with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
                for r in csv.DictReader(fh):
                    t = parse_ts(r.get("time"))
                    try:
                        o, h, l, c = (float(r["open"]), float(r["high"]),
                                      float(r["low"]), float(r["close"]))
                        v = float(r.get("volume") or 0)
                    except (TypeError, ValueError, KeyError):
                        continue
                    if t is None or min(o, h, l, c) <= 0 or h < l:
                        continue
                    if o == h == l == c:      # degenerate, exclude
                        continue
                    rows[t] = (o, h, l, c, v)
        except OSError:
            pass
    return rows


def pct(a, b):
    return abs(a - b) / b * 100.0 if b else 999.0


SYMS = ["ARB", "AVAX", "PEPE", "WIF", "BTC", "ETH", "SOL", "HYPE", "DOGE"]
CONTROL = {"BTC", "ETH", "SOL"}

print("=" * 102)
print("INTERNAL CONSISTENCY — do the 1h bars aggregate into the independently-pulled 6h bars?")
print(f"  accept if >= {MIN_AGREE}% of complete 6h windows agree within {TOL}% on open/high/low/close")
print("=" * 102)
print(f"  {'symbol':<8}{'1h bars':>9}{'6h bars':>9}{'windows':>9}{'agree%':>9}"
      f"{'med dev%':>10}  verdict")
print("-" * 102)

results = {}
for sym in SYMS:
    h1 = load(sym, "1h")
    h6 = load(sym, "6h")
    if not h1 or not h6:
        print(f"  {sym:<8}{len(h1):>9}{len(h6):>9}{'-':>9}{'-':>9}{'-':>10}  NO DATA")
        results[sym] = {"verdict": "NO_DATA", "h1": len(h1), "h6": len(h6)}
        continue
    agree = total = 0
    devs = []
    for t6, (o6, h6v, l6, c6, _) in sorted(h6.items()):
        hours = [h1.get(t6 + i * 3600) for i in range(6)]
        if any(x is None for x in hours):
            continue
        total += 1
        o1 = hours[0][0]
        c1 = hours[-1][3]
        hi1 = max(x[1] for x in hours)
        lo1 = min(x[2] for x in hours)
        d = max(pct(o1, o6), pct(hi1, h6v), pct(lo1, l6), pct(c1, c6))
        devs.append(d)
        if d <= TOL:
            agree += 1
    if total < 20:
        print(f"  {sym:<8}{len(h1):>9}{len(h6):>9}{total:>9}{'-':>9}{'-':>10}  TOO FEW WINDOWS")
        results[sym] = {"verdict": "TOO_FEW_WINDOWS", "windows": total}
        continue
    rate = 100.0 * agree / total
    med = statistics.median(devs)
    ok = rate >= MIN_AGREE
    tag = "ACCEPT" if ok else "REJECT"
    if sym in CONTROL:
        tag += " (control)"
    print(f"  {sym:<8}{len(h1):>9}{len(h6):>9}{total:>9}{rate:>8.1f}%{med:>10.4f}  {tag}")
    results[sym] = {"verdict": "ACCEPT" if ok else "REJECT", "windows": total,
                    "agree_pct": round(rate, 1), "median_dev_pct": round(med, 4),
                    "h1_bars": len(h1), "h6_bars": len(h6),
                    "control": sym in CONTROL}

newly = [s for s, v in results.items()
         if v.get("verdict") == "ACCEPT" and s not in CONTROL
         and not os.path.exists(os.path.join(OUTDIR, f"{s}_1h.csv"))]
print(f"\nnewly admissible via internal consistency: {newly or 'NONE'}")

for sym in newly:
    rows = load(sym, "1h")
    ts = sorted(rows)
    with io.open(os.path.join(OUTDIR, f"{sym}_1h.csv"), "w", encoding="utf-8", newline="") as fh:
        fh.write("t_ms,o,h,l,c,v\n")
        for t in ts:
            o, h, l, c, v = rows[t]
            fh.write(f"{t*1000},{o},{h},{l},{c},{v}\n")
    print(f"  wrote {sym}_1h.csv: {len(ts)} bars "
          f"{datetime.datetime.fromtimestamp(ts[0], datetime.UTC):%Y-%m-%d} -> "
          f"{datetime.datetime.fromtimestamp(ts[-1], datetime.UTC):%Y-%m-%d}")

print("\n=== merged store now holds ===")
for p in sorted(glob.glob(os.path.join(OUTDIR, "*_1h.csv"))):
    with io.open(p, encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh)]
    if rows:
        a = int(rows[0]["t_ms"]) // 1000
        b = int(rows[-1]["t_ms"]) // 1000
        print(f"  {os.path.basename(p):<16} {len(rows):>6} bars  "
              f"{datetime.datetime.fromtimestamp(a, datetime.UTC):%Y-%m-%d} -> "
              f"{datetime.datetime.fromtimestamp(b, datetime.UTC):%Y-%m-%d}")

with io.open(os.path.join(HERE, "internal_validation.json"), "w", encoding="utf-8") as fh:
    json.dump({"tolerance_pct": TOL, "min_agree_pct": MIN_AGREE, "results": results,
               "newly_admissible": newly}, fh, indent=1)
print("\nwrote internal_validation.json")
