"""RQ15: Thesis language forensics.

Regrades thesis_history.jsonl per-thesis (same methodology as
coordination/THESIS_GRADES_2026-07-01.md: text-derived direction/symbol,
HL 1h candles, +/-0.3% band at +6/12/24h), then compares linguistic /
structural features of graded-RIGHT vs graded-WRONG theses.

Read-only on bot data. Writes only a cache json next to this script.
"""
import json, re, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\vince\WAGMI")
HIST = ROOT / "bot/data/llm/thesis_history.jsonl"
CACHE = Path(__file__).with_name("rq15_candle_cache.json")
SYMS = ["BTC", "ETH", "SOL", "HYPE"]
BAND = 0.003

# ---------- candles ----------
def fetch_hl(coin, start_ms, end_ms):
    body = json.dumps({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "1h", "startTime": start_ms, "endTime": end_ms}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def load_candles():
    if CACHE.exists():
        return {k: {int(t): v for t, v in d.items()} for k, d in json.loads(CACHE.read_text()).items()}
    start = int(datetime(2026, 5, 29, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(time.time() * 1000)
    out = {}
    for s in SYMS:
        rows = fetch_hl(s, start, end)
        out[s] = {int(r["t"]): float(r["c"]) for r in rows}
        print(f"{s}: {len(rows)} candles", file=sys.stderr)
        time.sleep(0.4)
    CACHE.write_text(json.dumps({k: {str(t): v for t, v in d.items()} for k, d in out.items()}))
    return out

def close_at(candles, sym, ts_ms):
    """Close of the 1h candle containing ts_ms (candle t = open time)."""
    key = ts_ms - (ts_ms % 3600000)
    return candles[sym].get(key)

# ---------- direction / symbol from text (same precedence as grades pass) ----------
BEAR_WORDS = r"(short|sell|decline|breakdown|break(?:ing|s)? (?:below|down)|lower|downtrend|bearish|down toward|resolve[sd]? downward|dead-cat|fade the bounce|resumes? downtrend|sellers in control|drops?|falls?)"
BULL_WORDS = r"(long\b|buy\b|breakout above|break(?:ing|s)? (?:above|out)|higher|uptrend|bullish|up toward|holds? support|targeting \$?\d+.*(?:above)|rall(?:y|ies)|bounce[s]? to(?:ward)?|recover|climbs?|rises?)"

def derive_dir(text):
    t = text.lower()
    if re.search(r"\bshort\b|\bsell\b", t):
        return "SHORT"
    if re.search(r"\blong\b|\bbuy\b", t):
        return "LONG"
    if re.search(BEAR_WORDS, t):
        return "SHORT"
    if re.search(BULL_WORDS, t):
        return "LONG"
    return None

def derive_sym(text, rec_sym):
    hits = [(text.find(s), s) for s in SYMS if re.search(rf"\b{s}\b", text)]
    if hits:
        return sorted(hits)[0][1]  # first-mentioned = subject
    return rec_sym if rec_sym in SYMS else None

# ---------- linguistic features ----------
def features(text):
    t = text
    tl = text.lower()
    f = {}
    # names a specific price level (target/level with a number)
    f["specific_level"] = bool(re.search(r"(?:to|toward|target(?:ing)?|at|near|~|\$)\s*~?\$?\d[\d,\.]*", tl))
    # states an invalidation / stop condition
    f["invalidation"] = bool(re.search(r"\b(invalid\w*|stop(?:s|ped)?\b|unless|negate[sd]?|abort|reclaim\w* would|above [\d\$][\d,\.]* (?:kills|negates|invalidates)|fails? (?:to hold|above|below))", tl))
    # cites a timeframe / horizon
    f["timeframe"] = bool(re.search(r"\bwithin\s+\d|\b\d+\s*-\s*\d+\s*h\b|\b\d+\s*h(?:ours?)?\b|\bmin\b|\bintraday\b|\bsession\b", tl))
    # cites Quant-Brain style stats (WR / n= / EV / PF / validated edge)
    f["qb_stats"] = bool(re.search(r"\bwr\b|\bn\s*=\s*\d|\bev\b|\bpf\s*[\d=]|win rate|validated|\d+\s*%\s*wr|\bhot\b.*100%|100%\s*wr", tl))
    # hedging language
    f["hedging"] = bool(re.search(r"\b(may|might|could|possibly|potential(?:ly)?|likely|appears?|seems?|expected to|should)\b", tl))
    # conditional phrasing (if/unless/once/as-long-as) vs flat directional assertion
    f["conditional"] = bool(re.search(r"\b(if|unless|once|as long as|provided|assuming|contingent)\b", tl))
    # mechanism citations seen in best-10 pattern
    f["adx"] = bool(re.search(r"\badx\b", tl))
    f["cross_asset"] = len({s for s in SYMS if re.search(rf"\b{s}\b", t)}) >= 2 or "lead-lag" in tl or "lead lag" in tl
    f["regime_word"] = bool(re.search(r"regime|trending_(bear|bull)|consolidation|high_vol|range\b", tl))
    f["n_words"] = len(t.split())
    return f

# ---------- main ----------
def main():
    candles = load_candles()
    now_ms = int(time.time() * 1000)
    recs = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"total records: {len(recs)}", file=sys.stderr)

    graded = []
    skipped = defaultdict(int)
    for r in recs:
        text = (r.get("thesis") or "").strip()
        d = derive_dir(text)
        if not d:
            skipped["no_direction"] += 1
            continue
        sym = derive_sym(text, r.get("symbol") or "")
        if not sym:
            skipped["no_symbol"] += 1
            continue
        ts = int(datetime.fromisoformat(r["created_at"]).timestamp() * 1000)
        if ts + 24 * 3600000 > now_ms:
            skipped["too_recent_24h"] += 1
            continue
        p0 = close_at(candles, sym, ts)
        if p0 is None:
            skipped["no_candle"] += 1
            continue
        ep = r.get("entry_price") or 0
        entry = ep if ep and abs(ep - p0) / p0 <= 0.03 else p0  # symbol-bug fix
        row = {"text": text, "sym": sym, "dir": d, "ts": ts, "conf": r.get("confidence"),
               "created": r["created_at"][:16]}
        sign = -1 if d == "SHORT" else 1
        for h in (6, 12, 24):
            ph = close_at(candles, sym, ts + h * 3600000)
            if ph is None:
                row[f"g{h}"] = None
                continue
            ret = sign * (ph - entry) / entry
            row[f"ret{h}"] = ret
            row[f"g{h}"] = "R" if ret >= BAND else ("W" if ret <= -BAND else "F")
        row.update(features(text))
        graded.append(row)

    # dedupe by normalized text (keep first occurrence)
    seen, dd = set(), []
    for r in graded:
        k = re.sub(r"\s+", " ", r["text"].lower())
        if k in seen:
            continue
        seen.add(k)
        dd.append(r)

    print(f"graded: {len(graded)}, deduped: {len(dd)}, skipped: {dict(skipped)}", file=sys.stderr)

    FEATS = ["specific_level", "invalidation", "timeframe", "qb_stats", "hedging",
             "conditional", "adx", "cross_asset", "regime_word"]

    def bucket_stats(rows, horizon, label):
        R = [r for r in rows if r.get(f"g{horizon}") == "R"]
        W = [r for r in rows if r.get(f"g{horizon}") == "W"]
        print(f"\n=== {label} +{horizon}h: RIGHT n={len(R)}, WRONG n={len(W)} (flat excluded) ===")
        print(f"{'feature':<15} {'%R':>6} {'%W':>6} {'winWith':>12} {'winWithout':>12}")
        for f in FEATS:
            pr = sum(r[f] for r in R)
            pw = sum(r[f] for r in W)
            withf = [r for r in R + W if r[f]]
            wof = [r for r in R + W if not r[f]]
            ww = f"{sum(1 for r in withf if r[f'g{horizon}']=='R')}/{len(withf)}" if withf else "0/0"
            wwo = f"{sum(1 for r in wof if r[f'g{horizon}']=='R')}/{len(wof)}" if wof else "0/0"
            print(f"{f:<15} {pr/max(len(R),1)*100:>5.0f}% {pw/max(len(W),1)*100:>5.0f}% {ww:>12} {wwo:>12}")
        # length
        import statistics as st
        if R and W:
            print(f"words: RIGHT med={st.median(r['n_words'] for r in R):.0f} "
                  f"WRONG med={st.median(r['n_words'] for r in W):.0f}")
        # avg signed ret with/without each feature
        print(f"{'feature':<15} {'avgRet with':>12} {'avgRet w/o':>12}")
        allg = [r for r in rows if r.get(f"ret{horizon}") is not None]
        for f in FEATS:
            a = [r[f"ret{horizon}"] for r in allg if r[f]]
            b = [r[f"ret{horizon}"] for r in allg if not r[f]]
            am = sum(a) / len(a) * 100 if a else float("nan")
            bm = sum(b) / len(b) * 100 if b else float("nan")
            print(f"{f:<15} {am:>10.2f}%(n={len(a)}) {bm:>9.2f}%(n={len(b)})")

    bucket_stats(dd, 24, "DEDUPED")
    bucket_stats(dd, 12, "DEDUPED")

    # era split
    era1 = [r for r in dd if r["created"] <= "2026-06-06T23"]
    era2 = [r for r in dd if r["created"] > "2026-06-06T23"]
    bucket_stats(era1, 24, "ERA1 May31-Jun06")
    bucket_stats(era2, 24, "ERA2 Jun07+")

    # fragility: for each feature, winrate-with after dropping single best ret24 observation
    print("\n=== FRAGILITY (+24h, deduped): drop best single obs from 'with-feature' set ===")
    for f in FEATS:
        withf = [r for r in dd if r[f] and r.get("ret24") is not None and r.get("g24") in ("R", "W")]
        if len(withf) < 2:
            continue
        withf.sort(key=lambda r: r["ret24"], reverse=True)
        full = sum(1 for r in withf if r["g24"] == "R") / len(withf)
        drop = withf[1:]
        fr = sum(1 for r in drop if r["g24"] == "R") / len(drop)
        print(f"{f:<15} win {full*100:.0f}% (n={len(withf)}) -> drop-best {fr*100:.0f}% (n={len(drop)})")

    # hedging intensity / conditional cross-tab
    print("\n=== phrasing style cross-tab (+24h deduped, ex-flat) ===")
    for name, pred in [("assertive+level", lambda r: r["specific_level"] and not r["hedging"]),
                       ("hedged+level", lambda r: r["specific_level"] and r["hedging"]),
                       ("no-level", lambda r: not r["specific_level"])]:
        g = [r for r in dd if pred(r) and r.get("g24") in ("R", "W")]
        if g:
            w = sum(1 for r in g if r["g24"] == "R")
            avg = sum(r["ret24"] for r in g) / len(g) * 100
            print(f"{name:<16} {w}/{len(g)} = {w/len(g)*100:.0f}%  avg24 {avg:+.2f}%")

    # dump per-thesis for inspection
    out = Path(__file__).with_name("rq15_graded.json")
    out.write_text(json.dumps(dd, indent=1, default=str))
    print(f"\nwrote {out}", file=sys.stderr)

if __name__ == "__main__":
    main()
