"""SENSOR VALIDATION BACKTEST — validate WAGMI's mechanical/diagnostic layer
against multi-year free data. THE_STANDARD v1.4 compliant:
  - denominators (n) on every claim
  - era-splits by YEAR and by mechanical regime
  - honest ICs (t-stats use effective n corrected for overlapping horizons)
  - base rates alongside every hit rate
  - killed sensors logged as wins
  - artifact rule: edge concentrated in one year/regime is flagged

ZERO LLM calls. Pure computation. READ-ONLY on bot code (imports the real
strategies + mech_regime classifier; modifies nothing).

Data: Binance spot 1h klines via data-api.binance.vision (direct Binance is
geo-blocked 451 from this box) for BTC/ETH/SOL/XRP from 2023-01-01.
HYPE from Hyperliquid candleSnapshot (API only retains ~5000 1h bars).
Funding: Hyperliquid fundingHistory (hourly, back to mid-2023) — Binance
fapi funding is geo-blocked, noted in report.

Usage:
  python sensor_validation.py            # full run (fetch+cache, then compute)
  python sensor_validation.py --quick    # smoke test: BTC only, last 2000 bars
  python sensor_validation.py --fetch-only
"""

import argparse
import json
import logging
import math
import sys
import tempfile
import time as _time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from scipy.stats import spearmanr as _spearmanr
    def spearman(a, b):
        r = _spearmanr(a, b).correlation
        return float(r) if r is not None and not math.isnan(r) else float("nan")
except Exception:  # scipy optional
    def spearman(a, b):
        a = pd.Series(a).rank(); b = pd.Series(b).rank()
        if a.std() == 0 or b.std() == 0:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])

HERE = Path(__file__).resolve().parent            # bot/tools/research
BOT_DIR = HERE.parent.parent                      # bot/
ROOT = BOT_DIR.parent                             # WAGMI/
CACHE_DIR = HERE / "candle_cache"
REPORT_PATH = ROOT / "coordination" / "SENSOR_VALIDATION.md"

sys.path.insert(0, str(BOT_DIR))
logging.basicConfig(level=logging.ERROR)  # silence strategy INFO spam
for name in ("bot", "bot.strategy"):
    logging.getLogger(name).setLevel(logging.ERROR)

from trading_config import DEFAULT_SYMBOLS  # noqa: E402
from strategies.regime_trend import RegimeTrendStrategy  # noqa: E402
from strategies.monte_carlo_zones import MonteCarloZonesStrategy  # noqa: E402
from strategies.confidence_scorer import ConfidenceScorerStrategy  # noqa: E402
from strategies.multi_tier_quality import MultiTierQualityStrategy  # noqa: E402

import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("mech_regime", str(BOT_DIR / "llm" / "agents" / "mech_regime.py"))
_mech_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mech_mod)
compute_mech_regime = _mech_mod.compute_mech_regime

# ------------------------------------------------------------------ config
BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT"}
HL_SYMBOLS = ["HYPE"]
FUNDING_COINS = ["BTC", "ETH", "SOL", "XRP", "HYPE"]
START_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HORIZONS = {"1h": 1, "6h": 6, "24h": 24}
W1H = 400          # trailing 1h bars handed to hourly strategies
W6H = 70           # trailing 6h candles handed to strategies
WDAILY = 250       # trailing daily candles for monte_carlo
PTILE_WINDOW = 336
HIGH_VOL_PTILE = 0.90
TRENDING_ADX = 25.0

# ------------------------------------------------------------------ fetch

def _http_get(url, params, retries=5):
    import requests
    for k in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429):
                _time.sleep(2 ** k)
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception:
            if k == retries - 1:
                raise
            _time.sleep(1.5 ** k)


def _http_post(url, payload, retries=5):
    import requests
    for k in range(retries):
        try:
            r = requests.post(url, json=payload, timeout=25)
            if r.status_code == 200:
                return r.json()
            _time.sleep(2 ** k)
        except Exception:
            if k == retries - 1:
                raise
            _time.sleep(1.5 ** k)
    raise RuntimeError(f"POST failed: {url}")


def fetch_binance_1h(pair: str) -> list:
    """Paginated 1h klines from Binance Vision mirror. Rows: [ms,o,h,l,c,v]."""
    out, start = [], START_MS
    while True:
        batch = _http_get("https://data-api.binance.vision/api/v3/klines",
                          {"symbol": pair, "interval": "1h", "startTime": start, "limit": 1000})
        if not batch:
            break
        out.extend([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in batch])
        if len(batch) < 1000:
            break
        start = int(batch[-1][0]) + 3_600_000
        _time.sleep(0.12)
    return out


def fetch_hl_1h(coin: str) -> list:
    """HL candleSnapshot — API retains ~5000 most-recent 1h bars only."""
    now = int(_time.time() * 1000)
    d = _http_post("https://api.hyperliquid.xyz/info",
                   {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": 0, "endTime": now}})
    rows = [[int(c["t"]), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]), float(c["v"])] for c in d]
    # drop the still-open final candle
    return rows[:-1] if rows else rows


def fetch_hl_funding(coin: str) -> list:
    """HL fundingHistory paginated. Rows: [ms, hourly_funding_rate]."""
    out, start = [], START_MS
    while True:
        d = _http_post("https://api.hyperliquid.xyz/info",
                       {"type": "fundingHistory", "coin": coin, "startTime": start})
        if not d:
            break
        out.extend([[int(r["time"]), float(r["fundingRate"])] for r in d])
        if len(d) < 500:
            break
        start = int(d[-1]["time"]) + 1
        _time.sleep(0.15)
    return out


def load_or_fetch(path: Path, fetch_fn, label: str, refresh=False) -> list:
    if path.exists() and not refresh:
        with open(path) as f:
            d = json.load(f)
        print(f"  cache hit {label}: {len(d['rows'])} rows")
        return d["rows"]
    print(f"  fetching {label} ...", flush=True)
    rows = fetch_fn()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"label": label, "fetched_utc": datetime.now(timezone.utc).isoformat(), "rows": rows}, f)
    print(f"  fetched {label}: {len(rows)} rows")
    return rows


def load_all_data(quick=False):
    candles, funding = {}, {}
    syms = ["BTC"] if quick else list(BINANCE_SYMBOLS) + HL_SYMBOLS
    for s in syms:
        if s in BINANCE_SYMBOLS:
            rows = load_or_fetch(CACHE_DIR / f"BINANCE_{BINANCE_SYMBOLS[s]}_1h.json",
                                 lambda s=s: fetch_binance_1h(BINANCE_SYMBOLS[s]), f"binance {s} 1h")
        else:
            rows = load_or_fetch(CACHE_DIR / f"HL_{s}_1h_full.json",
                                 lambda s=s: fetch_hl_1h(s), f"HL {s} 1h")
        if quick:
            rows = rows[-2000:]
        candles[s] = rows
    for c in (["BTC"] if quick else FUNDING_COINS):
        try:
            funding[c] = load_or_fetch(CACHE_DIR / f"HL_FUNDING_{c}.json",
                                       lambda c=c: fetch_hl_funding(c), f"HL funding {c}")
        except Exception as e:
            print(f"  funding {c} FAILED: {e}")
    return candles, funding


# ------------------------------------------------------------------ frames

def to_df(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["ms"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.drop_duplicates("ms").sort_values("ms").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


def closed_6h(df: pd.DataFrame) -> pd.DataFrame:
    d = df.set_index("time").resample("6h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return d.reset_index()


def closed_daily(df: pd.DataFrame) -> pd.DataFrame:
    d = df.set_index("time").resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return d.reset_index()


# ------------------------------------------------ mech regime, vectorized

def wilder_regime_series(df: pd.DataFrame):
    """Per-bar replication of llm/agents/mech_regime.compute_mech_regime.
    Exact Wilder recursion (SMA seed) over the FULL series; per-bar labels.
    Returns dict of numpy arrays aligned to df index: adx, di_p, di_m,
    atr_pct, atr_ptile, label (object array).
    """
    H = df["high"].to_numpy(float); L = df["low"].to_numpy(float); C = df["close"].to_numpy(float)
    m = len(C); n = 14
    tr = np.maximum(H[1:] - L[1:], np.maximum(np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])))
    up = H[1:] - H[:-1]; dn = L[:-1] - L[1:]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)

    def wilder_run(v):
        out = np.full(len(v), np.nan)
        if len(v) < n:
            return out
        s = v[:n].mean(); out[n - 1] = s
        for i in range(n, len(v)):
            s = (s * (n - 1) + v[i]) / n
            out[i] = s
        return out

    atr = wilder_run(tr); spdm = wilder_run(pdm); sndm = wilder_run(ndm)
    with np.errstate(divide="ignore", invalid="ignore"):
        dip = 100.0 * spdm / atr
        dim = 100.0 * sndm / atr
        den = dip + dim
        dx = np.where(den > 0, 100.0 * np.abs(dip - dim) / den, 0.0)
    dx[np.isnan(dip) | np.isnan(dim)] = np.nan

    adx = np.full(len(tr), np.nan)
    valid = np.where(~np.isnan(dx))[0]
    if len(valid):
        first = valid[0]
        if len(tr) - first >= n:
            a = np.nanmean(dx[first:first + n]); adx[first + n - 1] = a
            for i in range(first + n, len(tr)):
                a = (a * (n - 1) + dx[i]) / n
                adx[i] = a

    # align to bar index: tr[j] is bar j+1.
    adx_b = np.full(m, np.nan); dip_b = np.full(m, np.nan); dim_b = np.full(m, np.nan)
    adx_b[1:] = adx; dip_b[1:] = dip; dim_b[1:] = dim
    # mech: atr list has len m-1 (over tr); atr_pct[i] = atr[i-1] / C[i] for i in 1..m-1
    atr_pct = np.full(m, np.nan)
    for i in range(1, m):
        a = atr[i - 1] if (i - 1) < len(atr) else np.nan
        if not np.isnan(a) and C[i] > 0:
            atr_pct[i] = a / C[i]

    # trailing percentile, window 336 PAST values excluding current, min 100 samples
    ptile = np.full(m, np.nan)
    ap = atr_pct
    for i in range(1, m):
        lo = max(0, i - PTILE_WINDOW)
        past = ap[lo:i]
        past = past[~np.isnan(past)]
        if len(past) >= 100 and not np.isnan(ap[i]):
            ptile[i] = float((past <= ap[i]).sum()) / len(past)

    label = np.array([None] * m, dtype=object)
    for i in range(m):
        if np.isnan(adx_b[i]):
            continue
        if not np.isnan(ptile[i]) and ptile[i] >= HIGH_VOL_PTILE:
            label[i] = "high_volatility"
        elif adx_b[i] >= TRENDING_ADX:
            label[i] = "trending_bull" if (dip_b[i] if not np.isnan(dip_b[i]) else 0) >= (dim_b[i] if not np.isnan(dim_b[i]) else 0) else "trending_bear"
        else:
            label[i] = "ranging"
    return {"adx": adx_b, "di_p": dip_b, "di_m": dim_b, "atr_pct": atr_pct,
            "atr_ptile": ptile, "label": label}


def validate_vectorization(df, vec, n_samples=40, window=800, seed=7):
    """Call the ACTUAL compute_mech_regime on trailing windows at sampled bars;
    report label agreement. Differences come from Wilder warm-up inside a
    finite window vs full-history recursion — honest to quantify."""
    rng = np.random.default_rng(seed)
    m = len(df)
    idxs = rng.choice(np.arange(window, m - 1), size=min(n_samples, max(0, m - window - 1)), replace=False)
    agree = tot = 0
    for i in idxs:
        sl = df.iloc[i - window + 1:i + 1]
        r = compute_mech_regime(sl[["time", "open", "high", "low", "close", "volume"]])
        if r is None or vec["label"][i] is None:
            continue
        tot += 1
        if r["label"] == vec["label"][i]:
            agree += 1
    return (agree / tot if tot else float("nan")), tot


# ------------------------------------------------------------- strategies

def build_strategies():
    symbols = DEFAULT_SYMBOLS
    tmp = tempfile.mkdtemp(prefix="wagmi_sv_cs_")
    rt = RegimeTrendStrategy(symbols)
    mc = MonteCarloZonesStrategy(symbols)
    cs = ConfidenceScorerStrategy(symbols, data_dir=tmp, backtest_mode=True)
    # backtest hygiene: no signal-log disk writes, no live WR feedback
    cs._log_signal = lambda *a, **k: None
    cs.evaluate_past_signals = lambda *a, **k: None
    mt = MultiTierQualityStrategy(symbols)
    return rt, mc, cs, mt


def run_strategies_for_symbol(sym, df, progress_every=4000):
    """Walk the 1h series bar by bar; call the REAL strategy code on trailing
    windows (no lookahead: only bars <= t are visible; last bar = last CLOSED).
    Returns list of signal events + per-bar confluence votes."""
    rt, mc, cs, mt = build_strategies()
    m = len(df)
    times = df["time"]
    hours = times.dt.hour.to_numpy()
    dates = times.dt.date.to_numpy()

    # strategies see ONLY raw OHLCV+time — context/forward-return columns can never leak
    base = df[["time", "open", "high", "low", "close", "volume"]]
    events = []
    mc_signal_by_date = {}   # eval date -> (side, conf)  (applies to NEXT day's bars)

    t0 = _time.time()
    for i in range(W1H, m):
        sl1 = base.iloc[i - W1H + 1:i + 1]
        # 6h frame: resample the slice (last bucket may be partial — same info a
        # live scan has intra-6h; built only from bars <= t, no lookahead)
        df6 = closed_6h(sl1).tail(W6H).reset_index(drop=True)
        data = {"1h": sl1.reset_index(drop=True), "6h": df6}

        for strat in (rt, cs, mt):
            try:
                sig = strat.evaluate(sym, data)
            except Exception:
                sig = None
            if sig is not None:
                events.append({"symbol": sym, "i": i, "strategy": strat.name,
                               "side": sig.side, "conf": float(sig.confidence),
                               "valid": bool(sig.is_valid)})

        # monte_carlo: once per completed UTC day (bar opening 23:00 closes the day)
        if hours[i] == 23:
            lo = max(0, i - WDAILY * 24)
            dfd = closed_daily(base.iloc[lo:i + 1]).tail(WDAILY).reset_index(drop=True)
            if len(dfd) >= 60:
                np.random.seed(i)  # deterministic MC
                try:
                    sig = mc.evaluate(sym, {"daily": dfd})
                except Exception:
                    sig = None
                if sig is not None:
                    events.append({"symbol": sym, "i": i, "strategy": "monte_carlo_zones",
                                   "side": sig.side, "conf": float(sig.confidence),
                                   "valid": bool(sig.is_valid)})
                    mc_signal_by_date[dates[i]] = (sig.side, float(sig.confidence))

        if progress_every and (i - W1H) % progress_every == 0:
            el = _time.time() - t0
            print(f"    {sym} bar {i}/{m}  events={len(events)}  ({el:.0f}s)", flush=True)
    print(f"    {sym} done: {len(events)} strategy signal events in {_time.time()-t0:.0f}s", flush=True)
    return events, mc_signal_by_date


# ------------------------------------------------------------------ metrics

def tstat_mean(x, h):
    """t-stat of mean with effective n = n/h (overlap correction for h-bar fwd returns)."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    ne = max(3.0, n / max(1, h))
    sd = x.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float(x.mean() / (sd / math.sqrt(ne)))


def ic_t(ic, n, h):
    ne = max(4.0, n / max(1, h))
    if math.isnan(ic) or abs(ic) >= 1:
        return float("nan")
    return float(ic * math.sqrt(ne - 2) / math.sqrt(1 - ic * ic))


def bucket_stats(sub: pd.DataFrame, hcol: str, h: int):
    """sub needs: dir (+1/-1), fwd (signed already NO — raw fwd), conf, base_p."""
    fwd = sub[hcol].to_numpy(float)
    d = sub["dir"].to_numpy(float)
    ok = ~np.isnan(fwd)
    fwd, d = fwd[ok], d[ok]
    n = len(fwd)
    if n == 0:
        return None
    signed = d * fwd
    hit = float((signed > 0).mean())
    base = float(sub.loc[ok, "base_" + hcol].mean()) if ("base_" + hcol) in sub else float("nan")
    conf = sub.loc[ok, "conf"].to_numpy(float) if "conf" in sub else None
    ic = spearman(conf, signed) if conf is not None and n >= 10 and len(set(conf)) > 1 else float("nan")
    return {"n": n, "hit": hit, "base": base, "mean_bps": float(signed.mean() * 1e4),
            "t": tstat_mean(signed, h), "conf_ic": ic, "conf_ic_t": ic_t(ic, n, h) if not math.isnan(ic) else float("nan")}


def fmt(v, nd=2):
    if v is None or (isinstance(v, float) and (math.isnan(v))):
        return "—"
    return f"{v:.{nd}f}"


# ------------------------------------------------------------------ zigzag

def zigzag_pivots(close: np.ndarray, pct=0.05):
    """5% reversal zigzag. Returns list of (idx, 'low'|'high')."""
    piv = []
    last_ext_i, last_ext = 0, close[0]
    direction = 0  # +1 rising leg, -1 falling
    for i in range(1, len(close)):
        c = close[i]
        if direction >= 0:
            if c > last_ext:
                last_ext, last_ext_i = c, i
            if c < last_ext * (1 - pct):
                if direction != 0 or piv == []:
                    piv.append((last_ext_i, "high"))
                direction = -1
                last_ext, last_ext_i = c, i
        if direction <= 0:
            if c < last_ext:
                last_ext, last_ext_i = c, i
            if c > last_ext * (1 + pct):
                piv.append((last_ext_i, "low"))
                direction = 1
                last_ext, last_ext_i = c, i
    return piv


# ==================================================================== MAIN

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--fetch-only", action="store_true")
    args = ap.parse_args()

    t_start = _time.time()
    print("== SENSOR VALIDATION BACKTEST ==")
    print("[1/6] data")
    candles, funding_raw = load_all_data(quick=args.quick)
    if args.fetch_only:
        return

    frames = {s: to_df(rows) for s, rows in candles.items()}
    fund = {}
    for c, rows in funding_raw.items():
        f = pd.DataFrame(rows, columns=["ms", "rate"])
        f["time"] = pd.to_datetime(f["ms"], unit="ms", utc=True).dt.tz_localize(None).dt.floor("h")
        f = f.drop_duplicates("time").set_index("time")["rate"]
        fund[c] = f

    print("[2/6] per-bar mechanical context (vectorized Wilder, validated vs real fn)")
    ctx = {}
    vec_agreement = {}
    for s, df in frames.items():
        vec = wilder_regime_series(df)
        ag, nt = validate_vectorization(df, vec) if len(df) > 900 else (float("nan"), 0)
        vec_agreement[s] = (ag, nt)
        # forward returns
        c = df["close"]
        add = {"label": vec["label"], "adx": vec["adx"], "atr_ptile": vec["atr_ptile"],
               "atr_pct": vec["atr_pct"], "di_p": vec["di_p"], "di_m": vec["di_m"]}
        for hn, h in HORIZONS.items():
            add[f"fwd{hn}"] = (c.shift(-h) / c - 1.0).to_numpy()
        add["past24"] = (c / c.shift(24) - 1.0).to_numpy()
        # realized fwd 24h vol (std of next 24 1h rets)
        r1 = c.pct_change()
        add["rv_fwd24"] = r1.rolling(24).std().shift(-24).to_numpy()
        add["ema20"] = c.ewm(span=20, adjust=False).mean().to_numpy()
        add["ema50"] = c.ewm(span=50, adjust=False).mean().to_numpy()
        # funding: hourly rate + trailing 8h sum, as-of bar open time
        fr = fund.get(s)
        if fr is not None:
            aligned = fr.reindex(df["time"]).to_numpy()
            add["fund_1h"] = aligned
            add["fund_8h"] = pd.Series(aligned).rolling(8, min_periods=4).sum().to_numpy()
        else:
            add["fund_1h"] = np.full(len(df), np.nan)
            add["fund_8h"] = np.full(len(df), np.nan)
        for k, v in add.items():
            df[k] = v
        df["year"] = df["time"].dt.year
        df["regime"] = [
            ("trend" if lb in ("trending_bull", "trending_bear") else
             "high_vol" if lb == "high_volatility" else
             "range" if lb == "ranging" else "unknown") for lb in vec["label"]]
        ctx[s] = df
        print(f"  {s}: {len(df)} bars {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}"
              f" | mech-vec vs real fn label agreement {fmt(ag*100 if ag==ag else float('nan'),1)}% (n={nt})")

    print("[3/6] strategy replay (REAL strategy code, trailing windows)")
    all_events = []
    mc_by_symdate = {}
    for s, df in ctx.items():
        ev, mcmap = run_strategies_for_symbol(s, df)
        all_events.extend(ev)
        mc_by_symdate[s] = mcmap
    events = pd.DataFrame(all_events)

    # attach outcomes/buckets to events
    def attach(evdf):
        rows = []
        for s, g in evdf.groupby("symbol"):
            df = ctx[s]
            ii = g["i"].to_numpy()
            g = g.copy()
            g["time"] = df["time"].to_numpy()[ii]
            g["year"] = df["year"].to_numpy()[ii]
            g["regime"] = df["regime"].to_numpy()[ii]
            g["dir"] = np.where(g["side"].to_numpy() == "BUY", 1.0, -1.0)
            for hn in HORIZONS:
                g[f"fwd{hn}"] = df[f"fwd{hn}"].to_numpy()[ii]
            rows.append(g)
        return pd.concat(rows, ignore_index=True) if rows else evdf

    events = attach(events)

    # base rates per (symbol, year, regime, horizon): P(fwd>0)
    base_tbl = {}
    for s, df in ctx.items():
        for hn in HORIZONS:
            f = df[f"fwd{hn}"].to_numpy()
            for (y, r), g in df.groupby(["year", "regime"]):
                idx = g.index.to_numpy()
                fv = f[idx]; fv = fv[~np.isnan(fv)]
                if len(fv):
                    base_tbl[(s, y, r, hn)] = float((fv > 0).mean())
    for hn in HORIZONS:
        def _b(row, hn=hn):
            p = base_tbl.get((row["symbol"], row["year"], row["regime"], hn), np.nan)
            if isinstance(p, float) and not math.isnan(p):
                return p if row["dir"] > 0 else 1.0 - p
            return np.nan
        if len(events):
            events["base_" + f"fwd{hn}"] = events.apply(_b, axis=1)

    print(f"  total strategy signal events: {len(events)}")

    # ---------------- confluence reconstruction
    print("[4/6] confluence + per-bar sensors")
    conf_rows = []
    if len(events):
        hourly = events[events["strategy"] != "monte_carlo_zones"]
        by_key = {}
        for _, e in hourly.iterrows():
            by_key.setdefault((e["symbol"], e["i"]), []).append((e["side"], e["strategy"]))
        for s, df in ctx.items():
            dates = df["time"].dt.date.to_numpy()
            mcmap = mc_by_symdate.get(s, {})
            # mc signal from day D applies to bars of day D+1
            mc_next = {}
            for d, sg in mcmap.items():
                mc_next[d + pd.Timedelta(days=1).to_pytimedelta()] = sg
            for (sym, i), votes in [(k, v) for k, v in by_key.items() if k[0] == s]:
                v = list(votes)
                mcsig = mc_next.get(dates[i])
                if mcsig:
                    v.append((mcsig[0], "monte_carlo_zones"))
                buys = sum(1 for side, _ in v if side == "BUY")
                sells = len(v) - buys
                if buys == sells:
                    continue  # conflicted tie — skip (rare, noted)
                side = "BUY" if buys > sells else "SELL"
                conf_rows.append({"symbol": s, "i": i, "side": side,
                                  "num_agree": max(buys, sells), "num_votes": len(v)})
    confl = pd.DataFrame(conf_rows)
    if len(confl):
        confl["strategy"] = "confluence"
        confl["conf"] = confl["num_agree"].astype(float)
        confl = attach(confl)
        for hn in HORIZONS:
            def _b2(row, hn=hn):
                p = base_tbl.get((row["symbol"], row["year"], row["regime"], hn), np.nan)
                if isinstance(p, float) and not math.isnan(p):
                    return p if row["dir"] > 0 else 1.0 - p
                return np.nan
            confl["base_" + f"fwd{hn}"] = confl.apply(_b2, axis=1)

    # ---------------- per-bar context sensor panels
    panels = []   # rows: sensor, horizon, slice_type, slice, n, hit, base, mean_bps, t, ic, ic_t
    def add_panel(sensor, hn, stype, sname, st):
        if st:
            panels.append(dict(sensor=sensor, horizon=hn, slice_type=stype, slice=str(sname), **st))

    def perbar_direction_sensor(name, dir_col_fn, conf_col=None):
        """dir_col_fn(df) -> +1/-1/0 array. Measures signed fwd by state."""
        for hn, h in HORIZONS.items():
            pooled = []
            for s, df in ctx.items():
                d = dir_col_fn(df)
                fwd = df[f"fwd{hn}"].to_numpy()
                ok = (d != 0) & ~np.isnan(fwd) & (df["regime"].to_numpy() != "unknown")
                sub = pd.DataFrame({"dir": d[ok], f"fwd{hn}": fwd[ok],
                                    "year": df["year"].to_numpy()[ok],
                                    "regime": df["regime"].to_numpy()[ok],
                                    "symbol": s})
                sub["conf"] = (conf_col(df)[ok] if conf_col is not None else np.abs(sub["dir"]))
                sub["base_" + f"fwd{hn}"] = [
                    (base_tbl.get((s, y, r, hn), np.nan) if dd > 0 else 1 - base_tbl.get((s, y, r, hn), np.nan))
                    for y, r, dd in zip(sub["year"], sub["regime"], sub["dir"])]
                pooled.append(sub)
            if not pooled:
                continue
            P = pd.concat(pooled, ignore_index=True)
            add_panel(name, hn, "ALL", "pooled", bucket_stats(P, f"fwd{hn}", h))
            if hn == "24h":
                for y, g in P.groupby("year"):
                    add_panel(name, hn, "year", y, bucket_stats(g, f"fwd{hn}", h))
                for r, g in P.groupby("regime"):
                    add_panel(name, hn, "regime", r, bucket_stats(g, f"fwd{hn}", h))

    # EMA20/50 cross state
    perbar_direction_sensor("ema20_50_state",
                            lambda df: np.sign(df["ema20"].to_numpy() - df["ema50"].to_numpy()))
    # mech regime directional read (trending_bull=+1, trending_bear=-1)
    perbar_direction_sensor("mech_regime_dir",
                            lambda df: np.where(df["label"].to_numpy() == "trending_bull", 1.0,
                                        np.where(df["label"].to_numpy() == "trending_bear", -1.0, 0.0)))
    # funding (contrarian orientation would be negative IC on raw): use dir = -sign(fund_8h)
    perbar_direction_sensor("funding_8h_contrarian",
                            lambda df: -np.sign(np.nan_to_num(df["fund_8h"].to_numpy())),
                            conf_col=lambda df: np.abs(np.nan_to_num(df["fund_8h"].to_numpy())))

    # continuous ICs for vol-type sensors (per THE_STANDARD: honest orientation —
    # ATR ptile & ADX are measured against future VOL, and also against direction
    # to prove they are NOT directional sensors)
    cont_rows = []
    for name, col, target in [("atr_ptile", "atr_ptile", "rv_fwd24"),
                              ("adx", "adx", "rv_fwd24"),
                              ("atr_ptile_vs_dir", "atr_ptile", "fwd24h"),
                              ("adx_vs_dir", "adx", "fwd24h"),
                              ("fund8h_vs_dir_raw", "fund_8h", "fwd24h")]:
        pooled_x, pooled_y, per_year = [], [], {}
        for s, df in ctx.items():
            x = df[col].to_numpy(float); y = df[target].to_numpy(float)
            ok = ~np.isnan(x) & ~np.isnan(y)
            pooled_x.append(x[ok]); pooled_y.append(y[ok])
            for yy in sorted(df["year"].unique()):
                mask = ok & (df["year"].to_numpy() == yy)
                if mask.sum() >= 100:
                    per_year.setdefault(yy, [[], []])
                    per_year[yy][0].append(x[mask]); per_year[yy][1].append(y[mask])
        X = np.concatenate(pooled_x); Y = np.concatenate(pooled_y)
        ic = spearman(X, Y); n = len(X)
        yr_ics = {yy: spearman(np.concatenate(a), np.concatenate(b)) for yy, (a, b) in per_year.items()}
        cont_rows.append({"sensor": name, "target": target, "n": n, "ic": ic,
                          "t": ic_t(ic, n, 24), "yr_ics": yr_ics})

    # ADX band continuation table (24h)
    adx_band_rows = []
    for band, lo, hi in [("<20", 0, 20), ("20-25", 20, 25), ("25-35", 25, 35), (">35", 35, 999)]:
        hits, tot = [], 0
        for s, df in ctx.items():
            a = df["adx"].to_numpy(); p24 = df["past24"].to_numpy(); f24 = df["fwd24h"].to_numpy()
            ok = ~np.isnan(a) & ~np.isnan(p24) & ~np.isnan(f24) & (a >= lo) & (a < hi) & (p24 != 0)
            hits.append((np.sign(p24[ok]) == np.sign(f24[ok])).astype(float))
        h = np.concatenate(hits)
        adx_band_rows.append({"band": band, "n": len(h), "cont_rate": float(h.mean()) if len(h) else float("nan"),
                              "t": tstat_mean(h - 0.5, 24) if len(h) else float("nan")})

    # ---------------- regime nowcast label accuracy + transition lag
    print("[5/6] regime nowcast accuracy + transition timing")
    regime_acc = []
    lag_stats = {}
    for s, df in ctx.items():
        lb = df["label"].to_numpy(); f24 = df["fwd24h"].to_numpy()
        rv = df["rv_fwd24"].to_numpy(); a24 = np.abs(f24)
        med_rv = np.nanmedian(rv); med_a24 = np.nanmedian(a24)
        checks = {
            "trending_bull->fwd24>0": (lb == "trending_bull", f24 > 0, float(np.nanmean(f24[~np.isnan(f24)] > 0))),
            "trending_bear->fwd24<0": (lb == "trending_bear", f24 < 0, float(np.nanmean(f24[~np.isnan(f24)] < 0))),
            "high_vol->rv_fwd24>med": (lb == "high_volatility", rv > med_rv, 0.5),
            "ranging->|fwd24|<med": (lb == "ranging", a24 < med_a24, 0.5),
        }
        for name, (mask, cond, base) in checks.items():
            ok = mask & ~np.isnan(f24) & ~np.isnan(rv)
            n = int(ok.sum())
            if n:
                regime_acc.append({"symbol": s, "check": name, "n": n,
                                   "acc": float(cond[ok].mean()), "base": base})
        # transition lag: zigzag 5% pivots -> first matching trending flag
        close = df["close"].to_numpy()
        piv = zigzag_pivots(close, 0.05)
        lags, missed = [], 0
        for k, (pi, kind) in enumerate(piv[:-1]):
            nxt = piv[k + 1][0]
            want = "trending_bull" if kind == "low" else "trending_bear"
            seg = lb[pi:nxt]
            w = np.where(seg == want)[0]
            if len(w):
                lags.append(int(w[0]))
            else:
                missed += 1
        if lags or missed:
            lag_stats[s] = {"legs": len(lags) + missed, "flagged": len(lags),
                            "median_lag_h": float(np.median(lags)) if lags else float("nan"),
                            "p75_lag_h": float(np.percentile(lags, 75)) if lags else float("nan")}

    # ---------------- strategy + confluence panels
    strat_panels = []
    def add_strat_panel(dfev, name):
        for hn, h in HORIZONS.items():
            st = bucket_stats(dfev, f"fwd{hn}", h)
            if st:
                strat_panels.append(dict(sensor=name, horizon=hn, slice_type="ALL", slice="pooled", **st))
            if hn == "24h":
                for y, g in dfev.groupby("year"):
                    st = bucket_stats(g, f"fwd{hn}", h)
                    if st:
                        strat_panels.append(dict(sensor=name, horizon=hn, slice_type="year", slice=str(y), **st))
                for r, g in dfev.groupby("regime"):
                    st = bucket_stats(g, f"fwd{hn}", h)
                    if st:
                        strat_panels.append(dict(sensor=name, horizon=hn, slice_type="regime", slice=str(r), **st))

    if len(events):
        for name, g in events.groupby("strategy"):
            add_strat_panel(g, name)
    if len(confl):
        for na, g in confl.groupby("num_agree"):
            add_strat_panel(g.assign(conf=g["num_agree"]), f"confluence_agree={int(na)}")
        add_strat_panel(confl[confl["num_agree"] >= 2], "confluence_agree>=2")

    # ---------------- cross-sensor correlation (redundancy)
    corr_frames = []
    for s, df in ctx.items():
        n = len(df)
        cols = {
            "ema_state": np.sign(df["ema20"].to_numpy() - df["ema50"].to_numpy()),
            "mech_dir": np.where(df["label"].to_numpy() == "trending_bull", 1.0,
                         np.where(df["label"].to_numpy() == "trending_bear", -1.0, 0.0)),
            "adx": df["adx"].to_numpy(),
            "atr_ptile": df["atr_ptile"].to_numpy(),
            "fund_8h": df["fund_8h"].to_numpy(),
        }
        for st in ("regime_trend", "confidence_scorer", "multi_tier_quality", "monte_carlo_zones"):
            v = np.zeros(n)
            if len(events):
                g = events[(events["symbol"] == s) & (events["strategy"] == st)]
                v[g["i"].to_numpy()] = g["dir"].to_numpy()
            cols["sig_" + st] = v
        corr_frames.append(pd.DataFrame(cols))
    corr_df = pd.concat(corr_frames, ignore_index=True)
    corr = corr_df.corr(method="spearman")

    # ---------------- verdicts
    print("[6/6] verdicts + report")

    def verdict_for(name, pooled_by_h, year_rows, regime_rows, metric="t"):
        """KEEP / WEIGHT-DOWN / MUTE per THE_STANDARD; artifact rule applied."""
        t24 = pooled_by_h.get("24h", {}).get(metric, float("nan"))
        t6 = pooled_by_h.get("6h", {}).get(metric, float("nan"))
        best_t = max([abs(x) for x in (t24, t6) if x == x] or [0])
        yr = [(r["slice"], r["mean_bps"], r["n"]) for r in year_rows if r["n"] >= 30]
        sign24 = math.copysign(1, pooled_by_h.get("24h", {}).get("mean_bps", 0) or 1)
        agree_years = sum(1 for _, mb, _ in yr if math.copysign(1, mb) == sign24)
        artifact = False
        if len(yr) >= 2 and agree_years <= len(yr) // 2:
            artifact = True
        # concentration: does one year hold >70% of the edge (n-weighted |mean|)?
        if yr:
            contrib = [abs(mb) * nn for _, mb, nn in yr]
            if sum(contrib) > 0 and max(contrib) / sum(contrib) > 0.7 and len(yr) >= 3:
                artifact = True
        if best_t >= 2.5 and not artifact and (len(yr) < 2 or agree_years >= max(2, len(yr) - 1)):
            v = "KEEP"
        elif best_t >= 1.5:
            v = "WEIGHT-DOWN" + (" (ARTIFACT-FLAG)" if artifact else "")
        else:
            v = "MUTE-FROM-CONTEXT"
            if artifact:
                v += " (ARTIFACT-FLAG)"
        return v, artifact, agree_years, len(yr)

    all_panels = strat_panels + panels
    sensors = sorted(set(p["sensor"] for p in all_panels))
    verdicts = {}
    for sn in sensors:
        rows = [p for p in all_panels if p["sensor"] == sn]
        pooled = {r["horizon"]: r for r in rows if r["slice_type"] == "ALL"}
        yrows = [r for r in rows if r["slice_type"] == "year"]
        rrows = [r for r in rows if r["slice_type"] == "regime"]
        verdicts[sn] = verdict_for(sn, pooled, yrows, rrows)

    # continuous sensors verdicts (vol targets)
    cont_verdicts = {}
    for r in cont_rows:
        yr_ics = r["yr_ics"]
        sign0 = math.copysign(1, r["ic"]) if r["ic"] == r["ic"] and r["ic"] != 0 else 1
        agree = sum(1 for v in yr_ics.values() if v == v and math.copysign(1, v) == sign0)
        tot = sum(1 for v in yr_ics.values() if v == v)
        t = r["t"]
        if abs(t) >= 2.5 and agree >= max(2, tot - 1):
            v = "KEEP"
        elif abs(t) >= 1.5:
            v = "WEIGHT-DOWN"
        else:
            v = "MUTE-FROM-CONTEXT"
        cont_verdicts[r["sensor"]] = (v, agree, tot)

    runtime_s = _time.time() - t_start
    total_bars = sum(len(df) for df in ctx.values())

    # ================================================================ report
    lines = []
    W = lines.append
    W("# SENSOR VALIDATION — the mechanical/diagnostic layer vs years of free data")
    W("")
    W(f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | runtime {runtime_s/60:.1f} min | "
      f"THE_STANDARD v1.4 | ZERO LLM calls (pure computation)")
    W(f"Harness: `bot/tools/research/sensor_validation.py` (imports the REAL strategy code + "
      f"`llm/agents/mech_regime.py`, read-only). Candle cache: `bot/tools/research/candle_cache/`.")
    W("")
    W("## Data")
    W("")
    W("| symbol | source | bars (1h) | span |")
    W("|---|---|---|---|")
    for s, df in ctx.items():
        src = "Binance spot (data-api.binance.vision)" if s in BINANCE_SYMBOLS else "Hyperliquid candleSnapshot"
        W(f"| {s} | {src} | {len(df)} | {df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()} |")
    W(f"| funding | Hyperliquid fundingHistory (hourly) | "
      f"{sum(len(v) for v in fund.values())} records | {len(fund)} coins |")
    W("")
    W(f"Total n = **{total_bars} symbol-bars**; strategy signal events = **{len(events)}**; "
      f"confluence bars = **{len(confl)}**.")
    W("")
    W("### Honesty ledger (degradations & method notes)")
    W("- **Binance direct + fapi are geo-blocked (HTTP 451) from this box** → spot klines via the official "
      "data-api.binance.vision mirror; **Binance funding history unavailable** → HL fundingHistory used instead "
      "(hourly, the venue the bot actually trades — arguably more relevant, but it is NOT Binance basis).")
    W("- **HYPE**: HL API retains only ~5000 1h bars → HYPE covers ~7 months, not years. All HYPE cells are "
      "short-era by construction.")
    W("- **5m unavailable historically** → `multi_tier_quality` runs 1h+6h, which is exactly its ported "
      "`get_required_timeframes()` — no degradation vs live. `regime_trend` builds its 16h HTF from 1h (same as live). "
      "`monte_carlo_zones` runs on Binance/HL UTC daily resampled from 1h; live uses CoinGecko daily — minor source drift.")
    W("- `confidence_scorer` historical-WR feedback is DISABLED (backtest_mode=True, per its own cold-start "
      "guard) and its signal-log disk writes are stubbed. Live confidence may differ by the ±10 hist-WR adjustment.")
    W("- 6h/daily frames are resampled from 1h with the final bucket PARTIAL (same information a live intra-bucket "
      "scan has). No lookahead anywhere: bar i sees only bars ≤ i; outcomes are forward returns from bar i close.")
    W(f"- Mech-regime vectorization validated against the REAL `compute_mech_regime` on sampled 800-bar trailing "
      f"windows: label agreement " + ", ".join(f"{s} {fmt((a or float('nan'))*100 if a==a else float('nan'),1)}% (n={nt})" for s, (a, nt) in vec_agreement.items()) + ". "
      "Residual disagreement = Wilder warm-up inside a finite window; treated as measurement noise.")
    W("- **No fitting anywhere** — every sensor is fixed code measured as-is (pure measurement, nothing in-sample). "
      "BUT: several thresholds inside the strategies (ADX 22, conf floors) were historically tuned on 2024-26 data, "
      "so year-splits are era-stability checks, not true out-of-sample for those constants.")
    W("- t-stats use effective n = n/horizon (overlap correction for autocorrelated forward windows); event "
      "sensors that re-fire on consecutive bars are still somewhat overstated — treat |t| near 2 as marginal.")
    W("- Hit rates are vs the SAME-bucket directional base rate (symbol × year × regime), shown alongside.")
    W("- Fees/slippage excluded deliberately: this validates INFORMATION content of sensors, not tradability.")
    W("")

    W("## 1. Strategy sensors (real code, every closed 1h bar)")
    W("")
    W("`hit` = P(direction correct at horizon); `base` = same-direction base rate in the same "
      "symbol/year/regime bucket; `mean_bps` = mean direction-signed fwd return; `conf_IC` = Spearman rank-IC "
      "of the strategy's OWN confidence value vs signed outcome.")
    W("")
    def panel_table(rows):
        W("| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |")
        W("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            edge = (r["hit"] - r["base"]) if r["base"] == r["base"] else float("nan")
            W(f"| {r['sensor']} | {r['horizon']} | {r['slice']} | {r['n']} | {fmt(r['hit'],3)} | "
              f"{fmt(r['base'],3)} | {fmt(edge*100 if edge==edge else float('nan'),1)}pp | {fmt(r['mean_bps'],1)} | "
              f"{fmt(r['t'],2)} | {fmt(r['conf_ic'],3)} | {fmt(r['conf_ic_t'],2)} |")
        W("")

    for sn in [s for s in sensors if not s.startswith("confluence") and s in
               ("regime_trend", "confidence_scorer", "multi_tier_quality", "monte_carlo_zones")]:
        rows = [p for p in all_panels if p["sensor"] == sn]
        W(f"### {sn} — verdict: **{verdicts[sn][0]}**")
        W("")
        panel_table([r for r in rows if r["slice_type"] == "ALL"])
        W("Era-split (24h horizon):")
        W("")
        panel_table([r for r in rows if r["slice_type"] == "year"])
        W("Regime-split (24h horizon):")
        W("")
        panel_table([r for r in rows if r["slice_type"] == "regime"])

    W("## 2. Vote confluence (reconstructed ensemble agreement)")
    W("")
    W("Votes at each bar = hourly strategy signals at that bar + monte_carlo's most recent daily signal "
      "(applies to the following day). Ties (1-1) skipped. Question: does num_agree rank outcomes?")
    W("")
    for sn in [s for s in sensors if s.startswith("confluence")]:
        rows = [p for p in all_panels if p["sensor"] == sn]
        W(f"### {sn} — verdict: **{verdicts[sn][0]}**")
        W("")
        panel_table([r for r in rows if r["slice_type"] == "ALL"])
        yr = [r for r in rows if r["slice_type"] == "year"]
        if yr:
            W("Era-split (24h):")
            W("")
            panel_table(yr)

    W("## 3. Regime nowcast (mech_regime.py — the RQ10 hybrid)")
    W("")
    W("| symbol | check | n | accuracy | base | edge |")
    W("|---|---|---|---|---|---|")
    for r in regime_acc:
        W(f"| {r['symbol']} | {r['check']} | {r['n']} | {fmt(r['acc'],3)} | {fmt(r['base'],3)} | "
          f"{fmt((r['acc']-r['base'])*100,1)}pp |")
    W("")
    W("Transition timing (5% zigzag legs → first matching trending_bull/bear flag):")
    W("")
    W("| symbol | legs | flagged | median lag (h) | p75 lag (h) |")
    W("|---|---|---|---|---|")
    for s, r in lag_stats.items():
        W(f"| {s} | {r['legs']} | {r['flagged']} ({r['flagged']/max(1,r['legs'])*100:.0f}%) | "
          f"{fmt(r['median_lag_h'],0)} | {fmt(r['p75_lag_h'],0)} |")
    W("")

    W("## 4. Classic context indicators (what the prompts cite)")
    W("")
    W("Directional state sensors (same table format as strategies):")
    W("")
    for sn in ("ema20_50_state", "mech_regime_dir", "funding_8h_contrarian"):
        if sn in verdicts:
            rows = [p for p in all_panels if p["sensor"] == sn]
            W(f"### {sn} — verdict: **{verdicts[sn][0]}**")
            W("")
            panel_table([r for r in rows if r["slice_type"] == "ALL"])
            yr = [r for r in rows if r["slice_type"] == "year"]
            if yr:
                W("Era-split (24h):")
                W("")
                panel_table(yr)
            rr = [r for r in rows if r["slice_type"] == "regime"]
            if rr:
                W("Regime-split (24h):")
                W("")
                panel_table(rr)

    W("### Continuous ICs (honest orientation: vol sensors scored vs future VOL, "
      "and vs direction to prove they are NOT directional)")
    W("")
    W("| sensor | target | n | IC | t (n_eff=n/24) | per-year ICs | verdict |")
    W("|---|---|---|---|---|---|---|")
    for r in cont_rows:
        ys = ", ".join(f"{y}:{fmt(v,2)}" for y, v in sorted(r["yr_ics"].items()))
        v = cont_verdicts[r["sensor"]][0]
        W(f"| {r['sensor']} | {r['target']} | {r['n']} | {fmt(r['ic'],3)} | {fmt(r['t'],1)} | {ys} | {v} |")
    W("")
    W("ADX band → 24h trend continuation (P(sign of next 24h == sign of past 24h)); coin-flip base 0.500:")
    W("")
    W("| ADX band | n | continuation rate | t vs 0.5 |")
    W("|---|---|---|---|")
    for r in adx_band_rows:
        W(f"| {r['band']} | {r['n']} | {fmt(r['cont_rate'],3)} | {fmt(r['t'],2)} |")
    W("")

    W("## 5. Cross-sensor redundancy (Spearman, pooled bars; signal columns 0-filled off-signal)")
    W("")
    cols = list(corr.columns)
    W("| | " + " | ".join(cols) + " |")
    W("|---|" + "|".join(["---"] * len(cols)) + "|")
    for c in cols:
        W(f"| {c} | " + " | ".join(fmt(corr.loc[c, c2], 2) for c2 in cols) + " |")
    W("")
    W("Note: 0-filling sparse signal columns deflates their correlations; read the sign/magnitude "
      "of the dense-column block (ema_state/mech_dir/adx/atr_ptile/fund_8h) as the redundancy map.")
    W("")

    W("## GRAND VERDICT — the validated sensor panel")
    W("")
    ranked = []
    for sn in sensors:
        p24 = next((p for p in all_panels if p["sensor"] == sn and p["slice_type"] == "ALL" and p["horizon"] == "24h"), None)
        if p24:
            ranked.append((sn, p24["t"] if p24["t"] == p24["t"] else 0, p24["n"], p24["mean_bps"], verdicts[sn][0]))
    ranked.sort(key=lambda x: -abs(x[1]))
    W("| rank | sensor | 24h t | n | mean_bps | verdict |")
    W("|---|---|---|---|---|---|")
    for k, (sn, t, n, mb, v) in enumerate(ranked, 1):
        W(f"| {k} | {sn} | {fmt(t,2)} | {n} | {fmt(mb,1)} | **{v}** |")
    W("")
    for r in cont_rows:
        if r["sensor"] in ("atr_ptile", "adx"):
            W(f"- Vol sensor `{r['sensor']}` vs future realized vol: IC {fmt(r['ic'],2)} (t {fmt(r['t'],1)}) — "
              f"{cont_verdicts[r['sensor']][0]}.")
    W("")
    W("Per THE_STANDARD §1, every MUTE verdict above is a WIN: a sensor with no information stops "
      "spending prompt tokens and stops steering the LLM. Log these into RESEARCH_AGENDA ANSWERED.")
    W("")
    W(f"_Total runtime {runtime_s/60:.1f} min; {total_bars} bars × 4 strategies + per-bar context panel; "
      f"zero LLM calls._")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport written: {REPORT_PATH}")
    print(f"runtime: {runtime_s/60:.1f} min | bars {total_bars} | events {len(events)} | confluence {len(confl)}")
    # terse console verdicts
    for sn, t, n, mb, v in ranked:
        print(f"  {sn:28s} t24={t:+.2f} n={n:6d} mean={mb:+.1f}bps  {v}")


if __name__ == "__main__":
    main()
