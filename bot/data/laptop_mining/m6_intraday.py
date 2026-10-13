"""M6 -- INTRADAY MAGNITUDE SEASONALITY. EXPLORATORY. Prereg only what survives the held-out coins.

MISSION: "Hour-of-day / weekday / funding-hour (00/08/16 UTC) |return| profiles per coin; does stop-hit
probability depend on entry hour HOLDING exp_move FIXED? (stop placement + entry timing, not
direction). EXPLORATORY first, prereg only what survives the held-out coins."

WHY THIS ONE MATTERS MORE THAN ITS PRIORITY SUGGESTS. M5 built its tail rates on
    expected 1h move = daily HAR forecast / sqrt(24)
which ASSUMES the day has no intraday shape. If this file finds one, M5's tail rates are hour-dependent
and its limits section says so already. So M6 is partly a check on M5's instrument, not just a new
question.

THE QUANTITY, so that "holding exp_move fixed" is actually true: everything is measured on
    z = |1h return| / (daily em / sqrt(24))
i.e. the realised move DIVIDED BY the forecast for that day. The daily forecast is therefore divided
out of every number here by construction. If there is no intraday shape, mean z is FLAT across hours.
Any deviation is shape the live daily model cannot express.

PLACEBO THAT CAN FAIL -- and it had to be designed differently from M5's. M5 circularly shifted the
condition series, but for an hour-of-day effect a shift by a multiple of 24 preserves the hour labels
exactly, so that placebo would be inert here. Instead each coin's RETURN series is rotated by a random
offset that is NOT a multiple of 24, which keeps the series' autocorrelation and marginal distribution
and destroys only its alignment with the clock. A real session effect must survive it.

HELD-OUT, per the mission: the hourly profile is built on ORIG17 and then checked against NEW156, and
the test is whether the SHAPE agrees (correlation across the 24 hours), not whether each group shows
something. A shape that does not replicate is not a shape.

EXPLORATORY: no card above HYPOTHESIS, no live change, magnitude only -- nothing here says which way to
trade, only when price travels further against a stop.
"""
import collections
import datetime
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
HOURS = 24
HOURS_PER_DAY = 24.0
FUNDING_HOURS = (0, 8, 16)
K_STOP = 1.65          # the live stop multiple, on the DAILY expected move
HOLD_H = 24            # a one-day hold, so every entry hour sees the same amount of clock
BOOT = 4000
MIN_BARS = 1500
rng = np.random.default_rng(20261013)

ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}

CO = json.load(io.open(os.path.join(HERE, "volatility_forecast.json"), encoding="utf-8"))
Y1B, Y1S = CO["y1_beta"], CO["y1_smearing"]


def sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def load_1h(c):
    out = {}
    cur, buf = None, []
    for coin, t, h, l, cl in c.execute("SELECT coin,t,h,l,c FROM candles_1h ORDER BY coin,t"):
        if coin != cur:
            if cur and len(buf) >= MIN_BARS:
                a = np.asarray(buf, float)
                out[cur] = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
            cur, buf = coin, []
        buf.append((t, h, l, cl))
    if cur and len(buf) >= MIN_BARS:
        a = np.asarray(buf, float)
        out[cur] = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
    return out


def daily_em(b):
    """Live daily HAR forecast (fraction) per 1h bar, plus the day index."""
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
    return em[np.searchsorted(uniq, day)] / 100.0, day


def profile(bars, key_fn, nkeys, rotate=False):
    """Per coin: mean z = |1h move| / (daily em / sqrt 24), bucketed by key. Returns {coin: array}."""
    out = {}
    for coin, b in bars.items():
        em, _ = daily_em(b)
        if em is None:
            continue
        ret = np.abs(b["c"][1:] / b["c"][:-1] - 1.0)
        emv = em[:-1]
        keys = key_fn(b["t"][1:])
        good = np.isfinite(ret) & np.isfinite(emv) & (emv > 0)
        if good.sum() < 500:
            continue
        r, k = ret[good], keys[good]
        e = emv[good] / math.sqrt(HOURS_PER_DAY)
        if rotate:
            # rotate the RETURN series against the clock by an offset that is NOT a multiple of 24,
            # so the hour labels genuinely move. A multiple of 24 would leave the profile untouched
            # and the placebo would be inert -- which is why M5's shift could not be reused here.
            off = int(rng.integers(1, HOURS))
            while off % HOURS == 0:
                off = int(rng.integers(1, HOURS))
            off += int(rng.integers(0, len(r) // HOURS)) * HOURS + off
            r = np.roll(r, off)
            e = np.roll(e, off)
        z = r / e
        m = np.full(nkeys, np.nan)
        for j in range(nkeys):
            sel = k == j
            if sel.sum() >= 20:
                m[j] = float(np.mean(z[sel]))
        if np.isfinite(m).sum() == nkeys:
            out[coin] = m
    return out


def eqmean(prof, coins):
    a = np.asarray([prof[c] for c in coins if c in prof], float)
    return (a.mean(axis=0), a) if len(a) else (None, None)


def boot_band(a):
    """Bootstrap over COINS; returns (lo, hi) per bucket."""
    idx = rng.integers(0, len(a), size=(BOOT, len(a)))
    ms = a[idx].mean(axis=1)
    return np.percentile(ms, 2.5, axis=0), np.percentile(ms, 97.5, axis=0)


def stop_hit_by_hour(bars):
    """P(stop at K x daily em is hit within 24h) by ENTRY HOUR, both-sided, em held fixed."""
    out = {}
    for coin, b in bars.items():
        em, _ = daily_em(b)
        if em is None:
            continue
        n = len(b["c"])
        hrs = ((b["t"] // 3600000) % HOURS).astype(int)
        ok = np.flatnonzero(np.isfinite(em[:n - HOLD_H - 1]))
        ok = ok[ok > 30]
        if len(ok) < 500:
            continue
        side = np.where(rng.random(len(ok)) < 0.5, 1.0, -1.0)
        pidx = ok[:, None] + np.arange(1, HOLD_H + 1)[None, :]
        entry = b["c"][ok]
        H, L = b["h"][pidx], b["l"][pidx]
        adv = np.where(side[:, None] > 0, (entry[:, None] - L) / entry[:, None],
                       (H - entry[:, None]) / entry[:, None])
        stop = K_STOP * em[ok]
        hit = (adv >= stop[:, None]).any(axis=1)
        hh = hrs[ok]
        m = np.full(HOURS, np.nan)
        for j in range(HOURS):
            sel = hh == j
            if sel.sum() >= 20:
                m[j] = float(hit[sel].mean())
        if np.isfinite(m).sum() == HOURS:
            out[coin] = m
    return out


def main():
    print("M6 -- intraday magnitude seasonality. EXPLORATORY, magnitude only.")
    print("every number is z = |1h move| / (daily em / sqrt 24), so the DAILY forecast is divided out.")
    print("flat z across hours == no intraday shape == M5's sqrt(24) assumption holds.\n")
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    _snap = panel_snapshot.stamp(c)
    print("SOURCE SNAPSHOT: %s" % panel_snapshot.describe(_snap))
    bars = load_1h(c)
    c.close()
    print("coins with >= %d 1h bars: %d" % (MIN_BARS, len(bars)))

    hour_of = lambda t: ((np.asarray(t, np.int64) // 3600000) % HOURS).astype(int)
    dow_of = lambda t: ((np.asarray(t, np.int64) // 86400000 + 4) % 7).astype(int)   # epoch = Thursday

    ph = profile(bars, hour_of, HOURS)
    ph_pl = profile(bars, hour_of, HOURS, rotate=True)
    pd_ = profile(bars, dow_of, 7)
    print("coins contributing a complete 24h profile: %d\n" % len(ph))

    o17 = [x for x in ph if x in ORIG17]
    new = [x for x in ph if x not in ORIG17]
    all_m, all_a = eqmean(ph, list(ph))
    o_m, _ = eqmean(ph, o17)
    n_m, _ = eqmean(ph, new)
    pl_m, pl_a = eqmean(ph_pl, list(ph_pl))
    lo, hi = boot_band(all_a)

    print("--- HOUR-OF-DAY PROFILE (z; 1.00 = exactly the daily forecast's implied hourly move) ---")
    print("  %3s %7s %17s %8s %8s %9s" % ("UTC", "z", "95% CI", "ORIG17", "NEW", "placebo"))
    for j in range(HOURS):
        star = "  <-- funding hour" if j in FUNDING_HOURS else ""
        print("  %02dh %7.3f  [%.3f,%.3f] %8.3f %8.3f %9.3f%s"
              % (j, all_m[j], lo[j], hi[j], o_m[j], n_m[j], pl_m[j], star))

    spread = float(np.nanmax(all_m) - np.nanmin(all_m))
    pl_spread = float(np.nanmax(pl_m) - np.nanmin(pl_m))
    shape_r = float(np.corrcoef(o_m, n_m)[0, 1])
    print("\n  peak %02dh %.3f | trough %02dh %.3f | SPREAD %.3f  (placebo spread %.3f)"
          % (int(np.nanargmax(all_m)), np.nanmax(all_m), int(np.nanargmin(all_m)),
             np.nanmin(all_m), spread, pl_spread))
    print("  HELD-OUT SHAPE TEST: corr(ORIG17 profile, NEW profile) over 24 hours = %+.3f"
          % shape_r)
    fh = [all_m[j] for j in FUNDING_HOURS]
    nfh = [all_m[j] for j in range(HOURS) if j not in FUNDING_HOURS]
    print("  funding hours (00/08/16) mean z %.3f vs other hours %.3f  -> %+.1f%%"
          % (np.mean(fh), np.mean(nfh), 100 * (np.mean(fh) / np.mean(nfh) - 1)))

    dall, da = eqmean(pd_, list(pd_))
    names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    print("\n--- WEEKDAY PROFILE (z) ---")
    print("  " + " ".join("%s %.3f" % (names[j], dall[j]) for j in range(7)))
    print("  spread %.3f" % float(np.nanmax(dall) - np.nanmin(dall)))

    sh = stop_hit_by_hour(bars)
    s_all, s_a = eqmean(sh, list(sh))
    s_o, _ = eqmean(sh, [x for x in sh if x in ORIG17])
    s_n, _ = eqmean(sh, [x for x in sh if x not in ORIG17])
    slo, shi = boot_band(s_a)
    print("\n--- P(stop hit within %dh) BY ENTRY HOUR, stop = %.2f x DAILY em, %d coins ---"
          % (HOLD_H, K_STOP, len(sh)))
    print("  %3s %8s %17s %8s %8s" % ("UTC", "P(stop)", "95% CI", "ORIG17", "NEW"))
    for j in range(HOURS):
        print("  %02dh %8.4f  [%.4f,%.4f] %8.4f %8.4f"
              % (j, s_all[j], slo[j], shi[j], s_o[j], s_n[j]))
    s_spread = float(np.nanmax(s_all) - np.nanmin(s_all))
    s_r = float(np.corrcoef(s_o, s_n)[0, 1])
    print("\n  worst entry hour %02dh %.4f | best %02dh %.4f | SPREAD %.4f (%.1f%% relative)"
          % (int(np.nanargmax(s_all)), np.nanmax(s_all), int(np.nanargmin(s_all)),
             np.nanmin(s_all), s_spread, 100 * s_spread / float(np.nanmean(s_all))))
    print("  HELD-OUT SHAPE TEST: corr(ORIG17, NEW) over 24 hours = %+.3f" % s_r)

    print("\n--- WHAT THIS DOES TO M5 ---")
    if spread > 3 * pl_spread and shape_r > 0.5:
        print("  There IS an intraday shape and it replicates. M5's expected-1h-move = daily/sqrt(24)")
        print("  is therefore WRONG BY UP TO %.0f%% depending on the hour, so M5's tail rates are"
              % (100 * spread / float(np.nanmean(all_m))))
        print("  hour-dependent and its 4.16%% unconditional rate is an average over a real shape.")
    else:
        print("  No replicating intraday shape beyond the placebo: M5's sqrt(24) scaling stands.")

    io.open(os.path.join(HERE, "m6_intraday.json"), "w", encoding="utf-8").write(json.dumps({
        "source_snapshot": _snap,
        "coins": len(ph), "hour_profile": all_m.tolist(), "ci_lo": lo.tolist(), "ci_hi": hi.tolist(),
        "orig17_profile": o_m.tolist(), "new_profile": n_m.tolist(),
        "placebo_profile": pl_m.tolist(), "spread": spread, "placebo_spread": pl_spread,
        "shape_corr_heldout": shape_r, "weekday_profile": dall.tolist(),
        "funding_hour_ratio": float(np.mean(fh) / np.mean(nfh)),
        "stop_hit_by_hour": s_all.tolist(), "stop_hit_ci_lo": slo.tolist(),
        "stop_hit_ci_hi": shi.tolist(), "stop_hit_orig17": s_o.tolist(),
        "stop_hit_new": s_n.tolist(), "stop_hit_spread": s_spread,
        "stop_hit_shape_corr_heldout": s_r, "stop_coins": len(sh),
    }, indent=1, default=float))
    print("\nwrote m6_intraday.json")


if __name__ == "__main__":
    main()
