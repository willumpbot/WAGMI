"""The laptop's piece of the hivemind: a single risk voice.

Everything the laptop established that is actually actionable, behind one call,
so the server imports a module instead of re-implementing three reports:

    from bot.data.laptop_mining.risk_voice import risk_read
    r = risk_read("BTC", candles_1d)      # list of (t_ms, o, h, l, c) or a DataFrame

Returns, for one coin, right now:
    expected_move_1d / _5d   HAR-RV forecast, smearing-corrected   (VOLATILITY.md)
    vol_bucket               which quintile today's forecast sits in
    stop_pct                 2x the 1d forecast                    (ADAPTIVE_STOPS.md)
    target_pct               0.5R on that stop                     (ADAPTIVE_STOPS.md)
    max_leverage             p99-safe, with the 1.5x haircut        (SAFE_LEVERAGE.md)
    worst_case_1d            p99 adverse move for this bucket/side  (SAFE_LEVERAGE.md)
    expected_move_label      plain-language size read for the desk
    notes                    the caveats that must travel with the numbers

Design rules, learned the hard way in this project:
  * no directional opinion -- nothing here predicts which way price goes
  * coefficients are LOADED from the fitted artefacts, never refitted at call
    time, so the live path cannot drift from what was validated
  * every number carries its provenance in `notes`
"""
import json, io, os, math

HERE = os.path.dirname(os.path.abspath(__file__))
_VOL = os.path.join(HERE, "volatility_forecast.json")
_LEV = os.path.join(HERE, "safe_leverage.json")

# ADAPTIVE_STOPS.md recommended default
STOP_K = 2.0            # stop = 2 x forecast next-day move
TARGET_R = 0.5          # take profit at 0.5R
TIME_STOP_H = 48
LEV_HAIRCUT = 1.5       # SAFE_LEVERAGE.md: p99 delivered 97.7%, not 99%

_cache = {}


def _load(path, key):
    if key not in _cache:
        if not os.path.exists(path):
            _cache[key] = None
        else:
            _cache[key] = json.load(io.open(path, encoding="utf-8"))
    return _cache[key]


def _coeffs():
    """HAR-RV coefficients + smearing factors, as fitted and validated."""
    v = _load(_VOL, "vol")
    if not v:
        return None
    out = {}
    for tgt in ("y1", "y5"):
        b = v.get(f"{tgt}_beta")
        sm = v.get(f"{tgt}_smearing")
        if b and sm:
            out[tgt] = (b, float(sm))
    return out or None


def _series(candles):
    """Accept a DataFrame or a list of tuples/dicts; return a list of closes."""
    try:
        import pandas as pd
        if isinstance(candles, pd.DataFrame):
            col = "c" if "c" in candles.columns else "close"
            return [float(x) for x in candles[col].tolist()]
    except Exception:
        pass
    out = []
    for row in candles:
        if isinstance(row, dict):
            out.append(float(row.get("c", row.get("close"))))
        else:
            out.append(float(row[4] if len(row) >= 5 else row[-1]))
    return out


def _rv(closes):
    """rv1 / rv5 / rv22 in percent, from closed daily candles, past only."""
    if len(closes) < 24:
        return None
    rets = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
    def sd(xs):
        if len(xs) < 2:
            return 0.0
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return {"rv1": abs(rets[-1]), "rv5": sd(rets[-5:]), "rv22": sd(rets[-22:])}


def _forecast(rv, tgt):
    c = _coeffs()
    if not c or tgt not in c or not rv:
        return None
    beta, sm = c[tgt]
    eps = 1e-8
    x = [1.0, math.log(rv["rv1"] + eps), math.log(rv["rv5"] + eps), math.log(rv["rv22"] + eps)]
    if len(beta) != len(x):
        return None
    return math.exp(sum(b * xi for b, xi in zip(beta, x))) * sm


def _bucket_and_leverage(sym, fcast_1d, side="long"):
    lev = _load(_LEV, "lev")
    if not lev or not fcast_1d:
        return None, None, None
    tbl = (lev.get("table") or {}).get(sym)
    if not tbl:
        return None, None, None
    qs = tbl.get("quintiles") or {}
    # pick the quintile whose median forecast is closest from below
    best = None
    for name, rec in sorted(qs.items()):
        med = rec.get("fcast_median")
        if med is None:
            continue
        if med <= fcast_1d or best is None:
            best = (name, rec)
    if not best:
        return None, None, None
    name, rec = best
    key = f"max_lev_{'long' if side == 'long' else 'short'}_1d_p99"
    raw = rec.get(key)
    worst = (((rec.get("horizons") or {}).get("1d") or {}).get(side) or {}).get("p99")
    safe = round(raw / LEV_HAIRCUT, 1) if raw else None
    return name, safe, worst


def _label(fcast_1d, bucket):
    if fcast_1d is None:
        return "unknown"
    if bucket in ("Q1",):
        return f"quiet — about {fcast_1d:.1f}% expected today"
    if bucket in ("Q5",):
        return f"HOT — about {fcast_1d:.1f}% expected today, cut size"
    return f"normal — about {fcast_1d:.1f}% expected today"


def risk_read(sym, candles_1d, side="long"):
    """One coin's risk read. No directional opinion by design."""
    closes = _series(candles_1d)
    rv = _rv(closes)
    f1 = _forecast(rv, "y1")
    f5 = _forecast(rv, "y5")
    bucket, max_lev, worst = _bucket_and_leverage(sym, f1, side)
    stop_pct = round(STOP_K * f1, 3) if f1 else None
    out = {
        "symbol": sym,
        "side": side,
        "expected_move_1d_pct": round(f1, 3) if f1 else None,
        "expected_move_5d_pct": round(f5, 3) if f5 else None,
        "vol_bucket": bucket,
        "expected_move_label": _label(f1, bucket),
        "stop_pct": stop_pct,
        "target_pct": round(stop_pct * TARGET_R, 3) if stop_pct else None,
        "time_stop_hours": TIME_STOP_H,
        "max_leverage": max_lev,
        "worst_case_1d_pct": worst,
        "notes": [
            "Direction is not forecastable; nothing here is a directional call.",
            "expected_move: HAR-RV on rv1/rv5/rv22, smearing-corrected. Beat naive "
            "persistence in 22/22 walk-forward folds. OOS R2 +0.04..+0.12 -- real but small.",
            "Top two forecast deciles over-predict by 15-24%; shade them down ~20%.",
            f"stop_pct = {STOP_K}x the 1d forecast, target {TARGET_R}R, {TIME_STOP_H}h time stop "
            "(ADAPTIVE_STOPS.md). Beat a fixed stop of the same average width by +0.209R "
            "[+0.063,+0.343], but that was observed on test, not pre-registered.",
            f"max_leverage is the p99-safe level divided by {LEV_HAIRCUT}: the raw p99 bound "
            "covered 97.7% of out-of-sample days, not 99%, and the liquidation maths excludes "
            "funding and fees.",
            "Shorts need more room than longs at the same forecast (91.3% vs 94.8% p95 coverage).",
            "APPROXIMATION: the vol bucket is assigned by nearest quintile MEDIAN from below, "
            "because safe_leverage.json stores medians and not bin edges. A forecast landing "
            "between two medians is assigned the lower bucket, which is conservative on "
            "leverage but can be one bucket off. Storing the edges would make it exact.",
        ],
    }
    return out


def batch(candles_by_symbol, side="long"):
    return {s: risk_read(s, c, side) for s, c in candles_by_symbol.items()}


if __name__ == "__main__":
    import csv, glob
    HIST = os.path.join(HERE, "history")
    ok = _coeffs() is not None and _load(_LEV, "lev") is not None
    print(f"artefacts loaded: coefficients={_coeffs() is not None}  "
          f"leverage_table={_load(_LEV, 'lev') is not None}")
    if not ok:
        raise SystemExit("missing volatility_forecast.json or safe_leverage.json")
    for sym in ("BTC", "ETH", "SOL", "HYPE", "XRP"):
        p = os.path.join(HIST, f"{sym}_1d.csv")
        if not os.path.exists(p):
            continue
        rows = []
        with io.open(p, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    rows.append((int(r["t_ms"]), float(r["o"]), float(r["h"]),
                                 float(r["l"]), float(r["c"])))
                except (TypeError, ValueError):
                    continue
        r = risk_read(sym, rows[:-1])      # drop the still-forming candle
        print(f"\n  {sym}: {r['expected_move_label']}")
        print(f"    1d {r['expected_move_1d_pct']}%   5d {r['expected_move_5d_pct']}%   "
              f"bucket {r['vol_bucket']}")
        print(f"    stop {r['stop_pct']}%   target {r['target_pct']}%   "
              f"max lev {r['max_leverage']}x   worst 1d {r['worst_case_1d_pct']}%")
