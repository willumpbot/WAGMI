"""Hivemind assembler: one state file per coin, every voice in the system.

Each run (every 15 min) writes data/hivemind/state/<SYM>.json and
data/hivemind/state/_all.json. Every voice says what it sees AND carries its
report card, so a reader (the owner, or the Opus chief analyst) can weight it:

  market      co-pilot DipRead: plain daily structure, range position, swing
              levels, ATR, RSI, funding  (measured context, no direction)
  history     how the CURRENT combination of readings behaved over the next
              5 days on these coins historically (tools/hivemind/basemap.py)
  weather     market-wide regime + breadth (co-pilot weather)
  deep        liquidation magnets + funding/OI trajectory (co-pilot eye_deep)
  context     decision-time features the graders use: book lean, funding
              side, session, BTC 4h (tools/live_grader.decision_context)
  agents      the bot's latest AI decision round on this coin, with each
              agent's live report card (data/agent_grades/live/live_scorecard.json)
  strategies  IC health of each strategy (muted = weight 0 in the ensemble)
  rules       active rules-manager rules that would apply to a LONG / SHORT now
  bot         the bot's open position on this coin, if any
  owner       the owner's logged calls on this coin and how they resolved

Read-only on everything it consults. Writes only under data/hivemind/.
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT))
sys.path.insert(0, str(BOT / "tools"))
sys.path.insert(0, str(BOT / "tools" / "copilot"))
os.environ.setdefault("WAGMI_SOURCE", "tool")

DATA = BOT / "data"
OUT = DATA / "hivemind" / "state"
SYMS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"]


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def _tail_jsonl(path, max_bytes=600_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - max_bytes))
            f.readline()
            out = []
            for raw in f:
                try:
                    out.append(json.loads(raw))
                except Exception:
                    continue
            return out
    except OSError:
        return []


# ── voices ────────────────────────────────────────────────────────────

def voice_market(client, sym):
    import copilot as cp
    d = cp.build_dip_read(client, sym)
    if not d.ok:
        return {"ok": False, "note": d.data_note}
    rng = None
    if d.swing_high and d.swing_low and d.swing_high > d.swing_low:
        rng = (d.price - d.swing_low) / (d.swing_high - d.swing_low)
    return {
        "ok": True, "price": d.price, "ret_1d_pct": _r(d.ret_1d_pct, 2), "ret_7d_pct": _r(d.ret_7d_pct, 2),
        "structure": d.structure_note, "trend_1d": d.trend_1d, "adx_1d": _r(d.adx_1d, 1),
        "range_20d": {"low": d.swing_low, "high": d.swing_high, "position": _r(rng, 3),
                      "pct_to_high": _r(d.dist_to_high_pct, 2), "pct_to_low": _r(d.dist_to_low_pct, 2)},
        "atr_pct_1d": _r(d.atr_pct_1d * 100 if d.atr_pct_1d and d.atr_pct_1d < 1 else d.atr_pct_1d, 2),
        "rsi_1d": _r(d.rsi_1d, 1), "bb_pos_1d": _r(d.bb_pos_1d, 2),
        "funding_note": d.funding_note, "funding_hourly": d.funding_rate,
        "copilot_action": d.action, "copilot_action_reason": (d.action_reason or "")[:200],
        "warnings": d.warnings[:4],
        "report_card": "measured context; no directional edge claimed (SIGNAL_SCORECARD.md)",
    }


def voice_weather(client):
    import weather as w
    mw = w.compute_market_weather(client)
    return {"regime": mw.regime, "breadth_pct": _r(mw.breadth_pct, 1), "btc_price": mw.btc_price,
            "line": mw.line, "session": w.session_vol_context()}


def voice_deep(sym, price):
    import eye_deep as ed
    out = {}
    try:
        out["liquidation_magnets"] = [l.strip() for l in ed.liq_magnet_lines(sym, price or 0) if l.strip()][:8]
    except Exception as e:
        out["liquidation_magnets"] = [f"unavailable: {e}"]
    try:
        out["funding_oi"] = [l.strip() for l in ed.funding_oi_lines(sym) if l.strip()][:8]
    except Exception as e:
        out["funding_oi"] = [f"unavailable: {e}"]
    return out


def voice_context(sym, side_hint=None):
    import live_grader as lg
    t0 = time.time()
    out = {}
    for side in ("LONG", "SHORT"):
        c = lg.decision_context(sym, side, t0)
        bt = lg.btc_trend_context(side, t0)
        if bt:
            c["btc4h"] = bt
        out[side] = c
    return out


def voice_agents(sym, scorecard):
    rows = _tail_jsonl(DATA / "llm" / "agent_performance.jsonl", 1_500_000)
    rounds = {}
    for r in rows:
        if r.get("type") != "decision" or r.get("symbol") != sym:
            continue
        ctx = r.get("ctx") or {}
        if ctx.get("trigger") != "llm_first_entry":
            continue   # event rounds (and untagged pre-10-08 rounds) are filed under an arbitrary coin
        rounds.setdefault(r["pipeline_id"], {})[r["agent_role"]] = r
    if not rounds:
        return {"latest": None, "note": "no recent entry-round decision on this coin"}
    latest = max(rounds.values(), key=lambda m: max(x["timestamp"] for x in m.values()))
    ts = max(x["timestamp"] for x in latest.values())
    cards = (scorecard or {}).get("agents", {})
    view = {}
    for role, rec in latest.items():
        card = cards.get(role) or {}
        view[role] = {"decision": rec["decision"], "confidence": rec.get("confidence"),
                      "why": (rec.get("reasoning_summary") or "")[:300], "model": rec.get("model_used"),
                      "report_card": {"verdict": card.get("verdict", "ungraded"), "diff_bps": card.get("diff_bps"),
                                      "n": min(card.get("nA", 0), card.get("nB", 0)) if card else 0}}
    return {"age_min": round((time.time() - ts) / 60), "signal": (next(iter(latest.values())).get("ctx") or {}).get("signal"),
            "roles": view}


def voice_strategies():
    try:
        from feedback.ic_tracker import ICTracker
        t = ICTracker()
    except Exception as e:
        return {"error": str(e)[:120]}
    out = {}
    for s in ("confidence_scorer", "multi_tier_quality", "bollinger_squeeze", "regime_trend", "mean_reversion",
              "funding_rate", "oi_delta", "liquidation_cascade", "probability_engine"):
        ic = t.compute_rolling_ic(s)
        w = t.get_ic_weight(s)
        out[s] = {"ic": _r(ic, 3), "weight": _r(w, 2),
                  "status": "MUTED (backwards track record)" if w == 0 else
                            "unproven (too few trades)" if ic is None else "active"}
    return out


def voice_rules(sym, ctx):
    import rules_manager as rm
    rules = [r for r in rm._load_rules() if r.get("status") != "retired"]
    out = {}
    for side in ("LONG", "SHORT"):
        row = {"symbol": sym, "side": side, "agree": None, "regimes": set(), "feat": ctx.get(side, {}),
               "strats": set()}
        hits = []
        for r in rules:
            s = r["slice"]
            # agree / regime / with_strategy depend on the eventual signal; judge only what is known now
            known = {k: v for k, v in s.items() if k not in ("agree", "regime", "with_strategy")}
            if rm.matches({**r, "slice": known}, row):
                hits.append({"id": r["id"], "action": r["action"], "status": r["status"], "slice": s,
                             "conditional_on": [k for k in s if k in ("agree", "regime", "with_strategy")],
                             "thesis": r.get("thesis", "")[:160]})
        out[side] = hits
    return out


def voice_bot(sym):
    st = _load(DATA / "position_state.json", {}) or {}
    p = (st.get("positions") or {}).get(sym)
    if not p:
        return {"position": None}
    return {"position": {k: p.get(k) for k in ("side", "entry", "qty", "sl", "tp1", "state", "realized_pnl",
                                                "leverage", "open_time", "notes")}}


def voice_owner(sym):
    calls = [r for r in _tail_jsonl(DATA / "copilot" / "call_ledger.jsonl", 2_000_000)
             if r.get("symbol") == sym and r.get("source") in ("owner", "call", "manual")]
    return {"n_calls": len(calls), "recent": calls[-3:],
            "note": "no owner calls logged yet on this coin" if not calls else ""}


def voice_history(sym, market):
    import basemap
    return basemap.lookup(sym, market)


# ── assemble ──────────────────────────────────────────────────────────

def assemble():
    OUT.mkdir(parents=True, exist_ok=True)
    import copilot as cp
    client = cp._get_hl_client()
    scorecard = _load(DATA / "agent_grades" / "live" / "live_scorecard.json", {})
    shared = {}
    for name, fn in (("weather", lambda: voice_weather(client)), ("strategies", voice_strategies)):
        try:
            shared[name] = fn()
        except Exception as e:
            shared[name] = {"error": f"{type(e).__name__}: {e}"[:200]}
    allstate = {"updated": _now_iso(), "shared": shared, "coins": {}}
    for sym in SYMS:
        st = {"symbol": sym, "updated": _now_iso()}
        for name, fn in (("market", lambda: voice_market(client, sym)), ("context", lambda: voice_context(sym)), ("agents", lambda: voice_agents(sym, scorecard)),
                         ("bot", lambda: voice_bot(sym)), ("owner", lambda: voice_owner(sym))):
            try:
                st[name] = fn()
            except Exception as e:
                st[name] = {"error": f"{type(e).__name__}: {e}"[:200]}
        try:
            st["deep"] = voice_deep(sym, (st.get("market") or {}).get("price") or 0)
        except Exception as e:
            st["deep"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        try:
            st["rules"] = voice_rules(sym, st.get("context") or {})
        except Exception as e:
            st["rules"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        try:
            st["history"] = voice_history(sym, st.get("market") or {})
        except Exception as e:
            st["history"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        (OUT / f"{sym}.json").write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
        allstate["coins"][sym] = st
    tmp = OUT / "_all.json.tmp"
    tmp.write_text(json.dumps(allstate, default=str), encoding="utf-8")
    os.replace(tmp, OUT / "_all.json")
    return allstate


if __name__ == "__main__":
    t = time.time()
    try:
        s = assemble()
        print(f"{_now_iso()} assembled {len(s['coins'])} coins in {time.time() - t:.0f}s")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
