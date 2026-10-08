"""Full-history extension: grade the 2025 paper-trade signals.

Downloads/'Paper Trades - jkh.csv' holds 40,187 rows spanning 2025-08-30 ->
2025-10-11 -- a year before the server's window and outside every other dataset
here. Provenance is UNKNOWN ("jkh"); it is treated as an unattributed third-party
signal stream, not as the owner's bot.

Only daily bars reach that far back, so:
  STEP 1  validate the daily cache against the already-validated 1h store by
          aggregating 1h -> daily over their overlap (2025-11-11 -> 2026-06-07).
          Daily bars for Aug-Oct 2025 have NO second source, so trust is an
          inference from the source passing on the overlap -- stated, not hidden.
  STEP 2  grade actionable rows (BUY/SELL/DEEP BUY/SAFE SELL) at 1d and 3d
          horizons for symbols whose daily series passed.

Resolution is coarse: a 14:58 decision is graded to the next daily close, so up
to ~24h of boundary drift. This can only answer one question -- did the stream
have directional edge at all -- not anything about timing.
"""
import csv, io, os, glob, json, collections, datetime, statistics, random, math

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = "C:/Users/vince/WAGMI/bot/data/cache"
MERGED = os.path.join(HERE, "candles_merged")
CSVPATH = "C:/Users/vince/Downloads/Paper Trades - jkh.csv"
FEE_BPS = 9.0
random.seed(20261008)


def parse_ts(s):
    s = (s or "").strip()
    if not s:
        return None
    if s.replace(".", "", 1).isdigit():
        v = float(s)
        return int(v / 1000 if v > 1e11 else v)
    for fmt in (None, "%Y-%m-%d %H:%M:%S"):
        try:
            if fmt is None:
                return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
            return int(datetime.datetime.strptime(s, fmt).replace(tzinfo=datetime.UTC).timestamp())
        except Exception:
            pass
    return None


def load_daily(sym):
    rows = {}
    pats = [f"{sym}_1d_*.csv", f"{sym}_daily_*.csv", f"{sym}_1d.csv", f"{sym}_daily.csv"]
    for pat in pats:
        for path in glob.glob(os.path.join(CACHE, pat)):
            try:
                with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
                    for r in csv.DictReader(fh):
                        t = parse_ts(r.get("time"))
                        try:
                            o, h, l, c = (float(r["open"]), float(r["high"]),
                                          float(r["low"]), float(r["close"]))
                        except (TypeError, ValueError, KeyError):
                            continue
                        if t is None or min(o, h, l, c) <= 0 or o == h == l == c:
                            continue
                        day = datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d")
                        rows[day] = (o, h, l, c)
            except OSError:
                pass
    return rows


def load_1h_as_daily(sym):
    p = os.path.join(MERGED, f"{sym}_1h.csv")
    if not os.path.exists(p):
        return {}
    buckets = collections.defaultdict(list)
    with io.open(p, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                t = int(r["t_ms"]) // 1000
                buckets[datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d")].append(
                    (t, float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])))
            except (TypeError, ValueError):
                pass
    out = {}
    for day, bars in buckets.items():
        if len(bars) < 20:          # need a near-complete day
            continue
        bars.sort()
        out[day] = (bars[0][1], max(b[2] for b in bars),
                    min(b[3] for b in bars), bars[-1][4])
    return out


print("=" * 96)
print("STEP 1 — validate the daily cache against the validated 1h store (aggregated to daily)")
print("=" * 96)
print(f"  {'symbol':<8}{'overlap':>9}{'median%':>10}{'within1%':>10}  verdict")
print("-" * 96)
ok_syms, dailies = [], {}
for sym in ("ETH", "SOL", "BTC", "HYPE"):
    d = load_daily(sym)
    ref = load_1h_as_daily(sym)
    common = sorted(set(d) & set(ref))
    if len(common) < 40:
        print(f"  {sym:<8}{len(common):>9}{'-':>10}{'-':>10}  INSUFFICIENT OVERLAP")
        continue
    devs = [abs(d[k][3] - ref[k][3]) / ref[k][3] * 100 for k in common if ref[k][3]]
    med = statistics.median(devs)
    within = 100 * sum(1 for x in devs if x <= 1.0) / len(devs)
    good = med <= 0.25 and within >= 95
    print(f"  {sym:<8}{len(common):>9}{med:>10.4f}{within:>9.1f}%  {'ACCEPT' if good else 'REJECT'}")
    if good:
        ok_syms.append(sym)
        dailies[sym] = d
print(f"\n  daily series accepted: {ok_syms or 'NONE'}")
if not ok_syms:
    raise SystemExit("no daily series validated -> 2025 data cannot be graded")

for s in ok_syms:
    ks = sorted(dailies[s])
    print(f"    {s}: {len(ks)} days  {ks[0]} -> {ks[-1]}")

# ---------------- STEP 2 ----------------
ACTION = {"BUY": 1, "DEEP BUY": 1, "SELL": -1, "SAFE SELL": -1}
sigs = []
with io.open(CSVPATH, encoding="utf-8", errors="replace", newline="") as fh:
    for row in csv.reader(fh):
        if len(row) < 4 or not row[0].strip():
            continue
        ts = parse_ts(row[0])
        sym, act = row[1].strip(), row[2].strip().upper()
        if ts is None or act not in ACTION or sym not in dailies:
            continue
        try:
            px = float(row[3])
        except ValueError:
            continue
        if px <= 0:
            continue
        sigs.append({"ts": ts, "day": datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d"),
                     "sym": sym, "sgn": ACTION[act], "act": act, "px": px})

print(f"\n=== STEP 2 — grade 2025 signals ({len(sigs)} actionable rows on accepted symbols) ===")
if not sigs:
    raise SystemExit("no gradeable 2025 rows")
print(f"  span: {min(s['day'] for s in sigs)} -> {max(s['day'] for s in sigs)}")

# price sanity: the CSV's own price vs the daily bar range for that day
bad = 0
for s in sigs:
    bar = dailies[s["sym"]].get(s["day"])
    if not bar or not (bar[2] * 0.97 <= s["px"] <= bar[1] * 1.03):
        s["sane"] = False
        bad += 1
    else:
        s["sane"] = True
print(f"  rows whose quoted price sits outside that day's range (±3%): {bad} "
      f"({100*bad/len(sigs):.1f}%) — dropped")
sigs = [s for s in sigs if s["sane"]]
print(f"  rows kept: {len(sigs)}")
if not sigs:
    raise SystemExit("all 2025 rows failed the price sanity check")

graded = []
for s in sigs:
    dd = dailies[s["sym"]]
    days = sorted(dd)
    try:
        i = days.index(s["day"])
    except ValueError:
        continue
    p0 = dd[s["day"]][3]
    rec = {"day": s["day"], "sym": s["sym"], "act": s["act"], "sgn": s["sgn"]}
    anyh = False
    for label, k in (("1d", 1), ("3d", 3)):
        if i + k < len(days):
            p1 = dd[days[i + k]][3]
            rec["e_" + label] = 1e4 * s["sgn"] * (p1 - p0) / p0 - FEE_BPS
            anyh = True
        else:
            rec["e_" + label] = None
    if anyh:
        graded.append(rec)

print(f"  graded: {len(graded)}")


def boot(rows, key, iters=3000):
    cl = collections.defaultdict(list)
    for r in rows:
        if r.get(key) is not None:
            cl[(r["sym"], r["day"])].append(r[key])
    keys = list(cl)
    if len(keys) < 3:
        return None, None
    ms = []
    for _ in range(iters):
        pool = []
        for _ in range(len(keys)):
            pool.extend(cl[keys[random.randrange(len(keys))]])
        if pool:
            ms.append(sum(pool) / len(pool))
    ms.sort()
    return ms[int(.025 * len(ms))], ms[int(.975 * len(ms))]


def show(label, rows):
    out = [f"  {label:<18}"]
    n4 = 0
    for key in ("e_1d", "e_3d"):
        v = [r[key] for r in rows if r.get(key) is not None]
        if not v:
            out.append(f"{'n/a':>22}")
            continue
        n4 = max(n4, len(v))
        lo, hi = boot(rows, key)
        mean = sum(v) / len(v)
        star = "*" if lo is not None and (hi < 0 or lo > 0) else " "
        ci = f"[{lo:>6.0f},{hi:>6.0f}]" if lo is not None else " " * 15
        out.append(f"{mean:>8.1f}{star}{ci}")
    flag = "  n<13" if n4 < 13 else ""
    print("".join(out) + f"  n={n4}{flag}")


print("\n" + "=" * 96)
print("2025 SIGNAL STREAM — forward return in proposed direction, bps net of 9 bps (daily closes)")
print("=" * 96)
print(f"  {'slice':<18}{'1d mean':>8} {'CI95':>14}{'3d mean':>8} {'CI95':>14}")
print("-" * 96)
show("ALL", graded)
for sym in sorted({g["sym"] for g in graded}):
    show(sym, [g for g in graded if g["sym"] == sym])
for sgn, lab in ((1, "LONG-side"), (-1, "SHORT-side")):
    show(lab, [g for g in graded if g["sgn"] == sgn])
for act in sorted({g["act"] for g in graded}):
    show(act, [g for g in graded if g["act"] == act])

v = [g["e_1d"] for g in graded if g.get("e_1d") is not None]
lo, hi = boot(graded, "e_1d")
payload = {"source": CSVPATH, "provenance": "UNKNOWN ('jkh') — unattributed third-party stream",
           "daily_series_validated": ok_syms,
           "validation_note": "daily cache matched the HL-validated 1h store on 2025-11-11..2026-06-07; "
                              "Aug-Oct 2025 bars have no second source and are trusted by inference",
           "span": [min(g["day"] for g in graded), max(g["day"] for g in graded)],
           "graded": len(graded), "dropped_price_insane": bad,
           "all_1d_mean_bps": round(sum(v) / len(v), 2) if v else None,
           "all_1d_ci": [round(lo, 2), round(hi, 2)] if lo is not None else None,
           "resolution_caveat": "daily closes only; up to ~24h boundary drift"}
with io.open(os.path.join(HERE, "grade_2025.json"), "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=1)
print("\nwrote grade_2025.json")
