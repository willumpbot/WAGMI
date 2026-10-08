"""Farming called memes: what does a mechanical exit actually capture?

The owner does not find contract addresses -- calls arrive from Telegram groups,
and Rick bot reports those groups as profitable "in terms of peak and median".

Peak is not capturable. The question that decides whether calls are farmable is:
**given a call, what does a MECHANICAL exit rule realise?** This measures that gap
on real DEX price history, so the answer does not depend on anyone's claims.

Method: for each sampled token, treat an early day in its history as "the call",
then walk forward measuring
  * peak multiple reached (what Rick bot would quote)
  * what each mechanical exit rule actually captures
  * buy-and-hold, for contrast
Medians AND means are reported, because meme outcomes are violently skewed and
the mean is driven by a handful of survivors.

SURVIVORSHIP, stated loudly: tokens are sampled from GeckoTerminal's CURRENT
listings. Tokens that died hard enough to be delisted are absent, and they are
the worst ones. **Every number here is therefore optimistic.** The gap between
peak and realised is the finding; the absolute levels are an upper bound.
"""
import json, io, os, math, time, urllib.request, collections
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GT = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "wagmi-research/1.0"}
NETWORKS = ["solana", "base", "eth", "bsc"]
PAGES = tuple(range(1, 11))   # 10 pages x 4 networks; default listing skews brand-new
CALL_DAY = 3            # the "call" lands on day 3 of available history
MIN_DAYS = 14           # 2 weeks is enough to see peak vs end; 20 left only 26 tokens
HORIZON = 30


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as e:
            if k == tries - 1:
                return {"__err__": str(e)}
            time.sleep(1.2 * (k + 1))
    return {"__err__": "unreachable"}


pools, seen = [], set()
for net in NETWORKS:
    for pg in PAGES:
        d = get(f"{GT}/networks/{net}/pools?page={pg}"
                + ("&sort=h24_volume_usd_desc" if pg % 2 == 0 else ""))
        if "__err__" in d:
            continue
        for p in (d.get("data") or []):
            a = p.get("attributes") or {}
            ad = a.get("address")
            if not ad or ad in seen:
                continue
            seen.add(ad)
            try:
                liq = float(a.get("reserve_in_usd") or 0)
            except (TypeError, ValueError):
                liq = 0.0
            pools.append({"net": net, "addr": ad, "name": a.get("name"), "liq": liq})
        time.sleep(0.22)
print(f"pools sampled: {len(pools)}")

# ---- exit rules, each returns the realised multiple ----
def evaluate(px):
    """px: list of closes from the call day onward. Returns {rule: multiple}."""
    entry = px[0]
    if entry <= 0:
        return None
    rel = [p / entry for p in px[1:]]
    if not rel:
        return None
    peak = max(rel)
    out = {"peak": peak, "hold_to_end": rel[-1]}
    # sell everything at the first touch of a target
    for tgt in (1.25, 1.5, 2.0, 3.0, 5.0):
        hit = next((r for r in rel if r >= tgt), None)
        out[f"all_at_{tgt}x"] = tgt if hit is not None else rel[-1]
    # sell half at 2x, let the rest ride to the end
    half = next((i for i, r in enumerate(rel) if r >= 2.0), None)
    out["half_at_2x_rest_hold"] = (0.5 * 2.0 + 0.5 * rel[-1]) if half is not None else rel[-1]
    # sell half at 1.5x, then stop the remainder out at entry
    h15 = next((i for i, r in enumerate(rel) if r >= 1.5), None)
    if h15 is not None:
        after = rel[h15:]
        stopped = next((r for r in after if r <= 1.0), None)
        out["half_at_1.5x_rest_be"] = 0.5 * 1.5 + 0.5 * (1.0 if stopped is not None else after[-1])
    else:
        out["half_at_1.5x_rest_be"] = rel[-1]
    # time exits
    for d in (1, 3, 7):
        out[f"exit_day_{d}"] = rel[min(d, len(rel)) - 1]
    # trailing: exit when price falls 30% from its running peak
    run, ex = 0.0, None
    for r in rel:
        run = max(run, r)
        if run > 0 and r <= run * 0.70:
            ex = r
            break
    out["trail_30pct"] = ex if ex is not None else rel[-1]
    return out


rows, used = [], 0
for pl in pools:
    if used >= 300:
        break
    o = get(f"{GT}/networks/{pl['net']}/pools/{pl['addr']}/ohlcv/day?limit=120")
    time.sleep(0.18)
    if "__err__" in o:
        continue
    lst = ((o.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    lst = list(reversed(lst))
    closes = [float(r[4]) for r in lst if r and len(r) >= 5 and r[4] and float(r[4]) > 0]
    if len(closes) < CALL_DAY + MIN_DAYS:
        continue
    seg = closes[CALL_DAY:CALL_DAY + 1 + HORIZON]
    ev = evaluate(seg)
    if not ev:
        continue
    used += 1
    ev.update({"name": pl["name"], "net": pl["net"], "liq": pl["liq"],
               "days": len(seg) - 1})
    rows.append(ev)
    if used % 40 == 0:
        print(f"  {used} tokens evaluated ...", flush=True)

print(f"\ntokens with usable history: {used}")
if used < 50:
    raise SystemExit("too few tokens sampled to say anything")

RULES = ["peak", "hold_to_end", "all_at_1.25x", "all_at_1.5x", "all_at_2.0x",
         "all_at_3.0x", "all_at_5.0x", "half_at_2x_rest_hold",
         "half_at_1.5x_rest_be", "exit_day_1", "exit_day_3", "exit_day_7",
         "trail_30pct"]

print("\n" + "=" * 100)
print(f"WHAT A MECHANICAL EXIT CAPTURES — {used} tokens, call on day {CALL_DAY}, {HORIZON}d window")
print("=" * 100)
print(f"  {'rule':<24}{'median':>9}{'mean':>9}{'% > 1x':>9}{'% > 2x':>9}{'worst':>8}{'best':>9}")
print("-" * 100)
out = {"tokens": used, "call_day": CALL_DAY, "horizon_days": HORIZON,
       "networks": NETWORKS, "rules": {}}
for r in RULES:
    v = np.array([x[r] for x in rows if r in x and np.isfinite(x[r])])
    if len(v) < 20:
        continue
    print(f"  {r:<24}{np.median(v):>9.3f}{v.mean():>9.3f}"
          f"{100*np.mean(v>1):>8.1f}%{100*np.mean(v>2):>8.1f}%"
          f"{v.min():>8.3f}{v.max():>9.2f}")
    out["rules"][r] = {"n": int(len(v)), "median": round(float(np.median(v)), 4),
                       "mean": round(float(v.mean()), 4),
                       "pct_above_1x": round(100 * float(np.mean(v > 1)), 1),
                       "pct_above_2x": round(100 * float(np.mean(v > 2)), 1),
                       "worst": round(float(v.min()), 4), "best": round(float(v.max()), 3)}

pk = np.array([x["peak"] for x in rows])
hd = np.array([x["hold_to_end"] for x in rows])
print("\n" + "=" * 100)
print("THE PEAK ILLUSION")
print("=" * 100)
print(f"  median PEAK multiple        {np.median(pk):.3f}x   <- what a caller's stats quote")
print(f"  median HOLD-TO-END multiple {np.median(hd):.3f}x   <- what holding actually gives")
print(f"  ratio                       {np.median(pk)/max(np.median(hd),1e-9):.2f}x of the peak is given back")
print(f"  tokens whose peak beat 2x:  {100*np.mean(pk>2):.1f}%")
print(f"  tokens that ENDED above 2x: {100*np.mean(hd>2):.1f}%")
print(f"  tokens that ended below 1x: {100*np.mean(hd<1):.1f}%")
out["peak_illusion"] = {
    "median_peak": round(float(np.median(pk)), 4),
    "median_hold_to_end": round(float(np.median(hd)), 4),
    "pct_peak_above_2x": round(100 * float(np.mean(pk > 2)), 1),
    "pct_ended_above_2x": round(100 * float(np.mean(hd > 2)), 1),
    "pct_ended_below_1x": round(100 * float(np.mean(hd < 1)), 1)}

best = max((r for r in out["rules"] if r not in ("peak",)),
           key=lambda r: out["rules"][r]["median"])
print(f"\n  BEST RULE BY MEDIAN: {best}  ({out['rules'][best]['median']:.3f}x median, "
      f"{out['rules'][best]['mean']:.3f}x mean)")
out["best_rule_by_median"] = best
out["survivorship_warning"] = (
    "tokens sampled from CURRENT GeckoTerminal listings; those that died hard enough to be "
    "delisted are absent and they are the worst ones. All absolute levels are optimistic. "
    "The PEAK-vs-REALISED GAP is the robust finding; the levels are an upper bound.")
with io.open(os.path.join(HERE, "meme_calls.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote meme_calls.json")
