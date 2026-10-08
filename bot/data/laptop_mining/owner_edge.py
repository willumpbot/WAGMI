"""Proposal A (PRE-REGISTERED): does the owner have directional edge?

WRITTEN BEFORE SEEING ANY FILL DATA. The server marked this pre-registered, so
the hypotheses, tests, nulls and decision rules below are fixed now and must not
be changed once results are visible. If something needs changing, that is a new
analysis and must be labelled as one.

Why it matters: every directional test in this project graded the BOT's signals
or mechanical voices -- about 98 tests across four datasets, nothing surviving.
The owner is a discretionary trader. Whether THEY have edge is a different
question with a different answer, and it decides what the system is for:
  * owner has edge  -> the system's job is sizing and risk around their calls,
                       which is what risk_voice.py already does
  * owner does not  -> better to know before more capital goes in, and the honest
                       product is carry/vol tooling rather than signals

INPUT: bot/data/hivemind/journal.json (round trips) or journal_fills.jsonl (raw
fills), produced by bot/tools/hivemind/journal.py.

=== PRE-REGISTERED TESTS ===
H1  Directional edge. Forward return in the direction taken, at 4h / 24h / 5d,
    net of 9 bps, measured from the entry mark on validated candles.
    PASS if the mean is positive with a cluster-bootstrap CI excluding zero at
    ANY horizon, AND the sign holds across a 60/40 chronological split.
H2  vs a random-side null. Same timestamps and coins, side assigned at random,
    2,000 draws. PASS if H1's point estimate lies outside the null's 95% band.
H3  vs buy-and-hold. Same coins over the same windows, always long.
    PASS if the owner's signed return exceeds always-long with a CI on the
    DIFFERENCE excluding zero.
H4  Realised P&L. Net P&L per round trip from the journal's own fills, including
    fees. Reported for completeness; NOT used to judge H1-H3 because position
    sizing confounds direction.
H5  Agreement with the hivemind. Split trades by whether the owner's side matched
    the hivemind's net direction at entry. Reported as a difference with a CI.
    No pass/fail -- this is descriptive.

=== PRE-REGISTERED DECISION RULE ===
"Owner has directional edge" requires H1 AND H2 AND H3 to pass.
Any other outcome is reported as "not established", with power stated.

=== PRE-REGISTERED POWER FLOOR ===
Below 30 completed round trips, report descriptive statistics ONLY and state that
the sample cannot support an inference. Do not report a verdict.

No subgroup will be mined. The only splits are the ones named above (horizon,
chronological half, hivemind agreement) plus coin and side, which are reported
descriptively and never used to claim an edge.
"""
import json, io, os, csv, glob, collections, warnings, datetime
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED, HL = os.path.join(HERE, "candles_merged"), os.path.join(HERE, "candles")
HM = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "hivemind")
FEE_BPS = 9.0
MIN_TRADES = 30
SPLIT_FRAC = 0.6
HORIZONS = {"4h": 4 * 3600, "24h": 24 * 3600, "5d": 5 * 86400}
rng = np.random.default_rng(20261008)


def load_candles(sym):
    for d in (MERGED, HL):
        p = os.path.join(d, f"{sym}_1h.csv")
        if os.path.exists(p):
            out = []
            with io.open(p, encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        out.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                                    float(r["l"]), float(r["c"])))
                    except (TypeError, ValueError):
                        continue
            out.sort()
            return out
    return None


def ib(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] <= t:
            best = m; lo = m + 1
        else:
            hi = m - 1
    return best


def ia(c, t):
    lo, hi, best = 0, len(c) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if c[m][0] >= t:
            best = m; hi = m - 1
        else:
            lo = m + 1
    return best


def load_trades():
    """Round trips from journal.json, else rebuilt from journal_fills.jsonl."""
    p = os.path.join(HM, "journal.json")
    if os.path.exists(p):
        d = json.load(io.open(p, encoding="utf-8"))
        for key in ("trades", "round_trips", "closed"):
            if isinstance(d, dict) and isinstance(d.get(key), list):
                return d[key]
        if isinstance(d, list):
            return d
    f = os.path.join(HM, "journal_fills.jsonl")
    if os.path.exists(f):
        fills = []
        with io.open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        fills.append(json.loads(line))
                    except Exception:
                        pass
        by = collections.defaultdict(list)
        for x in fills:
            if x.get("coin"):
                by[x["coin"]].append(x)
        trades = []
        for coin, fs in by.items():
            pos, cur = 0.0, None
            for x in sorted(fs, key=lambda y: y.get("time", 0)):
                try:
                    sz = float(x["sz"]) * (1 if x.get("side") == "B" else -1)
                except (KeyError, TypeError, ValueError):
                    continue
                prev, pos = pos, pos + sz
                if prev == 0 and pos != 0:
                    cur = {"coin": coin, "side": "LONG" if pos > 0 else "SHORT",
                           "open_time": x.get("time"), "entry_px": float(x.get("px", 0) or 0)}
                elif prev != 0 and pos == 0 and cur:
                    cur["close_time"] = x.get("time")
                    trades.append(cur); cur = None
        return trades
    return []


def boot(vals, keys, iters=2000):
    cl = collections.defaultdict(list)
    for v, k in zip(vals, keys):
        if np.isfinite(v):
            cl[k].append(v)
    ks = list(cl)
    if len(ks) < 5:
        return (float(np.mean([x for k in ks for x in cl[k]])) if ks else None), None, None
    point = float(np.mean([x for k in ks for x in cl[k]]))
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(ks), len(ks))
        ms[i] = np.mean([x for j in pick for x in cl[ks[j]]])
    ms.sort()
    return point, float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


trades = load_trades()
print(f"round trips found: {len(trades)}")
if not trades:
    print("\nNo journal data available yet. This script is the PRE-REGISTRATION for")
    print("Proposal A: the tests above are fixed and will run unchanged once")
    print(f"{HM}/journal.json (or journal_fills.jsonl) exists.")
    raise SystemExit(0)

cache, rows = {}, []
for t in trades:
    coin = t.get("coin") or t.get("symbol")
    side = (t.get("side") or "").upper()
    ot = t.get("open_time") or t.get("entry_time")
    if not coin or side not in ("LONG", "SHORT") or not ot:
        continue
    ts = float(ot) / 1000.0 if float(ot) > 1e11 else float(ot)
    if coin not in cache:
        cache[coin] = load_candles(coin)
    c = cache[coin]
    if not c:
        continue
    i0 = ib(c, ts)
    if i0 is None or ts - c[i0][0] > 7200:
        continue
    p0 = c[i0][4]
    if p0 <= 0:
        continue
    sgn = 1.0 if side == "LONG" else -1.0
    rec = {"coin": coin, "side": side, "ts": ts,
           "day": datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%d"),
           "pnl": t.get("pnl"), "agree": t.get("hivemind_agree")}
    for nm, dt in HORIZONS.items():
        j = ia(c, ts + dt)
        if j is None or c[j][0] - (ts + dt) > 3600:
            rec["e_" + nm] = None
            rec["long_" + nm] = None
            continue
        raw = (c[j][1] - p0) / p0
        rec["e_" + nm] = 1e4 * sgn * raw - FEE_BPS       # owner's direction
        rec["long_" + nm] = 1e4 * raw - FEE_BPS          # always-long, same window
    rows.append(rec)

print(f"gradeable trades: {len(rows)}")
if len(rows) < MIN_TRADES:
    print(f"\nPOWER FLOOR NOT MET ({len(rows)} < {MIN_TRADES}). Pre-registered rule:")
    print("report descriptive statistics only, no verdict.")
    for nm in HORIZONS:
        v = [r["e_" + nm] for r in rows if r.get("e_" + nm) is not None]
        if v:
            print(f"  {nm}: n={len(v)} mean {np.mean(v):+.1f} bps (descriptive only)")
    raise SystemExit(0)

days = sorted({r["day"] for r in rows})
cut = days[int(len(days) * SPLIT_FRAC)]
res = {"n_trades": len(rows), "split_day": cut, "fee_bps": FEE_BPS, "tests": {}}
print(f"split at {cut}")

print("\n" + "=" * 92)
print("H1 — DIRECTIONAL EDGE (owner's side, net of fees)")
print("=" * 92)
h1 = False
for nm in HORIZONS:
    sub = [r for r in rows if r.get("e_" + nm) is not None]
    if len(sub) < MIN_TRADES:
        continue
    p, lo, hi = boot([r["e_" + nm] for r in sub], [(r["coin"], r["day"]) for r in sub])
    a = [r for r in sub if r["day"] < cut]
    b = [r for r in sub if r["day"] >= cut]
    sa = np.mean([r["e_" + nm] for r in a]) if len(a) >= 5 else float("nan")
    sb = np.mean([r["e_" + nm] for r in b]) if len(b) >= 5 else float("nan")
    stable = np.isfinite(sa) and np.isfinite(sb) and ((sa > 0) == (sb > 0))
    ok = lo is not None and lo > 0 and stable
    h1 = h1 or ok
    print(f"  {nm:<5} n={len(sub):>4}  {p:>+8.1f} bps  "
          f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else f"  {nm}: n={len(sub)}")
    print(f"         halves {sa:+.1f} / {sb:+.1f}  sign stable: {stable}  -> {'PASS' if ok else 'fail'}")
    res["tests"][f"H1_{nm}"] = {"n": len(sub), "mean_bps": round(p, 2),
                                "ci": [round(lo, 2), round(hi, 2)] if lo is not None else None,
                                "half_a": round(float(sa), 2) if np.isfinite(sa) else None,
                                "half_b": round(float(sb), 2) if np.isfinite(sb) else None,
                                "sign_stable": bool(stable), "pass": bool(ok)}

print("\n" + "=" * 92)
print("H2 — vs RANDOM-SIDE NULL")
print("=" * 92)
h2 = False
for nm in HORIZONS:
    sub = [r for r in rows if r.get("e_" + nm) is not None]
    if len(sub) < MIN_TRADES:
        continue
    raw = np.array([(r["e_" + nm] + FEE_BPS) * (1 if r["side"] == "LONG" else -1) for r in sub])
    nulls = np.empty(2000)
    for i in range(2000):
        s = rng.choice([-1.0, 1.0], size=len(raw))
        nulls[i] = np.mean(s * raw - FEE_BPS)
    nulls.sort()
    obs = float(np.mean([r["e_" + nm] for r in sub]))
    ok = obs > nulls[-50]
    h2 = h2 or ok
    print(f"  {nm:<5} observed {obs:+8.1f} bps   null 95% band "
          f"[{nulls[50]:+.1f},{nulls[-50]:+.1f}]  -> {'PASS' if ok else 'fail'}")
    res["tests"][f"H2_{nm}"] = {"observed_bps": round(obs, 2),
                                "null_95": [round(float(nulls[50]), 2), round(float(nulls[-50]), 2)],
                                "pass": bool(ok)}

print("\n" + "=" * 92)
print("H3 — vs ALWAYS-LONG on the same coins and windows")
print("=" * 92)
h3 = False
for nm in HORIZONS:
    sub = [r for r in rows if r.get("e_" + nm) is not None and r.get("long_" + nm) is not None]
    if len(sub) < MIN_TRADES:
        continue
    d = [r["e_" + nm] - r["long_" + nm] for r in sub]
    p, lo, hi = boot(d, [(r["coin"], r["day"]) for r in sub])
    ok = lo is not None and lo > 0
    h3 = h3 or ok
    print(f"  {nm:<5} owner - always-long: {p:>+8.1f} bps  "
          + (f"[{lo:+.1f},{hi:+.1f}]" if lo is not None else "") + f"  -> {'PASS' if ok else 'fail'}")
    res["tests"][f"H3_{nm}"] = {"diff_bps": round(p, 2),
                                "ci": [round(lo, 2), round(hi, 2)] if lo is not None else None,
                                "pass": bool(ok)}

print("\n" + "=" * 92)
print("H4 — REALISED P&L (descriptive; sizing confounds direction)")
print("=" * 92)
pnl = [float(r["pnl"]) for r in rows if isinstance(r.get("pnl"), (int, float))]
if pnl:
    print(f"  n={len(pnl)}  total ${sum(pnl):,.2f}  mean ${np.mean(pnl):,.2f}  "
          f"median ${np.median(pnl):,.2f}  win rate {100*np.mean([x>0 for x in pnl]):.1f}%")
    res["tests"]["H4"] = {"n": len(pnl), "total": round(sum(pnl), 2),
                          "mean": round(float(np.mean(pnl)), 2),
                          "win_rate_pct": round(100 * float(np.mean([x > 0 for x in pnl])), 1)}
else:
    print("  no P&L field in the journal rows")

print("\n" + "=" * 92)
print("H5 — AGREEMENT WITH THE HIVEMIND (descriptive)")
print("=" * 92)
ag = [r for r in rows if r.get("agree") is not None and r.get("e_24h") is not None]
if len(ag) >= MIN_TRADES:
    w = [r["e_24h"] for r in ag if r["agree"]]
    x = [r["e_24h"] for r in ag if not r["agree"]]
    if len(w) >= 5 and len(x) >= 5:
        print(f"  with hivemind  n={len(w):>4}  {np.mean(w):+.1f} bps")
        print(f"  against it     n={len(x):>4}  {np.mean(x):+.1f} bps")
        res["tests"]["H5"] = {"with_n": len(w), "with_bps": round(float(np.mean(w)), 2),
                              "against_n": len(x), "against_bps": round(float(np.mean(x)), 2)}
else:
    print("  no hivemind-agreement field, or too few trades")

print("\n" + "=" * 92)
print("PRE-REGISTERED DECISION")
print("=" * 92)
verdict = ("OWNER HAS DIRECTIONAL EDGE" if (h1 and h2 and h3)
           else "not established (H1, H2 and H3 must all pass)")
print(f"  H1 {'PASS' if h1 else 'fail'}   H2 {'PASS' if h2 else 'fail'}   "
      f"H3 {'PASS' if h3 else 'fail'}  ->  {verdict}")
res["verdict"] = verdict
res["H1"], res["H2"], res["H3"] = bool(h1), bool(h2), bool(h3)
with io.open(os.path.join(HERE, "owner_edge.json"), "w", encoding="utf-8") as fh:
    json.dump(res, fh, indent=1)
print("\nwrote owner_edge.json")
