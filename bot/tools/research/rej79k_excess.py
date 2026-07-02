"""Beta-adjusted pass: per-gate mean EXCESS 24h return vs (era,side,symbol) baseline.
Also: confidence-gradient among rejected episodes (calibration check)."""
import json, re, collections, datetime as dt, os, statistics

HERE = os.path.dirname(__file__)
REJ = r"C:\Users\vince\WAGMI\bot\data\manual\sniper_rejections.jsonl"
CANDLES = json.load(open(os.path.join(HERE, "rej79k_candles.json")))
H = 3600_000
opens = {s: {row[0]: row[1] for row in rows} for s, rows in CANDLES.items()}

def gate_family(r):
    for pat, fam in [(r"^low_confidence_","low_confidence"),(r"^quality_floor_proven_solo_","quality_floor_proven_solo"),
        (r"^quality_floor_conf_","quality_floor_conf"),(r"^scorecard_.*_min40$","scorecard_min40"),
        (r"^dangerous_regime_high_volatility_","dangerous_regime_highvol"),(r"^low_win_prob_","low_win_prob"),
        (r"^rsi_overbought_","rsi_overbought"),(r"^low_rr_","low_rr"),(r"^low_consensus_","low_consensus")]:
        if re.match(pat, r): return fam
    return r

def era_of(d):
    if d <= "2026-06-05": return "W1"
    if d <= "2026-06-25": return "MID"
    return "LATE"

episodes = {}
for line in open(REJ, encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try: r = json.loads(line)
    except Exception: continue
    if r["symbol"] not in opens: continue
    ts = dt.datetime.fromisoformat(r["timestamp"])
    t0 = (int(ts.timestamp()*1000)//H + 1) * H
    fam = gate_family(r["reason"])
    key = (fam, r["symbol"], r["side"], t0)
    if key not in episodes or r["confidence"] > episodes[key][0]:
        episodes[key] = (r["confidence"], r["timestamp"][:10])

rows = []
for (fam, sym, side, t0), (conf, d) in episodes.items():
    e = opens[sym].get(t0); x = opens[sym].get(t0 + 24*H)
    if e is None or x is None: continue
    sgn = 1.0 if side == "BUY" else -1.0
    rows.append({"fam": fam, "sym": sym, "side": side, "era": era_of(d),
                 "conf": conf, "ret": sgn*(x-e)/e*1e4})

# baseline: mean over ALL episodes per (era, side, sym)
cell = collections.defaultdict(list)
for r in rows: cell[(r["era"], r["side"], r["sym"])].append(r["ret"])
base = {k: statistics.mean(v) for k, v in cell.items()}
for r in rows: r["ex"] = r["ret"] - base[(r["era"], r["side"], r["sym"])]

print("=== PER-GATE EXCESS vs (era,side,symbol) baseline, 24h ===")
fams = collections.Counter(r["fam"] for r in rows)
for f, n in fams.most_common():
    sel = [r for r in rows if r["fam"] == f]
    ex = [r["ex"] for r in sel]
    exw1 = [r["ex"] for r in sel if r["era"] == "W1"]
    exmid = [r["ex"] for r in sel if r["era"] == "MID"]
    exlate = [r["ex"] for r in sel if r["era"] == "LATE"]
    def m(v): return "%+.0f(n=%d)" % (statistics.mean(v), len(v)) if v else "--"
    print("%-28s allex=%s  W1=%s MID=%s LATE=%s" % (f, m(ex), m(exw1), m(exmid), m(exlate)))

print()
print("=== CONFIDENCE GRADIENT (all rejected episodes, excess 24h by conf band) ===")
bands = [(0,40),(40,50),(50,60),(60,70),(70,80),(80,101)]
for lo, hi in bands:
    v = [r["ex"] for r in rows if lo <= r["conf"] < hi]
    raw = [r["ret"] for r in rows if lo <= r["conf"] < hi]
    if v:
        print("conf %2d-%-3d n=%4d  raw=%+.0fbps  excess=%+.0fbps  wr=%.0f%%" % (
            lo, hi, len(v), statistics.mean(raw), statistics.mean(v),
            100*sum(1 for x in raw if x>0)/len(raw)))
print()
print("=== quality_floor_conf detail (the one EV candidate) ===")
qc = [r for r in rows if r["fam"] == "quality_floor_conf"]
for era in ["W1","MID","LATE"]:
    for sym in ["BTC","ETH","SOL","HYPE","XRP"]:
        v = [r for r in qc if r["era"]==era and r["sym"]==sym]
        if v:
            print("  %-4s %-4s n=%2d raw=%+.0f excess=%+.0f" % (era, sym, len(v),
                statistics.mean([x["ret"] for x in v]), statistics.mean([x["ex"] for x in v])))
