"""Replay a call minute-by-minute under different exit rules (owner 10-14: "map out how we would have read it
continuously ... I'm not sure how long we would have held, considering we close positions at 48h").

python tools/hivemind/replay_call.py COIN LONG|SHORT <utc-ts> <entry> [--k 1.65] [--risk 10]

Stop = entry -/+ K x the coin's expected daily move AS KNOWN AT THE CALL (HAR on daily closes before the call), the
bot's own stop geometry. Rules replayed on HL 5m bars from the call:
  fixed_1R_48h   stop, target +1R, close at 48h          (default plan behaviour)
  fixed_1R_72h   same, 72h limit                          (laptop M10's only alternative)
  partial_48h    half off at +1R, rest trails 1 daily ATR (point-in-time, 14d) behind the best price, 48h limit
                 (your exit idea; laptop M12: a 1-exp-move trail is the worst arm - ~0.43 ATR, inside normal noise)
  partial_72h    same, 72h limit
  partial_free   same, no time limit (runs to now)
  hold_to_now    stop only, still holding now
Prints each rule's exit time, price, R and $ at the given risk. Read-only; uses only data available at each bar.
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hl          # noqa: E402
import volforecast  # noqa: E402


def atr_at(coin, ts, n=14):
    d = sorted(hl.candles(coin, "1d", int((ts - 60 * 86400) * 1000), int(ts * 1000), ttl=3600) or [], key=lambda b: b["t"])
    d = [b for b in d if int(b["t"]) / 1000 + 86400 <= ts]
    if len(d) < n + 1:
        return None
    trs = [max(float(b["h"]) - float(b["l"]), abs(float(b["h"]) - float(p["c"])), abs(float(b["l"]) - float(p["c"])))
           for p, b in zip(d[:-1], d[1:])]
    return sum(trs[-n:]) / n


def exp_move_at(coin, ts):
    d = hl.candles(coin, "1d", int((ts - 120 * 86400) * 1000), int(ts * 1000), ttl=3600) or []
    closes = [float(b["c"]) for b in sorted(d, key=lambda b: b["t"]) if int(b["t"]) / 1000 + 86400 <= ts]
    f = volforecast.forecast(closes[-60:]) if len(closes) >= 23 else None
    return (f or {}).get("next_day_move_pct")


def replay(coin, side, ts, entry, k=1.65, risk_usd=10.0):
    em = exp_move_at(coin, ts)
    if not em:
        raise SystemExit(f"no expected move for {coin} at {ts}")
    sg = 1 if side == "LONG" else -1
    stop = entry * (1 - sg * k * em / 100)
    r1 = abs(entry - stop)
    tgt = entry + sg * r1
    atr = atr_at(coin, ts)
    trail_w = atr if atr else entry * em / 100     # 1 daily ATR as known at the call (laptop M12)
    now = time.time()
    bars = sorted(hl.candles(coin, "5m", int(ts * 1000), int(now * 1000), ttl=300) or [], key=lambda b: b["t"])
    bars = [b for b in bars if int(b["t"]) / 1000 >= ts - 300]
    out = {}

    def fixed(limit_h):
        end = ts + limit_h * 3600
        for b in bars:
            t, h, l = int(b["t"]) / 1000, float(b["h"]), float(b["l"])
            if (sg > 0 and l <= stop) or (sg < 0 and h >= stop):
                return t, stop, "stop"
            if (sg > 0 and h >= tgt) or (sg < 0 and l <= tgt):
                return t, tgt, "target +1R"
            if t + 300 >= end:
                return end, float(b["c"]), f"{limit_h}h limit"
        return None, float(bars[-1]["c"]), "still open"

    def partial(limit_h):
        end = ts + limit_h * 3600 if limit_h else None
        half_done, banked, best, st = False, 0.0, entry, stop
        for b in bars:
            t, h, l, c = int(b["t"]) / 1000, float(b["h"]), float(b["l"]), float(b["c"])
            if (sg > 0 and l <= st) or (sg < 0 and h >= st):
                rest = 0.5 if half_done else 1.0
                return t, banked + rest * sg * (st - entry) / r1, ("trail stop" if half_done else "stop")
            if not half_done and ((sg > 0 and h >= tgt) or (sg < 0 and l <= tgt)):
                half_done, banked = True, 0.5 * 1.0
            if half_done:
                best = max(best, h) if sg > 0 else min(best, l)
                trail = best - sg * trail_w
                st = max(st, trail) if sg > 0 else min(st, trail)
            if end and t + 300 >= end:
                rest = 0.5 if half_done else 1.0
                return end, banked + rest * sg * (c - entry) / r1, f"{limit_h}h limit"
        c = float(bars[-1]["c"])
        rest = 0.5 if half_done else 1.0
        return None, banked + rest * sg * (c - entry) / r1, "still open"

    for name, fn in (("fixed_1R_48h", lambda: fixed(48)), ("fixed_1R_72h", lambda: fixed(72))):
        t, px, how = fn()
        out[name] = (t, px, sg * (px - entry) / r1, how)
    for name, lim in (("partial_48h", 48), ("partial_72h", 72), ("partial_free", None)):
        t, r, how = partial(lim)
        out[name] = (t, None, r, how)
    hold = fixed(10 ** 6)
    out["hold_to_now"] = (hold[0], hold[1], sg * (hold[1] - entry) / r1, hold[2] if hold[2] != "target +1R" else "still open")
    if hold[2] == "target +1R":   # hold_to_now ignores the target: recompute as stop-only
        c = float(bars[-1]["c"])
        hit = next((int(b["t"]) / 1000 for b in bars if (sg > 0 and float(b["l"]) <= stop) or (sg < 0 and float(b["h"]) >= stop)), None)
        out["hold_to_now"] = (hit, stop if hit else c, sg * ((stop if hit else c) - entry) / r1, "stop" if hit else "still open")
    return {"em": em, "atr_pct": round(atr / entry * 100, 2) if atr else None, "stop": stop, "target": tgt, "r1": r1, "rules": out, "last": float(bars[-1]["c"]), "risk": risk_usd}


def fmt_t(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%m-%d %H:%M") if t else "  now  "


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("coin"); ap.add_argument("side"); ap.add_argument("ts", type=float); ap.add_argument("entry", type=float)
    ap.add_argument("--k", type=float, default=1.65); ap.add_argument("--risk", type=float, default=10.0)
    a = ap.parse_args()
    res = replay(a.coin, a.side.upper(), a.ts, a.entry, a.k, a.risk)
    print(f"{a.coin} {a.side} @ {a.entry} on {fmt_t(a.ts)} UTC | expected daily move then {res['em']}% | "
          f"trail 1 ATR = {res['atr_pct']}% | stop {res['stop']:.5f} | +1R target {res['target']:.5f} | now {res['last']}")
    for name, (t, px, r, how) in res["rules"].items():
        print(f"  {name:13} exit {fmt_t(t)}  {r:+.2f}R  ${r * a.risk:+.2f} at ${a.risk:.0f} risk  ({how})")
