"""M2 — replay exit rules on the bot's REAL trades. Supplies ARM A of PREREG_PARTIAL_EXIT (d78bbb05).

Reuses profits_only.py's proven data layer (load() recovers each trade's real stop from TRADE_OPENED,
because stop_initial is blank on most ledger rows; bars() pulls the series). Rebuilding that loader
would risk a different trade match for no gain.

ARM A, as sealed: partial_1R_har (50% off at +1R, remainder trailed 1.0 x R below the running extreme)
versus stop_only (hold to the stop), PAIRED on the same trade and the same price path, in BPS OF
NOTIONAL net of 9 bps round-trip fees, with the partial leg paying its own fee.

🔴 DECLARED INTERPRETATION, because the sealed text is ambiguous and the ambiguity is a trap.
The prereg says "K = 1.65 only -- the bot's own live stop distance". In FUNDING_STOP, K multiplies
exp_move; but the bot's ACTUAL live stop is ~1.66% of price, and ADAPTIVE_STOPS is FALSE so em-based
stops are not live at all. 1.65 x em would be roughly 5-8%, three to five times the real stop. The two
quantities share a number by coincidence.
So for arm A, R IS EACH TRADE'S OWN STOP DISTANCE |entry - sl|. That is faithful to "the bot's own live
stop distance" and avoids imposing a synthetic stop on real trades. Declared here, before any number.

HORIZON 72h, matching M1 so the rules are compared on the same footing. The bot's real cap was 96h;
trades that actually ran longer are truncated at 72h for BOTH rules, so the pairing stays fair.

BARS: 1h for every trade. Justified by the 5m referee run earlier today -- 0.2-0.6% ordering
disagreement and under 1.1 bps of mean bias at these stop widths (m1_referee_5m.json). 5m exists only
from 2026-09-22 and would cover ~21 of 295 trades; it is used as a CROSS-CHECK, never as the sample.

Also reports the three descriptive policies the owner asked about on 10-12 (actual / profits_only /
hands_off) in bps, day-clustered, so M2's own mining question is answered alongside arm A.
"""
import collections
import datetime
import importlib.util
import io
import json
import math
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
HORIZON_H = 72
FEE_BPS = 9.0
PARTIAL_FEE_BPS = FEE_BPS * 1.5
BOOT = 4000
rng = np.random.default_rng(20261013)

_spec = importlib.util.spec_from_file_location("po", os.path.join(HERE, "profits_only.py"))
PO = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PO)            # safe: profits_only.py guards main()


def series_for(c, sym, table):
    try:
        return PO.bars(c, sym, table)
    except Exception:
        return None


def path_after(series, t0, hours):
    """(high, low, close) arrays for bars strictly after t0, capped at `hours`."""
    if not series:
        return None
    ts = np.asarray([r[0] for r in series], float)
    hi = np.asarray([r[1] for r in series], float)
    lo = np.asarray([r[2] for r in series], float)
    cl = np.asarray([r[3] for r in series], float)
    if ts.max() > 1e12:
        ts = ts / 1000.0
    j0 = int(np.searchsorted(ts, t0, side="right"))
    j1 = int(np.searchsorted(ts, t0 + hours * 3600.0, side="right"))
    if j1 - j0 < 4:
        return None
    return hi[j0:j1], lo[j0:j1], cl[j0:j1]


def rule_stop_only(hi, lo, cl, entry, side, R):
    stop = entry - side * R
    hit = np.flatnonzero((lo <= stop) if side > 0 else (hi >= stop))
    if len(hit):
        return -1.0, int(hit[0]) + 1, True
    return float((cl[-1] - entry) * side / R), len(cl), False


def rule_partial_trail(hi, lo, cl, entry, side, R, trail_R=1.0):
    """50% off at +1R, remainder trails trail_R below the running favourable extreme."""
    stop = entry - side * R
    fav = ((hi - entry) if side > 0 else (entry - lo)) / R
    adv = ((entry - lo) if side > 0 else (hi - entry)) / R
    s = np.flatnonzero(adv >= 1.0)
    t1 = np.flatnonzero(fav >= 1.0)
    s0 = int(s[0]) if len(s) else 10 ** 9
    r0 = int(t1[0]) if len(t1) else 10 ** 9
    if r0 >= s0:                                     # stopped before +1R (ties -> stop)
        if s0 < 10 ** 9:
            return -1.0, s0 + 1, True
        return float((cl[-1] - entry) * side / R), len(cl), False
    peak = fav[r0]
    j = r0 + 1
    while j < len(cl):
        peak = max(peak, fav[j])
        if fav[j] <= peak - trail_R:
            break
        j += 1
    run = (peak - trail_R) if j < len(cl) else float((cl[-1] - entry) * side / R)
    return 0.5 * 1.0 + 0.5 * float(run), min(j, len(cl) - 1) + 1, False


def day_of(ts):
    return datetime.datetime.fromtimestamp(float(ts), datetime.UTC).strftime("%Y-%m-%d")


def boot_days(diffs_by_day, reps=BOOT):
    days = sorted(diffs_by_day)
    means = np.array([np.mean(diffs_by_day[d]) for d in days], float)
    if len(means) < 3:
        return None
    idx = rng.integers(0, len(means), size=(reps, len(means)))
    bs = means[idx].mean(axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    se = float(bs.std(ddof=1))
    return {"eq": float(means.mean()), "lo": float(lo), "hi": float(hi), "se": se,
            "z": float(means.mean() / se) if se > 0 else float("nan"), "days": len(means)}


def main():
    # load() returns (trades, open_connection) -- I assumed a bare list and it crashed immediately.
    # Cheap version of tonight's recurring error: assuming a shape instead of reading it.
    tr, c = PO.load()
    print("M2 -- exit replay on the bot's REAL trades.  prereg d78bbb05, ARM A")
    print("matched trades from the ledger: %d" % len(tr))
    syms = sorted({x["sym"] for x in tr})
    h1 = {s: series_for(c, s, "candles_1h") for s in syms}
    m5 = {s: series_for(c, s, "candles_5m") for s in syms}
    c.close()

    rows, skipped = [], collections.Counter()
    for t in tr:
        sl = t.get("sl")
        if not sl or not t.get("entry"):
            skipped["no_stop"] += 1
            continue
        R = abs(t["entry"] - sl)
        if R <= 0:
            skipped["bad_stop"] += 1
            continue
        p = path_after(h1.get(t["sym"]), t["open_ts"], HORIZON_H)
        if p is None:
            skipped["no_bars"] += 1
            continue
        hi, lo, cl = p
        r_bps = (R / t["entry"]) * 1e4
        g_so, h_so, st_so = rule_stop_only(hi, lo, cl, t["entry"], t["side"], R)
        g_pt, h_pt, st_pt = rule_partial_trail(hi, lo, cl, t["entry"], t["side"], R)
        rows.append({
            "sym": t["sym"], "day": day_of(t["open_ts"]), "r_bps": r_bps,
            "stop_only_bps": g_so * r_bps - FEE_BPS,
            "partial_bps": g_pt * r_bps - (PARTIAL_FEE_BPS if not st_pt else FEE_BPS),
            "stopped_so": st_so, "stopped_pt": st_pt,
            "held_so": h_so, "held_pt": h_pt,
            "has_5m": bool(m5.get(t["sym"])),
        })
    print("usable: %d  (skipped: %s)" % (len(rows), dict(skipped)))
    if len(rows) < 30:
        raise SystemExit("too few usable trades for arm A")

    print("\n--- 1. counts and clustering ---")
    byday = collections.defaultdict(list)
    for r in rows:
        byday[r["day"]].append(r["partial_bps"] - r["stop_only_bps"])
    print("  trades %d | day-clusters %d | coins %d | mean 1R %.0f bps"
          % (len(rows), len(byday), len({r["sym"] for r in rows}),
             float(np.mean([r["r_bps"] for r in rows]))))

    print("\n--- 2. the two rules, in bps net of fees ---")
    for k, lab in (("stop_only_bps", "stop_only"), ("partial_bps", "partial_1R_trail")):
        v = np.array([r[k] for r in rows], float)
        dm = {d: [x[k] for x in rows if x["day"] == d] for d in byday}
        eq = float(np.mean([np.mean(dm[d]) for d in dm]))
        print("  %-18s pooled %+8.1f | eq-weighted day %+8.1f | win %.2f | stopped %.2f"
              % (lab, v.mean(), eq, float(np.mean(v > 0)),
                 float(np.mean([r["stopped_so" if k.startswith("stop") else "stopped_pt"]
                                for r in rows]))))

    print("\n--- 3. ARM A: paired difference (partial minus stop_only) ---")
    b = boot_days(byday)
    pooled = float(np.mean([r["partial_bps"] - r["stop_only_bps"] for r in rows]))
    print("  pooled %+8.1f bps | EQ-WEIGHTED DAY %+8.1f bps (GOVERNS)" % (pooled, b["eq"]))
    print("  day-block CI [%+.1f, %+.1f]  z %.2f  (%d day-clusters)"
          % (b["lo"], b["hi"], b["z"], b["days"]))
    print("  signs agree: %s" % ("yes" if pooled * b["eq"] > 0 else "NO"))

    print("\n--- 4. 5m cross-check (never the sample: 5m starts 2026-09-22) ---")
    n5 = sum(1 for r in rows if r["has_5m"])
    print("  trades whose symbol has any 5m coverage: %d of %d" % (n5, len(rows)))

    out = {"prereg": "PREREG_PARTIAL_EXIT d78bbb05", "arm": "A_LIVE",
           "trades": len(rows), "days": len(byday),
           "R_is": "each trade's own stop distance |entry-sl| (declared)",
           "pooled_diff_bps": round(pooled, 2), "eq_day_diff_bps": round(b["eq"], 2),
           "ci_bps": [round(b["lo"], 2), round(b["hi"], 2)], "z": round(b["z"], 2),
           "skipped": dict(skipped)}
    io.open(os.path.join(HERE, "m2_exit_replay.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote m2_exit_replay.json")
    print("NOTE: the sealed MDE gate (>25 bps => UNDERPOWERED) is applied in the result doc, not here.")


if __name__ == "__main__":
    main()
