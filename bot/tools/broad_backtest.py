"""
Broad backtest — test HYPE_BUY signal parameters across 30 days of 1h OHLCV data.

Instead of replaying logged signals, this generates synthetic entries at every candle
where the multi_tier_quality strategy WOULD fire (based on technical conditions),
then walks forward to check TP/SL/time-stop resolution.

This validates whether the 94% WR from the signal replay holds across a larger sample.
"""
import os
import sys
import numpy as np
import pandas as pd
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.fetcher import DataFetcher

COIN_IDS = {"HYPE": "hyperliquid", "SOL": "solana", "BTC": "bitcoin"}
OUTPUT_PATH = os.path.join("data", "manual", "BROAD_BACKTEST.md")


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def compute_atr(df, period=14):
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift(1)),
                   abs(df["low"] - df["close"].shift(1)))
    )
    return tr.rolling(period).mean()


def should_enter_buy(df, i):
    """Simple filter mimicking multi_tier_quality BUY conditions."""
    if i < 50:
        return False
    close = df["close"].iloc[i]
    sma20 = df["close"].iloc[i-20:i].mean()
    sma50 = df["close"].iloc[i-50:i].mean()
    rsi = compute_rsi(df["close"].iloc[:i+1]).iloc[-1]

    # BUY conditions: price near/above SMA20, RSI not overbought, some momentum
    if rsi > 70:  # Overbought
        return False
    if close < sma50 * 0.95:  # Too far below trend
        return False
    # Require some recent buying pressure
    last_3_closes = df["close"].iloc[i-3:i+1]
    if last_3_closes.iloc[-1] < last_3_closes.iloc[0]:  # Downward in last 3 candles
        return False
    return True


def should_enter_sell(df, i):
    """Simple filter mimicking multi_tier_quality SELL conditions."""
    if i < 50:
        return False
    close = df["close"].iloc[i]
    sma20 = df["close"].iloc[i-20:i].mean()
    rsi = compute_rsi(df["close"].iloc[:i+1]).iloc[-1]

    if rsi < 30:  # Oversold
        return False
    if close > sma20 * 1.05:  # Too far above mean
        return False
    last_3_closes = df["close"].iloc[i-3:i+1]
    if last_3_closes.iloc[-1] > last_3_closes.iloc[0]:
        return False
    return True


def walk_forward(df, entry_idx, side, stop_pct, tp_pct, time_stop_bars=12):
    """Walk forward from entry, check TP/SL/time-stop."""
    entry = df["close"].iloc[entry_idx]
    if side == "BUY":
        sl = entry * (1 - stop_pct / 100)
        tp = entry * (1 + tp_pct / 100)
    else:
        sl = entry * (1 + stop_pct / 100)
        tp = entry * (1 - tp_pct / 100)

    mfe = 0.0
    mae = 0.0

    for bars in range(1, min(time_stop_bars + 1, len(df) - entry_idx)):
        c = df.iloc[entry_idx + bars]

        if side == "BUY":
            fav = (c["high"] - entry) / entry * 100
            adv = (entry - c["low"]) / entry * 100
            sl_hit = c["low"] <= sl
            tp_hit = c["high"] >= tp
        else:
            fav = (entry - c["low"]) / entry * 100
            adv = (c["high"] - entry) / entry * 100
            sl_hit = c["high"] >= sl
            tp_hit = c["low"] <= tp

        mfe = max(mfe, fav)
        mae = max(mae, adv)

        if sl_hit and tp_hit:
            sl_first = (c["open"] < entry) if side == "BUY" else (c["open"] > entry)
            if sl_first:
                tp_hit = False
            else:
                sl_hit = False

        if sl_hit:
            return "LOSS", bars, mfe, mae
        if tp_hit:
            return "WIN", bars, mfe, mae

    # Time stop
    last_price = df["close"].iloc[min(entry_idx + time_stop_bars, len(df) - 1)]
    if side == "BUY":
        move = (last_price - entry) / entry * 100
    else:
        move = (entry - last_price) / entry * 100
    return "TS_WIN" if move > 0 else "TS_LOSS", time_stop_bars, mfe, mae


def run_backtest(sym, side, stop_pct, tp_pct, time_stop_bars, df, filter_fn):
    """Run backtest across all candles where filter triggers."""
    results = []
    last_entry = -6  # Cooldown between entries

    for i in range(50, len(df) - time_stop_bars - 1):
        if i - last_entry < 6:  # 6-bar cooldown (6h between entries)
            continue
        if not filter_fn(df, i):
            continue

        outcome, bars, mfe, mae = walk_forward(df, i, side, stop_pct, tp_pct, time_stop_bars)
        results.append({
            "outcome": outcome,
            "bars": bars,
            "mfe": mfe,
            "mae": mae,
            "time": str(df["time"].iloc[i])[:16] if "time" in df.columns else i,
        })
        last_entry = i

    return results


def main():
    fetcher = DataFetcher()
    report = []
    report.append("# Broad Backtest — 30-Day OHLCV Validation")
    report.append("")
    report.append("Tests sniper signal parameters across 30 days of 1h data (not just the 27h signal window).")
    report.append("6-bar cooldown between entries to avoid over-counting.")
    report.append("")

    # Test configurations
    configs = [
        ("HYPE", "BUY", 2.5, 3.75, 12, should_enter_buy),
        ("HYPE", "BUY", 1.5, 2.2, 12, should_enter_buy),     # Tighter stops (current params)
        ("HYPE", "BUY", 2.5, 3.75, 24, should_enter_buy),
        ("SOL", "SELL", 2.2, 3.3, 12, should_enter_sell),
        ("SOL", "BUY", 2.0, 3.0, 12, should_enter_buy),
        ("BTC", "BUY", 1.5, 2.1, 12, should_enter_buy),
    ]

    # Also test blind entry (no filter) for comparison
    blind_configs = [
        ("HYPE", "BUY", 2.5, 3.75, 12, lambda df, i: i >= 50),  # Every candle
        ("HYPE", "BUY", 1.5, 2.2, 12, lambda df, i: i >= 50),
    ]

    report.append("## Filtered Entries (strategy-like conditions)")
    report.append("")
    report.append("| Setup | SL% | TP% | TS(h) | Trades | Wins | Losses | WR | Avg MFE | Avg MAE |")
    report.append("|-------|-----|-----|-------|--------|------|--------|----|---------|---------|")

    for sym, side, stop_pct, tp_pct, ts_bars, filter_fn in configs:
        df = fetcher.fetch_ohlcv(sym, COIN_IDS.get(sym, sym.lower()), "1h")
        if df is None or df.empty:
            continue
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        results = run_backtest(sym, side, stop_pct, tp_pct, ts_bars, df, filter_fn)
        if not results:
            report.append(f"| {sym}_{side} | {stop_pct}% | {tp_pct}% | {ts_bars}h | 0 | - | - | - | - | - |")
            continue

        wins = sum(1 for r in results if r["outcome"] in ("WIN", "TS_WIN"))
        losses = sum(1 for r in results if r["outcome"] in ("LOSS", "TS_LOSS"))
        total = wins + losses
        wr = wins / total * 100 if total else 0
        avg_mfe = np.mean([r["mfe"] for r in results])
        avg_mae = np.mean([r["mae"] for r in results])

        setup = f"{sym}_{side}"
        report.append(
            f"| {setup} | {stop_pct}% | {tp_pct}% | {ts_bars}h | "
            f"{total} | {wins} | {losses} | **{wr:.0f}%** | {avg_mfe:.2f}% | {avg_mae:.2f}% |"
        )
        print(f"{setup} SL={stop_pct}% TP={tp_pct}% TS={ts_bars}h: {total} trades, {wins}W/{losses}L, WR={wr:.0f}%")

    report.append("")
    report.append("## Blind Entry Comparison (every candle, no filter)")
    report.append("")
    report.append("| Setup | SL% | TP% | TS(h) | Trades | Wins | Losses | WR |")
    report.append("|-------|-----|-----|-------|--------|------|--------|----|")

    for sym, side, stop_pct, tp_pct, ts_bars, filter_fn in blind_configs:
        df = fetcher.fetch_ohlcv(sym, COIN_IDS.get(sym, sym.lower()), "1h")
        if df is None or df.empty:
            continue
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        results = run_backtest(sym, side, stop_pct, tp_pct, ts_bars, df, filter_fn)
        if not results:
            continue

        wins = sum(1 for r in results if r["outcome"] in ("WIN", "TS_WIN"))
        losses = sum(1 for r in results if r["outcome"] in ("LOSS", "TS_LOSS"))
        total = wins + losses
        wr = wins / total * 100 if total else 0

        report.append(
            f"| {sym}_{side} | {stop_pct}% | {tp_pct}% | {ts_bars}h | "
            f"{total} | {wins} | {losses} | {wr:.0f}% |"
        )
        print(f"BLIND {sym}_{side} SL={stop_pct}% TP={tp_pct}%: {total} trades, WR={wr:.0f}%")

    report.append("")
    report.append("## Interpretation")
    report.append("")
    report.append("- If filtered WR >> blind WR: the strategy filter adds real edge")
    report.append("- If filtered WR ~= blind WR: edge might be from stop/TP geometry, not filtering")
    report.append("- If blind WR > 50%: underlying asset has directional bias in sample period")
    report.append("")
    report.append("---")
    report.append("*30-day backtest on 500 1h candles per symbol from Hyperliquid*")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
