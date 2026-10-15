"""The owner's exit style, as ONE engine every grader / simulator uses (owner 10-15: "we want most all things to take
towards my style ... it would be important that we follow through with these things properly").

style "runner" (default): take HALF at +1R; the other half trails 1 daily ATR (14-day, point-in-time at the fill)
  behind the best price since; whatever is left closes at the plan's time limit. Before +1R the full position rides
  the owner's stop. Laptop evidence: partial_1R led every stop width (M1, exploratory; sealed test e0621993 reads by
  2026-12-01); a 1-ATR trail beats a tight one (M12); close winners on the clock, not on noise (M10).
style "full": the whole position closes at the stop, the target or the time limit (the old all-or-nothing).

R is per unit of the ORIGINAL risk (|entry - stop| x full size), before fees.
"""
import time

STYLES = ("runner", "full")
DEFAULT = "runner"


def norm(v):
    v = str(v or "").strip().lower()
    return v if v in STYLES else DEFAULT


def guarded(style, side, entry, stop, target):
    """The bot's target guard (OWNER_RUNNER_TARGET_GUARD, default on, live since 10-15): when the target sits at or
    inside +1R, 'runner' would ignore it and wait for a +1R that may never print, so the plan runs 'full' (all at
    target). Graders must apply it too, or live and graded diverge (RSR b33a49b78e, 10-15: target 0.00215 vs +1R
    0.00216)."""
    import os
    style = norm(style)
    if style != "runner" or os.getenv("OWNER_RUNNER_TARGET_GUARD", "true").strip().lower() in ("0", "false", "no", "off"):
        return style
    return "full" if abs(target - entry) <= abs(entry - stop) else style


def atr_at(hl, coin, ts, n=14):
    try:
        d = sorted(hl.candles(coin, "1d", int((ts - 60 * 86400) * 1000), int(ts * 1000), ttl=3600) or [],
                   key=lambda b: b["t"])
    except Exception:
        return None
    d = [b for b in d if int(b["t"]) / 1000 + 86400 <= ts]
    if len(d) < n + 1:
        return None
    trs = [max(float(b["h"]) - float(b["l"]), abs(float(b["h"]) - float(p["c"])), abs(float(b["l"]) - float(p["c"])))
           for p, b in zip(d[:-1], d[1:])]
    return sum(trs[-n:]) / n


def play(side, entry, stop, target, bars, fill_ts, max_hold_h, style="runner", atr=None, now=None):
    """Walk 5m bars (sorted, from the fill) under the style. Returns a dict:
    status open|won|lost|timed out, r (realised + open), legs [{at, px, frac, why}], exit_ts, best_px, trail."""
    now = now or time.time()
    sg = 1 if side == "LONG" else -1
    risk = abs(entry - stop)
    end = fill_ts + float(max_hold_h or 48) * 3600
    one_r = entry + sg * risk
    style = norm(style)
    legs, frac_left, banked, best, trail_stop = [], 1.0, 0.0, entry, stop
    runner_on = False
    trail_w = atr if atr else None
    for b in bars:
        t, h, l, c = int(b["t"]) / 1000, float(b["h"]), float(b["l"]), float(b["c"])
        if t + 300 <= fill_ts:
            continue
        cur_stop = trail_stop if runner_on else stop
        if (sg > 0 and l <= cur_stop) or (sg < 0 and h >= cur_stop):
            r = sg * (cur_stop - entry) / risk
            legs.append({"at": t, "px": cur_stop, "frac": frac_left, "why": "trail" if runner_on else "stop"})
            banked += frac_left * r
            return {"status": "won" if banked > 0 else "lost", "r": round(banked, 3), "legs": legs, "exit_ts": t,
                    "best_px": best, "trail": trail_stop if runner_on else None}
        if style == "full":
            if (sg > 0 and h >= target) or (sg < 0 and l <= target):
                r = sg * (target - entry) / risk
                legs.append({"at": t, "px": target, "frac": 1.0, "why": "target"})
                return {"status": "won", "r": round(r, 3), "legs": legs, "exit_ts": t, "best_px": best, "trail": None}
        elif not runner_on and ((sg > 0 and h >= one_r) or (sg < 0 and l <= one_r)):
            legs.append({"at": t, "px": one_r, "frac": 0.5, "why": "half at +1R"})
            banked += 0.5 * 1.0
            frac_left = 0.5
            runner_on = True
            best = one_r
            trail_stop = stop
        if runner_on:
            best = max(best, h) if sg > 0 else min(best, l)
            if trail_w:
                cand = best - sg * trail_w
                trail_stop = max(trail_stop, cand) if sg > 0 else min(trail_stop, cand)
        if t + 300 >= end:
            r = sg * (c - entry) / risk
            legs.append({"at": end, "px": c, "frac": frac_left, "why": "time limit"})
            banked += frac_left * r
            st_ = "timed out" if style == "full" else ("won" if banked > 0 else "lost" if banked < 0 else "timed out")
            return {"status": st_, "r": round(banked, 3),
                    "legs": legs, "exit_ts": end, "best_px": best, "trail": trail_stop if runner_on else None,
                    "timed_out": True}
    last = float(bars[-1]["c"]) if bars else entry
    open_r = banked + frac_left * sg * (last - entry) / risk
    return {"status": "open", "r": None, "live_r": round(open_r, 3), "legs": legs, "exit_ts": None, "best_px": best,
            "trail": trail_stop if runner_on else None, "frac_left": frac_left, "last": last}
