"""Gate-ROC study on signal_outcomes.jsonl (56k raw records, Jun 2 - Jul 2 2026).

Scores every logged signal (passed AND rejected) against HL 15m candle ground truth
at 1h/4h/24h horizons, then evaluates:
  - confidence as a ranker (AUC, bins), era- and side-split
  - each gate's precision/EV (money saved vs money cost)
  - gate redundancy matrix
  - confidence-floor threshold sweep (EV-maximizing floor)

Honesty notes baked in:
  - raw log is ~30s re-emissions of the same signal; primary unit is EPISODE
    (consecutive same (sym, side, conf) collapsed within 45 min).
  - era split: E1 Jun2-5 (crash week tail), E2 Jun6-10, E3 Jun17-Jul2
    (bot dark Jun10-16; floor regime also changed: 20 -> 58/62/66/71 on Jun17+).
"""
import json, math, collections, bisect, datetime as dt

SIG = r"C:\Users\vince\WAGMI\bot\data\logs\signal_outcomes.jsonl"
CANDLES = r"C:\Users\vince\WAGMI\bot\tools\research\gate_roc_candles_15m.json"
OUT = r"C:\Users\vince\WAGMI\bot\tools\research\gm_gate_roc_results.json"

HORIZONS = {"1h": 4, "4h": 16, "24h": 96}  # in 15m candles

# ---------- load candles ----------
cd = json.load(open(CANDLES))
ct = {s: [r[0] // 1000 for r in rows] for s, rows in cd.items()}
cc = {s: [r[4] for r in rows] for s, rows in cd.items()}

def fwd(sym, ts, nc):
    """directional-agnostic forward return: close[i+nc]/close[i]-1, i = candle containing ts."""
    t = ct[sym]
    i = bisect.bisect_right(t, ts) - 1
    if i < 0 or i + nc >= len(t):
        return None
    # guard gaps
    if t[i + nc] - t[i] > nc * 900 + 1800:
        return None
    return cc[sym][i + nc] / cc[sym][i] - 1.0

# ---------- load + episode-collapse ----------
recs = [json.loads(l) for l in open(SIG, encoding="utf-8", errors="replace") if l.strip()]
recs.sort(key=lambda r: r["ts"])

def era(ts):
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
    if d <= dt.date(2026, 6, 5):
        return "E1"
    if d <= dt.date(2026, 6, 16):
        return "E2"
    return "E3"

episodes = []
last = {}
for r in recs:
    k = (r["sym"], r["side"], round(r["conf"], 2))
    rej = frozenset(a["gate"] for a in r["annotations"] if a.get("severity") in ("reject", "rej"))
    if k in last and r["ts"] - last[k]["ts_last"] < 2700:
        e = last[k]
        e["ts_last"] = r["ts"]
        e["n_raw"] += 1
        e["rej"] |= set(rej)
        e["passed"] = e["passed"] or r["passed"]
        continue
    e = {
        "ts": r["ts"], "ts_last": r["ts"], "sym": r["sym"], "side": r["side"],
        "conf": r["conf"], "passed": r["passed"], "rej": set(rej), "n_raw": 1,
        "era": era(r["ts"]), "n_agree": r.get("n_agree"),
        "floor": next((a["threshold"] for a in r["annotations"] if a["gate"] == "confidence_floor"), None),
        "gate_conf": next((a["value"] for a in r["annotations"] if a["gate"] == "confidence_floor"), None),
        "ev_est": (r.get("meta") or {}).get("ev_per_dollar"),
        "chop": (r.get("meta") or {}).get("chop_score_smoothed"),
        "llm": ("llm_execute" if any(a["gate"] == "llm_execute" for a in r["annotations"])
                else "llm_skip" if any(a["gate"] == "llm_skip" for a in r["annotations"]) else None),
    }
    episodes.append(e)
    last[k] = e

# score
sgn = {"BUY": 1.0, "SELL": -1.0}
scored = 0
for e in episodes:
    e["ret"] = {}
    for h, nc in HORIZONS.items():
        f = fwd(e["sym"], e["ts"], nc)
        e["ret"][h] = None if f is None else sgn[e["side"]] * f * 1e4  # bps
    if e["ret"]["4h"] is not None:
        scored += 1

# ---------- helpers ----------
def auc(pos, neg):
    """Mann-Whitney AUC: P(score_pos > score_neg)."""
    if not pos or not neg:
        return None
    allv = sorted(pos + neg)
    import bisect as b
    def rank_sum(vals):
        s = 0.0
        for v in vals:
            lo = b.bisect_left(allv, v); hi = b.bisect_right(allv, v)
            s += (lo + hi + 1) / 2.0
        return s
    r1 = rank_sum(pos)
    n1, n2 = len(pos), len(neg)
    return (r1 - n1 * (n1 + 1) / 2.0) / (n1 * n2)

def stats(rs):
    rs = [r for r in rs if r is not None]
    if not rs:
        return {"n": 0}
    n = len(rs)
    mean = sum(rs) / n
    wr = sum(1 for r in rs if r > 0) / n
    sd = (sum((r - mean) ** 2 for r in rs) / max(n - 1, 1)) ** 0.5
    se = sd / n ** 0.5
    return {"n": n, "mean_bps": round(mean, 1), "wr": round(wr, 3), "se_bps": round(se, 1),
            "median_bps": round(sorted(rs)[n // 2], 1)}

def fragility(rs):
    rs = sorted([r for r in rs if r is not None], reverse=True)
    if len(rs) < 2:
        return None
    return round(sum(rs[1:]) / (len(rs) - 1), 1)  # mean without best

R = {"n_raw": len(recs), "n_episodes": len(episodes), "n_scored_4h": scored}

# ---------- 1. confidence as ranker ----------
conf_roc = {}
for h in HORIZONS:
    for split_name, filt in [("all", lambda e: True), ("BUY", lambda e: e["side"] == "BUY"),
                             ("SELL", lambda e: e["side"] == "SELL"),
                             ("E1", lambda e: e["era"] == "E1"), ("E2", lambda e: e["era"] == "E2"),
                             ("E3", lambda e: e["era"] == "E3")]:
        sub = [e for e in episodes if filt(e) and e["ret"][h] is not None]
        pos = [e["conf"] for e in sub if e["ret"][h] > 0]
        neg = [e["conf"] for e in sub if e["ret"][h] <= 0]
        a = auc(pos, neg)
        # rank corr of conf vs ret (spearman-lite via AUC is enough); also mean ret top vs bottom half
        conf_roc[f"{h}|{split_name}"] = {"n": len(sub), "n_win": len(pos),
                                         "auc": None if a is None else round(a, 3)}
R["conf_auc"] = conf_roc

# confidence bins
bins = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
bt = {}
for h in ["4h", "24h"]:
    for split in ["all", "E1", "E3", "BUY", "SELL"]:
        rows = {}
        for lo, hi in bins:
            sub = [e["ret"][h] for e in episodes
                   if lo <= e["conf"] < hi and e["ret"][h] is not None
                   and (split == "all" or e["era"] == split or e["side"] == split)]
            rows[f"{lo}-{hi-1}"] = stats(sub)
        bt[f"{h}|{split}"] = rows
R["conf_bins"] = bt

# ---------- 2. per-gate EV ----------
gates = ["confidence_floor", "volume_chop", "llm_skip"]
gate_ev = {}
for h in ["4h", "24h"]:
    for g in gates:
        for split in ["all", "E1", "E2", "E3"]:
            rej = [e["ret"][h] for e in episodes if g in e["rej"] and e["ret"][h] is not None
                   and (split == "all" or e["era"] == split)]
            ok = [e["ret"][h] for e in episodes if g not in e["rej"] and e["ret"][h] is not None
                  and (split == "all" or e["era"] == split)]
            gate_ev[f"{g}|{h}|{split}"] = {"rejected": stats(rej), "not_rejected": stats(ok)}
R["gate_ev"] = gate_ev

# passed vs all-rejected
for h in ["4h", "24h"]:
    for split in ["all", "E1", "E3"]:
        p = [e["ret"][h] for e in episodes if e["passed"] and e["ret"][h] is not None
             and (split == "all" or e["era"] == split)]
        r_ = [e["ret"][h] for e in episodes if not e["passed"] and e["ret"][h] is not None
              and (split == "all" or e["era"] == split)]
        R.setdefault("passed_vs_rejected", {})[f"{h}|{split}"] = {"passed": stats(p), "rejected": stats(r_),
                                                                  "passed_mean_wo_best": fragility([x for x in p])}

# LLM stage (only llm_first pipeline records)
for h in ["4h", "24h"]:
    ex = [e["ret"][h] for e in episodes if e["llm"] == "llm_execute" and e["ret"][h] is not None]
    sk = [e["ret"][h] for e in episodes if e["llm"] == "llm_skip" and e["ret"][h] is not None]
    R.setdefault("llm_gate", {})[h] = {"execute": stats(ex), "skip": stats(sk),
                                       "execute_mean_wo_best": fragility(ex)}

# ---------- 3. redundancy ----------
rejected_eps = [e for e in episodes if e["rej"]]
pair = collections.Counter()
solo = collections.Counter()
tot = collections.Counter()
for e in rejected_eps:
    gs = sorted(e["rej"])
    for g in gs:
        tot[g] += 1
    if len(gs) == 1:
        solo[gs[0]] += 1
    for i in range(len(gs)):
        for j in range(i + 1, len(gs)):
            pair[(gs[i], gs[j])] += 1
R["redundancy"] = {
    "n_rejected_episodes": len(rejected_eps),
    "gate_totals": dict(tot),
    "solo_rejections": dict(solo),
    "pair_overlap": {f"{a}&{b}": c for (a, b), c in pair.most_common(10)},
}
# unique saves: EV of episodes rejected ONLY by gate g
for h in ["4h", "24h"]:
    for g in gates:
        only = [e["ret"][h] for e in rejected_eps if e["rej"] == {g} and e["ret"][h] is not None]
        R["redundancy"].setdefault(f"unique_ev_{h}", {})[g] = stats(only)

# ---------- 4. threshold sweep ----------
sweep = {}
for h in ["4h", "24h"]:
    for split in ["all", "E1", "E2", "E3", "BUY", "SELL"]:
        rows = {}
        sub = [e for e in episodes if e["ret"][h] is not None
               and (split == "all" or e["era"] == split or e["side"] == split)]
        for f in range(0, 100, 5):
            rs = [e["ret"][h] for e in sub if e["conf"] >= f]
            below = [e["ret"][h] for e in sub if e["conf"] < f]
            s = stats(rs)
            s["blocked_mean_bps"] = stats(below).get("mean_bps")
            s["blocked_n"] = len(below)
            rows[f] = s
        sweep[f"{h}|{split}"] = rows
R["floor_sweep"] = sweep

# actual floors used late era: 58,62,66,71 — EV of the marginal band (58-71) in E3
for h in ["4h", "24h"]:
    band = [e["ret"][h] for e in episodes if e["era"] == "E3" and 58 <= e["conf"] < 71 and e["ret"][h] is not None]
    R.setdefault("marginal_band_E3", {})[h] = stats(band)

# ---------- 5. bot's own ev_per_dollar as ranker ----------
for h in ["4h", "24h"]:
    sub = [e for e in episodes if e["ev_est"] is not None and e["ret"][h] is not None]
    pos = [e["ev_est"] for e in sub if e["ret"][h] > 0]
    neg = [e["ev_est"] for e in sub if e["ret"][h] <= 0]
    a = auc(pos, neg)
    R.setdefault("ev_est_auc", {})[h] = {"n": len(sub), "auc": None if a is None else round(a, 3)}
# chop score as ranker (lower chop should mean better outcome -> auc<0.5 if predictive)
for h in ["4h", "24h"]:
    sub = [e for e in episodes if e["chop"] is not None and e["ret"][h] is not None]
    pos = [e["chop"] for e in sub if e["ret"][h] > 0]
    neg = [e["chop"] for e in sub if e["ret"][h] <= 0]
    a = auc(pos, neg)
    R.setdefault("chop_auc", {})[h] = {"n": len(sub), "auc": None if a is None else round(a, 3)}

# era + side base rates
for split in ["E1", "E2", "E3"]:
    for side in ["BUY", "SELL"]:
        sub = [e["ret"]["4h"] for e in episodes if e["era"] == split and e["side"] == side and e["ret"]["4h"] is not None]
        R.setdefault("base_rates_4h", {})[f"{split}|{side}"] = stats(sub)

json.dump(R, open(OUT, "w"), indent=1)
print("saved", OUT)
print("episodes:", len(episodes), "scored@4h:", scored)
