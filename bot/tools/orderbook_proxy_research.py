"""
Order Book Imbalance Proxy Research
====================================
Analyzes OHLCV data to detect order book behavior proxies:
1. Volume imbalance (buy vs sell volume)
2. Large candle detection (institutional orders)
3. Wick rejection patterns
4. Volume-weighted momentum
5. Exhaustion detection

Uses 500 1h candles for HYPE, BTC, SOL.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from data.fetcher import DataFetcher

# Coin mappings: symbol -> coingecko id
COINS = {
    "HYPE": "hyperliquid",
    "BTC": "bitcoin",
    "SOL": "solana",
}


def fetch_data():
    """Fetch 500 1h candles for each symbol."""
    fetcher = DataFetcher(fresh=True)
    data = {}
    for sym, cg_id in COINS.items():
        print(f"Fetching {sym} 1h candles...")
        df = fetcher.fetch_ohlcv(sym, cg_id, "1h")
        if df is not None and not df.empty:
            # Ensure we have standard columns
            df = df.tail(500).copy().reset_index(drop=True)
            print(f"  Got {len(df)} candles, cols: {list(df.columns)}")
            data[sym] = df
        else:
            print(f"  FAILED to fetch {sym}")
    return data


def compute_derived(df):
    """Add derived columns needed for analysis."""
    df = df.copy()
    df["body"] = df["close"] - df["open"]
    df["body_abs"] = df["body"].abs()
    df["range"] = df["high"] - df["low"]
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["is_green"] = (df["close"] > df["open"]).astype(int)
    df["is_red"] = (df["close"] < df["open"]).astype(int)
    # Returns
    df["ret_1h"] = df["close"].pct_change().shift(-1)  # NEXT candle return
    df["ret_3h"] = df["close"].pct_change(3).shift(-3)  # 3-candle forward return
    df["ret_6h"] = df["close"].pct_change(6).shift(-6)
    # Volume average (20-period)
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["body_ma20"] = df["body_abs"].rolling(20).mean()
    return df


def analysis_1_volume_imbalance(df, sym):
    """Compare buying vs selling volume and predictive power."""
    print(f"\n{'='*70}")
    print(f"  1. VOLUME IMBALANCE — {sym}")
    print(f"{'='*70}")

    # Classify candles
    buy_vol = df.loc[df["is_green"] == 1, "volume"]
    sell_vol = df.loc[df["is_red"] == 1, "volume"]

    # Rolling buy/sell volume ratio (10-period)
    df["buy_vol_10"] = (df["volume"] * df["is_green"]).rolling(10).sum()
    df["sell_vol_10"] = (df["volume"] * df["is_red"]).rolling(10).sum()
    df["vol_ratio"] = df["buy_vol_10"] / df["sell_vol_10"].replace(0, np.nan)

    print(f"  Total candles: {len(df)}")
    print(f"  Green candles: {df['is_green'].sum()} ({df['is_green'].mean()*100:.1f}%)")
    print(f"  Avg buy candle vol: {buy_vol.mean():,.0f}")
    print(f"  Avg sell candle vol: {sell_vol.mean():,.0f}")
    print(f"  Buy/Sell vol ratio: {buy_vol.sum()/sell_vol.sum():.3f}")

    # When buy vol > 2x sell vol (over 10 candles)
    heavy_buy = df[df["vol_ratio"] > 2.0].dropna(subset=["ret_1h"])
    heavy_sell = df[df["vol_ratio"] < 0.5].dropna(subset=["ret_1h"])

    if len(heavy_buy) > 0:
        buy_win = (heavy_buy["ret_1h"] > 0).mean()
        buy_avg = heavy_buy["ret_1h"].mean() * 100
        print(f"\n  Heavy BUY imbalance (ratio > 2.0): {len(heavy_buy)} occurrences")
        print(f"    Next-hour up: {buy_win*100:.1f}%")
        print(f"    Avg next-hour return: {buy_avg:.3f}%")
        # 3h forward
        hb3 = heavy_buy.dropna(subset=["ret_3h"])
        if len(hb3) > 0:
            print(f"    3h forward up: {(hb3['ret_3h']>0).mean()*100:.1f}%")
            print(f"    3h avg return: {hb3['ret_3h'].mean()*100:.3f}%")
    else:
        print(f"\n  Heavy BUY imbalance (ratio > 2.0): 0 occurrences")

    if len(heavy_sell) > 0:
        sell_win = (heavy_sell["ret_1h"] < 0).mean()
        sell_avg = heavy_sell["ret_1h"].mean() * 100
        print(f"\n  Heavy SELL imbalance (ratio < 0.5): {len(heavy_sell)} occurrences")
        print(f"    Next-hour down: {sell_win*100:.1f}%")
        print(f"    Avg next-hour return: {sell_avg:.3f}%")
        hs3 = heavy_sell.dropna(subset=["ret_3h"])
        if len(hs3) > 0:
            print(f"    3h forward down: {(hs3['ret_3h']<0).mean()*100:.1f}%")
            print(f"    3h avg return: {hs3['ret_3h'].mean()*100:.3f}%")
    else:
        print(f"\n  Heavy SELL imbalance (ratio < 0.5): 0 occurrences")

    # Finer granularity: various thresholds
    print(f"\n  Volume Ratio Threshold Scan:")
    print(f"  {'Threshold':>10} {'Count':>6} {'Next-1h Up%':>12} {'Avg Ret%':>10}")
    for thresh in [1.2, 1.5, 1.8, 2.0, 2.5, 3.0]:
        subset = df[df["vol_ratio"] > thresh].dropna(subset=["ret_1h"])
        if len(subset) >= 5:
            print(f"  {f'>{thresh}':>10} {len(subset):>6} {(subset['ret_1h']>0).mean()*100:>11.1f}% {subset['ret_1h'].mean()*100:>9.3f}%")

    return df


def analysis_2_large_candles(df, sym):
    """Large candles = institutional orders. What happens next?"""
    print(f"\n{'='*70}")
    print(f"  2. LARGE CANDLE DETECTION (Institutional Orders) — {sym}")
    print(f"{'='*70}")

    valid = df.dropna(subset=["vol_ma20", "body_ma20", "ret_1h"])

    # Institutional = volume > 2x avg AND body > 1.5x avg
    inst = valid[
        (valid["volume"] > 2 * valid["vol_ma20"]) &
        (valid["body_abs"] > 1.5 * valid["body_ma20"])
    ]

    inst_green = inst[inst["is_green"] == 1]
    inst_red = inst[inst["is_red"] == 1]

    print(f"  Total institutional candles: {len(inst)} ({len(inst)/len(valid)*100:.1f}% of all)")
    print(f"    Green institutional: {len(inst_green)}")
    print(f"    Red institutional: {len(inst_red)}")

    if len(inst_green) >= 3:
        cont = (inst_green["ret_1h"] > 0).mean()
        rev = (inst_green["ret_1h"] < 0).mean()
        avg = inst_green["ret_1h"].mean() * 100
        print(f"\n  After GREEN institutional candle:")
        print(f"    Continuation (next hour up): {cont*100:.1f}%")
        print(f"    Reversal (next hour down):   {rev*100:.1f}%")
        print(f"    Avg next-hour return:         {avg:.3f}%")
        g3 = inst_green.dropna(subset=["ret_3h"])
        if len(g3) >= 3:
            print(f"    3h continuation: {(g3['ret_3h']>0).mean()*100:.1f}%")
            print(f"    3h avg return:   {g3['ret_3h'].mean()*100:.3f}%")

    if len(inst_red) >= 3:
        cont = (inst_red["ret_1h"] < 0).mean()
        rev = (inst_red["ret_1h"] > 0).mean()
        avg = inst_red["ret_1h"].mean() * 100
        print(f"\n  After RED institutional candle:")
        print(f"    Continuation (next hour down): {cont*100:.1f}%")
        print(f"    Reversal (next hour up):       {rev*100:.1f}%")
        print(f"    Avg next-hour return:           {avg:.3f}%")
        r3 = inst_red.dropna(subset=["ret_3h"])
        if len(r3) >= 3:
            print(f"    3h continuation down: {(r3['ret_3h']<0).mean()*100:.1f}%")
            print(f"    3h avg return:        {r3['ret_3h'].mean()*100:.3f}%")

    # Volume-only spikes (no body requirement)
    vol_spike = valid[valid["volume"] > 2.5 * valid["vol_ma20"]]
    if len(vol_spike) >= 3:
        print(f"\n  Volume-only spikes (>2.5x avg): {len(vol_spike)}")
        print(f"    Next-hour same direction: {((vol_spike['body'] * vol_spike['ret_1h']) > 0).mean()*100:.1f}%")
        print(f"    Next-hour reversal:       {((vol_spike['body'] * vol_spike['ret_1h']) < 0).mean()*100:.1f}%")


def analysis_3_wick_rejections(df, sym):
    """Wick rejection = order absorption. Quantify forward returns."""
    print(f"\n{'='*70}")
    print(f"  3. WICK REJECTION PATTERNS — {sym}")
    print(f"{'='*70}")

    valid = df.dropna(subset=["ret_1h", "ret_3h"])
    mid = (valid["high"] + valid["low"]) / 2

    # Lower wick as % of price
    valid = valid.copy()
    valid["lower_wick_pct"] = valid["lower_wick"] / valid["close"] * 100
    valid["upper_wick_pct"] = valid["upper_wick"] / valid["close"] * 100
    valid["wick_ratio_lower"] = valid["lower_wick"] / valid["range"].replace(0, np.nan)
    valid["wick_ratio_upper"] = valid["upper_wick"] / valid["range"].replace(0, np.nan)

    # Lower wick > 0.5% (buy absorption)
    for thresh in [0.3, 0.5, 0.8, 1.0]:
        lw = valid[valid["lower_wick_pct"] > thresh]
        if len(lw) >= 5:
            up_1h = (lw["ret_1h"] > 0).mean() * 100
            up_3h = (lw["ret_3h"] > 0).mean() * 100
            avg_3h = lw["ret_3h"].mean() * 100
            print(f"\n  Lower wick > {thresh}%: {len(lw)} occurrences")
            print(f"    Next 1h up: {up_1h:.1f}%, Next 3h up: {up_3h:.1f}%")
            print(f"    Avg 3h return: {avg_3h:.3f}%")

    # Upper wick > 0.5% (sell absorption)
    for thresh in [0.3, 0.5, 0.8, 1.0]:
        uw = valid[valid["upper_wick_pct"] > thresh]
        if len(uw) >= 5:
            dn_1h = (uw["ret_1h"] < 0).mean() * 100
            dn_3h = (uw["ret_3h"] < 0).mean() * 100
            avg_3h = uw["ret_3h"].mean() * 100
            print(f"\n  Upper wick > {thresh}%: {len(uw)} occurrences")
            print(f"    Next 1h down: {dn_1h:.1f}%, Next 3h down: {dn_3h:.1f}%")
            print(f"    Avg 3h return: {avg_3h:.3f}%")

    # Hammer pattern: lower wick > 60% of range, body < 30% of range
    hammers = valid[
        (valid["wick_ratio_lower"] > 0.6) &
        (valid["body_abs"] / valid["range"].replace(0, np.nan) < 0.3)
    ]
    if len(hammers) >= 3:
        print(f"\n  HAMMER patterns (lower wick >60% of range, small body): {len(hammers)}")
        print(f"    Next 1h up: {(hammers['ret_1h']>0).mean()*100:.1f}%")
        print(f"    Next 3h up: {(hammers['ret_3h']>0).mean()*100:.1f}%")
        print(f"    Avg 3h return: {hammers['ret_3h'].mean()*100:.3f}%")

    # Shooting star: upper wick > 60%, small body
    stars = valid[
        (valid["wick_ratio_upper"] > 0.6) &
        (valid["body_abs"] / valid["range"].replace(0, np.nan) < 0.3)
    ]
    if len(stars) >= 3:
        print(f"\n  SHOOTING STAR patterns (upper wick >60%, small body): {len(stars)}")
        print(f"    Next 1h down: {(stars['ret_1h']<0).mean()*100:.1f}%")
        print(f"    Next 3h down: {(stars['ret_3h']<0).mean()*100:.1f}%")
        print(f"    Avg 3h return: {stars['ret_3h'].mean()*100:.3f}%")


def analysis_4_volume_weighted_momentum(df, sym):
    """Volume-weighted returns vs raw momentum for prediction."""
    print(f"\n{'='*70}")
    print(f"  4. VOLUME-WEIGHTED MOMENTUM — {sym}")
    print(f"{'='*70}")

    valid = df.dropna(subset=["ret_1h"]).copy()
    valid["raw_ret"] = valid["close"].pct_change()
    valid["vw_ret"] = valid["raw_ret"] * (valid["volume"] / valid["vol_ma20"].replace(0, np.nan))

    # Rolling momentum (5-period)
    for window in [3, 5, 10]:
        valid[f"raw_mom_{window}"] = valid["raw_ret"].rolling(window).sum()
        valid[f"vw_mom_{window}"] = valid["vw_ret"].rolling(window).sum()

        sub = valid.dropna(subset=[f"raw_mom_{window}", f"vw_mom_{window}", "ret_1h"])
        if len(sub) < 20:
            continue

        # Raw momentum prediction
        raw_up = sub[sub[f"raw_mom_{window}"] > 0]
        raw_dn = sub[sub[f"raw_mom_{window}"] < 0]
        raw_acc = 0
        if len(raw_up) > 0 and len(raw_dn) > 0:
            raw_acc = ((raw_up["ret_1h"] > 0).sum() + (raw_dn["ret_1h"] < 0).sum()) / len(sub) * 100

        # Volume-weighted momentum prediction
        vw_up = sub[sub[f"vw_mom_{window}"] > 0]
        vw_dn = sub[sub[f"vw_mom_{window}"] < 0]
        vw_acc = 0
        if len(vw_up) > 0 and len(vw_dn) > 0:
            vw_acc = ((vw_up["ret_1h"] > 0).sum() + (vw_dn["ret_1h"] < 0).sum()) / len(sub) * 100

        print(f"\n  {window}-period momentum:")
        print(f"    Raw momentum accuracy:     {raw_acc:.1f}%")
        print(f"    Vol-weighted accuracy:      {vw_acc:.1f}%")
        print(f"    Improvement:                {vw_acc - raw_acc:+.1f}%")

        # Average return when vw_mom is strongly positive
        vw_strong = sub[sub[f"vw_mom_{window}"] > sub[f"vw_mom_{window}"].quantile(0.8)]
        if len(vw_strong) >= 5:
            print(f"    Strong VW momentum (top 20%): avg next-hr ret = {vw_strong['ret_1h'].mean()*100:.3f}%")

    # Correlation comparison
    corr_sub = valid.dropna(subset=["raw_mom_5", "vw_mom_5", "ret_1h"])
    if len(corr_sub) >= 30:
        raw_corr = corr_sub["raw_mom_5"].corr(corr_sub["ret_1h"])
        vw_corr = corr_sub["vw_mom_5"].corr(corr_sub["ret_1h"])
        print(f"\n  Correlation with next-hour return:")
        print(f"    Raw 5-period momentum:  {raw_corr:.4f}")
        print(f"    VW 5-period momentum:   {vw_corr:.4f}")


def analysis_5_exhaustion(df, sym):
    """High volume + small body = exhaustion. Reversal signal?"""
    print(f"\n{'='*70}")
    print(f"  5. EXHAUSTION DETECTION — {sym}")
    print(f"{'='*70}")

    valid = df.dropna(subset=["vol_ma20", "body_ma20", "ret_1h", "ret_3h"]).copy()

    # Exhaustion: volume > 2x avg BUT body < 0.5x avg
    exhaustion = valid[
        (valid["volume"] > 2.0 * valid["vol_ma20"]) &
        (valid["body_abs"] < 0.5 * valid["body_ma20"])
    ]

    print(f"  Exhaustion candles (vol>2x, body<0.5x): {len(exhaustion)} ({len(exhaustion)/len(valid)*100:.1f}%)")

    if len(exhaustion) >= 3:
        # After exhaustion, does price reverse?
        # Look at the prevailing direction before exhaustion
        exhaustion = exhaustion.copy()
        exhaustion["prev_3h_ret"] = exhaustion["close"].pct_change(3)

        # Exhaustion after uptrend
        exh_up = exhaustion[exhaustion["prev_3h_ret"] > 0]
        if len(exh_up) >= 2:
            print(f"\n  Exhaustion after UPTREND ({len(exh_up)} cases):")
            print(f"    Next 1h down (reversal): {(exh_up['ret_1h']<0).mean()*100:.1f}%")
            print(f"    Next 3h down (reversal): {(exh_up['ret_3h']<0).mean()*100:.1f}%")
            print(f"    Avg 3h return: {exh_up['ret_3h'].mean()*100:.3f}%")

        # Exhaustion after downtrend
        exh_dn = exhaustion[exhaustion["prev_3h_ret"] < 0]
        if len(exh_dn) >= 2:
            print(f"\n  Exhaustion after DOWNTREND ({len(exh_dn)} cases):")
            print(f"    Next 1h up (reversal): {(exh_dn['ret_1h']>0).mean()*100:.1f}%")
            print(f"    Next 3h up (reversal): {(exh_dn['ret_3h']>0).mean()*100:.1f}%")
            print(f"    Avg 3h return: {exh_dn['ret_3h'].mean()*100:.3f}%")

    # Wider exhaustion: vol > 1.5x, body < 0.7x
    exh2 = valid[
        (valid["volume"] > 1.5 * valid["vol_ma20"]) &
        (valid["body_abs"] < 0.7 * valid["body_ma20"])
    ]
    if len(exh2) >= 5:
        print(f"\n  Relaxed exhaustion (vol>1.5x, body<0.7x): {len(exh2)} candles")
        exh2 = exh2.copy()
        exh2["prev_dir"] = np.sign(exh2["close"].pct_change(3))
        # Reversal rate
        reversal = ((exh2["prev_dir"] * exh2["ret_3h"]) < 0).mean()
        print(f"    3h reversal rate: {reversal*100:.1f}%")
        print(f"    Avg |3h return|: {exh2['ret_3h'].abs().mean()*100:.3f}%")

    # Combined exhaustion + wick rejection (strongest signal)
    exh_wick = valid[
        (valid["volume"] > 1.5 * valid["vol_ma20"]) &
        (valid["body_abs"] < 0.7 * valid["body_ma20"]) &
        ((valid["lower_wick"] > 0.5 * valid["range"]) | (valid["upper_wick"] > 0.5 * valid["range"]))
    ]
    if len(exh_wick) >= 3:
        print(f"\n  COMBO: Exhaustion + wick rejection: {len(exh_wick)} candles")
        print(f"    Next 1h reversal: {((np.sign(exh_wick['body']) * exh_wick['ret_1h']) < 0).mean()*100:.1f}%")
        print(f"    Next 3h reversal: {((np.sign(exh_wick['body']) * exh_wick['ret_3h']) < 0).mean()*100:.1f}%")


def print_summary(all_data):
    """Print actionable summary."""
    print(f"\n{'='*70}")
    print(f"  ACTIONABLE SUMMARY")
    print(f"{'='*70}")
    print("""
  METHODOLOGY:
  - 500 1h candles per symbol (~21 days)
  - Forward returns are out-of-sample (shifted forward, no lookahead)
  - Accuracy > 55% at 1h/3h horizons is actionable for leveraged trading
  - Need minimum 10+ occurrences for statistical relevance

  KEY QUESTION: Which signals hit 55%+ directional accuracy?
  Check the numbers above for each symbol. Cross-symbol consistency
  makes a signal more reliable (not curve-fitted to one asset).
  """)


def main():
    print("=" * 70)
    print("  ORDER BOOK IMBALANCE PROXY RESEARCH")
    print("  Using 500 1h candles for HYPE, BTC, SOL")
    print("=" * 70)

    data = fetch_data()

    if not data:
        print("ERROR: No data fetched. Check exchange connectivity.")
        return

    for sym, df in data.items():
        print(f"\n\n{'#'*70}")
        print(f"  SYMBOL: {sym} — {len(df)} candles")
        print(f"{'#'*70}")

        df = compute_derived(df)
        df = analysis_1_volume_imbalance(df, sym)
        analysis_2_large_candles(df, sym)
        analysis_3_wick_rejections(df, sym)
        analysis_4_volume_weighted_momentum(df, sym)
        analysis_5_exhaustion(df, sym)

    print_summary(data)


if __name__ == "__main__":
    main()
