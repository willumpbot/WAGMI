"""
Wick Noise Model: Maximum Adverse Excursion Analysis
=====================================================
Determines minimum stop-loss distances to survive normal market noise.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data" / "cache"
SYMBOLS = ["BTC", "SOL", "HYPE"]
EQUITY = 1025.0
RISK_PER_TRADE = 25.0  # max $ loss per trade

def load_data(symbol):
    fp = DATA_DIR / f"{symbol}_5m_30d.csv"
    df = pd.read_csv(fp, parse_dates=["time"])
    df = df.sort_values("time").reset_index(drop=True)
    return df

def compute_single_candle_wicks(df):
    """Per-candle wick excursion as % of close."""
    body_high = df[["open", "close"]].max(axis=1)
    body_low = df[["open", "close"]].min(axis=1)
    df["wick_up_pct"] = (df["high"] - body_high) / df["close"] * 100
    df["wick_down_pct"] = (body_low - df["low"]) / df["close"] * 100
    # Also compute full candle range
    df["range_pct"] = (df["high"] - df["low"]) / df["close"] * 100
    return df

def compute_multi_candle_mae(df, windows=[2, 3, 6, 12]):
    """
    Multi-candle Maximum Adverse Excursion.
    For each starting candle, look forward N candles and find max adverse move
    from the starting close.
    """
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    results = {}
    for w in windows:
        mae_long = []   # max adverse for a long (how far price drops below entry)
        mae_short = []  # max adverse for a short (how far price rises above entry)

        for i in range(len(df) - w):
            entry = closes[i]
            # For the next w candles (including current candle's close as entry)
            window_lows = lows[i+1:i+1+w]
            window_highs = highs[i+1:i+1+w]

            # MAE for LONG = (entry - min_low) / entry * 100
            min_low = window_lows.min()
            mae_l = max(0, (entry - min_low) / entry * 100)
            mae_long.append(mae_l)

            # MAE for SHORT = (max_high - entry) / entry * 100
            max_high = window_highs.max()
            mae_s = max(0, (max_high - entry) / entry * 100)
            mae_short.append(mae_s)

        results[w] = {
            "mae_long": np.array(mae_long),
            "mae_short": np.array(mae_short),
        }
    return results

def print_percentiles(arr, label, percentiles=[50, 75, 90, 95, 99]):
    vals = np.percentile(arr, percentiles)
    parts = [f"p{p}={v:.4f}%" for p, v in zip(percentiles, vals)]
    print(f"  {label:30s} | {' | '.join(parts)} | mean={np.mean(arr):.4f}% | max={np.max(arr):.4f}%")

def survival_table(arr, label, thresholds=[0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0]):
    """What % of the time does excursion EXCEED threshold?"""
    print(f"  {label}:")
    parts = []
    for t in thresholds:
        pct_exceed = (arr > t).mean() * 100
        parts.append(f"    >{t:.2f}%: {pct_exceed:.1f}% of candles")
    print("\n".join(parts))

def recommend_sl(mae_long_arr, mae_short_arr, symbol):
    """Recommend SL levels and max leverage."""
    print(f"\n  === RECOMMENDED STOP-LOSS for {symbol} ===")
    for side, arr, side_name in [("LONG", mae_long_arr, "long"), ("SHORT", mae_short_arr, "short")]:
        sl_90 = np.percentile(arr, 90)
        sl_95 = np.percentile(arr, 95)
        sl_99 = np.percentile(arr, 99)

        print(f"\n  {side} positions:")
        for pct_label, sl_val in [("90% survival", sl_90), ("95% survival", sl_95), ("99% survival", sl_99)]:
            # Max leverage = risk_budget / (equity * sl_pct/100)
            # If SL = 0.5%, equity = 1025, risk = 25:
            #   position_size = risk / (sl_pct/100) = 25 / 0.005 = 5000
            #   leverage = position_size / equity = 5000 / 1025 = 4.88x
            if sl_val > 0:
                max_position = RISK_PER_TRADE / (sl_val / 100)
                max_lev = max_position / EQUITY
            else:
                max_lev = float('inf')
            print(f"    {pct_label}: SL = {sl_val:.4f}% | max_lev = {max_lev:.1f}x | position = ${max_position:.0f}")

def main():
    print("=" * 120)
    print("WICK NOISE MODEL — Maximum Adverse Excursion Analysis")
    print(f"Equity: ${EQUITY} | Risk per trade: ${RISK_PER_TRADE}")
    print("=" * 120)

    for symbol in SYMBOLS:
        df = load_data(symbol)
        df = compute_single_candle_wicks(df)

        print(f"\n{'='*120}")
        print(f"  {symbol} — {len(df)} candles, {df['time'].min()} to {df['time'].max()}")
        print(f"  Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
        print(f"{'='*120}")

        # === SINGLE CANDLE WICKS ===
        print(f"\n--- SINGLE CANDLE (5-min) WICK ANALYSIS ---")
        print_percentiles(df["wick_up_pct"].values, "Wick UP (danger for SHORTS)")
        print_percentiles(df["wick_down_pct"].values, "Wick DOWN (danger for LONGS)")
        print_percentiles(df["range_pct"].values, "Full candle range")

        # === SURVIVAL TABLE ===
        print(f"\n--- SURVIVAL TABLE: How often does a single 5-min wick exceed X%? ---")
        survival_table(df["wick_up_pct"].values, "Wick UP (SHORT danger)")
        survival_table(df["wick_down_pct"].values, "Wick DOWN (LONG danger)")

        # === MULTI-CANDLE MAE ===
        windows = [2, 3, 6, 12, 24, 36]
        window_labels = {2: "10min", 3: "15min", 6: "30min", 12: "1h", 24: "2h", 36: "3h"}
        mae_results = compute_multi_candle_mae(df, windows=windows)

        print(f"\n--- MULTI-CANDLE MAX ADVERSE EXCURSION (from entry close) ---")
        print(f"  {'Window':10s} | {'Side':6s} | {'p50':>8s} | {'p75':>8s} | {'p90':>8s} | {'p95':>8s} | {'p99':>8s} | {'mean':>8s} | {'max':>8s}")
        print(f"  {'-'*10}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")

        for w in windows:
            for side, key in [("LONG", "mae_long"), ("SHORT", "mae_short")]:
                arr = mae_results[w][key]
                pcts = np.percentile(arr, [50, 75, 90, 95, 99])
                label = f"{window_labels[w]}"
                print(f"  {label:10s} | {side:6s} | {pcts[0]:7.4f}% | {pcts[1]:7.4f}% | {pcts[2]:7.4f}% | {pcts[3]:7.4f}% | {pcts[4]:7.4f}% | {np.mean(arr):7.4f}% | {np.max(arr):7.4f}%")

        # === MULTI-CANDLE SURVIVAL ===
        print(f"\n--- MULTI-CANDLE SURVIVAL: % of entries where MAE exceeds threshold ---")
        thresholds = [0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
        print(f"  {'Window':10s} | {'Side':6s} | " + " | ".join([f">{t:.1f}%" for t in thresholds]))
        print(f"  {'-'*10}-+-{'-'*6}-+-" + "-+-".join(["-"*6 for _ in thresholds]))

        for w in windows:
            for side, key in [("LONG", "mae_long"), ("SHORT", "mae_short")]:
                arr = mae_results[w][key]
                exceed_pcts = [(arr > t).mean() * 100 for t in thresholds]
                label = f"{window_labels[w]}"
                cols = " | ".join([f"{e:5.1f}%" for e in exceed_pcts])
                print(f"  {label:10s} | {side:6s} | {cols}")

        # === SL RECOMMENDATIONS ===
        # Use the 12-candle (1h) MAE as the primary recommendation
        # since most of our trades last at least 1 hour
        for hold_period, w in [(6, 6), (12, 12), (36, 36)]:
            label = window_labels[w]
            print(f"\n  === SL RECOMMENDATIONS for {symbol} (hold period: {label}) ===")
            for side, key, side_name in [("LONG", "mae_long", "long"), ("SHORT", "mae_short", "short")]:
                arr = mae_results[w][key]
                print(f"\n  {side} positions (based on {label} MAE):")
                for surv_pct in [90, 95, 99]:
                    sl_val = np.percentile(arr, surv_pct)
                    if sl_val > 0:
                        max_position = RISK_PER_TRADE / (sl_val / 100)
                        max_lev = max_position / EQUITY
                    else:
                        max_position = float('inf')
                        max_lev = float('inf')
                    print(f"    {surv_pct}% survival: SL = {sl_val:.4f}% | max leverage = {max_lev:.1f}x | max position = ${max_position:.0f}")

    # === CROSS-SYMBOL COMPARISON ===
    print(f"\n{'='*120}")
    print("CROSS-SYMBOL COMPARISON — Key Numbers for Config")
    print(f"{'='*120}")
    print(f"\n{'Symbol':8s} | {'Hold':6s} | {'Side':6s} | {'p90 SL':>8s} | {'p95 SL':>8s} | {'p99 SL':>8s} | {'max_lev@p95':>12s}")
    print(f"{'-'*8}-+-{'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*12}")

    for symbol in SYMBOLS:
        df = load_data(symbol)
        df = compute_single_candle_wicks(df)
        mae_results = compute_multi_candle_mae(df, windows=[6, 12, 36])

        for w, label in [(6, "30min"), (12, "1h"), (36, "3h")]:
            for side, key in [("LONG", "mae_long"), ("SHORT", "mae_short")]:
                arr = mae_results[w][key]
                p90 = np.percentile(arr, 90)
                p95 = np.percentile(arr, 95)
                p99 = np.percentile(arr, 99)
                if p95 > 0:
                    max_lev = (RISK_PER_TRADE / (p95 / 100)) / EQUITY
                else:
                    max_lev = float('inf')
                print(f"{symbol:8s} | {label:6s} | {side:6s} | {p90:7.4f}% | {p95:7.4f}% | {p99:7.4f}% | {max_lev:10.1f}x")

    # === ACTIONABLE CONFIG RECOMMENDATIONS ===
    print(f"\n{'='*120}")
    print("ACTIONABLE CONFIG RECOMMENDATIONS")
    print(f"{'='*120}")

    for symbol in SYMBOLS:
        df = load_data(symbol)
        df = compute_single_candle_wicks(df)
        mae_1h = compute_multi_candle_mae(df, windows=[12])[12]

        p95_long = np.percentile(mae_1h["mae_long"], 95)
        p95_short = np.percentile(mae_1h["mae_short"], 95)
        p95_both = max(p95_long, p95_short)

        max_lev = (RISK_PER_TRADE / (p95_both / 100)) / EQUITY

        print(f"\n  {symbol}:")
        print(f"    Min SL (95% noise survival, 1h hold): {p95_both:.3f}%")
        print(f"    Max leverage at this SL ($25 risk on $1025): {max_lev:.1f}x")
        print(f"    At 5x leverage: SL would need to be {RISK_PER_TRADE / (5 * EQUITY) * 100:.3f}% (survives {(mae_1h['mae_long'] <= RISK_PER_TRADE / (5 * EQUITY) * 100).mean()*100:.0f}% long / {(mae_1h['mae_short'] <= RISK_PER_TRADE / (5 * EQUITY) * 100).mean()*100:.0f}% short)")
        print(f"    At 10x leverage: SL would need to be {RISK_PER_TRADE / (10 * EQUITY) * 100:.3f}% (survives {(mae_1h['mae_long'] <= RISK_PER_TRADE / (10 * EQUITY) * 100).mean()*100:.0f}% long / {(mae_1h['mae_short'] <= RISK_PER_TRADE / (10 * EQUITY) * 100).mean()*100:.0f}% short)")
        print(f"    At 12x leverage: SL would need to be {RISK_PER_TRADE / (12 * EQUITY) * 100:.3f}% (survives {(mae_1h['mae_long'] <= RISK_PER_TRADE / (12 * EQUITY) * 100).mean()*100:.0f}% long / {(mae_1h['mae_short'] <= RISK_PER_TRADE / (12 * EQUITY) * 100).mean()*100:.0f}% short)")
        print(f"    At 15x leverage: SL would need to be {RISK_PER_TRADE / (15 * EQUITY) * 100:.3f}% (survives {(mae_1h['mae_long'] <= RISK_PER_TRADE / (15 * EQUITY) * 100).mean()*100:.0f}% long / {(mae_1h['mae_short'] <= RISK_PER_TRADE / (15 * EQUITY) * 100).mean()*100:.0f}% short)")
        print(f"    At 20x leverage: SL would need to be {RISK_PER_TRADE / (20 * EQUITY) * 100:.3f}% (survives {(mae_1h['mae_long'] <= RISK_PER_TRADE / (20 * EQUITY) * 100).mean()*100:.0f}% long / {(mae_1h['mae_short'] <= RISK_PER_TRADE / (20 * EQUITY) * 100).mean()*100:.0f}% short)")

    print(f"\n{'='*120}")
    print("KEY INSIGHT: leverage_max = risk$ / (equity$ * SL_pct/100)")
    print("At $25 risk on $1025 equity:")
    print("  SL=0.20% -> max 12.2x leverage")
    print("  SL=0.50% -> max 4.9x leverage")
    print("  SL=1.00% -> max 2.4x leverage")
    print("  SL=1.50% -> max 1.6x leverage")
    print("If your SL is smaller than the noise, you WILL get stopped out regardless of direction.")
    print(f"{'='*120}")

if __name__ == "__main__":
    main()
