"""Position watch (owner 10-14: "how can we be extremely proactive?").

Every hivemind cycle: look at everything the owner holds (bot-run owner positions + plans simulated on live prices)
and his watchlist, and raise a short alert only when something CHANGED or needs eyes:
  near_stop     price within 0.5 expected daily moves of the stop
  near_target   price within 0.3 expected daily moves of the target
  hot_flag      a held coin turned funding_hot (replicated: bigger moves, more stop hits - sizing, not direction)
  time_limit    the plan's own time limit is under 6 hours away
  watchlist     a watchlist coin carries a scanner flag
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
                    float(p.get("tp2") or pl.get("target") or 0) or None, exp))
    for s in _load(HM / "owner_plan_sims.json", {}).get("sims", []):
        if s.get("status") == "open" and s.get("bot_traded") is False:
            out.append(("simulated", "sim:" + s["plan_id"], s["coin"], s["side"], s["entry"], s["stop"], s["target"],
                        s.get("expires_ts")))
    return out


def run():
    now = time.time()
    scan = {r["coin"]: r for r in _load(HM / "scan.json", {}).get("coins", [])}
    try:
        mids = hl.post({"type": "allMids"}, ttl=30) or {}
    except Exception:
        mids = {}
    watch = _load(HM / "owner_watchlist.json", [])
    rows, alerts = [], []
    for src, key, coin, side, entry, stop, target, exp in holdings():
        px = float(mids.get(coin) or 0) or None
        sc = scan.get(coin) or {}
        em = sc.get("exp_move")
        sg = 1 if side == "LONG" else -1
        row = {"src": src, "key": key, "coin": coin, "side": side, "entry": entry, "stop": stop, "target": target,
               "px": px, "exp_move": em, "flags": sc.get("flags") or [], "expires_ts": exp}
        if px:
            row["r"] = round(sg * (px - entry) / abs(entry - stop), 2) if entry != stop else None
            row["to_stop_pct"] = round(abs(px - stop) / px * 100, 2)
            row["to_target_pct"] = round(abs(target - px) / px * 100, 2) if target else None
            if em:
                row["to_stop_em"] = round(row["to_stop_pct"] / em, 2)
                if row["to_stop_em"] <= NEAR_STOP_EM:
                    alerts.append((key, "near_stop", f"{coin} {side}: {row['to_stop_pct']}% from your stop "
                                                     f"({row['to_stop_em']} of a normal day), now {row['r']:+}R"))
                if row["to_target_pct"] is not None and row["to_target_pct"] / em <= NEAR_TGT_EM:
                    alerts.append((key, "near_target", f"{coin} {side}: {row['to_target_pct']}% from your target, now {row['r']:+}R"))
        if "funding_hot" in row["flags"]:
            alerts.append((key, "hot_flag", f"{coin}: 'longs paying a lot' is on - bigger moves and more stop hits "
                                            f"(replicated). Size/stop room, not direction."))
        if exp and 0 < exp - now <= TIME_LIMIT_H * 3600:
            alerts.append((key, "time_limit", f"{coin} {side}: your plan's time limit is in {(exp - now) / 3600:.1f}h"))
        rows.append(row)
    for c in watch:
        f = (scan.get(c) or {}).get("flags") or []
        if f:
            alerts.append(("watch:" + c, "watchlist", f"{c} (watchlist): {', '.join(f)}"))
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
