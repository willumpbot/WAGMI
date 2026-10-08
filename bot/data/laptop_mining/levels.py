"""Mission 11: what actually happens at the levels the terminal flags?

The terminal's "Near a level" strip fires when price is within half an expected
daily move of the 20-day high, the 20-day low or the 50-day average. The owner
will act on those, so they need base rates rather than folklore.

Definitions, all scaled by the HAR volatility forecast so they mean the same
thing on BTC and on a meme:
    touch        |price - level| <= 0.5 x expected daily move
    break        closes beyond the level by >= 0.5 expected moves within 2 days
    reject       moves >= 1.0 expected moves AWAY from the level within 2 days
                 (away = back to the side it approached from)
    follow       signed move, in expected moves, 2 days after the touch, in the
                 direction of the break

THE NULL THAT MATTERS: a "break rate" of 60% is meaningless if price breaks 60%
of random lines too. Every cell is compared against random-date pseudo-levels set
at the same distance from price, so the level has to beat its own geometry.
"""
import json, io, os, glob, time, collections, warnings
warnings.simplefilter("ignore")
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history")
CUTOFF = "2025-06-01"
EPS = 1e-8
COINS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "DOGE", "AVAX", "LINK", "ARB", "SUI"]
rng = np.random.default_rng(20261008)


def daily(sym):
    p = os.path.join(HIST, f"{sym}_1d.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p).rename(columns={"t_ms": "t"})
    for c in ("o", "h", "l", "c"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["c"]).sort_values("t").reset_index(drop=True)
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
        df = df.iloc[:-1]
    df["day"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    return df


# ---- HAR forecast, train-fitted, as in VOLATILITY.md ----
F = ["rv1", "rv5", "rv22"]
frames = []
for s in COINS:
    d = daily(s)
    if d is None or len(d) < 150:
        continue
    r = d["c"].pct_change() * 100
    f = pd.DataFrame({"day": d["day"], "sym": s, "rv1": r.abs(),
                      "rv5": r.rolling(5).std(), "rv22": r.rolling(22).std(),
                      "y1": r.shift(-1).abs()})
    frames.append(f.dropna(subset=F))
vf = pd.concat(frames, ignore_index=True)
tr = vf[(vf["day"] < CUTOFF) & vf["y1"].notna()]
X = np.log(tr[F] + EPS).values
y = np.log(tr["y1"] + EPS).values
A = np.column_stack([np.ones(len(X)), X])
beta, *_ = np.linalg.lstsq(A, y, rcond=None)
sm = float(np.mean(np.exp(y - A @ beta)))
Xa = np.log(vf[F] + EPS).values
vf["em"] = np.exp(np.column_stack([np.ones(len(Xa)), Xa]) @ beta) * sm   # expected move %
emap = {(r.sym, r.day): float(r.em) for r in vf.itertuples()}
print(f"expected-move model: {len(tr)} train rows, smearing {sm:.4f}")

rows = []
for s in COINS:
    d = daily(s)
    if d is None or len(d) < 150:
        continue
    c, h, l = d["c"], d["h"], d["l"]
    hi20 = h.rolling(20).max().shift(1)      # shift: the level is known before today
    lo20 = l.rolling(20).min().shift(1)
    ma50 = c.rolling(50).mean().shift(1)
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    struct = np.where(e20 > e50, "uptrend", "downtrend")
    for i in range(60, len(d) - 3):
        day = d["day"].iloc[i]
        em = emap.get((s, day))
        if not em or not np.isfinite(em) or em <= 0:
            continue
        px = float(c.iloc[i])
        emp = px * em / 100.0                       # expected move in price units
        for lname, lvl in (("hi20", hi20.iloc[i]), ("lo20", lo20.iloc[i]),
                           ("ma50", ma50.iloc[i])):
            if not np.isfinite(lvl) or lvl <= 0:
                continue
            dist = px - float(lvl)
            if abs(dist) > 0.5 * emp:
                continue                            # not a touch
            side = "from_below" if dist < 0 else "from_above"
            fwd = c.iloc[i + 1:i + 3]
            if len(fwd) < 2:
                continue
            # break: closes beyond the level by >=0.5 expected moves, in the
            # direction of travel (approaching from below => break is upward)
            if side == "from_below":
                broke = bool((fwd > float(lvl) + 0.5 * emp).any())
                rejected = bool((fwd < px - 1.0 * emp).any())
                follow = (float(fwd.iloc[-1]) - px) / emp
            else:
                broke = bool((fwd < float(lvl) - 0.5 * emp).any())
                rejected = bool((fwd > px + 1.0 * emp).any())
                follow = (px - float(fwd.iloc[-1])) / emp
            rows.append({"sym": s, "day": day, "level": lname, "side": side,
                         "structure": str(struct[i]), "em_pct": em,
                         "broke": int(broke), "rejected": int(rejected),
                         "follow": float(follow),
                         "half": "train" if day < CUTOFF else "test"})

# ---- random-date null: pseudo-levels at the same distance, random days ----
null_rows = []
pool = collections.defaultdict(list)
for s in COINS:
    d = daily(s)
    if d is None or len(d) < 150:
        continue
    pool[s] = d
for r in rows:
    d = pool.get(r["sym"])
    if d is None or len(d) < 120:
        continue
    for _ in range(2):                              # 2 nulls per real touch
        i = int(rng.integers(60, len(d) - 3))
        day = d["day"].iloc[i]
        em = emap.get((r["sym"], day))
        if not em or em <= 0:
            continue
        px = float(d["c"].iloc[i])
        emp = px * em / 100.0
        dist = rng.uniform(-0.5, 0.5) * emp         # same geometry as a touch
        lvl = px - dist
        fwd = d["c"].iloc[i + 1:i + 3]
        if len(fwd) < 2:
            continue
        side = "from_below" if dist < 0 else "from_above"
        if side == "from_below":
            broke = bool((fwd > lvl + 0.5 * emp).any())
            follow = (float(fwd.iloc[-1]) - px) / emp
        else:
            broke = bool((fwd < lvl - 0.5 * emp).any())
            follow = (px - float(fwd.iloc[-1])) / emp
        null_rows.append({"level": r["level"], "side": side, "broke": int(broke),
                          "follow": float(follow), "sym": r["sym"], "day": day})

df = pd.DataFrame(rows)
nl = pd.DataFrame(null_rows)
print(f"touches: {len(df)}   nulls: {len(nl)}   coins: {df['sym'].nunique()}")
print(f"span {df['day'].min()} -> {df['day'].max()}")
print(df.groupby(["level", "half"]).size().unstack(fill_value=0).to_string())


def boot_rate(sub, col, iters=2000):
    cl = collections.defaultdict(list)
    for _, r in sub.iterrows():
        cl[(r["sym"], r["day"])].append(r[col])
    keys = list(cl)
    if len(keys) < 5:
        return None, None, None
    point = float(np.mean([x for k in keys for x in cl[k]]))
    ms = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, len(keys), len(keys))
        ms[i] = np.mean([x for j in pick for x in cl[keys[j]]])
    ms.sort()
    return point, float(ms[int(.025 * iters)]), float(ms[int(.975 * iters)])


out = {"definition": {
    "touch": "|price - level| <= 0.5 x expected daily move",
    "break": "closes beyond the level by >= 0.5 expected moves within 2 days",
    "reject": "moves >= 1.0 expected moves away from the level within 2 days",
    "follow": "signed move in expected moves, 2 days out, in the break direction"},
    "cutoff": CUTOFF, "n_touches": int(len(df)), "levels": {}}

print("\n" + "=" * 112)
print("LEVEL BASE RATES — break / reject, vs a random-level null at the same distance")
print("=" * 112)
print(f"  {'level':<8}{'side':<13}{'n':>6}{'break%':>9}{'CI95':>18}"
      f"{'null break%':>13}{'vs null':>9}{'reject%':>9}{'median follow':>15}")
print("-" * 112)
for lvl in ("hi20", "lo20", "ma50"):
    for side in ("from_below", "from_above"):
        sub = df[(df["level"] == lvl) & (df["side"] == side)]
        if len(sub) < 13:
            continue
        b, blo, bhi = boot_rate(sub, "broke")
        rj, _, _ = boot_rate(sub, "rejected")
        nsub = nl[(nl["level"] == lvl) & (nl["side"] == side)]
        nb = float(nsub["broke"].mean()) if len(nsub) > 20 else float("nan")
        diff = (b - nb) * 100 if np.isfinite(nb) else float("nan")
        med = float(sub["follow"].median())
        sig = "*" if (np.isfinite(nb) and (blo > nb or bhi < nb)) else " "
        ci_s = f"[{blo*100:.1f},{bhi*100:.1f}]"
        print(f"  {lvl:<8}{side:<13}{len(sub):>6}{b*100:>8.1f}%{ci_s:>18}"
              + f"{nb*100:>12.1f}%{diff:>+8.1f}{sig}{rj*100:>8.1f}%{med:>15.2f}")
        out["levels"].setdefault(lvl, {}).setdefault(side, {})["all"] = {
            "n": int(len(sub)), "break_rate": round(b, 4),
            "break_ci": [round(blo, 4), round(bhi, 4)],
            "null_break_rate": round(nb, 4) if np.isfinite(nb) else None,
            "vs_null_pts": round(diff, 2) if np.isfinite(diff) else None,
            "beats_null": bool(np.isfinite(nb) and (blo > nb or bhi < nb)),
            "reject_rate": round(rj, 4), "median_follow_em": round(med, 3)}

print("\n  by structure (break rate, and whether train/test agree):")
print(f"  {'level':<8}{'side':<13}{'structure':<12}{'train n':>8}{'train brk':>10}"
       f"{'test n':>8}{'test brk':>10}{'stable':>8}")
print("-" * 112)
for lvl in ("hi20", "lo20", "ma50"):
    for side in ("from_below", "from_above"):
        for st in ("uptrend", "downtrend"):
            a = df[(df["level"] == lvl) & (df["side"] == side) &
                   (df["structure"] == st) & (df["half"] == "train")]
            b_ = df[(df["level"] == lvl) & (df["side"] == side) &
                    (df["structure"] == st) & (df["half"] == "test")]
            if len(a) < 13 or len(b_) < 13:
                continue
            ra, rb = float(a["broke"].mean()), float(b_["broke"].mean())
            stable = "yes" if abs(ra - rb) <= 0.12 else "no"
            print(f"  {lvl:<8}{side:<13}{st:<12}{len(a):>8}{ra*100:>9.1f}%"
                  f"{len(b_):>8}{rb*100:>9.1f}%{stable:>8}")
            out["levels"].setdefault(lvl, {}).setdefault(side, {})[st] = {
                "train_n": int(len(a)), "train_break_rate": round(ra, 4),
                "test_n": int(len(b_)), "test_break_rate": round(rb, 4),
                "stable": stable == "yes"}

print("\n  by forecast-vol quintile (hi20 and lo20 pooled):")
sub = df[df["level"].isin(["hi20", "lo20"])].copy()
sub["q"] = pd.qcut(sub["em_pct"], 5, labels=False, duplicates="drop")
for q, g in sub.groupby("q"):
    b, blo, bhi = boot_rate(g, "broke")
    if b is None:
        continue
    print(f"    Q{int(q)+1}  n={len(g):>5}  em {g['em_pct'].median():>5.2f}%  "
          f"break {b*100:>5.1f}% [{blo*100:>5.1f},{bhi*100:>5.1f}]  "
          f"median follow {g['follow'].median():+.2f} em")
    out.setdefault("by_vol_quintile", {})[f"Q{int(q)+1}"] = {
        "n": int(len(g)), "em_median_pct": round(float(g["em_pct"].median()), 3),
        "break_rate": round(b, 4), "break_ci": [round(blo, 4), round(bhi, 4)],
        "median_follow_em": round(float(g["follow"].median()), 3)}

with io.open(os.path.join(HERE, "levels.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote levels.json")
