"""Automatic trade journal from the owner's real Hyperliquid fills.

Every cycle: read the owner's PUBLIC address (data/hivemind/owner_address.txt, set from the terminal), pull new
fills (userFillsByTime), and log each one with a snapshot of what the hivemind said about that coin at the time
(trend, range position, levels nearby, expected move, safe leverage, squeeze odds, voice agreement, chief lean).
Fills are then rebuilt into round-trip trades per coin (position goes 0 -> nonzero -> 0), with P&L net of fees,
holding time and the conditions at entry. Stats by condition show where the owner trades well.

Read-only on Hyperliquid (public info endpoint, no keys). Writes only under data/hivemind/.
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
HM = BOT / "data" / "hivemind"
ADDR = HM / "owner_address.txt"
FILLS = HM / "journal_fills.jsonl"
STATE = HM / "journal_state.json"
OUT = HM / "journal.json"


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def snapshot(coin):
    """What the hivemind said about this coin at the latest cycle (taken within ~15 min of the fill)."""
    st = _load(HM / "state" / f"{coin}.json", None)
    if not st:
        return {"in_hivemind": False}
    m, r, c = st.get("market") or {}, st.get("risk") or {}, st.get("consensus") or {}
    chief = ((_load(HM / "chief_latest.json", {}) or {}).get("coins") or {}).get(coin) or {}
    rng = (m.get("range_20d") or {})
    return {
        "in_hivemind": True,
        "structure": "up" if "structure UP" in (m.get("structure") or "") else "down",
        "pullback": "pullback" in (m.get("structure") or "") or "bounce" in (m.get("structure") or ""),
        "range_pos": rng.get("position"),
        "expected_move_pct": (st.get("vol") or {}).get("next_day_move_pct"),
        "safe_lev_long": (r.get("long") or {}).get("max_leverage"),
        "safe_lev_short": (r.get("short") or {}).get("max_leverage"),
        "squeeze_long": (r.get("long") or {}).get("squeeze_pct"),
        "squeeze_short": (r.get("short") or {}).get("squeeze_pct"),
        "move_size": c.get("move_size"),
        "bull_families": c.get("bull_families"), "bear_families": c.get("bear_families"),
        "chief_lean": chief.get("lean"), "chief_conviction": chief.get("conviction"),
    }


def pull(addr, since_ms):
    """All fills since since_ms; the endpoint caps a response at 2000, so page forward by time."""
    import hl
    out, start, end = [], int(since_ms), int(time.time() * 1000)
    for _ in range(20):
        page = hl.post({"type": "userFillsByTime", "user": addr, "startTime": start, "endTime": end}, ttl=0) or []
        out.extend(page)
        if len(page) < 2000:
            break
        start = max(f["time"] for f in page) + 1
    return out


def rebuild(fills):
    """Round trips per coin: a trade opens when the position leaves 0 and closes when it returns to 0."""
    by = defaultdict(list)
    for f in sorted(fills, key=lambda x: x["time"]):
        by[f["coin"]].append(f)
    trades, open_ = [], []
    for coin, fs in by.items():
        cur = None
        for f in fs:
            sz = float(f["sz"]) * (1 if f["side"] == "B" else -1)
            start = float(f.get("startPosition") or 0)
            end = start + sz
            if cur is None and abs(start) < 1e-12:
                cur = {"coin": coin, "side": "LONG" if sz > 0 else "SHORT", "open_time": f["time"],
                       "entry_fills": [], "exit_fills": [], "pnl": 0.0, "fees": 0.0, "max_size": 0.0,
                       "context": f.get("_ctx")}
            if cur is None:
                continue   # the journal started mid-position; skip until flat
            leg = cur["entry_fills"] if abs(end) > abs(start) else cur["exit_fills"]
            leg.append((float(f["px"]), abs(float(f["sz"]))))
            cur["pnl"] += float(f.get("closedPnl") or 0)
            cur["fees"] += float(f.get("fee") or 0)
            cur["max_size"] = max(cur["max_size"], abs(end))
            if abs(end) < 1e-12:
                cur["close_time"] = f["time"]
                trades.append(cur)
                cur = None
        if cur is not None:
            open_.append(cur)

    def vwap(legs):
        q = sum(s for _, s in legs)
        return sum(p * s for p, s in legs) / q if q else None

    out = []
    for t in trades + open_:
        e, x = vwap(t["entry_fills"]), vwap(t["exit_fills"])
        out.append({"coin": t["coin"], "side": t["side"], "entry": e, "exit": x,
                    "open": datetime.fromtimestamp(t["open_time"] / 1000, timezone.utc).isoformat(timespec="minutes"),
                    "close": (datetime.fromtimestamp(t["close_time"] / 1000, timezone.utc).isoformat(timespec="minutes")
                              if t.get("close_time") else None),
                    "hold_h": round((t["close_time"] - t["open_time"]) / 3.6e6, 1) if t.get("close_time") else None,
                    "net_pnl": round(t["pnl"] - t["fees"], 2), "fees": round(t["fees"], 2),
                    "notional": round((e or 0) * t["max_size"], 2), "context": t.get("context"),
                    "status": "closed" if t.get("close_time") else "open"})
    return out


def stats(trades):
    closed = [t for t in trades if t["status"] == "closed"]
    if not closed:
        return {"n": 0}
    s = {"n": len(closed), "win_rate": round(sum(t["net_pnl"] > 0 for t in closed) / len(closed), 3),
         "net_pnl": round(sum(t["net_pnl"] for t in closed), 2),
         "avg_pnl": round(sum(t["net_pnl"] for t in closed) / len(closed), 2), "by": {}}

    def bucket(name, f):
        g = defaultdict(list)
        for t in closed:
            k = f(t)
            if k is not None:
                g[k].append(t["net_pnl"])
        s["by"][name] = {k: {"n": len(v), "win_rate": round(sum(x > 0 for x in v) / len(v), 2),
                             "net": round(sum(v), 2)} for k, v in g.items()}

    ctx = lambda t: t.get("context") or {}
    bucket("side", lambda t: t["side"])
    bucket("with_structure", lambda t: None if not ctx(t).get("in_hivemind") else
           ("with trend" if (ctx(t)["structure"] == "up") == (t["side"] == "LONG") else "against trend"))
    bucket("chief_agreed", lambda t: None if not ctx(t).get("chief_lean") else
           ("chief agreed" if ctx(t)["chief_lean"] == t["side"] else
            "chief neutral" if ctx(t)["chief_lean"] == "NEUTRAL" else "chief disagreed"))
    bucket("range_zone", lambda t: None if ctx(t).get("range_pos") is None else
           ("lower third" if ctx(t)["range_pos"] < 1 / 3 else "upper third" if ctx(t)["range_pos"] > 2 / 3 else "middle"))
    bucket("hold", lambda t: None if t["hold_h"] is None else
           ("< 4h" if t["hold_h"] < 4 else "4-48h" if t["hold_h"] <= 48 else "> 48h"))
    return s


def main():
    HM.mkdir(parents=True, exist_ok=True)
    try:
        addr = ADDR.read_text(encoding="utf-8").strip()
    except OSError:
        OUT.write_text(json.dumps({"enabled": False, "note": "No address yet: paste your public address in the terminal's account panel."}),
                       encoding="utf-8")
        return None
    st = _load(STATE, {}) or {}
    if st.get("addr") != addr:
        st = {"addr": addr, "since": int((time.time() - 90 * 86400) * 1000), "seen": []}   # first run: last 90 days
    new = pull(addr, st["since"])
    seen = set(st.get("seen", []))
    added = 0
    with open(FILLS, "a", encoding="utf-8") as f:
        for x in sorted(new, key=lambda z: z["time"]):
            key = f"{x.get('tid')}|{x.get('oid')}|{x['time']}"
            if key in seen:
                continue
            seen.add(key)
            fresh = time.time() * 1000 - x["time"] < 30 * 60 * 1000
            x["_ctx"] = snapshot(x["coin"]) if fresh else {"in_hivemind": False, "note": "backfilled: no snapshot"}
            x["_addr"] = addr
            f.write(json.dumps(x) + "\n")
            added += 1
            st["since"] = max(st["since"], x["time"] + 1)
    st["seen"] = list(seen)[-5000:]
    STATE.write_text(json.dumps(st), encoding="utf-8")
    fills = []
    try:
        fills = [json.loads(l) for l in FILLS.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        pass
    fills = [x for x in fills if x.get("_addr") == addr]
    trades = rebuild(fills)
    out = {"enabled": True, "address": addr[:6] + "…" + addr[-4:], "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "fills": len(fills), "added_this_run": added, "trades": trades[-60:], "stats": stats(trades)}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    r = main()
    print(json.dumps(r and {k: r[k] for k in ("fills", "added_this_run", "stats")}, indent=1) if r else "no address set")
