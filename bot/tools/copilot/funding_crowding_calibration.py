"""
Funding/OI CROWDING signal calibration for the WAGMI co-pilot.

HONEST question: does a funding-rate "crowding" state have predictive worth for
FORWARD adverse price moves (mean-reversion against the crowd)? This is a RISK
signal calibration, not a directional-entry hunt.

Pre-registered design (moat):
  - Universe: symbols with >=37d of 16-min funding/price history
    (BTC, ETH, SOL, HYPE, XRP). Memes/rotating excluded (<=5d history).
  - Signal: "crowding" = funding rate beyond a per-symbol quantile threshold.
      crowded-long  = funding >= train Q(HI)  (longs paying -> too many longs)
      crowded-short = funding <= train Q(LO)  (shorts paying -> too many shorts)
  - Outcome: forward return over N hours from the SAME collector's price series.
      fade_return = -sign(funding) * forward_ret
      (fade the crowd: short a crowded long, long a crowded short).
      Positive fade_return => the crowd got hurt => signal has worth.
  - Entry-time-safe: thresholds computed on TRAIN only, applied to strictly-later
    TEST; outcome window is strictly forward (t -> t+N).
  - Independence/dedup: after a trigger at t, suppress further triggers until
    t+N hours => non-overlapping forward windows.
  - Net-of-fees: subtract HL ~9 bps round-trip from a fade P&L interpretation.
  - Refutation: random-timestamp negative control (same episode count); per-symbol
    and per-era (month) breakdown to catch single-symbol / single-regime artifacts.
  - Verdict gate: EDGE only if TEST holds OOS + n>=30 + p<0.05 + control ~0.
    Mild real tilt = HINT. Null = NOISE.

Usage:
  python tools/copilot/funding_crowding_calibration.py
Reads (read-only): data/funding_oi_history.jsonl
Writes nothing outside stdout (results doc written separately).
"""
import json, os, math, random
from datetime import datetime, timedelta
from collections import defaultdict

random.seed(1729)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "data", "funding_oi_history.jsonl")

UNIVERSE = ["BTC", "ETH", "SOL", "HYPE", "XRP"]
HORIZONS_H = [8, 24]          # forward horizons
Q_HI, Q_LO = 0.80, 0.20       # crowding quantiles
TRAIN_FRAC = 0.60             # chronological split
FEE_ROUNDTRIP = 0.0009        # ~9 bps HL round-trip (project memory)
TOL_MIN = 30                  # tolerance (min) for locating t+N price tick


def load():
    by = defaultdict(list)
    with open(DATA, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            s = r["symbol"]
            if s not in UNIVERSE:
                continue
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                fr = float(r["funding_rate"])
                px = float(r["price"])
                oi = float(r.get("open_interest", 0) or 0)
            except (ValueError, TypeError, KeyError):
                continue
            if px <= 0:
                continue
            by[s].append((ts, fr, px, oi))
    for s in by:
        by[s].sort(key=lambda x: x[0])
    return by


def price_at(series, target_ts):
    """Nearest price tick to target_ts within TOL_MIN minutes, else None."""
    best, bestd = None, timedelta(minutes=TOL_MIN)
    # series is sorted; small linear scan is fine at this scale
    for ts, _, px, _ in series:
        d = abs(ts - target_ts)
        if d <= bestd:
            best, bestd = px, d
        if ts - target_ts > timedelta(minutes=TOL_MIN):
            break
    return best


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return sorted_vals[idx]


def bootstrap_ci(vals, n_boot=5000):
    if len(vals) < 2:
        return (float("nan"), float("nan"))
    means = []
    m = len(vals)
    for _ in range(n_boot):
        s = sum(vals[random.randrange(m)] for _ in range(m)) / m
        means.append(s)
    means.sort()
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot)]


def tstat(vals):
    n = len(vals)
    if n < 2:
        return float("nan"), float("nan")
    mean = sum(vals) / n
    var = sum((x - mean) ** 2 for x in vals) / (n - 1)
    se = math.sqrt(var / n)
    if se == 0:
        return float("nan"), float("nan")
    t = mean / se
    # two-sided p via normal approx (n usually >=30)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return t, p


def oi_change_trailing(series, i, lookback_h=4):
    """OI % change over trailing lookback_h, using only ticks at/ before i
    (entry-time-safe). None if not enough history."""
    ts_i, _, _, oi_i = series[i]
    if oi_i <= 0:
        return None
    target = ts_i - timedelta(hours=lookback_h)
    oi_past = None
    for j in range(i, -1, -1):
        if series[j][0] <= target:
            oi_past = series[j][3]
            break
    if oi_past is None or oi_past <= 0:
        return None
    return (oi_i - oi_past) / oi_past


def build_episodes(series, thr_hi, thr_lo, horizon_h, split_ts,
                   require_oi_rising=False, oi_min=0.0):
    """Walk TEST-region ticks (ts >= split_ts), non-overlapping by horizon.
    Returns list of dicts with fade_return + meta. Entry-time-safe: thresholds
    are from train; outcome strictly forward. Optional OI-rising overlay =
    "crowding INTO a move" (funding extreme AND OI building over trailing 4h)."""
    eps = []
    block_until = None
    hz = timedelta(hours=horizon_h)
    for i, (ts, fr, px, oi) in enumerate(series):
        if ts < split_ts:
            continue
        if block_until is not None and ts < block_until:
            continue
        crowd = 0
        if fr >= thr_hi:
            crowd = +1   # crowded long
        elif fr <= thr_lo:
            crowd = -1   # crowded short
        if crowd == 0:
            continue
        if require_oi_rising:
            oic = oi_change_trailing(series, i)
            if oic is None or oic < oi_min:
                continue
        fpx = price_at(series, ts + hz)
        if fpx is None:
            continue
        fwd = (fpx - px) / px
        fade = -crowd * fwd
        eps.append({"ts": ts, "crowd": crowd, "fwd": fwd, "fade": fade,
                    "funding": fr})
        block_until = ts + hz
    return eps


def random_control(series, n_target, horizon_h, split_ts):
    """Same episode count, random TEST timestamps, real realized funding sign."""
    hz = timedelta(hours=horizon_h)
    cand = [(ts, fr, px) for ts, fr, px, oi in series
            if ts >= split_ts and price_at(series, ts + hz) is not None]
    if len(cand) < n_target or n_target == 0:
        return []
    picks = random.sample(cand, n_target)
    out = []
    for ts, fr, px in picks:
        fpx = price_at(series, ts + hz)
        fwd = (fpx - px) / px
        crowd = 1 if fr >= 0 else -1  # fade whatever side funding leans
        out.append(-crowd * fwd)
    return out


def summarize(vals, label, net=False):
    if not vals:
        print(f"  {label:28} n=0")
        return None
    v = [x - FEE_ROUNDTRIP for x in vals] if net else list(vals)
    n = len(v)
    mean = sum(v) / n
    wins = sum(1 for x in v if x > 0)
    t, p = tstat(v)
    lo, hi = bootstrap_ci(v)
    tag = "net" if net else "gross"
    print(f"  {label:28} n={n:4} mean={mean*100:+6.3f}% ({tag})  "
          f"win%={wins/n*100:4.1f}  t={t:+5.2f} p={p:5.3f}  "
          f"95%CI=[{lo*100:+.3f}%,{hi*100:+.3f}%]")
    return {"n": n, "mean": mean, "winpct": wins / n, "t": t, "p": p,
            "ci": (lo, hi)}


def run():
    by = load()
    print("=" * 92)
    print("FUNDING CROWDING CALIBRATION  (fade-the-crowd forward return)")
    print("Signal: funding beyond per-symbol TRAIN quantile. Outcome: forward N-h return.")
    print("fade_return = -sign(crowd) * forward_ret ; positive => crowd got hurt => worth")
    print("=" * 92)

    # global chronological split point
    all_ts = sorted(ts for s in by for ts, *_ in by[s])
    split_ts = all_ts[int(TRAIN_FRAC * len(all_ts))]
    print(f"Universe: {', '.join(by.keys())}")
    print(f"Train/test split @ {split_ts}  (train={TRAIN_FRAC:.0%})")
    print(f"Fee (round-trip): {FEE_ROUNDTRIP*100:.2f}%   Horizons: {HORIZONS_H} h\n")

    results = {}
    for hz in HORIZONS_H:
        print("-" * 92)
        print(f"HORIZON {hz}h")
        print("-" * 92)
        all_eps, control_all = [], []
        per_symbol = {}
        for s in UNIVERSE:
            series = by.get(s, [])
            if not series:
                continue
            train = [fr for ts, fr, px, oi in series if ts < split_ts]
            if len(train) < 50:
                continue
            st = sorted(train)
            thr_hi = quantile(st, Q_HI)
            thr_lo = quantile(st, Q_LO)
            eps = build_episodes(series, thr_hi, thr_lo, hz, split_ts)
            ctrl = random_control(series, len(eps), hz, split_ts)
            per_symbol[s] = eps
            all_eps.extend(eps)
            control_all.extend(ctrl)

        fades = [e["fade"] for e in all_eps]
        print("POOLED (TEST, OOS):")
        g = summarize(fades, "crowding fade (gross)")
        nres = summarize(fades, "crowding fade (net fee)", net=True)
        summarize(control_all, "NEG CONTROL random", )
        # directional split
        cl = [e["fade"] for e in all_eps if e["crowd"] == +1]
        cs = [e["fade"] for e in all_eps if e["crowd"] == -1]
        print("  --- by crowd side ---")
        summarize(cl, "crowded-long faded (short)")
        summarize(cs, "crowded-short faded (long)")
        print("  --- by symbol ---")
        for s in UNIVERSE:
            if s in per_symbol:
                summarize([e["fade"] for e in per_symbol[s]], f"{s}")
        print("  --- by era (entry month) ---")
        era = defaultdict(list)
        for e in all_eps:
            era[e["ts"].strftime("%Y-%m")].append(e["fade"])
        for m in sorted(era):
            summarize(era[m], f"month {m}")
        results[hz] = {"gross": g, "net": nres, "n": len(fades)}
        print()

    # --- SECONDARY: OI-conditioned "crowding INTO a move" (funding extreme
    #     AND OI rising >1% over trailing 4h). Honors pre-registered AND/OR OI. ---
    print("=" * 92)
    print("SECONDARY: crowding INTO rising OI  (funding extreme AND OI +>1% trailing 4h)")
    print("=" * 92)
    for hz in HORIZONS_H:
        oi_eps = []
        for s in UNIVERSE:
            series = by.get(s, [])
            if not series:
                continue
            train = [fr for ts, fr, px, oi in series if ts < split_ts]
            if len(train) < 50:
                continue
            st = sorted(train)
            thr_hi, thr_lo = quantile(st, Q_HI), quantile(st, Q_LO)
            oi_eps.extend(build_episodes(series, thr_hi, thr_lo, hz, split_ts,
                                         require_oi_rising=True, oi_min=0.01))
        print(f"HORIZON {hz}h  (OI-rising overlay):")
        summarize([e["fade"] for e in oi_eps], "crowding+OIrising fade (gross)")
        summarize([e["fade"] for e in oi_eps], "crowding+OIrising fade (net)", net=True)
        print()

    return results


if __name__ == "__main__":
    run()
