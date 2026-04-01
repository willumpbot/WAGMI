"""
Overbought market level analysis — fetch 500 1h candles for HYPE, BTC, SOL
and compute key support/resistance levels, RSI-based entry optimization.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from data.fetcher import DataFetcher

# ─── Technical Indicators ────────────────────────────────────────────

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_bb(series, period=20, std_mult=2.0):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    return sma, sma + std_mult * std, sma - std_mult * std

def calc_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# ─── RSI Backtest ────────────────────────────────────────────────────

def backtest_rsi_shorts(df, rsi, atr, rsi_threshold):
    """Enter SHORT when RSI crosses above threshold. SL = high + 1*ATR, TP = EMA20."""
    ema20 = calc_ema(df['close'], 20)
    trades = []
    in_trade = False
    entry_price = sl = tp = 0

    for i in range(1, len(df)):
        if not in_trade:
            # Entry: RSI crosses above threshold
            if rsi.iloc[i] > rsi_threshold and rsi.iloc[i-1] <= rsi_threshold:
                entry_price = df['close'].iloc[i]
                sl = df['high'].iloc[i] + atr.iloc[i]
                tp = ema20.iloc[i]
                if tp >= entry_price:  # Skip if TP is above entry (no profit)
                    continue
                in_trade = True
        else:
            # Check SL/TP hit
            if df['high'].iloc[i] >= sl:
                trades.append({'pnl': -(sl - entry_price) / entry_price, 'win': False})
                in_trade = False
            elif df['low'].iloc[i] <= tp:
                trades.append({'pnl': (entry_price - tp) / entry_price, 'win': True})
                in_trade = False

    if not trades:
        return {'count': 0, 'wr': 0, 'avg_rr': 0, 'total_pnl': 0}

    wins = sum(1 for t in trades if t['win'])
    return {
        'count': len(trades),
        'wr': wins / len(trades) * 100,
        'avg_pnl': np.mean([t['pnl'] for t in trades]) * 100,
        'total_pnl': sum(t['pnl'] for t in trades) * 100,
    }

def backtest_rsi_longs(df, rsi, atr, rsi_threshold):
    """Enter LONG when RSI crosses below threshold. SL = low - 1*ATR, TP = EMA20."""
    ema20 = calc_ema(df['close'], 20)
    trades = []
    in_trade = False
    entry_price = sl = tp = 0

    for i in range(1, len(df)):
        if not in_trade:
            if rsi.iloc[i] < rsi_threshold and rsi.iloc[i-1] >= rsi_threshold:
                entry_price = df['close'].iloc[i]
                sl = df['low'].iloc[i] - atr.iloc[i]
                tp = ema20.iloc[i]
                if tp <= entry_price:
                    continue
                in_trade = True
        else:
            if df['low'].iloc[i] <= sl:
                trades.append({'pnl': -(entry_price - sl) / entry_price, 'win': False})
                in_trade = False
            elif df['high'].iloc[i] >= tp:
                trades.append({'pnl': (tp - entry_price) / entry_price, 'win': True})
                in_trade = False

    if not trades:
        return {'count': 0, 'wr': 0, 'avg_rr': 0, 'total_pnl': 0}

    wins = sum(1 for t in trades if t['win'])
    return {
        'count': len(trades),
        'wr': wins / len(trades) * 100,
        'avg_pnl': np.mean([t['pnl'] for t in trades]) * 100,
        'total_pnl': sum(t['pnl'] for t in trades) * 100,
    }

def backtest_multi_overbought(dfs_dict):
    """When ALL 3 assets have RSI > 65 simultaneously, what happens in the next 6 candles?"""
    # Align by index
    rsis = {}
    closes = {}
    for sym, df in dfs_dict.items():
        rsis[sym] = calc_rsi(df['close'], 14)
        closes[sym] = df['close']

    # Find bars where all 3 are overbought
    results = []
    syms = list(dfs_dict.keys())
    min_len = min(len(rsis[s]) for s in syms)

    for i in range(20, min_len - 6):
        all_ob = all(rsis[s].iloc[i] > 65 for s in syms)
        if all_ob:
            changes = {}
            for s in syms:
                future_close = closes[s].iloc[min(i+6, min_len-1)]
                current_close = closes[s].iloc[i]
                changes[s] = (future_close - current_close) / current_close * 100
            results.append(changes)

    return results

# ─── Main ────────────────────────────────────────────────────────────

def main():
    fetcher = DataFetcher(fresh=True)

    symbols = {
        'BTC': 'bitcoin',
        'SOL': 'solana',
        'HYPE': 'hyperliquid',
    }

    print("=" * 80)
    print("OVERBOUGHT MARKET LEVEL ANALYSIS")
    print("=" * 80)

    dfs = {}
    for sym, cg_id in symbols.items():
        print(f"\nFetching 500 1h candles for {sym}...")
        df = fetcher.fetch_ohlcv(sym, cg_id, "1h")
        if df is None or df.empty:
            print(f"  ERROR: No data for {sym}")
            continue
        print(f"  Got {len(df)} candles, latest: {df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else 'N/A'}")
        dfs[sym] = df

    print("\n" + "=" * 80)

    for sym, df in dfs.items():
        print(f"\n{'='*80}")
        print(f"  {sym} ANALYSIS")
        print(f"{'='*80}")

        close = df['close']
        rsi = calc_rsi(close, 14)
        atr = calc_atr(df, 14)
        ema20 = calc_ema(close, 20)
        ema50 = calc_ema(close, 50)
        bb_mid, bb_upper, bb_lower = calc_bb(close, 20, 2.0)

        current_price = close.iloc[-1]
        current_rsi = rsi.iloc[-1]
        current_atr = atr.iloc[-1]
        high_24h = df['high'].iloc[-24:].max()
        low_24h = df['low'].iloc[-24:].min()

        print(f"\n--- CURRENT STATE ---")
        print(f"  Price:      ${current_price:.4f}")
        print(f"  RSI(14):    {current_rsi:.1f}")
        print(f"  ATR(14):    ${current_atr:.4f} ({current_atr/current_price*100:.2f}%)")
        print(f"  EMA20:      ${ema20.iloc[-1]:.4f}")
        print(f"  EMA50:      ${ema50.iloc[-1]:.4f}")
        print(f"  BB Upper:   ${bb_upper.iloc[-1]:.4f}")
        print(f"  BB Mid:     ${bb_mid.iloc[-1]:.4f}")
        print(f"  BB Lower:   ${bb_lower.iloc[-1]:.4f}")
        print(f"  24h High:   ${high_24h:.4f}")
        print(f"  24h Low:    ${low_24h:.4f}")

        # Price position relative to bands
        bb_position = (current_price - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1]) * 100
        print(f"  BB Position: {bb_position:.0f}% (0=lower, 100=upper)")

        print(f"\n--- RESISTANCE (SHORT entries) ---")
        print(f"  R1: BB Upper     = ${bb_upper.iloc[-1]:.4f}  (distance: {(bb_upper.iloc[-1]-current_price)/current_price*100:+.2f}%)")
        print(f"  R2: 24h High     = ${high_24h:.4f}  (distance: {(high_24h-current_price)/current_price*100:+.2f}%)")
        r3 = high_24h + 0.5 * current_atr
        print(f"  R3: High+0.5*ATR = ${r3:.4f}  (distance: {(r3-current_price)/current_price*100:+.2f}%)")

        print(f"\n--- SUPPORT (BUY entries) ---")
        print(f"  S1: EMA20        = ${ema20.iloc[-1]:.4f}  (distance: {(ema20.iloc[-1]-current_price)/current_price*100:+.2f}%)")
        print(f"  S2: BB Lower     = ${bb_lower.iloc[-1]:.4f}  (distance: {(bb_lower.iloc[-1]-current_price)/current_price*100:+.2f}%)")
        print(f"  S3: EMA50        = ${ema50.iloc[-1]:.4f}  (distance: {(ema50.iloc[-1]-current_price)/current_price*100:+.2f}%)")
        print(f"  S4: 24h Low      = ${low_24h:.4f}  (distance: {(low_24h-current_price)/current_price*100:+.2f}%)")

        # RSI backtest for optimal SHORT entry
        print(f"\n--- RSI SHORT BACKTEST (500 1h candles) ---")
        print(f"  {'RSI Threshold':>15} {'Trades':>8} {'Win%':>8} {'Avg PnL%':>10} {'Total PnL%':>12}")
        best_short_rsi = None
        best_short_total = -999
        for rsi_thresh in [65, 70, 75, 80, 85]:
            result = backtest_rsi_shorts(df, rsi, atr, rsi_thresh)
            if result['count'] > 0:
                print(f"  {rsi_thresh:>15} {result['count']:>8} {result['wr']:>7.1f}% {result['avg_pnl']:>9.2f}% {result['total_pnl']:>11.2f}%")
                if result['total_pnl'] > best_short_total and result['count'] >= 2:
                    best_short_total = result['total_pnl']
                    best_short_rsi = rsi_thresh
            else:
                print(f"  {rsi_thresh:>15} {'no trades':>8}")

        if best_short_rsi:
            print(f"  >> Best SHORT RSI threshold: {best_short_rsi}")

        # RSI backtest for optimal LONG entry
        print(f"\n--- RSI LONG BACKTEST (500 1h candles) ---")
        print(f"  {'RSI Threshold':>15} {'Trades':>8} {'Win%':>8} {'Avg PnL%':>10} {'Total PnL%':>12}")
        best_long_rsi = None
        best_long_total = -999
        for rsi_thresh in [20, 25, 30, 35, 40]:
            result = backtest_rsi_longs(df, rsi, atr, rsi_thresh)
            if result['count'] > 0:
                print(f"  {rsi_thresh:>15} {result['count']:>8} {result['wr']:>7.1f}% {result['avg_pnl']:>9.2f}% {result['total_pnl']:>11.2f}%")
                if result['total_pnl'] > best_long_total and result['count'] >= 2:
                    best_long_total = result['total_pnl']
                    best_long_rsi = rsi_thresh
            else:
                print(f"  {rsi_thresh:>15} {'no trades':>8}")

        if best_long_rsi:
            print(f"  >> Best LONG RSI threshold: {best_long_rsi}")

        # Specific trade setup
        print(f"\n--- TRADE SETUP: SHORT {sym} ---")
        # Use BB upper or recent high as entry level
        short_entry = max(bb_upper.iloc[-1], current_price)  # At least current price
        short_sl = high_24h + current_atr  # SL above recent high + ATR buffer
        short_tp1 = ema20.iloc[-1]  # TP1 at EMA20
        short_tp2 = bb_mid.iloc[-1]  # TP2 at BB mid (SMA20)
        short_tp3 = ema50.iloc[-1]  # TP3 at EMA50

        risk = abs(short_sl - short_entry)
        reward1 = abs(short_entry - short_tp1) if short_tp1 < short_entry else 0
        reward2 = abs(short_entry - short_tp2) if short_tp2 < short_entry else 0
        reward3 = abs(short_entry - short_tp3) if short_tp3 < short_entry else 0

        rr1 = reward1 / risk if risk > 0 else 0
        rr2 = reward2 / risk if risk > 0 else 0
        rr3 = reward3 / risk if risk > 0 else 0

        print(f"  Entry:   ${short_entry:.4f}")
        print(f"  SL:      ${short_sl:.4f}  (risk: {risk/short_entry*100:.2f}%)")
        print(f"  TP1:     ${short_tp1:.4f}  (reward: {reward1/short_entry*100:.2f}%, R:R = {rr1:.2f})")
        print(f"  TP2:     ${short_tp2:.4f}  (reward: {reward2/short_entry*100:.2f}%, R:R = {rr2:.2f})")
        print(f"  TP3:     ${short_tp3:.4f}  (reward: {reward3/short_entry*100:.2f}%, R:R = {rr3:.2f})")

        # Leverage recommendation based on risk %
        risk_pct = risk / short_entry * 100
        if risk_pct > 0:
            # Max loss 2% of account
            max_lev = min(2.0 / risk_pct, 20)
            print(f"  Leverage: {max_lev:.1f}x (for 2% max account risk)")

        # Also compute: if we enter AT MARKET right now
        print(f"\n--- TRADE SETUP: SHORT {sym} AT MARKET (NOW) ---")
        market_entry = current_price
        market_sl = high_24h + 0.5 * current_atr
        market_tp1 = ema20.iloc[-1]

        m_risk = abs(market_sl - market_entry)
        m_reward1 = abs(market_entry - market_tp1) if market_tp1 < market_entry else 0
        m_rr1 = m_reward1 / m_risk if m_risk > 0 else 0

        print(f"  Entry:   ${market_entry:.4f}")
        print(f"  SL:      ${market_sl:.4f}  (risk: {m_risk/market_entry*100:.2f}%)")
        print(f"  TP1:     ${market_tp1:.4f}  (R:R = {m_rr1:.2f})")
        if m_risk > 0:
            m_lev = min(2.0 / (m_risk/market_entry*100), 20)
            print(f"  Leverage: {m_lev:.1f}x (for 2% max account risk)")

        # BUY setup (for pullback)
        print(f"\n--- TRADE SETUP: BUY {sym} ON PULLBACK ---")
        buy_entry = ema20.iloc[-1]  # Wait for pullback to EMA20
        buy_sl = buy_entry - 1.5 * current_atr
        buy_tp1 = high_24h
        buy_tp2 = high_24h + current_atr

        b_risk = abs(buy_entry - buy_sl)
        b_reward1 = abs(buy_tp1 - buy_entry)
        b_reward2 = abs(buy_tp2 - buy_entry)
        b_rr1 = b_reward1 / b_risk if b_risk > 0 else 0
        b_rr2 = b_reward2 / b_risk if b_risk > 0 else 0

        print(f"  Entry:   ${buy_entry:.4f}  (wait for pullback to EMA20)")
        print(f"  SL:      ${buy_sl:.4f}  (risk: {b_risk/buy_entry*100:.2f}%)")
        print(f"  TP1:     ${buy_tp1:.4f}  (R:R = {b_rr1:.2f})")
        print(f"  TP2:     ${buy_tp2:.4f}  (R:R = {b_rr2:.2f})")
        if b_risk > 0:
            b_lev = min(2.0 / (b_risk/buy_entry*100), 20)
            print(f"  Leverage: {b_lev:.1f}x (for 2% max account risk)")

    # ─── Multi-asset overbought analysis ─────────────────────────────
    print(f"\n{'='*80}")
    print("  MULTI-ASSET OVERBOUGHT ANALYSIS")
    print(f"{'='*80}")

    if len(dfs) == 3:
        results = backtest_multi_overbought(dfs)
        print(f"\n  Occurrences where ALL 3 assets had RSI > 65: {len(results)}")

        if results:
            for sym in dfs.keys():
                changes = [r[sym] for r in results]
                avg = np.mean(changes)
                median = np.median(changes)
                pos_pct = sum(1 for c in changes if c > 0) / len(changes) * 100
                print(f"\n  {sym} — 6h after all-overbought:")
                print(f"    Avg change: {avg:+.2f}%")
                print(f"    Median:     {median:+.2f}%")
                print(f"    Up %:       {pos_pct:.0f}%")
                print(f"    Worst:      {min(changes):+.2f}%")
                print(f"    Best:       {max(changes):+.2f}%")

    # ─── 6h Price Prediction Summary ─────────────────────────────────
    print(f"\n{'='*80}")
    print("  6-HOUR PRICE PREDICTION SUMMARY")
    print(f"{'='*80}")

    for sym, df in dfs.items():
        close = df['close']
        rsi = calc_rsi(close, 14)
        atr = calc_atr(df, 14)
        ema20 = calc_ema(close, 20)
        current = close.iloc[-1]
        cur_rsi = rsi.iloc[-1]
        cur_atr = atr.iloc[-1]

        # Historical: what happens 6h after this RSI level?
        future_changes = []
        for i in range(20, len(df) - 6):
            if abs(rsi.iloc[i] - cur_rsi) < 3:  # Similar RSI
                change = (close.iloc[i+6] - close.iloc[i]) / close.iloc[i] * 100
                future_changes.append(change)

        if future_changes:
            avg_change = np.mean(future_changes)
            median_change = np.median(future_changes)
            predicted_price = current * (1 + median_change / 100)
            down_prob = sum(1 for c in future_changes if c < 0) / len(future_changes) * 100

            print(f"\n  {sym} (RSI={cur_rsi:.1f}, Price=${current:.4f}):")
            print(f"    Historical samples at similar RSI: {len(future_changes)}")
            print(f"    Avg 6h change:    {avg_change:+.2f}%")
            print(f"    Median 6h change: {median_change:+.2f}%")
            print(f"    Predicted price:  ${predicted_price:.4f}")
            print(f"    Probability DOWN: {down_prob:.0f}%")
            print(f"    Expected range:   ${current - cur_atr:.4f} - ${current + cur_atr:.4f}")

    print(f"\n{'='*80}")
    print("  ANALYSIS COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
