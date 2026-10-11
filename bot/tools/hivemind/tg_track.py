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


VERDICT_SYSTEM = """You estimate, for a meme-coin call just posted in the owner's Telegram group (Solana), the probability
that price reaches 1.5x and 2x of the price at the call within 24 hours.
CALIBRATION IS EVERYTHING: you are scored with a Brier score on every call. Base rates in this chat (graded history):
about 62% of calls touch 1.5x and about 41% touch 2x. Your average p_15x across many calls should land near 62%.
Start from 62% and move it only for concrete evidence in the data: order-flow (buyers vs sellers, volume vs
liquidity over 5m/15m/1h), how far it already ran before the call, liquidity size, red flags (churn, tiny liquidity,
mint/freeze risks), the price path since the call, and the caller's graded record. A coin that has already run hard
is LESS likely to add another 50%; a fresh launch with strong net buying is MORE likely. Do not default to low numbers.
Output ONLY JSON: {"p_15x": 5-95, "p_2x": 5-95,
 "plan": "<=90 chars: if someone takes it, how to sell (e.g. 'sell all at 1.5x; out if -35% in the first hour')",
 "why": "<=160 chars plain, cite the numbers that moved you off 62%"}"""


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
                old["ran_15x"] = c["x_peak"] >= 1.5
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
        flow = {}
        if c.get("gt_pool"):
            d = _gt(f"{_GT}/pools/{c['gt_pool']}")
            a = ((d or {}).get("data") or {}).get("attributes") or {}
            flow = {k: a.get(k) for k in ("transactions", "volume_usd", "price_change_percentage", "reserve_in_usd",
                                          "pool_created_at")}
            flow["transactions"] = {w: v for w, v in (flow.get("transactions") or {}).items() if w in ("m5", "m15", "h1", "h6")}
        path = {k: c.get(k) for k in ("gt_peak_x", "gt_now_x", "gt_min_to_15x", "gt_min_to_2x", "gt_dd_first_hour")}
        prompt = json.dumps({"token": {k: card.get(k) for k in keep}, "order_flow": flow, "path_since_call": path,
                             "mcap_at_call": c["call_mcap"],
                             "minutes_since_call": round((now - c["call_ts"]) / 60),
                             "caller": c.get("caller"), "caller_record": records.get(c.get("caller"))}, default=str)
        try:
            resp = call_agent(user_prompt=prompt, system_prompt=VERDICT_SYSTEM, model="sonnet",
                              max_budget_usd=float(os.getenv("CLI_MAX_BUDGET_USD", "5.00")), timeout=180)
            raw = (getattr(resp, "text", None) or getattr(resp, "content", "")).strip()
            v = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            try:
                p15 = float(v.get("p_15x"))
            except (TypeError, ValueError):
                p15 = None
            # verdict is DERIVED from the calibrated probability (the label alone was 7/7 "avoid" on 10-11)
            verdict = None if p15 is None else ("runner" if p15 >= 75 else "avoid" if p15 <= 40 else "coin flip")
            c["ai"] = {"verdict": verdict, "p_15x": v.get("p_15x"), "p_2x": v.get("p_2x"), "prompt_v": 2,
                       "plan": str(v.get("plan") or "")[:120], "why": str(v.get("why") or "")[:200], "ts": now}
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
            s = out.setdefault(a.get("verdict") or "?", {"n": 0, "ran": 0, "ran15": 0})
            s["n"] += 1
            s["ran"] += bool(a["ran_2x"])
            s["ran15"] += bool(a.get("ran_15x"))
            if a.get("p_15x") is not None and a.get("prompt_v") == 2:
                s.setdefault("brier_sum", 0.0)
                s["brier_sum"] += (float(a["p_15x"]) / 100 - (1.0 if a.get("ran_15x") else 0.0)) ** 2
                s["brier_n"] = s.get("brier_n", 0) + 1
    return out


_GT = "https://api.geckoterminal.com/api/v2/networks/solana"


def _gt(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "wagmi-hivemind/1.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(3 * (i + 1))
    return None


def _exact_peaks(calls, prev, now, budget=24):
    """Exact peak since the call from GeckoTerminal 5-minute highs (the 15-min DexScreener snapshots miss spikes:
    MASSIMO read 1.6x but really hit 2.16x). Price multiple from the first 5m bar at/after the call. Rate-limited:
    calls <24h old refresh every cycle, older ones every 2h, at most `budget` requests per cycle."""
    used = 0
    for c in sorted(calls.values(), key=lambda c: -c["call_ts"]):
        old = prev.get(c["ca"]) or {}
        for k in ("gt_pool", "gt_entry", "gt_peak_x", "gt_now_x", "gt_peak_ts", "gt_checked", "gt_min_to_15x",
                  "gt_min_to_2x", "gt_dd_first_hour", "gt_min_done"):
            if old.get(k) is not None:
                c[k] = old[k]
        age = now - c["call_ts"]
        if age > 7 * 86400 or now - (c.get("gt_checked") or 0) < (840 if age < 86400 else 7200) or used >= budget:
            continue
        if not c.get("gt_pool"):
            d = _gt(f"{_GT}/tokens/{c['ca']}/pools?page=1"); used += 1; time.sleep(2.1)
            try:
                c["gt_pool"] = d["data"][0]["attributes"]["address"]
            except Exception:
                c["gt_checked"] = now
                continue
        e = c.get("gt_entry")
        if e is None or (c.get("gt_min_done") is None and age < 17 * 3600):
            # 1-minute bars ANCHORED at the call (memes move in minutes): entry, speed to 1.5x/2x, first-hour dip
            o = _gt(f"{_GT}/pools/{c['gt_pool']}/ohlcv/minute?aggregate=1&limit=1000&currency=usd"
                    f"&before_timestamp={int(c['call_ts']) + 1000 * 60}"); used += 1; time.sleep(2.1)
            if not o:
                continue   # rate-limited / failed: retry next cycle
            bars = sorted(((o.get("data") or {}).get("attributes", {}) or {}).get("ohlcv_list") or [])
            after = [b for b in bars if b[0] >= c["call_ts"] - 60]
            if not after or after[0][0] > c["call_ts"] + 120:
                c["gt_checked"] = now   # no trading right at the call: can't price it exactly
                continue
            e = c["gt_entry"] = after[0][4] if after[0][0] < c["call_ts"] else after[0][1]
            c["gt_peak_x"] = round(max(c.get("gt_peak_x") or 0, max(b[2] for b in after) / e), 3)
            for m, k in ((1.5, "gt_min_to_15x"), (2.0, "gt_min_to_2x")):
                hit = next((b for b in after if b[2] >= m * e), None)
                c[k] = round(max(0, hit[0] + 60 - c["call_ts"]) / 60) if hit else None
            first = [b for b in after if b[0] <= c["call_ts"] + 3600]
            c["gt_dd_first_hour"] = round((min(b[3] for b in first) / e - 1) * 100, 1) if first else None
            if age >= 16 * 3600:
                c["gt_min_done"] = True
        # later peaks: hourly highs after the call (exact highs, 8 days back per request)
        o = _gt(f"{_GT}/pools/{c['gt_pool']}/ohlcv/hour?aggregate=1&limit=200&currency=usd"); used += 1; time.sleep(2.1)
        if not o:
            continue
        hb = [b for b in sorted(((o.get("data") or {}).get("attributes", {}) or {}).get("ohlcv_list") or [])
              if b[0] >= c["call_ts"]]
        c["gt_checked"] = now
        if hb:
            hi = max(hb, key=lambda b: b[2])
            if hi[2] / e > (c.get("gt_peak_x") or 0):
                c["gt_peak_x"], c["gt_peak_ts"] = round(hi[2] / e, 3), hi[0]
                for m, k in ((1.5, "gt_min_to_15x"), (2.0, "gt_min_to_2x")):
                    if c.get(k) is None and hi[2] >= m * e:
                        c[k] = round((next(b for b in hb if b[2] >= m * e)[0] + 3600 - c["call_ts"]) / 60)
            c["gt_now_x"] = round(hb[-1][4] / e, 3)
    for c in calls.values():   # prefer the exact peak wherever we have it
        if c.get("gt_peak_x"):
            c["x_peak"] = round(max(c.get("x_peak") or 0, c["gt_peak_x"]), 2)


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
    _exact_peaks(calls, prev, now)
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
    try:   # the "sell all at 1.5x" view (CALLER_15X_PREREG.md): historical hit rate + mean per caller
        g15 = {}
        for l in (TG / "caller_calls_graded.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            if "Syndicate" in (r.get("chat") or "") and r.get("status") == "graded" and r.get("peak_mult") and r.get("ret_7d") is not None:
                g15.setdefault(r.get("sender"), []).append(((50.0 if r["peak_mult"] >= 1.5 else r["ret_7d"]) - 3, r["peak_mult"] >= 1.5))
        allv = [v for xs in g15.values() for v, _ in xs]
        records["_base_15x"] = {"hit": sum(h for xs in g15.values() for _, h in xs) / max(1, len(allv)),
                                "mean": sum(allv) / max(1, len(allv))}
        for h, xs in g15.items():
            if h and len(xs) >= 8:
                r = records.setdefault(h, {})
                r["hist15_n"], r["hist15_hit"] = len(xs), sum(x for _, x in xs) / len(xs)
                r["hist15_mean"] = sum(v for v, _ in xs) / len(xs)
                r["watch"] = r["hist15_hit"] >= records["_base_15x"]["hit"] + 0.10 and r["hist15_mean"] > records["_base_15x"]["mean"] + 10
    except Exception:
        pass
    for c in calls.values():
        h = c.get("caller")
        if h and c.get("x_peak") is not None:
            r = records.setdefault(h, {})
            r["fwd_n"] = r.get("fwd_n", 0) + 1
            r["fwd_2x"] = r.get("fwd_2x", 0) + (c["x_peak"] >= 2)
            r["fwd_15x"] = r.get("fwd_15x", 0) + (c["x_peak"] >= 1.5)
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
