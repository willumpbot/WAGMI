"""The null for grade_2025.py: what did simply being long do over the same window?

House rule: check the null and the baseline before trusting anything. The 2025
stream showed LONG-side +169.6 bps/1d, which is only meaningful relative to what
the market handed out for free in Aug-Oct 2025.

Baselines computed on the validated daily series, restricted to exactly the days
the signals occupy:
  always-long  : mean 1d forward return, every day, no signal
  always-short : its negative (minus fees both ways)
  random-side  : mean of 2,000 random sign assignments over the same rows
"""
import csv, io, os, glob, json, collections, datetime, random, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = "C:/Users/vince/WAGMI/bot/data/cache"
MERGED = os.path.join(HERE, "candles_merged")
CSVPATH = "C:/Users/vince/Downloads/Paper Trades - jkh.csv"
FEE_BPS = 9.0
random.seed(20261008)
SYMS = ("ETH", "SOL", "BTC")


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
        try:
            return int(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                       .replace(tzinfo=datetime.UTC).timestamp())
        except Exception:
            return None


def load_daily(sym):
    rows = {}
    for pat in (f"{sym}_1d_*.csv", f"{sym}_daily_*.csv", f"{sym}_1d.csv", f"{sym}_daily.csv"):
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
                        rows[datetime.datetime.fromtimestamp(t, datetime.UTC)
                             .strftime("%Y-%m-%d")] = c
            except OSError:
                pass
    return rows


daily = {s: load_daily(s) for s in SYMS}

ACTION = {"BUY": 1, "DEEP BUY": 1, "SELL": -1, "SAFE SELL": -1}
rows = []
with io.open(CSVPATH, encoding="utf-8", errors="replace", newline="") as fh:
    for row in csv.reader(fh):
        if len(row) < 4 or not row[0].strip():
            continue
        ts = parse_ts(row[0])
        sym, act = row[1].strip(), row[2].strip().upper()
        if ts is None or act not in ACTION or sym not in daily:
            continue
        rows.append({"day": datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d"),
                     "sym": sym, "sgn": ACTION[act]})

span = (min(r["day"] for r in rows), max(r["day"] for r in rows))
print(f"signal rows: {len(rows)}   span {span[0]} -> {span[1]}")


def fwd(sym, day, k=1):
    ds = sorted(daily[sym])
    try:
        i = ds.index(day)
    except ValueError:
        return None
    if i + k >= len(ds):
        return None
    p0, p1 = daily[sym][ds[i]], daily[sym][ds[i + k]]
    return (p1 - p0) / p0 if p0 else None


# --- market baseline: every calendar day in the span, per symbol ---
print("\n=== ALWAYS-LONG market baseline over the signal span (1d, bps net of 9bps) ===")
allret = []
for sym in SYMS:
    ds = [d for d in sorted(daily[sym]) if span[0] <= d <= span[1]]
    rs = [fwd(sym, d) for d in ds]
    rs = [x for x in rs if x is not None]
    if not rs:
        continue
    m = 1e4 * sum(rs) / len(rs) - FEE_BPS
    allret.extend(rs)
    tot = 1.0
    for x in rs:
        tot *= (1 + x)
    print(f"  {sym:<5} n={len(rs):>4}  mean {m:>8.1f} bps   "
          f"cumulative over window {100*(tot-1):>+7.1f}%")
mkt = 1e4 * sum(allret) / len(allret) - FEE_BPS
print(f"  {'ALL':<5} n={len(allret):>4}  mean {mkt:>8.1f} bps  <= the free lunch")

# --- same, but only on the (symbol, day) cells the signals actually occupy ---
cells = sorted({(r["sym"], r["day"]) for r in rows})
cv = [fwd(s, d) for s, d in cells]
cv = [x for x in cv if x is not None]
occ = 1e4 * sum(cv) / len(cv) - FEE_BPS
print(f"\n  always-long on the {len(cv)} signal-occupied symbol-days: {occ:>8.1f} bps")

# --- the stream's own realised mean, same rows ---
sv, lv, shv = [], [], []
for r in rows:
    f = fwd(r["sym"], r["day"])
    if f is None:
        continue
    e = 1e4 * r["sgn"] * f - FEE_BPS
    sv.append(e)
    (lv if r["sgn"] > 0 else shv).append(e)
stream = sum(sv) / len(sv)
print(f"  the stream's own signed mean, same rows            : {stream:>8.1f} bps")
print(f"    long-side  n={len(lv):>5}  {sum(lv)/len(lv):>8.1f} bps")
print(f"    short-side n={len(shv):>5}  {sum(shv)/len(shv):>8.1f} bps")

# --- random-side control on the identical rows ---
base = []
for r in rows:
    f = fwd(r["sym"], r["day"])
    if f is not None:
        base.append(f)
rnd = []
for _ in range(2000):
    tot = 0.0
    for f in base:
        tot += 1e4 * (f if random.random() < 0.5 else -f) - FEE_BPS
    rnd.append(tot / len(base))
rnd.sort()
print(f"  random-side control (2,000 draws)                  : "
      f"{statistics.mean(rnd):>8.1f} bps  [{rnd[50]:.1f}, {rnd[-50]:.1f}]")

print("\n" + "=" * 92)
print("VERDICT")
print("=" * 92)
edge_vs_mkt = stream - occ
print(f"  stream {stream:+.1f} vs always-long {occ:+.1f} on the same rows "
      f"=> {edge_vs_mkt:+.1f} bps of selection")
print(f"  long-side {sum(lv)/len(lv):+.1f} vs always-long {occ:+.1f} "
      f"=> {sum(lv)/len(lv) - occ:+.1f} bps")
inside = rnd[50] <= stream <= rnd[-50]
print(f"  stream mean sits {'INSIDE' if inside else 'OUTSIDE'} the random-side 95% band "
      f"[{rnd[50]:.1f}, {rnd[-50]:.1f}]")
print("  => " + ("no evidence of directional skill; the positive numbers are market beta"
                 if inside or edge_vs_mkt <= 0 else
                 "possible selection effect, needs forward confirmation"))

with io.open(os.path.join(HERE, "baseline_2025.json"), "w", encoding="utf-8") as fh:
    json.dump({"span": span, "signal_rows": len(rows),
               "always_long_all_days_bps": round(mkt, 2),
               "always_long_signal_days_bps": round(occ, 2),
               "stream_signed_mean_bps": round(stream, 2),
               "long_side_bps": round(sum(lv) / len(lv), 2),
               "short_side_bps": round(sum(shv) / len(shv), 2),
               "random_side_mean_bps": round(statistics.mean(rnd), 2),
               "random_side_95": [round(rnd[50], 2), round(rnd[-50], 2)],
               "selection_vs_market_bps": round(edge_vs_mkt, 2),
               "inside_random_band": inside}, fh, indent=1)
print("\nwrote baseline_2025.json")
