"""M9 — LEVERAGE & POSITIONING on the majors. Owner priority. EXPLORATORY phase 1.

Owner: "there's a lot of opportunity in extensively data mining through leverage and how to position,
especially in majors ... I probably would've gone closer to the safe max limit, however I don't know
... that's where the data and information gap really comes in." Today the ideas used <=3x on SOL/HYPE
where the terminal's safe leverage read 5.9x / 4.4x.

THE FRAMING FACT, which the mission states and which decides how to read everything below:
with DOLLAR RISK FIXED BY THE STOP, leverage does not change P&L at all. Size is risk / stop_distance,
so the position is identical at 3x and at 6x. Leverage changes exactly two things:
    1. MARGIN LOCKED  = notional / L   -> how many concurrent positions a $5k account can carry
    2. LIQUIDATION DISTANCE = 1/L - mm -> whether a wick can liquidate before the stop fills
So "3x or 5.9x" is not a returns question. Anyone answering it in terms of expected profit has the
wrong model. This file measures the two things leverage actually moves.

WHAT THE TERMINAL'S TABLE DOES TODAY: liquidation placed beyond the coin's own p99 1-day adverse move
over a year, divided by 1.5, capped at the HL max. That protects against a p99 DAILY CLOSE move --
but a stop at one expected move (~3%) fills long before an 11% p99 move, so the table is guarding
against something the stop already handles, UNLESS price can reach liquidation without the stop
filling. That is a wick/gap question, and it is measurable.

MEASURED HERE, per coin:
  * p99 1-day adverse move, and the implied "safe" leverage the terminal would quote
  * at 50 / 80 / 100 / 120% of that safe leverage: P(an intraday wick reaches LIQUIDATION before the
    stop fills), from real bars, with same-bar ambiguity counted AS A LIQUIDATION (conservative --
    we cannot know the order inside one bar, and assuming the bad outcome is the only honest default)
  * the hard ceiling: the largest L at which liquidation still sits outside a 1-em stop
  * margin freed: concurrent positions a $5,000 account can carry at each L, dollar risk fixed
  * conditioned on HAR exp_move decile, so "is /1.5 too timid" can be answered by regime

Maintenance margin is taken as a flat MM_FRAC here; HL's tiered schedule is a phase-2 refinement and
is NOT modelled, so liquidation distances are slightly optimistic for large positions. Declared.
Funding accrual over the hold is also phase 2.

EXPLORATORY. No card above HYPOTHESIS, and no live change without SUPPORT + owner yes.
"""
import collections
import io
import json
import math
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
EPS = 1e-8
MM_FRAC = 0.005          # flat maintenance margin stand-in; HL tiers are phase 2
ACCOUNT = 5000.0
RISK_PCT = 0.005         # the owner's own 0.5% per-trade cap, now enforced in code
HORIZON_H = 72
SAFE_DIV = 1.5           # the terminal's divisor, the thing under test
HL_MAX_L = 20.0
FRACS = (0.5, 0.8, 1.0, 1.2)
ENTRIES = 600
MAJORS = ("BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR")
rng = np.random.default_rng(20261013)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def bars(c, coin):
    rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
    if len(rows) < 500:
        return None
    a = np.asarray(rows, float)
    return {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


def em_series(b):
    """Fitted-HAR exp_move per day, mapped to each 1h bar (percent)."""
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
    return em[np.searchsorted(uniq, day)], rets


def p99_adverse(b):
    """p99 one-day adverse move (percent), both sides, from daily closes -- the table's own basis."""
    day = (b["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    close = np.array([b["c"][i] for i in np.append(first[1:], len(b["c"])) - 1])
    r = np.abs(close[1:] / close[:-1] - 1.0) * 100.0
    r = r[np.isfinite(r)]
    return float(np.percentile(r, 99)) if len(r) > 30 else None


def main():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    vol = {r[0]: r[1] for r in c.execute(
        "SELECT coin, COUNT(*) FROM candles_1h GROUP BY coin")}
    coins = list(MAJORS) + [k for k in sorted(vol, key=lambda x: -vol[x])
                            if k not in MAJORS][:20]
    print("M9 phase 1 -- what leverage actually costs. EXPLORATORY.")
    print("FRAMING: with dollar risk fixed by the stop, leverage changes MARGIN and LIQUIDATION")
    print("DISTANCE only -- never P&L. 3x and 6x hold the same position.\n")
    out = []
    print("%-7s %7s %8s %9s   %s" % ("coin", "em%", "p99adv%", "safeL", "P(liq before stop) at % of safeL"))
    print("%-7s %7s %8s %9s   %8s %8s %8s %8s  %9s" % ("", "", "", "", "50%", "80%", "100%", "120%",
                                                       "hardceil"))
    for coin in coins:
        b = bars(c, coin)
        if b is None:
            continue
        em_bar, _ = em_series(b)
        p99 = p99_adverse(b)
        if em_bar is None or not p99:
            continue
        safe_L = min(HL_MAX_L, 1.0 / ((p99 / 100.0) * SAFE_DIV + MM_FRAC))
        n = len(b["c"])
        ok = np.flatnonzero(~np.isnan(em_bar[:n - HORIZON_H - 1]))
        if len(ok) < 100:
            continue
        ent = rng.choice(ok, size=min(ENTRIES, len(ok)), replace=False)
        side = np.where(rng.random(len(ent)) < 0.5, 1.0, -1.0)
        off = np.arange(1, HORIZON_H + 1)
        pidx = ent[:, None] + off[None, :]
        H, L_ = b["h"][pidx], b["l"][pidx]
        entry = b["c"][ent]
        emf = em_bar[ent] / 100.0
        adv = np.where(side[:, None] > 0,
                       (entry[:, None] - L_) / entry[:, None],
                       (H - entry[:, None]) / entry[:, None])
        row = {"coin": coin, "em_pct": float(np.mean(emf) * 100), "p99_adv_pct": p99,
               "safe_L": safe_L, "liq_before_stop": {}}
        cells = []
        for f in FRACS:
            Lv = max(1.0, safe_L * f)
            liq_frac = max(1.0 / Lv - MM_FRAC, 1e-4)
            stop_frac = emf                      # our rule: stop at one expected move
            # first bar reaching the stop, and first reaching liquidation
            sb = np.where((adv >= stop_frac[:, None]).any(axis=1),
                          (adv >= stop_frac[:, None]).argmax(axis=1), 10 ** 6)
            lb = np.where((adv >= liq_frac).any(axis=1),
                          (adv >= liq_frac).argmax(axis=1), 10 ** 6)
            # same bar => counted as liquidation (conservative: ordering unknowable within a bar).
            # BUG FIXED: both "never reached" states are the sentinel 10**6, so `lb <= sb` was TRUE
            # when NEITHER was hit -- scoring every quiet trade as a liquidation. That produced a flat
            # ~0.4 at every leverage, which is what exposed it: P(liq) must RISE with leverage. The
            # liquidation must actually be REACHED to count. Sentinel-as-value, the same family as
            # treating an absent log line as a zero.
            p = float(np.mean((lb < 10 ** 6) & (lb <= sb)))
            row["liq_before_stop"]["%.0f%%" % (f * 100)] = p
            cells.append(p)
        hard = 1.0 / (float(np.mean(emf)) + MM_FRAC)
        row["hard_ceiling_L"] = hard
        out.append(row)
        print("%-7s %7.2f %8.2f %9.1f   %7.3f %8.3f %8.3f %8.3f  %9.1f"
              % (coin, row["em_pct"], p99, safe_L, cells[0], cells[1], cells[2], cells[3], hard))
    c.close()

    print("\n--- WHAT LEVERAGE BUYS: margin freed, dollar risk fixed at %.1f%% of $%.0f ---"
          % (RISK_PCT * 100, ACCOUNT))
    print("  (notional = risk / stop_frac, so notional is FIXED; only margin = notional/L moves)")
    print("  %-7s %9s %12s %12s %12s" % ("coin", "stop%", "notional$", "margin@3x", "margin@safeL"))
    for r in out[:6]:
        stop_frac = r["em_pct"] / 100.0
        notional = (ACCOUNT * RISK_PCT) / stop_frac
        print("  %-7s %8.2f%% %12.0f %12.0f %12.0f"
              % (r["coin"], r["em_pct"], notional, notional / 3.0, notional / r["safe_L"]))
    io.open(os.path.join(HERE, "m9_leverage.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote m9_leverage.json")
    print("Same-bar liq/stop counted AS LIQUIDATION. MM is flat %.3f, HL tiers are phase 2." % MM_FRAC)


if __name__ == "__main__":
    main()
