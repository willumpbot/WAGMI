"""Track every Syndicate call forward: market cap at the call, now, and the peak since.

Sources (local only, gitignored): data/hivemind/tg/calls.jsonl (live scanner) and history_calls.jsonl (export),
first mention of each contract address in the Syndicate chat within the last TRACK_DAYS. Market cap at the call
comes from the scanner's card or the price bot's message posted with it ("MC $83.7K", "74.3K -> 373.3K").
Each hivemind cycle fetches current market cap from DexScreener (free, batched 30 per request) and keeps the peak
seen. Peaks are only as fine as the 15-minute cycle, so short spikes between cycles are missed (the x_peak is a
floor). Writes data/hivemind/tg/track.json. Read-only: never posts anything anywhere.
"""
import json
import re
import time
import urllib.request
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
TG = BOT / "data" / "hivemind" / "tg"
OUT = TG / "track.json"
TRACK_DAYS = 7
SYNDICATE = -1003904703116


def _num(txt):
    m = re.match(r"\$?\s*([\d.]+)\s*([KMB]?)", txt.strip(), re.I)
    if not m:
        return None
    return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()]


def _call_mcap(rows, ca, t0):
    """MC at the call from messages posted within 10 min of it (price-bot stats or a multiplier alert)."""
    best = None
    for r in rows:
        if r.get("ca") != ca or not (t0 - 5 <= r["ts"] <= t0 + 600):
            continue
        msg = r.get("msg") or ""
        m = re.search(r"([\d.]+[KMB]?)\s*(?:→|->)\s*[\d.]+[KMB]?", msg)          # "74.3K → 373.3K" = MC at call
        if m:
            return _num(m.group(1))
        m = re.search(r"\b(?:MC|FDV)\s*:?\s*\$\s*([\d.]+\s*[KMB]?)", msg)
        if m and best is None:
            best = _num(m.group(1))
        if best is None and r.get("mcap"):
            best = float(r["mcap"])
    return best


def _dex(addrs):
    out = {}
    for i in range(0, len(addrs), 30):
        chunk = addrs[i:i + 30]
        req = urllib.request.Request("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk),
                                     headers={"User-Agent": "wagmi-hivemind/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                pairs = json.loads(r.read())
        except Exception:
            continue
        for p in pairs or []:
            ca = (p.get("baseToken") or {}).get("address")
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if ca and (ca not in out or liq > out[ca]["liq"]):
                out[ca] = {"mcap": p.get("marketCap") or p.get("fdv"), "liq": liq, "price": p.get("priceUsd"),
                           "name": (p.get("baseToken") or {}).get("name"), "sym": (p.get("baseToken") or {}).get("symbol"),
                           "url": p.get("url")}
        time.sleep(0.3)
    return out


VERDICT_SYSTEM = """You judge a meme-coin call just posted in a Telegram group the owner follows (Solana memes).
Facts for this chat (graded history, pre-registered): 41% of called coins touch 2x at some point, but the median is
-73% after 7 days, and no caller has beaten random calls from the same week. So "coin flip" is the honest default.
You see the token's on-chain market data and the caller's graded record. Say whether THIS call looks more likely than
the chat's 41% base rate to reach 2x from the call within 24h ("runner"), about base rate ("coin flip"), or clearly
worse / dangerous ("avoid": churn, tiny liquidity, rug flags, already ran). You are graded on this, so don't be a hype
machine. Output ONLY JSON: {"verdict": "runner|coin flip|avoid", "p_2x": 0-100, "why": "<=160 chars plain"}"""


def _ai_verdicts(calls, prev, records, now):
    """Sonnet verdict on each fresh call (<3h old), graded at 24h on whether it touched 2x from the call."""
    import importlib.util
    import os
    import sys
    fresh = [c for c in calls.values() if now - c["call_ts"] < 3 * 3600 and not (prev.get(c["ca"]) or {}).get("ai")
             and c.get("call_mcap")]
    for c in calls.values():   # carry forward + grade
        old = (prev.get(c["ca"]) or {}).get("ai")
        if old:
            c["ai"] = old
            if "ran_2x" not in old and now - c["call_ts"] >= 24 * 3600 and c.get("x_peak") is not None:
                old["ran_2x"] = c["x_peak"] >= 2
                with open(TG / "ai_verdict_log.jsonl", "a", encoding="utf-8") as f:   # permanent record beyond the 7-day window
                    f.write(json.dumps({"ca": c["ca"], "caller": c.get("caller"), "call_ts": c["call_ts"], **old,
                                        "x_peak_24h": c["x_peak"]}) + chr(10))
    if not fresh:
        return
    sys.path.insert(0, str(BOT))
    from llm.claude_cli_client import call_agent
    spec = importlib.util.spec_from_file_location("memecard", BOT / "data" / "laptop_mining" / "memecard.py")
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    for c in fresh[:6]:
        try:
            card = mc.card(c["ca"])
        except Exception as e:
            card = {"ok": False, "error": str(e)[:100]}
        keep = ("name", "market_cap", "liquidity_usd", "volume_24h_usd", "pair_age_days", "price_change", "risk_flags",
                "position_cap_usd_for_2pct_slip", "dex")
        prompt = json.dumps({"token": {k: card.get(k) for k in keep}, "mcap_at_call": c["call_mcap"],
                             "minutes_since_call": round((now - c["call_ts"]) / 60),
                             "caller": c.get("caller"), "caller_record": records.get(c.get("caller"))}, default=str)
        try:
            resp = call_agent(user_prompt=prompt, system_prompt=VERDICT_SYSTEM, model="sonnet",
                              max_budget_usd=float(os.getenv("CLI_MAX_BUDGET_USD", "5.00")), timeout=180)
            raw = (getattr(resp, "text", None) or getattr(resp, "content", "")).strip()
            v = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            c["ai"] = {"verdict": v.get("verdict"), "p_2x": v.get("p_2x"), "why": str(v.get("why") or "")[:200], "ts": now}
        except Exception:
            continue


def _ai_stats(calls):
    out = {}
    try:
        graded = [json.loads(l) for l in (TG / "ai_verdict_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        graded = []
    for a in graded:
        if "ran_2x" in a:
            s = out.setdefault(a.get("verdict") or "?", {"n": 0, "ran": 0})
            s["n"] += 1
            s["ran"] += bool(a["ran_2x"])
    return out


def run():
    now = time.time()
    rows = []
    for f in ("history_calls.jsonl", "calls.jsonl"):
        try:
            for l in (TG / f).read_text(encoding="utf-8").splitlines():
                r = json.loads(l)
                if r.get("chat_id") == SYNDICATE or r.get("chat") == "Syndicate 2.0":
                    rows.append(r)
        except OSError:
            pass
    rows.sort(key=lambda r: r.get("ts") or 0)
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8")).get("calls", {})
    except Exception:
        prev = {}
    calls = {}
    for r in rows:
        ca = r.get("ca")
        if not ca or ca in calls or r["ts"] < now - TRACK_DAYS * 86400 or ca.startswith("0x") or ca.islower():
            continue
        human = r.get("sender") and not str(r.get("sender")).lower().endswith("bot")
        old = prev.get(ca) or {}
        calls[ca] = {"ca": ca, "call_ts": r["ts"], "caller": r.get("sender") if human else old.get("caller"),
                     "call_mcap": old.get("call_mcap") or _call_mcap(rows, ca, r["ts"]),
                     "peak_mcap": old.get("peak_mcap"), "peak_ts": old.get("peak_ts"),
                     "call_mcap_approx": old.get("call_mcap_approx"),
                     "card_at_call": old.get("card_at_call") or ({"mcap": r.get("mcap"), "liq": r.get("liq")} if r.get("notified") else None)}
        if not human:   # first sight was a bot alert; credit the human named in it (e.g. "├ takinginitialshere")
            m = re.search(r"├\s*@?([A-Za-z0-9_]{3,})\s*(?:\n|/|$)", r.get("msg") or "")
            calls[ca]["caller"] = calls[ca]["caller"] or (("@" + m.group(1)) if m else None)
    live = _dex(list(calls))
    for ca, c in calls.items():
        d = live.get(ca) or {}
        c.update({"name": d.get("name") or (prev.get(ca) or {}).get("name"), "sym": d.get("sym"), "url": d.get("url"),
                  "now_mcap": d.get("mcap"), "liq_now": d.get("liq")})
        if not c.get("call_mcap") and c["now_mcap"] and now - c["call_ts"] <= 1800:
            # no price-bot stats with the call: first market cap we saw, within 30 min of the call (approximate)
            c["call_mcap"], c["call_mcap_approx"] = c["now_mcap"], True
        if c["now_mcap"] and (not c["peak_mcap"] or c["now_mcap"] > c["peak_mcap"]):
            c["peak_mcap"], c["peak_ts"] = c["now_mcap"], now
        if c["call_mcap"]:
            c["x_now"] = round(c["now_mcap"] / c["call_mcap"], 2) if c["now_mcap"] else None
            c["x_peak"] = round(c["peak_mcap"] / c["call_mcap"], 2) if c["peak_mcap"] else None
    # Caller records: history (caller_grade.py, pre-registered) + forward (this tracker). A caller is starred to
    # WATCH when their historical 2x hit rate beats the chat's with n>=8: a watch flag, not proof (none beat random).
    records = {}
    try:
        g = json.loads((TG / "caller_grades.json").read_text(encoding="utf-8"))["chats"]["syndicate"]
        base = g["base_all"]["hit_rate"]
        for c in g.get("callers") or []:
            if c.get("handle"):
                records[c["handle"]] = {"hist_n": c.get("n"), "hist_hit": c.get("hit_rate"),
                                        "hist_peak": c.get("median_peak_mult"),
                                        "watch": bool(c.get("n", 0) >= 8 and (c.get("hit_rate") or 0) > base)}
        records["_base_hit"] = base
    except Exception:
        pass
    for c in calls.values():
        h = c.get("caller")
        if h and c.get("x_peak") is not None:
            r = records.setdefault(h, {})
            r["fwd_n"] = r.get("fwd_n", 0) + 1
            r["fwd_2x"] = r.get("fwd_2x", 0) + (c["x_peak"] >= 2)
    _ai_verdicts(calls, prev, records, now)
    out = {"updated": now, "calls": calls, "callers": records, "ai_stats": _ai_stats(calls)}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(OUT)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    o = run()
    for c in sorted(o["calls"].values(), key=lambda c: -c["call_ts"])[:15]:
        print(time.strftime("%m-%d %H:%M", time.gmtime(c["call_ts"])), c.get("sym"), c.get("caller"),
              "call", c.get("call_mcap"), "now", c.get("now_mcap"), "x", c.get("x_now"), "peak x", c.get("x_peak"))
