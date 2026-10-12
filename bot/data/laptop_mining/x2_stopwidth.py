"""Mission X2 -- is the bot's own 1.66% stop too tight? Runs PREREG_MISSION_X2_STOPWIDTH_2026-10-12.

Sealed prereg: commit aa344cc5, sha256 2d57c66d92c3d88b. Nothing here re-specifies it.

Arms, all sharing the trade's real entry time, price, side, tp1 and tp2:
    A0    the bot's actual stop               (baseline, median 1.66% of price)
    A1    1.0 x exp_move at entry
    A1.5  1.5 x exp_move at entry
    A2    2.0 x exp_move at entry

Two structural guards, both prereg commitments rather than afterthoughts:

1. ONLY A TRADE WHOSE STOP WAS HIT CAN CHANGE. 124 SL + 20 TRAILING_STOP of the 295 can differ; the
   other 151 (139 LLM-agent, 7 time-stop, 5 TP2) never touched their stop, so every arm must return
   a BIT-IDENTICAL result for them. `verify_identity()` asserts it. If that assertion fails the
   harness is wrong -- it would mean the replay is diverging where the real trade could not have --
   and the arms must not be reported.

2. R NEEDS NO POSITION SIZE. R = per-unit P&L / per-unit initial risk, and quantity cancels. That
   keeps the primary outcome free of `position_size`, whose units are ambiguous in TRADE_OPENED
   (values like 1.0 and 1.7 against prices from 32 to 50,000). Quantity is derived from the ledger
   only for the secondary dollar figure, and only where it is derivable.

The exp_move input pipeline was validated against the server's 119 logged rows -- 119/119 exact,
max abs diff 0.000 on both exp_move and rv5 -- so the daily-close reconstruction feeding
volforecast matches what production fed it.
"""
import collections
import csv
import datetime
import io
import json
import math
import os
import random
import sqlite3
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, r"C:\Users\vince\WAGMI\bot\tools\hivemind")
import volforecast as vf                                        # noqa: E402

DB = os.path.join(HERE, "crunch", "panels.sqlite")
LEDGER = os.path.join(HERE, "server_exports", "trade_ledger.csv")
FEE_BPS = 9.0            # round trip, per the brief
CAP_H = 96               # prereg: arm stop, tp2, or 96h
ARMS = [("A0", None), ("A1", 1.0), ("A1.5", 1.5), ("A2", 2.0)]
CHANGEABLE = ("SL", "TRAILING_STOP")


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def secs(t):
    t = float(t)
    return t / 1000.0 if t > 1e11 else t


def conn():
    return sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)


# ---------------------------------------------------------------- inputs
def load_trades(c):
    led = []
    for r in csv.DictReader(io.open(LEDGER, newline="", encoding="utf-8")):
        e, ts, hold = num(r.get("entry_price")), num(r.get("timestamp")), num(r.get("hold_hours"))
        if e is None or ts is None:
            continue
        side = (r.get("side") or "").upper()
        led.append({
            "sym": (r.get("symbol") or "").upper(),
            "side": 1 if side.startswith(("L", "B")) else -1,
            "entry": e,
            "open_ts": ts - (hold or 0) * 3600.0,          # ledger ts is the CLOSE (settled 10-12)
            "close_ts": ts,
            "exit": num(r.get("exit_price")),
            "gross": num(r.get("gross_pnl")),
            "net": num(r.get("net_pnl")),
            "exit_type": (r.get("exit_type") or "").upper(),
            "hold": hold or 0.0,
        })
    opens = collections.defaultdict(list)
    for ts, sym, body in c.execute("SELECT ts, sym, body FROM bulk_rows "
                                   "WHERE stream='trade_events' AND kind='TRADE_OPENED'"):
        d = json.loads(body)
        e, sl = num(d.get("entry")), num(d.get("sl"))
        if not e or not sl or e <= 0:
            continue
        side = (d.get("side") or "").upper()
        opens[((d.get("symbol") or sym or "").upper(),
               1 if side.startswith(("L", "B")) else -1)].append({
                   "ts": secs(ts) if ts else None, "entry": e, "sl": sl,
                   "tp1": num(d.get("tp1")), "tp2": num(d.get("tp2"))})
    out = []
    for t in led:
        best, bd = None, None
        for o in opens.get((t["sym"], t["side"]), ()):
            if abs(o["entry"] - t["entry"]) / t["entry"] > 5e-4 or o["ts"] is None:
                continue
            dt = abs(o["ts"] - t["open_ts"])
            if bd is None or dt < bd:
                best, bd = o, dt
        if best and bd <= 6 * 3600:
            t.update(sl=best["sl"], tp1=best["tp1"], tp2=best["tp2"], ev_ts=best["ts"])
            out.append(t)
    return out


def bars(c, sym, table):
    rows = c.execute("SELECT t,o,h,l,c FROM %s WHERE coin=? ORDER BY t" % table, (sym,)).fetchall()
    return [(secs(r[0]), r[1], r[2], r[3], r[4]) for r in rows]


def daily_closes(hourly, before_day):
    by = {}
    for t, _o, _h, _l, cl in hourly:
        d = datetime.datetime.fromtimestamp(t, datetime.UTC).date()
        if d < before_day:
            by[d] = cl
    return [by[k] for k in sorted(by)]


def funding_sum(c, sym, t0, t1):
    r = c.execute("SELECT COALESCE(SUM(rate),0) FROM funding_hist WHERE coin=? AND t>=? AND t<=?",
                  (sym, t0 * 1000.0, t1 * 1000.0)).fetchone()
    return float(r[0] or 0.0)


# ---------------------------------------------------------------- replay
def replay(t, stop, series, lookahead=0):
    """Walk bars from entry. Returns (exit_price, reason, exit_ts, touched_tp1).

    DECLARED DEVIATION from the sealed prereg, forced by the prereg's own guard.

    Prereg section 4 said a counterfactual trade "ends at whichever comes first: its arm's stop,
    tp2, or 96h." Run literally, that contradicts section 2, which asserted only stop-exited trades
    can change. The guard caught it: 102 of the 151 untouched trades differed across arms, every one
    with an A0 near -1.0R. The cause is that a trade the LLM agent closed after 3 hours was being
    walked on for 96 hours, where it hit a stop it never actually reached -- so A0 was not the bot's
    behaviour, it was "the bot with its exit agent deleted", and the comparison was wider-stop versus
    a baseline that never existed.

    The fix, which is the only reading consistent with sections 2 and 3: the bot's NON-STOP exit
    decisions are held fixed. A trade the agent, a time stop, or tp2 ended at time T has its replay
    capped at T in every arm, so a wider stop cannot change it -- which is what section 2 claimed and
    what the brief means by holding the bot's other behaviour constant. Trades that DID stop out have
    no later exit decision to preserve, so their counterfactual runs to the arm stop, tp2, or 96h,
    carrying exactly the no-LLM-intervention assumption already declared in section 3.

    This makes section 3's confound narrower than feared: it applies only to the extended life of
    the 144 stop-exited trades, not to all 295.

    `lookahead` shifts the stop test one bar later -- the prereg's look-ahead probe, which MUST turn
    the wider arm significantly positive or the harness is not measuring what it claims.
    """
    s, e = t["side"], t["entry"]
    tp2, tp1 = t.get("tp2"), t.get("tp1")
    deadline = t["open_ts"] + CAP_H * 3600
    # a non-stop exit is a decision the bot made and we are holding fixed
    held = t["exit_type"] not in CHANGEABLE
    if held:
        deadline = min(deadline, t["close_ts"])
    seen_tp1 = False
    pend = None
    for (bt, _bo, bh, bl, bc) in series:
        if bt < t["open_ts"]:
            continue
        if bt > deadline:
            break
        if tp1 and ((s > 0 and bh >= tp1) or (s < 0 and bl <= tp1)):
            seen_tp1 = True
        hit_stop = (bl <= stop) if s > 0 else (bh >= stop)
        hit_tp2 = tp2 is not None and ((bh >= tp2) if s > 0 else (bl <= tp2))
        if lookahead and hit_stop:
            if pend is None:
                pend = bt                      # defer the stop by one bar
                hit_stop = False
            # else fall through: it stops on the following bar
        if hit_stop and hit_tp2:
            return stop, "stop_and_tp2_same_bar", bt, seen_tp1
        if hit_stop:
            return stop, "stop", bt, seen_tp1
        if hit_tp2:
            return tp2, "tp2", bt, seen_tp1
        last = bc, bt
    if held and t.get("exit") is not None:
        # the trade ended here for a reason unrelated to the stop: use its real exit price, so A0
        # reproduces the actual trade rather than a bar close near it
        return t["exit"], "held_actual_exit", t["close_ts"], seen_tp1
    return (last[0], "cap96h", last[1], seen_tp1) if series else (e, "no_bars", t["open_ts"], False)


def arm_r(c, t, stop, series, fund, lookahead=0, inject=0.0):
    """P&L per unit of quantity, expressed in R of the trade's ORIGINAL risk."""
    risk = abs(t["entry"] - t["sl"])
    if risk <= 0:
        return None, None
    px, reason, xts, tp1 = replay(t, stop, series, lookahead)
    gross = t["side"] * (px - t["entry"])
    fee = t["entry"] * FEE_BPS / 10000.0
    fnd = t["side"] * fund * t["entry"]            # longs pay positive funding
    return (gross - fee - fnd) / risk + inject, {"reason": reason, "tp1": tp1, "exit": px,
                                                 "exit_ts": xts}


# ---------------------------------------------------------------- stats
def day_mean(vals_by_day):
    ds = [statistics.fmean(v) for v in vals_by_day.values() if v]
    return statistics.fmean(ds) if ds else None, len(ds)


def day_block_ci(pairs, nrep=4000, seed=20261012):
    """pairs: list of (day, delta). Day-block bootstrap on the EQUAL-WEIGHTED day mean."""
    by = collections.defaultdict(list)
    for d, v in pairs:
        by[d].append(v)
    days = sorted(by)
    if len(days) < 3:
        return None, None, None, 0
    point = statistics.fmean([statistics.fmean(by[d]) for d in days])
    rng = random.Random(seed)
    boot = []
    for _ in range(nrep):
        pick = [days[rng.randrange(len(days))] for _ in days]
        boot.append(statistics.fmean([statistics.fmean(by[d]) for d in pick]))
    boot.sort()
    lo, hi = boot[int(.025 * nrep)], boot[int(.975 * nrep)]
    sd = statistics.pstdev(boot) or 1e-12
    return point, (lo, hi), point / sd, len(days)


def main():
    c = conn()
    trades = load_trades(c)
    print("matched trades: %d" % len(trades))
    syms = sorted({t["sym"] for t in trades})
    h1 = {s: bars(c, s, "candles_1h") for s in syms}
    m5 = {s: bars(c, s, "candles_5m") for s in syms}
    m5_from = {s: (v[0][0] if v else None) for s, v in m5.items()}

    # exp_move at entry + the bar series each trade will use
    used5 = 0
    for t in trades:
        day = datetime.datetime.fromtimestamp(t["open_ts"], datetime.UTC).date()
        cl = daily_closes(h1[t["sym"]], day)
        f = vf.forecast(cl) if len(cl) >= 23 else None
        t["em"] = (f or {}).get("next_day_move_pct")
        f5 = m5_from[t["sym"]]
        if f5 is not None and t["open_ts"] >= f5:
            t["series"], t["res"] = m5[t["sym"]], "5m"
            used5 += 1
        else:
            t["series"], t["res"] = h1[t["sym"]], "1h"
        t["fund"] = funding_sum(c, t["sym"], t["open_ts"], t["close_ts"])
        t["day"] = datetime.datetime.fromtimestamp(t["close_ts"], datetime.UTC).date()
    have_em = [t for t in trades if t["em"]]
    print("exp_move computed on %d of %d | bar resolution: 5m %d, 1h %d"
          % (len(have_em), len(trades), used5, len(trades) - used5))
    print("  NOTE 5m exists for all 6 symbols but only from %s, so it covers recent trades only"
          % datetime.datetime.fromtimestamp(min(v for v in m5_from.values() if v),
                                            datetime.UTC).date())

    trades = have_em
    for t in trades:
        t["stops"] = {}
        for name, mult in ARMS:
            d = abs(t["entry"] - t["sl"]) if mult is None else t["entry"] * t["em"] / 100.0 * mult
            t["stops"][name] = t["entry"] - t["side"] * d
            t["width_%s" % name] = d / t["entry"] * 100.0

    # ---- run arms
    for t in trades:
        t["R"], t["meta"] = {}, {}
        for name, _m in ARMS:
            r, meta = arm_r(c, t, t["stops"][name], t["series"], t["fund"])
            t["R"][name], t["meta"][name] = r, meta

    # ---- GUARD 1: the 151 untouched trades must be identical in every arm
    chg = [t for t in trades if t["exit_type"] in CHANGEABLE]
    unc = [t for t in trades if t["exit_type"] not in CHANGEABLE]
    bad = [t for t in unc if len({round(t["R"][n], 12) for n, _ in ARMS if t["R"][n] is not None}) > 1]
    print("\nGUARD -- trades whose stop was never hit must be arm-invariant:")
    print("   changeable (SL/TRAILING): %d | untouched: %d | VIOLATIONS: %d"
          % (len(chg), len(unc), len(bad)))
    if bad:
        print("   *** HARNESS IS WRONG. %d untouched trades differ across arms. Arms NOT reported."
              % len(bad))
        for t in bad[:5]:
            print("       %s %s %s -> %s" % (t["sym"], t["exit_type"], t["day"],
                                             {n: round(t["R"][n], 4) for n, _ in ARMS}))
        return
    print("   PASS -- every untouched trade is bit-identical across all four arms")

    # ---- GUARD 2: A0 must reproduce the real trade, or the baseline is fiction
    dev = []
    for t in trades:
        a = t["meta"]["A0"]
        if a and t.get("exit"):
            rel = abs(a["exit"] - t["exit"]) / t["exit"]
            if rel > 0.005:
                dev.append((t, rel))
    print("\nGUARD 2 -- A0 must reproduce each trade's ACTUAL exit price:")
    print("   within 0.5%%: %d of %d | off by more: %d"
          % (len(trades) - len(dev), len(trades), len(dev)))
    if dev:
        dev.sort(key=lambda x: -x[1])
        for t, rel in dev[:6]:
            print("      %-5s %-16s actual %.6g vs A0 %.6g (%.1f%% off)"
                  % (t["sym"], t["exit_type"], t["exit"], t["meta"]["A0"]["exit"], rel * 100))
        if len(dev) > 0.15 * len(trades):
            print("   *** A0 does not reproduce the bot on %.0f%% of trades. Baseline is not the "
                  "bot. Arms NOT reported." % (100.0 * len(dev) / len(trades)))
            return

    # ---- widths actually tested
    print("\nstop widths, %% of price (changeable trades, n=%d):" % len(chg))
    for name, _m in ARMS:
        w = sorted(t["width_%s" % name] for t in chg)
        print("   %-5s median %5.2f%%  p10 %5.2f  p90 %5.2f" % (
            name, w[len(w) // 2], w[int(.1 * len(w))], w[int(.9 * len(w))]))

    json.dump({"n_matched": len(trades), "n_changeable": len(chg),
               "trades": [{k: (str(v) if isinstance(v, datetime.date) else v)
                           for k, v in t.items() if k not in ("series", "meta")} for t in trades]},
              io.open(os.path.join(HERE, "x2_arms.json"), "w", encoding="utf-8"))
    print("\narms written to x2_arms.json -- placebos run next, before any arm comparison")


if __name__ == "__main__":
    main()
