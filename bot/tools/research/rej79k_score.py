"""Per-gate counterfactual EV audit of sniper_rejections.jsonl (79,855 records).

Method (honest limits):
- Records carry NO entry/SL/TP and NO outcome. We forward-score fixed horizons
  (1h/4h/24h) against HL 1h candles: entry = open of the first full hourly
  candle AFTER the rejection timestamp; exit = open of the candle k hours later.
  Signed by side. Gross of fees (HL taker round trip ~9 bps).
- Records are massively autocorrelated (same signal re-rejected every loop).
  Primary denominator = EPISODES: unique (gate_family, symbol, side, entry_hour).
  Record counts reported alongside.
- Era split: W1 = 2026-05-30..06-05 (crash week), MID = 06-06..06-25,
  LATE = 06-26..07-02. Bot dark 06-10..06-16.
- Baseline per era/side = mean signed return over ALL episodes in that era/side
  (separates market beta from gate-specific selection).
Output: JSON + text tables.
"""
import json, re, collections, datetime as dt, os, statistics

HERE = os.path.dirname(__file__)
REJ = r"C:\Users\vince\WAGMI\bot\data\manual\sniper_rejections.jsonl"
CANDLES = json.load(open(os.path.join(HERE, "rej79k_candles.json")))

H = 3600_000
# candle open lookup: sym -> {t_ms: open}
opens = {s: {row[0]: row[1] for row in rows} for s, rows in CANDLES.items()}

def gate_family(reason):
    r = reason
    for pat, fam in [
        (r"^low_confidence_", "low_confidence"),
        (r"^quality_floor_proven_solo_", "quality_floor_proven_solo"),
        (r"^quality_floor_conf_", "quality_floor_conf"),
        (r"^scorecard_.*_min40$", "scorecard_min40"),
        (r"^dangerous_regime_high_volatility_", "dangerous_regime_highvol"),
        (r"^dangerous_regime_panic_", "dangerous_regime_panic"),
        (r"^low_win_prob_", "low_win_prob"),
        (r"^rsi_overbought_", "rsi_overbought"),
        (r"^rsi_oversold_", "rsi_oversold"),
        (r"^low_rr_", "low_rr"),
        (r"^chop_too_high_", "chop_too_high"),
        (r"^setup_low_conf_", "setup_low_conf"),
        (r"^already_dipped_", "already_dipped"),
        (r"^low_consensus_", "low_consensus"),
    ]:
        if re.match(pat, r):
            return fam
    return r  # dedup, symbol_cooldown, daily_limit, aggressive_standard_skip, zero_risk, weak_regime_unknown

def era_of(d):  # d = date string YYYY-MM-DD
    if d <= "2026-06-05": return "W1"
    if d <= "2026-06-25": return "MID"
    return "LATE"

HORIZONS = [1, 4, 24]

# episodes: key -> record (keep max confidence among dupes)
episodes = {}
n_rec = collections.Counter()   # per gate, raw record count
bad = 0
for line in open(REJ, encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try: r = json.loads(line)
    except Exception: bad += 1; continue
    sym = r["symbol"]
    if sym not in opens: continue  # DOGE n=7, unscored
    ts = dt.datetime.fromisoformat(r["timestamp"])
    t0 = (int(ts.timestamp() * 1000) // H + 1) * H  # next hour boundary = entry
    fam = gate_family(r["reason"])
    n_rec[fam] += 1
    key = (fam, sym, r["side"], t0)
    if key not in episodes or r["confidence"] > episodes[key]["confidence"]:
        episodes[key] = {"confidence": r["confidence"], "regime": r["regime"],
                         "date": r["timestamp"][:10]}

# score episodes
rows = []
unscored = 0
for (fam, sym, side, t0), meta in episodes.items():
    e = opens[sym].get(t0)
    if e is None: unscored += 1; continue
    sgn = 1.0 if side == "BUY" else -1.0
    rets = {}
    for k in HORIZONS:
        x = opens[sym].get(t0 + k * H)
        rets[k] = None if x is None else sgn * (x - e) / e * 1e4  # bps
    rows.append({"fam": fam, "sym": sym, "side": side, "era": era_of(meta["date"]),
                 "conf": meta["confidence"], "rets": rets})

def agg(rs, k):
    v = [r["rets"][k] for r in rs if r["rets"][k] is not None]
    if not v: return None
    wins = sum(1 for x in v if x > 0)
    m = statistics.mean(v)
    med = statistics.median(v)
    # fragility: drop single best
    m_drop = statistics.mean(sorted(v)[:-1]) if len(v) > 1 else None
    return {"n": len(v), "wr": wins / len(v), "mean_bps": m, "med_bps": med,
            "mean_drop_best": m_drop}

# baseline per era/side at 24h
def fmt(a):
    if a is None: return "n=0"
    return "n=%d wr=%.0f%% mean=%+.0fbps med=%+.0fbps dropbest=%+.0fbps" % (
        a["n"], a["wr"] * 100, a["mean_bps"], a["med_bps"],
        a["mean_drop_best"] if a["mean_drop_best"] is not None else float("nan"))

out = {"unscored_episodes": unscored, "bad_lines": bad}
fams = sorted(set(r["fam"] for r in rows), key=lambda f: -n_rec[f])
print("EPISODES total:", len(rows), "unscored:", unscored)
print()
print("=== BASELINE (all rejection episodes, by era & side, 24h) ===")
for era in ["W1", "MID", "LATE"]:
    for side in ["BUY", "SELL"]:
        sel = [r for r in rows if r["era"] == era and r["side"] == side]
        print("  %-4s %-4s %s" % (era, side, fmt(agg(sel, 24))))
print()
print("=== PER-GATE TABLE (episodes; 4h and 24h; era-split) ===")
for f in fams:
    sel = [r for r in rows if r["fam"] == f]
    print("%s  records=%d episodes=%d" % (f, n_rec[f], len(sel)))
    print("   ALL   4h: %s" % fmt(agg(sel, 4)))
    print("   ALL  24h: %s" % fmt(agg(sel, 24)))
    for era in ["W1", "MID", "LATE"]:
        es = [r for r in sel if r["era"] == era]
        if es:
            print("   %-4s 24h: %s" % (era, fmt(agg(es, 24))))
    for side in ["BUY", "SELL"]:
        ss = [r for r in sel if r["side"] == side]
        if ss:
            print("   %-4s 24h: %s" % (side, fmt(agg(ss, 24))))
    out[f] = {"records": n_rec[f], "episodes": len(sel),
              "all_4h": agg(sel, 4), "all_24h": agg(sel, 24),
              "era_24h": {era: agg([r for r in sel if r["era"] == era], 24) for era in ["W1","MID","LATE"]},
              "side_24h": {s: agg([r for r in sel if r["side"] == s], 24) for s in ["BUY","SELL"]}}
    print()

json.dump(out, open(os.path.join(HERE, "rej79k_results.json"), "w"), indent=1)
print("saved rej79k_results.json")
