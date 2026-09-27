#!/usr/bin/env python
"""
Mover-Scanner Follow-Through / Fade Test - mover_followthrough_test.py
=============================================================================
STANDALONE, READ-ONLY analysis script. Tests whether tools/copilot/whats_moving.py
(the "What's Moving" attention scanner) carries any measurable FORWARD
information, or whether its flags are noise dressed as attention-direction.

DOES NOT import copilot.py, whats_moving.py, or any live-bot module. Per the
task constraint, the scanner's scoring/flag LOGIC is re-implemented here from
scratch (read from whats_moving.py, not imported) against the offline
longtail daily OHLC panel (data/longtail/ohlc/*_1d.csv, 25 coins, daily bars,
~2025-06-26 -> ~2026-07-31). This is a NEW analysis file; it does not touch
or depend on any file another agent may be editing.

WHAT'S FAITHFULLY REPRODUCED FROM whats_moving.py vs WHAT'S A DOCUMENTED PROXY
-----------------------------------------------------------------------------
Faithful (same constants, same formulas, read directly from the source file):
  - pct_24h              = (close_t - close_{t-1}) / close_{t-1} * 100
  - vol_ratio             = dayNtlVlm-equivalent (v*c) / MEDIAN of trailing
                            BASELINE_LOOKBACK_DAYS(=20) COMPLETED days'
                            notional volume, capped at VOL_SURGE_CAP(=15x),
                            None if < MIN_BASELINE_DAYS(=5) history
  - range_pos_pct         = position of close_t in the trailing 20-daily-bar
                            [low,high] range (0=range low, 100=range high),
                            using the same window whats_moving.py uses (does
                            NOT exclude the current bar, matching enrich_with_
                            candles' `daily` variable, only the volume
                            baseline drops the forming bar)
  - PARABOLIC flag        = |pct_24h| >= PARABOLIC_24H_PCT(40) AND
                            range_pos_pct >= 90 or <= 10 (PARABOLIC_RANGE_POS_PCT)
  - MIN_24H_VOLUME_USD    = $2,000,000 floor applied as in apply_liquidity_floor
  - ALERT_DECILE_FRACTION = 0.10 -> per-day cross-sectional top-decile = "flagged"
  - composite score       = |pct_24h| * vol_factor (vol_ratio if present else
                            1.0) -- this is compute_score() WITHOUT the two
                            factors longtail OHLC cannot supply (see below),
                            so it is momentum-x-volume-surge only.

Documented PROXIES / omissions (longtail OHLC has NO OI, funding, or
sub-daily 1h/4h history reliably spanning the whole panel per-coin at t):
  - OI floor (MIN_OI_USD) and "low OI - thin/rug-risk" flag: NO OI data
    exists in data/longtail/ohlc/*.csv (columns are open_time_ms, dt_utc_iso,
    o,h,l,c,v only). Cannot be reproduced. Substituted with a CROSS-SECTIONAL
    volume-thinness proxy (bottom quartile of that day's notional volume
    among the day's liquidity-floor survivors) - labeled "THIN(vol-proxy)"
    everywhere, never conflated with the real OI-based flag.
  - OI-confirmation score factor (oi_factor) and "high funding - crowded"
    flag: no OI-delta or funding-rate history in this panel -> both omitted
    entirely (neutral, oi_factor=1.0 equivalent), not faked.
  - roc_1h/roc_4h same-direction 1.25x momentum multiplier: requires intraday
    candles at the exact daily boundary for the full 13-month panel; not
    reliably available per-coin here. Omitted -> composite score is momentum
    x volume-surge only. This can only make the flagged set NOISIER
    (a fuzzier score), never better -- if we still find no edge on this
    coarser score, the real (sharper) live score is not going to look better
    made of the same directionless ingredients.
  - Universe: 25 longtail coins, not the ~230-coin HL universe. Cross-
    sectional decile-ranking still applies (same "who's an outlier today"
    mechanism), but n is smaller -> fewer "flags" per day (usually 2-3).

METHOD (entry-time-safe)
-----------------------------------------------------------------------------
For every (coin, day t) with >= MIN_BASELINE_DAYS trailing history and
day_t notional volume >= MIN_24H_VOLUME_USD:
  1. Compute pct_24h(t), vol_ratio(t), range_pos_pct(t), composite score(t)
     -- all using ONLY data with timestamp <= close of day t.
  2. Cross-sectionally rank all eligible coins on day t by score desc.
     Top decile (round(n*0.10), floor 1) = "FLAGGED" that day.
     Direction = UP if pct_24h(t) > 0 else DOWN.
  3. Forward return over h in {1,3,5} trading days = close_{t+h}/close_t - 1,
     sign-adjusted to the flag's direction (so >0 means "the flagged move's
     direction continued"), MINUS a single one-way-trip-equivalent 9bps
     (0.0009) round-trip fee drag, applied once regardless of horizon.
  4. Forward realized vol over h = stdev of daily log returns t+1..t+h.
     Vol-clustering control: forward_vol(h) / trailing_vol_20(t) ratio, so
     "flagged coins are more volatile forward" can be checked AFTER removing
     the trivial "they were already volatile" effect.
  5. Compare FLAGGED-UP vs FLAGGED-DOWN vs UNFLAGGED (the rest of the
     liquidity-floor survivors that day), overall / first-half / second-half
     (OOS) / per-quarter, plus PARABOLIC vs non-PARABOLIC subsets, plus
     THIN(vol-proxy) vs liquid subsets.
  6. Pooled t-stats AND a per-coin-equal-weight cross-check (average each
     coin's own mean first, then average across coins) since flags recur on
     consecutive days for the same coin (overlapping, non-independent
     samples) -- pooled n overstates independent evidence; the per-coin
     cross-check guards against a couple of chatty coins dominating.

Run:
    python tools/copilot/mover_followthrough_test.py
"""
from __future__ import annotations

import glob
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")

# ---- constants copied verbatim from whats_moving.py (read, not imported) --
MIN_24H_VOLUME_USD = 2_000_000
BASELINE_LOOKBACK_DAYS = 20
MIN_BASELINE_DAYS = 5
VOL_SURGE_CAP = 15.0
PARABOLIC_24H_PCT = 40.0
PARABOLIC_RANGE_POS_PCT = 90.0
ALERT_DECILE_FRACTION = 0.10

FEE_RT = 0.0009  # ~9bps round trip, net-of-fees adjustment
HORIZONS = [1, 3, 5]


# ---------------------------------------------------------------------------
# Load panel
# ---------------------------------------------------------------------------
def load_panel() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(OHLC_DIR, "*_1d.csv"))):
        sym = os.path.basename(path).replace("_1d.csv", "")
        df = pd.read_csv(path)
        df["symbol"] = sym
        df["date"] = pd.to_datetime(df["dt_utc_iso"], utc=True).dt.normalize()
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        frames.append(df[["symbol", "date", "o", "h", "l", "c", "v"]])
    panel = pd.concat(frames, ignore_index=True)
    panel["notional"] = panel["v"] * panel["c"]
    return panel


def compute_features(panel: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        c = g["c"].values
        h = g["h"].values
        l = g["l"].values
        notional = g["notional"].values
        n = len(g)

        pct_24h = np.full(n, np.nan)
        vol_ratio = np.full(n, np.nan)
        range_pos = np.full(n, np.nan)
        trailing_vol20 = np.full(n, np.nan)  # stdev of daily log returns, trailing 20d (t-20..t-1)

        log_ret = np.full(n, np.nan)
        for i in range(1, n):
            log_ret[i] = np.log(c[i] / c[i - 1])
            pct_24h[i] = (c[i] / c[i - 1] - 1.0) * 100.0

        for i in range(n):
            # vol baseline: median notional of the MIN_BASELINE_DAYS..BASELINE_LOOKBACK_DAYS
            # completed days strictly BEFORE t (mirrors `completed = daily[:-1]`)
            lo = max(0, i - BASELINE_LOOKBACK_DAYS)
            hist = notional[lo:i]
            if len(hist) >= MIN_BASELINE_DAYS:
                med = np.median(hist)
                if med > 0:
                    vol_ratio[i] = min(notional[i] / med, VOL_SURGE_CAP)
            # range position: trailing 20 bars INCLUDING today (matches whats_moving's
            # `daily` list, which is not trimmed for the range calc)
            lo2 = max(0, i - BASELINE_LOOKBACK_DAYS + 1)
            hh = h[lo2 : i + 1]
            ll = l[lo2 : i + 1]
            if len(hh) >= MIN_BASELINE_DAYS:
                rng_hi, rng_lo = hh.max(), ll.min()
                if rng_hi > rng_lo:
                    range_pos[i] = max(0.0, min(100.0, (c[i] - rng_lo) / (rng_hi - rng_lo) * 100.0))
            # trailing realized vol (log-return stdev), strictly before t
            lret_hist = log_ret[lo:i]
            lret_hist = lret_hist[~np.isnan(lret_hist)]
            if len(lret_hist) >= MIN_BASELINE_DAYS:
                trailing_vol20[i] = np.std(lret_hist, ddof=1)

        g = g.copy()
        g["pct_24h"] = pct_24h
        g["vol_ratio"] = vol_ratio
        g["range_pos_pct"] = range_pos
        g["trailing_vol20"] = trailing_vol20
        g["log_ret"] = log_ret

        # forward returns / forward vol (entry-time-safe: only uses t+1..t+h, future by construction)
        for hz in HORIZONS:
            fwd_close = np.full(n, np.nan)
            fwd_close[: n - hz] = c[hz:]
            g[f"fwd_ret_{hz}"] = fwd_close / c - 1.0
            fwd_vol = np.full(n, np.nan)
            for i in range(n - hz):
                window = log_ret[i + 1 : i + 1 + hz]
                window = window[~np.isnan(window)]
                if len(window) >= max(2, hz - 1):
                    fwd_vol[i] = np.std(window, ddof=1) if len(window) > 1 else abs(window[0])
            g[f"fwd_vol_{hz}"] = fwd_vol

        out.append(g)
    return pd.concat(out, ignore_index=True)


def apply_floor_and_score(feat: pd.DataFrame) -> pd.DataFrame:
    feat = feat.copy()
    feat["passes_floor"] = (
        feat["notional"].notna()
        & (feat["notional"] >= MIN_24H_VOLUME_USD)
        & feat["pct_24h"].notna()
        & feat["vol_ratio"].notna()  # require baseline established (matches MIN_BASELINE_DAYS gate)
    )
    vol_factor = feat["vol_ratio"].fillna(1.0)
    feat["score"] = feat["pct_24h"].abs() * vol_factor
    feat.loc[~feat["passes_floor"], "score"] = np.nan

    feat["parabolic"] = (
        feat["pct_24h"].abs().ge(PARABOLIC_24H_PCT)
        & feat["range_pos_pct"].notna()
        & ((feat["range_pos_pct"] >= PARABOLIC_RANGE_POS_PCT) | (feat["range_pos_pct"] <= 100 - PARABOLIC_RANGE_POS_PCT))
    )
    return feat


def flag_movers(feat: pd.DataFrame) -> pd.DataFrame:
    """Per-day cross-sectional top-decile-by-score = FLAGGED (mirrors
    whats_moving.py's --alert top-decile mechanism, applied daily here
    instead of "vs last poll" since this is an offline panel)."""
    feat = feat.copy()
    feat["flagged"] = False
    feat["thin_proxy"] = False
    for date, g in feat.groupby("date"):
        elig = g[g["passes_floor"]]
        if elig.empty:
            continue
        n_elig = len(elig)
        decile_n = max(1, round(n_elig * ALERT_DECILE_FRACTION))
        top_idx = elig["score"].sort_values(ascending=False).head(decile_n).index
        feat.loc[top_idx, "flagged"] = True
        # thin-proxy: bottom quartile of notional volume among today's survivors
        q25 = elig["notional"].quantile(0.25)
        thin_idx = elig[elig["notional"] <= q25].index
        feat.loc[thin_idx, "thin_proxy"] = True
    feat["direction"] = np.where(feat["pct_24h"] > 0, "UP", np.where(feat["pct_24h"] < 0, "DOWN", "FLAT"))
    return feat


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------
def signed_fwd_ret(df: pd.DataFrame, hz: int) -> pd.Series:
    """Return in the direction of the flag (>0 = move continued), net of one 9bps round trip."""
    sign = np.where(df["direction"] == "UP", 1.0, np.where(df["direction"] == "DOWN", -1.0, np.nan))
    return sign * df[f"fwd_ret_{hz}"] - FEE_RT


def summarize(df: pd.DataFrame, hz: int, label: str) -> Dict:
    sub = df.dropna(subset=[f"fwd_ret_{hz}"])
    if sub.empty:
        return {"group": label, "horizon": hz, "n": 0}
    r = signed_fwd_ret(sub, hz)
    r = r.dropna()
    n = len(r)
    if n == 0:
        return {"group": label, "horizon": hz, "n": 0}
    mean = r.mean()
    std = r.std(ddof=1) if n > 1 else np.nan
    tstat = mean / (std / np.sqrt(n)) if std and std > 0 else np.nan
    hit = (r > 0).mean()
    # per-coin equal-weight cross-check
    by_coin = sub.assign(_r=r).groupby("symbol")["_r"].mean()
    coin_eq_mean = by_coin.mean()
    return {
        "group": label,
        "horizon": hz,
        "n": n,
        "n_coins": sub["symbol"].nunique(),
        "mean_net_pct": mean * 100,
        "median_net_pct": r.median() * 100,
        "std_pct": (std * 100) if std == std else np.nan,
        "tstat": tstat,
        "hit_rate": hit * 100,
        "coin_eq_wt_mean_pct": coin_eq_mean * 100,
    }


def print_table(rows: List[Dict], title: str) -> None:
    print(f"\n=== {title} ===")
    dfres = pd.DataFrame(rows)
    if dfres.empty:
        print("  (no data)")
        return
    cols = ["group", "horizon", "n", "n_coins", "mean_net_pct", "median_net_pct", "std_pct", "tstat", "hit_rate", "coin_eq_wt_mean_pct"]
    cols = [c for c in cols if c in dfres.columns]
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(dfres[cols].to_string(index=False))


def directional_edge_block(df: pd.DataFrame, title: str) -> None:
    rows = []
    for hz in HORIZONS:
        for grp_name, grp_df in [
            ("FLAGGED-UP", df[df["flagged"] & (df["direction"] == "UP")]),
            ("FLAGGED-DOWN", df[df["flagged"] & (df["direction"] == "DOWN")]),
            ("UNFLAGGED", df[~df["flagged"] & df["passes_floor"]]),
        ]:
            rows.append(summarize(grp_df, hz, grp_name))
    print_table(rows, title)


def parabolic_block(df: pd.DataFrame, title: str) -> None:
    rows = []
    flagged_up = df[df["flagged"] & (df["direction"] == "UP")]
    for hz in HORIZONS:
        rows.append(summarize(flagged_up[flagged_up["parabolic"]], hz, "FLAGGED-UP & PARABOLIC"))
        rows.append(summarize(flagged_up[~flagged_up["parabolic"]], hz, "FLAGGED-UP & non-parabolic"))
    flagged_down = df[df["flagged"] & (df["direction"] == "DOWN")]
    for hz in HORIZONS:
        rows.append(summarize(flagged_down[flagged_down["parabolic"]], hz, "FLAGGED-DOWN & PARABOLIC"))
        rows.append(summarize(flagged_down[~flagged_down["parabolic"]], hz, "FLAGGED-DOWN & non-parabolic"))
    print_table(rows, title)


def thin_block(df: pd.DataFrame, title: str) -> None:
    rows = []
    flagged = df[df["flagged"]]
    for hz in HORIZONS:
        rows.append(summarize(flagged[flagged["thin_proxy"]], hz, "FLAGGED & THIN(vol-proxy)"))
        rows.append(summarize(flagged[~flagged["thin_proxy"]], hz, "FLAGGED & liquid"))
    print_table(rows, title)


def vol_worthiness_block(df: pd.DataFrame, title: str) -> None:
    """Attention-worthiness test: forward vol raw AND normalized by the
    coin's own trailing vol (vol-clustering control)."""
    rows = []
    for hz in HORIZONS:
        for grp_name, grp_df in [
            ("FLAGGED", df[df["flagged"] & df["passes_floor"]]),
            ("UNFLAGGED", df[~df["flagged"] & df["passes_floor"]]),
        ]:
            sub = grp_df.dropna(subset=[f"fwd_vol_{hz}", "trailing_vol20"])
            sub = sub[sub["trailing_vol20"] > 0]
            if sub.empty:
                rows.append({"group": grp_name, "horizon": hz, "n": 0})
                continue
            raw_vol = sub[f"fwd_vol_{hz}"]
            norm = raw_vol / sub["trailing_vol20"]
            rows.append({
                "group": grp_name,
                "horizon": hz,
                "n": len(sub),
                "mean_fwd_vol_pct": raw_vol.mean() * 100,
                "mean_fwd_vol_norm_x_trailing": norm.mean(),
                "median_fwd_vol_norm_x_trailing": norm.median(),
            })
    print(f"\n=== {title} ===")
    dfres = pd.DataFrame(rows)
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(dfres.to_string(index=False))


def era_split(feat: pd.DataFrame):
    dates = sorted(feat["date"].unique())
    mid = dates[len(dates) // 2]
    first = feat[feat["date"] < mid]
    second = feat[feat["date"] >= mid]
    print(f"\nOOS split: first-half < {mid.date()}  |  second-half >= {mid.date()}  "
          f"({len(first['date'].unique())} vs {len(second['date'].unique())} days)")
    return first, second


def quarter_split(feat: pd.DataFrame):
    feat = feat.copy()
    feat["q"] = feat["date"].dt.to_period("Q").astype(str)
    rows = []
    for q, g in feat.groupby("q"):
        for hz in [1, 3]:
            for grp_name, grp_df in [
                ("FLAGGED-UP", g[g["flagged"] & (g["direction"] == "UP")]),
                ("FLAGGED-DOWN", g[g["flagged"] & (g["direction"] == "DOWN")]),
            ]:
                s = summarize(grp_df, hz, f"{q} {grp_name}")
                s["quarter"] = q
                rows.append(s)
    return rows


def main() -> None:
    print("Loading longtail daily OHLC panel...")
    panel = load_panel()
    print(f"  {panel['symbol'].nunique()} coins, {panel['date'].min().date()} -> {panel['date'].max().date()}, "
          f"{len(panel)} coin-days")

    feat = compute_features(panel)
    feat = apply_floor_and_score(feat)
    feat = flag_movers(feat)

    n_elig_days = feat[feat["passes_floor"]].groupby("date").size()
    n_flag_days = feat[feat["flagged"]].groupby("date").size()
    print(f"\nEligible (liquidity-floor-passing) coin-days: {feat['passes_floor'].sum()} / {len(feat)}")
    print(f"Median eligible coins/day: {n_elig_days.median():.0f}  |  median flagged/day: {n_flag_days.median():.0f}")
    print(f"Total flagged coin-days: {feat['flagged'].sum()}  "
          f"(UP: {(feat['flagged'] & (feat['direction']=='UP')).sum()}, "
          f"DOWN: {(feat['flagged'] & (feat['direction']=='DOWN')).sum()})")
    print(f"Of flagged: parabolic={feat[feat['flagged']]['parabolic'].sum()}, "
          f"thin-proxy={feat[feat['flagged']]['thin_proxy'].sum()}")

    # ---- (1) Directional follow-through / fade, full period ----
    directional_edge_block(feat, "1) FULL PERIOD: net signed forward return by flag/direction (bps=x*100, fee 9bps applied)")

    # ---- OOS split ----
    first, second = era_split(feat)
    directional_edge_block(first, "1b) FIRST HALF (in-sample-ish): net signed forward return")
    directional_edge_block(second, "1c) SECOND HALF (OOS): net signed forward return")

    # ---- (2) Attention-worthiness / vol test ----
    vol_worthiness_block(feat, "2) FULL PERIOD: forward realized vol, raw and normalized by own trailing vol")
    vol_worthiness_block(second, "2b) SECOND HALF (OOS): forward realized vol, raw and normalized")

    # ---- (3) Parabolic = late? ----
    parabolic_block(feat, "3) FULL PERIOD: PARABOLIC vs non-parabolic forward return within flagged set")
    parabolic_block(second, "3b) SECOND HALF (OOS): PARABOLIC vs non-parabolic")

    # ---- thin-proxy cut ----
    thin_block(feat, "3c) FULL PERIOD: THIN(vol-proxy) vs liquid within flagged set")

    # ---- (4) per-quarter robustness ----
    print("\n=== 4) PER-QUARTER: net signed forward return (h=1,3) by flag/direction ===")
    qrows = quarter_split(feat)
    qdf = pd.DataFrame(qrows)
    if not qdf.empty:
        cols = ["quarter", "group", "horizon", "n", "mean_net_pct", "tstat", "hit_rate"]
        cols = [c for c in cols if c in qdf.columns]
        with pd.option_context("display.float_format", "{:.3f}".format):
            print(qdf[cols].to_string(index=False))

    # flag high-vol era explicitly (2026-01/02 mentioned in project memory)
    hv_era = feat[(feat["date"] >= "2026-01-01") & (feat["date"] < "2026-03-01")]
    directional_edge_block(hv_era, "4b) 2026-01/02 HIGH-VOL ERA ONLY: net signed forward return (is any full-period finding just this window?)")

    print("\nDone.")


if __name__ == "__main__":
    main()
