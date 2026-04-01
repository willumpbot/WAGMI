"""
Cross-Asset Correlation Analysis — Live Research Tool
Fetches 500 1h candles for BTC, SOL, HYPE and runs:
1. Rolling correlation matrix (24h, 48h, 7d)
2. Lead-lag cross-correlation (lags 0-5h)
3. Regime-conditional correlations (RSI-based)
4. Divergence signals (current)
5. Pairs trade opportunities (ratio analysis)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from data.fetcher import DataFetcher

# ─── Fetch Data ───────────────────────────────────────────────────

print("=" * 70)
print("CROSS-ASSET CORRELATION ANALYSIS — LIVE DATA")
print("=" * 70)

fetcher = DataFetcher(cache_ttl=10)  # short cache for fresh data

SYMBOLS = {
    "BTC": "bitcoin",
    "SOL": "solana",
    "HYPE": "hyperliquid",
}

data = {}
for sym, cg_id in SYMBOLS.items():
    print(f"Fetching {sym} 1h candles...")
    df = fetcher.fetch_ohlcv(sym, cg_id, "1h")
    if df is not None and not df.empty:
        df = df.tail(500).reset_index(drop=True)
        data[sym] = df
        print(f"  {sym}: {len(df)} candles, last close={df['close'].iloc[-1]:.4f}, "
              f"range {df['time'].iloc[0]} -> {df['time'].iloc[-1]}")
    else:
        print(f"  WARNING: No data for {sym}")

if len(data) < 3:
    print("ERROR: Could not fetch all 3 symbols")
    sys.exit(1)

# Align timestamps
min_len = min(len(data[s]) for s in data)
for s in data:
    data[s] = data[s].tail(min_len).reset_index(drop=True)

print(f"\nAligned to {min_len} candles")

# ─── Compute Returns ─────────────────────────────────────────────

returns = {}
for sym in data:
    returns[sym] = data[sym]["close"].pct_change().dropna().values

# Trim to same length
min_ret_len = min(len(returns[s]) for s in returns)
for s in returns:
    returns[s] = returns[s][-min_ret_len:]

ret_df = pd.DataFrame(returns)

# ─── Helper: RSI ─────────────────────────────────────────────────

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

# ═══════════════════════════════════════════════════════════════════
# 1. ROLLING CORRELATION MATRIX
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("1. ROLLING CORRELATION MATRIX")
print("=" * 70)

pairs = [("BTC", "HYPE"), ("BTC", "SOL"), ("HYPE", "SOL")]
windows = {"24h": 24, "48h": 48, "7d": 168}

for window_name, window_size in windows.items():
    print(f"\n--- {window_name} Rolling Window (last value) ---")
    for s1, s2 in pairs:
        rolling_corr = ret_df[s1].rolling(window_size).corr(ret_df[s2])
        current = rolling_corr.iloc[-1]
        prev = rolling_corr.iloc[-window_size] if len(rolling_corr) > window_size else np.nan
        mean_corr = rolling_corr.dropna().mean()
        std_corr = rolling_corr.dropna().std()

        # Trend: is correlation rising or falling?
        recent_5 = rolling_corr.iloc[-5:].mean()
        recent_20 = rolling_corr.iloc[-20:].mean() if len(rolling_corr) >= 20 else np.nan
        trend = "RISING" if recent_5 > recent_20 else "FALLING"

        print(f"  {s1}-{s2}: {current:+.4f}  (mean={mean_corr:+.4f}, std={std_corr:.4f})  "
              f"trend={trend}  5bar={recent_5:+.4f} vs 20bar={recent_20:+.4f}")

# Full-sample correlation
print(f"\n--- Full Sample Correlation ({min_ret_len} bars) ---")
full_corr = ret_df.corr()
for s1, s2 in pairs:
    print(f"  {s1}-{s2}: {full_corr.loc[s1, s2]:+.4f}")

# ═══════════════════════════════════════════════════════════════════
# 2. LEAD-LAG ANALYSIS
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("2. LEAD-LAG ANALYSIS (Cross-Correlation at lags 0-5h)")
print("=" * 70)

for s1, s2 in pairs:
    print(f"\n--- {s1} leads {s2}? ---")
    r1 = ret_df[s1].values
    r2 = ret_df[s2].values

    best_lag = 0
    best_corr = 0

    for lag in range(6):
        if lag == 0:
            corr = np.corrcoef(r1, r2)[0, 1]
        else:
            # s1 at time t correlated with s2 at time t+lag
            # (s1 leads s2 by `lag` bars)
            corr = np.corrcoef(r1[:-lag], r2[lag:])[0, 1]

        marker = " <-- BEST" if abs(corr) > abs(best_corr) else ""
        if abs(corr) > abs(best_corr):
            best_corr = corr
            best_lag = lag

        print(f"  lag={lag}h: r={corr:+.4f}{marker}")

    if best_lag > 0:
        print(f"  >>> {s1} LEADS {s2} by {best_lag}h (r={best_corr:+.4f})")
    else:
        print(f"  >>> Contemporaneous correlation strongest (r={best_corr:+.4f})")

# Also check reverse direction for completeness
print("\n--- Reverse direction check ---")
for s1, s2 in pairs:
    r1 = ret_df[s1].values
    r2 = ret_df[s2].values

    # Check if s2 leads s1
    best_lag = 0
    best_corr = np.corrcoef(r1, r2)[0, 1]

    for lag in range(1, 6):
        corr = np.corrcoef(r2[:-lag], r1[lag:])[0, 1]
        if abs(corr) > abs(best_corr):
            best_corr = corr
            best_lag = lag

    if best_lag > 0:
        print(f"  {s2} leads {s1} by {best_lag}h (r={best_corr:+.4f})")
    else:
        print(f"  {s1}-{s2}: contemporaneous is strongest")

# ═══════════════════════════════════════════════════════════════════
# 3. REGIME-CONDITIONAL CORRELATIONS
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("3. REGIME-CONDITIONAL CORRELATIONS")
print("=" * 70)

btc_close = data["BTC"]["close"]
btc_rsi = compute_rsi(btc_close)
btc_rsi_aligned = btc_rsi.iloc[-min_ret_len:].values

# RSI-based regimes
rsi_oversold = btc_rsi_aligned < 30
rsi_overbought = btc_rsi_aligned > 70
rsi_neutral = (btc_rsi_aligned >= 30) & (btc_rsi_aligned <= 70)

print(f"\nBTC RSI now: {btc_rsi.iloc[-1]:.1f}")
print(f"Bars with RSI<30: {rsi_oversold.sum()} | RSI>70: {rsi_overbought.sum()} | Neutral: {rsi_neutral.sum()}")

for regime_name, regime_mask in [("RSI<30 (oversold)", rsi_oversold),
                                   ("RSI>70 (overbought)", rsi_overbought),
                                   ("RSI 30-70 (neutral)", rsi_neutral)]:
    n = regime_mask.sum()
    if n < 10:
        print(f"\n  {regime_name}: Too few samples ({n}), skipping")
        continue

    print(f"\n  {regime_name} ({n} bars):")
    for s1, s2 in pairs:
        r1 = ret_df[s1].values[regime_mask]
        r2 = ret_df[s2].values[regime_mask]
        if len(r1) > 2:
            corr = np.corrcoef(r1, r2)[0, 1]
            print(f"    {s1}-{s2}: {corr:+.4f}")

# Trending vs ranging (using 20-bar rolling std of BTC returns)
btc_ret_vol = pd.Series(ret_df["BTC"].values).rolling(20).std().values
vol_median = np.nanmedian(btc_ret_vol)
trending = btc_ret_vol > vol_median
ranging = btc_ret_vol <= vol_median

# Remove NaN indices
valid = ~np.isnan(btc_ret_vol)
trending = trending & valid
ranging = ranging & valid

print(f"\n--- Trending vs Ranging (BTC 20h vol split at median) ---")
for regime_name, regime_mask in [("TRENDING (high vol)", trending), ("RANGING (low vol)", ranging)]:
    n = regime_mask.sum()
    print(f"\n  {regime_name} ({n} bars):")
    for s1, s2 in pairs:
        r1 = ret_df[s1].values[regime_mask]
        r2 = ret_df[s2].values[regime_mask]
        if len(r1) > 2:
            corr = np.corrcoef(r1, r2)[0, 1]
            print(f"    {s1}-{s2}: {corr:+.4f}")

# ═══════════════════════════════════════════════════════════════════
# 4. DIVERGENCE SIGNALS — RIGHT NOW
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("4. DIVERGENCE SIGNALS — CURRENT STATE")
print("=" * 70)

# Cumulative returns over different windows
for window in [6, 12, 24, 48, 72]:
    print(f"\n--- {window}h Cumulative Return ---")
    for sym in ["BTC", "SOL", "HYPE"]:
        cum_ret = (data[sym]["close"].iloc[-1] / data[sym]["close"].iloc[-window-1] - 1) * 100
        print(f"  {sym}: {cum_ret:+.2f}%")

    # Alpha calculations
    btc_ret = (data["BTC"]["close"].iloc[-1] / data["BTC"]["close"].iloc[-window-1] - 1) * 100
    hype_ret = (data["HYPE"]["close"].iloc[-1] / data["HYPE"]["close"].iloc[-window-1] - 1) * 100
    sol_ret = (data["SOL"]["close"].iloc[-1] / data["SOL"]["close"].iloc[-window-1] - 1) * 100

    print(f"  HYPE alpha vs BTC: {hype_ret - btc_ret:+.2f}%")
    print(f"  SOL alpha vs BTC: {sol_ret - btc_ret:+.2f}%")
    print(f"  HYPE alpha vs SOL: {hype_ret - sol_ret:+.2f}%")

# Z-score of current divergence
print(f"\n--- Divergence Z-Scores (is current divergence unusual?) ---")
for s1, s2 in pairs:
    # Rolling spread: s1 return - s2 return
    spread = ret_df[s1] - ret_df[s2]
    rolling_mean = spread.rolling(48).mean()
    rolling_std = spread.rolling(48).std()
    z_score = (spread.iloc[-1] - rolling_mean.iloc[-1]) / rolling_std.iloc[-1] if rolling_std.iloc[-1] > 0 else 0

    # Cumulative spread over last 24h
    cum_spread_24h = spread.iloc[-24:].sum() * 100
    cum_spread_48h = spread.iloc[-48:].sum() * 100

    print(f"  {s1}-{s2}: z={z_score:+.2f}  cum_spread_24h={cum_spread_24h:+.2f}%  "
          f"cum_spread_48h={cum_spread_48h:+.2f}%")

# HYPE-BTC divergence trend
print(f"\n--- HYPE-BTC Divergence Trend (is it increasing or reverting?) ---")
hype_btc_spread = ret_df["HYPE"] - ret_df["BTC"]
cum_spread = hype_btc_spread.cumsum()
# Last 5 values of cumulative spread
for i in [1, 6, 12, 24, 48]:
    val = cum_spread.iloc[-i] * 100
    print(f"  {i}h ago cumulative spread: {val:+.3f}%")

recent_trend = cum_spread.iloc[-1] - cum_spread.iloc[-24]
print(f"  24h change in cumulative spread: {recent_trend*100:+.3f}%")
print(f"  Direction: {'DIVERGENCE INCREASING' if recent_trend > 0.001 else 'REVERTING' if recent_trend < -0.001 else 'STABLE'}")

# ═══════════════════════════════════════════════════════════════════
# 5. PAIRS TRADE OPPORTUNITIES
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("5. PAIRS TRADE OPPORTUNITIES")
print("=" * 70)

# Price ratios
for s1, s2 in [("HYPE", "SOL"), ("HYPE", "BTC"), ("SOL", "BTC")]:
    ratio = data[s1]["close"] / data[s2]["close"]
    current_ratio = ratio.iloc[-1]
    mean_ratio = ratio.mean()
    std_ratio = ratio.std()
    z = (current_ratio - mean_ratio) / std_ratio if std_ratio > 0 else 0

    # Percentile
    pct = (ratio < current_ratio).mean() * 100

    # Mean reversion potential
    half_life = None
    try:
        log_ratio = np.log(ratio)
        lag = log_ratio.shift(1).dropna()
        diff = log_ratio.diff().dropna()
        # Simple OLS for mean reversion speed
        common_idx = lag.index.intersection(diff.index)
        if len(common_idx) > 10:
            x = lag.loc[common_idx].values
            y = diff.loc[common_idx].values
            beta = np.polyfit(x, y, 1)[0]
            if beta < 0:
                half_life = -np.log(2) / beta
    except:
        pass

    hl_str = f"{half_life:.1f}h" if half_life and half_life > 0 and half_life < 500 else "N/A"

    print(f"\n  {s1}/{s2} Ratio:")
    print(f"    Current: {current_ratio:.6f}")
    print(f"    Mean (500h): {mean_ratio:.6f}")
    print(f"    Z-score: {z:+.2f}")
    print(f"    Percentile: {pct:.0f}th")
    print(f"    Half-life: {hl_str}")

    if abs(z) > 1.5:
        direction = "SHORT" if z > 0 else "LONG"
        print(f"    >>> SIGNAL: {direction} {s1}/{s2} (z={z:+.2f}, mean-reversion)")
    elif abs(z) > 1.0:
        direction = "SHORT" if z > 0 else "LONG"
        print(f"    >>> WATCH: {direction} {s1}/{s2} approaching signal (z={z:+.2f})")
    else:
        print(f"    >>> No signal (ratio near fair value)")

# ═══════════════════════════════════════════════════════════════════
# 6. SUMMARY & TRADE IMPLICATIONS
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("6. SUMMARY & TRADE IMPLICATIONS")
print("=" * 70)

# Current prices
print(f"\nCurrent Prices:")
for sym in ["BTC", "SOL", "HYPE"]:
    print(f"  {sym}: {data[sym]['close'].iloc[-1]:.4f}")

# RSI values
print(f"\nRSI(14):")
for sym in ["BTC", "SOL", "HYPE"]:
    rsi = compute_rsi(data[sym]["close"])
    print(f"  {sym}: {rsi.iloc[-1]:.1f}")

# Key findings for SOL SELL thesis
print(f"\n--- SOL SELL Thesis Assessment ---")
sol_btc_corr_24h = ret_df["BTC"].rolling(24).corr(ret_df["SOL"]).iloc[-1]
sol_ret_24h = (data["SOL"]["close"].iloc[-1] / data["SOL"]["close"].iloc[-25] - 1) * 100
btc_ret_24h = (data["BTC"]["close"].iloc[-1] / data["BTC"]["close"].iloc[-25] - 1) * 100
sol_alpha = sol_ret_24h - btc_ret_24h

print(f"  SOL-BTC 24h correlation: {sol_btc_corr_24h:+.4f}")
print(f"  SOL 24h return: {sol_ret_24h:+.2f}%")
print(f"  BTC 24h return: {btc_ret_24h:+.2f}%")
print(f"  SOL alpha vs BTC: {sol_alpha:+.2f}%")

if sol_alpha < -0.5:
    print(f"  >>> SOL underperforming BTC — supports SELL thesis")
elif sol_alpha > 0.5:
    print(f"  >>> SOL outperforming BTC — challenges SELL thesis")
else:
    print(f"  >>> SOL tracking BTC — neutral for directional thesis")

print("\n" + "=" * 70)
print("ANALYSIS COMPLETE")
print("=" * 70)
