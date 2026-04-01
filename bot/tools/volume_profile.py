"""Volume profile and support/resistance analysis."""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.fetcher import DataFetcher

SYMBOLS = {"HYPE": "hyperliquid", "BTC": "bitcoin", "SOL": "solana"}


def analyze_volume_profile(sym, df):
    """Find high-volume price zones (support/resistance)."""
    price = df["close"].iloc[-1]
    # Create price buckets (1% wide)
    bucket_size = price * 0.01
    df["bucket"] = (df["close"] / bucket_size).round(0) * bucket_size

    vol_profile = df.groupby("bucket")["volume"].sum().sort_values(ascending=False)

    print(f"\n  {sym} Volume Profile (high-volume zones = S/R):")
    for i, (bucket_price, vol) in enumerate(vol_profile.head(5).items()):
        dist_pct = (bucket_price - price) / price * 100
        role = "SUPPORT" if bucket_price < price else "RESISTANCE" if bucket_price > price else "AT PRICE"
        print(f"    ${bucket_price:.2f} ({dist_pct:+.1f}%) vol={vol:.0f} — {role}")


def analyze_range_stats(sym, df):
    """Analyze typical trading ranges for position sizing."""
    price = df["close"].iloc[-1]

    # Intraday range (high-low) as % of close
    df["range_pct"] = (df["high"] - df["low"]) / df["close"] * 100

    last_24 = df.tail(24)
    last_7d = df.tail(168)

    print(f"\n  {sym} Range Statistics:")
    print(f"    24h avg range: {last_24['range_pct'].mean():.2f}%")
    print(f"    7d avg range:  {last_7d['range_pct'].mean():.2f}%")
    print(f"    7d max range:  {last_7d['range_pct'].max():.2f}%")
    print(f"    Current ATR:   {last_24['range_pct'].mean():.2f}%")

    # What % of bars move > 1%, > 2%, > 3%?
    for thresh in [1.0, 2.0, 3.0]:
        pct = (last_7d["range_pct"] > thresh).mean() * 100
        print(f"    Bars with >{thresh}% range: {pct:.0f}%")

    # Optimal SL should be wider than typical noise
    median_range = last_7d["range_pct"].median()
    print(f"    Recommended min SL: {median_range * 1.5:.2f}% (1.5x median range)")


def analyze_momentum_persistence(sym, df):
    """How persistent is momentum across bars?"""
    df["ret"] = df["close"].pct_change() * 100
    df["prev_ret"] = df["ret"].shift(1)

    # Autocorrelation of returns
    autocorr = df["ret"].autocorr(lag=1)
    print(f"\n  {sym} Momentum Analysis:")
    print(f"    1-bar return autocorrelation: {autocorr:.3f}")
    if autocorr > 0.1:
        print(f"    Interpretation: MOMENTUM (trends persist)")
    elif autocorr < -0.1:
        print(f"    Interpretation: MEAN REVERSION (moves reverse)")
    else:
        print(f"    Interpretation: RANDOM WALK (no predictability)")

    # Conditional: after big moves, what happens?
    big_up = df[df["ret"] > 1.0]
    if len(big_up) > 3:
        next_ret = df.loc[big_up.index + 1, "ret"].dropna()
        print(f"    After >1% up bar: next bar avg {next_ret.mean():.3f}%, positive {(next_ret > 0).mean()*100:.0f}% (n={len(next_ret)})")

    big_down = df[df["ret"] < -1.0]
    if len(big_down) > 3:
        next_ret = df.loc[big_down.index + 1, "ret"].dropna()
        print(f"    After >1% down bar: next bar avg {next_ret.mean():.3f}%, positive {(next_ret > 0).mean()*100:.0f}% (n={len(next_ret)})")


def analyze_session_volume(sym, df):
    """Volume by trading session."""
    df["hour"] = df["time"].dt.hour

    sessions = {
        "Asian (00-08 UTC)": (0, 8),
        "London (08-14 UTC)": (8, 14),
        "US (14-21 UTC)": (14, 21),
        "Evening (21-00 UTC)": (21, 24),
    }

    print(f"\n  {sym} Session Volume:")
    total_vol = df["volume"].sum()
    for name, (start, end) in sessions.items():
        mask = (df["hour"] >= start) & (df["hour"] < end)
        session_vol = df[mask]["volume"].sum()
        pct = session_vol / total_vol * 100 if total_vol > 0 else 0
        avg_range = df[mask]["range_pct"].mean() if "range_pct" in df.columns else 0
        print(f"    {name}: {pct:.0f}% of volume, avg range {avg_range:.2f}%")


def main():
    fetcher = DataFetcher()

    for sym, coin_id in SYMBOLS.items():
        df = fetcher.fetch_ohlcv(sym, coin_id, "1h")
        if df is None or df.empty:
            continue
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        price = df["close"].iloc[-1]
        print(f"\n{'=' * 50}")
        print(f"  {sym} DEEP MARKET STRUCTURE (${price:.2f})")
        print(f"{'=' * 50}")

        df["range_pct"] = (df["high"] - df["low"]) / df["close"] * 100
        analyze_volume_profile(sym, df)
        analyze_range_stats(sym, df)
        analyze_momentum_persistence(sym, df)
        analyze_session_volume(sym, df)


if __name__ == "__main__":
    main()
