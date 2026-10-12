"""AI trade ideas: twice a day Opus proposes up to 2 complete swing trades, graded exactly like the owner's plans.

Why: the owner often has no read of his own. Instead of a blank planner he gets concrete, risk-sized ideas he can
adopt or pass on, and every idea is graded forward (plans.py::_walk: HL 5m candles, stop-first ties, adverse-side
fill-candle rule, 48h window, 9 bps fees, R units). Ideas live in data/hivemind/ai_plans.jsonl, separate from the
owner's record; adopting one in the terminal copies it into his plans (setup "ai idea").
Never trades anything itself.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plans  # noqa: E402

BOT = HERE.parents[1]
HM = BOT / "data" / "hivemind"
IDEAS = HM / "ai_plans.jsonl"
OUT = HM / "ai_plans.json"
EVERY_H = 4.0   # was 11.5; owner 10-12: digest the data into trades more often (~6 Opus calls/day)

SYSTEM = """You are the WAGMI desk's trade-idea generator for a discretionary swing trader on Hyperliquid perps
(1-2 day holds). He often has no read of his own, so you propose up to TWO complete trades he could take, or NONE if
nothing is worth it (none is a perfectly good answer). Every idea is graded forward on real prices, so be honest.
Facts from forward grading: no single voice or AI has proven directional skill; move SIZE is forecastable (each coin's
vol/risk blocks); stops tighter than a normal day's move lose ~0.13-0.20R/trade; no target size or time limit tested
better than another; liquidation clusters may be mildly visited by price (+3-8 pts vs random, unproven) and are a bad
place for a stop; the 20-day low breaks more than chance. So: stop OUTSIDE one expected daily move and not sitting on a
liquidation cluster, target at a real level, leverage within the coin's safe leverage, prefer limit entries at a level
over chasing. Use only coins present in the input. Plain words for a visual learner.
The owner wants more attention on SMALLER perps that are moving (scanner coins with a high vol_rank / a
"momentum_small" flag): always look at them seriously alongside the majors, and when one of your ideas is a small
cap, size it for its bigger expected move and thinner book (lower leverage, wider stop). Tested (laptop M2, 164 coins, corrected 10-11):
a small cap that just broke out above its 20-day high tends to FALL BACK vs other small caps over the next 1-7 days, and
the further above the high the worse (8%+ above: about -15% vs peers in 3 days). So NEVER propose a long on a small cap
sitting well above its 20-day high; a small-cap idea needs its own reason (level, positioning, funding). A short fading
such a breakout is NOT proven (funding and thin books may eat it) - only if it also has its own reason, with a wide stop.
CONTEXT LABELS (be honest about them): oi_chg_4h_pct / oi_chg_24h_pct = open-interest change, UNTESTED as a signal
(a sealed test is accruing); depth_1pct_usd / spread_bps = how much size the book holds within 1% - execution context:
size down where thin, never a direction signal; funding_hot flag = TESTED: bigger move and stop risk, not direction;
oi_usd vs vol24_usd = how crowded a coin is relative to its trading. Coins with owner_watchlist=true are coins the
owner is personally interested in: always assess them (an idea, or one line in "note" on why not).
Output ONLY JSON:
{"ideas": [{"coin": "SOL", "side": "LONG|SHORT", "entry_type": "limit|market", "entry": <num>, "stop": <num>,
  "target": <num>, "leverage": <num>, "confidence": 1-5, "setup": "<=30 chars",
  "why": "<=220 chars, one plain sentence first", "invalidation": "<=100 chars", "used": ["which context fields drove this idea"]}],
 "note": "<=160 chars: why these, or why none"}"""


def _rows():
    try:
        return [json.loads(l) for l in IDEAS.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def _positioning(coins):
    """Per-coin context the idea generator never saw before (data-to-trades audit, 10-12): open-interest change over
    ~4h and ~24h (all perps, ctx_snapshots) and order-book depth within 1% (depth_all). Labelled honestly: OI change
    is UNTESTED (PREREG_OI sealed, accruing); depth is execution context, not direction."""
    import gzip
    want, out = set(coins), {}
    snaps = sorted((BOT / "data" / "ctx_snapshots").glob("*.jsonl.gz"))[-2:]
    hist = {}
    for f in snaps:
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        o = json.loads(ln)
                    except ValueError:
                        continue
                    if o.get("c") in want:
                        hist.setdefault(o["c"], []).append((o["t"], float(o["oi"]) * float(o["mark"])))
        except OSError:
            continue
    for c, pts in hist.items():
        pts.sort()
        t1, v1 = pts[-1]
        def ago(h):
            old = [v for t, v in pts if t <= t1 - h * 3600]
            return round((v1 / old[-1] - 1) * 100, 1) if old and old[-1] else None
        out[c] = {"oi_usd": round(v1), "oi_chg_4h_pct": ago(4), "oi_chg_24h_pct": ago(24)}
    try:
        with open(BOT / "data" / "hivemind" / "depth_all.jsonl", "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 400_000))
            tail = fh.read().decode("utf-8", "replace").splitlines()[1:]
        for ln in tail:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if o.get("coin") in want:
                out.setdefault(o["coin"], {}).update(depth_1pct_usd={"bid": o.get("bid_usd_1.0"), "ask": o.get("ask_usd_1.0")},
                                                     spread_bps=o.get("spread_bps"))
    except OSError:
        pass
    return out


def _prompt():
    import chief
    st = json.loads((HM / "state" / "_all.json").read_text(encoding="utf-8"))
    hive = json.loads(chief._compact(st))
    try:
        watch = [str(c).upper() for c in json.loads((HM / "owner_watchlist.json").read_text(encoding="utf-8"))]
    except Exception:
        watch = []
    try:
        scan = json.loads((HM / "scan.json").read_text(encoding="utf-8"))
        keep = ("coin", "px", "chg_24h", "ret_7d", "exp_move", "trend_up", "d50_pct", "hi20", "lo20", "range_pos",
                "funding_h", "vol_ratio", "safe_lev_long", "safe_lev_short", "flags", "oi_usd", "vol24_usd", "rv5", "rv22")
        allc = scan.get("coins", [])
        scan_rows = [{k: r.get(k) for k in keep + ("vol_rank",)} for r in allc[:25]]
        # make sure the moving small caps are in view even if they rank low on the scanner's sort
        extra = [r for r in allc[25:] if "momentum_small" in r.get("flags", [])]
        scan_rows += [{k: r.get(k) for k in keep + ("vol_rank",)} for r in extra[:8]]
        # the owner's own watchlist always in view
        have = {r["coin"] for r in scan_rows}
        scan_rows += [dict({k: r.get(k) for k in keep + ("vol_rank",)}, owner_watchlist=True)
                      for r in allc if r["coin"] in watch and r["coin"] not in have]
        for r in scan_rows:
            if r["coin"] in watch:
                r["owner_watchlist"] = True
        pos = _positioning([r["coin"] for r in scan_rows])
        for r in scan_rows:
            r.update(pos.get(r["coin"], {}))
    except Exception:
        scan_rows = []
    return json.dumps({"hivemind_majors": hive, "scanner": scan_rows}, default=str)[:90000]


def generate(force=False):
    rows = _rows()
    last = max((r["ts"] for r in rows if r.get("kind") == "run"), default=0)
    if not force and time.time() - last < EVERY_H * 3600:
        return None
    sys.path.insert(0, str(BOT))
    from llm.claude_cli_client import call_agent
    import hl
    resp = call_agent(user_prompt=_prompt(), system_prompt=SYSTEM, model="opus",
                      max_budget_usd=float(os.getenv("CLI_MAX_BUDGET_USD", "5.00")), timeout=600, allow_tools=False)
    now = time.time()
    run = {"kind": "run", "ts": now, "ok": bool(resp.ok)}
    out = []
    if resp.ok:
        raw = (getattr(resp, "text", None) or getattr(resp, "content", "")).strip()
        try:
            got = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        except ValueError:
            got = {"ideas": []}
        run["note"] = str(got.get("note") or "")[:200]
        mids = hl.post({"type": "allMids"}, ttl=30)
        for i in (got.get("ideas") or [])[:2]:
            try:
                coin, side = str(i["coin"]).upper(), str(i["side"]).upper()
                entry, stop, target = float(i["entry"]), float(i["stop"]), float(i["target"])
                px = float(mids[coin])
            except (KeyError, TypeError, ValueError):
                continue
            etype = "market" if i.get("entry_type") == "market" else "limit"
            if etype == "market":
                entry = px
            sg = 1 if side == "LONG" else -1
            if side not in ("LONG", "SHORT") or sg * (entry - stop) <= 0 or sg * (target - entry) <= 0:
                continue
            out.append({"kind": "plan", "source": "ai", "id": "ai" + uuid.uuid4().hex[:8], "ts": now, "coin": coin,
                        "side": side, "entry": entry, "stop": stop, "target": target, "price_at_plan": px,
                        "entry_type": etype, "entry_window_h": 24.0, "max_hold_h": 48.0,
                        "leverage": float(i.get("leverage") or 1), "confidence": int(i.get("confidence") or 1),
                        "setup": str(i.get("setup") or "")[:40], "reason": str(i.get("why") or "")[:260],
                        "invalidation": str(i.get("invalidation") or "")[:120],
                        "used": [str(u)[:40] for u in (i.get("used") or [])][:8]})
    else:
        run["error"] = str(resp.error)[:200]
    run["n"] = len(out)
    with open(IDEAS, "a", encoding="utf-8") as f:
        for r in out + [run]:
            f.write(json.dumps(r) + "\n")
    return run


def resolve():
    import hl
    rows = _rows()
    try:
        prev = {p["id"]: p for p in json.loads(OUT.read_text(encoding="utf-8")).get("ideas", [])}
    except Exception:
        prev = {}
    now, ideas = time.time(), []
    for pl in (r for r in rows if r.get("kind") == "plan"):
        old = (prev.get(pl["id"]) or {}).get("result") or {}
        if old.get("status") in ("won", "lost", "timed out", "expired"):
            res = old
        else:
            try:
                res = plans._walk(pl, hl.candles(pl["coin"], "5m", pl["ts"] * 1000 - 300000, ttl=50) or [], now)
            except Exception as e:
                res = dict(old or {"status": "waiting"}, error=str(e)[:100])
        ideas.append(dict(pl, result=res))
    done = [x["result"]["r"] for x in ideas if "r" in x["result"]]
    stats = {"n": len(done)}
    if done:
        stats.update(win_rate=round(sum(r > 0 for r in done) / len(done), 3), avg_r=round(sum(done) / len(done), 3),
                     total_r=round(sum(done), 2))
    runs = [r for r in rows if r.get("kind") == "run"]
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ideas": ideas, "stats": stats,
           "last_note": (runs[-1].get("note") if runs else None), "last_run": (runs[-1]["ts"] if runs else None)}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(OUT)
    return out


def run():
    try:
        generate()
    finally:
        return resolve()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(generate(force="--force" in sys.argv))
    o = resolve()
    print(o["stats"], o["last_note"])
    for i in o["ideas"][-4:]:
        print(i["coin"], i["side"], i["entry_type"], i["entry"], i["stop"], i["target"], i["confidence"], i["result"], "|", i["reason"])
