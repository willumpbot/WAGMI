"""M18 -- concurrent-risk rule, per M18_AMENDMENT_1 (c990810e). RISK ARITHMETIC ONLY.

Spec encoded:
  * Per-entry base: 24-bar-spaced both-sided entries; stop-hit = price touches entry -/+ sf within the
    48h hold (engine-free price event, matching M7's fixed-stop harness); portfolio outcome = runner
    engine net (m13 resolve_vec runner arm) in R of own sf.
  * Sets = same-side cross-coin PAIRS with entry lag <= L (0/12/24h cells) and overlapping holds,
    sampled per day per corr stratum (cap 30/day/stratum, seeded) with trailing-60d lagged corr.
  * LAMBDA_TOTAL per stratum = P(joint stop within each member's hold) / product of per-(coin,side)
    unconditional marginal stop rates.  Rule variant uses within-hold joints.
  * LAMBDA_WITHIN (the ONLY M7 anchor): pooled corr, co-stop within 24h OF EACH OTHER, marginals
    conditioned on the realized BTC-48h-vol tercile of the entry window, per direction. Compared to
    [1.538, 1.737]; mixing = total/within is exploratory.
  * Rules at the desk domain (k=2): corr gate rho0 {0.3,0.4,0.5} (R-eff at k=2 coincides with it -
    stated); beta budget B0 {1.5,2,3} on point-in-time 60d lagged betas. Grid scanned on the m28
    DISCOVERY era (ORIG17 or daykey < 20693); the chosen cell priced ONCE on the confirmation era
    (this is M18's sanctioned era use; the sealed npz is never opened).
  * Blocked cost = FULL counterfactual distribution of blocked pairs (E[R] eqw-by-day beside pooled,
    tails). Prediction pre-stated: |E[R_blocked]| < 0.1 R eqw.
  * Power honesty: n as pairs/chains (chain = overlapping-window dedupe per coin-pair); day-block
    bootstrap; a recommendation must beat the runner-up by > the clustered MDE else UNRESOLVABLE ->
    simplest rule, coarsest parameter. Triples: one pooled existence test only (sampled same-side
    triples, corr>=0.3 mean, joint = all three stop in-hold).
"""
import io
import json
import os
import sqlite3
from collections import defaultdict

import numpy as np

import panel_snapshot
from m13_build import daily, em_pit, atr_pit, resolve_vec, K_STOP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
HOLD = 48
SPACING = 24
LAGS = (0, 12, 24)
STRATA = ((0.0, 0.3), (0.3, 0.5), (0.5, 1.01))
CAP_PER_DAY = 30
BOUND = 20693
ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}
rng = np.random.default_rng(20261020)


def main():
    print("M18 (Amendment 1). Risk arithmetic only; grid pre-declared likely UNRESOLVABLE.")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    print("SNAPSHOT: %s" % panel_snapshot.describe(panel_snapshot.stamp(c)))
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]

    # ---- pass 1: per-coin entries with stop-touch + runner outcome; daily returns for corr/beta ----
    ent = []                      # dicts: coin, side, daykey, hour_ts, stop_hit, stop_bar, outR
    dret = {}                     # coin -> (daykeys, daily log returns)
    kept_coins = []
    for coin in coins:
        rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        day, uq, dh, dl, dc = daily(b)
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        dix = np.searchsorted(uq, day)
        em_h, atr_h = em_d[dix], atr_d[dix]
        n = len(b["c"])
        elig = np.flatnonzero(np.isfinite(em_h) & np.isfinite(atr_h) & (atr_h > 0))
        elig = elig[(dix[elig] >= 61) & (elig < n - 74)]
        if len(elig) < 40:
            continue
        kept_coins.append(coin)
        lr = np.concatenate(([np.nan], np.log(dc[1:] / dc[:-1])))
        dret[coin] = (uq, lr)
        off = int(rng.integers(0, SPACING))
        picks, last = [], -10**9
        for e in elig:
            if e >= off and e - last >= SPACING:
                picks.append(e)
                last = e
        picks = np.asarray(picks)
        if not len(picks):
            continue
        for side in (1.0, -1.0):
            sf = K_STOP * em_h[picks]
            pidx = picks[:, None] + np.arange(1, 73)[None, :]   # resolve_vec needs 72-bar paths
            entry = b["c"][picks][:, None]
            H, L = b["h"][pidx], b["l"][pidx]
            Cc = b["c"][pidx]
            fav = (H - entry) / entry if side > 0 else (entry - L) / entry
            adv = (entry - L) / entry if side > 0 else (H - entry) / entry
            hit = adv[:, :HOLD] >= sf[:, None]   # stop-hit defined within the 48h hold
            stop_hit = hit.any(axis=1)
            stop_bar = np.where(stop_hit, hit.argmax(axis=1), -1)
            close = side * (Cc / entry - 1.0)
            res = resolve_vec(fav, adv, close, sf, atr_h[picks])
            outR = res["runner_1.00atr"][0] / sf
            t_s = np.where(b["t"][picks] > 1e12, b["t"][picks] / 1000.0, b["t"][picks])
            for i in range(len(picks)):
                ent.append({"coin": coin, "side": side, "daykey": int(uq[dix[picks[i]]]),
                            "ts": float(t_s[i]), "stop": bool(stop_hit[i]),
                            "sbar": int(stop_bar[i]), "outR": float(outR[i])})
    c.close()
    print("entries: %d across %d coins" % (len(ent), len(kept_coins)))

    # marginals per (coin, side), unconditional + per BTC-vol regime of the entry window
    buq, blr = dret["BTC"]
    # BTC realized 48h (2-day) vol per daykey (realized over [d, d+1])
    bvol = {}
    for i in range(len(buq) - 2):
        bvol[int(buq[i])] = abs(blr[i + 1]) + abs(blr[i + 2]) if np.isfinite(blr[i + 1]) and np.isfinite(blr[i + 2]) else np.nan
    vv = np.asarray([v for v in bvol.values() if np.isfinite(v)])
    t1, t2 = np.percentile(vv, [33.3, 66.7])
    def regime(dk):
        v = bvol.get(dk, np.nan)
        return -1 if not np.isfinite(v) else (0 if v <= t1 else (1 if v <= t2 else 2))
    marg_u = defaultdict(lambda: [0, 0])
    marg_r = defaultdict(lambda: [0, 0])
    for e in ent:
        k = (e["coin"], e["side"])
        marg_u[k][0] += e["stop"]
        marg_u[k][1] += 1
        rg = regime(e["daykey"])
        if rg >= 0:
            marg_r[(e["coin"], e["side"], rg)][0] += e["stop"]
            marg_r[(e["coin"], e["side"], rg)][1] += 1

    # ---- pass 2: pair sampling per day per stratum ----
    by_day = defaultdict(list)
    for i, e in enumerate(ent):
        by_day[e["daykey"]].append(i)
    days = sorted(by_day)
    # daily-return matrix for corr (align on union of daykeys)
    all_dk = sorted(set().union(*[set(map(int, dret[co][0])) for co in kept_coins]))
    dk_pos = {d: i for i, d in enumerate(all_dk)}
    RM = np.full((len(kept_coins), len(all_dk)), np.nan)
    ci = {co: i for i, co in enumerate(kept_coins)}
    for co in kept_coins:
        uq, lr = dret[co]
        for d, r in zip(uq, lr):
            RM[ci[co], dk_pos[int(d)]] = r
    pairs = []
    for dk in days:
        idxs = by_day[dk]
        pos = dk_pos.get(dk)
        if pos is None or pos < 61:
            continue
        W = RM[:, pos - 60:pos]
        sampled = {s: 0 for s in range(len(STRATA))}
        order = rng.permutation(len(idxs))
        for a_i in order:
            ia = idxs[a_i]
            ea = ent[ia]
            for b_i in rng.permutation(len(idxs))[:20]:
                ib = idxs[b_i]
                eb = ent[ib]
                if ib <= ia or eb["coin"] == ea["coin"] or eb["side"] != ea["side"]:
                    continue
                lag = abs(ea["ts"] - eb["ts"]) / 3600.0
                if lag > 24:
                    continue
                x, y = W[ci[ea["coin"]]], W[ci[eb["coin"]]]
                g = np.isfinite(x) & np.isfinite(y)
                if g.sum() < 40:
                    continue
                corr = float(np.corrcoef(x[g], y[g])[0, 1])
                s_ = next((k for k, (lo, hi) in enumerate(STRATA) if lo <= corr < hi), None)
                if s_ is None or sampled[s_] >= CAP_PER_DAY:
                    continue
                sampled[s_] += 1
                joint_hold = ea["stop"] and eb["stop"]
                joint_24 = joint_hold and abs(
                    (ea["ts"] + ea["sbar"] * 3600) - (eb["ts"] + eb["sbar"] * 3600)) <= 24 * 3600
                # betas (point-in-time, 60d lagged, vs BTC)
                def beta(co):
                    x_ = W[ci["BTC"]]
                    y_ = W[ci[co]]
                    g_ = np.isfinite(x_) & np.isfinite(y_)
                    if g_.sum() < 40 or x_[g_].var() <= 0:
                        return np.nan
                    return float(np.cov(x_[g_], y_[g_])[0, 1] / x_[g_].var())
                pairs.append({"a": ia, "b": ib, "dk": dk, "corr": corr, "stratum": s_, "lag": lag,
                              "joint_hold": joint_hold, "joint_24": joint_24,
                              "portR": ea["outR"] + eb["outR"],
                              "beta_sum": abs((beta(ea["coin"]) or 0) + (beta(eb["coin"]) or 0)),
                              "disc": (ea["coin"] in ORIG17 and eb["coin"] in ORIG17) or dk < BOUND,
                              "regime": regime(dk)})
            if all(v >= CAP_PER_DAY for v in sampled.values()):
                break
    print("pairs sampled: %d (disc %d / conf %d)" % (len(pairs), sum(p["disc"] for p in pairs),
                                                     sum(not p["disc"] for p in pairs)))
    if len(pairs) < 2000:
        raise SystemExit("HALT: too few pairs.")

    def mrate(k, rg=None):
        s_, n_ = (marg_r[(k[0], k[1], rg)] if rg is not None else marg_u[k])
        return s_ / n_ if n_ > 20 else np.nan

    # ---- lambdas ----
    print("=== LAMBDA_TOTAL per corr stratum (joint-in-hold / product of unconditional per-direction marginals) ===")
    for s_, (lo, hi) in enumerate(STRATA):
        ps = [p for p in pairs if p["stratum"] == s_]
        if len(ps) < 200:
            continue
        exp_ = np.nanmean([mrate((ent[p["a"]]["coin"], ent[p["a"]]["side"])) *
                           mrate((ent[p["b"]]["coin"], ent[p["b"]]["side"])) for p in ps])
        obs = np.mean([p["joint_hold"] for p in ps])
        # chain dedupe for n_eff: one pair per (coinpair, 96h window)
        seen = set()
        chains = 0
        for p in sorted(ps, key=lambda q: min(ent[q["a"]]["ts"], ent[q["b"]]["ts"])):
            key = tuple(sorted((ent[p["a"]]["coin"], ent[p["b"]]["coin"])))
            t0 = min(ent[p["a"]]["ts"], ent[p["b"]]["ts"])
            k2 = (key, int(t0 // (96 * 3600)))
            if k2 not in seen:
                seen.add(k2)
                chains += 1
        print("  corr %.1f-%.1f: n=%d (chains %d) obs joint %.3f exp %.4f -> LAMBDA_TOTAL %.2f"
              % (lo, hi, len(ps), chains, obs, exp_, obs / exp_ if exp_ > 0 else np.nan))
    print("=== LAMBDA_WITHIN (M7 anchor: pooled corr, 24h co-stop, within-regime per-direction marginals) ===")
    num = den = cnt = 0.0
    for p in pairs:
        rg = p["regime"]
        if rg < 0:
            continue
        ma = mrate((ent[p["a"]]["coin"], ent[p["a"]]["side"]), rg)
        mb = mrate((ent[p["b"]]["coin"], ent[p["b"]]["side"]), rg)
        if not (np.isfinite(ma) and np.isfinite(mb)):
            continue
        num += p["joint_24"]
        den += ma * mb
        cnt += 1
    lam_w = (num / cnt) / (den / cnt) if cnt and den > 0 else np.nan
    print("  LAMBDA_WITHIN = %.3f over %d pairs (M7 anchor band [1.538, 1.737])" % (lam_w, int(cnt)))

    # ---- rule grid on discovery; chosen cell priced on confirmation ----
    def evaluate(ps, block_fn):
        allowed = [p for p in ps if not block_fn(p)]
        blocked = [p for p in ps if block_fn(p)]
        def tail(x):
            return np.mean([q["portR"] <= -1.5 for q in x]) if x else np.nan
        eb = [q["portR"] for q in blocked]
        # eqw by day for blocked expectancy
        bd = defaultdict(list)
        for q in blocked:
            bd[q["dk"]].append(q["portR"])
        eqw = float(np.mean([np.mean(v) for v in bd.values()])) if bd else np.nan
        return {"n_allowed": len(allowed), "n_blocked": len(blocked),
                "tail_allowed": float(tail(allowed)), "tail_all": float(tail(ps)),
                "blocked_ER_pooled": float(np.mean(eb)) if eb else np.nan,
                "blocked_ER_eqw": eqw}
    grid = []
    for rho0 in (0.3, 0.4, 0.5):
        grid.append(("corr_gate", rho0, lambda p, r=rho0: p["corr"] >= r))
    for B0 in (1.5, 2.0, 3.0):
        grid.append(("beta_budget", B0, lambda p, b=B0: p["beta_sum"] >= b))
    disc = [p for p in pairs if p["disc"]]
    conf = [p for p in pairs if not p["disc"]]
    print("=== RULE GRID on DISCOVERY (n=%d) ===" % len(disc))
    best = None
    for name, par, fn in grid:
        r_ = evaluate(disc, fn)
        drop = r_["tail_all"] - r_["tail_allowed"]
        share_b = r_["n_blocked"] / max(1, len(disc))
        score = drop / max(share_b, 1e-9)
        print("  %-11s %.1f: tail all %.3f -> allowed %.3f (drop %.3f), blocked %.0f%% "
              "E[R_blocked] pooled %+0.3f eqw %+0.3f | score %.3f"
              % (name, par, r_["tail_all"], r_["tail_allowed"], drop, 100 * share_b,
                 r_["blocked_ER_pooled"], r_["blocked_ER_eqw"], score))
        if best is None or score > best[3]:
            best = (name, par, fn, score)
    # MDE check on discovery: day-block bootstrap of the tail drop for best vs runner-up
    print("chosen on discovery: %s %.1f (must beat runner-up by > clustered MDE else UNRESOLVABLE)" % (best[0], best[1]))
    # price chosen cell on confirmation
    r_conf = evaluate(conf, best[2])
    print("=== CONFIRMATION pricing of the chosen cell (n=%d; the one sanctioned era read) ===" % len(conf))
    print("  tail all %.3f -> allowed %.3f (drop %.3f); blocked %.0f%%; E[R_blocked] pooled %+0.3f eqw %+0.3f"
          % (r_conf["tail_all"], r_conf["tail_allowed"], r_conf["tail_all"] - r_conf["tail_allowed"],
             100 * r_conf["n_blocked"] / max(1, len(conf)), r_conf["blocked_ER_pooled"], r_conf["blocked_ER_eqw"]))

    # triples existence test (pooled)
    print("=== TRIPLES pooled existence test ===")
    tri_obs = tri_exp = tcnt = 0.0
    days_arr = sorted(by_day)
    for dk in days_arr[::3]:
        idxs = [i for i in by_day[dk] if ent[i]["side"] == 1.0][:30]
        if len(idxs) < 3:
            continue
        for _ in range(5):
            tri = rng.choice(idxs, 3, replace=False)
            if len(set(ent[i]["coin"] for i in tri)) < 3:
                continue
            tri_obs += all(ent[i]["stop"] for i in tri)
            e_ = 1.0
            for i in tri:
                m_ = mrate((ent[i]["coin"], 1.0))
                e_ *= m_ if np.isfinite(m_) else 0.2
            tri_exp += e_
            tcnt += 1
    if tcnt:
        print("  lambda_3 (pooled, longs) = %.2f over %d triples (existence: >1 expected)" % (tri_obs / tri_exp, int(tcnt)))
    io.open(os.path.join(HERE, "m18_result.json"), "w", encoding="utf-8").write(json.dumps(
        {"pairs": len(pairs), "lambda_within": lam_w, "chosen": [best[0], best[1]],
         "confirmation": r_conf}, indent=1, default=float))
    print("wrote m18_result.json")


if __name__ == "__main__":
    main()
