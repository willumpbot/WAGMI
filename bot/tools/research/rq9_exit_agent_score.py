# RQ9: Score the LLM exit agent's calls (close/partial/tighten) against price truth.
# NULL baseline = pure mechanical geometry (existing SL/TP2 simulated forward on HL 15m candles).
# Read-only on bot code; writes only rq9_* artifacts in this directory.
import json, os, re, csv, time, urllib.request
from datetime import datetime, timezone
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # bot/
DEC = os.path.join(ROOT, "data", "logs", "exit_decisions.jsonl")
LEDGER = os.path.join(ROOT, "data", "trade_ledger.csv")
CACHE = os.path.join(HERE, "rq9_candles_15m.json")
OUT = os.path.join(HERE, "rq9_results.json")

SYMS = ["BTC", "ETH", "SOL", "XRP", "HYPE"]
START_MS = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)

def fetch_candles():
    if os.path.exists(CACHE):
        d = json.load(open(CACHE))
        # refresh if stale > 6h vs now
        newest = max(c[0] for c in d["BTC"])
        if time.time() * 1000 - newest < 6 * 3600 * 1000:
            return d
    out = {}
    end = int(time.time() * 1000)
    for s in SYMS:
        req = json.dumps({"type": "candleSnapshot", "req": {"coin": s, "interval": "15m",
                          "startTime": START_MS, "endTime": end}}).encode()
        r = urllib.request.Request("https://api.hyperliquid.xyz/info", data=req,
                                   headers={"Content-Type": "application/json"})
        rows = json.loads(urllib.request.urlopen(r, timeout=30).read())
        out[s] = [[int(c["t"]), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])] for c in rows]
        print(s, len(out[s]), "candles",
              datetime.fromtimestamp(out[s][0][0]/1000, tz=timezone.utc),
              "->", datetime.fromtimestamp(out[s][-1][0]/1000, tz=timezone.utc))
        time.sleep(0.3)
    json.dump(out, open(CACHE, "w"))
    return out

CANDLES = fetch_candles()
IDX = {s: {c[0]: i for i, c in enumerate(CANDLES[s])} for s in SYMS}

def candle_at(sym, ts_ms):
    """index of candle containing ts_ms, or None"""
    base = ts_ms - ts_ms % (15 * 60 * 1000)
    return IDX[sym].get(base)

def px_at(sym, ts_ms):
    i = candle_at(sym, ts_ms)
    return CANDLES[sym][i][4] if i is not None else None

def sim_mech(sym, ts_ms, direction, sl, tp2, horizon_h):
    """Simulate mechanical exit (SL / TP2) from ts_ms for horizon_h hours.
    Conservative: if SL and TP2 touch in the same candle, SL fills first.
    Returns (exit_px, kind, resolved) where kind in SL/TP2/EOH; resolved False if data ran out."""
    i0 = candle_at(sym, ts_ms)
    if i0 is None:
        return None, None, False
    n = int(horizon_h * 4)
    arr = CANDLES[sym]
    for i in range(i0 + 1, min(i0 + 1 + n, len(arr))):
        t, o, h, l, c = arr[i]
        if direction > 0:  # LONG
            if sl and l <= sl:
                return sl, "SL", True
            if tp2 and h >= tp2:
                return tp2, "TP2", True
        else:  # SHORT
            if sl and h >= sl:
                return sl, "SL", True
            if tp2 and l <= tp2:
                return tp2, "TP2", True
    last = min(i0 + n, len(arr) - 1)
    resolved = (i0 + n) <= len(arr) - 1
    return arr[last][4], "EOH", resolved

# --- load decisions ---
recs = [json.loads(l) for l in open(DEC, encoding="utf-8")]
llm = [r for r in recs if (r.get("reason") or "").startswith("[LLM-EXIT]")]
mech_tight = [r for r in recs if not (r.get("reason") or "").startswith("[LLM-EXIT]")]

# --- ledger join for qty (dollar estimates) ---
ledger = list(csv.DictReader(open(LEDGER, encoding="utf-8")))
def find_qty(sym, entry, side):
    best = None
    for row in ledger:
        if row["symbol"] != sym or row["side"] != side:
            continue
        try:
            ep = float(row["entry_price"]); xp = float(row["exit_price"]); g = float(row["gross_pnl"])
        except (ValueError, KeyError):
            continue
        if entry and abs(ep - entry) / entry < 1e-4 and xp != ep:
            d = 1 if side == "LONG" else -1
            q = g / ((xp - ep) * d)
            if q > 0:
                best = q
    return best

def era(ts):
    d = ts[:10]
    if d <= "2026-06-10":
        return "E1_jun01-10"
    if d <= "2026-06-22":
        return "E2_jun16-22"
    return "E3_jun23-jul02"

def reason_bucket(reason):
    r = (reason or "").lower()
    for pat, name in [
        (r"regime (mismatch|incompat|failure|invalid|conflict|shift)|ranging market|range regime|toxic|no-trade zone", "regime_mismatch"),
        (r"thesis invalid|invalidated", "thesis_invalidated"),
        (r"no progress|zero progress|stall|hold \d|h hold|hours? at", "time_stop"),
        (r"wr[ =]|historical|lifetime|hard-block|validated (loss|conf)|n=\d", "historical_stats"),
        (r"mfe|retrace|profit-lock|peak", "mfe_protect"),
        (r"funding|oi |open interest", "funding_oi"),
        (r"panic", "panic_regime"),
    ]:
        if re.search(pat, r):
            return name
    return "other"

results = []
for r in llm:
    ts = datetime.fromisoformat(r["ts"]).timestamp() * 1000
    sym, side = r["symbol"], r["position_side"]
    d = 1 if side == "LONG" else -1
    p0 = px_at(sym, int(ts))
    if p0 is None:
        continue
    entry = r.get("position_entry")
    sl, tp2 = r.get("position_sl"), r.get("position_tp2")
    row = {"ts": r["ts"], "era": era(r["ts"]), "symbol": sym, "side": side,
           "action": r["exit_action"], "applied": r["applied"], "p0": p0,
           "entry": entry, "bucket": reason_bucket(r.get("reason")),
           "conf": r.get("exit_confidence"),
           "pos_key": f"{sym}|{side}|{entry}"}
    qty = find_qty(sym, entry, side)
    row["qty"] = qty
    if r["exit_action"] in ("close", "partial"):
        # NULL baseline: hold under mechanical SL/TP2 management
        for h in (6, 12, 24):
            ep, kind, ok = sim_mech(sym, int(ts), d, sl, tp2, h)
            hold_pct = d * (ep - p0) / p0 * 100 if ep else None
            row[f"hold_{h}h_pct"] = round(hold_pct, 4) if hold_pct is not None else None
            row[f"hold_{h}h_kind"] = kind
            row[f"resolved_{h}h"] = ok
        frac = 1.0
        if r["exit_action"] == "partial":
            m = re.search(r"Partial (\d+)%", r.get("details") or "")
            frac = int(m.group(1)) / 100 if m else 0.5
        row["frac"] = frac
        # value of the CLOSE decision vs null, per horizon (positive = close beat holding)
        for h in (6, 12, 24):
            hp = row[f"hold_{h}h_pct"]
            row[f"close_value_{h}h_pct"] = round(-frac * hp, 4) if hp is not None else None
    elif r["exit_action"] == "tighten_sl":
        m = re.search(r"SL ([\d.]+) -> ([\d.]+)", r.get("details") or "")
        if not m:
            continue
        old_sl, new_sl = float(m.group(1)), float(m.group(2))
        row["old_sl"], row["new_sl"] = old_sl, new_sl
        exA, kA, okA = sim_mech(sym, int(ts), d, new_sl, tp2, 48)
        exB, kB, okB = sim_mech(sym, int(ts), d, old_sl, tp2, 48)
        row["new_exit_kind"], row["old_exit_kind"] = kA, kB
        row["resolved_48h"] = okA and okB
        row["tighten_value_pct"] = round(d * (exA - exB) / p0 * 100, 4)
        if kA == "SL" and kB != "SL":
            # tightened stop tagged where old survived: premature if old path ended better
            row["tighten_class"] = "premature" if d * (exB - exA) > 0 else "protective"
        elif kA == "SL" and kB == "SL":
            row["tighten_class"] = "protective" if d * (exA - exB) > 0 else ("premature" if d * (exA - exB) < 0 else "wash")
        else:
            row["tighten_class"] = "wash"
    results.append(row)

json.dump(results, open(OUT, "w"), indent=1)

# ---------- aggregate ----------
def agg(rows, label, dollars=True):
    n = len(rows)
    if n == 0:
        print(f"{label}: n=0")
        return
    out = {"n": n}
    for h in (6, 12, 24):
        vals = [x[f"close_value_{h}h_pct"] for x in rows if x.get(f"close_value_{h}h_pct") is not None]
        if not vals:
            continue
        wins = sum(1 for v in vals if v > 0)
        out[f"{h}h"] = f"correct {wins}/{len(vals)} ({wins/len(vals)*100:.0f}%), mean {sum(vals)/len(vals):+.3f}%, median {sorted(vals)[len(vals)//2]:+.3f}%"
        if dollars:
            dv = [v/100 * x["qty"] * x["p0"] for v, x in
                  [(x[f"close_value_{h}h_pct"], x) for x in rows if x.get(f"close_value_{h}h_pct") is not None and x.get("qty")]]
            if dv:
                out[f"{h}h_$"] = f"n={len(dv)} sum {sum(dv):+.2f}$ mean {sum(dv)/len(dv):+.2f}$"
    print(label, json.dumps(out, indent=1))

def dedupe_first(rows):
    seen, out = set(), []
    for x in sorted(rows, key=lambda z: z["ts"]):
        k = (x["pos_key"], x["action"])
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

closes = [x for x in results if x["action"] == "close"]
partials = [x for x in results if x["action"] == "partial"]
tightens = [x for x in results if x["action"] == "tighten_sl"]

print("\n======== CLOSE decisions (per-call) ========")
for ap in (True, False):
    sub = [x for x in closes if x["applied"] == ap]
    agg(sub, f"close applied={ap} ALL")
    for e in ("E1_jun01-10", "E2_jun16-22", "E3_jun23-jul02"):
        agg([x for x in sub if x["era"] == e], f"  {e}")

print("\n======== CLOSE decisions (per-position first-call) ========")
for ap in (True, False):
    sub = dedupe_first([x for x in closes if x["applied"] == ap])
    agg(sub, f"close applied={ap} EPISODES")
    for e in ("E1_jun01-10", "E2_jun16-22", "E3_jun23-jul02"):
        agg([x for x in sub if x["era"] == e], f"  {e}")

print("\n======== CLOSE by reason bucket (episodes, all applied+blocked) ========")
epi = dedupe_first(closes)
for b in sorted(set(x["bucket"] for x in epi)):
    agg([x for x in epi if x["bucket"] == b], f"bucket={b}")

print("\n======== CLOSE by winner/loser at decision time (episodes) ========")
for lab, cond in [("in_profit", lambda x: x["entry"] and (x["p0"] - x["entry"]) * (1 if x["side"] == "LONG" else -1) > 0),
                  ("in_loss", lambda x: x["entry"] and (x["p0"] - x["entry"]) * (1 if x["side"] == "LONG" else -1) <= 0)]:
    agg([x for x in epi if cond(x)], lab)

print("\n======== PARTIAL decisions ========")
agg(partials, "partial ALL (frac-weighted)")
agg([x for x in partials if x["applied"]], "partial applied")
agg([x for x in partials if not x["applied"]], "partial blocked")
agg(dedupe_first(partials), "partial EPISODES")

print("\n======== TIGHTEN_SL decisions ========")
tt = [x for x in tightens if "tighten_class" in x]
print("n =", len(tt), Counter(x["tighten_class"] for x in tt))
print("applied:", Counter(x["tighten_class"] for x in tt if x["applied"]))
vals = [x["tighten_value_pct"] for x in tt if x["applied"]]
if vals:
    print(f"applied tighten value vs old-SL null: mean {sum(vals)/len(vals):+.3f}% median {sorted(vals)[len(vals)//2]:+.3f}% "
          f"pos {sum(1 for v in vals if v>0)} neg {sum(1 for v in vals if v<0)} zero {sum(1 for v in vals if v==0)}")
    dv = [x["tighten_value_pct"]/100 * x["qty"] * x["p0"] for x in tt if x["applied"] and x.get("qty")]
    if dv:
        print(f"dollar est (n={len(dv)}): sum {sum(dv):+.2f}$")
for e in ("E1_jun01-10", "E2_jun16-22", "E3_jun23-jul02"):
    sub = [x for x in tt if x["era"] == e and x["applied"]]
    v = [x["tighten_value_pct"] for x in sub]
    if v:
        print(f"  {e}: n={len(v)} mean {sum(v)/len(v):+.3f}% classes {Counter(x['tighten_class'] for x in sub)}")
ep_t = dedupe_first(tt)
print("episodes:", len(ep_t), Counter(x["tighten_class"] for x in ep_t))
vv = [x["tighten_value_pct"] for x in ep_t]
if vv:
    print(f"episode value: mean {sum(vv)/len(vv):+.3f}% median {sorted(vv)[len(vv)//2]:+.3f}%")

print("\n======== unresolved horizon counts (data ran out) ========")
print("close 24h unresolved:", sum(1 for x in closes if x.get("resolved_24h") is False))
print("tighten 48h unresolved:", sum(1 for x in tightens if x.get("resolved_48h") is False))
print("qty matched:", sum(1 for x in results if x.get("qty")), "/", len(results))
