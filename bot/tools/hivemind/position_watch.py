"""Position watch (owner 10-14: "how can we be extremely proactive?").

Every hivemind cycle: look at everything the owner holds (bot-run owner positions + plans simulated on live prices)
and his watchlist, and raise a short alert only when something CHANGED or needs eyes:
  near_stop     price within 0.5 expected daily moves of the stop
  near_target   price within 0.3 expected daily moves of the target
  hot_flag      a held coin turned funding_hot (replicated: bigger moves, more stop hits - sizing, not direction)
  time_limit    the plan's own time limit is under 6 hours away
  watchlist     a watchlist coin carries a scanner flag
  waking_up     a watchlist or held coin moved >= 0.5 expected daily moves in the last closed hour on >= 2.5x its
                median hourly volume (owner 10-14: CASHCAT's first +8.3% hour on 2.9x volume came ~14% before the top)
Writes data/hivemind/watch.json (current state + alerts) and appends NEW alerts to watch_log.jsonl (deduped per
position+kind per day). Read-only: never trades, never moves a stop.
"""
import json
import time
from pathlib import Path

import hl

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"
OUT = HM / "watch.json"
LOG = HM / "watch_log.jsonl"
NEAR_STOP_EM = 0.5
NEAR_TGT_EM = 0.3
TIME_LIMIT_H = 6


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def holdings():
    """[(source, key, coin, side, entry, stop, target, expires_ts)] - owner positions the bot runs + open sims."""
    out = []
    pos = _load(BOT / "data" / "position_state.json", {})
    pos = pos.get("positions", pos) if isinstance(pos, dict) else {}
    plans = {p["id"]: p for p in _load(HM / "plans.json", {}).get("plans", [])}
    for sym, p in (pos or {}).items():
        if p.get("strategy") != "owner_plan":
            continue
        er = p.get("entry_reasons") or {}
        pl = plans.get(er.get("owner_plan_id")) or {}
        exp = None
        mh = er.get("plan_max_hold_h")
        if mh and p.get("open_time"):
            try:
                from datetime import datetime
                exp = datetime.fromisoformat(p["open_time"]).timestamp() + float(mh) * 3600
            except Exception:
                exp = None
        out.append(("bot-run", "pos:" + sym, sym, p["side"], float(p["entry"]), float(p["sl"]),
                    float(p.get("tp2") or pl.get("target") or 0) or None, exp,
                    float(p.get("original_sl") or p["sl"])))   # R is per ORIGINAL risk (the trail moves sl)
    for s in _load(HM / "owner_plan_sims.json", {}).get("sims", []):
        if s.get("status") == "open" and s.get("bot_traded") is False:
            out.append(("simulated", "sim:" + s["plan_id"], s["coin"], s["side"], s["entry"], s["stop"], s["target"],
                        s.get("expires_ts"), s["stop"]))
    return out


def _structural_hot():
    """Coins whose funding_hot flag is on most days (laptop M11: CASHCAT 79% of days) - for them the flag is normal,
    not news, so the alert is muted. Needs >= 5 logged days."""
    days, hot = set(), {}
    try:
        for l in (HM / "scan_log.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            days.add(r["day"])
            if r.get("flag") == "funding_hot":
                hot.setdefault(r["coin"], set()).add(r["day"])
    except (OSError, ValueError):
        return set()
    if len(days) < 5:
        return set()
    return {c for c, d in hot.items() if len(d) / len(days) > 0.5}


def run():
    now = time.time()
    always_hot = _structural_hot()
    scan = {r["coin"]: r for r in _load(HM / "scan.json", {}).get("coins", [])}
    try:
        mids = hl.post({"type": "allMids"}, ttl=30) or {}
    except Exception:
        mids = {}
    watch = _load(HM / "owner_watchlist.json", [])
    rows, alerts = [], []
    for src, key, coin, side, entry, stop, target, exp, stop0 in holdings():
        px = float(mids.get(coin) or 0) or None
        sc = scan.get(coin) or {}
        em = sc.get("exp_move")
        sg = 1 if side == "LONG" else -1
        row = {"src": src, "key": key, "coin": coin, "side": side, "entry": entry, "stop": stop, "target": target,
               "px": px, "exp_move": em, "flags": sc.get("flags") or [], "expires_ts": exp}
        if px:
            row["r"] = round(sg * (px - entry) / abs(entry - stop0), 2) if entry != stop0 else None
            row["to_stop_pct"] = round(abs(px - stop) / px * 100, 2)
            row["to_target_pct"] = round(abs(target - px) / px * 100, 2) if target else None
            if em:
                row["to_stop_em"] = round(row["to_stop_pct"] / em, 2)
                if row["to_stop_em"] <= NEAR_STOP_EM:
                    alerts.append((key, "near_stop", f"{coin} {side}: {row['to_stop_pct']}% from your stop "
                                                     f"({row['to_stop_em']} of a normal day), now {row['r']:+}R"))
                if row["to_target_pct"] is not None and row["to_target_pct"] / em <= NEAR_TGT_EM:
                    alerts.append((key, "near_target", f"{coin} {side}: {row['to_target_pct']}% from your target, now {row['r']:+}R"))
        if "funding_hot" in row["flags"] and coin not in always_hot:
            alerts.append((key, "hot_flag", f"{coin}: 'longs paying a lot' is on - bigger moves and more stop hits "
                                            f"(replicated). Size/stop room, not direction."))
        if exp and 0 < exp - now <= TIME_LIMIT_H * 3600:
            alerts.append((key, "time_limit", f"{coin} {side}: your plan's time limit is in {(exp - now) / 3600:.1f}h"))
        rows.append(row)
    # GIVE-BACK (owner 10-15: "we were RIGHT" on VVV +0.52R and RSR +0.92R, both drifted back without banking anything).
    # Insight, not an exit: a filled plan that reached >= +0.5R before banking anything, and has since given back half
    # of that best, is flagged so the owner can take what was given by hand. Whether an AUTOMATIC version pays is
    # laptop M30 - until it passes, rules set at entry still manage the exit.
    ideas = [dict(x, _idea=True) for x in (_load(HM / "ai_plans.json", {}) or {}).get("ideas", [])]
    for pl in _load(HM / "plans.json", {}).get("plans", []) + ideas:
        R = pl.get("result") or {}
        if R.get("status") != "open" or R.get("legs"):
            continue                       # closed, or half already banked at +1R
        best, live = R.get("best_r"), R.get("live_r")
        if best is None or live is None or best < 0.5 or live > best / 2:
            continue
        alerts.append((f"giveback:{pl['id']}", "giveback",
                       f"{'Claude idea (not taken) ' if pl.get('_idea') else ''}{pl['coin']} {pl['side']}: was up +{best:.2f}R, now {live:+.2f}R - nothing banked yet. "
                       f"Taking some by hand is your call; the plan's rules will not."))
    try:   # standing laptop dive for every NEW watchlist coin (LAPTOP_BACKLOG S1)
        dq = BOT / "data" / "laptop_mining" / "server_exports" / "dive_requests.jsonl"
        asked = {json.loads(l).get("coin") for l in dq.read_text(encoding="utf-8").splitlines() if l.strip()
                 and json.loads(l).get("kind") == "watchlist"} if dq.exists() else set()
        with open(dq, "a", encoding="utf-8") as fh:
            for c in watch:
                if c not in asked:
                    fh.write(json.dumps({"ts": now, "kind": "watchlist", "coin": c}) + chr(10))
    except (OSError, ValueError):
        pass
    for c in watch:
        f = [x for x in ((scan.get(c) or {}).get("flags") or []) if not (x == "funding_hot" and c in always_hot)]
        if f:
            alerts.append(("watch:" + c, "watchlist", f"{c} (watchlist): {', '.join(f)}"))
    for c in sorted(set(watch) | {r["coin"] for r in rows}):
        em = (scan.get(c) or {}).get("exp_move")
        try:
            b = hl.candles(c, "1h", int((now - 30 * 3600) * 1000), int(now * 1000), ttl=300) or []
        except Exception:
            b = []
        b = [x for x in b if int(x["t"]) / 1000 + 3600 <= now]          # closed hours only
        if len(b) < 10:
            continue
        vols = sorted(float(x["v"]) * float(x["c"]) for x in b[:-1])
        med = vols[len(vols) // 2] or 0
        last = b[-1]
        o_, c_ = float(last["o"]), float(last["c"])
        chg = (c_ / o_ - 1) * 100
        vx = (float(last["v"]) * c_ / med) if med else 0
        if em and abs(chg) >= 0.5 * em and vx >= 2.5:
            hr = time.strftime("%H:00", time.gmtime(int(last["t"]) / 1000))
            alerts.append((f"wake:{c}:{int(last['t'])}", "waking_up",
                           f"{c}: {chg:+.1f}% in the {hr} UTC hour on {vx:.1f}x normal volume - waking up "
                           f"- worth a look; across 177 coins such surges slightly FADED over the next 4h-3d (laptop M11), so don't chase"))
    # new = not already logged today for this key+kind
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    seen = set()
    try:
        for l in LOG.read_text(encoding="utf-8").splitlines():
            o = json.loads(l)
            if o.get("day") == day:
                seen.add((o["key"], o["kind"]))
    except (OSError, ValueError):
        pass
    new = [a for a in alerts if (a[0], a[1]) not in seen]
    if new:
        with open(LOG, "a", encoding="utf-8") as f:
            for k, kind, msg in new:
                f.write(json.dumps({"ts": now, "day": day, "key": k, "kind": kind, "msg": msg}) + chr(10))
    state = {"updated": now, "holdings": rows, "alerts": [{"key": k, "kind": kd, "msg": m} for k, kd, m in alerts],
             "new": [{"key": k, "kind": kd, "msg": m} for k, kd, m in new]}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    tmp.replace(OUT)
    return state


if __name__ == "__main__":
    s = run()
    print(len(s["holdings"]), "holdings;", len(s["alerts"]), "alerts;", len(s["new"]), "new")
    for a in s["alerts"]:
        print(" -", a["kind"], a["msg"])
