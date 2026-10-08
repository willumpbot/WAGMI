"""Chief analyst: Opus reads every hivemind voice and writes one read per coin.

  python tools/hivemind/chief.py            # read all coins, log graded calls
  python tools/hivemind/chief.py --resolve  # grade matured calls only (no LLM)

Each call is logged to data/hivemind/chief_calls.jsonl with the price at the
time and graded at +1d and +5d against Hyperliquid prices. NEUTRAL calls are
graded too (as "stayed within one daily ATR"). The report card in
data/hivemind/chief_scorecard.json is what tells the owner, and later the bot,
how much weight the chief deserves. Nothing here places or changes trades.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT))
HM = BOT / "data" / "hivemind"
STATE = HM / "state" / "_all.json"
CALLS = HM / "chief_calls.jsonl"
CARD = HM / "chief_scorecard.json"
READS = HM / "chief_latest.json"
HORIZONS = {"1d": 86400, "5d": 5 * 86400}

SYSTEM = """You are the Chief Analyst of a trading "hivemind" for a discretionary swing trader on Hyperliquid perps.
You receive, per coin, every voice in the system. Each voice carries a report card. Weight voices by their
report cards, not by how confident they sound. Established facts from forward grading:
- The bot's AI agents (trade/critic/regime) have NOT shown directional skill; risk-agent vetoes were the only positive.
- The ensemble's main strategies are currently IC-muted (backwards track record).
- Taking every bot signal loses ~10-14 bps per 4h after fees; stop/target geometry is ~coin-flip.
- Rules-manager rules are hypotheses until "earned".
- "history" is a base rate for today's combination of daily readings (overlapping windows; n_eff ~ n/5).
- Liquidation clusters are path-risk context, not targets.
- Out-of-sample study (18k symbol-days, 2020-26): voice AGREEMENT does not predict direction; stretch/range/driver
  are one voice. What IS predictable is MOVE SIZE: when few independent voice families dissent, the next day moves
  ~5% vs ~3% when many dissent; ATR persists (corr 0.35). consensus.move_size in each coin carries this.
- So the most useful thing you can give a leverage trader is: expected move size, the levels that matter within it,
  and where risk sits (liquidation clusters, stops). Direction only when the evidence is unusually clear.
Your job: for each coin, say plainly what the evidence supports for a 1-5 day SWING view, including "nothing" -
NEUTRAL is the right answer when voices conflict or evidence is thin. Never invent data. Prefer few, specific
statements a trader can check: levels, what would invalidate the view, which voice you leaned on and why.

Output ONLY JSON:
{"coins": {"<SYM>": {"lean": "LONG|SHORT|NEUTRAL", "conviction": 1-5,
   "read": "<=350 chars, plain English, what the trader should know right now",
   "key_levels": "<=120 chars", "invalidation": "<=120 chars",
   "expected_move": "<=90 chars: likely size of the next 1-2 days' move and why (ATR, move_size flag)",
   "leaned_on": ["voice names"], "ignored": ["voice names + why, <=60 chars each"]}},
 "market_note": "<=250 chars, the one thing that matters across all coins today"}"""


def _compact(allstate):
    out = {"shared": allstate.get("shared"), "coins": {}}
    for sym, st in allstate.get("coins", {}).items():
        c = dict(st)
        deep = c.get("deep") or {}
        c["deep"] = {k: v[:6] for k, v in deep.items() if isinstance(v, list)}
        out["coins"][sym] = c
    txt = json.dumps(out, default=str)
    return txt[:60000]


def _price(sym):
    body = json.dumps({"type": "allMids"}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        mids = json.loads(r.read())
    return float(mids[sym]) if sym in mids else None


def _price_at(sym, ts):
    """Open of the first 1h bar starting at/after ts."""
    body = json.dumps({"type": "candleSnapshot", "req": {"coin": sym, "interval": "1h",
                                                          "startTime": int(ts * 1000), "endTime": int((ts + 7200) * 1000)}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        bars = json.loads(r.read())
    return float(bars[0]["o"]) if bars else None


def run_chief():
    from llm.claude_cli_client import call_agent
    allstate = json.loads(STATE.read_text(encoding="utf-8"))
    resp = call_agent(user_prompt=_compact(allstate), system_prompt=SYSTEM, model="opus",
                      max_budget_usd=float(os.getenv("CLI_MAX_BUDGET_USD", "5.00")), timeout=900, allow_tools=False)
    if not resp.ok:
        raise RuntimeError(resp.error)
    raw = (getattr(resp, "text", None) or getattr(resp, "content", "")).strip()
    out = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    now = time.time()
    with open(CALLS, "a", encoding="utf-8") as f:
        for sym, c in (out.get("coins") or {}).items():
            st = allstate["coins"].get(sym, {})
            px = (st.get("market") or {}).get("price") or _price(sym)
            atr = (st.get("market") or {}).get("atr_pct_1d")
            f.write(json.dumps({"ts": now, "symbol": sym, "lean": c.get("lean"), "conviction": c.get("conviction"),
                                "price": px, "atr_pct_1d": atr, "read": c.get("read"),
                                "invalidation": c.get("invalidation")}) + "\n")
    out["ts"] = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="minutes")
    READS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def resolve():
    if not CALLS.exists():
        return {}
    rows = [json.loads(l) for l in CALLS.read_text(encoding="utf-8").splitlines() if l.strip()]
    now = time.time()
    changed = False
    for r in rows:
        for hz, sec in HORIZONS.items():
            k = "ret_" + hz
            if k in r or now - r["ts"] < sec + 3600 or not r.get("price"):
                continue
            try:
                p = _price_at(r["symbol"], r["ts"] + sec)
            except Exception:
                continue
            if p:
                r[k] = round((p / r["price"] - 1) * 100, 3)
                changed = True
    if changed:
        tmp = CALLS.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        os.replace(tmp, CALLS)
    card = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "horizons": {}}
    for hz in HORIZONS:
        k = "ret_" + hz
        g = [r for r in rows if k in r]
        dirn = [r for r in g if r.get("lean") in ("LONG", "SHORT")]
        edge = [(1 if r["lean"] == "LONG" else -1) * r[k] for r in dirn]
        neut = [r for r in g if r.get("lean") == "NEUTRAL" and r.get("atr_pct_1d")]
        card["horizons"][hz] = {
            "n_calls": len(g), "n_directional": len(dirn),
            "directional_hit": round(sum(e > 0 for e in edge) / len(edge), 3) if edge else None,
            "directional_mean_pct": round(sum(edge) / len(edge), 3) if edge else None,
            "always_long_mean_pct": round(sum(r[k] for r in dirn) / len(dirn), 3) if dirn else None,
            "neutral_quiet_rate": round(sum(abs(r[k]) <= r["atr_pct_1d"] * (1 if hz == "1d" else 2.2)
                                            for r in neut) / len(neut), 3) if neut else None,
            "by_conviction": {str(cv): (lambda xs: {"n": len(xs), "mean_pct": round(sum(xs) / len(xs), 3)})(
                [(1 if r["lean"] == "LONG" else -1) * r[k] for r in dirn if r.get("conviction") == cv])
                for cv in range(1, 6) if any(r.get("conviction") == cv for r in dirn)},
        }
    card["verdict"] = ("collecting" if card["horizons"]["5d"]["n_directional"] < 30 else "graded")
    CARD.write_text(json.dumps(card, indent=1), encoding="utf-8")
    return card


if __name__ == "__main__":
    HM.mkdir(parents=True, exist_ok=True)
    if "--resolve" not in sys.argv:
        out = run_chief()
        print(json.dumps({s: (c.get("lean"), c.get("conviction")) for s, c in out.get("coins", {}).items()}))
        print(out.get("market_note"))
    print(json.dumps(resolve().get("horizons", {}).get("5d", {})))
