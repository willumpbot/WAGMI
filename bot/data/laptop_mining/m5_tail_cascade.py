"""M5 -- TAIL / CASCADE RISK. P(|1h move| > 3x expected) conditional on five regimes. EXPLORATORY.

MISSION: "P(|1h move| > 3x expected) conditional on liq bursts, OI change, funding extremes, depth
thinning, BTC shocks. Output: a recalibrated safe-leverage table (rolling, fat-tail aware) and which
conditions should cut leverage. Magnitude only."

THE DESIGN FACT THAT DECIDES EVERYTHING -- the five conditions are NOT equally observable here:

    condition            coins   window
    funding extremes      178    ~367 d   funding_hist
    BTC shocks            178    ~210 d   candles_1h
    OI change              31     128 d   server_exports/funding_oi_history.jsonl.gz
    depth thinning         30    ~103 d   panels.depth
    liq bursts             13     ~73 d   panels.liq_events

So a single table "conditioned on all five" would silently collapse to the INTERSECTION: 13 coins over
73 days. Each condition is therefore measured on its OWN maximal panel, and every row prints its own
coin count and window. A lift found on 13 coins is not the same evidence as one found on 178, and the
output must not let those sit in one column looking alike.

OUTCOME, fixed before looking: tail = |next 1h return| > 3 x (expected 1h move), where the expected 1h
move is the live daily HAR forecast scaled by sqrt(24). The condition is evaluated from information at
bar i and the outcome is bar i+1, so nothing peeks.

PLACEBO THAT CAN FAIL: each coin's condition series is CIRCULARLY SHIFTED by a random offset. That
preserves the marginal rate AND the condition's own autocorrelation, and destroys only its alignment
with the outcome. A real regime effect must survive it; a spurious one driven by "flags cluster in
volatile months" will not. This is the research standard's requirement -- a placebo pinned to zero by
construction is not a placebo, so this one resamples the alignment and is free to come out positive.

LEVERAGE OUTPUT uses HL's REAL tier-1 maintenance margin (hl_margin_tiers.json), not the flat 0.5%
stand-in that M9 phase 1 got wrong, and is capped by HL's own per-asset max leverage.

EXPLORATORY: no card above HYPOTHESIS, no live change. Magnitude only -- nothing here says which way
to trade, only how far price can travel against a stop.
"""
import collections
import datetime
import gzip
import io
import json
import math
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
EPS = 1e-8
TAIL_MULT = 3.0
HOURS_PER_DAY = 24.0
EXTREME_Q = 0.95          # "extreme" = top 5% of the coin's OWN distribution
BOOT = 4000
MIN_COND_HOURS = 30       # a coin needs this many flagged hours to contribute a rate
rng = np.random.default_rng(20261013)

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]
TIERS = json.load(io.open(os.path.join(HERE, "hl_margin_tiers.json"), encoding="utf-8"))


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def em_hourly(b):
    """Expected 1h |move| as a FRACTION: the live daily HAR forecast / sqrt(24), per 1h bar."""
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
    return (em[np.searchsorted(uniq, day)] / 100.0) / math.sqrt(HOURS_PER_DAY)


def load_1h(c):
    out = {}
    rows = c.execute("SELECT coin,t,h,l,c FROM candles_1h ORDER BY coin,t").fetchall()
    cur, buf = None, []
    for coin, t, h, l, cl in rows:
        if coin != cur:
            if cur and len(buf) >= 500:
                a = np.asarray(buf, float)
                out[cur] = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
            cur, buf = coin, []
        buf.append((t, h, l, cl))
    if cur and len(buf) >= 500:
        a = np.asarray(buf, float)
        out[cur] = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
    return out


def hour_key(t_ms):
    return (np.asarray(t_ms, np.int64) // 3600000).astype(np.int64)


# ------------------------------------------------------------------ condition builders (per coin)
def cond_funding(c, coins):
    """|funding rate| in the top 5% of the coin's own history. 178 coins, widest window."""
    out = {}
    rows = c.execute("SELECT coin,t,rate FROM funding_hist ORDER BY coin,t").fetchall()
    by = collections.defaultdict(list)
    for coin, t, r in rows:
        if r is not None:
            by[coin].append((int(t) // 3600000, abs(float(r))))
    for coin, v in by.items():
        if coin not in coins or len(v) < 500:
            continue
        a = np.asarray(v, float)
        thr = float(np.quantile(a[:, 1], EXTREME_Q))
        out[coin] = set(a[a[:, 1] >= thr, 0].astype(np.int64).tolist())
    return out, "funding_hist"


def cond_btc_shock(bars):
    """|BTC 1h move| above 3x BTC's own expected 1h move. MARKET-WIDE: same hours for every coin."""
    b = bars.get("BTC")
    if b is None:
        return {}, "no BTC"
    em = em_hourly(b)
    if em is None:
        return {}, "no em"
    ret = np.concatenate(([0.0], np.abs(b["c"][1:] / b["c"][:-1] - 1.0)))
    hk = hour_key(b["t"])
    ok = np.isfinite(em) & np.isfinite(ret)
    hit = ok & (ret > TAIL_MULT * em)
    return set(hk[hit].tolist()), "candles_1h/BTC"


def cond_oi(coins):
    """|1h change in open interest| in the top 5% of the coin's own history. 31 coins, 128 d."""
    p = os.path.join(HERE, "server_exports", "funding_oi_history.jsonl.gz")
    if not os.path.exists(p):
        return {}, "absent"
    by = collections.defaultdict(list)
    with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            s, oi, t = r.get("symbol"), r.get("open_interest"), r.get("timestamp")
            if s is None or oi is None or t is None:
                continue
            if isinstance(t, str):
                try:
                    t = datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
            t = float(t) / 1000.0 if float(t) > 1e11 else float(t)
            by[s].append((int(t // 3600), float(oi)))
    out = {}
    for coin, v in by.items():
        if coin not in coins or len(v) < 200:
            continue
        v = sorted(set(v))
        a = np.asarray(v, float)
        oi = a[:, 1]
        d = np.abs(np.diff(oi) / np.maximum(oi[:-1], 1e-9))
        if len(d) < 100:
            continue
        thr = float(np.quantile(d, EXTREME_Q))
        out[coin] = set(a[1:, 0][d >= thr].astype(np.int64).tolist())
    return out, "funding_oi_history.jsonl.gz"


def cond_depth(c, coins):
    """Total 0.5% book depth in the BOTTOM 5% of the coin's own history. 30 coins, ~103 d."""
    try:
        rows = c.execute("SELECT symbol,t,bid_05,ask_05 FROM depth ORDER BY symbol,t").fetchall()
    except Exception as e:
        return {}, "depth unreadable: %s" % e
    by = collections.defaultdict(list)
    for s, t, bd, ak in rows:
        if bd is None or ak is None:
            continue
        tot = float(bd) + float(ak)
        if tot > 0:
            by[s].append((int(t) // 3600000, tot))
    out = {}
    for coin, v in by.items():
        if coin not in coins or len(v) < 200:
            continue
        a = np.asarray(v, float)
        thr = float(np.quantile(a[:, 1], 1.0 - EXTREME_Q))     # THIN = low depth
        out[coin] = set(a[a[:, 1] <= thr, 0].astype(np.int64).tolist())
    return out, "panels.depth"


def cond_liq(c, coins):
    """Hourly liquidation notional in the top 5% of the coin's own NONZERO hours. 13 coins, ~73 d."""
    try:
        rows = c.execute("SELECT symbol,t,notional_usd FROM liq_events ORDER BY symbol,t").fetchall()
    except Exception as e:
        return {}, "liq unreadable: %s" % e
    by = collections.defaultdict(collections.Counter)
    for s, t, nz in rows:
        if nz is None:
            continue
        by[s][int(t) // 3600000] += float(nz)
    out = {}
    for coin, h in by.items():
        if coin not in coins or len(h) < 100:
            continue
        vals = np.asarray(list(h.values()), float)
        thr = float(np.quantile(vals, EXTREME_Q))
        out[coin] = {k for k, v in h.items() if v >= thr}
    return out, "panels.liq_events"


# ------------------------------------------------------------------------------------ the statistic
def rates(bars, tails, hks, condsets, shift=False):
    """Per coin: P(tail | flagged) and P(tail | not flagged). Returns list of (coin, p1, p0, n1, n0)."""
    out = []
    for coin, tail in tails.items():
        cs = condsets if isinstance(condsets, set) else condsets.get(coin)
        if not cs:
            continue
        hk = hks[coin]
        flag = np.isin(hk, np.fromiter(cs, np.int64, len(cs)))
        if shift:
            # circular shift: keeps the marginal rate and the flag's own autocorrelation, breaks only
            # its alignment with the outcome. A placebo that is FREE to come out positive.
            flag = np.roll(flag, int(rng.integers(100, max(101, len(flag) - 100))))
        m = np.isfinite(tail)
        f, nf = flag & m, (~flag) & m
        if f.sum() < MIN_COND_HOURS or nf.sum() < MIN_COND_HOURS:
            continue
        out.append((coin, float(tail[f].mean()), float(tail[nf].mean()), int(f.sum()), int(nf.sum())))
    return out


def summarize(name, src, rs, placebo):
    if len(rs) < 3:
        print("  %-16s %-26s SKIPPED -- only %d coins reached the minimum" % (name, src, len(rs)))
        return {"condition": name, "source": src, "skipped": True, "coins": len(rs)}
    d = np.asarray([r[1] - r[2] for r in rs], float)          # per-coin difference in tail rate
    p1 = np.asarray([r[1] for r in rs], float)
    p0 = np.asarray([r[2] for r in rs], float)
    n1 = int(sum(r[3] for r in rs))
    n0 = int(sum(r[4] for r in rs))
    idx = rng.integers(0, len(d), size=(BOOT, len(d)))
    ms = d[idx].mean(axis=1)
    m, se = float(d.mean()), float(np.std(ms, ddof=1))
    lo, hi = float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5))
    z = m / se if se > 0 else float("nan")
    # pooled = event-weighted, printed beside the equal-weighted mean that governs
    pool1 = float(sum(r[1] * r[3] for r in rs) / max(n1, 1))
    pool0 = float(sum(r[2] * r[4] for r in rs) / max(n0, 1))
    pl = np.asarray([r[1] - r[2] for r in placebo], float) if len(placebo) >= 3 else np.array([])
    plm = float(pl.mean()) if len(pl) else float("nan")
    print("  %-16s %-26s coins %3d | P(tail) %.4f vs %.4f | lift %+.4f [%+.4f,%+.4f] z %6.2f"
          " | ratio %4.2fx | pooled %+.4f | placebo %+.4f"
          % (name, src, len(rs), float(p1.mean()), float(p0.mean()), m, lo, hi, z,
             (float(p1.mean()) / float(p0.mean()) if p0.mean() else float("nan")),
             pool1 - pool0, plm))
    return {"condition": name, "source": src, "coins": len(rs), "p_tail_flagged": float(p1.mean()),
            "p_tail_unflagged": float(p0.mean()), "lift": m, "ci": [lo, hi], "se": se, "z": z,
            "ratio": (float(p1.mean()) / float(p0.mean()) if p0.mean() else None),
            "pooled_lift": pool1 - pool0, "placebo_lift": plm,
            "hours_flagged": n1, "hours_unflagged": n0}


def mm_and_cap(coin):
    """Tier-1 maintenance margin and exchange cap. Tier 1 is the only tier a $5k account reaches."""
    r = TIERS.get(coin)
    if not r or not r.get("tiers"):
        return None, None
    lev = sorted(r["tiers"], key=lambda x: x["lower_usd"])[0]["max_lev"]
    return 1.0 / (2.0 * lev), float(lev)


def flagged_hours_for(cs, coin):
    """Condition sets come in two shapes and the leverage table must accept both.

    A MARKET-WIDE condition (btc_shock) is a single set of hours that applies to every coin; a
    per-coin condition is a dict. The first run returned n/a across the whole flagged column because
    the best-supported condition was the market-wide one and the lookup assumed a dict.
    """
    if isinstance(cs, set):
        return cs
    if isinstance(cs, dict):
        return cs.get(coin) or set()
    return set()


def main():
    print("M5 -- tail / cascade risk. EXPLORATORY, magnitude only, no card above HYPOTHESIS.")
    print("tail = |next 1h move| > %.0fx the live HAR expectation scaled to 1h.\n" % TAIL_MULT)
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    bars = load_1h(c)
    print("loaded %d coins of 1h bars" % len(bars))

    tails, hks = {}, {}
    for coin, b in bars.items():
        em = em_hourly(b)
        if em is None:
            continue
        ret = np.abs(b["c"][1:] / b["c"][:-1] - 1.0)
        t = np.full(len(b["c"]), np.nan)
        # condition at bar i, outcome at bar i+1: no peeking
        t[:-1] = np.where(np.isfinite(em[:-1]), (ret > TAIL_MULT * em[:-1]).astype(float), np.nan)
        tails[coin] = t
        hks[coin] = hour_key(b["t"])
    base = np.nanmean(np.concatenate([tails[k] for k in tails]))
    print("unconditional tail rate: %.4f (%d coins)\n" % (base, len(tails)))

    coins = set(tails)
    conds = []
    f, s = cond_funding(c, coins);                conds.append(("funding_extreme", s, f))
    b2, s = cond_btc_shock(bars);                 conds.append(("btc_shock", s, b2))
    o, s = cond_oi(coins);                        conds.append(("oi_jump", s, o))
    dp, s = cond_depth(c, coins);                 conds.append(("depth_thin", s, dp))
    lq, s = cond_liq(c, coins);                   conds.append(("liq_burst", s, lq))
    c.close()

    print("--- CONDITION LIFTS (equal-weighted over coins; pooled and placebo beside every row) ---")
    out = {"unconditional_tail_rate": float(base), "tail_mult": TAIL_MULT,
           "extreme_quantile": EXTREME_Q, "coins_1h": len(tails), "conditions": []}
    for name, src, cs in conds:
        if not cs:
            print("  %-16s %-26s NO DATA -- reported as absent, NOT as zero" % (name, src))
            out["conditions"].append({"condition": name, "source": src, "absent": True})
            continue
        rs = rates(bars, tails, hks, cs)
        pl = rates(bars, tails, hks, cs, shift=True)
        out["conditions"].append(summarize(name, src, rs, pl))

    print("\n--- WHICH CONDITIONS SHOULD CUT LEVERAGE ---")
    real = [r for r in out["conditions"] if not r.get("absent") and not r.get("skipped")]
    for r in sorted(real, key=lambda x: -(x["lift"] or 0)):
        surv = abs(r["lift"]) > 2.5 * abs(r["placebo_lift"] or 0) and abs(r["z"]) > 2.5
        agree = (r["lift"] > 0) == (r["pooled_lift"] > 0)
        verd = ("CUT LEVERAGE" if (surv and agree and r["lift"] > 0) else
                "not actionable" if agree else "SIGN DISAGREEMENT -- not actionable")
        print("  %-16s lift %+.4f (%.2fx baseline) z %6.2f placebo %+.4f -> %s"
              % (r["condition"], r["lift"], (r["ratio"] or float("nan")), r["z"],
                 r["placebo_lift"], verd))
        r["verdict"] = verd

    print("\n--- FAT-TAIL-AWARE LEVERAGE, real HL maintenance margin, flagged vs calm hours ---")
    print("  %-6s %6s %7s %7s | %9s %9s | %8s" % ("coin", "mm%", "HLcap", "p999_1h%",
                                                  "ceil_calm", "ceil_flag", "cut_to"))
    lev = []
    # Condition the table on the best-SUPPORTED condition (survives its placebo and agrees in sign),
    # not merely the largest lift -- liq_burst has the biggest lift and a placebo at 57% of it.
    ok_conds = [r for r in real if r.get("verdict") == "CUT LEVERAGE"]
    pick = max(ok_conds, key=lambda x: abs(x["z"])) if ok_conds else None
    cs = next((c3 for n, s, c3 in conds if n == (pick or {}).get("condition")), {})
    print("  conditioning the flagged column on: %s"
          % ((pick or {}).get("condition") or "nothing cleared its placebo"))
    for coin in ("BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"):
        if coin not in bars:
            continue
        mm, cap = mm_and_cap(coin)
        if mm is None:
            continue
        b = bars[coin]
        ret = np.abs(b["c"][1:] / b["c"][:-1] - 1.0)
        hk = hks[coin][1:]
        fh = flagged_hours_for(cs, coin)
        flag = (np.isin(hk, np.fromiter(fh, np.int64, len(fh))) if fh
                else np.zeros(len(ret), bool))
        p999 = float(np.quantile(ret, 0.999)) * 100
        calm = ret[~flag] if flag.any() else ret
        q_calm = float(np.quantile(calm, 0.999))
        # MIN_FLAG_HOURS was 200 and BTC's own shock hours number ~180 after the HAR warmup, so
        # the whole flagged column read n/a with no explanation. The count is now PRINTED, so an
        # n/a always says why rather than looking like "no effect".
        q_flag = (float(np.quantile(ret[flag], 0.999)) if flag.sum() >= 100 else float("nan"))
        ceil_calm = min(cap, 1.0 / (q_calm + mm))
        ceil_flag = min(cap, 1.0 / (q_flag + mm)) if np.isfinite(q_flag) else float("nan")
        lev.append({"coin": coin, "mm_frac": mm, "hl_cap": cap, "p999_1h_pct": p999,
                    "ceiling_calm": ceil_calm, "ceiling_flagged": ceil_flag,
                    "flagged_hours": int(flag.sum())})
        print("  %-6s %6.2f %6.0fx %7.2f | %8.1fx %8s | %7s  (flagged hrs %d)"
              % (coin, mm * 100, cap, p999, ceil_calm,
                 ("%.1fx" % ceil_flag) if np.isfinite(ceil_flag) else "n/a",
                 ("%.0f%%" % (100 * ceil_flag / ceil_calm)) if np.isfinite(ceil_flag) else "too few",
                 int(flag.sum())))
    out["leverage_table"] = lev
    out["leverage_condition"] = (pick or {}).get("condition")

    # ---------------------------------------------------------------------------------------------
    # The per-coin flagged column above is honestly unestimable: a market-wide BTC shock supplies only
    # ~90 hours inside 210 days, and the 0.999 quantile of 90 points IS the maximum. So the tail
    # inflation is estimated ONCE, POOLED across coins, on the move NORMALISED by that coin's own
    # expected hourly move -- which makes coins comparable and turns 90 hours x 177 coins into a
    # usable sample. The per-coin ceiling is then that coin's em times the pooled quantile.
    if pick and cs:
        zc, zf = [], []
        for coin, b in bars.items():
            em = em_hourly(b)
            if em is None:
                continue
            ret = np.abs(b["c"][1:] / b["c"][:-1] - 1.0)
            emv, hk = em[:-1], hks[coin][1:]
            fh = flagged_hours_for(cs, coin)
            if not fh:
                continue
            flag = np.isin(hk, np.fromiter(fh, np.int64, len(fh)))
            good = np.isfinite(emv) & np.isfinite(ret) & (emv > 0)
            z = ret[good] / emv[good]
            fl = flag[good]
            zf.append(z[fl])
            zc.append(z[~fl])
        zc = np.concatenate(zc) if zc else np.array([])
        zf = np.concatenate(zf) if zf else np.array([])
        if len(zf) > 2000 and len(zc) > 2000:
            qc = float(np.quantile(zc, 0.999))
            qf = float(np.quantile(zf, 0.999))
            print("\n--- POOLED TAIL INFLATION under %s (move normalised by the coin's own em) ---"
                  % pick["condition"])
            print("  calm   n %7d  p99.9 of |move|/em = %.2f" % (len(zc), qc))
            print("  flagged n %6d  p99.9 of |move|/em = %.2f   inflation %.2fx"
                  % (len(zf), qf, qf / qc if qc else float("nan")))
            print("\n  %-6s %7s | %9s %9s | %7s" % ("coin", "em_1h%", "ceil_calm", "ceil_flag",
                                                    "cut to"))
            lev2 = []
            for coin in ("BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"):
                if coin not in bars:
                    continue
                mm, cap = mm_and_cap(coin)
                em = em_hourly(bars[coin])
                if mm is None or em is None:
                    continue
                emm = float(np.nanmean(em))
                cc = min(cap, 1.0 / (emm * qc + mm))
                cf = min(cap, 1.0 / (emm * qf + mm))
                lev2.append({"coin": coin, "em_1h_pct": emm * 100, "ceiling_calm": cc,
                             "ceiling_flagged": cf, "cut_to_pct": 100 * cf / cc})
                print("  %-6s %7.3f | %8.1fx %8.1fx | %6.0f%%"
                      % (coin, emm * 100, cc, cf, 100 * cf / cc))
            out["pooled_tail_inflation"] = {"condition": pick["condition"], "q999_calm": qc,
                                            "q999_flagged": qf, "inflation": qf / qc if qc else None,
                                            "n_calm": int(len(zc)), "n_flagged": int(len(zf))}
            out["leverage_table_pooled"] = lev2

    io.open(os.path.join(HERE, "m5_tail_cascade.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1, default=float))
    print("\nwrote m5_tail_cascade.json")
    print("Coverage differs per condition BY DESIGN; a lift on 13 coins is not a lift on 178.")


if __name__ == "__main__":
    main()
