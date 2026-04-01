"""
Stop-Loss Microstructure Analysis
Analyzes wick behavior, stop-hunt zones, and optimal SL placement
using 500 1h candles for HYPE, BTC, SOL.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from data.fetcher import DataFetcher

# CoinGecko IDs for fallback
SYMBOLS = {
    "HYPE": "hyperliquid",
    "BTC": "bitcoin",
    "SOL": "solana",
}

def fetch_data():
    """Fetch 500 1h candles for each symbol."""
    fetcher = DataFetcher(fresh=True)
    data = {}
    for sym, cg_id in SYMBOLS.items():
        print(f"\nFetching {sym} 1h candles...")
        df = fetcher.fetch_ohlcv(sym, cg_id, "1h")
        if df is not None and not df.empty:
            # Take last 500
            df = df.tail(500).reset_index(drop=True)
            data[sym] = df
            print(f"  Got {len(df)} candles. Last close: {df['close'].iloc[-1]:.2f}")
        else:
            print(f"  FAILED to fetch {sym}")
    return data


def wick_analysis(data: dict):
    """Analyze how far wicks extend beyond the body."""
    print("\n" + "="*80)
    print("1. WICK ANALYSIS — How far do wicks extend beyond the candle body?")
    print("="*80)

    for sym, df in data.items():
        body_top = df[['open', 'close']].max(axis=1)
        body_bot = df[['open', 'close']].min(axis=1)
        body_size = body_top - body_bot

        upper_wick = df['high'] - body_top
        lower_wick = body_bot - df['low']

        # As percentage of close price
        upper_wick_pct = (upper_wick / df['close']) * 100
        lower_wick_pct = (lower_wick / df['close']) * 100
        body_pct = (body_size / df['close']) * 100
        full_range_pct = ((df['high'] - df['low']) / df['close']) * 100

        print(f"\n--- {sym} ---")
        print(f"  Full candle range:  avg={full_range_pct.mean():.3f}%  median={full_range_pct.median():.3f}%  p75={full_range_pct.quantile(0.75):.3f}%  p95={full_range_pct.quantile(0.95):.3f}%")
        print(f"  Body size:          avg={body_pct.mean():.3f}%  median={body_pct.median():.3f}%")
        print(f"  Upper wick:         avg={upper_wick_pct.mean():.3f}%  median={upper_wick_pct.median():.3f}%  p75={upper_wick_pct.quantile(0.75):.3f}%  p95={upper_wick_pct.quantile(0.95):.3f}%")
        print(f"  Lower wick:         avg={lower_wick_pct.mean():.3f}%  median={lower_wick_pct.median():.3f}%  p75={lower_wick_pct.quantile(0.75):.3f}%  p95={lower_wick_pct.quantile(0.95):.3f}%")

        # What % of candles have wicks > various thresholds
        for thresh in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
            pct_lower = (lower_wick_pct > thresh).mean() * 100
            pct_upper = (upper_wick_pct > thresh).mean() * 100
            print(f"  Wicks > {thresh}%:  lower={pct_lower:.1f}% of candles  upper={pct_upper:.1f}% of candles")


def stop_hunt_analysis(data: dict):
    """Detect stop-hunt patterns: wick below prev low then close above it."""
    print("\n" + "="*80)
    print("2. STOP-HUNT ZONES — Wick below previous low, then close above")
    print("="*80)

    for sym, df in data.items():
        prev_low = df['low'].shift(1)
        prev_high = df['high'].shift(1)

        # Bullish stop hunt: wicks below prev low but closes above it
        bull_hunt = (df['low'] < prev_low) & (df['close'] > prev_low)
        # Bearish stop hunt: wicks above prev high but closes below it
        bear_hunt = (df['high'] > prev_high) & (df['close'] < prev_high)

        # Multi-candle: wick below lowest low of last 3/5 candles then close above
        low_3 = df['low'].rolling(3).min().shift(1)
        low_5 = df['low'].rolling(5).min().shift(1)
        high_3 = df['high'].rolling(3).max().shift(1)
        high_5 = df['high'].rolling(5).max().shift(1)

        bull_hunt_3 = (df['low'] < low_3) & (df['close'] > low_3)
        bull_hunt_5 = (df['low'] < low_5) & (df['close'] > low_5)
        bear_hunt_3 = (df['high'] > high_3) & (df['close'] < high_3)
        bear_hunt_5 = (df['high'] > high_5) & (df['close'] < high_5)

        valid = df.index[5:]  # skip first 5 for rolling windows

        print(f"\n--- {sym} ---")
        print(f"  Bullish stop-hunt (wick below prev low, close above):")
        print(f"    vs prev 1 candle low: {bull_hunt[valid].mean()*100:.1f}%")
        print(f"    vs prev 3 candle low: {bull_hunt_3[valid].mean()*100:.1f}%")
        print(f"    vs prev 5 candle low: {bull_hunt_5[valid].mean()*100:.1f}%")
        print(f"  Bearish stop-hunt (wick above prev high, close below):")
        print(f"    vs prev 1 candle high: {bear_hunt[valid].mean()*100:.1f}%")
        print(f"    vs prev 3 candle high: {bear_hunt_3[valid].mean()*100:.1f}%")
        print(f"    vs prev 5 candle high: {bear_hunt_5[valid].mean()*100:.1f}%")

        # How far below the prev low does the wick go before recovering?
        hunt_depth_pct = ((prev_low - df['low']) / df['close'] * 100).clip(lower=0)
        hunt_depth_when_hunting = hunt_depth_pct[bull_hunt]
        if len(hunt_depth_when_hunting) > 0:
            print(f"  Hunt depth (how far below prev low before reversing):")
            print(f"    avg={hunt_depth_when_hunting.mean():.3f}%  median={hunt_depth_when_hunting.median():.3f}%  p75={hunt_depth_when_hunting.quantile(0.75):.3f}%  max={hunt_depth_when_hunting.max():.3f}%")


def optimal_sl_simulation(data: dict):
    """Simulate SL widths and find optimal for maximizing expectancy."""
    print("\n" + "="*80)
    print("3. OPTIMAL SL WIDTH — Which SL % maximizes expectancy?")
    print("="*80)
    print("  Simulating: enter at close of each candle, SL at X%, TP at 2*SL (2:1 R:R)")
    print("  Check next 12 candles (12h horizon). If SL hit first = loss. If TP hit first = win.")

    sl_widths = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0]

    for sym, df in data.items():
        print(f"\n--- {sym} (LONG entries) ---")
        print(f"  {'SL%':>6s} {'WR%':>6s} {'Trades':>7s} {'AvgWin%':>8s} {'AvgLoss%':>9s} {'Expectancy':>11s} {'EV/trade%':>10s}")

        best_ev = -999
        best_sl = 0

        for sl_pct in sl_widths:
            wins = 0
            losses = 0
            total_win_pct = 0
            total_loss_pct = 0
            timeouts = 0

            tp_pct = sl_pct * 2  # 2:1 R:R

            for i in range(len(df) - 13):
                entry = df['close'].iloc[i]
                sl_price = entry * (1 - sl_pct/100)
                tp_price = entry * (1 + tp_pct/100)

                hit = False
                for j in range(1, 13):
                    candle = df.iloc[i + j]
                    if candle['low'] <= sl_price:
                        losses += 1
                        total_loss_pct += sl_pct
                        hit = True
                        break
                    if candle['high'] >= tp_price:
                        wins += 1
                        total_win_pct += tp_pct
                        hit = True
                        break
                if not hit:
                    # Close at end - calculate P/L
                    final = df['close'].iloc[i + 12]
                    pnl_pct = (final - entry) / entry * 100
                    if pnl_pct > 0:
                        wins += 1
                        total_win_pct += pnl_pct
                    else:
                        losses += 1
                        total_loss_pct += abs(pnl_pct)
                    timeouts += 1

            total = wins + losses
            if total == 0:
                continue
            wr = wins / total * 100
            avg_win = total_win_pct / max(wins, 1)
            avg_loss = total_loss_pct / max(losses, 1)
            ev = (wins * avg_win - losses * avg_loss) / total

            marker = ""
            if ev > best_ev:
                best_ev = ev
                best_sl = sl_pct
                marker = " <-- BEST"

            print(f"  {sl_pct:>5.1f}% {wr:>6.1f} {total:>7d} {avg_win:>7.3f}% {avg_loss:>8.3f}% {ev:>10.4f}% {ev:>9.4f}%{marker}")

        print(f"\n  >>> Best SL for {sym} LONG: {best_sl}% (EV={best_ev:.4f}% per trade)")

        # Now SHORT
        print(f"\n--- {sym} (SHORT entries) ---")
        print(f"  {'SL%':>6s} {'WR%':>6s} {'Trades':>7s} {'AvgWin%':>8s} {'AvgLoss%':>9s} {'Expectancy':>11s} {'EV/trade%':>10s}")

        best_ev = -999
        best_sl = 0

        for sl_pct in sl_widths:
            wins = 0
            losses = 0
            total_win_pct = 0
            total_loss_pct = 0

            tp_pct = sl_pct * 2

            for i in range(len(df) - 13):
                entry = df['close'].iloc[i]
                sl_price = entry * (1 + sl_pct/100)
                tp_price = entry * (1 - tp_pct/100)

                hit = False
                for j in range(1, 13):
                    candle = df.iloc[i + j]
                    if candle['high'] >= sl_price:
                        losses += 1
                        total_loss_pct += sl_pct
                        hit = True
                        break
                    if candle['low'] <= tp_price:
                        wins += 1
                        total_win_pct += tp_pct
                        hit = True
                        break
                if not hit:
                    final = df['close'].iloc[i + 12]
                    pnl_pct = (entry - final) / entry * 100
                    if pnl_pct > 0:
                        wins += 1
                        total_win_pct += pnl_pct
                    else:
                        losses += 1
                        total_loss_pct += abs(pnl_pct)

            total = wins + losses
            if total == 0:
                continue
            wr = wins / total * 100
            avg_win = total_win_pct / max(wins, 1)
            avg_loss = total_loss_pct / max(losses, 1)
            ev = (wins * avg_win - losses * avg_loss) / total

            marker = ""
            if ev > best_ev:
                best_ev = ev
                best_sl = sl_pct
                marker = " <-- BEST"

            print(f"  {sl_pct:>5.1f}% {wr:>6.1f} {total:>7d} {avg_win:>7.3f}% {avg_loss:>8.3f}% {ev:>10.4f}% {ev:>9.4f}%{marker}")

        print(f"\n  >>> Best SL for {sym} SHORT: {best_sl}% (EV={best_ev:.4f}% per trade)")


def dynamic_sl_analysis(data: dict):
    """Compare fixed SL vs swing-low-based SL."""
    print("\n" + "="*80)
    print("4. DYNAMIC SL — Swing-low/high based vs fixed ATR")
    print("="*80)
    print("  Comparing: fixed 1.5% SL vs SL placed below the lowest low of last 5 candles + 0.1% buffer")

    for sym, df in data.items():
        # Calculate ATR for reference
        tr = pd.DataFrame({
            'hl': df['high'] - df['low'],
            'hc': (df['high'] - df['close'].shift(1)).abs(),
            'lc': (df['low'] - df['close'].shift(1)).abs()
        }).max(axis=1)
        atr = tr.rolling(14).mean()
        atr_pct = (atr / df['close']) * 100

        print(f"\n--- {sym} ---")
        print(f"  ATR(14) as % of price:  avg={atr_pct.dropna().mean():.3f}%  current={atr_pct.iloc[-1]:.3f}%")
        print(f"  Current ATR-based SL (2.0x ATR): {atr_pct.iloc[-1] * 2:.3f}%")

        # Swing low based SL for LONG
        swing_low_5 = df['low'].rolling(5).min().shift(1)
        swing_sl_dist_pct = ((df['close'] - swing_low_5) / df['close'] * 100)

        # Wick cluster: find where the densest cluster of lows is
        # Use lower wick tips as support levels

        print(f"\n  Swing-low(5) SL distance:  avg={swing_sl_dist_pct.dropna().mean():.3f}%  median={swing_sl_dist_pct.dropna().median():.3f}%  p75={swing_sl_dist_pct.dropna().quantile(0.75):.3f}%")

        # Simulate: fixed 1.5% vs swing-low + buffer
        fixed_sl_pct = 1.5
        buffer_pct = 0.15  # 0.15% below swing low

        methods = {
            f"Fixed {fixed_sl_pct}%": [],
            "Swing-low(5)+buffer": [],
            "Swing-low(3)+buffer": [],
            "ATR(14) x 1.5": [],
            "ATR(14) x 2.0": [],
        }

        swing_low_3 = df['low'].rolling(3).min().shift(1)

        for i in range(14, len(df) - 13):
            entry = df['close'].iloc[i]

            sls = {
                f"Fixed {fixed_sl_pct}%": entry * (1 - fixed_sl_pct/100),
                "Swing-low(5)+buffer": swing_low_5.iloc[i] * (1 - buffer_pct/100) if pd.notna(swing_low_5.iloc[i]) else entry * (1 - fixed_sl_pct/100),
                "Swing-low(3)+buffer": swing_low_3.iloc[i] * (1 - buffer_pct/100) if pd.notna(swing_low_3.iloc[i]) else entry * (1 - fixed_sl_pct/100),
                "ATR(14) x 1.5": entry - atr.iloc[i] * 1.5 if pd.notna(atr.iloc[i]) else entry * (1 - fixed_sl_pct/100),
                "ATR(14) x 2.0": entry - atr.iloc[i] * 2.0 if pd.notna(atr.iloc[i]) else entry * (1 - fixed_sl_pct/100),
            }

            for method_name, sl_price in sls.items():
                sl_dist = (entry - sl_price) / entry * 100
                tp_price = entry * (1 + sl_dist * 2 / 100)  # 2:1 R:R

                result = 0  # timeout
                for j in range(1, 13):
                    candle = df.iloc[i + j]
                    if candle['low'] <= sl_price:
                        result = -sl_dist
                        break
                    if candle['high'] >= tp_price:
                        result = sl_dist * 2
                        break

                if result == 0:
                    final = df['close'].iloc[i + 12]
                    result = (final - entry) / entry * 100

                methods[method_name].append(result)

        print(f"\n  LONG simulation (12h horizon, 2:1 R:R):")
        print(f"  {'Method':<25s} {'WR%':>6s} {'AvgSL%':>7s} {'TotalPnL%':>10s} {'EV/trade%':>10s} {'Trades':>7s}")

        for method_name, results in methods.items():
            results = np.array(results)
            wins = (results > 0).sum()
            total = len(results)
            wr = wins / total * 100
            total_pnl = results.sum()
            ev = results.mean()

            # Calculate avg SL width used
            avg_sl = np.mean(np.abs(results[results < 0])) if (results < 0).any() else 0

            print(f"  {method_name:<25s} {wr:>6.1f} {avg_sl:>6.2f}% {total_pnl:>9.2f}% {ev:>9.4f}% {total:>7d}")


def sol_sell_analysis(data: dict):
    """Analyze optimal SL for current SOL SELL position."""
    print("\n" + "="*80)
    print("5. SOL SELL POSITION — Where should the SL be?")
    print("="*80)

    if "SOL" not in data:
        print("  No SOL data available!")
        return

    df = data["SOL"]
    current_price = df['close'].iloc[-1]

    # Calculate ATR
    tr = pd.DataFrame({
        'hl': df['high'] - df['low'],
        'hc': (df['high'] - df['close'].shift(1)).abs(),
        'lc': (df['low'] - df['close'].shift(1)).abs()
    }).max(axis=1)
    atr = tr.rolling(14).mean()
    current_atr = atr.iloc[-1]
    atr_pct = current_atr / current_price * 100

    print(f"  Current SOL price: ${current_price:.2f}")
    print(f"  Current ATR(14): ${current_atr:.2f} ({atr_pct:.2f}%)")
    print(f"  Mentioned SL: $84.58")
    sl_mentioned = 84.58
    sl_dist_pct = (sl_mentioned - current_price) / current_price * 100
    print(f"  SL distance from current: {sl_dist_pct:.2f}% ({sl_dist_pct/atr_pct:.1f}x ATR)")

    # Recent highs (resistance for SHORT)
    recent_20 = df.tail(20)
    recent_high = recent_20['high'].max()
    recent_high_3 = df.tail(3)['high'].max()
    recent_high_5 = df.tail(5)['high'].max()
    swing_high_10 = df.tail(10)['high'].max()

    print(f"\n  Recent resistance levels (for SHORT SL placement):")
    print(f"    Last 3 candle high:  ${recent_high_3:.2f} ({(recent_high_3-current_price)/current_price*100:.2f}% above)")
    print(f"    Last 5 candle high:  ${recent_high_5:.2f} ({(recent_high_5-current_price)/current_price*100:.2f}% above)")
    print(f"    Last 10 candle high: ${swing_high_10:.2f} ({(swing_high_10-current_price)/current_price*100:.2f}% above)")
    print(f"    Last 20 candle high: ${recent_high:.2f} ({(recent_high-current_price)/current_price*100:.2f}% above)")

    # Upper wick behavior (relevant for SHORT SL)
    body_top = df[['open', 'close']].max(axis=1)
    upper_wick_pct = ((df['high'] - body_top) / df['close'] * 100)

    print(f"\n  Upper wick statistics (noise that would hit tight SHORT SLs):")
    print(f"    avg={upper_wick_pct.mean():.3f}%  p75={upper_wick_pct.quantile(0.75):.3f}%  p90={upper_wick_pct.quantile(0.90):.3f}%  p95={upper_wick_pct.quantile(0.95):.3f}%")

    # Recommended SL placements for SHORT
    recommendations = {
        "Swing high(5) + 0.2% buffer": recent_high_5 * 1.002,
        "Swing high(10) + 0.2% buffer": swing_high_10 * 1.002,
        "ATR x 1.5 above entry": current_price + current_atr * 1.5,
        "ATR x 2.0 above entry": current_price + current_atr * 2.0,
        f"Current SL ($84.58)": 84.58,
    }

    print(f"\n  SL placement options for SOL SHORT:")
    print(f"  {'Method':<35s} {'SL Price':>10s} {'Dist%':>7s} {'ATR mult':>9s}")
    for name, sl_price in recommendations.items():
        dist = (sl_price - current_price) / current_price * 100
        atr_m = (sl_price - current_price) / current_atr
        print(f"  {name:<35s} ${sl_price:>9.2f} {dist:>6.2f}% {atr_m:>8.1f}x")


def wick_cluster_analysis(data: dict):
    """Find price levels where wicks cluster (potential support/resistance)."""
    print("\n" + "="*80)
    print("BONUS: WICK CLUSTER ANALYSIS — Where do wicks concentrate?")
    print("="*80)

    for sym, df in data.items():
        last_50 = df.tail(50)
        price = last_50['close'].iloc[-1]

        # Collect all wick tips (lows) as potential support
        lows = last_50['low'].values
        highs = last_50['high'].values

        # Bin them into price buckets (0.2% width)
        bucket_width_pct = 0.2
        bucket_width = price * bucket_width_pct / 100

        min_price = min(lows.min(), highs.min())
        max_price = max(lows.max(), highs.max())

        buckets = np.arange(min_price, max_price + bucket_width, bucket_width)

        low_counts, _ = np.histogram(lows, bins=buckets)
        high_counts, _ = np.histogram(highs, bins=buckets)

        # Find top support clusters (most frequent low zones)
        top_support_idx = np.argsort(low_counts)[-5:][::-1]
        top_resist_idx = np.argsort(high_counts)[-5:][::-1]

        print(f"\n--- {sym} (last 50 candles) ---")
        print(f"  Current price: ${price:.2f}")
        print(f"\n  Top support zones (wick-low clusters):")
        for idx in top_support_idx:
            level = (buckets[idx] + buckets[idx+1]) / 2
            dist = (price - level) / price * 100
            if low_counts[idx] > 1:
                print(f"    ${level:.2f} ({low_counts[idx]} touches, {dist:.2f}% below)")

        print(f"\n  Top resistance zones (wick-high clusters):")
        for idx in top_resist_idx:
            level = (buckets[idx] + buckets[idx+1]) / 2
            dist = (level - price) / price * 100
            if high_counts[idx] > 1:
                print(f"    ${level:.2f} ({high_counts[idx]} touches, {dist:.2f}% above)")


if __name__ == "__main__":
    print("="*80)
    print("STOP-LOSS MICROSTRUCTURE ANALYSIS")
    print("="*80)

    data = fetch_data()

    if not data:
        print("ERROR: No data fetched!")
        sys.exit(1)

    wick_analysis(data)
    stop_hunt_analysis(data)
    optimal_sl_simulation(data)
    dynamic_sl_analysis(data)
    sol_sell_analysis(data)
    wick_cluster_analysis(data)

    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
