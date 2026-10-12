"""Runs PREREG_E2B_ABSRET_2026-10-12 (sealed da0cbf4a). Sibling of e2_tighten.py, which stays intact.

OUTCOME CHANGED, and that is the whole point: E2 measured R of the ORIGINAL risk, which a
stop-distance treatment biases mechanically (+0.4065 R measured, +0.1759 R on a driftless walk).
This measures ABSOLUTE return -- % of entry, net of 9 bps and realised funding -- which has no
stop-distance denominator.

The GBM control is therefore a test of the METRIC as well as the result: on a driftless walk,
moving a stop changes when you exit but not expected absolute return, so the no-edge median should
now be ~0. If it is not, the metric is still wrong and the arms are not reported (prereg criterion 6).

Owner's question: "our thesis was pretty right, but we seemed to get stopped out before it could
truly show?" -- does the exit engine's stop-tightening help or hurt?

Paired design: for each applied tighten_sl, replay forward from the tighten moment under the stop as
it was (KEEP) and the stop the engine set (TIGHTEN). Same path, same target, same cap. The pairing
is what makes 34 day-clusters usable.

Two things the prereg fixed before any outcome was replayed:
  * the before->after is ONLY in the `details` string -- these rows are logged post-application, so
    position_sl and new_sl both carry the NEW value, and comparing them says "83 of 86 were no-ops",
    which is false;
  * tightening a stop changes outcomes on a random walk DETERMINISTICALLY, so the driftless-GBM
    control is the primary validity check, not an afterthought.
"""
import collections
import datetime
import io
import json
import math
import os
import random
import re
import sqlite3
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
DEC = os.path.join(HERE, "server_exports", "exit_decisions.jsonl")
CAP_H = 96
Z_BAR = 1.96
MDE_FLOOR_R = 0.20
PAT = re.compile(r"SL\s+([0-9.]+)\s*->\s*([0-9.]+)")


def secs(t):
    if isinstance(t, (int, float)):
        return float(t) / 1000.0 if float(t) > 1e11 else float(t)
    try:
        return datetime.datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def load_events():
    out = []
    for line in io.open(DEC, encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("exit_action") != "tighten_sl" or d.get("applied") is not True:
            continue
        m = PAT.search(str(d.get("details") or ""))
        ent, ts = d.get("position_entry"), secs(d.get("ts"))
        tp2 = d.get("position_tp2")
        if not m or not isinstance(ent, (int, float)) or not ent or ts is None:
            continue
        old, new = float(m.group(1)), float(m.group(2))
        side = 1 if str(d.get("position_side", "")).upper().startswith("L") else -1
        # risk is measured against the ORIGINAL stop so both arms share one denominator
        risk = abs(ent - old)
        if risk <= 0:
            continue
        out.append({"sym": d.get("symbol"), "side": side, "ent": ent, "old": old, "new": new,
                    "tp2": tp2 if isinstance(tp2, (int, float)) else None, "ts": ts, "risk": risk,
                    "day": datetime.datetime.fromtimestamp(ts, datetime.UTC).date()})
    return out


def bars(c, sym, table):
    rows = c.execute("SELECT t,o,h,l,c FROM %s WHERE coin=? ORDER BY t" % table, (sym,)).fetchall()
    return [(secs(r[0]), r[1], r[2], r[3], r[4]) for r in rows]


def replay(ev, stop, series):
    """From the tighten moment to stop / tp2 / cap. Stop wins a tie inside a bar (pessimistic)."""
    s, t0 = ev["side"], ev["ts"]
    tp2, deadline = ev["tp2"], ev["ts"] + CAP_H * 3600
    last = None
    for (bt, _o, bh, bl, bc) in series:
        if bt < t0:
            continue
        if bt > deadline:
            break
        hit_stop = (bl <= stop) if s > 0 else (bh >= stop)
        hit_tp = tp2 is not None and ((bh >= tp2) if s > 0 else (bl <= tp2))
        if hit_stop:
            return stop, "stop"
        if hit_tp:
            return tp2, "tp2"
        last = bc
    return (last, "cap") if last is not None else (None, "no_bars")


FEE_PCT = 0.09          # 9 bps round trip, per the server's figure for the live bot


def outcome_R(ev, stop, series, fundfn=None):
    """ABSOLUTE return as % of entry, net of fee and (where available) realised funding.

    Name kept so the harness is otherwise identical to E2's; the quantity is not R.
    """
    px, why = replay(ev, stop, series)
    if px is None:
        return None, why
    gross = ev["side"] * (px - ev["ent"]) / ev["ent"] * 100.0
    fund = 0.0
    if fundfn is not None:
        fund = fundfn(ev, why)
    return gross - FEE_PCT - fund, why


def day_block(pairs, nrep=4000, seed=20261012):
    by = collections.defaultdict(list)
    for d, v in pairs:
        by[d].append(v)
    days = sorted(by)
    if len(days) < 3:
        return None
    eq = statistics.fmean([statistics.fmean(by[d]) for d in days])
    pooled = statistics.fmean([v for _, v in pairs])
    rng = random.Random(seed)
    boot = sorted(statistics.fmean([statistics.fmean(by[days[rng.randrange(len(days))]])
                                   for _ in days]) for _ in range(nrep))
    sd = statistics.pstdev(boot) or 1e-12
    return {"eq": eq, "pooled": pooled, "lo": boot[int(.025 * nrep)], "hi": boot[int(.975 * nrep)],
            "z": eq / sd, "ndays": len(days), "n": len(pairs), "by": by, "days": days}


def gbm(t0, px, sig, hours, rng, step=3600.0):
    out, p = [], px
    for i in range(hours):
        o = p
        p = o * math.exp(rng.gauss(0.0, sig))
        w1 = o * math.exp(rng.gauss(0.0, sig * 0.7))
        w2 = p * math.exp(rng.gauss(0.0, sig * 0.7))
        out.append((t0 + i * step, o, max(o, p, w1, w2), min(o, p, w1, w2), p))
    return out


def realised_vol(series, t0, n=480):
    past = [b for b in series if b[0] < t0][-n - 1:]
    r = [math.log(b[4] / a[4]) for a, b in zip(past, past[1:]) if a[4] and b[4] and a[4] > 0]
    return statistics.pstdev(r) if len(r) >= 50 else None


def main():
    evs = load_events()
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    syms = sorted({e["sym"] for e in evs})
    h1 = {s: bars(c, s, "candles_1h") for s in syms}
    m5 = {s: bars(c, s, "candles_5m") for s in syms}
    for e in evs:
        f5 = m5[e["sym"]][0][0] if m5[e["sym"]] else None
        e["series"] = m5[e["sym"]] if (f5 and e["ts"] >= f5) else h1[e["sym"]]
        e["res"] = "5m" if (f5 and e["ts"] >= f5) else "1h"
        e["sig"] = realised_vol(h1[e["sym"]], e["ts"])
    print("applied tighten events: %d | %d days | bars: 5m %d, 1h %d"
          % (len(evs), len({e["day"] for e in evs}),
             sum(1 for e in evs if e["res"] == "5m"), sum(1 for e in evs if e["res"] == "1h")))

    pairs, why_k, why_t, used = [], collections.Counter(), collections.Counter(), []
    for e in evs:
        rk, wk = outcome_R(e, e["old"], e["series"])
        rt, wt = outcome_R(e, e["new"], e["series"])
        if rk is None or rt is None:
            continue
        why_k[wk] += 1
        why_t[wt] += 1
        pairs.append((e["day"], rt - rk))
        used.append(e)
    print("replayed pairs: %d" % len(pairs))
    print("  KEEP    ended: %s" % dict(why_k.most_common()))
    print("  TIGHTEN ended: %s" % dict(why_t.most_common()))

    s = day_block(pairs)
    print("\n--- PRIMARY: TIGHTEN - KEEP, in R of the original risk ---")
    print("  equal-weighted day mean %+.4f R   CI95 [%+.4f, %+.4f]   z %+.2f   days %d"
          % (s["eq"], s["lo"], s["hi"], s["z"], s["ndays"]))
    print("  pooled per-event        %+.4f R   -> signs %s"
          % (s["pooled"], "AGREE" if (s["pooled"] > 0) == (s["eq"] > 0) else "DISAGREE"))
    print("  CI excludes zero: %s   (bar |z| > %.2f)"
          % ("YES" if (s["lo"] > 0 or s["hi"] < 0) else "NO", Z_BAR))

    mid = s["days"][len(s["days"]) // 2]
    a = day_block([(d, v) for d, v in pairs if d < mid])
    b = day_block([(d, v) for d, v in pairs if d >= mid])
    if a and b:
        print("  walk-forward halves: %+.4f / %+.4f -> %s"
              % (a["eq"], b["eq"], "SIGN-STABLE" if (a["eq"] > 0) == (b["eq"] > 0) else "FLIPS"))

    print("\n--- GBM NO-EDGE CONTROL (the primary validity check) ---")
    rng = random.Random(20261012)
    sims = []
    for _ in range(300):
        pp = []
        for e in used:
            if not e["sig"]:
                continue
            g = gbm(e["ts"], e["ent"], e["sig"], CAP_H + 2, rng)
            rk, _ = outcome_R(e, e["old"], g)
            rt, _ = outcome_R(e, e["new"], g)
            if rk is not None and rt is not None:
                pp.append((e["day"], rt - rk))
        if pp:
            by = collections.defaultdict(list)
            for d, v in pp:
                by[d].append(v)
            sims.append(statistics.fmean([statistics.fmean(v) for v in by.values()]))
    sims.sort()
    lo, hi = sims[int(.025 * len(sims))], sims[int(.975 * len(sims))]
    print("  no-edge worlds (n=%d): median %+.4f R  95%% spread [%+.4f, %+.4f]"
          % (len(sims), statistics.median(sims), lo, hi))
    inside = lo <= s["eq"] <= hi
    print("  measured %+.4f R is %s the no-edge spread -> %s"
          % (s["eq"], "INSIDE" if inside else "OUTSIDE",
             "NO FINDING: this is arithmetic, not skill" if inside
             else "survives the mechanical explanation"))

    print("\n--- MDE (simulated, 80%% power at z %.2f) ---" % Z_BAR)
    dm = [statistics.fmean(v) for v in s["by"].values()]
    centred = [x - statistics.fmean(dm) for x in dm]
    r2 = random.Random(11)
    mde = None
    for e_bps in range(1, 201):
        eff = e_bps / 100.0
        hits = 0
        for _ in range(500):
            draw = [centred[r2.randrange(len(centred))] + eff for _ in centred]
            se = statistics.pstdev(draw) / (len(draw) ** 0.5) or 1e-12
            if abs(statistics.fmean(draw) / se) > Z_BAR:
                hits += 1
        if hits / 500 >= 0.80:
            mde = eff
            break
    print("  MDE %s R | pre-committed floor %.2f R -> %s"
          % ("%.2f" % mde if mde else ">2.00", MDE_FLOOR_R,
             "UNDERPOWERED by the pre-commitment" if (mde is None or mde > MDE_FLOOR_R)
             else "powered for the prior effect size"))


if __name__ == "__main__":
    main()
