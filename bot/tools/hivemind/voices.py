"""The signal web: every voice's current reading on a coin, in one common shape.

Each voice reads +1 (bullish: favors a long), -1 (bearish: favors a short), 0 (neutral) or None (no reading),
and carries a TRUST class from forward grading:
  earned      proven forward (CI excludes 0)                      weight 1.0
  promising   positive lead, not yet proven                       weight 0.5
  unproven    no forward evidence either way yet                  weight 0.25
  context     describes conditions; not a directional claim       weight 0
  backwards   graded and found anti-predictive or no-skill        weight 0
Trust here is deliberately conservative and is meant to be REPLACED by each voice's own forward grade
(tools/hivemind/voice_grader.py reads data/hivemind/voice_log.jsonl, written every cycle by assemble.py).
"""
import json
import re
import time
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
DATA = BOT / "data"
WEIGHT = {"earned": 1.0, "promising": 0.5, "unproven": 0.25, "context": 0.0, "backwards": 0.0}

# family = voices that are near-copies; the laptop's voice_families.json (mission 5) will refine this.
FAMILY = {  # laptop mission 5 (voice_families.json): stretch, range and driver correlate 0.64-0.78 = ONE voice
    "structure": "structure", "stretch": "stretch/driver", "driver": "stretch/driver", "range": "stretch/driver",
    "momentum_7d": "momentum", "rsi": "rsi", "history_5d": "base-rate",
    "structure_4h": "trend-4h", "stretch_4h": "trend-4h", "driver_4h": "trend-4h",
    "funding": "funding", "oi": "positioning", "liq_skew": "positioning",
    "book": "microstructure", "btc": "btc", "weather": "market",
    "copilot": "co-pilot", "strategies": "bot-strategies", "trade_agent": "bot-ai",
    "rules": "rules", "chief": "chief", "bot_position": "bot", "owner": "owner", "top_traders": "top-traders"}


def _load_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _graded_trust():
    """Per-voice trust from the voice grader, when it has enough data; else None."""
    try:
        g = json.loads((DATA / "hivemind" / "voice_grades.json").read_text(encoding="utf-8"))
        return {k: v.get("trust") for k, v in (g.get("voices") or {}).items() if v.get("trust")}
    except Exception:
        return {}


def _latest_strategy_vote(sym, max_age_s=3 * 3600):
    """Most recent bot strategy vote on this coin: SIGNAL_GENERATED or an IC-muted drop."""
    path = DATA / "trade_events.jsonl"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 1_500_000))
            f.readline()
            best = None
            for raw in f:
                if b'"' + sym.encode() + b'"' not in raw:
                    continue
                if b"SIGNAL_GENERATED" not in raw and b"ic_muted" not in raw:
                    continue
                try:
                    r = json.loads(raw)
                except Exception:
                    continue
                if r.get("symbol") != sym:
                    continue
                best = r
    except OSError:
        return None
    if not best:
        return None
    from datetime import datetime
    try:
        ts = datetime.fromisoformat(best["timestamp"].replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
    if time.time() - ts > max_age_s:
        return None
    return {"side": best.get("side"), "muted": "ic_muted" in (best.get("reason") or ""),
            "strategies": best.get("strategies_agree") or best.get("strategy"), "age_min": int((time.time() - ts) / 60)}


def compute(sym, st, shared, chief):
    m = st.get("market") or {}
    h = st.get("history") or {}
    ctx = st.get("context") or {}
    deep = st.get("deep") or {}
    graded = _graded_trust()
    V = []

    def add(key, label, reading, detail, trust):
        V.append({"voice": key, "family": FAMILY.get(key, key), "label": label, "reading": reading,
                  "detail": detail, "trust": graded.get(key, trust)})

    note = m.get("structure") or ""
    if note:
        add("structure", "Daily structure", 1 if "structure UP" in note else -1,
            "20d avg above 50d" if "structure UP" in note else "20d avg below 50d", "unproven")
        add("stretch", "Price vs 20d avg", 1 if "price above" in note else -1,
            "above its 20d average" if "price above" in note else "below its 20d average", "unproven")
    di = m.get("di")
    if di:
        add("driver", "Who's driving", 1 if di["plus"] > di["minus"] else -1,
            f"buyers {di['plus']} vs sellers {di['minus']}", "unproven")
    f4 = st.get("tf4h") or {}
    if f4:
        add("structure_4h", "4h structure", f4["structure_4h"],
            "4h 20-bar avg " + ("above" if f4["structure_4h"] > 0 else "below") + " 50-bar avg", "unproven")
        add("stretch_4h", "4h price vs avg", f4["stretch_4h"],
            "above its 4h 20-bar avg" if f4["stretch_4h"] > 0 else "below its 4h 20-bar avg", "unproven")
        add("driver_4h", "4h who's driving", f4["driver_4h"], f"buyers {f4['pdi']:.0f} vs sellers {f4['mdi']:.0f}", "unproven")
    r7 = m.get("ret_7d_pct")
    if r7 is not None:
        add("momentum_7d", "7-day momentum", 1 if r7 > 5 else -1 if r7 < -5 else 0, f"{r7:+.1f}% over 7 days", "unproven")
    rsi = m.get("rsi_1d")
    if rsi is not None:
        add("rsi", "RSI stretch", 1 if rsi < 30 else -1 if rsi > 70 else 0,
            f"RSI {rsi:.0f} ({'oversold' if rsi < 30 else 'overbought' if rsi > 70 else 'normal'})", "unproven")
    pos = (m.get("range_20d") or {}).get("position")
    if pos is not None:
        add("range", "20d range position", 0, f"{pos * 100:.0f}% of the way from low to high", "context")
    a = (h or {}).get("next_5d") or {}
    if a.get("n"):
        add("history_5d", "History of this setup", 1 if a["up_pct"] >= 55 else -1 if a["up_pct"] <= 45 else 0,
            f"up {a['up_pct']:.0f}% of {a['n']} past times (5d)", "unproven")
    fh = m.get("funding_hourly")
    if fh is not None:
        crowd = fh > 2.5e-5
        add("funding", "Funding (crowding)", -1 if crowd else 1 if fh < 0 else 0,
            f"{fh * 100:+.4f}%/hr ({'longs crowded' if crowd else 'shorts paying' if fh < 0 else 'normal'})", "unproven")
    for line in deep.get("funding_oi") or []:
        mm = re.search(r"OI \$[\d,]+ -> \$[\d,]+ \(([+-]?\d+)%", line)
        if mm:
            add("oi", "Open interest (7d)", 0, f"{int(mm.group(1)):+d}% over 7 days (leverage {'building' if int(mm.group(1)) > 5 else 'leaving' if int(mm.group(1)) < -5 else 'steady'})", "context")
            break
    for line in deep.get("liquidation_magnets") or []:
        mm = re.search(r"\$([\d,]+) flushed ABOVE / \$([\d,]+) flushed BELOW", line)
        if mm:
            above, below = (float(x.replace(",", "")) for x in mm.groups())
            add("liq_skew", "Liquidation skew (7d)", 0,
                f"${above / 1e6:.1f}M flushed above vs ${below / 1e6:.1f}M below", "context")
            break
    bl = (ctx.get("LONG") or {}).get("book")
    if bl:
        add("book", "Order book lean", 1 if bl == "supports" else -1 if bl == "against" else 0,
            {"supports": "bids heavier", "against": "asks heavier", "balanced": "balanced"}[bl], "promising")
    bt = (ctx.get("LONG") or {}).get("btc4h")
    if bt and sym != "BTC":
        add("btc", "BTC last 4h", 1 if bt == "with" else -1 if bt == "against" else 0,
            {"with": "BTC rising", "against": "BTC falling", "flat": "BTC flat"}[bt], "unproven")
    w = (shared or {}).get("weather") or {}
    if w.get("regime"):
        reg = w["regime"]
        add("weather", "Market weather", -1 if reg in ("STORMY", "HEADWIND") else 1 if reg in ("TAILWIND",) else 0,
            f"{reg}, breadth {w.get('breadth_pct') or 0:.0f}%", "context")
    act = m.get("copilot_action")
    if act:
        add("copilot", "Co-pilot zone", 1 if act == "ADD" else -1 if act in ("TRIM", "REDUCE") else 0,
            act, "backwards" if act == "ADD" else "unproven")
    sv = _latest_strategy_vote(sym)
    if sv:
        side = 1 if sv["side"] in ("BUY", "LONG") else -1
        add("strategies", "Bot strategies", side,
            f"{'BUY' if side > 0 else 'SELL'} via {sv['strategies']} ({sv['age_min']}m ago)"
            + (" - dropped, all IC-muted" if sv["muted"] else ""), "backwards")
    roles = ((st.get("agents") or {}).get("roles") or {})
    tr = roles.get("trade")
    sig = (st.get("agents") or {}).get("signal") or {}
    if tr and sig.get("side"):
        go = tr["decision"] == "go"
        s = 1 if str(sig["side"]).upper() in ("BUY", "LONG") else -1
        add("trade_agent", "Bot's AI trade agent", s if go else 0,
            f"{tr['decision']} on a {sig['side']} signal", "backwards")
    rules = st.get("rules") or {}
    score = 0
    names = []
    for side, sgn in (("LONG", 1), ("SHORT", -1)):
        for r in rules.get(side) or []:
            if r.get("conditional_on"):
                continue
            score += sgn * (1 if r["action"] == "favor" else -1)
            names.append(f"{r['id']} {r['action']} {side.lower()}")
    if names:
        add("rules", "Rules in force", (score > 0) - (score < 0), ", ".join(names),
            "earned" if any(r.get("status") == "earned" for s_ in rules.values() for r in s_) else "unproven")
    w = ((_load_json(DATA / "hivemind" / "whales_latest.json") or {}).get("coins") or {}).get(sym)
    if w and (w["long"] + w["short"]) >= 5:
        L_, S_ = w["long"], w["short"]
        rd = 1 if L_ >= 2 * max(S_, 1) else -1 if S_ >= 2 * max(L_, 1) else 0
        add("top_traders", "Top traders' positions", rd,
            f"{L_} long vs {S_} short among profitable HL traders (net {w['net_share']*100:+.0f}% of ${w['gross']/1e6:.0f}M)",
            "unproven")
    c = chief or {}
    if c.get("lean"):
        add("chief", "Chief analyst", {"LONG": 1, "SHORT": -1}.get(c["lean"], 0),
            f"{c['lean']} (conviction {c.get('conviction')})", "unproven")
    bp = (st.get("bot") or {}).get("position")
    if bp:
        add("bot_position", "Bot's open trade", 1 if bp.get("side") == "LONG" else -1,
            f"{bp.get('side')} from {bp.get('entry')}", "context")
    return V


def consensus(V):
    bull = [v for v in V if v["reading"] == 1]
    bear = [v for v in V if v["reading"] == -1]
    wb = sum(WEIGHT.get(v["trust"], 0) for v in bull)
    ws = sum(WEIGHT.get(v["trust"], 0) for v in bear)
    fam_b = len({v["family"] for v in bull})
    fam_s = len({v["family"] for v in bear})
    # Move SIZE (laptop mission 5, held out of sample): the fewer independent families dissent, the bigger
    # the next day's move (1 dissenting ~5.1% vs 4 dissenting ~3.2%, average ~3.5%). No directional content.
    dissent = min(fam_b, fam_s)
    # LAPTOP_REPLY.md: disagree <= 1 -> expect a ~5.1% day [4.71, 5.55]; >= 3 -> ~3.2% [3.04, 3.33].
    size = ("bigger than usual" if dissent <= 1 and (fam_b + fam_s) >= 3 else
            "smaller than usual" if dissent >= 3 else "normal")
    size_hint = "~5% day" if size == "bigger than usual" else "~3.2% day" if size == "smaller than usual" else "~3.5% day"
    return {"bull": len(bull), "bear": len(bear), "neutral": sum(1 for v in V if v["reading"] == 0),
            "bull_families": fam_b, "bear_families": fam_s, "dissent_families": dissent, "move_size": size, "move_size_hint": size_hint,
            "trust_weighted": round(wb - ws, 2), "trust_total": round(wb + ws, 2)}


def contradictions(V):
    """Pairs of directional voices from different families that disagree, strongest trust first."""
    d = [v for v in V if v["reading"] in (1, -1)]
    out = []
    for i, a in enumerate(d):
        for b in d[i + 1:]:
            if a["reading"] != b["reading"] and a["family"] != b["family"]:
                out.append((WEIGHT.get(a["trust"], 0) + WEIGHT.get(b["trust"], 0), a, b))
    out.sort(key=lambda x: -x[0])
    return [{"bull": (a if a["reading"] == 1 else b)["label"], "bear": (b if a["reading"] == 1 else a)["label"],
             "bull_detail": (a if a["reading"] == 1 else b)["detail"], "bear_detail": (b if a["reading"] == 1 else a)["detail"]}
            for _, a, b in out[:4]]


# Plain-language explainer for every voice: what it measures, how to read it, and what to watch for.
INFO = {
    "structure": ("Compares the 20-day average price with the 50-day average. 20 above 50 = the market has been rising "
                  "over weeks (uptrend); below = falling.", "Slow and steady: tells you the backdrop, not the timing. "
                  "It still says 'uptrend' for days after a sharp drop."),
    "stretch": ("Is today's price above or below its own 20-day average?", "Below the average inside an uptrend = a "
                "pullback. Above it inside a downtrend = a bounce."),
    "driver": ("+DI vs -DI: over the last ~2 weeks, were the big daily pushes mostly UP (buyers) or DOWN (sellers)?",
               "Faster than structure. When it flips against the structure, the trend is being tested."),
    "structure_4h": ("Same as daily structure but on 4-hour candles: is the 20-bar average above the 50-bar average?",
                     "Shows the trend of the last week or so. When it disagrees with the daily, the short-term move "
                     "is against the bigger trend. Historically ~no edge on its own; use it for timing."),
    "stretch_4h": ("Is price above or below its 4-hour 20-bar average?", "Fast. Flips often. Below it inside a daily "
                   "uptrend = a short-term dip."),
    "driver_4h": ("+DI vs -DI on 4-hour candles: who has pushed harder over the last ~2 days.",
                  "The quickest read of who's in control right now. Historically ~no edge alone."),
    "momentum_7d": ("Price change over the last 7 days. Above +5% reads bullish, below -5% bearish.",
                    "Crypto has historically tended to keep moving the way it just moved (momentum), but that edge has "
                    "faded since 2024."),
    "rsi": ("RSI: how stretched the recent move is. Under 30 = 'oversold', over 70 = 'overbought'. This voice bets on "
            "a snap-back.", "TRACK RECORD IS BACKWARDS: on these coins, extreme RSI has more often meant the move "
            "CONTINUES. Treat 'oversold' as a warning, not a buy."),
    "range": ("Where price sits between its 20-day low (0%) and high (100%).", "Context only: near the low is close to "
              "support, near the high close to resistance. Not a direction call."),
    "history_5d": ("Looks up every past day (since 2020) when these coins had today's exact combination of structure, "
                   "stretch, range and driver, and counts how often price was higher 5 days later.",
                   "A base rate, not a forecast. Trust it more when 'independent' cases are large (100+)."),
    "funding": ("Funding: the fee longs and shorts pay each other every hour on perps. High positive = longs crowded "
                "and paying up.", "Crowded longs can unwind fast. Negative funding = shorts are paying, which can "
                "fuel squeezes up."),
    "oi": ("Open interest: total size of open leveraged positions, and how it changed this week.",
           "Building OI = more leverage in the market, so bigger forced moves when it breaks. Context, not direction."),
    "liq_skew": ("Dollar amount of forced liquidations above vs below today's price this week.",
                 "Shows where leverage got cleaned out. Clusters are where moves can accelerate. Measured: price does "
                 "NOT gravitate to them."),
    "book": ("Order book: are resting buy orders (bids) or sell orders (asks) heavier within 1% of price?",
             "A promising early lead (+0.19%/4h when the book supports the side, from exploratory data). Being tested "
             "forward as rule R005."),
    "btc": ("Is BTC rising or falling over the last 4 hours?", "Alts mostly follow BTC. A long while BTC is falling "
            "is swimming upstream."),
    "weather": ("Market-wide mood: how many coins are above their 20-day average, and BTC's trend.",
                "HEADWIND = most coins weak. Context: it describes conditions, it doesn't time entries."),
    "copilot": ("The co-pilot's zone call: ADD = a dip zone, TRIM = a stretched zone, HOLD/WAIT = neither.",
                "TRACK RECORD: ADD zones had no edge out of sample. Shown for context."),
    "strategies": ("What the bot's own strategies voted most recently on this coin.",
                   "TRACK RECORD IS BACKWARDS: the main strategies are muted for anti-predictive results. Shown so you "
                   "can see what the bot sees, not to follow."),
    "trade_agent": ("The bot's AI trade agent (Opus) on its latest signal for this coin.",
                    "TRACK RECORD: no directional skill so far (its GO picks did worse than its skips). Being re-graded "
                    "live since the Opus upgrade."),
    "rules": ("Rules the Opus rules manager wrote that apply here right now (avoid/favor).",
              "Hypotheses until 'earned' on future data. Dashed chips on the cards."),
    "top_traders": ("What ~60 of Hyperliquid's consistently profitable traders (not market makers or vaults) are holding "
                    "right now: how many are long vs short this coin.", "NEW data, started 2026-10-08, so no track record yet. "
                    "Reads bullish/bearish only when one side outnumbers the other 2 to 1. Graded forward like every voice."),
    "chief": ("The Opus chief analyst's lean after reading every other voice.",
              "Graded at 1 and 5 days. Its track record shows at the top of the desk."),
    "bot_position": ("The bot's own open trade on this coin.", "Context: what the bot is already exposed to."),
}
