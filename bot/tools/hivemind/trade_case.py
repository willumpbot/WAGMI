"""One case file per owner trade (owner 10-15: "each trade needs its own team of micromanaging data mining").

Every 15-min cycle, for every owner plan that has filled (bot-run or simulated, any HL perp):
  opened   (written once)  the plan, the expected move and daily ATR AS KNOWN AT THE FILL, the scanner flags then,
                           and the eye.py deep read summary (levels, funding cost, BTC link) captured the first cycle
                           the file exists - so the post-mortem compares against what was knowable, never hindsight.
  live     (each cycle)    price, R now, distance to stop / +1R / target / trail in the coin's own daily moves,
                           exit-style state (half banked? trail level), time left, flags now, the owner's style vs
                           'all at target' so far, and the position-watch alerts for this trade.
  closed   (on close)      post-mortem: how it ended, which style did better and by how much, how far price went
                           after the exit (24h), and what the open-time read said.
Writes data/hivemind/cases/<plan_id>.json and an index data/hivemind/cases/index.json. Read-only: never trades.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import hl
import exit_style

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"
CASES = HM / "cases"


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _deep_read(coin):
    """eye.py --deep, condensed to the lines that matter (subprocess: it has its own imports and can be slow)."""
    try:
        out = subprocess.run([sys.executable, str(BOT / "tools" / "copilot" / "eye.py"), coin, "--deep"],
                             cwd=str(BOT), capture_output=True, text=True, timeout=180).stdout
    except Exception as e:
        return {"error": str(e)[:120]}
    keep = []
    for line in out.splitlines():
        s = line.strip()
        if any(k in s for k in ("Price $", "Daily:", "20d range", "ATR", "FUNDING", "Beta-to-BTC", "RESISTANCE", "SUPPORT",
                                "touches", "VOLUME last", "TREND:")):
            keep.append(s[:200])
    return {"lines": keep[:24]}


def run(deep_reads=2):
    now = time.time()
    CASES.mkdir(parents=True, exist_ok=True)
    plans = _load(HM / "plans.json", {}).get("plans", [])
    scan = {r["coin"]: r for r in _load(HM / "scan.json", {}).get("coins", [])}
    watch = _load(HM / "watch.json", {}).get("alerts", [])
    try:
        mids = hl.post({"type": "allMids"}, ttl=30) or {}
    except Exception:
        mids = {}
    index, reads_left = [], deep_reads
    for p in plans:
        R = p.get("result") or {}
        if not R.get("filled_at"):
            continue
        pid, coin, side = p["id"], p["coin"], p["side"]
        path = CASES / f"{pid}.json"
        case = _load(path, {})
        e, st, tg = float(p["entry"]), float(p["stop"]), float(p["target"])
        risk = abs(e - st)
        sg = 1 if side == "LONG" else -1
        f_ts = float(R["filled_at"])
        if "opened" not in case:
            atr = exit_style.atr_at(hl, coin, f_ts)
            case["opened"] = {"plan_id": pid, "coin": coin, "side": side, "entry": e, "stop": st, "target": tg,
                              "one_r": e + sg * risk, "filled_at": f_ts, "max_hold_h": p.get("max_hold_h"),
                              "exit_style": exit_style.norm(p.get("exit_style")), "exit_mode": p.get("exit_mode"),
                              "risk_usd": p.get("risk_usd"), "atr_at_fill": atr,
                              "atr_pct_at_fill": round(atr / e * 100, 2) if atr else None,
                              "flags_at_case_start": (scan.get(coin) or {}).get("flags"),
                              "late_logged": bool(p.get("late_logged")), "reason": (p.get("reason") or "")[:300],
                              "case_started": now}
        if "deep_read" not in case and reads_left > 0 and R.get("status") == "open":
            case["deep_read"] = dict(_deep_read(coin), at=now)
            reads_left -= 1
        px = float(mids.get(coin) or 0) or None
        sc = scan.get(coin) or {}
        atr = case["opened"].get("atr_at_fill")
        unit = atr or (e * (sc.get("exp_move") or 0) / 100) or None
        legs = R.get("legs") or []
        live = {"at": now, "status": R.get("status"), "px": px, "flags": sc.get("flags") or [],
                "half_banked": any(l.get("why") == "half at +1R" for l in legs), "trail": R.get("trail"),
                "style_r": R.get("r") if R.get("status") != "open" else R.get("live_r"),
                "alt_style": R.get("alt_style"), "alt_r": R.get("alt_r") if R.get("alt_r") is not None else R.get("alt_live_r"),
                "alerts": [a["msg"] for a in watch if coin in a.get("msg", "")]}
        if px and unit:
            live["r_now"] = round(sg * (px - e) / risk, 2)
            live["to_stop_atr"] = round(abs(px - st) / unit, 2)
            live["to_1r_atr"] = round((case["opened"]["one_r"] - px) * sg / unit, 2)
            live["to_target_atr"] = round((tg - px) * sg / unit, 2)
            if R.get("trail"):
                live["to_trail_atr"] = round(abs(px - float(R["trail"])) / unit, 2)
        exp_ts = f_ts + float(p.get("max_hold_h") or 48) * 3600
        live["hours_left"] = round((exp_ts - now) / 3600, 1) if R.get("status") == "open" else None
        hv = _load(HM / "state" / f"{coin}.json", {})
        if hv:
            cons = hv.get("consensus") or {}
            vlist = hv.get("voices") or []
            live["hivemind"] = {
                "updated": hv.get("updated"),
                "consensus": {k: cons.get(k) for k in ("bull", "bear", "neutral", "bull_families", "bear_families",
                                                      "dissent_families", "move_size", "move_size_hint")},
                # voices.py: reading +1 = leans up, -1 = leans down, 0 = neutral (context only - none predicts direction)
                "with_you": sum(1 for v in vlist if (v.get("reading") or 0) * sg > 0),
                "against_you": sum(1 for v in vlist if (v.get("reading") or 0) * sg < 0),
                "voices": [{k: v.get(k) for k in ("voice", "family", "label", "reading", "detail", "trust") if k in v}
                           for v in vlist][:24],
                "contradictions": (hv.get("contradictions") or [])[:6],
                "liquidation_magnets": ((hv.get("deep") or {}).get("liquidation_magnets")),
                "this_coin_history": {k: (hv.get("history") or {}).get(k) for k in ("state_words", "next_5d_this_coin")},
                "risk_notes": ((hv.get("risk") or {}).get("notes") or [])[:4],
                "expected_move_pct": (hv.get("vol") or {}).get("next_day_move_pct"),
            }
        case["live"] = live
        if R.get("status") != "open" and "closed" not in case:
            after = None
            try:
                b = hl.candles(coin, "1h", int(R["closed_at"] * 1000), int((R["closed_at"] + 86400) * 1000), ttl=600) or []
                if b and now >= R["closed_at"] + 86400:
                    after = round(sg * (float(b[-1]["c"]) - float(R.get("exit") or e)) / risk, 2)
            except Exception:
                pass
            if after is not None or now >= R.get("closed_at", now) + 86400 * 2:
                case["closed"] = {"status": R.get("status"), "r": R.get("r"), "exit": R.get("exit"),
                                  "closed_at": R.get("closed_at"), "hold_h": R.get("hold_h"),
                                  "how": (legs[-1]["why"] if legs else None), "legs": legs,
                                  "alt_style": R.get("alt_style"), "alt_r": R.get("alt_r"),
                                  "style_won": (None if R.get("alt_r") is None or R.get("r_gross") is None
                                                else ("your style" if R["r_gross"] > R["alt_r"] else
                                                      "the other style" if R["r_gross"] < R["alt_r"] else "tie")),
                                  "r_moved_24h_after_exit": after, "written": now}
        path.write_text(json.dumps(case, default=str, indent=1), encoding="utf-8")
        index.append({"plan_id": pid, "coin": coin, "side": side, "status": R.get("status"),
                      "r_now": live.get("r_now"), "style_r": live.get("style_r"), "alt_r": live.get("alt_r"),
                      "to_stop_atr": live.get("to_stop_atr"), "hours_left": live.get("hours_left"),
                      "closed": "closed" in case, "late_logged": case["opened"].get("late_logged")})
    (CASES / "index.json").write_text(json.dumps({"updated": now, "cases": index}, default=str), encoding="utf-8")
    return index


if __name__ == "__main__":
    for c in run():
        print(c)
