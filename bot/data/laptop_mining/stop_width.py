"""What stop does the bot ACTUALLY use? Recovered from TRADE_OPENED, not from the ledger column.

WHY THIS EXISTS. `MISSION_XZ_SYNTHESIS` could not test the bot's own exit rule: `stop_initial` is
populated on 1 of 294 ledger rows, so the 16-cell grid swept 1-4x expected move (risk 5.2-20.7% of
price) while the bot's implied stop was ~0.43-0.47x (risk ~1.5-2.2%). The study answered "does a
2-9x wider stop beat the bot?" -- no -- and not "is the bot's stop the right width?"

The server then told me why and where to look: the ledger columns were ADDED on 2026-10-10 and
exactly one trade has closed since, so it is not a writer defect; for the earlier 293 the stop at
entry lives on the SIGNAL_GENERATED / TRADE_OPENED events in the bulk export. Those are already on
the laptop -- j7 archived 154,850 `trade_events` rows, of which 10,639 are TRADE_OPENED carrying
entry / sl / tp1 / tp2 / side / leverage.

THE TRAP, AND WHY MOST OF THIS FILE IS THE FILTER. 10,639 TRADE_OPENED against 294 real closed
trades means the overwhelming majority are NOT live: the server confirmed the writer runs in any
process using PositionManager with cwd=bot -- backtests, replays, sims -- and the same 80-per-day
shape already disqualified `trade_events` for the OI counter in j2. A stop-width distribution taken
over all 10,639 rows would be a distribution over whatever parameters those sweeps used, dressed up
as the bot's behaviour. So every number here is reported twice: over the ledger-matched subset
(defensible) and over everything (diagnostic only).

STOP WIDTH IS MEASURED DEFINITION-FREE. |entry - sl| / entry, in percent of price. This deliberately
avoids expressing it as a multiple of expected move, because three incompatible `exp_move`
definitions exist in this project and they differ by ~2x -- so "0.45x exp_move" is not a width until
you say whose exp_move. Percent of price is the same number for everyone.
"""
import collections
import csv
import json
import os
import sqlite3
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
LEDGER = os.path.join(HERE, "server_exports", "trade_ledger.csv")


def f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def load_ledger():
    out = []
    with open(LEDGER, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            e, ts, hold = f(r.get("entry_price")), f(r.get("timestamp")), f(r.get("hold_hours"))
            if e is None or ts is None:
                continue
            out.append({
                "sym": (r.get("symbol") or "").upper(),
                "side": (r.get("side") or "").upper(),
                "entry": e,
                # the ledger timestamp is the CLOSE (settled 2026-10-12; see ENTRY_TIMING
                # retraction), so the OPEN is timestamp - hold_hours
                "open_ts": ts - (hold or 0) * 3600.0,
                "close_ts": ts,
                "stop_initial": f(r.get("stop_initial")),
                "realized_rr": f(r.get("realized_rr")),
                "exit_type": r.get("exit_type") or "",
                "win": r.get("win"),
                "net": f(r.get("net_pnl")),
            })
    return out


def load_opens():
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    out = []
    for ts, sym, body in c.execute(
            "SELECT ts, sym, body FROM bulk_rows "
            "WHERE stream='trade_events' AND kind='TRADE_OPENED'"):
        d = json.loads(body)
        e, sl = f(d.get("entry")), f(d.get("sl"))
        if not e or not sl or e <= 0:
            continue
        out.append({
            "ts": ts,
            "sym": (d.get("symbol") or sym or "").upper(),
            "side": (d.get("side") or "").upper(),
            "entry": e, "sl": sl,
            "tp1": f(d.get("tp1")), "tp2": f(d.get("tp2")),
            "lev": f(d.get("leverage")),
            "width": abs(e - sl) / e * 100.0,
            "strategy": d.get("strategy"),
        })
    c.close()
    return out


def match(ledger, opens):
    """Pair each ledger trade with its TRADE_OPENED event.

    Keyed on symbol + side + relative entry-price agreement, then nearest in time to the
    reconstructed open. Price is the discriminating field -- an exact symbol/side pair recurs
    constantly, but the same symbol opening at the same price to 5 bp within a few hours of the
    reconstructed open is the trade.
    """
    idx = collections.defaultdict(list)
    for o in opens:
        idx[(o["sym"], o["side"])].append(o)
    hits, miss = [], 0
    for t in ledger:
        best, bestdt = None, None
        for o in idx.get((t["sym"], t["side"]), ()):
            if abs(o["entry"] - t["entry"]) / t["entry"] > 5e-4:      # 5 bp
                continue
            dt = abs((o["ts"] or 0) - t["open_ts"])
            if bestdt is None or dt < bestdt:
                best, bestdt = o, dt
        if best is not None and bestdt is not None and bestdt <= 6 * 3600:
            hits.append((t, best, bestdt))
        else:
            miss += 1
    return hits, miss


def describe(name, widths):
    if not widths:
        print("  %-26s (none)" % name)
        return
    w = sorted(widths)
    q = lambda p: w[min(int(p * len(w)), len(w) - 1)]
    print("  %-26s n=%-5d median %5.2f%%  p10 %5.2f  p90 %5.2f  mean %5.2f  "
          "at 5.00%%: %d (%.0f%%)"
          % (name, len(w), q(.5), q(.1), q(.9), statistics.fmean(w),
             sum(1 for x in w if abs(x - 5.0) < 0.005),
             100.0 * sum(1 for x in w if abs(x - 5.0) < 0.005) / len(w)))


def main():
    ledger, opens = load_ledger(), load_opens()
    print("ledger %d closed trades | TRADE_OPENED %d events" % (len(ledger), len(opens)))

    hits, miss = match(ledger, opens)
    print("\nMATCHED %d of %d ledger trades to a TRADE_OPENED event (%d unmatched)"
          % (len(hits), len(ledger), miss))
    if hits:
        dts = sorted(h[2] for h in hits)
        print("  time offset event-vs-reconstructed-open: median %.0fs, p90 %.0fs"
              % (dts[len(dts) // 2], dts[int(.9 * len(dts))]))

    print("\nSTOP WIDTH, |entry-sl|/entry in %% of price:")
    describe("ledger-matched (live)", [h[1]["width"] for h in hits])
    describe("ALL TRADE_OPENED", [o["width"] for o in opens])
    print("  ^ the second line is DIAGNOSTIC ONLY -- it pools backtests, replays and sims that\n"
          "    share the writer, so its parameters are not necessarily the bot's.")

    # does the one ledger row carrying stop_initial agree with its event?
    for t, o, _ in hits:
        if t["stop_initial"]:
            w = abs(t["entry"] - t["stop_initial"]) / t["entry"] * 100.0
            print("\n  CROSS-CHECK on the single row with stop_initial populated:")
            print("    ledger stop_initial -> %.3f%% | TRADE_OPENED sl -> %.3f%% | %s"
                  % (w, o["width"], "AGREE" if abs(w - o["width"]) < 0.05 else "DISAGREE"))

    print("\nIS THE 5.00%% DEFAULT DOING THE DAMAGE? (matched live trades only)")
    at5 = [h for h in hits if abs(h[1]["width"] - 5.0) < 0.005]
    not5 = [h for h in hits if abs(h[1]["width"] - 5.0) >= 0.005]
    for nm, grp in (("stop == 5.00%", at5), ("stop != 5.00%", not5)):
        if not grp:
            print("  %-16s (none)" % nm)
            continue
        wins = [1 if (h[0]["win"] in ("True", "true", "1", True)) else 0 for h in grp]
        sl = sum(1 for h in grp if "SL" in (h[0]["exit_type"] or "").upper())
        nets = [h[0]["net"] for h in grp if h[0]["net"] is not None]
        print("  %-16s n=%-4d win %3.0f%%  SL-exit %3.0f%%  mean net %+7.2f  median width %5.2f%%"
              % (nm, len(grp), 100 * statistics.fmean(wins) if wins else 0,
                 100.0 * sl / len(grp), statistics.fmean(nets) if nets else 0,
                 statistics.median([h[1]["width"] for h in grp])))
    print("\n  NO VERDICT from this file. It is a description of what the bot did, not a test of\n"
          "  whether a different width would have done better -- that needs the grid re-centred,\n"
          "  and the split above is not randomised: the bot chose which trades got which stop.")


if __name__ == "__main__":
    main()
