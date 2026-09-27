#!/usr/bin/env python3
"""
DEPTH / ORDER-FLOW SIGNAL CALIBRATION  (WAGMI co-pilot honest signal-worth test)

Question: does an order-book / taker-flow signal (L2 depth imbalance, taker
buy/sell ratio, long/short account ratio) have any FORWARD predictive worth?

This is NOT a hunt for a directional entry edge. It calibrates whether this
co-pilot signal is a real hint or noise, so the co-pilot's framing matches
measured truth. A clean null is a fully acceptable, expected result.

PRE-REGISTERED (committed before any forward return was computed):
  Primary signal : l2.imbalance_0_1pct  (near-touch book imbalance)
    Prediction   : extreme touch imbalance -> mild REVERSION over 1h; likely NOISE net of fees.
  Secondary      : futures_ctx.taker_buy_sell_ratio -> weak continuation (exploratory)
                   futures_ctx.long_short_account_ratio -> contrarian (exploratory)
  Statistic      : signed continuation return = sign(signal-neutral) * fwd_return
                   (positive mean => "follow" works; negative => "fade" works)
  Horizon        : primary 1h forward; secondary 4h forward.
  Extreme        : per-symbol top/bottom 15% by |signal-neutral|, thresholds
                   from TRAIN ONLY, applied to TEST.
  Dedup          : per-symbol cooldown = horizon; forward windows never overlap.
  OOS            : chronological per-symbol split, train=first 60%, test=last 40%.
                   Decisive = TEST.
  Fees           : HL taker round-trip ~9 bps applied to net P&L framing.
  Neg control    : random timestamps (unconditioned), same n -> expect ~0.

ENTRY-TIME-SAFE: signal at t uses only data through t; outcome strictly forward
(mid at t+horizon). No ledger join (mid price lives in the same snapshot record),
so no close-time look-ahead risk.

Reproduce:  python tools/copilot/depth_flow_calibration.py --seed 12345
"""
import json, argparse, random, statistics, math, collections, datetime as dt

DATA = "data/market_depth_history.jsonl"
GOOD_SYMBOLS = ("BTC", "ETH", "HYPE", "SOL", "XRP")
FEE_BPS_ROUNDTRIP = 9.0          # HL taker round-trip ~9 bps
CADENCE_S = 15 * 60
EXTREME_FRAC = 0.15
TRAIN_FRAC = 0.60

# (group, field, neutral point, naive-direction) ; naive-dir=+1 means signal>neutral naively bullish
SIGNALS = {
    "imbalance_0_1pct":       ("l2", "imbalance_0_1pct", 0.0, +1),
    "taker_buy_sell_ratio":   ("futures_ctx", "taker_buy_sell_ratio", 1.0, +1),
    "long_short_account_ratio": ("futures_ctx", "long_short_account_ratio", 1.0, +1),
}

def parse_ts(x):
    return dt.datetime.fromisoformat(x.replace("Z", "+00:00"))

def load():
    per = collections.defaultdict(list)
    with open(DATA) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("symbol") in GOOD_SYMBOLS:
                per[d["symbol"]].append(d)
    for s in per:
        per[s].sort(key=lambda d: d["ts"])
    return per

def getv(d, grp, fld):
    g = d.get(grp)
    return g.get(fld) if isinstance(g, dict) else None

def build_series(records):
    """Return list of (epoch_seconds, mid, {signal_name: value}) with valid mid."""
    out = []
    for d in records:
        mid = getv(d, "l2", "mid")
        if not isinstance(mid, (int, float)) or mid <= 0:
            continue
        t = parse_ts(d["ts"]).timestamp()
        sig = {}
        for name, (grp, fld, _, _) in SIGNALS.items():
            v = getv(d, grp, fld)
            sig[name] = v if isinstance(v, (int, float)) else None
        out.append((t, mid, sig))
    return out

def fwd_mid(series, i, horizon_s, tol_s=CADENCE_S):
    """Find mid at series[i].t + horizon_s, accept nearest within tol_s. Returns mid or None."""
    t0 = series[i][0]
    target = t0 + horizon_s
    j = i + 1
    best = None
    best_dt = None
    while j < len(series):
        t = series[j][0]
        if t > target + tol_s:
            break
        dd = abs(t - target)
        if best_dt is None or dd < best_dt:
            best_dt = dd
            best = series[j][1]
        j += 1
    if best is not None and best_dt is not None and best_dt <= tol_s:
        return best
    return None

def episodes_for_signal(series, sig_name, horizon_s, lo_thr, hi_thr):
    """Yield extreme episodes with cooldown=horizon. lo_thr/hi_thr are signal-value
    thresholds (below lo or above hi = extreme). Returns list of signed continuation returns."""
    _, _, neutral, ndir = (SIGNALS[sig_name][0], SIGNALS[sig_name][1],
                            SIGNALS[sig_name][2], SIGNALS[sig_name][3])
    res = []
    cooldown_until = -1
    for i in range(len(series)):
        t0, mid0, sig = series[i]
        if t0 < cooldown_until:
            continue
        v = sig.get(sig_name)
        if v is None:
            continue
        if not (v <= lo_thr or v >= hi_thr):
            continue
        fm = fwd_mid(series, i, horizon_s)
        if fm is None:
            continue
        fwd_ret = fm / mid0 - 1.0
        naive_dir = ndir * (1 if v >= neutral else -1)   # direction signal points
        signed = naive_dir * fwd_ret                     # >0 continuation, <0 reversion
        res.append(signed)
        cooldown_until = t0 + horizon_s
    return res

def train_thresholds(series, sig_name, split_t):
    _, _, neutral, _ = SIGNALS[sig_name]
    vals = [s[sig_name] for (t, m, s) in series
            if t < split_t and s.get(sig_name) is not None]
    if len(vals) < 40:
        return None
    vals_sorted = sorted(vals)
    lo = vals_sorted[int(EXTREME_FRAC * len(vals_sorted))]
    hi = vals_sorted[int((1 - EXTREME_FRAC) * len(vals_sorted))]
    return lo, hi

def tstat(xs):
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    m = statistics.mean(xs)
    sd = statistics.pstdev(xs)
    if sd == 0:
        return m, 0.0
    se = sd / math.sqrt(n)
    return m, m / se

def summarize(xs, label):
    n = len(xs)
    if n == 0:
        return f"{label}: n=0"
    m, t = tstat(xs)
    wr = sum(1 for x in xs if x > 0) / n
    net = m - (FEE_BPS_ROUNDTRIP / 1e4)   # implied trade pays round-trip fee
    return (f"{label}: n={n:4d}  gross_signed={m*1e4:+7.2f}bps  net={net*1e4:+7.2f}bps  "
            f"t={t:+5.2f}  hitrate={wr:5.1%}")

def run(seed):
    rng = random.Random(seed)
    per = load()
    horizons = {"1h": 3600, "4h": 4 * 3600}

    print("=" * 96)
    print("DEPTH / ORDER-FLOW FORWARD-PREDICTIVE CALIBRATION")
    print(f"seed={seed}  fees={FEE_BPS_ROUNDTRIP}bps rt  extreme={EXTREME_FRAC:.0%}  "
          f"train={TRAIN_FRAC:.0%}  symbols={','.join(GOOD_SYMBOLS)}")
    print("=" * 96)

    for sig_name in SIGNALS:
        print(f"\n#### SIGNAL: {sig_name}  (naive-dir continuation coefficient)")
        for hname, hs in horizons.items():
            pooled_train, pooled_test = [], []
            per_sym_test = {}
            neg_pooled = []
            for sym in GOOD_SYMBOLS:
                series = build_series(per[sym])
                if len(series) < 100:
                    continue
                t_lo = series[0][0]
                t_hi = series[-1][0]
                split_t = t_lo + TRAIN_FRAC * (t_hi - t_lo)
                thr = train_thresholds(series, sig_name, split_t)
                if thr is None:
                    continue
                lo, hi = thr
                train_series = [s for s in series if s[0] < split_t]
                test_series = [s for s in series if s[0] >= split_t]
                tr = episodes_for_signal(train_series, sig_name, hs, lo, hi)
                te = episodes_for_signal(test_series, sig_name, hs, lo, hi)
                pooled_train += tr
                pooled_test += te
                per_sym_test[sym] = te

                # negative control: random timestamps (unconditioned), random assigned
                # direction, non-overlapping. Decoupled from test-n for a stable baseline
                # (up to 300/symbol) -> confirms the forward-return machinery is unbiased.
                idx_pool = list(range(len(test_series)))
                rng.shuffle(idx_pool)
                want = 300
                picks = []
                used = []  # accepted [t0, t0+hs] intervals; reject overlaps
                for i in idx_pool:
                    if len(picks) >= want:
                        break
                    t0 = test_series[i][0]
                    if any(not (t0 + hs <= a or t0 >= b) for (a, b) in used):
                        continue
                    fm = fwd_mid(test_series, i, hs)
                    if fm is None:
                        continue
                    fwd_ret = fm / test_series[i][1] - 1.0
                    picks.append(rng.choice([1, -1]) * fwd_ret)  # random unconditioned direction
                    used.append((t0, t0 + hs))
                neg_pooled += picks

            print(f"  [{hname}]")
            print("    TRAIN " + summarize(pooled_train, "pooled"))
            print("    TEST  " + summarize(pooled_test, "pooled"))
            print("    CTRL  " + summarize(neg_pooled, "random-ts"))
            # per-symbol test robustness
            for sym in GOOD_SYMBOLS:
                if sym in per_sym_test and per_sym_test[sym]:
                    print("      " + summarize(per_sym_test[sym], f"TEST {sym}"))
            # era robustness: split test into halves chronologically (pooled already time-ordered? no)
    print("\n" + "=" * 96)
    print("Interpretation: signed continuation coefficient. Positive+significant+net>0 in TEST")
    print("and absent in random control => real. |t|<2 or net<0 => NOISE. Small real tilt => HINT.")
    print("=" * 96)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()
    run(args.seed)
