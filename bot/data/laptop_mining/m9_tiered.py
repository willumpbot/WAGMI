"""M9 phase 2, step 1 -- REDO phase 1 with Hyperliquid's REAL maintenance margin.

WHY THIS EXISTS. M9 phase 1 modelled maintenance margin FLAT at 0.5% and declared in its own section
5.1 that the resulting ceilings were therefore optimistic. The server then told me the real schedule is
public (`meta` -> `marginTables`). It is, it is one unauthenticated call, and the real tier-1 numbers
are 2.5x to 10x my stand-in:

    mm = 1 / (2 * maxLeverage)      HL: maintenance margin is half the initial margin at max leverage
    BTC 1.25%   ETH 2.00%   SOL 2.50%   XRP 2.50%   HYPE 5.00%   NEAR 5.00%     vs my flat 0.50%

So phase 1's "hard ceiling 22x-43x" was wrong in the direction I flagged but had not measured. Phase 1
is owner-facing -- the server carded it as a milestone and the owner read it -- so the correction gets
published rather than quietly folded into phase 2.

SECOND THING THE REAL TABLE SETTLES, which phase 1 could not see at all: every asset carries an
EXCHANGE max leverage (BTC 40x, ETH 25x, SOL/XRP 20x, HYPE/NEAR 10x). Where that cap sits BELOW the
stop-based ceiling, the question "how much leverage is safe" is answered by Hyperliquid, not by me.

TIERS ARE IRRELEVANT AT THIS ACCOUNT SIZE, and that is worth stating rather than modelling: the
second tier begins at $20,000,000 to $150,000,000 of notional. A $5,000 account at 0.5% risk holds
about $1,000. Tier 1 is the only tier Nunu will ever touch, so "tiered margin" collapses to "the
tier-1 number", and the error in phase 1 was never about tiering -- it was about the level.

Everything else is phase 1's method unchanged: p99 one-day adverse move / 1.5 for the terminal's
"safe" leverage, real 1h bars, same-bar liquidation/stop ambiguity counted AS A LIQUIDATION.
EXPLORATORY. No live change; the recommendation from phase 1 (do not raise the cap) is re-tested here.
"""
import io
import json
import math
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
EPS = 1e-8
ACCOUNT = 5000.0
RISK_PCT = 0.005
HORIZON_H = 72
SAFE_DIV = 1.5
FRACS = (0.5, 0.8, 1.0, 1.2)
ENTRIES = 600
MM_FLAT_PHASE1 = 0.005          # what phase 1 assumed, kept only to quantify the correction
MAJORS = ("BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR")
rng = np.random.default_rng(20261013)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]
TIERS = json.load(io.open(os.path.join(HERE, "hl_margin_tiers.json"), encoding="utf-8"))


def mm_and_cap(coin, notional_usd):
    """Real maintenance-margin fraction and exchange max leverage for this coin at this notional."""
    r = TIERS.get(coin)
    if not r or not r.get("tiers"):
        return None, None
    lev = None
    for t in sorted(r["tiers"], key=lambda x: x["lower_usd"]):
        if notional_usd >= t["lower_usd"]:
            lev = t["max_lev"]
    lev = lev or r["max_leverage"]
    return 1.0 / (2.0 * lev), float(lev)


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
    return em[np.searchsorted(uniq, day)]


def p99_adverse(b):
    day = (b["t"] // 86400000).astype(np.int64)
    uniq, first = np.unique(day, return_index=True)
    close = np.array([b["c"][i] for i in np.append(first[1:], len(b["c"])) - 1])
    r = np.abs(close[1:] / close[:-1] - 1.0) * 100.0
    r = r[np.isfinite(r)]
    return float(np.percentile(r, 99)) if len(r) > 30 else None


def main():
    print("M9 phase 2 step 1 -- phase 1 redone with HL's REAL maintenance margin. EXPLORATORY.")
    print("mm = 1/(2*maxLeverage) per HL; phase 1 used a FLAT %.3f stand-in.\n" % MM_FLAT_PHASE1)
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    vol = {r[0]: r[1] for r in c.execute("SELECT coin, COUNT(*) FROM candles_1h GROUP BY coin")}
    coins = list(MAJORS) + [k for k in sorted(vol, key=lambda x: -vol[x])
                            if k not in MAJORS and k in TIERS][:14]
    out = []
    print("%-6s %6s %7s %7s %7s | %8s %8s %7s | %7s  %s"
          % ("coin", "em%", "p99%", "mm%", "HLcap", "ceil_old", "ceil_new", "shrink", "safeL",
             "P(liq<stop)@120%"))
    for coin in coins:
        b = bars(c, coin)
        if b is None:
            continue
        em_bar = em_series(b)
        p99 = p99_adverse(b)
        if em_bar is None or not p99:
            continue
        emf_mean = float(np.nanmean(em_bar)) / 100.0
        notional = (ACCOUNT * RISK_PCT) / emf_mean          # the position this account actually holds
        mm, hlcap = mm_and_cap(coin, notional)
        if mm is None:
            continue
        # phase 1's two headline quantities, recomputed with the real mm and then capped by HL
        ceil_old = 1.0 / (emf_mean + MM_FLAT_PHASE1)
        ceil_raw = 1.0 / (emf_mean + mm)
        ceil_new = min(ceil_raw, hlcap)
        safe_L = min(hlcap, 1.0 / ((p99 / 100.0) * SAFE_DIV + mm))
        n = len(b["c"])
        ok = np.flatnonzero(~np.isnan(em_bar[:n - HORIZON_H - 1]))
        if len(ok) < 100:
            continue
        ent = rng.choice(ok, size=min(ENTRIES, len(ok)), replace=False)
        side = np.where(rng.random(len(ent)) < 0.5, 1.0, -1.0)
        pidx = ent[:, None] + np.arange(1, HORIZON_H + 1)[None, :]
        H, L_ = b["h"][pidx], b["l"][pidx]
        entry = b["c"][ent]
        emf = em_bar[ent] / 100.0
        adv = np.where(side[:, None] > 0, (entry[:, None] - L_) / entry[:, None],
                       (H - entry[:, None]) / entry[:, None])
        row = {"coin": coin, "em_pct": emf_mean * 100, "p99_adv_pct": p99, "mm_frac": mm,
               "hl_max_leverage": hlcap, "ceiling_phase1_flat_mm": ceil_old,
               "ceiling_real_mm_uncapped": ceil_raw, "ceiling_real_mm_capped": ceil_new,
               "cap_binds": bool(ceil_raw > hlcap), "safe_L": safe_L, "liq_before_stop": {}}
        cells = []
        for f in FRACS:
            Lv = max(1.0, safe_L * f)
            liq_frac = max(1.0 / Lv - mm, 1e-4)
            sb = np.where((adv >= emf[:, None]).any(axis=1),
                          (adv >= emf[:, None]).argmax(axis=1), 10 ** 6)
            lb = np.where((adv >= liq_frac).any(axis=1), (adv >= liq_frac).argmax(axis=1), 10 ** 6)
            # the phase-1 sentinel bug: BOTH "never reached" states are 10**6, so `lb <= sb` was True
            # when NEITHER happened. The liquidation must actually be REACHED to count.
            p = float(np.mean((lb < 10 ** 6) & (lb <= sb)))
            row["liq_before_stop"]["%.0f%%" % (f * 100)] = p
            cells.append(p)
        out.append(row)
        print("%-6s %6.2f %7.2f %7.2f %6.0fx | %7.1fx %7.1fx %6.2fx | %6.1fx  %.3f%s"
              % (coin, row["em_pct"], p99, mm * 100, hlcap, ceil_old, ceil_new,
                 ceil_old / ceil_new if ceil_new else float("nan"), safe_L, cells[3],
                 "  <-- HL CAP BINDS" if row["cap_binds"] else ""))
    c.close()

    maj = [r for r in out if r["coin"] in MAJORS]
    binds = [r for r in maj if r["cap_binds"]]
    print("\n--- WHAT CHANGED vs PHASE 1 ---")
    if maj:
        sh = [r["ceiling_phase1_flat_mm"] / r["ceiling_real_mm_capped"] for r in maj]
        print("  stop-based ceiling is %.2fx to %.2fx LOWER than phase 1 reported (flat mm understated"
              " maintenance margin by 2.5x-10x)" % (min(sh), max(sh)))
        rat = [r["ceiling_real_mm_capped"] / r["safe_L"] for r in maj]
        print("  terminal table is now %.1fx to %.1fx conservative, NOT phase 1's 4.6x-6.7x"
              % (min(rat), max(rat)))
        print("  HL's own max leverage is the binding ceiling for %d of %d majors: %s"
              % (len(binds), len(maj), ", ".join(r["coin"] for r in binds) or "none"))
        print("  P(liq before stop) at 120%% of safe L, majors: %.3f to %.3f"
              % (min(r["liq_before_stop"]["120%"] for r in maj),
                 max(r["liq_before_stop"]["120%"] for r in maj)))
    print("\n  UNCHANGED: with dollar risk fixed by the stop, leverage still cannot move P&L. That was")
    print("  algebra (size = risk / stop), not simulation, so no margin number touches it.")
    print("  Tier 2 starts at $20M-$150M notional; this account holds ~$1,000. Tier 1 is the only")
    print("  tier that will ever apply, so 'tiered margin' reduces to 'the tier-1 level'.")

    io.open(os.path.join(HERE, "m9_tiered.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("\nwrote m9_tiered.json")


if __name__ == "__main__":
    main()
