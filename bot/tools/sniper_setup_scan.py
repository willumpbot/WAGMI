"""
Sniper Setup Scanner — 7-day historical analysis
Fetches 1h data and catalogs all sniper setup opportunities.
Research-only script, does not modify any bot files.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from data.fetcher import DataFetcher

# ─── Config ──────────────────────────────────────────────────────
SYMBOLS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "HYPE": "hyperliquid",
}
LOOKBACK = 168  # 7 days of 1h candles
LEVERAGE = 15
RISK_USD = 100
SL_PCT = 0.01  # 1% stop loss
TIMEFRAME = "1h"

# ─── Indicators ──────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add BB, RSI, EMA20, EMA50, avg body, avg volume."""
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    opn = df["open"].astype(float)
    vol = df["volume"].astype(float) if "volume" in df.columns else pd.Series(0, index=df.index)

    # Bollinger Bands (20-period, 2 std)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_mid"] = sma20

    # RSI (14-period)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # EMAs
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # Body and wick stats
    df["body"] = (close - opn).abs()
    df["avg_body"] = df["body"].rolling(20).mean()
    df["upper_wick"] = high - close.where(close >= opn, opn)
    df["lower_wick"] = close.where(close < opn, opn) - low
    df["total_range"] = high - low
    df["candle_color"] = np.where(close >= opn, "green", "red")

    # Volume
    df["vol"] = vol
    df["avg_vol"] = vol.rolling(20).mean()

    return df


# ─── Setup Detection ────────────────────────────────────────────

def detect_setups(df: pd.DataFrame, symbol: str) -> list:
    """Scan for all setup types in the dataframe."""
    setups = []
    n = len(df)

    for i in range(50, n - 8):  # need 50 bars warmup, 8 bars forward
        row = df.iloc[i]
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        opn = float(row["open"])
        rsi = float(row["rsi"]) if not np.isnan(row["rsi"]) else 50
        bb_upper = float(row["bb_upper"]) if not np.isnan(row["bb_upper"]) else close * 1.1
        bb_lower = float(row["bb_lower"]) if not np.isnan(row["bb_lower"]) else close * 0.9
        bb_range = bb_upper - bb_lower if bb_upper != bb_lower else 1
        ema20 = float(row["ema20"])
        ema50 = float(row["ema50"])
        body = float(row["body"])
        avg_body = float(row["avg_body"]) if not np.isnan(row["avg_body"]) else body
        vol = float(row["vol"])
        avg_vol = float(row["avg_vol"]) if not np.isnan(row["avg_vol"]) else vol
        ts = row.get("timestamp", row.name)

        # Forward returns
        fwd = {}
        for h in [1, 2, 4, 8]:
            if i + h < n:
                fwd[f"{h}h"] = float(df.iloc[i + h]["close"])
            else:
                fwd[f"{h}h"] = close

        base = {
            "symbol": symbol,
            "timestamp": ts,
            "price": close,
            "fwd_1h": fwd["1h"],
            "fwd_2h": fwd["2h"],
            "fwd_4h": fwd["4h"],
            "fwd_8h": fwd["8h"],
        }

        # a) BB Upper Rejection (SELL)
        dist_to_upper = (bb_upper - close) / bb_range if bb_range > 0 else 1
        if dist_to_upper < 0.05 and rsi > 65:
            setups.append({**base, "setup": "BB_Upper_Rejection", "side": "SELL", "rsi": rsi})

        # b) BB Lower Bounce (BUY)
        dist_to_lower = (close - bb_lower) / bb_range if bb_range > 0 else 1
        if dist_to_lower < 0.05 and rsi < 35:
            setups.append({**base, "setup": "BB_Lower_Bounce", "side": "BUY", "rsi": rsi})

        # c) EMA20 Touch (trend continuation)
        ema20_dist = abs(close - ema20) / close
        if ema20_dist < 0.002:  # within 0.2% of EMA20
            if ema20 > ema50:  # uptrend
                setups.append({**base, "setup": "EMA20_Touch_Long", "side": "BUY", "rsi": rsi})
            elif ema20 < ema50:  # downtrend
                setups.append({**base, "setup": "EMA20_Touch_Short", "side": "SELL", "rsi": rsi})

        # d) Exhaustion Reversal
        if i > 0 and avg_body > 0:
            prev = df.iloc[i - 1]
            prev_body = float(prev["body"])
            if prev_body > 2 * avg_body:
                prev_color = prev["candle_color"]
                curr_color = row["candle_color"]
                total_range = float(row["total_range"])
                wick_ratio = (float(row["upper_wick"]) + float(row["lower_wick"])) / total_range if total_range > 0 else 0
                if prev_color != curr_color and wick_ratio > 0.5:
                    side = "SELL" if prev_color == "green" else "BUY"
                    setups.append({**base, "setup": "Exhaustion_Reversal", "side": side, "rsi": rsi})

        # e) Volume Spike Reversal
        if avg_vol > 0 and vol > 3 * avg_vol:
            if i > 0:
                prev_color = df.iloc[i - 1]["candle_color"]
                curr_color = row["candle_color"]
                if prev_color != curr_color:
                    side = "BUY" if curr_color == "green" else "SELL"
                    setups.append({**base, "setup": "Volume_Spike_Reversal", "side": side, "rsi": rsi})

        # f) RSI Divergence (simplified: 5-bar lookback)
        if i >= 55:
            lookback = 5
            prices_window = [float(df.iloc[i - j]["close"]) for j in range(lookback)]
            rsi_window = [float(df.iloc[i - j]["rsi"]) if not np.isnan(df.iloc[i - j]["rsi"]) else 50 for j in range(lookback)]

            # Bearish divergence: price making new high but RSI lower
            if close == max(prices_window) and rsi < max(rsi_window) - 3 and rsi > 60:
                setups.append({**base, "setup": "RSI_Divergence_Bear", "side": "SELL", "rsi": rsi})

            # Bullish divergence: price making new low but RSI higher
            if close == min(prices_window) and rsi > min(rsi_window) + 3 and rsi < 40:
                setups.append({**base, "setup": "RSI_Divergence_Bull", "side": "BUY", "rsi": rsi})

    return setups


# ─── PnL Calculation ────────────────────────────────────────────

def calc_pnl(setup: dict) -> dict:
    """Calculate trade outcome at various horizons with 15x leverage."""
    price = setup["price"]
    side = setup["side"]
    sl_price = price * (1 - SL_PCT) if side == "BUY" else price * (1 + SL_PCT)
    risk_per_unit = abs(price - sl_price)
    position_size = (RISK_USD * LEVERAGE) / price if price > 0 else 0

    results = {}
    best_pnl = -RISK_USD  # worst case = full SL hit
    best_horizon = "1h"

    for horizon in ["1h", "2h", "4h", "8h"]:
        exit_price = setup[f"fwd_{horizon}"]
        if side == "BUY":
            pnl_pct = (exit_price - price) / price
            hit_sl = exit_price <= sl_price
        else:
            pnl_pct = (price - exit_price) / price
            hit_sl = exit_price >= sl_price

        raw_pnl = pnl_pct * LEVERAGE * RISK_USD
        # Cap loss at risk amount (SL triggered)
        if raw_pnl < -RISK_USD:
            raw_pnl = -RISK_USD

        results[f"pnl_{horizon}"] = round(raw_pnl, 2)
        results[f"rr_{horizon}"] = round(raw_pnl / RISK_USD, 2) if RISK_USD > 0 else 0
        results[f"win_{horizon}"] = 1 if raw_pnl > 0 else 0

        if raw_pnl > best_pnl:
            best_pnl = raw_pnl
            best_horizon = horizon

    results["best_pnl"] = round(best_pnl, 2)
    results["best_horizon"] = best_horizon
    # Use 4h as the "standard" evaluation horizon
    results["is_winner"] = results["win_4h"]
    results["trade_pnl"] = results["pnl_4h"]
    results["trade_rr"] = results["rr_4h"]

    return results


# ─── Main ────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("  SNIPER SETUP SCANNER — 7-Day Historical Analysis")
    print("  Leverage: 15x | Risk: $100/trade | SL: 1% | Eval Horizon: 4h")
    print("=" * 80)
    print()

    fetcher = DataFetcher()
    all_setups = []

    for symbol, cg_id in SYMBOLS.items():
        print(f"[*] Fetching {symbol} 1h data...")
        try:
            df = fetcher.fetch_ohlcv(symbol, cg_id, TIMEFRAME)
            if df is None or len(df) < 60:
                print(f"    WARNING: Insufficient data for {symbol} ({len(df) if df is not None else 0} candles)")
                continue

            # Take last ~200 candles (need warmup + 168 analysis window)
            df = df.tail(220).reset_index(drop=True)
            print(f"    Got {len(df)} candles, latest: {df.iloc[-1].get('timestamp', 'N/A')}")

            # Compute indicators
            df = compute_indicators(df)

            # Detect setups
            setups = detect_setups(df, symbol)
            print(f"    Found {len(setups)} setups")

            # Calculate PnL for each
            for s in setups:
                pnl = calc_pnl(s)
                s.update(pnl)

            all_setups.extend(setups)

        except Exception as e:
            print(f"    ERROR fetching {symbol}: {e}")
            import traceback
            traceback.print_exc()

    if not all_setups:
        print("\nNo setups found. Check data availability.")
        return

    df_setups = pd.DataFrame(all_setups)

    # ─── Report ──────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  RESULTS SUMMARY")
    print("=" * 80)

    # 1) Setup counts
    print(f"\nTotal setups found: {len(df_setups)}")
    print("\nSetups per type:")
    for setup_type in df_setups["setup"].unique():
        count = len(df_setups[df_setups["setup"] == setup_type])
        print(f"  {setup_type:30s}: {count}")

    print("\nSetups per symbol:")
    for sym in df_setups["symbol"].unique():
        count = len(df_setups[df_setups["symbol"] == sym])
        print(f"  {sym:10s}: {count}")

    # 2) Win rate per setup type per symbol (4h horizon)
    print("\n" + "-" * 80)
    print("  WIN RATE PER SETUP TYPE PER SYMBOL (4h horizon)")
    print("-" * 80)

    pivot = df_setups.groupby(["setup", "symbol"]).agg(
        count=("is_winner", "count"),
        wins=("is_winner", "sum"),
        avg_pnl=("trade_pnl", "mean"),
        total_pnl=("trade_pnl", "sum"),
    ).reset_index()
    pivot["win_rate"] = (pivot["wins"] / pivot["count"] * 100).round(1)
    pivot["avg_rr"] = (pivot["avg_pnl"] / RISK_USD).round(2)

    print(f"\n{'Setup':<30s} {'Symbol':<8s} {'Count':>6s} {'WR%':>7s} {'Avg PnL':>10s} {'Total PnL':>11s} {'Avg R:R':>8s}")
    print("-" * 80)
    for _, r in pivot.sort_values("total_pnl", ascending=False).iterrows():
        print(f"{r['setup']:<30s} {r['symbol']:<8s} {r['count']:>6d} {r['win_rate']:>6.1f}% ${r['avg_pnl']:>9.2f} ${r['total_pnl']:>10.2f} {r['avg_rr']:>7.2f}R")

    # 3) Aggregated by setup type
    print("\n" + "-" * 80)
    print("  AGGREGATED BY SETUP TYPE (4h horizon)")
    print("-" * 80)

    agg = df_setups.groupby("setup").agg(
        count=("is_winner", "count"),
        wins=("is_winner", "sum"),
        avg_pnl=("trade_pnl", "mean"),
        total_pnl=("trade_pnl", "sum"),
        avg_best=("best_pnl", "mean"),
    ).reset_index()
    agg["win_rate"] = (agg["wins"] / agg["count"] * 100).round(1)
    agg["loss_rate"] = 100 - agg["win_rate"]
    # EV = WR * avg_win - (1-WR) * avg_loss
    for idx, r in agg.iterrows():
        winners = df_setups[(df_setups["setup"] == r["setup"]) & (df_setups["trade_pnl"] > 0)]["trade_pnl"]
        losers = df_setups[(df_setups["setup"] == r["setup"]) & (df_setups["trade_pnl"] <= 0)]["trade_pnl"]
        avg_win = winners.mean() if len(winners) > 0 else 0
        avg_loss = abs(losers.mean()) if len(losers) > 0 else RISK_USD
        wr = r["win_rate"] / 100
        ev = wr * avg_win - (1 - wr) * avg_loss
        agg.at[idx, "avg_win"] = round(avg_win, 2)
        agg.at[idx, "avg_loss"] = round(avg_loss, 2)
        agg.at[idx, "ev"] = round(ev, 2)

    print(f"\n{'Setup':<30s} {'N':>5s} {'WR%':>7s} {'AvgWin':>9s} {'AvgLoss':>9s} {'EV/trade':>10s} {'TotalPnL':>11s}")
    print("-" * 80)
    for _, r in agg.sort_values("ev", ascending=False).iterrows():
        print(f"{r['setup']:<30s} {r['count']:>5.0f} {r['win_rate']:>6.1f}% ${r.get('avg_win',0):>8.2f} ${r.get('avg_loss',0):>8.2f} ${r.get('ev',0):>9.2f} ${r['total_pnl']:>10.2f}")

    # 4) Best performing setups ranked by EV
    print("\n" + "-" * 80)
    print("  BEST SETUPS BY SETUP+SYMBOL (ranked by EV)")
    print("-" * 80)

    combo = df_setups.groupby(["setup", "symbol", "side"]).agg(
        count=("is_winner", "count"),
        wins=("is_winner", "sum"),
        avg_pnl=("trade_pnl", "mean"),
        total_pnl=("trade_pnl", "sum"),
    ).reset_index()
    combo["win_rate"] = (combo["wins"] / combo["count"] * 100).round(1)

    for idx, r in combo.iterrows():
        mask = (df_setups["setup"] == r["setup"]) & (df_setups["symbol"] == r["symbol"])
        winners = df_setups[mask & (df_setups["trade_pnl"] > 0)]["trade_pnl"]
        losers = df_setups[mask & (df_setups["trade_pnl"] <= 0)]["trade_pnl"]
        avg_win = winners.mean() if len(winners) > 0 else 0
        avg_loss = abs(losers.mean()) if len(losers) > 0 else RISK_USD
        wr = r["win_rate"] / 100
        ev = wr * avg_win - (1 - wr) * avg_loss
        combo.at[idx, "ev"] = round(ev, 2)
        combo.at[idx, "avg_win"] = round(avg_win, 2)
        combo.at[idx, "avg_loss"] = round(avg_loss, 2)

    combo_sorted = combo.sort_values("ev", ascending=False)
    print(f"\n{'Setup':<28s} {'Sym':<6s} {'Side':<5s} {'N':>4s} {'WR%':>7s} {'AvgW':>8s} {'AvgL':>8s} {'EV':>9s} {'TotPnL':>10s}")
    print("-" * 90)
    for _, r in combo_sorted.iterrows():
        print(f"{r['setup']:<28s} {r['symbol']:<6s} {r['side']:<5s} {r['count']:>4.0f} {r['win_rate']:>6.1f}% ${r.get('avg_win',0):>7.2f} ${r.get('avg_loss',0):>7.2f} ${r.get('ev',0):>8.2f} ${r['total_pnl']:>9.2f}")

    # 5) Multi-horizon analysis
    print("\n" + "-" * 80)
    print("  OPTIMAL HOLDING PERIOD BY SETUP TYPE")
    print("-" * 80)

    print(f"\n{'Setup':<30s} {'1h WR':>7s} {'2h WR':>7s} {'4h WR':>7s} {'8h WR':>7s} {'Best':>6s}")
    print("-" * 70)
    for setup_type in df_setups["setup"].unique():
        mask = df_setups["setup"] == setup_type
        sub = df_setups[mask]
        wr_1h = sub["win_1h"].mean() * 100
        wr_2h = sub["win_2h"].mean() * 100
        wr_4h = sub["win_4h"].mean() * 100
        wr_8h = sub["win_8h"].mean() * 100
        wrs = {"1h": wr_1h, "2h": wr_2h, "4h": wr_4h, "8h": wr_8h}
        best = max(wrs, key=wrs.get)
        print(f"{setup_type:<30s} {wr_1h:>6.1f}% {wr_2h:>6.1f}% {wr_4h:>6.1f}% {wr_8h:>6.1f}% {best:>6s}")

    # 6) Top 10 individual trades by PnL
    print("\n" + "-" * 80)
    print("  TOP 10 HIGHEST-EV INDIVIDUAL SETUPS")
    print("-" * 80)

    top10 = df_setups.nlargest(10, "best_pnl")
    print(f"\n{'#':<3s} {'Symbol':<7s} {'Setup':<28s} {'Side':<5s} {'Price':>10s} {'BestPnL':>10s} {'Horizon':>8s} {'RSI':>6s}")
    print("-" * 80)
    for rank, (_, r) in enumerate(top10.iterrows(), 1):
        ts_str = str(r["timestamp"])[:16] if r["timestamp"] else "N/A"
        print(f"{rank:<3d} {r['symbol']:<7s} {r['setup']:<28s} {r['side']:<5s} ${r['price']:>9.2f} ${r['best_pnl']:>9.2f} {r['best_horizon']:>8s} {r.get('rsi', 0):>5.1f}")
        print(f"    Time: {ts_str}")

    # 7) Total theoretical PnL
    print("\n" + "=" * 80)
    print("  TOTAL THEORETICAL PnL (if all setups traded at 15x, $100 risk)")
    print("=" * 80)

    for horizon in ["1h", "2h", "4h", "8h"]:
        total = df_setups[f"pnl_{horizon}"].sum()
        wins = df_setups[f"win_{horizon}"].sum()
        total_trades = len(df_setups)
        wr = wins / total_trades * 100 if total_trades > 0 else 0
        print(f"  {horizon} hold: ${total:>10.2f} total PnL | {wr:.1f}% WR | {total_trades} trades")

    best_total = df_setups["best_pnl"].sum()
    print(f"\n  Best-case (optimal exit per trade): ${best_total:>10.2f}")
    print(f"  Average PnL per setup (4h): ${df_setups['trade_pnl'].mean():>.2f}")
    print(f"  Median PnL per setup (4h):  ${df_setups['trade_pnl'].median():>.2f}")

    # Positive EV setups only
    pos_ev = combo_sorted[combo_sorted["ev"] > 0]
    if len(pos_ev) > 0:
        print(f"\n  Positive-EV setup combinations: {len(pos_ev)}/{len(combo_sorted)}")
        pos_ev_setups = set(zip(pos_ev["setup"], pos_ev["symbol"], pos_ev["side"]))
        mask = df_setups.apply(lambda r: (r["setup"], r["symbol"], r["side"]) in pos_ev_setups, axis=1)
        filtered = df_setups[mask]
        print(f"  If only trading +EV setups: ${filtered['trade_pnl'].sum():>.2f} from {len(filtered)} trades")

    print("\n" + "=" * 80)
    print("  SCAN COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
