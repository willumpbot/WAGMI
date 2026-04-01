#!/usr/bin/env python3
"""
72-Hour Alpha Opportunity Study
================================
Fetches 500 1h candles for HYPE, BTC, SOL.
Identifies every >1% move in the last 72 hours.
Categorizes as CATCHABLE vs UNPREDICTABLE.
Calculates total addressable profit on $89 account.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from data.fetcher import DataFetcher

# ─── CONFIG ──────────────────────────────────────────────────────
ACCOUNT_SIZE = 89.0
RISK_PER_TRADE = 0.02  # 2% risk per trade
MAX_LEVERAGE = 20
MIN_MOVE_PCT = 1.0  # minimum move to count

# Technical indicator parameters
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
EMA_50 = 50
ATR_PERIOD = 14

# Coin gecko IDs for fallback
SYMBOLS = {
    "HYPE": "hyperliquid",
    "BTC": "bitcoin",
    "SOL": "solana",
}

def compute_indicators(df):
    """Add all technical indicators to dataframe."""
    c = df["close"].copy()
    h = df["high"].copy()
    l = df["low"].copy()

    # EMAs
    df["ema9"] = c.ewm(span=EMA_FAST, adjust=False).mean()
    df["ema21"] = c.ewm(span=EMA_SLOW, adjust=False).mean()
    df["ema50"] = c.ewm(span=EMA_50, adjust=False).mean()

    # Bollinger Bands
    df["bb_mid"] = c.rolling(BB_PERIOD).mean()
    bb_std = c.rolling(BB_PERIOD).std()
    df["bb_upper"] = df["bb_mid"] + BB_STD * bb_std
    df["bb_lower"] = df["bb_mid"] - BB_STD * bb_std

    # RSI
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR
    tr = pd.DataFrame({
        "hl": h - l,
        "hc": (h - c.shift()).abs(),
        "lc": (l - c.shift()).abs()
    }).max(axis=1)
    df["atr"] = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"] = df["atr"] / c * 100

    # Volume SMA for volume confirmation
    if "volume" in df.columns:
        df["vol_sma20"] = df["volume"].rolling(20).mean()
        df["vol_ratio"] = df["volume"] / df["vol_sma20"].replace(0, np.nan)

    # Support/Resistance levels (pivot highs/lows over 10-bar lookback)
    df["pivot_high"] = h.rolling(21, center=True).max()
    df["pivot_low"] = l.rolling(21, center=True).min()

    # VWAP approximation (session-based)
    if "volume" in df.columns:
        tp = (h + l + c) / 3
        cumvol = df["volume"].cumsum()
        cumtpvol = (tp * df["volume"]).cumsum()
        df["vwap"] = cumtpvol / cumvol.replace(0, np.nan)

    return df


def find_significant_moves(df, min_pct=MIN_MOVE_PCT):
    """Find all moves >min_pct% in the last 72 hours of data."""
    moves = []

    # Get last 72 hours
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
        cutoff = df["time"].max() - timedelta(hours=72)
        mask = df["time"] >= cutoff
        start_idx = mask.idxmax() if mask.any() else 0
    else:
        start_idx = max(0, len(df) - 72)

    # Find swing points using zigzag-like approach
    # A swing high: higher than N bars on each side
    # A swing low: lower than N bars on each side
    lookback = 3  # bars on each side

    swings = []
    for i in range(start_idx + lookback, len(df) - lookback):
        h_val = df["high"].iloc[i]
        l_val = df["low"].iloc[i]

        # Check swing high
        is_high = True
        for j in range(1, lookback + 1):
            if df["high"].iloc[i-j] >= h_val or df["high"].iloc[i+j] >= h_val:
                is_high = False
                break

        # Check swing low
        is_low = True
        for j in range(1, lookback + 1):
            if df["low"].iloc[i-j] <= l_val or df["low"].iloc[i+j] <= l_val:
                is_low = False
                break

        if is_high:
            swings.append(("high", i, h_val))
        if is_low:
            swings.append(("low", i, l_val))

    # Find moves between consecutive opposite swings
    for k in range(len(swings) - 1):
        s1_type, s1_idx, s1_price = swings[k]
        s2_type, s2_idx, s2_price = swings[k + 1]

        if s1_type == s2_type:
            continue  # skip same-direction swings

        if s1_type == "low" and s2_type == "high":
            # Upward move
            pct = (s2_price - s1_price) / s1_price * 100
            direction = "LONG"
            entry_price = s1_price
            exit_price = s2_price
        else:
            # Downward move
            pct = (s1_price - s2_price) / s1_price * 100
            direction = "SHORT"
            entry_price = s1_price
            exit_price = s2_price

        if abs(pct) >= min_pct:
            duration_bars = s2_idx - s1_idx
            time_start = df["time"].iloc[s1_idx] if "time" in df.columns else f"bar_{s1_idx}"
            time_end = df["time"].iloc[s2_idx] if "time" in df.columns else f"bar_{s2_idx}"

            moves.append({
                "direction": direction,
                "start_idx": s1_idx,
                "end_idx": s2_idx,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pct_move": abs(pct),
                "duration_bars": duration_bars,
                "time_start": time_start,
                "time_end": time_end,
            })

    return moves


def check_technical_setup(df, move):
    """Check what technical signals existed at the move's start point."""
    idx = move["start_idx"]
    direction = move["direction"]

    # Get indicator values at the entry bar (and a few bars before for context)
    setup = {
        "bb_touch": False,
        "rsi_extreme": False,
        "ema_bounce": False,
        "ema_crossover": False,
        "volume_spike": False,
        "vwap_test": False,
        "support_resistance": False,
        "setup_count": 0,
        "signals": [],
        "rsi_value": None,
        "bb_position": None,
    }

    if idx < 2 or idx >= len(df):
        return setup

    row = df.iloc[idx]
    prev = df.iloc[idx - 1]
    price = row["close"]
    low = row["low"]
    high = row["high"]

    # RSI extreme
    rsi = row.get("rsi")
    if pd.notna(rsi):
        setup["rsi_value"] = round(rsi, 1)
        if direction == "LONG" and rsi < 35:
            setup["rsi_extreme"] = True
            setup["signals"].append(f"RSI oversold ({rsi:.1f})")
            setup["setup_count"] += 1
        elif direction == "SHORT" and rsi > 65:
            setup["rsi_extreme"] = True
            setup["signals"].append(f"RSI overbought ({rsi:.1f})")
            setup["setup_count"] += 1

    # Bollinger Band touch
    bb_lower = row.get("bb_lower")
    bb_upper = row.get("bb_upper")
    if pd.notna(bb_lower) and pd.notna(bb_upper):
        bb_width = bb_upper - bb_lower
        if bb_width > 0:
            bb_pos = (price - bb_lower) / bb_width
            setup["bb_position"] = round(bb_pos, 2)

            if direction == "LONG" and low <= bb_lower * 1.002:
                setup["bb_touch"] = True
                setup["signals"].append(f"BB lower touch (pos={bb_pos:.2f})")
                setup["setup_count"] += 1
            elif direction == "SHORT" and high >= bb_upper * 0.998:
                setup["bb_touch"] = True
                setup["signals"].append(f"BB upper touch (pos={bb_pos:.2f})")
                setup["setup_count"] += 1

    # EMA bounce (price touches EMA and bounces)
    ema9 = row.get("ema9")
    ema21 = row.get("ema21")
    ema50 = row.get("ema50")

    for ema_name, ema_val in [("EMA9", ema9), ("EMA21", ema21), ("EMA50", ema50)]:
        if pd.notna(ema_val):
            dist_pct = abs(low - ema_val) / ema_val * 100 if direction == "LONG" else abs(high - ema_val) / ema_val * 100
            if dist_pct < 0.3:  # within 0.3% of EMA
                setup["ema_bounce"] = True
                setup["signals"].append(f"{ema_name} bounce (dist={dist_pct:.2f}%)")
                setup["setup_count"] += 1
                break

    # EMA crossover
    if pd.notna(ema9) and pd.notna(ema21):
        prev_ema9 = prev.get("ema9")
        prev_ema21 = prev.get("ema21")
        if pd.notna(prev_ema9) and pd.notna(prev_ema21):
            if direction == "LONG" and prev_ema9 < prev_ema21 and ema9 >= ema21:
                setup["ema_crossover"] = True
                setup["signals"].append("EMA9/21 bullish crossover")
                setup["setup_count"] += 1
            elif direction == "SHORT" and prev_ema9 > prev_ema21 and ema9 <= ema21:
                setup["ema_crossover"] = True
                setup["signals"].append("EMA9/21 bearish crossover")
                setup["setup_count"] += 1

    # Volume spike
    vol_ratio = row.get("vol_ratio")
    if pd.notna(vol_ratio) and vol_ratio > 1.5:
        setup["volume_spike"] = True
        setup["signals"].append(f"Volume spike ({vol_ratio:.1f}x avg)")
        setup["setup_count"] += 1

    # VWAP test
    vwap = row.get("vwap")
    if pd.notna(vwap):
        vwap_dist = abs(price - vwap) / vwap * 100
        if vwap_dist < 0.3:
            setup["vwap_test"] = True
            setup["signals"].append(f"VWAP test (dist={vwap_dist:.2f}%)")
            setup["setup_count"] += 1

    return setup


def calculate_trade_metrics(move, df, account_size=ACCOUNT_SIZE):
    """Calculate optimal trade metrics for a move."""
    entry = move["entry_price"]
    exit_p = move["exit_price"]
    direction = move["direction"]
    pct = move["pct_move"]

    # ATR at entry for stop placement
    atr = df.iloc[move["start_idx"]].get("atr", 0)
    atr_pct = df.iloc[move["start_idx"]].get("atr_pct", 1.0)

    if pd.isna(atr) or atr == 0:
        atr_pct = 1.0

    # SL at 1 ATR from entry
    sl_distance_pct = max(atr_pct, 0.5)  # minimum 0.5% SL

    if direction == "LONG":
        sl = entry * (1 - sl_distance_pct / 100)
        tp = exit_p
    else:
        sl = entry * (1 + sl_distance_pct / 100)
        tp = exit_p

    # R:R ratio
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0

    # Optimal leverage: risk 2% of account
    risk_amount = account_size * RISK_PER_TRADE
    position_size = risk_amount / (sl_distance_pct / 100) if sl_distance_pct > 0 else 0
    leverage = position_size / account_size if account_size > 0 else 1
    leverage = min(leverage, MAX_LEVERAGE)
    leverage = max(leverage, 1)

    # Actual position and profit
    actual_position = account_size * leverage
    profit_pct = pct * leverage / 100
    dollar_profit = account_size * profit_pct

    # Also calculate at conservative leverage
    conservative_lev = min(leverage, 10)
    conservative_profit = account_size * (pct * conservative_lev / 100)

    return {
        "entry": round(entry, 4),
        "sl": round(sl, 4),
        "tp": round(tp, 4),
        "sl_pct": round(sl_distance_pct, 2),
        "rr_ratio": round(rr, 2),
        "optimal_leverage": round(leverage, 1),
        "position_size": round(actual_position, 2),
        "dollar_profit": round(dollar_profit, 2),
        "conservative_leverage": round(conservative_lev, 1),
        "conservative_profit": round(conservative_profit, 2),
        "pct_return_on_account": round(profit_pct * 100, 2),
    }


def classify_move(setup, move):
    """Classify a move as CATCHABLE or UNPREDICTABLE."""
    # A move is catchable if:
    # 1. At least 1 strong technical signal at entry
    # 2. The move had reasonable R:R (>1.5)

    if setup["setup_count"] >= 1:
        if setup["setup_count"] >= 2:
            return "HIGHLY_CATCHABLE"
        return "CATCHABLE"

    # Check if it was a gradual grind (could be caught with trend following)
    if move["duration_bars"] >= 6 and move["pct_move"] > 2:
        return "TREND_CATCHABLE"

    return "UNPREDICTABLE"


def analyze_symbol(symbol, coin_id, fetcher):
    """Full analysis for one symbol."""
    print(f"\n{'='*80}")
    print(f"  ANALYZING {symbol} — Last 72 Hours")
    print(f"{'='*80}")

    # Fetch data
    print(f"Fetching 500 1h candles for {symbol}...")
    df = fetcher.fetch_ohlcv(symbol, coin_id, "1h")

    if df is None or df.empty:
        print(f"  ERROR: No data for {symbol}")
        return None

    print(f"  Got {len(df)} candles, from {df['time'].iloc[0]} to {df['time'].iloc[-1]}")

    # Compute indicators
    df = compute_indicators(df)

    # Get 72h window
    df["time"] = pd.to_datetime(df["time"])
    cutoff = df["time"].max() - timedelta(hours=72)
    window = df[df["time"] >= cutoff]

    # Price range in window
    price_high = window["high"].max()
    price_low = window["low"].min()
    price_now = window["close"].iloc[-1]
    total_range = (price_high - price_low) / price_low * 100

    print(f"\n  72h Window: {cutoff.strftime('%Y-%m-%d %H:%M')} -> {df['time'].max().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Price: ${price_low:.4f} -> ${price_high:.4f} (current: ${price_now:.4f})")
    print(f"  Total range: {total_range:.2f}%")
    print(f"  ATR(14): ${df['atr'].iloc[-1]:.4f} ({df['atr_pct'].iloc[-1]:.2f}%)")

    # Find significant moves
    moves = find_significant_moves(df, min_pct=MIN_MOVE_PCT)
    print(f"\n  Found {len(moves)} significant moves (>{MIN_MOVE_PCT}%)")

    results = {
        "symbol": symbol,
        "price_now": price_now,
        "total_range_pct": total_range,
        "moves": [],
        "catchable_profit": 0,
        "highly_catchable_profit": 0,
        "trend_catchable_profit": 0,
        "unpredictable_moves": 0,
        "total_addressable_profit": 0,
    }

    for i, move in enumerate(moves):
        setup = check_technical_setup(df, move)
        classification = classify_move(setup, move)
        metrics = calculate_trade_metrics(move, df)

        move_result = {
            **move,
            **setup,
            **metrics,
            "classification": classification,
        }
        results["moves"].append(move_result)

        # Print each move
        time_start = move["time_start"]
        time_end = move["time_end"]
        if isinstance(time_start, pd.Timestamp):
            time_start = time_start.strftime("%m/%d %H:%M")
        if isinstance(time_end, pd.Timestamp):
            time_end = time_end.strftime("%m/%d %H:%M")

        tag = {
            "HIGHLY_CATCHABLE": "[*** HIGHLY CATCHABLE ***]",
            "CATCHABLE": "[** CATCHABLE **]",
            "TREND_CATCHABLE": "[* TREND *]",
            "UNPREDICTABLE": "[  unpredictable  ]",
        }[classification]

        print(f"\n  Move #{i+1}: {move['direction']} {move['pct_move']:.2f}% | {time_start} -> {time_end} ({move['duration_bars']}h)")
        print(f"    {tag}")
        print(f"    Entry: ${metrics['entry']:.4f} -> Exit: ${metrics['tp']:.4f} | SL: ${metrics['sl']:.4f} ({metrics['sl_pct']:.2f}%)")
        print(f"    R:R = {metrics['rr_ratio']:.1f} | Leverage: {metrics['optimal_leverage']:.0f}x | Profit: ${metrics['dollar_profit']:.2f}")

        if setup["signals"]:
            print(f"    Signals: {' | '.join(setup['signals'])}")
        else:
            print(f"    Signals: NONE — no technical setup at entry")

        if setup["rsi_value"] is not None:
            print(f"    RSI: {setup['rsi_value']:.1f} | BB pos: {setup.get('bb_position', 'N/A')}")

        # Accumulate profits by category
        if classification == "HIGHLY_CATCHABLE":
            results["highly_catchable_profit"] += metrics["conservative_profit"]
            results["total_addressable_profit"] += metrics["conservative_profit"]
        elif classification == "CATCHABLE":
            results["catchable_profit"] += metrics["conservative_profit"]
            results["total_addressable_profit"] += metrics["conservative_profit"]
        elif classification == "TREND_CATCHABLE":
            results["trend_catchable_profit"] += metrics["conservative_profit"]
            results["total_addressable_profit"] += metrics["conservative_profit"]
        else:
            results["unpredictable_moves"] += 1

    return results


def print_summary(all_results):
    """Print final summary across all symbols."""
    print(f"\n\n{'#'*80}")
    print(f"  TOTAL ADDRESSABLE PROFIT SUMMARY (72 Hours, $89 Account)")
    print(f"{'#'*80}")

    total_highly_catchable = 0
    total_catchable = 0
    total_trend = 0
    total_unpredictable = 0
    total_profit = 0
    all_catchable_moves = []

    for r in all_results:
        if r is None:
            continue

        print(f"\n  {r['symbol']}:")

        highly = [m for m in r["moves"] if m["classification"] == "HIGHLY_CATCHABLE"]
        catch = [m for m in r["moves"] if m["classification"] == "CATCHABLE"]
        trend = [m for m in r["moves"] if m["classification"] == "TREND_CATCHABLE"]
        unpred = [m for m in r["moves"] if m["classification"] == "UNPREDICTABLE"]

        print(f"    Highly Catchable: {len(highly)} moves -> ${r['highly_catchable_profit']:.2f}")
        print(f"    Catchable:        {len(catch)} moves -> ${r['catchable_profit']:.2f}")
        print(f"    Trend Catchable:  {len(trend)} moves -> ${r['trend_catchable_profit']:.2f}")
        print(f"    Unpredictable:    {len(unpred)} moves")
        print(f"    TOTAL ADDRESSABLE: ${r['total_addressable_profit']:.2f}")

        total_highly_catchable += r["highly_catchable_profit"]
        total_catchable += r["catchable_profit"]
        total_trend += r["trend_catchable_profit"]
        total_profit += r["total_addressable_profit"]
        total_unpredictable += r["unpredictable_moves"]

        all_catchable_moves.extend([m for m in r["moves"] if m["classification"] != "UNPREDICTABLE"])

    print(f"\n  {'-'*60}")
    print(f"  GRAND TOTAL:")
    print(f"    Highly Catchable profit:  ${total_highly_catchable:.2f}")
    print(f"    Catchable profit:         ${total_catchable:.2f}")
    print(f"    Trend-Following profit:   ${total_trend:.2f}")
    print(f"    -----------------------------")
    print(f"    TOTAL ADDRESSABLE:        ${total_profit:.2f}")
    print(f"    As % of account:          {total_profit/ACCOUNT_SIZE*100:.1f}%")
    print(f"    Annualized (if repeats):  {total_profit/ACCOUNT_SIZE*100 / 3 * 365:.0f}%")
    print(f"    Unpredictable moves:      {total_unpredictable}")

    # Best entry methods
    if all_catchable_moves:
        print(f"\n  {'-'*60}")
        print(f"  OPTIMAL ENTRY METHODS (from catchable moves):")

        bb_count = sum(1 for m in all_catchable_moves if m.get("bb_touch"))
        rsi_count = sum(1 for m in all_catchable_moves if m.get("rsi_extreme"))
        ema_count = sum(1 for m in all_catchable_moves if m.get("ema_bounce"))
        cross_count = sum(1 for m in all_catchable_moves if m.get("ema_crossover"))
        vol_count = sum(1 for m in all_catchable_moves if m.get("volume_spike"))
        vwap_count = sum(1 for m in all_catchable_moves if m.get("vwap_test"))

        total_catchable_count = len(all_catchable_moves)
        print(f"    BB touch:       {bb_count}/{total_catchable_count} ({bb_count/total_catchable_count*100:.0f}%)")
        print(f"    RSI extreme:    {rsi_count}/{total_catchable_count} ({rsi_count/total_catchable_count*100:.0f}%)")
        print(f"    EMA bounce:     {ema_count}/{total_catchable_count} ({ema_count/total_catchable_count*100:.0f}%)")
        print(f"    EMA crossover:  {cross_count}/{total_catchable_count} ({cross_count/total_catchable_count*100:.0f}%)")
        print(f"    Volume spike:   {vol_count}/{total_catchable_count} ({vol_count/total_catchable_count*100:.0f}%)")
        print(f"    VWAP test:      {vwap_count}/{total_catchable_count} ({vwap_count/total_catchable_count*100:.0f}%)")

        # Optimal hold times
        durations = [m["duration_bars"] for m in all_catchable_moves]
        profits = [m["conservative_profit"] for m in all_catchable_moves]

        print(f"\n  OPTIMAL HOLD TIMES:")
        print(f"    Mean duration:  {np.mean(durations):.1f} hours")
        print(f"    Median:         {np.median(durations):.0f} hours")
        print(f"    Best R:R moves: {[m['duration_bars'] for m in sorted(all_catchable_moves, key=lambda x: x['rr_ratio'], reverse=True)[:3]]} hours")

        # Leverage analysis
        leverages = [m["optimal_leverage"] for m in all_catchable_moves]
        print(f"\n  LEVERAGE ANALYSIS:")
        print(f"    Mean optimal:   {np.mean(leverages):.1f}x")
        print(f"    Conservative:   {np.mean([m['conservative_leverage'] for m in all_catchable_moves]):.1f}x")
        print(f"    At 5x across all: ${sum(ACCOUNT_SIZE * m['pct_move'] * 5 / 10000 for m in all_catchable_moves):.2f}")
        print(f"    At 10x across all: ${sum(ACCOUNT_SIZE * m['pct_move'] * 10 / 10000 for m in all_catchable_moves):.2f}")
        print(f"    At 15x across all: ${sum(ACCOUNT_SIZE * m['pct_move'] * 15 / 10000 for m in all_catchable_moves):.2f}")
        print(f"    At 20x across all: ${sum(ACCOUNT_SIZE * m['pct_move'] * 20 / 10000 for m in all_catchable_moves):.2f}")

        # Top 5 best opportunities
        top5 = sorted(all_catchable_moves, key=lambda x: x["conservative_profit"], reverse=True)[:5]
        print(f"\n  TOP 5 BEST OPPORTUNITIES:")
        for j, m in enumerate(top5):
            ts = m["time_start"]
            if isinstance(ts, pd.Timestamp):
                ts = ts.strftime("%m/%d %H:%M")
            print(f"    #{j+1}: {m['direction']} {m['pct_move']:.2f}% at {ts} | "
                  f"R:R={m['rr_ratio']:.1f} | ${m['conservative_profit']:.2f} profit | "
                  f"Signals: {', '.join(m['signals'][:2]) if m['signals'] else 'trend'}")

    # What we actually made
    print(f"\n  {'-'*60}")
    print(f"  WHAT WE ACTUALLY MADE: $0.00 (bot in paper mode, sniper not live)")
    print(f"  ALPHA GAP: ${total_profit:.2f}")
    print(f"  PATIENCE COST: Must wait at levels, ~{np.mean(durations) if all_catchable_moves else 0:.0f}h avg hold")


def main():
    print("="*80)
    print("  72-HOUR ALPHA OPPORTUNITY STUDY")
    print("  Account: $89 | Max Leverage: 20x | Risk/Trade: 2%")
    print("="*80)

    fetcher = DataFetcher(fresh=True)
    all_results = []

    for symbol, coin_id in SYMBOLS.items():
        try:
            result = analyze_symbol(symbol, coin_id, fetcher)
            all_results.append(result)
        except Exception as e:
            print(f"\n  ERROR analyzing {symbol}: {e}")
            import traceback
            traceback.print_exc()
            all_results.append(None)

    print_summary(all_results)


if __name__ == "__main__":
    main()
