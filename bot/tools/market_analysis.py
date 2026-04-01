#!/usr/bin/env python3
"""
Momentum & Order Flow Analysis
Fetches 500 1h candles for HYPE, BTC, SOL and runs comprehensive analysis.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from data.fetcher import DataFetcher

SYMBOLS = {
    "HYPE": "hyperliquid",
    "BTC": "bitcoin",
    "SOL": "solana",
}


def roc(series, periods):
    """Rate of change as percentage."""
    return ((series.iloc[-1] - series.iloc[-periods]) / series.iloc[-periods]) * 100


def compute_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_adx(df, period=14):
    """ADX, +DI, -DI."""
    high, low, close = df["high"], df["low"], df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.rolling(period).mean()

    return adx, plus_di, minus_di


def find_support_resistance(df, n_candles=100):
    """Find key S/R levels from last n candles using pivot clustering."""
    recent = df.tail(n_candles)
    highs = recent["high"].values
    lows = recent["low"].values
    closes = recent["close"].values

    # Collect pivot points
    pivots = []
    for i in range(2, len(recent) - 2):
        # Swing high
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            pivots.append(("R", highs[i]))
        # Swing low
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            pivots.append(("S", lows[i]))

    current_price = closes[-1]

    # Cluster nearby levels (within 0.5%)
    supports = sorted([p[1] for p in pivots if p[1] < current_price], reverse=True)
    resistances = sorted([p[1] for p in pivots if p[1] >= current_price])

    # Cluster
    def cluster(levels, threshold_pct=0.5):
        if not levels:
            return []
        clusters = []
        current_cluster = [levels[0]]
        for lvl in levels[1:]:
            if abs(lvl - current_cluster[0]) / current_cluster[0] * 100 < threshold_pct:
                current_cluster.append(lvl)
            else:
                clusters.append(np.mean(current_cluster))
                current_cluster = [lvl]
        clusters.append(np.mean(current_cluster))
        return clusters

    return cluster(supports)[:3], cluster(resistances)[:3]


def volume_analysis(df, lookback=50):
    """Analyze volume on up vs down moves."""
    recent = df.tail(lookback).copy()
    recent["change"] = recent["close"] - recent["open"]
    recent["is_up"] = recent["change"] > 0

    avg_vol = recent["volume"].mean()
    current_vol = recent["volume"].iloc[-1]
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

    up_vol = recent.loc[recent["is_up"], "volume"].mean() if recent["is_up"].any() else 0
    down_vol = recent.loc[~recent["is_up"], "volume"].mean() if (~recent["is_up"]).any() else 0

    # VWAP
    recent["vwap"] = (recent["volume"] * (recent["high"] + recent["low"] + recent["close"]) / 3).cumsum() / recent["volume"].cumsum()
    vwap = recent["vwap"].iloc[-1]

    # Recent volume trend (last 10 vs prior 40)
    recent_vol = recent["volume"].tail(10).mean()
    prior_vol = recent["volume"].head(40).mean()
    vol_trend = ((recent_vol - prior_vol) / prior_vol * 100) if prior_vol > 0 else 0

    return {
        "current_vol": current_vol,
        "avg_vol": avg_vol,
        "vol_ratio": vol_ratio,
        "up_vol_avg": up_vol,
        "down_vol_avg": down_vol,
        "sell_pressure_ratio": down_vol / up_vol if up_vol > 0 else float('inf'),
        "vwap": vwap,
        "vol_trend_pct": vol_trend,
    }


def mean_reversion_analysis(df, period=20):
    """Z-score from moving average."""
    closes = df["close"]
    ma = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    current = closes.iloc[-1]
    z_score = (current - ma.iloc[-1]) / std.iloc[-1] if std.iloc[-1] > 0 else 0
    distance_pct = (current - ma.iloc[-1]) / ma.iloc[-1] * 100

    return {
        "ma20": ma.iloc[-1],
        "current": current,
        "z_score": z_score,
        "distance_pct": distance_pct,
        "std": std.iloc[-1],
    }


def check_bearish_exhaustion(df, lookback=30):
    """Check for signs of downtrend exhaustion (for SOL SELL analysis)."""
    recent = df.tail(lookback).copy()
    closes = recent["close"]
    lows = recent["low"]
    volumes = recent["volume"]

    rsi = compute_rsi(df["close"], 14)
    recent_rsi = rsi.tail(lookback)

    # Check for higher lows
    swing_lows = []
    for i in range(2, len(lows) - 2):
        if lows.iloc[i] < lows.iloc[i-1] and lows.iloc[i] < lows.iloc[i-2] and lows.iloc[i] < lows.iloc[i+1] and lows.iloc[i] < lows.iloc[i+2]:
            swing_lows.append((i, lows.iloc[i]))

    higher_lows = False
    if len(swing_lows) >= 2:
        higher_lows = swing_lows[-1][1] > swing_lows[-2][1]

    # Volume declining on selloffs
    down_candles = recent[recent["close"] < recent["open"]]
    if len(down_candles) >= 10:
        first_half_down_vol = down_candles.head(len(down_candles)//2)["volume"].mean()
        second_half_down_vol = down_candles.tail(len(down_candles)//2)["volume"].mean()
        declining_sell_volume = second_half_down_vol < first_half_down_vol
    else:
        declining_sell_volume = False
        first_half_down_vol = 0
        second_half_down_vol = 0

    # RSI bullish divergence: price making lower lows but RSI making higher lows
    price_lower_low = False
    rsi_higher_low = False
    if len(swing_lows) >= 2:
        price_lower_low = swing_lows[-1][1] < swing_lows[-2][1]
        idx1 = swing_lows[-2][0]
        idx2 = swing_lows[-1][0]
        if idx1 < len(recent_rsi) and idx2 < len(recent_rsi):
            rsi_val1 = recent_rsi.iloc[idx1] if idx1 < len(recent_rsi) else None
            rsi_val2 = recent_rsi.iloc[idx2] if idx2 < len(recent_rsi) else None
            if rsi_val1 is not None and rsi_val2 is not None:
                rsi_higher_low = rsi_val2 > rsi_val1

    bullish_divergence = price_lower_low and rsi_higher_low

    return {
        "higher_lows": higher_lows,
        "declining_sell_volume": declining_sell_volume,
        "sell_vol_first_half": first_half_down_vol,
        "sell_vol_second_half": second_half_down_vol,
        "bullish_divergence": bullish_divergence,
        "current_rsi": rsi.iloc[-1],
        "rsi_5_ago": rsi.iloc[-5] if len(rsi) >= 5 else None,
        "swing_lows": swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows,
    }


def analyze_asset(symbol, df):
    """Run full analysis on one asset."""
    print(f"\n{'='*70}")
    print(f"  {symbol} ANALYSIS  |  Current Price: ${df['close'].iloc[-1]:,.4f}")
    print(f"  Candles: {len(df)} | Range: {df.index[0]} to {df.index[-1]}")
    print(f"{'='*70}")

    closes = df["close"]

    # 1. MOMENTUM
    print(f"\n--- 1. MOMENTUM SCORE ---")
    periods = {"3h": 3, "6h": 6, "12h": 12, "24h": 24}
    rocs = {}
    for label, p in periods.items():
        if len(closes) > p:
            r = roc(closes, p)
            rocs[label] = r
            direction = "UP" if r > 0 else "DOWN"
            print(f"  ROC {label:>4s}: {r:+.3f}% ({direction})")

    # Acceleration: is short-term ROC stronger than longer-term?
    if "3h" in rocs and "12h" in rocs:
        accel = abs(rocs["3h"]) > abs(rocs["12h"]) / 4
        momentum_dir = "accelerating" if accel else "decelerating"
        print(f"  Momentum: {momentum_dir.upper()}")

    # 2. VOLUME ANALYSIS
    print(f"\n--- 2. VOLUME ANALYSIS ---")
    va = volume_analysis(df)
    print(f"  Current vol / Avg vol: {va['vol_ratio']:.2f}x")
    print(f"  Avg UP candle vol:   {va['up_vol_avg']:,.0f}")
    print(f"  Avg DOWN candle vol: {va['down_vol_avg']:,.0f}")
    print(f"  Sell pressure ratio: {va['sell_pressure_ratio']:.2f}x  (>1 = more selling)")
    print(f"  VWAP (50-period):    ${va['vwap']:,.4f}")
    price_vs_vwap = "ABOVE" if closes.iloc[-1] > va['vwap'] else "BELOW"
    print(f"  Price vs VWAP:       {price_vs_vwap}")
    print(f"  Volume trend (recent vs prior): {va['vol_trend_pct']:+.1f}%")

    # 3. SUPPORT/RESISTANCE
    print(f"\n--- 3. SUPPORT/RESISTANCE (last 100 candles) ---")
    supports, resistances = find_support_resistance(df)
    current = closes.iloc[-1]
    print(f"  Supports:    {['$'+f'{s:,.4f}' for s in supports[:3]]}")
    print(f"  Resistances: {['$'+f'{r:,.4f}' for r in resistances[:3]]}")
    if supports:
        dist_to_support = (current - supports[0]) / current * 100
        print(f"  Distance to nearest support: {dist_to_support:.2f}%")
    if resistances:
        dist_to_resistance = (resistances[0] - current) / current * 100
        print(f"  Distance to nearest resistance: {dist_to_resistance:.2f}%")

    # 4. MEAN REVERSION
    print(f"\n--- 4. MEAN REVERSION ---")
    mr = mean_reversion_analysis(df)
    print(f"  20-period MA: ${mr['ma20']:,.4f}")
    print(f"  Current:      ${mr['current']:,.4f}")
    print(f"  Z-score:      {mr['z_score']:+.2f}")
    print(f"  Distance:     {mr['distance_pct']:+.2f}%")
    if abs(mr['z_score']) > 2:
        print(f"  *** HIGH Z-SCORE: Mean reversion LIKELY ***")
    elif abs(mr['z_score']) > 1:
        print(f"  ** Moderate z-score: Mean reversion possible **")
    else:
        print(f"  Z-score normal range - no strong mean reversion signal")

    # 5. TREND STRENGTH
    print(f"\n--- 5. TREND STRENGTH (ADX) ---")
    adx, plus_di, minus_di = compute_adx(df)
    adx_val = adx.iloc[-1]
    pdi = plus_di.iloc[-1]
    mdi = minus_di.iloc[-1]
    print(f"  ADX:  {adx_val:.1f}  ({'STRONG trend' if adx_val > 25 else 'WEAK/ranging' if adx_val < 20 else 'moderate trend'})")
    print(f"  +DI:  {pdi:.1f}")
    print(f"  -DI:  {mdi:.1f}")
    print(f"  Spread: {pdi - mdi:+.1f}  ({'BULLISH' if pdi > mdi else 'BEARISH'})")

    # ADX trend
    adx_5ago = adx.iloc[-5] if len(adx) >= 5 else adx_val
    print(f"  ADX 5h ago: {adx_5ago:.1f} -> now {adx_val:.1f}  ({'strengthening' if adx_val > adx_5ago else 'weakening'})")

    # RSI
    rsi = compute_rsi(closes)
    print(f"  RSI(14): {rsi.iloc[-1]:.1f}")

    return {
        "rocs": rocs,
        "volume": va,
        "supports": supports,
        "resistances": resistances,
        "mean_rev": mr,
        "adx": adx_val,
        "plus_di": pdi,
        "minus_di": mdi,
        "rsi": rsi.iloc[-1],
    }


def main():
    print("Fetching 500 1h candles for HYPE, BTC, SOL...")
    fetcher = DataFetcher(fresh=True)

    data = {}
    for symbol, coin_id in SYMBOLS.items():
        print(f"  Fetching {symbol}...")
        df = fetcher.fetch_ohlcv(symbol, coin_id, "1h")
        if df is not None and not df.empty:
            data[symbol] = df
            print(f"  {symbol}: {len(df)} candles fetched, last close: ${df['close'].iloc[-1]:,.4f}")
        else:
            print(f"  WARNING: Failed to fetch {symbol}")

    results = {}
    for symbol, df in data.items():
        results[symbol] = analyze_asset(symbol, df)

    # 6. SOL-specific bearish exhaustion check
    if "SOL" in data:
        print(f"\n{'='*70}")
        print(f"  SOL SELL POSITION - EXHAUSTION ANALYSIS")
        print(f"{'='*70}")
        exhaust = check_bearish_exhaustion(data["SOL"], lookback=48)
        print(f"  Higher lows forming?       {'YES - CAUTION' if exhaust['higher_lows'] else 'NO'}")
        print(f"  Declining sell volume?      {'YES - EXHAUSTION SIGNAL' if exhaust['declining_sell_volume'] else 'NO'}")
        if exhaust['sell_vol_first_half'] > 0:
            print(f"    Sell vol (early):  {exhaust['sell_vol_first_half']:,.0f}")
            print(f"    Sell vol (recent): {exhaust['sell_vol_second_half']:,.0f}")
        print(f"  RSI bullish divergence?    {'YES - DANGER' if exhaust['bullish_divergence'] else 'NO'}")
        print(f"  Current RSI: {exhaust['current_rsi']:.1f}")
        if exhaust['rsi_5_ago']:
            print(f"  RSI 5h ago:  {exhaust['rsi_5_ago']:.1f}")

        danger_signals = sum([
            exhaust['higher_lows'],
            exhaust['declining_sell_volume'],
            exhaust['bullish_divergence'],
            exhaust['current_rsi'] > 45,
        ])
        print(f"\n  Exhaustion danger signals: {danger_signals}/4")
        if danger_signals >= 3:
            print(f"  *** HIGH RISK: Downtrend likely exhausting. Consider tightening stop or closing. ***")
        elif danger_signals >= 2:
            print(f"  ** MODERATE RISK: Some exhaustion signs. Watch closely. **")
        else:
            print(f"  Downtrend appears intact. SOL SELL can continue.")

    # RECOMMENDATIONS
    print(f"\n{'='*70}")
    print(f"  RECOMMENDATIONS")
    print(f"{'='*70}")

    for symbol in SYMBOLS:
        if symbol not in results:
            continue
        r = results[symbol]

        signals = []

        # Momentum signal
        if "24h" in r["rocs"]:
            if r["rocs"]["24h"] > 1:
                signals.append(("BUY", "24h momentum positive"))
            elif r["rocs"]["24h"] < -1:
                signals.append(("SELL", "24h momentum negative"))
            else:
                signals.append(("HOLD", "24h momentum flat"))

        # Trend signal
        if r["plus_di"] > r["minus_di"] and r["adx"] > 20:
            signals.append(("BUY", f"ADX={r['adx']:.0f} bullish trend"))
        elif r["minus_di"] > r["plus_di"] and r["adx"] > 20:
            signals.append(("SELL", f"ADX={r['adx']:.0f} bearish trend"))
        else:
            signals.append(("HOLD", f"ADX={r['adx']:.0f} weak trend"))

        # Volume signal
        if r["volume"]["sell_pressure_ratio"] > 1.2:
            signals.append(("SELL", f"sell pressure {r['volume']['sell_pressure_ratio']:.2f}x"))
        elif r["volume"]["sell_pressure_ratio"] < 0.8:
            signals.append(("BUY", f"buy pressure dominant"))

        # Mean reversion signal
        if r["mean_rev"]["z_score"] > 1.5:
            signals.append(("SELL", f"z={r['mean_rev']['z_score']:.1f} overbought"))
        elif r["mean_rev"]["z_score"] < -1.5:
            signals.append(("BUY", f"z={r['mean_rev']['z_score']:.1f} oversold"))

        # RSI signal
        if r["rsi"] > 70:
            signals.append(("SELL", f"RSI={r['rsi']:.0f} overbought"))
        elif r["rsi"] < 30:
            signals.append(("BUY", f"RSI={r['rsi']:.0f} oversold"))

        buy_count = sum(1 for s in signals if s[0] == "BUY")
        sell_count = sum(1 for s in signals if s[0] == "SELL")
        total = len(signals)

        if buy_count > sell_count:
            rec = "BUY"
            confidence = buy_count / total * 100
        elif sell_count > buy_count:
            rec = "SELL"
            confidence = sell_count / total * 100
        else:
            rec = "HOLD"
            confidence = 50

        print(f"\n  {symbol}: {rec} (confidence: {confidence:.0f}%)")
        for action, reason in signals:
            print(f"    [{action:4s}] {reason}")


if __name__ == "__main__":
    main()
