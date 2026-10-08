"""Owner trade plans: log a planned trade from the terminal, then grade it against what price actually did.

No wallet needed. A plan is (coin, side, entry, stop, target, entry type) plus what the hivemind said at that
moment. resolve() walks Hyperliquid 5-minute candles from the plan's creation:
  - market plans fill at the logged price immediately; limit plans fill the first time price touches the entry,
    and expire unfilled after `entry_window_h` (default 24h)
  - after the fill: stop or target, whichever is touched first; if one candle touches both, the STOP is
    assumed (conservative); otherwise closed at the candle close after `max_hold_h` (default 48h, the tested setup)
  - result in R (1R = entry-to-stop distance), net of 0.09% round-trip taker fees, plus best/worst excursion
Writes data/hivemind/plans.json (every plan with status + the track record by setup and side).
"""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"
PLANS = HM / "owner_plans.jsonl"       # append-only: creations and cancels
OUT = HM / "plans.json"
REVIEWS = HM / "owner_plan_reviews.jsonl"   # the bot's AI second opinion on each plan
FEE_RT = 0.0009
SETUPS = ["50d pullback", "breakout", "breakdown", "range fade", "liq magnet", "trend continuation", "other"]


def _rows():
    try:
        return [json.loads(l) for l in PLANS.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def _context(coin):
    """What the hivemind said about the coin when the plan was made (empty for coins it doesn't analyse)."""
    try:
        st = json.loads((HM / "state" / "_all.json").read_text(encoding="utf-8"))
        c = (st.get("coins") or {}).get(coin) or {}
    except Exception:
        return {}
    m, v, cs = c.get("market") or {}, c.get("vol") or {}, c.get("consensus") or {}
    try:
        ch = (json.loads((HM / "chief_latest.json").read_text(encoding="utf-8")).get("coins") or {}).get(coin) or {}
    except Exception:
        ch = {}
    return {"trend_up": "structure UP" in (m.get("structure") or ""), "structure_4h": (c.get("tf4h") or {}).get("structure_4h"),
            "exp_move_pct": v.get("next_day_move_pct"), "range_pos": (m.get("range_20d") or {}).get("position"),
            "funding_h": m.get("funding_hourly"), "move_size": cs.get("move_size"),
            "chief_lean": ch.get("lean"), "chief_conv": ch.get("conviction")}


def create(p):
    coin = str(p.get("coin", "")).strip()[:20]
    side = str(p.get("side", "")).upper()
    try:
        entry, stop, target = float(p["entry"]), float(p["stop"]), float(p["target"])
        price = float(p.get("price") or entry)
    except (KeyError, TypeError, ValueError):
        raise ValueError("entry, stop and target must be numbers")
    if not coin or side not in ("LONG", "SHORT"):
        raise ValueError("coin and side (LONG/SHORT) required")
    sg = 1 if side == "LONG" else -1
    if sg * (entry - stop) <= 0 or sg * (target - entry) <= 0:
        raise ValueError("stop must be on the losing side of entry and target on the winning side")
    etype = "market" if p.get("entry_type") == "market" else "limit"
    row = {"kind": "plan", "id": uuid.uuid4().hex[:10], "ts": time.time(), "coin": coin, "side": side,
           "entry": price if etype == "market" else entry, "stop": stop, "target": target, "price_at_plan": price,
           "entry_type": etype, "entry_window_h": float(p.get("entry_window_h") or 24),
           "max_hold_h": float(p.get("max_hold_h") or 48), "leverage": float(p.get("leverage") or 1),
           "risk_usd": float(p.get("risk_usd") or 0), "setup": str(p.get("setup") or "other")[:40],
           "reason": str(p.get("reason") or "")[:300], "context": _context(coin)}
    HM.mkdir(parents=True, exist_ok=True)
    with open(PLANS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


REVIEW_SYSTEM = """You are the WAGMI trading bot's desk, giving the owner a SECOND OPINION on a trade plan they wrote
for themselves (a discretionary swing trader on Hyperliquid perps). You get the plan and every hivemind voice for
the coin. Be honest and specific; you are graded forward against real prices, and so is the owner.
Known facts from forward grading: no single voice or AI agent has proven directional skill; move SIZE is
forecastable (risk block: stop ~2x expected move, target 0.5R, 48h; safe leverage); stops inside one expected daily
move lost ~0.4R/trade; the 50-day average holds from above more than chance; the 20-day low breaks MORE than chance.
Judge: is the stop survivable (vs expected move and liquidation clusters), is the target reachable, is leverage safe,
does the evidence conflict with the direction. Your own stop/target must follow the tested geometry unless a level
clearly argues otherwise. Write for a visual learner: lead with one plain sentence.
Output ONLY JSON:
{"verdict": "take|adjust|skip", "agrees_with_direction": true|false|null, "confidence": 1-5,
 "summary": "<=200 chars, one plain sentence first",
 "bot_stop": <number>, "bot_target": <number>,
 "risks": ["<=90 chars each, max 3"], "would_change_mind": "<=120 chars"}"""


def review(plan):
    """Ask the bot's AI (Opus via the CLI subscription) for a second opinion; appends to REVIEWS. Slow (~1 min)."""
    import os
    import sys
    sys.path.insert(0, str(BOT))
    from llm.claude_cli_client import call_agent
    try:
        st = json.loads((HM / "state" / "_all.json").read_text(encoding="utf-8"))
        coin = (st.get("coins") or {}).get(plan["coin"]) or {}
        coin = {k: v for k, v in coin.items() if k != "deep"}
        shared = st.get("shared")
    except Exception:
        coin, shared = {}, None
    keep = ("coin", "side", "entry", "stop", "target", "entry_type", "leverage", "setup", "reason", "price_at_plan")
    prompt = json.dumps({"plan": {k: plan.get(k) for k in keep}, "hivemind": coin, "market": shared}, default=str)[:40000]
    row = {"id": plan["id"], "ts": time.time()}
    try:
        resp = call_agent(user_prompt=prompt, system_prompt=REVIEW_SYSTEM, model="opus",
                          max_budget_usd=float(os.getenv("CLI_MAX_BUDGET_USD", "5.00")), timeout=300, allow_tools=False)
        if not resp.ok:
            raise RuntimeError(resp.error)
        raw = (getattr(resp, "text", None) or getattr(resp, "content", "")).strip()
        rv = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        sg = 1 if plan["side"] == "LONG" else -1
        for k in ("bot_stop", "bot_target"):
            try:
                rv[k] = float(rv[k])
            except (KeyError, TypeError, ValueError):
                rv[k] = None
        if rv["bot_stop"] is not None and sg * (plan["entry"] - rv["bot_stop"]) <= 0:
            rv["bot_stop"] = None
        if rv["bot_target"] is not None and sg * (rv["bot_target"] - plan["entry"]) <= 0:
            rv["bot_target"] = None
        row["review"] = rv
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"[:200]
    with open(REVIEWS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + chr(10))
    return row


def _reviews():
    out = {}
    try:
        for l in REVIEWS.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                out[r["id"]] = r
    except OSError:
        pass
    return out


EXEC_STATE = HM / "owner_orders_state.json"   # bot paper-execution state (core/owner_plan_exec.py)
EXEC_FILLS = HM / "owner_fills.jsonl"         # bot paper-execution legs: open / partial / final


def _exec_results(last_px=None):
    """What the bot made of each plan when it paper-traded it (OWNER_PLAN_EXEC). {plan_id: exec_result}.

    status: queued|open|closed|blocked|rejected|stale|expired|cancelled. r is net of the bot's real
    fees on the bot's own fill; for an open position it includes the unrealized part at `last_px`.
    """
    try:
        st = json.loads(EXEC_STATE.read_text(encoding="utf-8")).get("plans") or {}
    except (OSError, ValueError):
        st = {}
    fills = {}
    try:
        for l in EXEC_FILLS.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    r = json.loads(l)
                except ValueError:
                    continue
                if r.get("plan_id"):
                    fills.setdefault(r["plan_id"], []).append(r)
    except OSError:
        pass
    out = {}
    for pid in set(st) | set(fills):
        rec = st.get(pid) or {}
        legs = fills.get(pid, [])
        closes = [f for f in legs if f.get("kind") in ("partial", "final")]
        final = next((f for f in reversed(closes) if f.get("kind") == "final"), None)
        opened = next((f for f in legs if f.get("kind") == "open"), None)
        status = "closed" if final else rec.get("status") or ("open" if opened else "queued")
        realized = round(sum(float(f.get("pnl") or 0) for f in closes), 4)
        risk = float((opened or {}).get("risk_usd") or rec.get("risk_usd") or 0)
        er = {"status": status, "reason": rec.get("reason", ""), "fill_price": rec.get("fill_price") or (opened or {}).get("entry"),
              "fills": [{k: f.get(k) for k in ("kind", "exit", "qty", "pnl", "r", "reason", "ts")} for f in closes],
              "pnl_usd": None, "r": None}
        if final:
            er["pnl_usd"] = final.get("total_pnl", realized)
            er["r"] = final.get("total_r")
        elif status == "open" and opened:
            unreal = 0.0
            px = (last_px or {}).get(pid)
            if px:
                sg = 1 if opened.get("side") == "LONG" else -1
                left = float(opened.get("qty") or 0) - sum(float(f.get("qty") or 0) for f in closes)
                unreal = (px - float(opened["entry"])) * sg * max(left, 0.0) * float(opened.get("pnl_lev") or 1.0)
            er["pnl_usd"] = round(realized + unreal, 4)
            er["r"] = round((realized + unreal) / risk, 3) if risk > 0 else None
            er["live"] = True
        out[pid] = er
    return out


def cancel(pid):
    with open(PLANS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "cancel", "id": str(pid)[:20], "ts": time.time()}) + "\n")


def _walk(pl, bars, now):
    """bars: HL 5m candles from the plan's creation. Returns the plan's status dict."""
    sg = 1 if pl["side"] == "LONG" else -1
    e, st, tg = pl["entry"], pl["stop"], pl["target"]
    risk = abs(e - st)
    fill_t = pl["ts"] if pl["entry_type"] == "market" else None
    out = {"status": "waiting"}
    lo_x = hi_x = 0.0   # worst / best excursion in R
    for b in bars:
        t0, h, l, c = b["t"] / 1000, float(b["h"]), float(b["l"]), float(b["c"])
        if t0 < pl["ts"] - 1:
            continue    # candle opened before the plan existed: its range may predate it
        if fill_t is None:
            if t0 > pl["ts"] + pl["entry_window_h"] * 3600:
                return {"status": "expired", "note": "entry never reached"}
            if l <= e <= h:
                fill_t = t0
            else:
                continue
        best, worst = (h - e) * sg / risk, (l - e) * sg / risk
        if sg < 0:
            best, worst = (e - l) / risk, (e - h) / risk
        hi_x, lo_x = max(hi_x, best), min(lo_x, worst)
        hit_stop = (l <= st) if sg > 0 else (h >= st)
        hit_tgt = (h >= tg) if sg > 0 else (l <= tg)
        if hit_stop or hit_tgt:
            exit_px = st if hit_stop else tg
            return _close(pl, "lost" if hit_stop else "won", exit_px, t0, fill_t, hi_x, lo_x)
        if t0 + 300 >= fill_t + pl["max_hold_h"] * 3600:
            return _close(pl, "timed out", c, t0 + 300, fill_t, hi_x, lo_x)
    if fill_t is not None:
        last = float(bars[-1]["c"]) if bars else e
        out = {"status": "open", "filled_at": fill_t, "live_r": round((last - e) * sg / risk, 2),
               "best_r": round(hi_x, 2), "worst_r": round(lo_x, 2)}
    elif now > pl["ts"] + pl["entry_window_h"] * 3600:
        out = {"status": "expired", "note": "entry never reached"}
    return out


def _close(pl, status, exit_px, t, fill_t, hi_x, lo_x):
    sg = 1 if pl["side"] == "LONG" else -1
    risk = abs(pl["entry"] - pl["stop"])
    gross = (exit_px - pl["entry"]) * sg / risk
    fee_r = FEE_RT * pl["entry"] / risk
    return {"status": status, "filled_at": fill_t, "closed_at": t, "exit": exit_px, "r_gross": round(gross, 3),
            "r": round(gross - fee_r, 3), "fee_r": round(fee_r, 3), "best_r": round(hi_x, 2), "worst_r": round(lo_x, 2),
            "hold_h": round((t - fill_t) / 3600, 1)}


def _stats(rows):
    def agg(xs):
        rs = [x["result"]["r"] for x in xs]
        if not rs:
            return {"n": 0}
        return {"n": len(rs), "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3), "avg_r": round(sum(rs) / len(rs), 3),
                "total_r": round(sum(rs), 2)}
    done = [x for x in rows if "r" in x.get("result", {})]
    out = {"all": agg(done), "by_setup": {}, "by_side": {}, "by_chief": {}}
    for k in sorted({x["setup"] for x in done}):
        out["by_setup"][k] = agg([x for x in done if x["setup"] == k])
    for k in ("LONG", "SHORT"):
        out["by_side"][k] = agg([x for x in done if x["side"] == k])
    rv = lambda x: ((x.get("review") or {}).get("review") or {})
    for k, fn in (("bot said take", lambda x: rv(x).get("verdict") == "take"),
                  ("bot said adjust", lambda x: rv(x).get("verdict") == "adjust"),
                  ("bot said skip", lambda x: rv(x).get("verdict") == "skip")):
        out.setdefault("by_review", {})[k] = agg([x for x in done if fn(x)])
    both = [x for x in done if "r" in (x.get("bot_result") or {})]
    if both:
        out["mine_vs_bot_levels"] = {"n": len(both), "mine_avg_r": round(sum(x["result"]["r"] for x in both) / len(both), 3),
                                     "bot_avg_r": round(sum(x["bot_result"]["r"] for x in both) / len(both), 3)}
    # Plan as written vs the SAME plan managed by the bot's exit logic (OWNER_PLAN_EXEC paper fills).
    ex = [x for x in done if (x.get("exec_result") or {}).get("status") == "closed"
          and (x.get("exec_result") or {}).get("r") is not None]
    if ex:
        pr = [x["result"]["r"] for x in ex]
        br = [x["exec_result"]["r"] for x in ex]
        out["by_exec"] = {"n": len(ex), "plan_avg_r": round(sum(pr) / len(ex), 3), "bot_avg_r": round(sum(br) / len(ex), 3),
                          "plan_total_r": round(sum(pr), 2), "bot_total_r": round(sum(br), 2),
                          "bot_better": sum(b > p for p, b in zip(pr, br))}
    else:
        out["by_exec"] = {"n": 0}
    for k, fn in (("with chief", lambda x: (x.get("context") or {}).get("chief_lean") == x["side"]),
                  ("against / no chief", lambda x: (x.get("context") or {}).get("chief_lean") != x["side"])):
        out["by_chief"][k] = agg([x for x in done if fn(x)])
    return out


def resolve(write=True):
    import hl
    rows = _rows()
    cancelled = {r["id"] for r in rows if r.get("kind") == "cancel"}
    try:
        prev = {p["id"]: p for p in json.loads(OUT.read_text(encoding="utf-8")).get("plans", [])}
    except Exception:
        prev = {}
    now = time.time()
    reviews = _reviews()
    plans = []
    last_px = {}
    for pl in (r for r in rows if r.get("kind") == "plan"):
        old = (prev.get(pl["id"]) or {}).get("result") or {}
        if old.get("status") in ("won", "lost", "timed out", "expired"):
            res = old
        elif pl["id"] in cancelled and old.get("status") != "open":
            res = {"status": "cancelled"}
        else:
            try:
                bars = hl.candles(pl["coin"], "5m", pl["ts"] * 1000 - 300000, ttl=50)
                res = _walk(pl, bars or [], now)
                if bars:
                    last_px[pl["id"]] = float(bars[-1]["c"])
            except Exception as e:
                res = dict(old or {"status": "waiting"}, error=str(e)[:120])
            if pl["id"] in cancelled and res.get("status") == "waiting":
                res = {"status": "cancelled"}
        rv = (reviews.get(pl["id"]) or {}).get("review")
        bot_res = (prev.get(pl["id"]) or {}).get("bot_result") or {}
        if rv and rv.get("bot_stop") and rv.get("bot_target") and res.get("status") not in ("waiting", "expired", "cancelled") and bot_res.get("status") not in ("won", "lost", "timed out"):
            try:
                alt = dict(pl, stop=rv["bot_stop"], target=rv["bot_target"])
                bot_res = _walk(alt, hl.candles(pl["coin"], "5m", pl["ts"] * 1000 - 300000, ttl=50) or [], now)
            except Exception:
                pass
        plans.append(dict(pl, result=res, review=(reviews.get(pl["id"]) or None), bot_result=bot_res or None))
    execs = _exec_results(last_px)
    for p in plans:
        p["exec_result"] = execs.get(p["id"])
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "plans": plans, "stats": _stats(plans),
           "setups": SETUPS}
    if write:
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(out), encoding="utf-8")
        tmp.replace(OUT)
    return out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    o = resolve()
    print(json.dumps(o["stats"], indent=1))
    for p in o["plans"][-10:]:
        print(p["coin"], p["side"], p["setup"], p["result"])
