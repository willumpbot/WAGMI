"""Ladder-selling called memes: peaks DO matter, so measure the peak distribution.

Correction to my earlier framing. I said "median, not mean" and "peak is the number
you cannot capture". That is right for a single all-or-nothing exit. It is WRONG
for a ladder, because a ladder is specifically a machine for harvesting the right
tail: a call peaking at 5x fills five rungs, one peaking at 1.2x fills one. So the
object that decides ladder yield is the DISTRIBUTION OF PEAKS, tail included.

What survives from the earlier caution, narrowed: you do not capture the peak, you
capture a fraction of it set by rung spacing -- and Rick measures peak from the
CALL price while your ladder fills from YOUR entry. So this also measures the
entry tax directly, by laddering from a delayed entry as well as from the call.

Reports:
  1. P(peak >= k) -- the primitive a ladder designer actually needs
  2. realised multiple for several ladder designs, from the call price
  3. the same ladders from a DELAYED entry (next bar), i.e. after the crowd
  4. what the unfilled remainder does: hold to end vs stop at entry

SURVIVORSHIP: tokens come from GeckoTerminal's CURRENT listings, so hard rugs are
absent and they are the worst cases. Every level here is OPTIMISTIC. The shape of
P(peak >= k) and the RANKING of ladders are the usable outputs.
"""
import json, io, os, math, time, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GT = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "wagmi-research/1.0"}
NETWORKS = ["solana", "base", "eth", "bsc"]
PAGES = tuple(range(1, 11))
CALL_DAY = 3
MIN_DAYS = 14
HORIZON = 30
PEAK_GRID = [1.2, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0]

# (multiple, fraction) rungs; fractions need not sum to 1 -- the remainder is the moonbag
LADDERS = {
    "fast 70@1.3 / 30@2": [(1.3, 0.70), (2.0, 0.30)],
    "conservative 50@1.5 / 30@2 / 20@3": [(1.5, 0.50), (2.0, 0.30), (3.0, 0.20)],
    "balanced 25 each @1.5/2/3/5": [(1.5, 0.25), (2.0, 0.25), (3.0, 0.25), (5.0, 0.25)],
    "moonbag 20@2/3/5/10, 20% held": [(2.0, 0.20), (3.0, 0.20), (5.0, 0.20), (10.0, 0.20)],
    "wide 33@2 / 33@5 / 33@10": [(2.0, 1 / 3), (5.0, 1 / 3), (10.0, 1 / 3)],
    "single all @2": [(2.0, 1.00)],
    "single all @1.5": [(1.5, 1.00)],
}


def get(url, tries=3):
    for k in range(tries):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=30).read())
        except Exception as e:
            if k == tries - 1:
                return {"__err__": str(e)}
            time.sleep(1.2 * (k + 1))
    return {"__err__": "unreachable"}


def ladder_yield(rel, rungs, remainder="hold"):
    """rel: price path as multiples of entry, in order. Returns realised multiple."""
    got, filled = 0.0, 0.0
    run = 0.0
    for mult, frac in rungs:
        # a rung fills if the path ever reaches it
        if any(r >= mult for r in rel):
            got += frac * mult
            filled += frac
    left = max(0.0, 1.0 - filled)
    if left > 0:
        if remainder == "hold":
            got += left * rel[-1]
        else:   # stop the remainder at entry once the first rung has filled
            stopped = filled > 0 and any(r <= 1.0 for r in rel)
            got += left * (1.0 if stopped else rel[-1])
    return got


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
            pools.append({"net": net, "addr": ad, "name": a.get("name")})
        time.sleep(0.22)
print(f"pools sampled: {len(pools)}", flush=True)

rows, used = [], 0
for pl in pools:
    if used >= 400:
        break
    o = get(f"{GT}/networks/{pl['net']}/pools/{pl['addr']}/ohlcv/day?limit=120")
    time.sleep(0.18)
    if "__err__" in o:
        continue
    lst = ((o.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    lst = list(reversed(lst))
    # use HIGHS for peak detection -- a ladder rung fills intraday, not at the close
    bars = [(float(r[2]), float(r[4])) for r in lst
            if r and len(r) >= 5 and r[2] and r[4] and float(r[4]) > 0]
    if len(bars) < CALL_DAY + MIN_DAYS:
        continue
    seg = bars[CALL_DAY:CALL_DAY + 1 + HORIZON]
    if len(seg) < 3:
        continue
    e_call = seg[0][1]                 # close of the call day
    e_late = seg[1][1]                 # close of the NEXT day = after the crowd
    if e_call <= 0 or e_late <= 0:
        continue
    used += 1
    rec = {"name": pl["name"], "net": pl["net"], "tax": e_late / e_call}
    for tag, entry, path in (("call", e_call, seg[1:]), ("late", e_late, seg[2:])):
        if not path:
            continue
        relH = [h / entry for h, _ in path]     # highs, for rung fills
        relC = [c / entry for _, c in path]     # closes, for the remainder
        rec[f"peak_{tag}"] = max(relH)
        rec[f"end_{tag}"] = relC[-1]
        for name, rungs in LADDERS.items():
            rec[f"{tag}|{name}|hold"] = ladder_yield(relH + [relC[-1]], rungs, "hold")
            rec[f"{tag}|{name}|stop"] = ladder_yield(relH + [relC[-1]], rungs, "stop")
    rows.append(rec)
    if used % 50 == 0:
        print(f"  {used} tokens ...", flush=True)

print(f"\ntokens usable: {used}")
if used < 50:
    raise SystemExit("too few tokens to say anything")

out = {"tokens": used, "call_day": CALL_DAY, "horizon_days": HORIZON,
       "note": "peaks detected on daily HIGHS, remainder marked at the close"}

pk = np.array([r["peak_call"] for r in rows if "peak_call" in r])
pl_ = np.array([r["peak_late"] for r in rows if "peak_late" in r])
tax = np.array([r["tax"] for r in rows])
print("\n" + "=" * 92)
print("1. P(peak >= k) — the primitive a ladder needs")
print("=" * 92)
print(f"  {'rung k':>8}{'from call':>14}{'from late entry':>18}")
for k in PEAK_GRID:
    print(f"  {k:>8.1f}{100*np.mean(pk>=k):>13.1f}%{100*np.mean(pl_>=k):>17.1f}%")
out["p_peak_ge"] = {str(k): {"from_call": round(100 * float(np.mean(pk >= k)), 1),
                             "from_late": round(100 * float(np.mean(pl_ >= k)), 1)}
                    for k in PEAK_GRID}

print(f"\n  median peak from call {np.median(pk):.3f}x   from late entry {np.median(pl_):.3f}x")
print(f"  THE ENTRY TAX: median next-day price is {np.median(tax):.3f}x the call price")
print(f"  ({100*np.mean(tax>1):.0f}% of calls were HIGHER a day later, "
      f"{100*np.mean(tax<1):.0f}% lower)")
out["entry_tax"] = {"median_next_day_mult": round(float(np.median(tax)), 4),
                    "pct_higher_next_day": round(100 * float(np.mean(tax > 1)), 1),
                    "median_peak_from_call": round(float(np.median(pk)), 4),
                    "median_peak_from_late": round(float(np.median(pl_)), 4)}

print("\n" + "=" * 92)
print("2. LADDER YIELD — realised multiple (mean matters here: ladders harvest the tail)")
print("=" * 92)
for tag, label in (("call", "entering AT the call price"), ("late", "entering a day LATE")):
    print(f"\n  {label}")
    print(f"    {'ladder':<36}{'median':>9}{'mean':>9}{'%>1x':>8}{'worst':>8}{'best':>9}")
    for name in LADDERS:
        for rem in ("hold", "stop"):
            key = f"{tag}|{name}|{rem}"
            v = np.array([r[key] for r in rows if key in r])
            if len(v) < 30:
                continue
            lab = f"{name} [{rem}]"
            print(f"    {lab[:35]:<36}{np.median(v):>9.3f}{v.mean():>9.3f}"
                  f"{100*np.mean(v>1):>7.0f}%{v.min():>8.3f}{v.max():>9.2f}")
            out.setdefault("ladders", {})[key] = {
                "n": int(len(v)), "median": round(float(np.median(v)), 4),
                "mean": round(float(v.mean()), 4),
                "pct_above_1x": round(100 * float(np.mean(v > 1)), 1),
                "worst": round(float(v.min()), 4), "best": round(float(v.max()), 3)}

L = out.get("ladders", {})
if L:
    bym = max((k for k in L if k.startswith("call|")), key=lambda k: L[k]["mean"])
    byd = max((k for k in L if k.startswith("call|")), key=lambda k: L[k]["median"])
    bml = max((k for k in L if k.startswith("late|")), key=lambda k: L[k]["mean"])
    print("\n" + "=" * 92)
    print("3. BEST LADDERS")
    print("=" * 92)
    print(f"  by MEAN, from call : {bym.split('|',1)[1]}   mean {L[bym]['mean']:.3f}x  median {L[bym]['median']:.3f}x")
    print(f"  by MEDIAN, from call: {byd.split('|',1)[1]}   mean {L[byd]['mean']:.3f}x  median {L[byd]['median']:.3f}x")
    print(f"  by MEAN, entering late: {bml.split('|',1)[1]}   mean {L[bml]['mean']:.3f}x")
    print(f"\n  cost of entering a day late, on the mean-best ladder: "
          f"{L[bym]['mean'] - L.get(bym.replace('call|','late|'), {}).get('mean', float('nan')):+.3f}x")
    out["best"] = {"by_mean_from_call": bym, "by_median_from_call": byd,
                   "by_mean_from_late": bml}
out["survivorship_warning"] = (
    "GeckoTerminal CURRENT listings only; hard rugs are delisted and absent. Levels are "
    "optimistic. Use the SHAPE of P(peak>=k) and the RANKING of ladders, not the absolute multiples.")
with io.open(os.path.join(HERE, "ladder.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("\nwrote ladder.json")
