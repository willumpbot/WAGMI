#!/usr/bin/env python
"""
liq_magnet_calibration.py -- HONEST calibration: do LIQUIDATION-PRICE CLUSTERS
act as MAGNETS? Does price subsequently REACH a cluster of prior liquidations
MORE than it reaches a DISTANCE-MATCHED RANDOM level?
=============================================================================
READ-ONLY on all data/ files. Writes NOTHING outside tools/copilot/ (this
file) and the scratchpad candle cache. No Discord, no process restart.

THE ONE THING THAT MATTERS (the crux):
  Magnets form NEAR the current price, so "price reaches a nearby level" is
  TRIVIALLY common. The entire test is: reach-rate(MAGNET) vs reach-rate of a
  DISTANCE-MATCHED, SAME-SIDE control level with NO cluster. If magnets are
  NOT reached more than distance+side-matched randoms, the magnet is an
  illusion of proximity == NULL. We ALSO report a vol-matched refinement
  (clusters form in high-vol bursts -> high forward vol -> more reach at ANY
  distance; distance-matching alone does not kill that confound).

PRE-REGISTERED DEFINITIONS (fixed before looking at outcomes):
  - Price path: Hyperliquid 5m candles (independent of the Bybit liq feed).
  - Trailing cluster window  W_HOURS      = 12h  (only liqs with ts < t).
  - Cluster price tolerance  CLUSTER_TOL  = 0.20% (agglomerative bins).
  - Cluster STRENGTH counts INDEPENDENT liq-episodes, not raw events: same-
    symbol, same-side events within EPISODE_GAP_SEC=300s collapse to ONE
    (the partial-fill pseudoreplication lesson from liq_hypothesis_harness).
  - Magnet threshold         K_MIN        = 3   (>=3 independent liq-episodes
    at a level).  Sensitivity swept over {2,3,4}.
  - Distance band            D_BAND       = [0.30%, 3.00%] of price(t).
  - Forward horizon          H_HOURS      = 6h.
  - Anchor grid              STEP_HOURS   = 1h.
  - REACH: within (t, t+H], candle HIGH >= level (magnet ABOVE price) or
    candle LOW <= level (magnet BELOW price).
  - INDEPENDENCE dedup: a persistent cluster re-sampled every hour is NOT N
    independent episodes. Within (symbol, side, level-bin) we greedily keep
    magnet episodes separated by >= H_HOURS so forward windows never overlap
    and the same standing cluster is counted ONCE per non-overlapping window.
  - CONTROL: distance+side matched. For the reach-rate at distance D on side
    S we take the BACKGROUND over all anchors that had NO cluster>=K near
    that (side, D) -- i.e. "how often does price move D in direction S within
    H when there is no magnet there". We reweight the background to match the
    MAGNET (side, D-bin) histogram exactly (stratified matching). The
    vol-matched variant additionally stratifies on a realized-vol bucket.
  - NEGATIVE CONTROL: shuffle liq PRICES within symbol (keep timestamps),
    rebuild magnets, re-run -> the magnet-vs-control edge must collapse to ~0.
  - OOS: chronological split at the median anchor time; the effect must hold
    on the held-out (later) slice.

VERDICT LOGIC:
  MAGNET-REAL  : reach(magnet) > reach(control), n>=30 independent magnet
                 episodes, p<0.05, survives OOS + negative-control.
  NULL         : no edge over distance+side-matched control, OR fails OOS/neg.
  UNDERPOWERED : < 30 independent magnet episodes (5 days may simply not have
                 enough) -> report descriptively, force NO p-value claim.

Usage:
    python tools/copilot/liq_magnet_calibration.py            # full run
    python tools/copilot/liq_magnet_calibration.py --no-net   # cache-only (no HL fetch)
Reproduce: fixed SEED=1337 below.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

SEED = 1337

# ---- pre-registered parameters -------------------------------------------
W_HOURS = 12
CLUSTER_TOL = 0.0020          # 0.20%
EPISODE_GAP_SEC = 300         # partial-fill collapse
K_MIN = 3
K_SWEEP = (2, 3, 4)
D_MIN, D_MAX = 0.0030, 0.0300  # 0.30% .. 3.00%
D_BIN = 0.0025                 # 0.25% distance bins for stratified matching
H_HOURS = 6
STEP_HOURS = 1
SYMBOLS = ("BTC", "SOL")      # well-powered; HL candle symbols
VOL_BINS = 3                  # tertiles for the vol-matched refinement

LIQ_PATH = os.path.join("data", "copilot", "liquidations", "liq_events.jsonl")
CACHE_DIR = os.path.join(
    os.environ.get("TEMP", "/tmp"), "liq_magnet_cache")


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------
def load_liqs():
    """Return {symbol: [ {ts, side, price}, ... ]} sorted by ts (epoch sec)."""
    by_sym = defaultdict(list)
    with open(LIQ_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            try:
                ts = datetime.fromisoformat(e["ts_utc"]).timestamp()
            except Exception:
                continue
            by_sym[e["symbol"]].append(
                {"ts": ts, "side": e.get("side"), "price": float(e["price"])})
    for s in by_sym:
        by_sym[s].sort(key=lambda r: r["ts"])
    return by_sym


def hl_candles(coin, interval, start_ms, end_ms):
    body = {"type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval,
                    "startTime": start_ms, "endTime": end_ms}}
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read())
    return [{"t": c["t"] / 1000.0, "o": float(c["o"]), "h": float(c["h"]),
             "l": float(c["l"]), "c": float(c["c"])} for c in d]


def get_candles(coin, start_sec, end_sec, no_net):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{coin}_5m.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            c = json.load(f)
        if c and c[0]["t"] <= start_sec + 3600 and c[-1]["t"] >= end_sec - 3600:
            return c
    if no_net:
        raise RuntimeError(f"no cache for {coin} and --no-net set")
    # fetch generously padded
    cs = hl_candles(coin, "5m", int((start_sec - 3600) * 1000),
                    int((end_sec + 3600) * 1000))
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(cs, f)
    return cs


# ---------------------------------------------------------------------------
# price-path helpers
# ---------------------------------------------------------------------------
def price_at(candles, t):
    """Close of the candle whose interval contains t (last candle with c.t<=t)."""
    lo, hi, ans = 0, len(candles) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid]["t"] <= t:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return candles[ans]["c"] if ans is not None else None


def forward_extremes(candles, t0, t1):
    """(max high, min low) over candles with t0 < c.t <= t1. None if empty."""
    hi = -math.inf
    lo = math.inf
    n = 0
    for c in candles:
        if c["t"] <= t0:
            continue
        if c["t"] > t1:
            break
        hi = max(hi, c["h"])
        lo = min(lo, c["l"])
        n += 1
    if n == 0:
        return None
    return hi, lo


def realized_vol(candles, t, back_sec):
    """Std of 5m log-returns over (t-back_sec, t]. None if too few bars."""
    rs = []
    prev = None
    for c in candles:
        if c["t"] <= t - back_sec:
            prev = c["c"]
            continue
        if c["t"] > t:
            break
        if prev is not None and prev > 0 and c["c"] > 0:
            rs.append(math.log(c["c"] / prev))
        prev = c["c"]
    if len(rs) < 5:
        return None
    m = sum(rs) / len(rs)
    return (sum((r - m) ** 2 for r in rs) / (len(rs) - 1)) ** 0.5


# ---------------------------------------------------------------------------
# liquidation clustering (entry-time-safe: only ts < t)
# ---------------------------------------------------------------------------
def collapse_episodes(events):
    """Collapse same-side events within EPISODE_GAP_SEC into one liq-episode.
    Returns list of {price, side, ts} representative points (one per episode)."""
    byside = defaultdict(list)
    for e in events:
        byside[e["side"]].append(e)
    out = []
    for side, evs in byside.items():
        evs.sort(key=lambda r: r["ts"])
        cur = []
        for e in evs:
            if cur and (e["ts"] - cur[-1]["ts"]) > EPISODE_GAP_SEC:
                out.append(_rep(cur, side))
                cur = []
            cur.append(e)
        if cur:
            out.append(_rep(cur, side))
    return out


def _rep(cur, side):
    # notional-agnostic representative: median price, latest ts
    ps = sorted(e["price"] for e in cur)
    return {"price": ps[len(ps) // 2], "side": side, "ts": cur[-1]["ts"]}


def cluster_levels(episodes):
    """Agglomerate liq-episode representative prices into levels within
    CLUSTER_TOL. Returns [{level, strength, sides}]. strength = # independent
    liq-episodes on the level."""
    pts = sorted(episodes, key=lambda r: r["price"])
    clusters = []
    for p in pts:
        placed = False
        for cl in clusters:
            if abs(p["price"] - cl["level"]) / cl["level"] <= CLUSTER_TOL:
                cl["members"].append(p)
                cl["level"] = sum(m["price"] for m in cl["members"]) / len(cl["members"])
                placed = True
                break
        if not placed:
            clusters.append({"level": p["price"], "members": [p]})
    out = []
    for cl in clusters:
        out.append({"level": cl["level"], "strength": len(cl["members"]),
                    "sides": sorted(set(m["side"] for m in cl["members"]))})
    return out


# ---------------------------------------------------------------------------
# candidate enumeration
# ---------------------------------------------------------------------------
def d_bin(d):
    return int(d / D_BIN)


def enumerate_candidates(symbol, liqs, candles, k_min):
    """For each hourly anchor build MAGNET and PLACEBO candidate levels.

    Returns list of dicts:
      {symbol, t, side ('up'/'down'), level, d, dbin, is_magnet, strength,
       reached, volbucket_raw}
    Entry-time-safe: clusters from ts<t only; reach strictly in (t, t+H].
    """
    if not liqs or not candles:
        return []
    t_start = max(candles[0]["t"], liqs[0]["ts"]) + W_HOURS * 3600
    t_end = candles[-1]["t"] - H_HOURS * 3600
    step = STEP_HOURS * 3600
    cands = []
    t = math.ceil(t_start / step) * step
    while t <= t_end:
        p0 = price_at(candles, t)
        if p0 is None or p0 <= 0:
            t += step
            continue
        # prior liqs in trailing window, entry-time-safe
        prior = [e for e in liqs if t - W_HOURS * 3600 <= e["ts"] < t]
        if not prior:
            t += step
            continue
        levels = cluster_levels(collapse_episodes(prior))
        fx = forward_extremes(candles, t, t + H_HOURS * 3600)
        if fx is None:
            t += step
            continue
        fhi, flo = fx
        rv = realized_vol(candles, t, W_HOURS * 3600)
        # index existing cluster levels for placebo exclusion
        # MAGNET candidates: qualifying levels in the D band
        for lv in levels:
            d = abs(lv["level"] - p0) / p0
            if not (D_MIN <= d <= D_MAX):
                continue
            side = "up" if lv["level"] > p0 else "down"
            reached = (fhi >= lv["level"]) if side == "up" else (flo <= lv["level"])
            is_mag = lv["strength"] >= k_min
            cands.append({
                "symbol": symbol, "t": t, "side": side, "level": lv["level"],
                "d": d, "dbin": d_bin(d), "is_magnet": is_mag,
                "strength": lv["strength"], "reached": reached, "rv": rv})
        # PLACEBO candidates: synthetic levels at each D-bin center, both
        # sides, that do NOT coincide with ANY cluster>=k_min level.
        mag_prices = [lv["level"] for lv in levels if lv["strength"] >= k_min]
        nb = int((D_MAX - D_MIN) / D_BIN) + 1
        for i in range(nb):
            dc = D_MIN + (i + 0.5) * D_BIN
            if dc > D_MAX:
                break
            for side in ("up", "down"):
                lvl = p0 * (1 + dc) if side == "up" else p0 * (1 - dc)
                # exclude if within CLUSTER_TOL of a real magnet level
                if any(abs(lvl - mp) / mp <= CLUSTER_TOL for mp in mag_prices):
                    continue
                reached = (fhi >= lvl) if side == "up" else (flo <= lvl)
                cands.append({
                    "symbol": symbol, "t": t, "side": side, "level": lvl,
                    "d": dc, "dbin": d_bin(dc), "is_magnet": None,
                    "strength": 0, "reached": reached, "rv": rv})
        t += step
    return cands


# ---------------------------------------------------------------------------
# independence dedup for MAGNET episodes
# ---------------------------------------------------------------------------
def dedup_magnets(mags):
    """Greedy: within (symbol, side, level-bin) keep episodes separated by
    >= H_HOURS so forward windows never overlap / a standing cluster is
    counted once per non-overlapping window. level-bin = round(level/(CLUSTER
    _TOL*level)) approximated by fractional bucket."""
    groups = defaultdict(list)
    for m in mags:
        # bucket the level to ~CLUSTER_TOL resolution
        lb = round(math.log(m["level"]) / CLUSTER_TOL)
        groups[(m["symbol"], m["side"], lb)].append(m)
    kept = []
    sep = H_HOURS * 3600
    for _, arr in groups.items():
        arr.sort(key=lambda m: m["t"])
        last = -math.inf
        for m in arr:
            if m["t"] - last >= sep:
                kept.append(m)
                last = m["t"]
    return kept


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------
def two_prop_z(x1, n1, x2, n2):
    """Two-proportion z-test. Returns (p1, p2, z, two-sided p)."""
    if n1 == 0 or n2 == 0:
        return (float("nan"), float("nan"), float("nan"), float("nan"))
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return (p1, p2, 0.0, 1.0)
    z = (p1 - p2) / se
    pval = math.erfc(abs(z) / math.sqrt(2))
    return (p1, p2, z, pval)


def matched_control_rate(magnets, placebos, strata_keys):
    """Distance(+optionally vol/side)-matched control reach-rate: reweight
    placebo reach to the MAGNET stratum histogram. strata_keys is a function
    cand->key. Returns (control_rate, effective_n_placebo, per_stratum)."""
    mag_w = defaultdict(int)
    for m in magnets:
        mag_w[strata_keys(m)] += 1
    plac = defaultdict(lambda: [0, 0])  # key -> [reached, total]
    for p in placebos:
        k = strata_keys(p)
        plac[k][1] += 1
        if p["reached"]:
            plac[k][0] += 1
    num = 0.0
    den = 0.0
    used = 0
    for k, w in mag_w.items():
        if k in plac and plac[k][1] > 0:
            rate = plac[k][0] / plac[k][1]
            num += w * rate
            den += w
            used += w
    if den == 0:
        return (float("nan"), 0, {})
    return (num / den, used, dict(plac))


def block_bootstrap_diff(magnets, placebos, strata_keys, n_boot=2000, rng=None):
    """Bootstrap CI for reach(magnet) - matched_control. Resample MAGNET
    episodes (the binding independent unit) with replacement; control rate
    recomputed against fixed placebo pool with the resampled magnet
    histogram. Returns (mean_diff, lo, hi)."""
    if rng is None:
        rng = random.Random(SEED)
    if not magnets:
        return (float("nan"), float("nan"), float("nan"))
    # pre-index placebo strata
    plac = defaultdict(lambda: [0, 0])
    for p in placebos:
        k = strata_keys(p)
        plac[k][1] += 1
        if p["reached"]:
            plac[k][0] += 1
    diffs = []
    m = len(magnets)
    for _ in range(n_boot):
        sample = [magnets[rng.randrange(m)] for _ in range(m)]
        mag_rate = sum(1 for s in sample if s["reached"]) / m
        num = den = 0.0
        for s in sample:
            k = strata_keys(s)
            if k in plac and plac[k][1] > 0:
                num += plac[k][0] / plac[k][1]
                den += 1
        if den == 0:
            continue
        diffs.append(mag_rate - num / den)
    if not diffs:
        return (float("nan"), float("nan"), float("nan"))
    diffs.sort()
    return (sum(diffs) / len(diffs), diffs[int(0.025 * len(diffs))],
            diffs[int(0.975 * len(diffs))])


# ---------------------------------------------------------------------------
# analysis over a candidate set
# ---------------------------------------------------------------------------
def assign_vol_buckets(cands):
    rvs = sorted(c["rv"] for c in cands if c["rv"] is not None)
    if len(rvs) < VOL_BINS:
        for c in cands:
            c["vb"] = 0
        return
    cuts = [rvs[int(len(rvs) * (i + 1) / VOL_BINS) - 1] for i in range(VOL_BINS - 1)]
    for c in cands:
        if c["rv"] is None:
            c["vb"] = -1
            continue
        b = 0
        for cut in cuts:
            if c["rv"] > cut:
                b += 1
        c["vb"] = b


def analyze(cands, label, rng):
    assign_vol_buckets(cands)
    mags_all = [c for c in cands if c["is_magnet"] is True]
    placebos = [c for c in cands if c["is_magnet"] is None]
    mags = dedup_magnets(mags_all)
    n = len(mags)
    if n == 0:
        return {"label": label, "n": 0}
    mag_reach = sum(1 for m in mags if m["reached"]) / n

    # distance+side matched control
    key_ds = lambda c: (c["side"], c["dbin"])
    ctrl_ds, np_ds, _ = matched_control_rate(mags, placebos, key_ds)
    # distance+side+vol matched control
    key_dsv = lambda c: (c["side"], c["dbin"], c["vb"])
    ctrl_dsv, np_dsv, _ = matched_control_rate(mags, placebos, key_dsv)

    # significance: magnet reaches vs matched control reaches.
    # Represent control as a proportion over its effective placebo pool count.
    plac_reached = sum(1 for p in placebos if p["reached"])
    # for z-test use magnet count vs matched-control equivalent: build a
    # pseudo-count from the matched rate over the placebo pool actually used.
    _, _, _, p_ds = two_prop_z(int(mag_reach * n), n,
                               int(round(ctrl_ds * len(placebos))), len(placebos)) \
        if placebos else (0, 0, 0, float("nan"))
    md, lo, hi = block_bootstrap_diff(mags, placebos, key_ds, rng=rng)
    mdv, lov, hiv = block_bootstrap_diff(mags, placebos, key_dsv, rng=rng)

    per_sym = {}
    for s in SYMBOLS:
        ms = [m for m in mags if m["symbol"] == s]
        ps = [p for p in placebos if p["symbol"] == s]
        if ms:
            r = sum(1 for m in ms if m["reached"]) / len(ms)
            cr, _, _ = matched_control_rate(ms, ps, key_ds)
            per_sym[s] = {"n": len(ms), "mag": r, "ctrl": cr}

    return {
        "label": label, "n": n, "n_raw_magnet_obs": len(mags_all),
        "mag_reach": mag_reach,
        "ctrl_ds": ctrl_ds, "np_ds": np_ds,
        "ctrl_dsv": ctrl_dsv, "np_dsv": np_dsv,
        "diff_ds": mag_reach - ctrl_ds if ctrl_ds == ctrl_ds else float("nan"),
        "diff_dsv": mag_reach - ctrl_dsv if ctrl_dsv == ctrl_dsv else float("nan"),
        "boot_ds": (md, lo, hi), "boot_dsv": (mdv, lov, hiv),
        "p_ds": p_ds,
        "per_sym": per_sym,
        "n_placebo": len(placebos),
    }


def shuffle_prices(liqs, rng):
    """Negative control: shuffle liq PRICES within symbol, keep timestamps."""
    out = {}
    for s, evs in liqs.items():
        prices = [e["price"] for e in evs]
        rng.shuffle(prices)
        out[s] = [{"ts": e["ts"], "side": e["side"], "price": prices[i]}
                  for i, e in enumerate(evs)]
        out[s].sort(key=lambda r: r["ts"])
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_all(liqs, candle_map, k_min):
    cands = []
    for s in SYMBOLS:
        cands += enumerate_candidates(s, liqs.get(s, []), candle_map[s], k_min)
    return cands


def fmt(x, nd=3):
    return "nan" if x != x else f"{x:.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-net", action="store_true")
    args = ap.parse_args()
    rng = random.Random(SEED)

    liqs = load_liqs()
    tmin = min(e["ts"] for s in SYMBOLS for e in liqs.get(s, []))
    tmax = max(e["ts"] for s in SYMBOLS for e in liqs.get(s, []))
    candle_map = {}
    for s in SYMBOLS:
        candle_map[s] = get_candles(s, tmin, tmax, args.no_net)
    print(f"# liq span: {datetime.utcfromtimestamp(tmin)} .. "
          f"{datetime.utcfromtimestamp(tmax)} "
          f"({(tmax-tmin)/86400:.2f}d)")
    for s in SYMBOLS:
        print(f"#  {s}: {len(liqs.get(s,[]))} liq events, "
              f"{len(candle_map[s])} 5m candles")

    # ---- main run (K_MIN) ----
    cands = build_all(liqs, candle_map, K_MIN)
    res = analyze([dict(c) for c in cands], f"MAIN K>={K_MIN}", rng)
    print("\n" + "=" * 70)
    print(f"MAIN  (K>={K_MIN}, W={W_HOURS}h, D=[{D_MIN*100:.2f},{D_MAX*100:.2f}]%, H={H_HOURS}h)")
    print("=" * 70)
    _print_res(res)

    # ---- K sweep ----
    print("\n--- K sensitivity sweep ---")
    for k in K_SWEEP:
        c2 = build_all(liqs, candle_map, k)
        r2 = analyze([dict(c) for c in c2], f"K>={k}", rng)
        if r2["n"]:
            print(f"K>={k}: n={r2['n']:3d}  mag={fmt(r2['mag_reach'])}  "
                  f"ctrl_ds={fmt(r2['ctrl_ds'])}  diff={fmt(r2['diff_ds'])}  "
                  f"boot95=[{fmt(r2['boot_ds'][1])},{fmt(r2['boot_ds'][2])}]")
        else:
            print(f"K>={k}: n=0 (no magnets)")

    # ---- OOS chronological split ----
    print("\n--- OOS (chronological split at median anchor time) ---")
    ts_all = sorted(set(c["t"] for c in cands if c["is_magnet"] is True))
    if ts_all:
        tmid = ts_all[len(ts_all) // 2]
        train = [dict(c) for c in cands if c["t"] < tmid]
        test = [dict(c) for c in cands if c["t"] >= tmid]
        rtr = analyze(train, "TRAIN", rng)
        rte = analyze(test, "TEST", rng)
        for r in (rtr, rte):
            if r["n"]:
                print(f"{r['label']:5s}: n={r['n']:3d}  mag={fmt(r['mag_reach'])}  "
                      f"ctrl_ds={fmt(r['ctrl_ds'])}  diff={fmt(r['diff_ds'])}  "
                      f"boot95=[{fmt(r['boot_ds'][1])},{fmt(r['boot_ds'][2])}]")
            else:
                print(f"{r['label']:5s}: n=0")

    # ---- negative control (shuffled prices) ----
    print("\n--- NEGATIVE CONTROL (liq prices shuffled within symbol) ---")
    neg_diffs = []
    for i in range(5):
        sh = shuffle_prices(liqs, rng)
        cn = build_all(sh, candle_map, K_MIN)
        rn = analyze([dict(c) for c in cn], f"shuf{i}", rng)
        if rn["n"]:
            neg_diffs.append(rn["diff_ds"])
            print(f"shuffle {i}: n={rn['n']:3d}  mag={fmt(rn['mag_reach'])}  "
                  f"ctrl_ds={fmt(rn['ctrl_ds'])}  diff={fmt(rn['diff_ds'])}")
        else:
            print(f"shuffle {i}: n=0")
    if neg_diffs:
        print(f"neg-control mean diff = {fmt(sum(neg_diffs)/len(neg_diffs))} "
              f"(want ~0)")

    # ---- verdict ----
    print("\n" + "=" * 70)
    _verdict(res)
    print("=" * 70)


def _print_res(r):
    if not r["n"]:
        print("  n=0 magnets -> UNDERPOWERED (no magnet episodes at all)")
        return
    print(f"  independent magnet episodes n = {r['n']}  "
          f"(raw magnet obs before dedup = {r['n_raw_magnet_obs']})")
    print(f"  placebo (control) candidates = {r['n_placebo']}")
    print(f"  reach-rate MAGNET            = {fmt(r['mag_reach'])}")
    print(f"  reach-rate CONTROL dist+side = {fmt(r['ctrl_ds'])}   "
          f"diff = {fmt(r['diff_ds'])}")
    md, lo, hi = r["boot_ds"]
    print(f"    bootstrap95 diff (dist+side) = {fmt(md)} [{fmt(lo)}, {fmt(hi)}]")
    print(f"  reach-rate CONTROL +vol      = {fmt(r['ctrl_dsv'])}   "
          f"diff = {fmt(r['diff_dsv'])}")
    mdv, lov, hiv = r["boot_dsv"]
    print(f"    bootstrap95 diff (+vol)      = {fmt(mdv)} [{fmt(lov)}, {fmt(hiv)}]")
    print(f"  two-prop z p (dist+side)     = {fmt(r['p_ds'], 4)}")
    print("  per-symbol (dist+side matched):")
    for s, d in r["per_sym"].items():
        print(f"    {s}: n={d['n']:3d}  mag={fmt(d['mag'])}  ctrl={fmt(d['ctrl'])}  "
              f"diff={fmt(d['mag']-d['ctrl'])}")


def _verdict(r):
    if not r["n"] or r["n"] < 30:
        print(f"VERDICT: UNDERPOWERED  (n={r.get('n',0)} independent magnet "
              f"episodes < 30). 5 days of feed cannot cleanly separate the "
              f"magnet effect from proximity. No p-value claim asserted.")
        return
    md, lo, hi = r["boot_ds"]
    if lo > 0 and r["p_ds"] < 0.05:
        print("VERDICT: candidate MAGNET-REAL on primary control -- CHECK OOS "
              "+ negative-control above before trusting.")
    else:
        print("VERDICT: NULL -- magnets are NOT reached more than distance+"
              "side-matched controls (bootstrap CI spans 0). Proximity "
              "illusion. eye --deep keeps path-context framing.")


if __name__ == "__main__":
    main()
