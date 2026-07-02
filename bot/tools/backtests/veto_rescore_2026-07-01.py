"""
Dollar re-score of EVERY graduated rule (active + retired) against the
counterfactual corpus. Lane: BT_VETO_RESCORE, 2026-07-01.

Rule population = union of:
  - bot/data/llm/graduated_rules.json          (current file, regenerated 2026-07-01)
  - bot/data/llm/graduated_rules.json.bak.20260619T161520Z  (legacy: hype_long_veto_v1 etc.)

Scoring, per rule:
  - Reimplement GraduatedRule.matches() semantics (regime canonicalization,
    side canonicalization, confidence bounds, hour-of-day bounds, strategy).
  - Match against counterfactual_resolved.jsonl (resolved records only).
  - RAW numbers: every matching record.
  - EPISODE numbers (honest denominator): consecutive records for the same
    (symbol, side) within 4h and entry within 1.5% collapse into one episode
    (the bot could only have taken ONE position); episode pnl = median.
  - veto/penalize framing: pnl_saved = sum |pnl| of blocked losers,
    pnl_missed = sum pnl of blocked winners, net = saved - missed.
  - boost framing: net_boost_value = winners - losers (a boost promotes trades).
  - Per-fortnight breakdown (14d buckets from corpus start).
  - Actual-trade cross-check from trades.csv for boost/penalize rules.

Dollar conversion: hypothetical_pnl_pct is an UNLEVERED price-move pct with no
fees. Dollars are quoted at the median live notional derived from trades.csv
(notional = |pnl_dollars| / |price_move_pct|), stated in the output.
"""
import json, csv, math, statistics, sys, io
from collections import defaultdict
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = r"C:\Users\vince\WAGMI\bot\data"
RULES_CUR = BASE + r"\llm\graduated_rules.json"
RULES_BAK = BASE + r"\llm\graduated_rules.json.bak.20260619T161520Z"
CF = BASE + r"\llm\counterfactual_resolved.jsonl"
TRADES = BASE + r"\trades.csv"
OUT = r"C:\Users\vince\WAGMI\bot\tools\backtests\veto_rescore_results.json"

REGIME_SYNONYMS = {
    "illiquid": "low_liquidity", "trending": "trend", "ranging": "range",
    "volatile": "high_volatility", "trending_bull": "trend",
    "trending_bear": "trend", "consolidation": "range",
    "panic_oversold": "panic", "recovering": "trend",
}
def canon_regime(r):
    r = (r or "").strip().lower()
    return REGIME_SYNONYMS.get(r, r)

def canon_side(s):
    s = (s or "").upper()
    if s in ("BUY", "LONG"): return "LONG"
    if s in ("SELL", "SHORT"): return "SHORT"
    return s

def load_rules():
    rules = {}
    for path, prov in [(RULES_CUR, "current"), (RULES_BAK, "backup_20260619")]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data.get("rules", []):
            rid = r["rule_id"]
            if rid in rules:
                rules[rid]["provenance"] += "+" + prov
            else:
                r["provenance"] = prov
                rules[rid] = r
    return list(rules.values())

def rule_matches(rule, rec):
    c = rule["conditions"]
    if c.get("symbol") and rec["symbol"].upper() != c["symbol"].upper():
        return False
    if c.get("regime"):
        if canon_regime(c["regime"]) != canon_regime(rec["regime"]) and \
           (c["regime"] or "").lower() != (rec["regime"] or "").lower():
            return False
    if c.get("side") and canon_side(rec["side"]) != canon_side(c["side"]):
        return False
    if c.get("strategy") and rec["strategy"] != c["strategy"]:
        return False
    if c.get("strategies_include") or c.get("strategies_exclude") or \
       c.get("setup_type") or c.get("min_agree"):
        return None  # unmeasurable from cf record (no per-strategy metadata)
    conf = rec["confidence"]
    if "confidence_min" in c and conf < c["confidence_min"]: return False
    if "confidence_max" in c and conf > c["confidence_max"]: return False
    if "hour_utc_min" in c or "hour_utc_max" in c:
        h = rec["hour_utc"]
        if "hour_utc_min" in c and h < c["hour_utc_min"]: return False
        if "hour_utc_max" in c and h >= c["hour_utc_max"]: return False
    return True

def load_cf():
    recs = []
    with open(CF, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except Exception: continue
            if not r.get("resolved"): continue
            pnl = r.get("hypothetical_pnl_pct")
            if pnl is None: continue
            try:
                ts = datetime.fromisoformat(r["created_at"]).astimezone(timezone.utc)
            except Exception:
                continue
            recs.append({
                "symbol": r.get("symbol", ""), "side": r.get("side", ""),
                "regime": r.get("regime", ""), "strategy": r.get("strategy", ""),
                "confidence": float(r.get("confidence") or 0.0),
                "entry": float(r.get("entry_price") or 0.0),
                "pnl": float(pnl), "skip": r.get("skip_reason", ""),
                "ts": ts, "hour_utc": ts.hour,
            })
    recs.sort(key=lambda x: x["ts"])
    return recs

def episodes(matched):
    """Collapse scan-cycle duplicates into tradeable episodes."""
    by_key = defaultdict(list)
    for r in matched:
        by_key[(r["symbol"], canon_side(r["side"]))].append(r)
    eps = []
    for key, rs in by_key.items():
        rs.sort(key=lambda x: x["ts"])
        cur = [rs[0]]
        for r in rs[1:]:
            prev = cur[-1]
            gap_h = (r["ts"] - prev["ts"]).total_seconds() / 3600.0
            entry_drift = abs(r["entry"] - cur[0]["entry"]) / max(cur[0]["entry"], 1e-9)
            if gap_h <= 4.0 and entry_drift <= 0.015:
                cur.append(r)
            else:
                eps.append(cur); cur = [r]
        eps.append(cur)
    out = []
    for ep in eps:
        out.append({
            "symbol": ep[0]["symbol"], "side": ep[0]["side"],
            "ts": ep[0]["ts"], "n_raw": len(ep),
            "pnl": statistics.median([r["pnl"] for r in ep]),
        })
    out.sort(key=lambda x: x["ts"])
    return out

def saved_missed(items):
    saved = sum(abs(i["pnl"]) for i in items if i["pnl"] < 0)
    missed = sum(i["pnl"] for i in items if i["pnl"] > 0)
    losers = sum(1 for i in items if i["pnl"] < 0)
    winners = sum(1 for i in items if i["pnl"] > 0)
    return saved, missed, losers, winners

def load_trades():
    trades = []
    with open(TRADES, "r", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for row in rd:
            try:
                entry = float(row["entry"]); exit_ = float(row["exit"])
                pnl = float(row["pnl"]); fees = float(row.get("fees") or 0)
                ts = datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc)
            except Exception:
                continue
            move = abs(exit_ - entry) / entry if entry else 0
            notional = abs(pnl) / move if move > 1e-6 else None
            conf = 0.0
            try: conf = float(row.get("confidence") or 0)
            except Exception: pass
            trades.append({
                "symbol": row["symbol"], "side": row["side"],
                "regime": row.get("regime", ""), "strategy": row.get("strategy", ""),
                "confidence": conf, "pnl": pnl, "fees": fees, "ts": ts,
                "hour_utc": ts.hour, "notional": notional, "entry": entry,
            })
    return trades

def trade_matches(rule, t):
    c = rule["conditions"]
    if c.get("symbol") and t["symbol"].upper() != c["symbol"].upper(): return False
    if c.get("regime"):
        if canon_regime(c["regime"]) != canon_regime(t["regime"]) and \
           (c["regime"] or "").lower() != (t["regime"] or "").lower():
            return False
    if c.get("side") and canon_side(t["side"]) != canon_side(c["side"]): return False
    if c.get("strategy") and t["strategy"] != c["strategy"]: return False
    if c.get("strategies_include") or c.get("strategies_exclude") or \
       c.get("setup_type") or c.get("min_agree"):
        return None
    if "confidence_min" in c and t["confidence"] < c["confidence_min"]: return False
    if "confidence_max" in c and t["confidence"] > c["confidence_max"]: return False
    if "hour_utc_min" in c or "hour_utc_max" in c:
        h = t["hour_utc"]
        if "hour_utc_min" in c and h < c["hour_utc_min"]: return False
        if "hour_utc_max" in c and h >= c["hour_utc_max"]: return False
    return True

def fortnight_key(ts, t0):
    return int((ts - t0).days // 14)

def main():
    rules = load_rules()
    cf = load_cf()
    trades = load_trades()

    notionals = [t["notional"] for t in trades if t["notional"] and 100 < t["notional"] < 1e6]
    med_notional = statistics.median(notionals) if notionals else 0
    t0 = cf[0]["ts"]
    t_end = cf[-1]["ts"]

    print(f"cf resolved records: {len(cf)}  span {t0.date()} .. {t_end.date()}")
    print(f"trades: {len(trades)}  median notional ${med_notional:,.0f}  "
          f"(dollar conversion: $ = pct/100 * {med_notional:,.0f})")

    skipdist = defaultdict(int)
    for r in cf: skipdist[r["skip"]] += 1
    print("skip_reason dist:", dict(sorted(skipdist.items(), key=lambda x: -x[1])))

    results = []
    for rule in rules:
        rid = rule["rule_id"]
        action = rule["action"]
        matched, unmeasurable = [], False
        for r in cf:
            m = rule_matches(rule, r)
            if m is None: unmeasurable = True; break
            if m: matched.append(r)
        entry = {
            "rule_id": rid, "action": action, "active": rule.get("active"),
            "provenance": rule["provenance"], "conditions": rule["conditions"],
            "hypothesis": rule["hypothesis_statement"][:100],
        }
        if unmeasurable:
            entry["verdict"] = "UNMEASURABLE (conditions need per-strategy/setup metadata absent from cf records)"
            results.append(entry); continue

        eps = episodes(matched)
        s_raw, m_raw, l_raw, w_raw = saved_missed(matched)
        s_ep, m_ep, l_ep, w_ep = saved_missed(eps)
        # fortnight breakdown on episodes
        fn = defaultdict(lambda: [0.0, 0.0, 0, 0])
        for e in eps:
            k = fortnight_key(e["ts"], t0)
            if e["pnl"] < 0:
                fn[k][0] += abs(e["pnl"]); fn[k][2] += 1
            elif e["pnl"] > 0:
                fn[k][1] += e["pnl"]; fn[k][3] += 1
        fortnights = {}
        for k in sorted(fn):
            start = (t0 + __import__("datetime").timedelta(days=14 * k)).date().isoformat()
            sv, ms, lc, wc = fn[k]
            fortnights[start] = {
                "saved_pct": round(sv, 2), "missed_pct": round(ms, 2),
                "net_pct": round(sv - ms, 2), "losers": lc, "winners": wc,
                "net_usd": round((sv - ms) / 100 * med_notional, 2),
            }
        # actual trades matched
        tm = [t for t in trades if trade_matches(rule, t)]
        t_pnl = sum(t["pnl"] for t in tm)
        entry.update({
            "cf_matches_raw": len(matched), "cf_episodes": len(eps),
            "raw": {"saved_pct": round(s_raw, 2), "missed_pct": round(m_raw, 2),
                    "net_pct": round(s_raw - m_raw, 2), "losers": l_raw, "winners": w_raw},
            "episode": {"saved_pct": round(s_ep, 2), "missed_pct": round(m_ep, 2),
                        "net_pct": round(s_ep - m_ep, 2), "losers": l_ep, "winners": w_ep,
                        "net_usd": round((s_ep - m_ep) / 100 * med_notional, 2)},
            "fortnights": fortnights,
            "actual_trades_matched": len(tm),
            "actual_trades_pnl_usd": round(t_pnl, 2),
        })
        net_ep = s_ep - m_ep
        if action == "veto":
            if len(eps) < 5:
                v = "UNMEASURABLE (n<5 episodes)"
            elif net_ep > 0:
                v = "DOLLAR-POSITIVE (keep)"
            else:
                v = "DOLLAR-NEGATIVE (retire candidate)"
        elif action == "penalize":
            if len(eps) < 5:
                v = "UNMEASURABLE (n<5 episodes)"
            elif net_ep > 0:
                v = "DOLLAR-POSITIVE if it blocks (keep; partial-block upper bound)"
            else:
                v = "DOLLAR-NEGATIVE if it blocks (retire candidate)"
        else:  # boost
            net_boost = m_ep - s_ep  # boost promotes: winners good, losers bad
            entry["episode"]["net_boost_pct"] = round(net_boost, 2)
            entry["episode"]["net_boost_usd"] = round(net_boost / 100 * med_notional, 2)
            if len(eps) < 5:
                v = "UNMEASURABLE (n<5 episodes)"
            elif net_boost > 0:
                v = "DOLLAR-POSITIVE boost (keep)"
            else:
                v = "DOLLAR-NEGATIVE boost (retire candidate)"
        entry["verdict"] = v
        results.append(entry)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"meta": {
            "cf_records": len(cf), "span": [str(t0), str(t_end)],
            "median_notional_usd": med_notional,
            "skip_reason_dist": dict(skipdist),
        }, "rules": results}, f, indent=1, default=str)

    for e in results:
        ep = e.get("episode", {})
        print(f"\n{e['rule_id']} [{e['action']}] active={e['active']} prov={e['provenance']}")
        print(f"  cond={e['conditions']}")
        print(f"  raw={e.get('cf_matches_raw','-')} eps={e.get('cf_episodes','-')} "
              f"saved={ep.get('saved_pct','-')}% missed={ep.get('missed_pct','-')}% "
              f"net={ep.get('net_pct','-')}% (${ep.get('net_usd','-')}) "
              f"L/W={ep.get('losers','-')}/{ep.get('winners','-')}")
        print(f"  actual trades matched={e.get('actual_trades_matched','-')} "
              f"pnl=${e.get('actual_trades_pnl_usd','-')}")
        print(f"  VERDICT: {e['verdict']}")

if __name__ == "__main__":
    main()
