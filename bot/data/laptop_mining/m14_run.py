"""M14 -- re-entry after a runner exits. BUILD + GATES + READ in one file, to M14_AMENDMENT_1 exactly.

Spec highlights encoded (see the amendment for the full list):
  * Events: 24-bar-spaced both-sided entries (m28 grid), runner armed (+1R) then exited via TRAIL or
    CLOCK; eligibility = entry has >= 144 forward bars (watch 48 + re-entry hold 48 past a 48h exit).
  * Unit = CHAINS: keep-first dedupe of overlapping [t_x, t_x+96h] same-coin windows (either side).
    Raw events / chains / fills all reported.
  * Arms (ITT: no-fill = 0): A1 immediate re-entry at the FIRST WATCH-BAR OPEN (tradeable price);
    A2 hold-longer shadow = net(runner, 96h clock) - net(runner, 48h clock) on the ORIGINAL entry
    (identical legs for clock exits, mechanically 0 for trail exits - its n is the clock stratum);
    A3 true pullback, CLOCK exits only: price must first trade >= 0.5 x ATR_f ABOVE the exit-time
    trail level (favourable side), then touch it from above (long; mirrored for short), fill at the
    level, stop-first fill-bar rule, no same-bar arming.
  * Re-entry em/ATR re-resolved point-in-time at the FILL day (lagged conventions); new stop 1.65 x em_f,
    trail 1.0 x ATR_f, 48h; leg fees; side-correct carry from the fill bar.
  * Controls: K=8 martingale continuations + 1 nullreal ANCHORED AT t_x (pool strictly before t_x,
    >= 500 valid bars, E[step]=1 per event), 96 bars long; triggers + engine run IDENTICALLY on them;
    ITT control mean subtracted per chain. m28 arrays NOT reused.
  * Null gate first (3 cells on nullreal-ctrl must sit inside z<3); positive control: linearity
    (inject known R into null A1) + detection at 1.5 x A1's own MDE; MDE stated before the read.
  * Family = 3 ITT cells vs 0 at z >= 3.0; verdict floor fill >= 20% AND n_fills >= 1000 (else no
    verdict language). Vol-sensitivity line: post-t_x realized vol / control-pool vol. Pre-named first
    split: trail vs clock. HUGE-EFFECTS-ONLY SCREEN (MDE ~0.2 R expected) stated up front.
"""
import io
import json
import math
import os
import sqlite3

import numpy as np

import panel_snapshot
from m13_build import daily, em_pit, atr_pit, fund_series, rate_at, K_STOP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
FEE_HALF = 0.00045
SPACING = 24
WATCH = 48
HOLD = 48
CONT = WATCH + HOLD          # 96 bars past t_x
K_CTRL = 8
DISPL = 0.5                  # A3 re-arm displacement in ATR_f
Z_BAR = 3.0
rng = np.random.default_rng(20261017)


def run_runner(o, h, l, c, fill, sf, trail_w, lim, side, rates):
    """Scalar runner from an intrabar fill price. Bars are ABSOLUTE prices starting at the fill bar
    (index 0 = fill bar; its remaining range participates stop-first; no same-bar arming credit).
    Returns net fraction of fill notional (fees on legs + side-correct carry)."""
    sg = 1.0 if side > 0 else -1.0
    stop = fill * (1 - sg * sf)
    one_r = fill * (1 + sg * sf)
    banked = 0.0
    frac = 1.0
    armed = False
    best = fill
    trail = stop
    legs = []
    carry = 0.0
    x = min(lim, len(c)) - 1
    for j in range(min(lim, len(c))):
        hj, lj, cj = h[j], l[j], c[j]
        carry += sg * rates[j] * frac
        cur = trail if armed else stop
        if (sg > 0 and lj <= cur) or (sg < 0 and hj >= cur):
            ret = sg * (cur - fill) / fill
            legs.append((frac, ret))
            banked += frac * ret
            frac = 0.0
            x = j
            break
        if not armed and j > 0 and ((sg > 0 and hj >= one_r) or (sg < 0 and lj <= one_r)):
            legs.append((0.5, sg * sf))
            banked += 0.5 * sg * (one_r - fill) / fill
            frac = 0.5
            armed = True
            best = one_r
        if armed:
            best = max(best, hj) if sg > 0 else min(best, lj)
            cand = best - sg * trail_w * fill
            if (sg > 0 and cand > trail) or (sg < 0 and cand < trail):
                trail = cand
    if frac > 0:
        j = min(lim, len(c)) - 1
        ret = sg * (c[j] - fill) / fill
        legs.append((frac, ret))
        banked += frac * ret
        x = j
    fee = FEE_HALF * (1.0 + sum(fr * (1 + sg * r_) for fr, r_ in legs))
    return banked - fee - carry


def a3_fill(h, l, level, atr_abs, side):
    """A3 trigger on bars after t_x: first trade >= DISPL*ATR beyond the level (favourable side),
    then touch the level from that side within WATCH bars. Returns fill bar index or None."""
    sg = 1.0 if side > 0 else -1.0
    armed = False
    thresh = level + sg * DISPL * atr_abs
    for j in range(min(WATCH, len(h))):
        if not armed:
            if (sg > 0 and h[j] >= thresh) or (sg < 0 and l[j] <= thresh):
                armed = True
                # the arming bar may also touch back - conservative: no same-bar fill
                continue
        else:
            if (sg > 0 and l[j] <= level) or (sg < 0 and h[j] >= level):
                return j
    return None


def synth_cont(b, xi, k, nbars):
    """k martingale continuations of nbars anchored at bar xi (pool strictly before xi)."""
    prevc = b["c"][:-1]
    lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
    up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
    dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
    g = np.flatnonzero(np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn))
    g = g[g < xi - 1]
    if len(g) < 500:
        return None
    lrp = lr[g]
    norm = float(np.mean(np.exp(lrp)))
    draw = g[rng.integers(0, len(g), size=(k, nbars))]
    step = np.exp(lr[draw]) / norm
    p0 = b["c"][xi]
    C = p0 * np.cumprod(step, axis=1)
    prev = np.concatenate((np.full((k, 1), p0), C[:, :-1]), axis=1)
    H = np.maximum(prev, C) * (1.0 + np.maximum(up[draw], 0))
    L = np.minimum(prev, C) * (1.0 - np.maximum(dn[draw], 0))
    O = prev
    return O, H, L, C


def main():
    print("M14 (Amendment 1 spec). HUGE-EFFECTS-ONLY SCREEN: expected MDE ~0.2 R pooled.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("SNAPSHOT: %s" % panel_snapshot.describe(panel_snapshot.stamp(c)))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
              "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}
    BOUND = 20693

    raw_events = 0
    chains = []
    for coin in coins:
        rows = c.execute("SELECT t,o,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4]}
        day, uq, dh, dl, dc = daily(b)
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        dix = np.searchsorted(uq, day)
        em_h, atr_h = em_d[dix], atr_d[dix]
        n = len(b["c"])
        fr = fund_series(c, coin)
        t_s = np.where(b["t"] > 1e12, b["t"] / 1000.0, b["t"])
        elig = np.flatnonzero(np.isfinite(em_h) & np.isfinite(atr_h) & (atr_h > 0))
        elig = elig[(dix[elig] >= 61) & (elig >= 520) & (elig < n - 145)]
        if len(elig) < 40:
            continue
        off = int(rng.integers(0, SPACING))
        ents, last = [], -10**9
        for e in elig:
            if e >= off and e - last >= SPACING:
                ents.append(e)
                last = e
        kept_windows = []
        for e in ents:
            for side in (1.0, -1.0):
                sf = K_STOP * em_h[e]
                sg = side
                entry = b["c"][e]
                stop = entry * (1 - sg * sf)
                one_r = entry * (1 + sg * sf)
                armed = False
                best = entry
                trail = stop
                x = None
                etype = None
                for j in range(e + 1, e + 1 + HOLD):
                    hj, lj = b["h"][j], b["l"][j]
                    cur = trail if armed else stop
                    if (sg > 0 and lj <= cur) or (sg < 0 and hj >= cur):
                        if armed:
                            x, etype, lvl = j, "trail", cur
                        break
                    if not armed and ((sg > 0 and hj >= one_r) or (sg < 0 and lj <= one_r)):
                        armed = True
                        best = one_r
                    if armed:
                        best = max(best, hj) if sg > 0 else min(best, lj)
                        cand = best - sg * atr_h[e] * entry
                        if (sg > 0 and cand > trail) or (sg < 0 and cand < trail):
                            trail = cand
                else:
                    if armed:
                        x, etype, lvl = e + HOLD, "clock", trail
                if x is None:
                    continue
                raw_events += 1
                # keep-first chain dedupe on [t_x, t_x+96h] same-coin windows (either side)
                ok = True
                for (w0, w1) in kept_windows:
                    if x < w1 and x + CONT > w0:
                        ok = False
                        break
                if not ok:
                    continue
                kept_windows.append((x, x + CONT))
                # --- arms on the REAL continuation ---
                fd = dix[x] if x < n else dix[-1]
                bars = slice(x + 1, x + 1 + CONT)
                O, H, L, Cc = b["o"][bars], b["h"][bars], b["l"][bars], b["c"][bars]
                rates = rate_at(fr, t_s[x + 1:x + 1 + CONT][None, :])[0] if len(fr) else np.zeros(CONT)
                ev = {"coin": coin, "side": side, "etype": etype, "t_x": float(t_s[x]),
                      "daykey": int(uq[dix[x]]), "disc": (coin in ORIG17) or (int(uq[dix[x]]) < BOUND)}

                def arms_on(O_, H_, L_, C_, em_f, atr_f):
                    out = {}
                    # A1: fill at first watch-bar open
                    if np.isfinite(em_f) and np.isfinite(atr_f) and atr_f > 0:
                        out["A1"] = run_runner(O_, H_, L_, C_, O_[0], K_STOP * em_f, atr_f,
                                               HOLD, side, rates) / (K_STOP * em_f)
                    else:
                        out["A1"] = 0.0
                    # A3: clock exits only
                    out["A3"] = 0.0
                    if etype == "clock" and np.isfinite(atr_f) and atr_f > 0:
                        fj = a3_fill(H_, L_, lvl, atr_h[e] * entry, side)
                        if fj is not None and np.isfinite(em_f):
                            sub = slice(fj, min(fj + HOLD, len(C_)))
                            out["A3"] = run_runner(O_[sub], H_[sub], L_[sub], C_[sub], lvl,
                                                   K_STOP * em_f, atr_f, HOLD, side,
                                                   rates[sub]) / (K_STOP * em_f)
                            out["A3_fill"] = 1
                    # A2: extend the original runner's remaining half to 96h (clock exits only move)
                    out["A2"] = 0.0
                    if etype == "clock":
                        sg2 = side
                        bst, trl = best, trail
                        fr2 = 0.5
                        carry2 = 0.0
                        ret2 = None
                        for j2 in range(min(HOLD, len(C_))):
                            carry2 += sg2 * rates[j2] * fr2
                            if (sg2 > 0 and L_[j2] <= trl) or (sg2 < 0 and H_[j2] >= trl):
                                ret2 = sg2 * (trl - entry) / entry
                                break
                            bst = max(bst, H_[j2]) if sg2 > 0 else min(bst, L_[j2])
                            cand = bst - sg2 * atr_h[e] * entry
                            if (sg2 > 0 and cand > trl) or (sg2 < 0 and cand < trl):
                                trl = cand
                            jlast = j2
                        if ret2 is None:
                            ret2 = sg2 * (C_[min(HOLD, len(C_)) - 1] - entry) / entry
                        base_ret = sg2 * (lvl - entry) / entry   # what the 48h clock close took
                        out["A2"] = (0.5 * (ret2 - base_ret) - carry2) / sf
                    return out

                em_f, atr_f = em_h[min(x + 1, n - 1)], atr_h[min(x + 1, n - 1)]
                ev["real"] = arms_on(O, H, L, Cc, em_f, atr_f)
                sp = synth_cont(b, x, K_CTRL + 1, CONT)
                if sp is None:
                    kept_windows.pop()
                    continue
                ctr = {k_: [] for k_ in ("A1", "A2", "A3")}
                for ki in range(K_CTRL):
                    r_ = arms_on(sp[0][ki], sp[1][ki], sp[2][ki], sp[3][ki], em_f, atr_f)
                    for k_ in ctr:
                        ctr[k_].append(r_[k_])
                ev["ctrl"] = {k_: float(np.mean(v)) for k_, v in ctr.items()}
                nr = arms_on(sp[0][K_CTRL], sp[1][K_CTRL], sp[2][K_CTRL], sp[3][K_CTRL], em_f, atr_f)
                ev["null"] = {k_: nr[k_] for k_ in ("A1", "A2", "A3")}
                # vol sensitivity: realized next-48h vol vs pool vol
                rl = np.diff(np.log(np.maximum(Cc[:HOLD], 1e-12)))
                ev["vol_ratio"] = float(np.std(rl) / max(1e-9, np.std(np.diff(np.log(
                    np.maximum(b["c"][max(0, x - 500):x], 1e-12))))))
                chains.append(ev)
    c.close()
    if len(chains) < 300:
        raise SystemExit("HALT: only %d chains built." % len(chains))
    print("raw events %d -> kept chains %d (overlap dropped %.0f%%)"
          % (raw_events, len(chains), 100 * (1 - len(chains) / max(1, raw_events))))
    etypes = [e["etype"] for e in chains]
    print("exit types: trail %d / clock %d" % (etypes.count("trail"), etypes.count("clock")))

    # ---- gates + read ----
    coins_u = sorted(set(e["coin"] for e in chains))
    cidx = {k_: i for i, k_ in enumerate(coins_u)}
    carr = np.array([cidx[e["coin"]] for e in chains])
    week = np.array([e["daykey"] // 7 for e in chains])

    def cell(vals, idx=None):
        v = np.asarray(vals, float)
        ca = carr if idx is None else carr[idx]
        cm = np.zeros(len(coins_u))
        cc = np.zeros(len(coins_u))
        np.add.at(cm, ca, v)
        np.add.at(cc, ca, 1)
        has = cc > 0
        per = cm[has] / cc[has]
        boots = []
        for _ in range(3000):
            boots.append(per[rng.integers(0, len(per), len(per))].mean())
        lo, hi = np.percentile(boots, [2.5, 97.5])
        # chain-level
        b2 = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(3000)]
        lo2, hi2 = np.percentile(b2, [2.5, 97.5])
        lo, hi = (lo, hi) if (hi - lo) >= (hi2 - lo2) else (lo2, hi2)
        se = (hi - lo) / 3.92
        return {"mean": float(v.mean()), "eqw_coin": float(per.mean()), "lo": float(lo),
                "hi": float(hi), "se": float(se), "z": float(v.mean() / se if se > 0 else 0), "n": len(v)}

    def read(key):
        out = {}
        for arm in ("A1", "A2", "A3"):
            out[arm] = cell([e[key][arm] - e["ctrl"][arm] for e in chains])
        return out

    print("=== NULL GATE (nullreal - ctrl, 3 cells) ===")
    ng = read("null")
    for arm, r_ in ng.items():
        print("  [NULL %s] %+0.4f R [%+0.4f,%+0.4f] z %+0.2f n=%d" % (arm, r_["mean"], r_["lo"], r_["hi"], r_["z"], r_["n"]))
    if max(abs(r_["z"]) for r_ in ng.values()) >= Z_BAR:
        raise SystemExit("HALT: NULL GATE FAILED.")
    mde = {arm: 2.8 * r_["se"] for arm, r_ in ng.items()}
    print("NULL GATE PASSED. per-arm MDE (2.8 x SE):", {k_: round(v, 3) for k_, v in mde.items()})

    print("=== POSITIVE CONTROL (A1: linearity + detection at 1.5 x own MDE) ===")
    base = ng["A1"]["mean"]
    okpc = True
    for shift in (0.10, 1.5 * mde["A1"]):
        v = [e["null"]["A1"] - e["ctrl"]["A1"] + shift for e in chains]
        r_ = cell(v)
        rec = r_["mean"] - base
        lin = abs(rec - shift) <= 0.1 * shift + 1e-9
        det = abs(r_["z"]) >= 2.8 if shift >= 1.5 * mde["A1"] - 1e-9 else True
        print("  inject %.3f R -> recovered %.4f (lin %s, z %+0.2f det %s)" % (shift, rec, lin, r_["z"], det))
        okpc &= lin and det
    if not okpc:
        raise SystemExit("HALT: POSITIVE CONTROL FAILED.")
    print("POSITIVE CONTROL PASSED.")

    print("=== THE READ (3 ITT cells vs 0; family z >= %.1f; verdict floor fill>=20%% & n_fills>=1000) ===" % Z_BAR)
    rr = read("real")
    fills_a3 = sum(1 for e in chains if e["real"].get("A3_fill"))
    n_clock = etypes.count("clock")
    for arm, r_ in rr.items():
        extra = ""
        if arm == "A3":
            extra = "  fill rate %.0f%% of clock events (n_fills=%d)" % (100 * fills_a3 / max(1, n_clock), fills_a3)
        if arm == "A2":
            extra = "  (n effective = clock stratum %d; mechanically 0 on trail exits)" % n_clock
        print("  [%s] ITT %+0.4f R [%+0.4f,%+0.4f] eqwC %+0.4f z %+0.2f n=%d%s"
              % (arm, r_["mean"], r_["lo"], r_["hi"], r_["eqw_coin"], r_["z"], r_["n"], extra))
    vr = np.median([e["vol_ratio"] for e in chains])
    print("vol-sensitivity: median post-t_x realized vol / pool vol = %.2f (>1 means the control underprices)" % vr)
    for nm in ("trail", "clock"):
        idx = np.flatnonzero(np.array(etypes) == nm)
        if len(idx) > 50:
            v = [chains[i]["real"]["A1"] - chains[i]["ctrl"]["A1"] for i in idx]
            r_ = cell(v, idx)
            print("  split A1 by exit=%s: %+0.4f R [%+0.4f,%+0.4f] n=%d" % (nm, r_["mean"], r_["lo"], r_["hi"], r_["n"]))
    io.open(os.path.join(HERE, "m14_result.json"), "w", encoding="utf-8").write(json.dumps(
        {"chains": len(chains), "raw_events": raw_events, "null": ng, "mde": mde, "read": rr,
         "vol_ratio_median": vr, "a3_fillrate_clock": fills_a3 / max(1, n_clock)}, indent=1, default=float))
    print("wrote m14_result.json")


if __name__ == "__main__":
    main()
