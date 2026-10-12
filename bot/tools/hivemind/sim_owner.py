"""Simulate an executed owner plan as if it had run under exit_mode = "profits_only" (owner request 10-13).

For each plan the bot actually executed (owner_fills.jsonl): keep the bot's real partial-profit legs (in order, clipped
so partials never exceed 50% of the original size - the profits_only cap), never move the owner's stop, never close
early. The rest of the position rides from the fill to the FIRST of: the owner's stop, the owner's target, or the plan's
own max_hold_h - walked on HL 5m bars from the fill (stop wins ties in a bar, pessimistic). If none has happened yet the
remainder is marked to the live price. P&L before fees; R = P&L / (|entry - stop| x original qty).
Shown in the terminal next to what the bot actually did. Simulation only - never trades.
"""
import json
import time
from pathlib import Path

import hl

HM = Path(__file__).resolve().parents[2] / "data" / "hivemind"
CAP = 0.5


def simulate(plan_id, plan):
    legs = []
    try:
        for l in (HM / "owner_fills.jsonl").read_text(encoding="utf-8").splitlines():
            f = json.loads(l)
            if f.get("plan_id") == plan_id:
                legs.append(f)
    except OSError:
        return None
    opn = next((f for f in legs if f.get("kind") == "open"), None)
    if not opn:
        return None
    side, entry, q0 = opn["side"], float(opn["entry"]), float(opn["qty"])
    stop, target = float(plan.get("stop") or opn["sl"]), float(plan.get("target") or opn["tp2"])
    sg = 1 if side == "LONG" else -1
    t_open = float(opn["ts"])
    t_end = t_open + float(plan.get("max_hold_h") or 48) * 3600
    pnl, qty, taken, out_legs = 0.0, q0, 0.0, []
    for f in sorted((f for f in legs if f.get("kind") == "partial"), key=lambda f: f["ts"]):
        q = min(float(f["qty"]), max(0.0, CAP * q0 - taken))
        if q <= 0:
            continue
        pnl += sg * (float(f["exit"]) - entry) * q
        qty -= q
        taken += q
        out_legs.append({"ts": f["ts"], "exit": float(f["exit"]), "qty": round(q, 6)})
    now = time.time()
    try:
        bars = sorted(hl.candles(opn["coin"], "5m", int(t_open * 1000), int(min(now, t_end) * 1000), ttl=240) or [],
                      key=lambda b: b["t"])
    except Exception:
        bars = []
    status, exit_px, exit_ts = "open", None, None
    for b in bars:
        t, hi, lo = int(b["t"]) / 1000, float(b["h"]), float(b["l"])
        if t + 300 <= t_open:
            continue
        hit_stop = (sg < 0 and hi >= stop) or (sg > 0 and lo <= stop)
        hit_tgt = (sg < 0 and lo <= target) or (sg > 0 and hi >= target)
        if hit_stop:
            status, exit_px, exit_ts = "stop", stop, t
            break
        if hit_tgt:
            status, exit_px, exit_ts = "target", target, t
            break
    if status == "open" and now >= t_end and bars:
        status, exit_px, exit_ts = "time limit", float(bars[-1]["c"]), t_end
    if status == "open":
        try:
            mark = float(hl.post({"type": "allMids"}, ttl=30)[opn["coin"]])
        except Exception:
            mark = float(bars[-1]["c"]) if bars else entry
        rest = sg * (mark - entry) * qty
    else:
        mark, rest = exit_px, sg * (exit_px - entry) * qty
    total = pnl + rest
    risk = abs(entry - stop) * q0
    return {"mode": "profits_only", "status": status, "lev": float(plan.get("leverage") or 1), "entry": entry, "stop": stop, "target": target,
            "partials": out_legs, "banked_usd": round(pnl, 2), "open_qty": round(qty, 6), "mark": mark,
            "open_pnl_usd": round(rest, 2), "total_usd": round(total, 2),
            "r": round(total / risk, 3) if risk else None, "exit_ts": exit_ts, "expires_ts": t_end, "as_of": now}


if __name__ == "__main__":
    for p in json.loads((HM / "plans.json").read_text(encoding="utf-8")).get("plans", []):
        if (p.get("exec_result") or {}).get("fills"):
            print(p["coin"], p["side"], simulate(p["id"], p))
