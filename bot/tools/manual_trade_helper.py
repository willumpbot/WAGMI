"""
Manual Trade Helper — Quick decision support for manual HYPE trading.

Based on all quant analysis, gives a simple GO/WAIT/SKIP recommendation
with exact entry/SL/TP levels for manual execution on Hyperliquid.

Usage:
    cd bot && python -m tools.manual_trade_helper
    cd bot && python -m tools.manual_trade_helper --symbol BTC
"""
import sys
import os
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def analyze(symbol="HYPE", account_equity=100.0):
    from data.fetcher import DataFetcher

    fetcher = DataFetcher()
    coin_ids = {"HYPE": "hyperliquid", "BTC": "bitcoin", "SOL": "solana"}

    # Fetch data
    df = fetcher.fetch_ohlcv(symbol, coin_ids.get(symbol, symbol.lower()), "1h")
    if df is None or df.empty:
        print(f"No data for {symbol}")
        return

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)

    # Also fetch BTC for lead-lag
    btc_df = None
    if symbol != "BTC":
        btc_df = fetcher.fetch_ohlcv("BTC", "bitcoin", "1h")
        if btc_df is not None:
            btc_df["time"] = pd.to_datetime(btc_df["time"], utc=True)
            btc_df = btc_df.sort_values("time").reset_index(drop=True)

    price = df["close"].iloc[-1]
    now = datetime.now(timezone.utc)
    hour = now.hour

    # Indicators
    sma20 = df["close"].tail(20).mean()
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]

    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift(1)),
                   abs(df["low"] - df["close"].shift(1)))
    )
    atr = tr.rolling(14).mean().iloc[-1]
    atr_pct = atr / price * 100

    ret_1h = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
    ret_3h = (df["close"].iloc[-1] - df["close"].iloc[-4]) / df["close"].iloc[-4] * 100

    # BTC lead-lag
    btc_signal = None
    if btc_df is not None and len(btc_df) >= 2:
        btc_ret = (btc_df["close"].iloc[-1] - btc_df["close"].iloc[-2]) / btc_df["close"].iloc[-2] * 100
        if abs(btc_ret) >= 0.8:
            btc_signal = "STRONG" if btc_ret > 0 else "STRONG_DOWN"
        elif abs(btc_ret) >= 0.5:
            btc_signal = "MODERATE" if btc_ret > 0 else "MODERATE_DOWN"

    # Score conditions
    is_prime = hour >= 18 or hour < 6
    above_sma = price > sma20
    rsi_ok = 35 <= rsi <= 65
    btc_positive = btc_signal in ("STRONG", "MODERATE")

    score = 0
    conditions = []

    if above_sma:
        score += 25
        conditions.append("Above SMA20")
    if rsi_ok:
        score += 20
        conditions.append(f"RSI {rsi:.0f} in sweet spot")
    if is_prime:
        score += 20
        conditions.append("Prime hours (18-06 UTC)")
    if btc_signal == "STRONG":
        score += 25
        conditions.append("BTC strong momentum (77% follow)")
    elif btc_signal == "MODERATE":
        score += 15
        conditions.append("BTC moderate momentum (73% follow)")
    if ret_1h > 0:
        score += 10
        conditions.append(f"Positive momentum ({ret_1h:+.1f}%)")

    # Compute levels
    if symbol == "HYPE":
        sl_pct = 2.5
        tp_pct = 3.75
        lev = 6
    elif symbol == "BTC":
        sl_pct = 1.5
        tp_pct = 2.2
        lev = 10
    else:
        sl_pct = 2.5
        tp_pct = 3.75
        lev = 5

    sl_price = round(price * (1 - sl_pct / 100), 4)
    tp_price = round(price * (1 + tp_pct / 100), 4)
    risk_usd = account_equity * 0.05  # 5% risk
    position_usd = risk_usd / (sl_pct / 100)
    margin_usd = position_usd / lev
    qty = position_usd / price
    pnl_win = risk_usd * (tp_pct / sl_pct)
    rr = tp_pct / sl_pct

    # Decision
    if score >= 70:
        decision = "GO"
        emoji = ">>>"
    elif score >= 45:
        decision = "WAIT"
        emoji = "---"
    else:
        decision = "SKIP"
        emoji = "XXX"

    # Print
    print(f"\n{'=' * 50}")
    print(f"  {emoji} {decision}: {symbol} BUY @ ${price:.4f}")
    print(f"  Score: {score}/100")
    print(f"{'=' * 50}")
    print(f"\n  Conditions ({len(conditions)} met):")
    for c in conditions:
        print(f"    + {c}")
    if not above_sma:
        print(f"    - Below SMA20 (${sma20:.2f})")
    if not rsi_ok:
        print(f"    - RSI {rsi:.0f} outside sweet spot (35-65)")
    if not is_prime:
        print(f"    - Weak hours ({hour}:00 UTC)")
    if btc_signal and "DOWN" in btc_signal:
        print(f"    - BTC moving down — HYPE likely follows")

    if decision != "SKIP":
        print(f"\n  --- ORDER PARAMETERS ---")
        print(f"  Entry:    ${price:.4f}")
        print(f"  Stop:     ${sl_price:.4f} (-{sl_pct}%)")
        print(f"  Target:   ${tp_price:.4f} (+{tp_pct}%)")
        print(f"  Leverage: {lev}x")
        print(f"  R:R:      {rr:.1f}")
        print(f"")
        print(f"  --- SIZING (${account_equity:.0f} account) ---")
        print(f"  Risk:     ${risk_usd:.2f} (5%)")
        print(f"  Position: ${position_usd:.2f}")
        print(f"  Margin:   ${margin_usd:.2f}")
        print(f"  Qty:      {qty:.4f} {symbol}")
        print(f"  Win:      +${pnl_win:.2f}")
        print(f"  Loss:     -${risk_usd:.2f}")

    print(f"\n  Market: RSI={rsi:.0f}, ATR={atr_pct:.1f}%, 1h={ret_1h:+.1f}%, 3h={ret_3h:+.1f}%")
    print(f"  Time:   {now.strftime('%H:%M UTC')} ({'PRIME' if is_prime else 'WEAK'})")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="HYPE", help="Symbol to analyze")
    parser.add_argument("--equity", type=float, default=100.0, help="Account equity")
    args = parser.parse_args()
    analyze(args.symbol, args.equity)
