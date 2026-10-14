"""M11 -- CASHCAT dive (owner-flagged coin workflow, first instance). EXPLORATORY.

OWNER flagged CASHCAT near ~0.102-0.104 on 10-13 ~17:00Z; it ran ~+27% to 0.1295 by 10-14 22:00Z, the
first leg being 21:00Z at +8.3% on 2.9x hourly volume. His words: "I was telling you it looks good so we
could start data mining and analyzing it."

🔴 THE STRUCTURAL PROBLEM, STATED FIRST BECAUSE IT DECIDES WHAT THIS FILE CAN CLAIM.
The pattern being tested was described AFTER watching it work. One realised instance, selected because
it paid, is an anecdote and cannot be evidence of anything -- no matter how many statistics I compute on
it. So the design is:
    * CASHCAT's own trigger count is reported as a COUNT, and if it is small the answer is "too small".
    * THE EVIDENCE IS THE CROSS-SECTION: the identical rule applied to all ~178 perps, coin-clustered.
      That arm was not selected on outcome and is the only one with power.
    * Every forward number is compared to the SAME coin's unconditional base rate over the same
      horizon. "Continuation" can only mean "beat the base rate", never "went up".

TRIGGERS, both defined once and applied identically everywhere:
  A  the owner's setup    1h close-to-close >= +8%, hourly volume >= 2.5x trailing 480h median,
                          and the close sitting in the LOWER THIRD of the trailing 20d range
  B  the server's new     |1h move| >= 0.5 x (daily exp_move / sqrt 24) on >= 2.5x median volume
     'waking up' alert    -- a looser attention trigger; reported for the UP leg and for both legs

FORWARD: 4h / 24h / 72h from the trigger close. Sign (mean, median, P(up)) AND magnitude (mean |move|),
because the owner asked for both and they answer different questions.

DATA NOTE, correcting the request: the server said funding_oi_history has no fresh CASHCAT rows and to
use HL fundingHistory directly. True of that collector -- but `panels.sqlite.funding_hist` already
carries 2,298 CASHCAT rows locally, which is the same source the rest of this project uses. No fetch.

EXPLORATORY. Attention signal, not an edge claim. No card above HYPOTHESIS.
"""
import io
import json
import math
import os
import sqlite3

import numpy as np

import panel_snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
EPS = 1e-8
COIN = "CASHCAT"
VOL_MULT = 2.5
MED_WIN = 480          # 20 days of hourly bars for the volume median and the range
RET_A = 0.08           # trigger A: +8% hour
EM_MULT_B = 0.5        # trigger B: half an hourly expected move
FWD_H = (4, 24, 72)
BOOT = 4000
rng = np.random.default_rng(20261014)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def bars(c, coin):
    rows = c.execute("SELECT t,o,h,l,c,v FROM candles_1h WHERE coin=? ORDER BY t",
                     (coin,)).fetchall()
    if len(rows) < MED_WIN + max(FWD_H) + 60:
        return None
    a = np.asarray(rows, float)
    return {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5]}


def em_hourly(b):
    """Live daily HAR forecast / sqrt(24), per 1h bar, as a fraction."""
    day = (b["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    close = np.array([b["c"][i] for i in np.append(first[1:], len(b["c"])) - 1])
    if len(close) < 40:
        return None
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
    return (em[np.searchsorted(uniq, day)] / 100.0) / math.sqrt(24.0)


def roll_median(v, w):
    out = np.full(len(v), np.nan)
    for i in range(w, len(v)):
        out[i] = np.median(v[i - w:i])
    return out


def triggers(b):
    """Boolean masks for trigger A and trigger B, aligned to the bar that CLOSED the move."""
    n = len(b["c"])
    ret = np.full(n, np.nan)
    ret[1:] = b["c"][1:] / b["c"][:-1] - 1.0
    medv = roll_median(b["v"], MED_WIN)
    volok = (medv > 0) & (b["v"] >= VOL_MULT * medv)
    # lower third of the trailing 20d range, measured BEFORE this bar
    lo = np.full(n, np.nan); hi = np.full(n, np.nan)
    for i in range(MED_WIN, n):
        lo[i] = np.min(b["l"][i - MED_WIN:i])
        hi[i] = np.max(b["h"][i - MED_WIN:i])
    rng_pos = (b["c"] - lo) / np.maximum(hi - lo, EPS)
    lower_third = rng_pos <= (1.0 / 3.0)
    em = em_hourly(b)
    A = np.isfinite(ret) & (ret >= RET_A) & volok & lower_third
    B_up = np.isfinite(ret) & (em is not None) & volok & (ret >= EM_MULT_B * (em if em is not None else 0))
    B_abs = np.isfinite(ret) & volok & (np.abs(ret) >= EM_MULT_B * (em if em is not None else 0))
    # never fire inside the warmup or where a forward window would run off the end
    ok = np.zeros(n, bool)
    ok[MED_WIN:n - max(FWD_H) - 1] = True
    return (A & ok), (B_up & ok), (B_abs & ok), ret


def forwards(b, mask, ret):
    """Forward returns from each trigger close, plus the SAME coin's unconditional base rate."""
    n = len(b["c"])
    idx = np.flatnonzero(mask)
    base_idx = np.arange(MED_WIN, n - max(FWD_H) - 1)
    out = {}
    for h in FWD_H:
        f = lambda ii: b["c"][ii + h] / b["c"][ii] - 1.0
        t = f(idx) if len(idx) else np.array([])
        bse = f(base_idx)
        out[h] = {
            "n": int(len(t)),
            "mean": float(np.mean(t)) if len(t) else None,
            "median": float(np.median(t)) if len(t) else None,
            "p_up": float(np.mean(t > 0)) if len(t) else None,
            "mean_abs": float(np.mean(np.abs(t))) if len(t) else None,
            "base_mean": float(np.mean(bse)),
            "base_median": float(np.median(bse)),
            "base_p_up": float(np.mean(bse > 0)),
            "base_mean_abs": float(np.mean(np.abs(bse))),
        }
    return out


def profile(c, b):
    """Volatility, BTC beta, funding -- the owner's three profile questions."""
    day = (b["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    dh = np.array([np.max(b["h"][i:j]) for i, j in zip(first, np.append(first[1:], len(b["h"])))])
    dl = np.array([np.min(b["l"][i:j]) for i, j in zip(first, np.append(first[1:], len(b["l"])))])
    dc = np.array([b["c"][j - 1] for j in np.append(first[1:], len(b["c"]))])
    tr = np.maximum(dh[1:] - dl[1:], np.maximum(np.abs(dh[1:] - dc[:-1]), np.abs(dl[1:] - dc[:-1])))
    atr14 = float(np.mean(tr[-14:]) / dc[-1] * 100) if len(tr) >= 14 else None
    rets = (dc[1:] / dc[:-1] - 1.0) * 100
    # BTC beta on common 1h bars
    bt = bars(c, "BTC")
    beta = r2 = None
    if bt is not None:
        ha, hb = (b["t"] // 3600000).astype(np.int64), (bt["t"] // 3600000).astype(np.int64)
        common, ia, ib = np.intersect1d(ha, hb, return_indices=True)
        if len(common) > 200:
            ra = np.diff(np.log(b["c"][ia]))
            rb = np.diff(np.log(bt["c"][ib]))
            g = np.isfinite(ra) & np.isfinite(rb)
            if g.sum() > 200 and np.var(rb[g]) > 0:
                beta = float(np.cov(ra[g], rb[g])[0, 1] / np.var(rb[g]))
                r2 = float(np.corrcoef(ra[g], rb[g])[0, 1] ** 2)
    rows = c.execute("SELECT t,rate FROM funding_hist WHERE coin=? ORDER BY t", (COIN,)).fetchall()
    fr = np.asarray([r[1] for r in rows], float) if rows else np.array([])
    fnd = None
    if len(fr):
        fnd = {"rows": int(len(fr)), "mean_hourly": float(np.mean(fr)),
               "mean_pct_per_day": float(np.mean(fr) * 24 * 100),
               "last_pct_per_day": float(fr[-1] * 24 * 100),
               "pct_rows_positive": float(np.mean(fr > 0) * 100),
               "newest_t": int(rows[-1][0])}
    return {"atr14_pct_per_day": atr14, "daily_sd_pct": float(np.std(rets, ddof=1)),
            "btc_beta_1h": beta, "btc_r2_1h": r2, "n_daily": int(len(rets)), "funding": fnd}


def main():
    print("M11 -- CASHCAT dive. EXPLORATORY. Attention signal, NOT an edge claim.")
    print("The owner's own instance is ONE outcome-selected observation. The cross-section is the")
    print("evidence; CASHCAT's own trigger count is reported as a count.\n")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    snap = panel_snapshot.stamp(c, ("candles_1h", "funding_hist"))
    print("SOURCE SNAPSHOT: %s\n" % panel_snapshot.describe(snap))

    cb = bars(c, COIN)
    if cb is None:
        c.close()
        raise SystemExit("HALT: %s has too little 1h history to run anything." % COIN)
    out = {"source_snapshot": snap, "coin": COIN,
           "n_bars": int(len(cb["c"])),
           "days": float((cb["t"][-1] - cb["t"][0]) / 86400000)}
    print("--- 1. %s PROFILE (%d bars, %.1f days) ---" % (COIN, out["n_bars"], out["days"]))
    prof = profile(c, cb)
    out["profile"] = prof
    print("  ATR14 %.1f%%/day | daily sd %.1f%% | BTC beta(1h) %s (R2 %s) over %d daily obs"
          % (prof["atr14_pct_per_day"] or float("nan"), prof["daily_sd_pct"],
             ("%.2f" % prof["btc_beta_1h"]) if prof["btc_beta_1h"] else "n/a",
             ("%.2f" % prof["btc_r2_1h"]) if prof["btc_r2_1h"] else "n/a", prof["n_daily"]))
    if prof["funding"]:
        f = prof["funding"]
        print("  funding: %d local rows, mean %+.3f%%/day, latest %+.3f%%/day, %.0f%% of hours positive"
              % (f["rows"], f["mean_pct_per_day"], f["last_pct_per_day"], f["pct_rows_positive"]))

    A, Bu, Ba, ret = triggers(cb)
    out["cashcat_triggers"] = {"A_owner_setup": int(A.sum()), "B_up": int(Bu.sum()),
                               "B_abs": int(Ba.sum())}
    print("\n--- 2. %s OWN TRIGGER COUNTS --- A(+8%%/2.5x/lower-third) %d | B_up %d | B_abs %d"
          % (COIN, A.sum(), Bu.sum(), Ba.sum()))
    for nm, m in (("A_owner_setup", A), ("B_up", Bu), ("B_abs", Ba)):
        fw = forwards(cb, m, ret)
        out.setdefault("cashcat_forward", {})[nm] = fw
        if fw[4]["n"] == 0:
            print("  %-14s n=0 -- the rule never fired on its own history. Nothing to report." % nm)
            continue
        print("  %-14s n=%d" % (nm, fw[4]["n"]))
        for h in FWD_H:
            d = fw[h]
            print("     +%-3dh  mean %+7.2f%% (base %+6.2f%%) | median %+7.2f%% | P(up) %4.0f%% "
                  "(base %4.0f%%) | |move| %5.2f%% (base %5.2f%%)"
                  % (h, d["mean"] * 100, d["base_mean"] * 100, d["median"] * 100,
                     d["p_up"] * 100, d["base_p_up"] * 100,
                     d["mean_abs"] * 100, d["base_mean_abs"] * 100))

    print("\n--- 3. THE EVIDENCE ARM: identical rules across all perps, coin-clustered ---")
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    agg = {nm: {h: [] for h in FWD_H} for nm in ("A_owner_setup", "B_up", "B_abs")}
    counts = {nm: 0 for nm in agg}
    ncoins = {nm: 0 for nm in agg}
    for coin in coins:
        bb = bars(c, coin)
        if bb is None:
            continue
        a2, b2u, b2a, r2_ = triggers(bb)
        for nm, m in (("A_owner_setup", a2), ("B_up", b2u), ("B_abs", b2a)):
            if m.sum() < 3:
                continue
            fw = forwards(bb, m, r2_)
            counts[nm] += fw[4]["n"]
            ncoins[nm] += 1
            for h in FWD_H:
                # EXCESS over the same coin's own base rate -- that is what "continuation" means
                agg[nm][h].append(fw[h]["mean"] - fw[h]["base_mean"])
    c.close()
    for nm in ("A_owner_setup", "B_up", "B_abs"):
        if ncoins[nm] < 3:
            print("  %-14s only %d coins fired it >=3 times -- too few to pool." % (nm, ncoins[nm]))
            continue
        print("  %-14s %d coins, %d triggers total" % (nm, ncoins[nm], counts[nm]))
        for h in FWD_H:
            a = np.asarray(agg[nm][h], float)
            a = a[np.isfinite(a)]
            idx = rng.integers(0, len(a), size=(BOOT, len(a)))
            ms = a[idx].mean(axis=1)
            m, se = float(a.mean()), float(np.std(ms, ddof=1))
            lo, hi = float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5))
            z = m / se if se > 0 else float("nan")
            verdict = ("CONTINUATION" if (m > 0 and abs(z) > 2) else
                       "FADE" if (m < 0 and abs(z) > 2) else "no signal")
            print("     +%-3dh excess over own base rate %+6.2f%% [%+6.2f,%+6.2f] z %6.2f  -> %s"
                  % (h, m * 100, lo * 100, hi * 100, z, verdict))
            out.setdefault("cross_section", {}).setdefault(nm, {})[h] = {
                "coins": ncoins[nm], "triggers": counts[nm], "excess_mean": m,
                "ci": [lo, hi], "z": z, "verdict": verdict}

    io.open(os.path.join(HERE, "m11_cashcat_dive.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("\nwrote m11_cashcat_dive.json")
    print("REMINDER: 'excess over own base rate' is the only honest reading of continuation.")


if __name__ == "__main__":
    main()
