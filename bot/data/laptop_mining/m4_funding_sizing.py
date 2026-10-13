"""M4 -- funding_hot sizing on an ECONOMIC objective. Sealed 1a00b1cf, amended 7c699867.

THE QUESTION (mission M4): on funding_hot days, does widening the stop, sizing down, or both actually
PAY? KSTAR_RECOMPUTE found K* ~= 1.770 makes a funding_hot day's stop-hit rate MATCH the unflagged
baseline -- but exceedance parity is a statistical target, not a reason to act. A wider stop is hit
less often AND loses more when hit. This measures the economics.

WHAT THE AMENDMENT CHANGED, and why it matters for reading the output (PREREG A1):
  * Expectancy was sealed as "bps of notional". notional = risk / stop, so in bps of notional the
    risk CANCELS -- P2 (size-down) would have been identically zero against P0 in every sample. An
    arm that is zero by construction is the same defect as one positive by construction.
  * Drawdown was sealed as "per unit risk, in R". R *is* the stop, so widening it makes the same
    price excursion a smaller number of R. The sealed tie-break "better drawdown wins" would have
    handed the verdict to P1 for geometry alone.
  * BOTH outcomes are therefore measured in % OF EQUITY here -- the one denominator no policy
    appears in.
  * P2 = P0 x 0.9322 EXACTLY on expectancy, and identical on drawdown-per-unit-risk. That is
    arithmetic, not an estimate: it gets no CI and no verdict.
  * The ONE estimated contrast is P1 - P2: equal notional (0.9322 x baseline), differing ONLY in
    where the stop sits. One contrast, so the threshold is |z| > 1.96.

POLICIES (all applied only on funding_hot coin-days; identical off them, so entries are restricted
there -- a power gain, not a filter on the outcome):
    P0 baseline   stop 1.65  x em, risk 0.500%
    P1 widen      stop 1.770 x em, risk 0.500%     -> notional x 0.9322
    P2 size-down  stop 1.65  x em, risk 0.4661%    -> notional x 0.9322  (MATCHED to P1)
    P3 both       stop 1.770 x em, risk 0.4661%
  target 3.30 x em for EVERY policy (2x the BASELINE stop), held constant on purpose so a policy
  moves the stop and nothing else; horizon 72h; same-bar stop/target ambiguity counted as the STOP.

CONTROL: the M1 v3 martingale bootstrap (a coin's own bar shapes, multiplicative steps normalised to
E[step] == 1), SUBTRACTED. Two stop geometries do not give equal expectancy under no edge -- M1's
three control versions established exactly that, and the raw difference would measure geometry.

SPLIT: DISCOVERY = ORIG17. HELD-OUT = NEW156, labelled "near-clean, not clean" -- KSTAR_RECOMPUTE
touched those coins with the SAME flag and the SAME stop-width lever. Declared, every time.
"""
import collections
import csv
import datetime
import glob
import io
import json
import math
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
HIST = os.path.join(HERE, "history")     # VOID RUN 1: I wrote "hist". 178 funding files, 0 found.
EPS = 1e-8
HORIZON = 72
FEE_FRAC = 0.0009                 # 9 bps round-trip taker, the ground-rule unit
K0, K1 = 1.65, 1.770              # baseline stop, K* from KSTAR_RECOMPUTE (fixed, not searched)
RISK0 = 0.005                     # the live 0.5% cap
SHRINK = K0 / K1                  # 0.93220 -- the matched notional reduction
TGT_MULT = 2.0 * K0               # 3.30 x em, policy-independent
ENTRIES_PER_COIN = 400
BOOT = 4000
Z_THR = 1.96                      # one estimated contrast (PREREG A1c)
rng = np.random.default_rng(20261013)

ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]   # live coefficients, unrefitted: out-of-sample by design

POLICIES = (("P0_baseline", K0, RISK0),
            ("P1_widen", K1, RISK0),
            ("P2_sizedown", K0, RISK0 * SHRINK),
            ("P3_both", K1, RISK0 * SHRINK))


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def load_bars(c, coin):
    rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
    if len(rows) < 500:
        return None
    a = np.asarray(rows, float)
    return {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


def daily_em(b):
    """Fitted-HAR exp_move per UTC day (percent), mapped onto each 1h bar. Verbatim from M1/M9."""
    day = (b["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    close = np.array([b["c"][i] for i in np.append(first[1:], len(b["c"])) - 1])
    if len(close) < 40:
        return None, None
    rets = np.concatenate(([0.0], (close[1:] / close[:-1] - 1.0) * 100.0))
    em = np.full(len(uniq), np.nan)
    for i in range(30, len(uniq)):
        rv1, rv5, rv22 = abs(rets[i]), sd(list(rets[i - 4:i + 1])), sd(list(rets[i - 21:i + 1]))
        if rv5 <= 0 or rv22 <= 0:
            continue
        z = (Y1B[0] + Y1B[1] * math.log(rv1 + EPS) + Y1B[2] * math.log(rv5 + EPS)
             + Y1B[3] * math.log(rv22 + EPS))
        v = math.exp(z) * Y1S
        if v > 0:
            em[i] = v
    return em[np.searchsorted(uniq, day)], day


def load_funding_daily(sym):
    """Mean funding rate per UTC date -- the same daily reduction size_flags_wide.load_funding uses."""
    p = os.path.join(HIST, "%s_funding.csv" % sym)
    if not os.path.exists(p):
        return {}
    byday = collections.defaultdict(list)
    with io.open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                t = int(r["t_ms"]) // 1000
                byday[int(t // 86400)].append(float(r["rate"]))
            except (TypeError, ValueError):
                continue
    return {d: float(np.mean(v)) for d, v in byday.items() if v}


def hot_days(fund_by_coin):
    """funding_hot = top funding quintile PER DATE across the population (size_flags_wide.flag_rank).

    `>=` the 80th percentile, matching the replicated definition exactly. Funding is tie-heavy (the
    HL default 1.25e-05 was 18.2% of rows in reply 121), so `>=` fires on more than 20% of coin-days
    by design -- that is the definition that replicated and it is not re-litigated here.
    """
    bydate = collections.defaultdict(dict)
    for coin, dd in fund_by_coin.items():
        for d, r in dd.items():
            bydate[d][coin] = r
    hot = collections.defaultdict(set)
    fired = tot = 0
    for d, m in bydate.items():
        if len(m) < 5:
            continue
        vals = np.asarray(list(m.values()), float)
        thr = float(np.quantile(vals, 0.80))
        for coin, r in m.items():
            tot += 1
            if r >= thr:
                hot[coin].add(d)
                fired += 1
    return hot, (100.0 * fired / tot if tot else 0.0)


def outcomes(entry, side, H, L, C, em_frac, k, risk):
    """Return (pnl_% of equity, max adverse excursion % of equity) per entry for one policy."""
    stop_frac = k * em_frac
    tgt_frac = TGT_MULT * em_frac
    notional = risk / stop_frac                       # size = risk / stop. Fixed dollar risk.
    adv = np.where(side[:, None] > 0,
                   (entry[:, None] - L) / entry[:, None],
                   (H - entry[:, None]) / entry[:, None])
    fav = np.where(side[:, None] > 0,
                   (H - entry[:, None]) / entry[:, None],
                   (entry[:, None] - L) / entry[:, None])
    s_hit = adv >= stop_frac[:, None]
    t_hit = fav >= tgt_frac[:, None]
    sb = np.where(s_hit.any(axis=1), s_hit.argmax(axis=1), HORIZON)
    tb = np.where(t_hit.any(axis=1), t_hit.argmax(axis=1), HORIZON)
    # same bar => STOP (ordering inside a bar is unknowable; assuming the bad outcome is the only
    # honest default, and it is the convention M9 used)
    stopped = (sb < HORIZON) & (sb <= tb)
    tgted = (~stopped) & (tb < HORIZON)
    last = side * (C[:, -1] / entry - 1.0)
    ret = np.where(stopped, -stop_frac, np.where(tgted, tgt_frac, last))
    exit_bar = np.where(stopped, sb, np.where(tgted, tb, HORIZON - 1))
    mask = np.arange(HORIZON)[None, :] <= exit_bar[:, None]
    mae = np.nanmax(np.where(mask, adv, np.nan), axis=1)
    mae = np.maximum(mae, 0.0)
    return (notional * (ret - FEE_FRAC) * 100.0), (notional * mae * 100.0)


def run_coin(b, em_bar, dayv, hotset, synthetic=False):
    n = len(b["c"])
    valid = ~np.isnan(em_bar[:n - HORIZON - 1])
    isday = np.isin(dayv[:n - HORIZON - 1], list(hotset)) if hotset else np.zeros(n - HORIZON - 1, bool)
    ok = np.flatnonzero(valid & isday)
    ok = ok[ok > 30]
    if len(ok) < 50:
        return None
    take = min(ENTRIES_PER_COIN, len(ok))
    ent = rng.choice(ok, size=take, replace=False)
    side = np.where(rng.random(take) < 0.5, 1.0, -1.0)
    entry = b["c"][ent]
    if synthetic:
        # M1 v3 martingale control: bootstrap the coin's OWN bar shapes (proportional close move plus
        # high/low wick offsets), then normalise the multiplicative steps so E[step] == 1 exactly.
        # v2 demeaned LOG returns, which by Jensen leaves +sig^2/2 arithmetic drift per bar -- that
        # control read +66 bps on WIF where a no-edge control must sit at -(fee).
        prevc = b["c"][:-1]
        lr = np.log(np.maximum(b["c"][1:], 1e-12) / np.maximum(prevc, 1e-12))
        up = (b["h"][1:] - np.maximum(prevc, b["c"][1:])) / np.maximum(prevc, 1e-12)
        dn = (np.minimum(prevc, b["c"][1:]) - b["l"][1:]) / np.maximum(prevc, 1e-12)
        g = np.isfinite(lr) & np.isfinite(up) & np.isfinite(dn)
        lr, up, dn = lr[g], np.maximum(up[g], 0.0), np.maximum(dn[g], 0.0)
        if len(lr) < 100:
            return None
        draw = rng.integers(0, len(lr), size=(take, HORIZON))
        step = np.exp(lr[draw]) / float(np.mean(np.exp(lr)))
        C = entry[:, None] * np.cumprod(step, axis=1)
        prev = np.concatenate((entry[:, None], C[:, :-1]), axis=1)
        H = np.maximum(prev, C) * (1.0 + up[draw])
        L = np.minimum(prev, C) * (1.0 - dn[draw])
    else:
        pidx = ent[:, None] + np.arange(1, HORIZON + 1)[None, :]
        H, L, C = b["h"][pidx], b["l"][pidx], b["c"][pidx]
    em_frac = em_bar[ent] / 100.0
    out = {}
    for name, k, risk in POLICIES:
        pnl, dd = outcomes(entry, side, H, L, C, em_frac, k, risk)
        out[name] = {"pnl": pnl, "dd": dd}
    out["_n"] = take
    return out


def boot_ci(per_coin):
    """Block bootstrap over WHOLE COINS -- the clustering unit that governs."""
    a = np.asarray(per_coin, float)
    a = a[np.isfinite(a)]
    if len(a) < 3:
        return float("nan"), float("nan"), float("nan"), float("nan")
    idx = rng.integers(0, len(a), size=(BOOT, len(a)))
    ms = a[idx].mean(axis=1)
    m = float(a.mean())
    se = float(np.std(ms, ddof=1))
    return m, float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5)), se


def report(label, coins, res, key):
    """Equal-weighted (coin-clustered) BESIDE pooled, for every figure."""
    per_coin, pooled = [], []
    for coin in coins:
        r = res.get(coin)
        if not r:
            continue
        per_coin.append(float(np.mean(r[key])))
        pooled.extend(list(r[key]))
    m, lo, hi, se = boot_ci(per_coin)
    pm = float(np.mean(pooled)) if pooled else float("nan")
    z = m / se if se and np.isfinite(se) and se > 0 else float("nan")
    mde = 2.8 * se if np.isfinite(se) else float("nan")
    print("  %-26s eq-wt %+8.4f  [%+7.4f,%+7.4f]  z %6.2f | pooled %+8.4f | coins %3d n %6d"
          % (label, m, lo, hi, z, pm, len(per_coin), len(pooled)))
    return {"label": label, "eq_mean": m, "ci": [lo, hi], "se": se, "z": z,
            "pooled_mean": pm, "coins": len(per_coin), "n": len(pooled), "mde_2p8se": mde}


def main():
    print("M4 -- funding_hot sizing, ECONOMIC objective. PREREG 1a00b1cf amended 7c699867.")
    print("UNIT: %% OF EQUITY per trade (PREREG A1b). bps-of-notional made P2 identically zero.")
    print("P2 = P0 x %.5f EXACTLY -- arithmetic, not an estimate (A1c). Primary: P1 - P2.\n" % SHRINK)

    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    fund = {}
    for s in sorted({os.path.basename(p).split("_funding")[0]
                     for p in glob.glob(os.path.join(HIST, "*_funding.csv"))}):
        d = load_funding_daily(s)
        if d:
            fund[s] = d
    hot, fired_pct = hot_days(fund)
    print("funding panel: %d coins with funding, flag fired on %.1f%% of coin-days" % (len(fund), fired_pct))
    # VOID RUN 1 FOUND A WORSE DEFECT THAN THE PATH BUG. With HIST pointing at a directory that does
    # not exist, every coin was skipped -- and the script still printed "VERDICT: UNDERPOWERED" and
    # scored expectation 7.2 as "MISSED", because (nan > 0) == (nan > 0) is True and (nan < 0) is
    # False. A harness that renders a verdict out of ZERO ROWS is the absence-is-not-evidence failure
    # in the instrument itself. It must HALT, not conclude.
    if len(fund) < 50:
        raise SystemExit("HALT: only %d coins carry funding (expected ~178). Fix the source before "
                         "any arm is read -- an empty panel must never reach a verdict." % len(fund))

    real, ctrl, skipped = {}, {}, collections.Counter()
    for coin in coins:
        b = load_bars(c, coin)
        if b is None:
            skipped["under_500_bars"] += 1
            continue
        em_bar, dayv = daily_em(b)
        if em_bar is None:
            skipped["no_em"] += 1
            continue
        hs = hot.get(coin, set())
        if not hs:
            skipped["no_funding_or_never_hot"] += 1
            continue
        r = run_coin(b, em_bar, dayv, hs, synthetic=False)
        if r is None:
            skipped["under_50_hot_entries"] += 1
            continue
        s = run_coin(b, em_bar, dayv, hs, synthetic=True)
        if s is None:
            skipped["control_failed"] += 1
            continue
        real[coin], ctrl[coin] = r, s
    c.close()

    # --- control first, in the sealed report order -------------------------------------------------
    print("\n--- 1. CONTROL (martingale, no edge): expectancy must sit at about -(fee x notional) ---")
    for name, k, risk in POLICIES:
        vals = [float(np.mean(ctrl[x][name]["pnl"])) for x in ctrl]
        exp_fee = -FEE_FRAC * (risk / (k * 0.02)) * 100.0     # at a nominal 2% em, for scale only
        print("  %-14s control eq-wt %+8.4f %% of equity   (fee-only at em=2%%: %+.4f)"
              % (name, float(np.mean(vals)), exp_fee))

    net = {}
    for coin in real:
        net[coin] = {}
        for name, _, _ in POLICIES:
            net[coin][name + "_pnl"] = real[coin][name]["pnl"] - ctrl[coin][name]["pnl"]
            net[coin][name + "_dd"] = real[coin][name]["dd"]      # drawdown is not control-adjusted
        net[coin]["D_P1_P2_pnl"] = net[coin]["P1_widen_pnl"] - net[coin]["P2_sizedown_pnl"]
        net[coin]["D_P1_P2_dd"] = net[coin]["P1_widen_dd"] - net[coin]["P2_sizedown_dd"]
        net[coin]["D_P3_P2_pnl"] = net[coin]["P3_both_pnl"] - net[coin]["P2_sizedown_pnl"]

    o17 = [x for x in net if x in ORIG17]
    new = [x for x in net if x not in ORIG17]
    # Second half of the void-run fix: the held-out arm must actually HAVE coins to be evidence.
    if len(new) < 20 or len(o17) < 3:
        raise SystemExit("HALT: ORIG17 %d / NEW156 %d coins survived -- too few to report. The "
                         "verdict block is unreachable on an empty panel by design." % (len(o17), len(new)))
    print("\n--- 2. COUNTS --- coins %d (ORIG17 %d, NEW156 %d), entries/coin <= %d, skipped %s"
          % (len(net), len(o17), len(new), ENTRIES_PER_COIN, dict(skipped)))

    out = {"sealed": "1a00b1cf", "amended": "7c699867", "unit": "percent_of_equity_per_trade",
           "shrink": SHRINK, "flag_fired_pct": fired_pct, "coins": len(net),
           "orig17": len(o17), "new156": len(new), "skipped": dict(skipped), "arms": {}}

    print("\n--- 3. DETERMINISTIC, NOT ESTIMATED (A1c): P2 vs P0 ---")
    p0 = float(np.mean([np.mean(net[x]["P0_baseline_pnl"]) for x in net]))
    p2 = float(np.mean([np.mean(net[x]["P2_sizedown_pnl"]) for x in net]))
    print("  P0 %+.4f  P2 %+.4f  ratio %.5f (expected %.5f exactly) -- no CI, no verdict"
          % (p0, p2, (p2 / p0 if p0 else float('nan')), SHRINK))
    out["determinism_check"] = {"p0": p0, "p2": p2,
                                "ratio": (p2 / p0 if p0 else None), "expected": SHRINK}

    for arm, cl in (("ORIG17_discovery", o17), ("NEW156_heldout_NEAR_CLEAN", new)):
        print("\n--- 4. %s --- expectancy, %% of equity, control subtracted" % arm)
        rows = {}
        for name, _, _ in POLICIES:
            rows[name] = report(name, cl, net, name + "_pnl")
        print("  %-26s  THE PRIMARY ESTIMATED CONTRAST (equal notional, stop differs only)" % "")
        rows["D_P1_P2"] = report("D = P1_widen - P2_sizedown", cl, net, "D_P1_P2_pnl")
        rows["D_P3_P2"] = report("D = P3_both  - P2_sizedown", cl, net, "D_P3_P2_pnl")
        print("  --- drawdown (max adverse excursion, %% of equity; lower is better) ---")
        for name, _, _ in POLICIES:
            rows[name + "_dd"] = report(name + " dd", cl, net, name + "_dd")
        rows["D_P1_P2_dd"] = report("D dd = P1 - P2", cl, net, "D_P1_P2_dd")
        out["arms"][arm] = rows

    # --- verdict, on the HELD-OUT arm only, by the sealed rule ------------------------------------
    h = out["arms"]["NEW156_heldout_NEAR_CLEAN"]
    d, dd = h["D_P1_P2"], h["D_P1_P2_dd"]
    print("\n--- 5. VERDICT (held-out NEW156 only; ORIG17 is discovery and is NOT evidence) ---")
    print("  MDE (2.8 x SE, 80%% power at alpha .05) = %.4f %% of equity" % d["mde_2p8se"])
    print("  P1 - P2 = %+.4f, CI [%+.4f,%+.4f], z %.2f, threshold |z| > %.2f"
          % (d["eq_mean"], d["ci"][0], d["ci"][1], d["z"], Z_THR))
    signs_agree = (d["eq_mean"] > 0) == (d["pooled_mean"] > 0)
    clears = abs(d["z"]) > Z_THR if np.isfinite(d["z"]) else False
    above_mde = abs(d["eq_mean"]) > d["mde_2p8se"] if np.isfinite(d["mde_2p8se"]) else False
    if clears and signs_agree and above_mde:
        v = ("SUPPORT widen (P1)" if d["eq_mean"] > 0 else "SUPPORT size-down (P2)")
        if d["eq_mean"] > 0 and dd["eq_mean"] > 0:
            v += " -- but drawdown is WORSE; sealed tie-break favours the better drawdown"
    elif clears and not signs_agree:
        v = "UNDERPOWERED -- clears z but pooled and equal-weighted DISAGREE IN SIGN"
    else:
        v = "UNDERPOWERED"
    print("  signs agree: %s | above MDE: %s | clears z: %s" % (signs_agree, above_mde, clears))
    print("  VERDICT: %s" % v)
    print("  expectation 7.2 (P2 beats P1): %s"
          % ("HELD" if d["eq_mean"] < 0 else "MISSED -- the wider stop did not lose"))
    out["verdict"] = {"text": v, "signs_agree": bool(signs_agree), "above_mde": bool(above_mde),
                      "clears_z": bool(clears), "z_threshold": Z_THR}

    io.open(os.path.join(HERE, "m4_funding_sizing.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("\nwrote m4_funding_sizing.json")
    print("NEW156 is NEAR-CLEAN, NOT CLEAN: KSTAR_RECOMPUTE touched it with the same flag and lever.")


if __name__ == "__main__":
    main()
