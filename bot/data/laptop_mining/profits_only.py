"""Mining job: replay the bot's live trades under three exit policies. DESCRIPTIVE, not a verdict.

Owner, verbatim: "there's not really a point in changing the others, but looking under them under
data mining could be useful just like everything else we are data mining." So this is exploration,
not a decision input, and nothing here is preregistered.

Policies:
  (a) actual       -- what the bot did (from the ledger)
  (b) profits_only -- stop never moved, no early AI close, partial legs capped at 50% of size,
                      ends at the ORIGINAL stop / tp2 / the hold cap
  (c) hands_off    -- original stop / tp2 / hold cap only, no partials at all

THE BIAS RUNS THE OTHER WAY THIS TIME, which is why this is worth running when E2 and E2b were not.

E2 compared a TIGHTENED stop against the original and measured in R of the original risk. The
tightened arm's loss is arithmetically capped at a fraction of that denominator, so the mechanical
bias FAVOURED the thing being tested, and a +0.41R result at z 4.69 turned out to be the denominator.

Here the tightened arm is (a), the STATUS QUO. Policy (b)/(c) hold the original, wider stop and so
eat full-size losses. **So the geometry bias favours the status quo, and if profits_only wins it
wins against the bias.** That is a much stronger position than E2 ever had -- but it is only a
position, not a licence: the GBM no-edge control still runs FIRST, before any arm is read, exactly
as the server asked.
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
LEDGER = os.path.join(HERE, "server_exports", "trade_ledger.csv")
DEC = os.path.join(HERE, "server_exports", "exit_decisions.jsonl")
FEE_PCT = 0.09
CAP_H = 96
PARTIAL_CAP = 0.50


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def secs(t):
    if isinstance(t, (int, float)):
        return float(t) / 1000.0 if float(t) > 1e11 else float(t)
    try:
        return datetime.datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def bars(c, sym, table):
    r = c.execute("SELECT t,o,h,l,c FROM %s WHERE coin=? ORDER BY t" % table, (sym,)).fetchall()
    return [(secs(x[0]), x[1], x[2], x[3], x[4]) for x in r]


def load():
    import csv
    led = []
    for r in csv.DictReader(io.open(LEDGER, newline="", encoding="utf-8")):
        e, ts, hold = num(r.get("entry_price")), num(r.get("timestamp")), num(r.get("hold_hours"))
        if e is None or ts is None:
            continue
        side = (r.get("side") or "").upper()
        led.append({"sym": (r.get("symbol") or "").upper(),
                    "side": 1 if side.startswith(("L", "B")) else -1,
                    "entry": e, "open_ts": ts - (hold or 0) * 3600.0, "close_ts": ts,
                    "exit": num(r.get("exit_price")), "gross": num(r.get("gross_pnl")),
                    "exit_type": (r.get("exit_type") or "").upper()})
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    opens = collections.defaultdict(list)
    for ts, sym, body in c.execute("SELECT ts, sym, body FROM bulk_rows "
                                   "WHERE stream='trade_events' AND kind='TRADE_OPENED'"):
        d = json.loads(body)
        e, sl = num(d.get("entry")), num(d.get("sl"))
        if not e or not sl or e <= 0:
            continue
        sd = (d.get("side") or "").upper()
        opens[((d.get("symbol") or sym or "").upper(),
               1 if sd.startswith(("L", "B")) else -1)].append(
                   {"ts": secs(ts), "entry": e, "sl": sl,
                    "tp1": num(d.get("tp1")), "tp2": num(d.get("tp2"))})
    out = []
    for t in led:
        best, bd = None, None
        for o in opens.get((t["sym"], t["side"]), ()):
            if o["ts"] is None or abs(o["entry"] - t["entry"]) / t["entry"] > 5e-4:
                continue
            dt = abs(o["ts"] - t["open_ts"])
            if bd is None or dt < bd:
                best, bd = o, dt
        if best and bd <= 6 * 3600:
            t.update(sl=best["sl"], tp1=best["tp1"], tp2=best["tp2"])
            out.append(t)
    # actual partial legs, for policy (b)
    pat = re.compile(r"([0-9.]+)\s*%")
    parts = collections.defaultdict(list)
    if os.path.exists(DEC):
        for line in io.open(DEC, encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("exit_action") != "partial" or d.get("applied") is not True:
                continue
            ts, ent = secs(d.get("ts")), d.get("position_entry")
            if ts is None or not isinstance(ent, (int, float)):
                continue
            parts[(d.get("symbol"), round(ent, 6))].append(ts)
    for t in out:
        t["partial_ts"] = sorted(parts.get((t["sym"], round(t["entry"], 6)), []))
    return out, c


def walk(t, stop, series, upto=None, tp=None):
    """First touch wins; stop wins a tie (pessimistic). Returns (exit_px, why)."""
    s, e = t["side"], t["entry"]
    tp = tp if tp is not None else t.get("tp2")
    deadline = min(x for x in (t["open_ts"] + CAP_H * 3600, upto) if x is not None)
    last = None
    for (bt, _o, bh, bl, bc) in series:
        if bt < t["open_ts"]:
            continue
        if bt > deadline:
            break
        if (bl <= stop) if s > 0 else (bh >= stop):
            return stop, "stop"
        if tp is not None and ((bh >= tp) if s > 0 else (bl <= tp)):
            return tp, "tp2"
        last = bc
    return (last, "cap") if last is not None else (e, "nobars")


def pol_return(t, series, policy):
    """Return (% of notional net of fee, R of original risk, why)."""
    e, s = t["entry"], t["side"]
    risk = abs(e - t["sl"])
    if risk <= 0:
        return None
    if policy == "actual":
        px = t["exit"]
        if px is None:
            return None
        why = t["exit_type"]
        gross = s * (px - e) / e * 100.0
    else:
        px, why = walk(t, t["sl"], series)
        if px is None:
            return None
        gross = s * (px - e) / e * 100.0
        if policy == "profits_only" and t["partial_ts"]:
            # the real partial legs, capped at 50% of size in total
            legs = t["partial_ts"][:2]
            frac = min(PARTIAL_CAP, 0.25 * len(legs))
            tot = 0.0
            for pts in legs:
                ppx, _ = walk(t, t["sl"], series, upto=pts)
                if ppx is not None:
                    tot += s * (ppx - e) / e * 100.0 * (frac / len(legs))
            gross = tot + gross * (1.0 - frac)
    net = gross - FEE_PCT
    return net, net / (risk / e * 100.0), why


def gbm(t0, px, sig, hours, rng):
    out, p = [], px
    for i in range(hours):
        o = p
        p = o * math.exp(rng.gauss(0.0, sig))
        w1 = o * math.exp(rng.gauss(0.0, sig * 0.7))
        w2 = p * math.exp(rng.gauss(0.0, sig * 0.7))
        out.append((t0 + i * 3600.0, o, max(o, p, w1, w2), min(o, p, w1, w2), p))
    return out


def rvol(series, t0):
    past = [b for b in series if b[0] < t0][-481:]
    r = [math.log(b[4] / a[4]) for a, b in zip(past, past[1:]) if a[4] and b[4] and a[4] > 0]
    return statistics.pstdev(r) if len(r) >= 50 else None


def main():
    tr, c = load()
    syms = sorted({t["sym"] for t in tr})
    h1 = {s: bars(c, s, "candles_1h") for s in syms}
    m5 = {s: bars(c, s, "candles_5m") for s in syms}
    for t in tr:
        f5 = m5[t["sym"]][0][0] if m5[t["sym"]] else None
        t["res"] = "5m" if (f5 and t["open_ts"] >= f5) else "1h"
        t["series"] = m5[t["sym"]] if t["res"] == "5m" else h1[t["sym"]]
        t["sig"] = rvol(h1[t["sym"]], t["open_ts"])
        t["day"] = datetime.datetime.fromtimestamp(t["close_ts"], datetime.UTC).date()
    print("matched trades %d | bars: 5m %d, 1h %d | with real partial legs %d"
          % (len(tr), sum(1 for t in tr if t["res"] == "5m"),
             sum(1 for t in tr if t["res"] == "1h"),
             sum(1 for t in tr if t["partial_ts"])))

    # ---------------- GBM NO-EDGE CONTROL, RUN AND PRINTED FIRST, AS INSTRUCTED
    print("\n" + "=" * 74)
    print("GBM NO-EDGE CONTROL -- read BEFORE any arm (E2/E2b lesson)")
    print("=" * 74)
    rng = random.Random(20261013)
    sims = collections.defaultdict(list)
    use = [t for t in tr if t["sig"]]
    for _ in range(200):
        acc = collections.defaultdict(list)
        for t in use:
            g = gbm(t["open_ts"], t["entry"], t["sig"], CAP_H + 2, rng)
            a = pol_return(dict(t, exit=None, series=g), g, "hands_off")
            # under no edge the "actual" arm is a tightened stop: use half the original distance
            half = dict(t, sl=t["entry"] - t["side"] * abs(t["entry"] - t["sl"]) * 0.5)
            b = pol_return(dict(half, exit=None), g, "hands_off")
            if a and b:
                acc["pct"].append(a[0] - b[0])
                acc["R"].append(a[1] - b[1])
        for k, v in acc.items():
            if v:
                sims[k].append(statistics.fmean(v))
    for k in ("pct", "R"):
        v = sorted(sims[k])
        if v:
            print("  wide-minus-tight under NO EDGE, in %-4s median %+.4f  95%% [%+.4f, %+.4f]"
                  % (k, statistics.median(v), v[int(.025 * len(v))], v[int(.975 * len(v))]))
    print("  NOTE the sign: a no-edge world makes the WIDER stop look WORSE, so the geometry bias")
    print("  here favours the STATUS QUO. profits_only/hands_off must beat this to mean anything.")

    # ---------------- the three policies
    print("\n" + "=" * 74)
    print("THE THREE POLICIES (descriptive -- not a verdict)")
    print("=" * 74)
    res = {}
    for pol in ("actual", "profits_only", "hands_off"):
        rows = []
        for t in tr:
            r = pol_return(t, t["series"], pol)
            if r:
                rows.append((t, r))
        res[pol] = rows
        pct = [r[0] for _, r in rows]
        R = [r[1] for _, r in rows]
        byday = collections.defaultdict(list)
        for t, r in rows:
            byday[t["day"]].append(r[0])
        eq = statistics.fmean([statistics.fmean(v) for v in byday.values()])
        print("  %-13s n=%-4d  pooled %+7.3f%%  eq-day %+7.3f%%  mean R %+6.3f  days %d"
              % (pol, len(rows), statistics.fmean(pct), eq, statistics.fmean(R), len(byday)))

    base = {id(t): r for t, r in res["actual"]}
    for pol in ("profits_only", "hands_off"):
        d = [(t, r[0] - base[id(t)][0]) for t, r in res[pol] if id(t) in base]
        if not d:
            continue
        byday = collections.defaultdict(list)
        for t, v in d:
            byday[t["day"]].append(v)
        eq = statistics.fmean([statistics.fmean(v) for v in byday.values()])
        print("\n  %s MINUS actual: pooled %+.3f%%  eq-day %+.3f%%  (n=%d, %d days)"
              % (pol, statistics.fmean([v for _, v in d]), eq, len(d), len(byday)))
        for lbl, keyf in (("era", lambda t: "Jun-Jul" if t["day"] < datetime.date(2026, 8, 1)
                           else "Sep-Oct"),
                          ("side", lambda t: "LONG" if t["side"] > 0 else "SHORT"),
                          ("coin", lambda t: t["sym"])):
            g = collections.defaultdict(list)
            for t, v in d:
                g[keyf(t)].append(v)
            parts = "  ".join("%s %+.2f%% (n%d)" % (k, statistics.fmean(v), len(v))
                              for k, v in sorted(g.items(), key=lambda x: -len(x[1])))
            print("     by %-5s %s" % (lbl, parts))

    # ---------------- 1h vs 5m referee disagreement
    print("\n  1h/5m referee check (trades where 5m exists):")
    dis = same = 0
    for t in tr:
        if t["res"] != "5m":
            continue
        a, _ = walk(t, t["sl"], m5[t["sym"]])
        b, _ = walk(t, t["sl"], h1[t["sym"]])
        if a is None or b is None:
            continue
        if abs(a - b) / t["entry"] > 0.002:
            dis += 1
        else:
            same += 1
    print("     agree %d, disagree %d of %d  (5m only reaches back to 2026-09-22)"
          % (same, dis, same + dis))


if __name__ == "__main__":
    main()
