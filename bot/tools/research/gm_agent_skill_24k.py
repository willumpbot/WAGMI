# GM_AGENT_SKILL_24K — per-agent skill attribution from agent_performance.jsonl (24.4k calls)
# Ground truth: HL 1h candles (gm_candles_1h.json), trade_ledger.csv, counterfactual_resolved.jsonl
# READ-ONLY on bot code. Standard: THE_STANDARD.md v1.3 (denominators, era-split, week-1 test).
import json, csv, re, bisect, statistics, collections, datetime

ROOT = r"C:\Users\vince\WAGMI"
recs = [json.loads(l) for l in open(ROOT + r"\bot\data\llm\agent_performance.jsonl", encoding="utf-8")]
candles = json.load(open(ROOT + r"\bot\tools\research\gm_candles_1h.json"))
ledger = list(csv.DictReader(open(ROOT + r"\bot\data\trade_ledger.csv", encoding="utf-8")))
cfs = []
_bad_cf = 0
for l in open(ROOT + r"\bot\data\llm\counterfactual_resolved.jsonl", encoding="utf-8"):
    try:
        cfs.append(json.loads(l))
    except Exception:
        _bad_cf += 1

CTIMES = {s: [c["t"] / 1000 for c in v] for s, v in candles.items()}

WEEK1_END = 1780704000  # 2026-06-05 00:00 UTC  (May30-Jun5 crash week)
def era(ts):
    if ts < WEEK1_END: return "wk1"
    if ts < 1782000000: return "mid"   # Jun5 - Jun20ish
    return "late"

def fwd_ret(sym, ts, hours):
    """forward pct return close(ts+h)/close(ts)-1 from candle whose bar contains ts"""
    if sym not in CTIMES: return None
    times = CTIMES[sym]; cs = candles[sym]
    i = bisect.bisect_right(times, ts) - 1
    j = i + hours
    if i < 0 or j >= len(cs): return None
    return cs[j]["c"] / cs[i]["c"] - 1

def realized(sym, ts, lookback=24):
    """mechanical stats over prior `lookback` 1h bars: trend ret, vol (std of 1h rets), ATR%"""
    if sym not in CTIMES: return None
    times = CTIMES[sym]; cs = candles[sym]
    i = bisect.bisect_right(times, ts) - 1
    if i - lookback < 0: return None
    w = cs[i - lookback:i + 1]
    rets = [w[k + 1]["c"] / w[k]["c"] - 1 for k in range(len(w) - 1)]
    trend = w[-1]["c"] / w[0]["c"] - 1
    vol = statistics.pstdev(rets)
    atr = statistics.mean((b["h"] - b["l"]) / b["c"] for b in w)
    return {"trend": trend, "vol": vol, "atr": atr}

def mech_label(sym, ts):
    """mechanical regime: trend if |24h ret| > 1.5*sqrt(24)*hourly vol... simple: |trend|/ (vol*sqrt24)"""
    r = realized(sym, ts)
    if not r or r["vol"] == 0: return None
    z = r["trend"] / (r["vol"] * (24 ** 0.5))
    if r["vol"] > 0.008: base = "high_volatility"
    elif z > 1.0: base = "trending_bull"
    elif z < -1.0: base = "trending_bear"
    else: base = "range"
    return base

SIDE_RE_SHORT = re.compile(r"\b(SHORT|SELL|short|sell|bear(?:ish)? (?:thesis|entry)|downtrend continuation)\b")
SIDE_RE_LONG = re.compile(r"\b(LONG|BUY|long|buy|bull(?:ish)? (?:thesis|entry)|uptrend continuation)\b")
def infer_side(txt):
    s = bool(SIDE_RE_SHORT.search(txt)); l = bool(SIDE_RE_LONG.search(txt))
    if s and not l: return "SHORT"
    if l and not s: return "LONG"
    return None

out = {}

# ---------------- pipelines ----------------
pipes = collections.defaultdict(dict)
for r in recs:
    pipes[r["pipeline_id"]][r["agent_role"]] = r

# ---------------- TRADE agent ----------------
trade = [r for r in recs if r["agent_role"] == "trade"]
go = [r for r in trade if r["decision"] in ("go", "flip")]
res = {"n_calls": len(trade), "n_go": len(go)}
# side inference
go_sided = [(r, infer_side(r["reasoning_summary"])) for r in go]
res["go_side_match_rate"] = sum(1 for _, s in go_sided if s) / max(1, len(go))
# score go vs 4h and 24h fwd return in trade direction
def dir_score(rows, hours):
    vals = [(r["confidence"], (1 if s == "LONG" else -1) * fr)
            for r, s in rows if s and (fr := fwd_ret(r["symbol"], r["timestamp"], hours)) is not None]
    return vals
for h in (4, 24):
    v = dir_score(go_sided, h)
    if v:
        rets = [x[1] for x in v]
        res[f"go_{h}h"] = {"n": len(v), "mean_bps": statistics.mean(rets) * 1e4,
                           "wr": sum(1 for x in rets if x > 0) / len(v)}
        # era split
        by_era = collections.defaultdict(list)
        for (r, s) in go_sided:
            fr = fwd_ret(r["symbol"], r["timestamp"], h)
            if s and fr is not None: by_era[era(r["timestamp"])].append((1 if s == "LONG" else -1) * fr)
        res[f"go_{h}h"]["era"] = {e: {"n": len(x), "mean_bps": statistics.mean(x) * 1e4,
                                      "wr": sum(1 for y in x if y > 0) / len(x)} for e, x in by_era.items()}
# confidence vs outcome (go only)
v = dir_score(go_sided, 4)
if len(v) > 20:
    cs = [x[0] for x in v]; rs = [x[1] for x in v]
    mc, mr = statistics.mean(cs), statistics.mean(rs)
    cov = sum((c - mc) * (r - mr) for c, r in zip(cs, rs)) / len(v)
    sd = statistics.pstdev(cs) * statistics.pstdev(rs)
    res["go_conf_corr_4h"] = cov / sd if sd else None
    hi = [r for c, r in v if c >= statistics.median(cs)]
    lo = [r for c, r in v if c < statistics.median(cs)]
    res["go_conf_split_4h"] = {"hi_conf": {"n": len(hi), "mean_bps": statistics.mean(hi) * 1e4},
                               "lo_conf": {"n": len(lo), "mean_bps": statistics.mean(lo) * 1e4}}
# skip quality via counterfactuals: match cf created_at ~ trade skip ts (same symbol, +/-10min)
cf_by_sym = collections.defaultdict(list)
for c in cfs:
    ts = datetime.datetime.fromisoformat(c["created_at"]).timestamp()
    cf_by_sym[c["symbol"]].append((ts, c))
for v_ in cf_by_sym.values(): v_.sort(key=lambda x: x[0])
def match_cf(sym, ts, tol=600):
    arr = cf_by_sym.get(sym, [])
    i = bisect.bisect_left(arr, (ts - tol,))
    best = None
    while i < len(arr) and arr[i][0] <= ts + tol:
        if best is None or abs(arr[i][0] - ts) < abs(best[0] - ts): best = arr[i]
        i += 1
    return best[1] if best else None
skips = [r for r in trade if r["decision"] == "skip"]
mskip = [(r, match_cf(r["symbol"], r["timestamp"])) for r in skips]
mm = [(r, c) for r, c in mskip if c and c.get("hypothetical_pnl_pct") is not None]
res["skip_cf_match_rate"] = len(mm) / max(1, len(skips))
if mm:
    p = [c["hypothetical_pnl_pct"] for _, c in mm]
    res["skips_cf"] = {"n": len(mm), "mean_hypo_pnl_pct": statistics.mean(p),
                       "would_win_rate": sum(1 for x in p if x > 0) / len(p)}
out["trade"] = res

# ---------------- CRITIC ----------------
critic = [r for r in recs if r["agent_role"] == "critic"]
ch = [r for r in critic if r["decision"] == "challenge"]
res = {"n_calls": len(critic), "n_challenge": len(ch)}
# For each challenge, get the pipeline's trade decision + inferred side; score what the challenged trade would have done
rows = []
for r in ch:
    p = pipes[r["pipeline_id"]]
    t = p.get("trade")
    if not t: continue
    s = infer_side(t["reasoning_summary"]) or infer_side(r["reasoning_summary"])
    rows.append((r, t, s))
res["challenge_with_trade_ctx"] = len(rows)
res["challenged_trade_decisions"] = dict(collections.Counter(t["decision"] for _, t, _ in rows))
ch_go = [(r, t, s) for r, t, s in rows if t["decision"] in ("go", "flip") and s]
res["challenged_go_sided_n"] = len(ch_go)
for h in (4, 24):
    v = [(1 if s == "LONG" else -1) * fr for r, t, s in ch_go
         if (fr := fwd_ret(r["symbol"], r["timestamp"], h)) is not None]
    if v:
        res[f"vetoed_go_{h}h"] = {"n": len(v), "mean_bps": statistics.mean(v) * 1e4,
                                  "would_win_rate": sum(1 for x in v if x > 0) / len(v)}
# approvals of go: baseline for comparison
ap_go = []
for r in critic:
    if r["decision"] != "approve": continue
    t = pipes[r["pipeline_id"]].get("trade")
    if t and t["decision"] in ("go", "flip"):
        s = infer_side(t["reasoning_summary"])
        if s: ap_go.append((r, t, s))
for h in (4, 24):
    v = [(1 if s == "LONG" else -1) * fr for r, t, s in ap_go
         if (fr := fwd_ret(r["timestamp"] and r["symbol"], r["timestamp"], h)) is not None] if False else \
        [(1 if s == "LONG" else -1) * fr for r, t, s in ap_go
         if (fr := fwd_ret(r["symbol"], r["timestamp"], h)) is not None]
    if v:
        res[f"approved_go_{h}h"] = {"n": len(v), "mean_bps": statistics.mean(v) * 1e4,
                                    "win_rate": sum(1 for x in v if x > 0) / len(v)}
out["critic"] = res

# ---------------- REGIME ----------------
reg = [r for r in recs if r["agent_role"] == "regime" and r["symbol"] in CTIMES]
res = {"n_calls": len(reg)}
lbl_norm = {"trend": None, "consolidation": "range", "low_liquidity": "range", "panic": "high_volatility"}
agree = tot = 0
conf_by_agree = {True: [], False: []}
dir_rows_llm, dir_rows_mech = [], []
for r in reg:
    m = mech_label(r["symbol"], r["timestamp"])
    if not m: continue
    d = r["decision"]
    dn = lbl_norm.get(d, d)
    if dn is None:  # 'trend' ambiguous direction — resolve by sign of 24h trend in reasoning? skip for agreement
        pass
    else:
        tot += 1
        a = (dn == m)
        agree += a
        conf_by_agree[a].append(r["confidence"])
    # directional value: trending_bull/bear as a forecast of next 4h
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is not None:
        if d == "trending_bull": dir_rows_llm.append(fr)
        elif d == "trending_bear": dir_rows_llm.append(-fr)
        if m == "trending_bull": dir_rows_mech.append(fr)
        elif m == "trending_bear": dir_rows_mech.append(-fr)
res["mech_agreement"] = {"n": tot, "rate": agree / max(1, tot)}
res["conf_when_agree"] = statistics.mean(conf_by_agree[True]) if conf_by_agree[True] else None
res["conf_when_disagree"] = statistics.mean(conf_by_agree[False]) if conf_by_agree[False] else None
res["llm_trend_calls_fwd4h"] = {"n": len(dir_rows_llm), "mean_bps": statistics.mean(dir_rows_llm) * 1e4,
                                "hit": sum(1 for x in dir_rows_llm if x > 0) / len(dir_rows_llm)} if dir_rows_llm else None
res["mech_trend_calls_fwd4h"] = {"n": len(dir_rows_mech), "mean_bps": statistics.mean(dir_rows_mech) * 1e4,
                                 "hit": sum(1 for x in dir_rows_mech if x > 0) / len(dir_rows_mech)} if dir_rows_mech else None
# era split of LLM trend skill
by_era = collections.defaultdict(list)
for r in reg:
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is None: continue
    if r["decision"] == "trending_bull": by_era[era(r["timestamp"])].append(fr)
    elif r["decision"] == "trending_bear": by_era[era(r["timestamp"])].append(-fr)
res["llm_trend_era"] = {e: {"n": len(v), "mean_bps": statistics.mean(v) * 1e4} for e, v in by_era.items()}
# regime confidence calibration: conf vs whether trend call hit
cal = []
for r in reg:
    if r["decision"] not in ("trending_bull", "trending_bear"): continue
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is None: continue
    hit = (fr > 0) == (r["decision"] == "trending_bull")
    cal.append((r["confidence"], hit))
if len(cal) > 20:
    med = statistics.median(c for c, _ in cal)
    hi = [h for c, h in cal if c >= med]; lo = [h for c, h in cal if c < med]
    res["conf_calibration_trend"] = {"hi_conf_hit": sum(hi) / len(hi), "n_hi": len(hi),
                                     "lo_conf_hit": sum(lo) / len(lo), "n_lo": len(lo)}
out["regime"] = res

# ---------------- EXIT ----------------
ex = [r for r in recs if r["agent_role"] == "exit" and r["symbol"] in CTIMES]
res = {"n_calls": len(ex)}
def exit_score(rows, h):
    v = []
    for r in rows:
        fr = fwd_ret(r["symbol"], r["timestamp"], h)
        if fr is None: continue
        pos = (1 if r["side"] == "LONG" else -1) * fr  # what the position would have earned next h hours
        v.append(pos)
    return v
for dec in ("full_close", "hold", "partial_close", "tighten_sl"):
    rows = [r for r in ex if r["decision"] == dec]
    d = {}
    for h in (4, 24):
        v = exit_score(rows, h)
        if v: d[f"pos_fwd_{h}h"] = {"n": len(v), "mean_bps": statistics.mean(v) * 1e4,
                                    "pos_up_rate": sum(1 for x in v if x > 0) / len(v)}
    res[dec] = d
# era split for full_close 4h
by_era = collections.defaultdict(list)
for r in ex:
    if r["decision"] != "full_close": continue
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is not None: by_era[era(r["timestamp"])].append((1 if r["side"] == "LONG" else -1) * fr)
res["full_close_era_4h"] = {e: {"n": len(v), "mean_bps": statistics.mean(v) * 1e4} for e, v in by_era.items()}
out["exit"] = res

# ---------------- QUANT ----------------
q = [r for r in recs if r["agent_role"] == "quant" and r["symbol"] in CTIMES]
res = {"n_calls": len(q)}
def qev(r):
    m = re.match(r"ev=(long|short|neutral)", r["decision"])
    if m: return m.group(1)
    m = re.match(r"(long|short|neutral),", r["decision"])
    return m.group(1) if m else None
rows = [(r, qev(r)) for r in q]
res["ev_parse_rate"] = sum(1 for _, e in rows if e) / max(1, len(q))
for h in (4, 24):
    d = {}
    for side in ("long", "short"):
        v = [(1 if side == "long" else -1) * fr for r, e in rows if e == side
             and (fr := fwd_ret(r["symbol"], r["timestamp"], h)) is not None]
        if v: d[side] = {"n": len(v), "mean_bps": statistics.mean(v) * 1e4,
                         "hit": sum(1 for x in v if x > 0) / len(v)}
    res[f"ev_dir_{h}h"] = d
# era split combined directional
by_era = collections.defaultdict(list)
for r, e in rows:
    if e not in ("long", "short"): continue
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is not None: by_era[era(r["timestamp"])].append((1 if e == "long" else -1) * fr)
res["ev_dir_era_4h"] = {er: {"n": len(v), "mean_bps": statistics.mean(v) * 1e4} for er, v in by_era.items()}
# quality=noise vs marginal: does 'marginal' (tradeable) mark better fwd |move| realization for the pipeline's trade?
out["quant"] = res

# ---------------- RISK ----------------
rk = [r for r in recs if r["agent_role"] == "risk"]
res = {"n_calls": len(rk)}
def rsize(r):
    m = re.match(r"size=([\d.]+)", r["decision"])
    return float(m.group(1)) if m else None
# when pipeline trade=go, did risk size correlate with outcome?
rows = []
for r in rk:
    p = pipes[r["pipeline_id"]]
    t = p.get("trade")
    if not t or t["decision"] not in ("go", "flip"): continue
    s = infer_side(t["reasoning_summary"])
    sz = rsize(r)
    if s is None or sz is None: continue
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is None: continue
    rows.append((sz, (1 if s == "LONG" else -1) * fr))
if rows:
    zero = [x for s_, x in rows if s_ == 0]
    pos = [x for s_, x in rows if s_ > 0]
    res["on_go_4h"] = {"sized0": {"n": len(zero), "mean_bps": statistics.mean(zero) * 1e4} if zero else None,
                       "sized>0": {"n": len(pos), "mean_bps": statistics.mean(pos) * 1e4} if pos else None}
out["risk"] = res

# ---------------- ledger match for trade go ----------------
led = [(float(t["timestamp"]), t) for t in ledger]
led.sort()
def match_trade(sym, ts, tol=3600):
    best = None
    for lt, t in led:
        if t["symbol"] != sym: continue
        if abs(lt - ts) <= tol and (best is None or abs(lt - ts) < abs(best[0] - ts)): best = (lt, t)
    return best[1] if best else None
gm = [(r, match_trade(r["symbol"], r["timestamp"])) for r in go]
gmm = [(r, t) for r, t in gm if t]
out["trade"]["go_ledger_match_rate"] = len(gmm) / max(1, len(go))
if gmm:
    pn = [float(t["net_pnl"]) for _, t in gmm]
    out["trade"]["go_matched_ledger"] = {"n": len(gmm), "sum_net_pnl": sum(pn), "mean": statistics.mean(pn),
                                         "wr": sum(1 for x in pn if x > 0) / len(pn)}

# ---------------- cost proxies ----------------
lat = collections.defaultdict(list)
for r in recs: lat[r["agent_role"]].append(r["latency_ms"])
out["latency_sec_total"] = {k: round(sum(v) / 1000) for k, v in lat.items()}
opus = collections.Counter(r["agent_role"] for r in recs if "opus" in r["model_used"])
out["opus_calls_by_role"] = dict(opus)

# ---------------- adversarial extras ----------------
ext = {}
# decision + confidence distribution per role
dd = collections.defaultdict(collections.Counter)
cd = collections.defaultdict(list)
for r in recs:
    dd[r["agent_role"]][r["decision"]] += 1
    cd[r["agent_role"]].append(r["confidence"])
ext["decisions_by_role"] = {k: dict(v.most_common(8)) for k, v in dd.items()}
ext["conf_by_role"] = {k: {"mean": round(statistics.mean(v), 3), "stdev": round(statistics.pstdev(v), 3),
                           "n_distinct": len(set(v))} for k, v in cd.items()}
# side field population by role
ext["side_field_populated"] = {k: sum(1 for r in recs if r["agent_role"] == k and r["side"]) for k in dd}

# critic era split: vetoed vs approved go, 24h
def era_split(rows_dirret):
    by = collections.defaultdict(list)
    for e_, x in rows_dirret: by[e_].append(x)
    return {e_: {"n": len(v), "mean_bps": round(statistics.mean(v) * 1e4, 1),
                 "wr": round(sum(1 for y in v if y > 0) / len(v), 3)} for e_, v in by.items()}
for name, grp in (("vetoed", ch_go), ("approved", ap_go)):
    for h in (4, 24):
        rows_ = [(era(r["timestamp"]), (1 if s == "LONG" else -1) * fr) for r, t, s in grp
                 if (fr := fwd_ret(r["symbol"], r["timestamp"], h)) is not None]
        ext[f"critic_{name}_go_{h}h_era"] = era_split(rows_)

# quant 24h era split (recompute — `rows` was shadowed by the risk section)
qrows = [(r, qev(r)) for r in q]
rows_ = [(era(r["timestamp"]), (1 if e_ == "long" else -1) * fr) for r, e_ in qrows
         if e_ in ("long", "short") and (fr := fwd_ret(r["symbol"], r["timestamp"], 24)) is not None]
ext["quant_ev_dir_24h_era"] = era_split(rows_)
# quant short-only era (dominant side)
rows_s = [(era(r["timestamp"]), -fr) for r, e_ in qrows
          if e_ == "short" and (fr := fwd_ret(r["symbol"], r["timestamp"], 24)) is not None]
ext["quant_short_24h_era"] = era_split(rows_s)

# quant confidence calibration on directional calls (4h)
qc = [(r["confidence"], (1 if e_ == "long" else -1) * fr) for r, e_ in qrows
      if e_ in ("long", "short") and (fr := fwd_ret(r["symbol"], r["timestamp"], 4)) is not None]
if len(qc) > 40 and len(set(c for c,_ in qc))>1:
    med = statistics.median(c for c, _ in qc)
    hi = [x for c, x in qc if c > med]; lo = [x for c, x in qc if c <= med]
    ext["quant_conf_split_4h"] = {"hi": {"n": len(hi), "mean_bps": round(statistics.mean(hi) * 1e4, 1)},
                                  "lo": {"n": len(lo), "mean_bps": round(statistics.mean(lo) * 1e4, 1)}}

# exit hold era split (4h)
rows_ = [(era(r["timestamp"]), (1 if r["side"] == "LONG" else -1) * fr) for r in ex
         if r["decision"] == "hold" and (fr := fwd_ret(r["symbol"], r["timestamp"], 4)) is not None]
ext["exit_hold_4h_era"] = era_split(rows_)
# exit confidence calibration on full_close (did close avoid a further adverse move?)
ec = [(r["confidence"], -(1 if r["side"] == "LONG" else -1) * fr) for r in ex
      if r["decision"] == "full_close" and (fr := fwd_ret(r["symbol"], r["timestamp"], 4)) is not None]
if len(ec) > 40 and len(set(c for c,_ in ec))>1:
    med = statistics.median(c for c, _ in ec)
    hi = [x for c, x in ec if c > med]; lo = [x for c, x in ec if c <= med]
    ext["exit_close_conf_split_savings4h"] = {"hi": {"n": len(hi), "mean_bps": round(statistics.mean(hi) * 1e4, 1)},
                                              "lo": {"n": len(lo), "mean_bps": round(statistics.mean(lo) * 1e4, 1)}}

# regime era hit rates (not just bps)
by_era2 = collections.defaultdict(list)
for r in reg:
    if r["decision"] not in ("trending_bull", "trending_bear"): continue
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is None: continue
    by_era2[era(r["timestamp"])].append((fr > 0) == (r["decision"] == "trending_bull"))
ext["regime_trend_hit_era"] = {e_: {"n": len(v), "hit": round(sum(v) / len(v), 3)} for e_, v in by_era2.items()}
# mech baseline era
by_era3 = collections.defaultdict(list)
for r in reg:
    m = mech_label(r["symbol"], r["timestamp"])
    fr = fwd_ret(r["symbol"], r["timestamp"], 4)
    if fr is None or m not in ("trending_bull", "trending_bear"): continue
    by_era3[era(r["timestamp"])].append((fr > 0) == (m == "trending_bull"))
ext["mech_trend_hit_era"] = {e_: {"n": len(v), "hit": round(sum(v) / len(v), 3)} for e_, v in by_era3.items()}

# fragility: trade go 24h wk1 minus single best observation
wk1_24 = [(1 if s == "LONG" else -1) * fr for r, s in go_sided
          if s and era(r["timestamp"]) == "wk1" and (fr := fwd_ret(r["symbol"], r["timestamp"], 24)) is not None]
if wk1_24:
    srt = sorted(wk1_24)
    ext["trade_wk1_24h_fragility"] = {"full_mean_bps": round(statistics.mean(srt) * 1e4, 1),
                                      "drop_best_mean_bps": round(statistics.mean(srt[:-1]) * 1e4, 1),
                                      "drop_best3_mean_bps": round(statistics.mean(srt[:-3]) * 1e4, 1)}
# skips cf era split
by_era4 = collections.defaultdict(list)
for r, c in mm:
    by_era4[era(r["timestamp"])].append(c["hypothetical_pnl_pct"])
ext["trade_skips_cf_era"] = {e_: {"n": len(v), "mean_hypo_pnl_pct": round(statistics.mean(v), 4),
                                  "would_wr": round(sum(1 for y in v if y > 0) / len(v), 3)} for e_, v in by_era4.items()}
# model mix per role
mm2 = collections.defaultdict(collections.Counter)
for r in recs: mm2[r["agent_role"]][r["model_used"]] += 1
ext["model_mix"] = {k: dict(v) for k, v in mm2.items()}
ext["bad_cf_lines_skipped"] = _bad_cf
out["extras"] = ext

print(json.dumps(out, indent=1, default=str))
