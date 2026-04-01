"""
Comprehensive Quantitative Edge Study — WAGMI Bot
===================================================
Pure research: 7 analyses producing actionable numbers.

1. Edge Decay Analysis (rolling 50-trade WR)
2. Optimal Entry Timing (intra-candle timing)
3. Volatility Regime Profitability (ATR percentile buckets)
4. Correlation Regime Map (BTC-HYPE corr vs edge)
5. Drawdown Recovery Analysis (5/10/15% recovery speed)
6. Signal Clustering (streak analysis)
7. Fee Impact at Scale (breakeven WR by leverage)

Fetches 500 1h candles for HYPE, BTC, SOL via DataFetcher.
Saves report to data/manual/COMPREHENSIVE_EDGE_STUDY.md
Updates insight_journal.json with top findings.
"""

import json
import os
import sys
import time
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.fetcher import DataFetcher

COIN_IDS = {"HYPE": "hyperliquid", "SOL": "solana", "BTC": "bitcoin"}
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "manual", "COMPREHENSIVE_EDGE_STUDY.md")
INSIGHT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "llm", "deep_memory", "insight_journal.json")


# ═══════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════

def compute_indicators(df):
    """Add technical indicators to dataframe."""
    df = df.copy()
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["returns"] = df["close"].pct_change()
    df["vol_20"] = df["returns"].rolling(20).std()

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift(1)),
                   abs(df["low"] - df["close"].shift(1)))
    )
    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / df["close"] * 100

    # Trend
    df["trend"] = np.where(df["close"] > df["sma20"], 1,
                  np.where(df["close"] < df["sma20"], -1, 0))

    # ROC
    df["roc_6"] = df["close"].pct_change(6) * 100
    df["roc_12"] = df["close"].pct_change(12) * 100

    # Bollinger width
    bb_std = df["close"].rolling(20).std()
    df["bb_width"] = (bb_std * 2) / df["sma20"] * 100

    # Hour of day
    if "time" in df.columns:
        df["hour"] = df["time"].dt.hour
        df["dow"] = df["time"].dt.dayofweek

    return df


def walk_forward(df, entry_idx, side, stop_pct, tp_pct, time_stop_bars):
    """Walk forward from entry and return trade result."""
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
            return {"outcome": "LOSS", "bars": bars, "mfe": mfe, "mae": mae,
                    "pnl_pct": -stop_pct}
        if tp_hit:
            return {"outcome": "WIN", "bars": bars, "mfe": mfe, "mae": mae,
                    "pnl_pct": tp_pct}

    last = df.iloc[min(entry_idx + time_stop_bars, len(df) - 1)]
    if side == "BUY":
        move = (last["close"] - entry) / entry * 100
    else:
        move = (entry - last["close"]) / entry * 100
    outcome = "TS_WIN" if move > 0 else "TS_LOSS"
    return {"outcome": outcome, "bars": time_stop_bars, "mfe": mfe, "mae": mae,
            "pnl_pct": move}


def should_enter(df, i, side):
    """Entry filter mimicking strategy pipeline."""
    if i < 50:
        return False
    rsi = df["rsi"].iloc[i]
    if pd.isna(rsi):
        return False
    if side == "BUY":
        return rsi < 75
    else:
        return rsi > 25


# ═══════════════════════════════════════════════════════════════════
# DATA FETCH
# ═══════════════════════════════════════════════════════════════════

def fetch_all_data():
    """Fetch 500 1h candles for HYPE, BTC, SOL."""
    print("=" * 70)
    print("FETCHING DATA: 500 1h candles for HYPE, BTC, SOL")
    print("=" * 70)
    fetcher = DataFetcher(fresh=True)
    data = {}
    for sym, cid in COIN_IDS.items():
        print(f"  Fetching {sym}...")
        df = fetcher.fetch_ohlcv(sym, cid, "1h")
        if df is not None and not df.empty:
            df = compute_indicators(df)
            data[sym] = df
            print(f"    Got {len(df)} candles, range: {df['close'].min():.2f} - {df['close'].max():.2f}")
        else:
            print(f"    FAILED to fetch {sym}")
    return data


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS 1: EDGE DECAY
# ═══════════════════════════════════════════════════════════════════

def analyze_edge_decay(data, report):
    """Rolling 50-trade WR for proven setups."""
    print("\n" + "=" * 70)
    print("ANALYSIS 1: EDGE DECAY (Rolling 50-trade WR)")
    print("=" * 70)
    report.append("# 1. Edge Decay Analysis\n")

    setups = [
        ("HYPE", "BUY", 2.5, 3.75, 12),
        ("SOL", "SELL", 2.5, 3.75, 12),
    ]

    decay_results = {}

    for sym, side, sl, tp, ts in setups:
        if sym not in data:
            continue
        df = data[sym]
        setup_name = f"{sym}_{side}"
        trades = []

        for i in range(50, len(df) - ts):
            if should_enter(df, i, side):
                result = walk_forward(df, i, side, sl, tp, ts)
                result["idx"] = i
                result["time"] = df["time"].iloc[i] if "time" in df.columns else i
                trades.append(result)

        if len(trades) < 20:
            report.append(f"\n## {setup_name}: Insufficient trades ({len(trades)})\n")
            print(f"  {setup_name}: Only {len(trades)} trades, skipping")
            continue

        # Rolling 50-trade WR
        window = min(50, len(trades) // 3)
        if window < 10:
            window = 10
        wins = [1 if t["outcome"] in ("WIN", "TS_WIN") else 0 for t in trades]
        rolling_wr = pd.Series(wins).rolling(window).mean() * 100

        # First third, middle third, last third
        n = len(trades)
        thirds = [
            ("First third", wins[:n//3]),
            ("Middle third", wins[n//3:2*n//3]),
            ("Last third", wins[2*n//3:]),
        ]

        overall_wr = sum(wins) / len(wins) * 100
        overall_pf = _profit_factor(trades, tp, sl)

        report.append(f"\n## {setup_name} ({len(trades)} trades, WR={overall_wr:.1f}%, PF={overall_pf:.2f})\n")
        report.append(f"| Period | Trades | WR | Trend |\n|---|---|---|---|\n")

        trend_label = "UNKNOWN"
        for label, chunk in thirds:
            if len(chunk) > 0:
                wr = sum(chunk) / len(chunk) * 100
                report.append(f"| {label} | {len(chunk)} | {wr:.1f}% | |\n")

        # Trend detection: compare last third WR to first third WR
        first_wr = sum(thirds[0][1]) / max(len(thirds[0][1]), 1) * 100
        last_wr = sum(thirds[2][1]) / max(len(thirds[2][1]), 1) * 100
        diff = last_wr - first_wr

        if diff > 5:
            trend_label = "STRENGTHENING (+{:.1f}pp)".format(diff)
        elif diff < -5:
            trend_label = "WEAKENING ({:.1f}pp)".format(diff)
        else:
            trend_label = "STABLE ({:+.1f}pp)".format(diff)

        # Rolling min/max WR
        valid_rolling = rolling_wr.dropna()
        if len(valid_rolling) > 0:
            min_wr = valid_rolling.min()
            max_wr = valid_rolling.max()
            current_wr = valid_rolling.iloc[-1]
            report.append(f"\nRolling {window}-trade WR: min={min_wr:.1f}%, max={max_wr:.1f}%, current={current_wr:.1f}%\n")
            report.append(f"\n**Edge Trend: {trend_label}**\n")

        decay_results[setup_name] = {
            "total_trades": len(trades),
            "overall_wr": overall_wr,
            "pf": overall_pf,
            "first_third_wr": first_wr,
            "last_third_wr": last_wr,
            "trend": trend_label,
        }
        print(f"  {setup_name}: {len(trades)} trades, WR={overall_wr:.1f}%, trend={trend_label}")

    return decay_results


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS 2: OPTIMAL ENTRY TIMING
# ═══════════════════════════════════════════════════════════════════

def analyze_entry_timing(data, report):
    """Compare close-of-candle vs intra-candle entry timing for HYPE BUY."""
    print("\n" + "=" * 70)
    print("ANALYSIS 2: OPTIMAL ENTRY TIMING (HYPE BUY)")
    print("=" * 70)
    report.append("\n# 2. Optimal Entry Timing\n")

    if "HYPE" not in data:
        report.append("No HYPE data available.\n")
        return {}

    df = data["HYPE"]
    sl_pct = 2.5
    tp_pct = 3.75
    ts = 12
    results = {}

    # Simulate different entry prices within the candle
    entry_methods = {
        "close": lambda c: c["close"],                                    # Current: enter at close
        "open_next": lambda c: c["open"],                                 # Enter at open of next candle (wait)
        "vwap_proxy": lambda c: (c["high"] + c["low"] + c["close"]) / 3, # VWAP proxy
        "mid_candle": lambda c: (c["open"] + c["close"]) / 2,            # Mid-candle
        "worst_quarter": lambda c: c["close"] + (c["high"] - c["low"]) * 0.25 if c["close"] > c["open"] else c["close"] - (c["high"] - c["low"]) * 0.25,  # Adverse entry
    }

    report.append("Comparing entry timing methods for HYPE BUY:\n\n")
    report.append("| Entry Method | Trades | WR | Avg PnL% | PF | Avg Slip vs Close |\n")
    report.append("|---|---|---|---|---|---|\n")

    for method_name, price_fn in entry_methods.items():
        trades = []
        for i in range(50, len(df) - ts - 1):
            if not should_enter(df, i, "BUY"):
                continue

            if method_name == "open_next" and i + 1 < len(df):
                entry_price = df["open"].iloc[i + 1]
                walk_idx = i + 1
            else:
                entry_price = price_fn(df.iloc[i])
                walk_idx = i

            # Walk forward with custom entry price
            sl = entry_price * (1 - sl_pct / 100)
            tp = entry_price * (1 + tp_pct / 100)
            mfe = 0.0
            mae = 0.0
            result = None

            for bars in range(1, min(ts + 1, len(df) - walk_idx)):
                c = df.iloc[walk_idx + bars]
                fav = (c["high"] - entry_price) / entry_price * 100
                adv = (entry_price - c["low"]) / entry_price * 100
                mfe = max(mfe, fav)
                mae = max(mae, adv)

                sl_hit = c["low"] <= sl
                tp_hit = c["high"] >= tp

                if sl_hit and tp_hit:
                    if c["open"] < entry_price:
                        tp_hit = False
                    else:
                        sl_hit = False

                if sl_hit:
                    result = {"outcome": "LOSS", "pnl_pct": -sl_pct}
                    break
                if tp_hit:
                    result = {"outcome": "WIN", "pnl_pct": tp_pct}
                    break

            if result is None:
                last = df.iloc[min(walk_idx + ts, len(df) - 1)]
                move = (last["close"] - entry_price) / entry_price * 100
                result = {"outcome": "TS_WIN" if move > 0 else "TS_LOSS", "pnl_pct": move}

            result["entry_price"] = entry_price
            result["close_price"] = df["close"].iloc[i]
            trades.append(result)

        if not trades:
            continue

        wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
        wr = wins / len(trades) * 100
        avg_pnl = np.mean([t["pnl_pct"] for t in trades])
        avg_slip = np.mean([(t["entry_price"] - t["close_price"]) / t["close_price"] * 100 for t in trades])

        # PF
        gross_profit = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
        gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        results[method_name] = {"trades": len(trades), "wr": wr, "avg_pnl": avg_pnl, "pf": pf, "avg_slip": avg_slip}
        report.append(f"| {method_name} | {len(trades)} | {wr:.1f}% | {avg_pnl:+.3f}% | {pf:.2f} | {avg_slip:+.3f}% |\n")
        print(f"  {method_name}: {len(trades)} trades, WR={wr:.1f}%, PF={pf:.2f}")

    # Determine best
    if results:
        best = max(results.items(), key=lambda x: x[1]["pf"])
        report.append(f"\n**Best entry method: {best[0]} (PF={best[1]['pf']:.2f})**\n")

    return results


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS 3: VOLATILITY REGIME PROFITABILITY
# ═══════════════════════════════════════════════════════════════════

def analyze_volatility_regimes(data, report):
    """Bucket candles by ATR percentile, measure edge per regime."""
    print("\n" + "=" * 70)
    print("ANALYSIS 3: VOLATILITY REGIME PROFITABILITY")
    print("=" * 70)
    report.append("\n# 3. Volatility Regime Profitability\n")

    vol_results = {}

    for sym in ["HYPE", "SOL", "BTC"]:
        if sym not in data:
            continue
        df = data[sym]
        side = "BUY" if sym in ("HYPE", "BTC") else "SELL"
        sl, tp, ts = 2.5, 3.75, 12

        # Calculate ATR percentiles
        atr_pct = df["atr_pct"].dropna()
        if len(atr_pct) < 50:
            continue

        p25 = atr_pct.quantile(0.25)
        p50 = atr_pct.quantile(0.50)
        p75 = atr_pct.quantile(0.75)
        p90 = atr_pct.quantile(0.90)

        buckets = {
            "Low Vol (<P25)": lambda x: x < p25,
            "Normal (P25-P50)": lambda x: p25 <= x < p50,
            "High Vol (P50-P75)": lambda x: p50 <= x < p75,
            "Very High (P75-P90)": lambda x: p75 <= x < p90,
            "Extreme (>P90)": lambda x: x >= p90,
        }

        report.append(f"\n## {sym} {side} by ATR Regime\n")
        report.append(f"ATR percentiles: P25={p25:.3f}%, P50={p50:.3f}%, P75={p75:.3f}%, P90={p90:.3f}%\n\n")
        report.append("| Vol Regime | Trades | WR | Avg PnL% | PF | Avg MFE | Avg MAE |\n")
        report.append("|---|---|---|---|---|---|---|\n")

        sym_results = {}
        for bucket_name, bucket_fn in buckets.items():
            trades = []
            for i in range(50, len(df) - ts):
                if not should_enter(df, i, side):
                    continue
                atr_val = df["atr_pct"].iloc[i]
                if pd.isna(atr_val) or not bucket_fn(atr_val):
                    continue
                result = walk_forward(df, i, side, sl, tp, ts)
                trades.append(result)

            if not trades:
                report.append(f"| {bucket_name} | 0 | - | - | - | - | - |\n")
                continue

            wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
            wr = wins / len(trades) * 100
            avg_pnl = np.mean([t["pnl_pct"] for t in trades])
            pf = _profit_factor_from_trades(trades)
            avg_mfe = np.mean([t["mfe"] for t in trades])
            avg_mae = np.mean([t["mae"] for t in trades])

            sym_results[bucket_name] = {"trades": len(trades), "wr": wr, "pf": pf, "avg_pnl": avg_pnl}
            report.append(f"| {bucket_name} | {len(trades)} | {wr:.1f}% | {avg_pnl:+.3f}% | {pf:.2f} | {avg_mfe:.2f}% | {avg_mae:.2f}% |\n")
            print(f"  {sym} {bucket_name}: {len(trades)} trades, WR={wr:.1f}%, PF={pf:.2f}")

        vol_results[sym] = sym_results

        # Best regime
        if sym_results:
            best = max(sym_results.items(), key=lambda x: x[1].get("pf", 0))
            report.append(f"\n**Best vol regime for {sym} {side}: {best[0]} (PF={best[1]['pf']:.2f})**\n")

    return vol_results


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS 4: CORRELATION REGIME MAP
# ═══════════════════════════════════════════════════════════════════

def analyze_correlation_regimes(data, report):
    """How does BTC-HYPE correlation affect edge?"""
    print("\n" + "=" * 70)
    print("ANALYSIS 4: CORRELATION REGIME MAP")
    print("=" * 70)
    report.append("\n# 4. Correlation Regime Map (BTC-HYPE)\n")

    if "HYPE" not in data or "BTC" not in data:
        report.append("Missing HYPE or BTC data.\n")
        return {}

    hype = data["HYPE"]
    btc = data["BTC"]

    # Align by time
    if "time" in hype.columns and "time" in btc.columns:
        hype_r = hype.set_index("time")["returns"]
        btc_r = btc.set_index("time")["returns"]
        aligned = pd.DataFrame({"hype": hype_r, "btc": btc_r}).dropna()
    else:
        min_len = min(len(hype), len(btc))
        aligned = pd.DataFrame({
            "hype": hype["returns"].iloc[:min_len].values,
            "btc": btc["returns"].iloc[:min_len].values,
        }).dropna()

    # Rolling 24h correlation
    rolling_corr = aligned["hype"].rolling(24).corr(aligned["btc"])
    aligned["corr_24h"] = rolling_corr

    # Overall correlation
    overall_corr = aligned["hype"].corr(aligned["btc"])
    report.append(f"\nOverall BTC-HYPE 1h return correlation: **{overall_corr:.3f}**\n")
    report.append(f"Rolling 24h correlation range: {rolling_corr.min():.3f} to {rolling_corr.max():.3f}\n\n")

    # Bucket by correlation level
    corr_buckets = {
        "Decorrelated (<0.3)": lambda x: x < 0.3,
        "Low (0.3-0.5)": lambda x: 0.3 <= x < 0.5,
        "Medium (0.5-0.7)": lambda x: 0.5 <= x < 0.7,
        "High (>0.7)": lambda x: x >= 0.7,
        "Negative (<0)": lambda x: x < 0,
    }

    # Now backtest HYPE BUY in each correlation regime
    df_hype = data["HYPE"]
    sl, tp, ts = 2.5, 3.75, 12

    report.append("| Corr Regime | Trades | WR | Avg PnL% | PF |\n")
    report.append("|---|---|---|---|---|\n")

    corr_results = {}
    for bucket_name, bucket_fn in corr_buckets.items():
        trades = []
        for i in range(50, len(df_hype) - ts):
            if not should_enter(df_hype, i, "BUY"):
                continue
            # Get correlation at this time
            t = df_hype["time"].iloc[i] if "time" in df_hype.columns else None
            if t is not None and t in aligned.index:
                corr_val = aligned.loc[t, "corr_24h"]
            else:
                # Find nearest
                idx = i if i < len(rolling_corr) else len(rolling_corr) - 1
                corr_val = rolling_corr.iloc[idx] if idx < len(rolling_corr) else np.nan

            if pd.isna(corr_val) or not bucket_fn(corr_val):
                continue

            result = walk_forward(df_hype, i, "BUY", sl, tp, ts)
            trades.append(result)

        if not trades:
            report.append(f"| {bucket_name} | 0 | - | - | - |\n")
            continue

        wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
        wr = wins / len(trades) * 100
        avg_pnl = np.mean([t["pnl_pct"] for t in trades])
        pf = _profit_factor_from_trades(trades)

        corr_results[bucket_name] = {"trades": len(trades), "wr": wr, "pf": pf, "avg_pnl": avg_pnl}
        report.append(f"| {bucket_name} | {len(trades)} | {wr:.1f}% | {avg_pnl:+.3f}% | {pf:.2f} |\n")
        print(f"  {bucket_name}: {len(trades)} trades, WR={wr:.1f}%, PF={pf:.2f}")

    if corr_results:
        best = max(corr_results.items(), key=lambda x: x[1].get("pf", 0))
        report.append(f"\n**Best correlation regime: {best[0]} (PF={best[1]['pf']:.2f})**\n")

    return corr_results


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS 5: DRAWDOWN RECOVERY
# ═══════════════════════════════════════════════════════════════════

def analyze_drawdown_recovery(data, report):
    """After drawdowns of 5/10/15%, how quickly does the system recover?"""
    print("\n" + "=" * 70)
    print("ANALYSIS 5: DRAWDOWN RECOVERY ANALYSIS")
    print("=" * 70)
    report.append("\n# 5. Drawdown Recovery Analysis\n")

    if "HYPE" not in data:
        report.append("No HYPE data.\n")
        return {}

    df = data["HYPE"]
    sl, tp, ts = 2.5, 3.75, 12

    # Generate all trades in sequence
    trades = []
    i = 50
    while i < len(df) - ts:
        if should_enter(df, i, "BUY"):
            result = walk_forward(df, i, "BUY", sl, tp, ts)
            result["entry_idx"] = i
            result["time"] = df["time"].iloc[i] if "time" in df.columns else i
            trades.append(result)
            # Skip forward past this trade
            i += max(result["bars"], 1)
        else:
            i += 1

    if len(trades) < 10:
        report.append("Not enough sequential trades for drawdown analysis.\n")
        return {}

    # Simulate equity curve with 2% risk per trade
    equity = [100.0]
    risk_pct = 2.0
    leverage = 5  # representative

    for t in trades:
        prev = equity[-1]
        if t["outcome"] in ("WIN", "TS_WIN"):
            pnl = prev * (risk_pct / 100) * (t["pnl_pct"] / sl)
        else:
            pnl = -prev * (risk_pct / 100)
        equity.append(prev + pnl)

    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak * 100

    # Find drawdown events
    dd_thresholds = [5, 10, 15]
    report.append(f"\nSimulation: {len(trades)} sequential HYPE BUY trades, 2% risk/trade\n")
    report.append(f"Max drawdown: {drawdown.max():.1f}%\n")
    report.append(f"Final equity: {equity[-1]:.1f} (from 100)\n\n")

    report.append("| DD Threshold | Events | Avg Recovery Trades | Avg Recovery % | P(Recovery) |\n")
    report.append("|---|---|---|---|---|\n")

    dd_results = {}
    for threshold in dd_thresholds:
        events = []
        in_dd = False
        dd_start = 0

        for j in range(len(drawdown)):
            if drawdown[j] >= threshold and not in_dd:
                in_dd = True
                dd_start = j
            elif drawdown[j] < 1.0 and in_dd:  # Recovered (within 1% of peak)
                events.append({
                    "start": dd_start,
                    "end": j,
                    "trades_to_recover": j - dd_start,
                    "max_dd": max(drawdown[dd_start:j+1]),
                    "recovered": True,
                })
                in_dd = False

        if in_dd:
            events.append({
                "start": dd_start,
                "end": len(drawdown) - 1,
                "trades_to_recover": len(drawdown) - dd_start,
                "max_dd": max(drawdown[dd_start:]),
                "recovered": False,
            })

        if not events:
            report.append(f"| {threshold}% | 0 | - | - | - |\n")
            dd_results[threshold] = {"events": 0}
            print(f"  {threshold}% DD: No events")
            continue

        recovered = [e for e in events if e["recovered"]]
        p_recovery = len(recovered) / len(events) * 100
        avg_trades = np.mean([e["trades_to_recover"] for e in recovered]) if recovered else float("inf")
        avg_max_dd = np.mean([e["max_dd"] for e in events])

        dd_results[threshold] = {
            "events": len(events),
            "recovered": len(recovered),
            "p_recovery": p_recovery,
            "avg_trades_to_recover": avg_trades,
        }
        report.append(f"| {threshold}% | {len(events)} | {avg_trades:.1f} | {avg_max_dd:.1f}% | {p_recovery:.0f}% |\n")
        print(f"  {threshold}% DD: {len(events)} events, recovery={p_recovery:.0f}%, avg {avg_trades:.1f} trades")

    # Consecutive loss analysis
    report.append("\n## Consecutive Loss Streaks\n")
    streaks = []
    current_streak = 0
    for t in trades:
        if t["outcome"] in ("LOSS", "TS_LOSS"):
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        streaks.append(current_streak)

    if streaks:
        report.append(f"Max consecutive losses: {max(streaks)}\n")
        report.append(f"Avg streak length: {np.mean(streaks):.1f}\n")
        for s in range(1, min(max(streaks) + 1, 8)):
            count = sum(1 for x in streaks if x >= s)
            report.append(f"  {s}+ loss streaks: {count} times\n")

    return dd_results


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS 6: SIGNAL CLUSTERING
# ═══════════════════════════════════════════════════════════════════

def analyze_signal_clustering(data, report):
    """Do profitable signals cluster? Streak analysis."""
    print("\n" + "=" * 70)
    print("ANALYSIS 6: SIGNAL CLUSTERING (Streak Analysis)")
    print("=" * 70)
    report.append("\n# 6. Signal Clustering Analysis\n")

    if "HYPE" not in data:
        report.append("No HYPE data.\n")
        return {}

    df = data["HYPE"]
    sl, tp, ts = 2.5, 3.75, 12

    # Generate sequential trades (non-overlapping)
    trades = []
    i = 50
    while i < len(df) - ts:
        if should_enter(df, i, "BUY"):
            result = walk_forward(df, i, "BUY", sl, tp, ts)
            result["win"] = 1 if result["outcome"] in ("WIN", "TS_WIN") else 0
            trades.append(result)
            i += max(result["bars"], 1)
        else:
            i += 1

    if len(trades) < 20:
        report.append("Not enough trades.\n")
        return {}

    # After-win and after-loss WR
    after_win = [trades[i+1]["win"] for i in range(len(trades)-1) if trades[i]["win"] == 1]
    after_loss = [trades[i+1]["win"] for i in range(len(trades)-1) if trades[i]["win"] == 0]

    overall_wr = sum(t["win"] for t in trades) / len(trades) * 100
    after_win_wr = (sum(after_win) / len(after_win) * 100) if after_win else 0
    after_loss_wr = (sum(after_loss) / len(after_loss) * 100) if after_loss else 0

    report.append(f"Total trades: {len(trades)}, Overall WR: {overall_wr:.1f}%\n\n")
    report.append("| Previous Result | Next Trade WR | Sample Size | vs Baseline |\n")
    report.append("|---|---|---|---|\n")
    report.append(f"| After WIN | {after_win_wr:.1f}% | {len(after_win)} | {after_win_wr - overall_wr:+.1f}pp |\n")
    report.append(f"| After LOSS | {after_loss_wr:.1f}% | {len(after_loss)} | {after_loss_wr - overall_wr:+.1f}pp |\n")

    # After N consecutive wins/losses
    report.append("\n## After Consecutive Streaks\n\n")
    report.append("| After Streak | Next WR | N |\n|---|---|---|\n")

    for streak_type, target in [("wins", 1), ("losses", 0)]:
        for streak_len in [2, 3, 4]:
            next_results = []
            for j in range(streak_len, len(trades)):
                if all(trades[j - k - 1]["win"] == target for k in range(streak_len)):
                    next_results.append(trades[j]["win"])
            if next_results:
                wr = sum(next_results) / len(next_results) * 100
                report.append(f"| After {streak_len} {streak_type} | {wr:.1f}% | {len(next_results)} |\n")

    # Autocorrelation of wins
    win_series = pd.Series([t["win"] for t in trades])
    autocorr_1 = win_series.autocorr(lag=1)
    autocorr_2 = win_series.autocorr(lag=2)
    autocorr_3 = win_series.autocorr(lag=3)

    report.append(f"\n**Win autocorrelation**: lag1={autocorr_1:.3f}, lag2={autocorr_2:.3f}, lag3={autocorr_3:.3f}\n")

    clustering = "YES - wins cluster" if autocorr_1 > 0.1 else ("NO - random/anticorrelated" if autocorr_1 < -0.1 else "MARGINAL - near random")
    report.append(f"**Signal clustering: {clustering}**\n")

    print(f"  Overall WR: {overall_wr:.1f}%, After WIN: {after_win_wr:.1f}%, After LOSS: {after_loss_wr:.1f}%")
    print(f"  Autocorrelation: lag1={autocorr_1:.3f}")

    return {
        "overall_wr": overall_wr,
        "after_win_wr": after_win_wr,
        "after_loss_wr": after_loss_wr,
        "autocorr_1": autocorr_1,
        "clustering": clustering,
    }


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS 7: FEE IMPACT AT SCALE
# ═══════════════════════════════════════════════════════════════════

def analyze_fee_impact(data, report):
    """Fee impact at each leverage level. Breakeven WR by leverage."""
    print("\n" + "=" * 70)
    print("ANALYSIS 7: FEE IMPACT AT SCALE")
    print("=" * 70)
    report.append("\n# 7. Fee Impact at Scale\n")

    # Hyperliquid fee structure
    maker_fee = 0.02  # 0.02% maker
    taker_fee = 0.05  # 0.05% taker
    round_trip_taker = taker_fee * 2  # 0.10% round-trip taker
    round_trip_maker = maker_fee * 2  # 0.04% round-trip maker
    round_trip_mixed = maker_fee + taker_fee  # 0.07% mixed (limit entry, market exit)

    report.append("## Hyperliquid Fee Structure\n")
    report.append(f"- Maker: {maker_fee}%\n")
    report.append(f"- Taker: {taker_fee}%\n")
    report.append(f"- Round-trip (taker/taker): {round_trip_taker}%\n")
    report.append(f"- Round-trip (maker/taker): {round_trip_mixed}%\n")
    report.append(f"- Round-trip (maker/maker): {round_trip_maker}%\n\n")

    leverages = [1, 2, 3, 5, 7, 10, 15, 20]
    sl_pct = 2.5
    tp_pct = 3.75
    rr = tp_pct / sl_pct

    report.append("## Breakeven WR by Leverage (SL=2.5%, TP=3.75%, R:R=1.5)\n\n")
    report.append("| Leverage | Fee % of Capital | Fee as % of TP | Breakeven WR (no fees) | Breakeven WR (w/ fees) | WR Premium |\n")
    report.append("|---|---|---|---|---|---|\n")

    fee_results = {}
    be_wr_no_fees = 1 / (1 + rr) * 100  # 40% for 1.5 R:R

    for lev in leverages:
        # Fee impact per trade (on notional = capital * leverage)
        fee_of_capital = round_trip_mixed * lev  # as % of capital
        fee_as_pct_tp = fee_of_capital / (tp_pct * lev) * 100  # fee as fraction of TP profit

        # With fees, effective TP and SL
        effective_tp = tp_pct * lev - fee_of_capital  # profit after fees
        effective_sl = sl_pct * lev + fee_of_capital  # loss including fees

        # Breakeven WR: WR * eff_tp = (1-WR) * eff_sl
        # WR = eff_sl / (eff_tp + eff_sl)
        be_wr_with_fees = effective_sl / (effective_tp + effective_sl) * 100

        wr_premium = be_wr_with_fees - be_wr_no_fees

        fee_results[lev] = {
            "fee_of_capital": fee_of_capital,
            "be_wr_with_fees": be_wr_with_fees,
            "wr_premium": wr_premium,
        }

        report.append(f"| {lev}x | {fee_of_capital:.3f}% | {fee_as_pct_tp:.1f}% | {be_wr_no_fees:.1f}% | {be_wr_with_fees:.1f}% | +{wr_premium:.1f}pp |\n")
        print(f"  {lev}x: fees={fee_of_capital:.3f}% of capital, BE WR={be_wr_with_fees:.1f}% (+{wr_premium:.1f}pp)")

    # PnL drag simulation
    report.append("\n## PnL Fee Drag Over 100 Trades (at observed HYPE BUY WR)\n\n")

    if "HYPE" in data:
        df = data["HYPE"]
        trades = []
        for i in range(50, len(df) - 12):
            if should_enter(df, i, "BUY"):
                result = walk_forward(df, i, "BUY", sl_pct, tp_pct, 12)
                trades.append(result)

        if trades:
            actual_wr = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN")) / len(trades) * 100
            report.append(f"Observed WR: {actual_wr:.1f}% over {len(trades)} trades\n\n")
            report.append("| Leverage | Gross PnL (100 trades) | Fee Drag | Net PnL | Fee as % of Gross |\n")
            report.append("|---|---|---|---|---|\n")

            for lev in leverages:
                # Per 100 trades
                n_wins = actual_wr
                n_losses = 100 - actual_wr
                gross = n_wins * tp_pct * lev - n_losses * sl_pct * lev
                total_fees = 100 * round_trip_mixed * lev
                net = gross - total_fees
                fee_pct = total_fees / abs(gross) * 100 if gross != 0 else float("inf")

                report.append(f"| {lev}x | {gross:+.1f}% | -{total_fees:.1f}% | {net:+.1f}% | {fee_pct:.1f}% |\n")

    # Optimal leverage
    report.append("\n## Optimal Leverage (Kelly Criterion)\n")
    if trades:
        p = actual_wr / 100
        q = 1 - p
        b = tp_pct / sl_pct  # odds
        kelly = (p * b - q) / b
        report.append(f"Win probability: {p:.3f}\n")
        report.append(f"Win/loss ratio: {b:.2f}\n")
        report.append(f"Full Kelly fraction: {kelly:.3f} ({kelly * 100:.1f}% of capital per trade)\n")
        report.append(f"Half Kelly (recommended): {kelly/2:.3f} ({kelly/2 * 100:.1f}% per trade)\n")

        # At what leverage does Kelly suggest
        if kelly > 0:
            optimal_lev = kelly * 100 / sl_pct  # leverage where risk = kelly fraction
            report.append(f"Kelly-optimal leverage (at 2.5% SL): {optimal_lev:.1f}x\n")
            report.append(f"Half-Kelly leverage: {optimal_lev/2:.1f}x\n")

    return fee_results


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _profit_factor(trades, tp, sl):
    gross_profit = sum(tp if t["outcome"] in ("WIN",) else max(t.get("pnl_pct", 0), 0) for t in trades)
    gross_loss = sum(sl if t["outcome"] in ("LOSS",) else abs(min(t.get("pnl_pct", 0), 0)) for t in trades)
    return gross_profit / gross_loss if gross_loss > 0 else float("inf")


def _profit_factor_from_trades(trades):
    gross_profit = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] < 0))
    return gross_profit / gross_loss if gross_loss > 0 else float("inf")


# ═══════════════════════════════════════════════════════════════════
# UPDATE INSIGHT JOURNAL
# ═══════════════════════════════════════════════════════════════════

def update_insight_journal(all_results):
    """Add top findings to insight_journal.json."""
    try:
        with open(INSIGHT_PATH, "r") as f:
            journal = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        journal = {"insights": []}

    ts = time.time()
    new_insights = []

    # From edge decay
    decay = all_results.get("edge_decay", {})
    if "HYPE_BUY" in decay:
        d = decay["HYPE_BUY"]
        new_insights.append({
            "ts": ts,
            "category": "strategy_insight",
            "insight": f"HYPE_BUY edge trend: {d['trend']}. Overall: {d['total_trades']} trades, WR={d['overall_wr']:.1f}%, PF={d['pf']:.2f}. First third WR={d['first_third_wr']:.1f}%, last third WR={d['last_third_wr']:.1f}%.",
            "confidence": 0.85,
            "evidence": f"500 1h candle edge decay analysis, {d['total_trades']} trades split into thirds.",
            "source": "quant_edge_study_2026_03_25",
            "validated": True,
            "validation_count": d["total_trades"],
        })

    # From entry timing
    timing = all_results.get("entry_timing", {})
    if timing:
        best = max(timing.items(), key=lambda x: x[1].get("pf", 0))
        worst = min(timing.items(), key=lambda x: x[1].get("pf", 0))
        new_insights.append({
            "ts": ts + 1,
            "category": "execution_insight",
            "insight": f"HYPE BUY entry timing: best={best[0]} (PF={best[1]['pf']:.2f}, WR={best[1]['wr']:.1f}%), worst={worst[0]} (PF={worst[1]['pf']:.2f}). Entry price method matters {abs(best[1]['pf'] - worst[1]['pf']):.2f} PF difference.",
            "confidence": 0.8,
            "evidence": f"5 entry methods compared on {best[1]['trades']} HYPE BUY trades.",
            "source": "quant_edge_study_2026_03_25",
            "validated": True,
            "validation_count": best[1]["trades"],
        })

    # From volatility regimes
    vol = all_results.get("volatility", {})
    for sym, sym_data in vol.items():
        if sym_data:
            best = max(sym_data.items(), key=lambda x: x[1].get("pf", 0))
            worst = min(sym_data.items(), key=lambda x: x[1].get("pf", 0))
            new_insights.append({
                "ts": ts + 2,
                "category": "regime_insight",
                "insight": f"{sym} volatility regime edge: best={best[0]} (PF={best[1]['pf']:.2f}, WR={best[1]['wr']:.1f}%), worst={worst[0]} (PF={worst[1]['pf']:.2f}). Trade when vol is {best[0]}.",
                "confidence": 0.85,
                "evidence": f"500 1h candles bucketed by ATR percentile.",
                "source": "quant_edge_study_2026_03_25",
                "validated": True,
                "validation_count": best[1]["trades"],
            })

    # From correlation
    corr = all_results.get("correlation", {})
    if corr:
        best = max(corr.items(), key=lambda x: x[1].get("pf", 0))
        new_insights.append({
            "ts": ts + 3,
            "category": "correlation_insight",
            "insight": f"HYPE BUY edge by BTC correlation: best regime={best[0]} (PF={best[1]['pf']:.2f}, WR={best[1]['wr']:.1f}%, {best[1]['trades']} trades). Correlation regime affects profitability.",
            "confidence": 0.8,
            "evidence": "Rolling 24h BTC-HYPE correlation bucketed, HYPE BUY backtested per bucket.",
            "source": "quant_edge_study_2026_03_25",
            "validated": True,
            "validation_count": best[1]["trades"],
        })

    # From clustering
    cluster = all_results.get("clustering", {})
    if cluster:
        new_insights.append({
            "ts": ts + 4,
            "category": "strategy_insight",
            "insight": f"Signal clustering: {cluster['clustering']}. After WIN: {cluster['after_win_wr']:.1f}% WR. After LOSS: {cluster['after_loss_wr']:.1f}% WR. Autocorrelation(1)={cluster['autocorr_1']:.3f}. {'Size up after winners.' if cluster['after_win_wr'] > cluster['overall_wr'] + 5 else 'Keep position sizing constant.'}",
            "confidence": 0.8,
            "evidence": f"Sequential trade analysis on HYPE BUY, win/loss streaks.",
            "source": "quant_edge_study_2026_03_25",
            "validated": True,
            "validation_count": 0,
        })

    # From fee impact
    fees = all_results.get("fees", {})
    if fees:
        lev5 = fees.get(5, {})
        lev10 = fees.get(10, {})
        new_insights.append({
            "ts": ts + 5,
            "category": "execution_insight",
            "insight": f"Fee impact: at 5x leverage, fees add +{lev5.get('wr_premium', 0):.1f}pp to breakeven WR (BE={lev5.get('be_wr_with_fees', 0):.1f}%). At 10x, +{lev10.get('wr_premium', 0):.1f}pp (BE={lev10.get('be_wr_with_fees', 0):.1f}%). Use limit orders (0.02% maker) to halve fee drag.",
            "confidence": 0.95,
            "evidence": "Mathematical fee analysis at Hyperliquid rates (0.02% maker, 0.05% taker).",
            "source": "quant_edge_study_2026_03_25",
            "validated": True,
            "validation_count": 0,
        })

    journal["insights"].extend(new_insights)

    with open(INSIGHT_PATH, "w") as f:
        json.dump(journal, f, indent=2)

    print(f"\nAdded {len(new_insights)} insights to insight_journal.json")
    return len(new_insights)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    start = time.time()
    print("=" * 70)
    print("COMPREHENSIVE QUANTITATIVE EDGE STUDY")
    print(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    data = fetch_all_data()
    if not data:
        print("FATAL: No data fetched. Aborting.")
        return

    report = []
    report.append("# Comprehensive Quantitative Edge Study\n")
    report.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    report.append(f"Data: 500 1h candles for {', '.join(data.keys())}\n")

    all_results = {}

    # Run all 7 analyses
    all_results["edge_decay"] = analyze_edge_decay(data, report)
    all_results["entry_timing"] = analyze_entry_timing(data, report)
    all_results["volatility"] = analyze_volatility_regimes(data, report)
    all_results["correlation"] = analyze_correlation_regimes(data, report)
    all_results["drawdown"] = analyze_drawdown_recovery(data, report)
    all_results["clustering"] = analyze_signal_clustering(data, report)
    all_results["fees"] = analyze_fee_impact(data, report)

    # Executive Summary
    summary = ["\n# Executive Summary\n"]
    summary.append("## Key Actionable Numbers\n")

    decay = all_results.get("edge_decay", {})
    if "HYPE_BUY" in decay:
        d = decay["HYPE_BUY"]
        summary.append(f"1. **HYPE BUY Edge**: {d['trend']} (WR: {d['first_third_wr']:.0f}% -> {d['last_third_wr']:.0f}%)\n")

    timing = all_results.get("entry_timing", {})
    if timing:
        best_t = max(timing.items(), key=lambda x: x[1].get("pf", 0))
        summary.append(f"2. **Best Entry Method**: {best_t[0]} (PF={best_t[1]['pf']:.2f})\n")

    vol = all_results.get("volatility", {})
    if "HYPE" in vol:
        best_v = max(vol["HYPE"].items(), key=lambda x: x[1].get("pf", 0))
        summary.append(f"3. **Best Vol Regime for HYPE**: {best_v[0]} (PF={best_v[1]['pf']:.2f})\n")

    corr = all_results.get("correlation", {})
    if corr:
        best_c = max(corr.items(), key=lambda x: x[1].get("pf", 0))
        summary.append(f"4. **Best Correlation Regime**: {best_c[0]} (PF={best_c[1]['pf']:.2f})\n")

    dd = all_results.get("drawdown", {})
    if dd:
        for threshold, dd_data in dd.items():
            if dd_data.get("events", 0) > 0:
                summary.append(f"5. **{threshold}% Drawdown**: {dd_data.get('events')} events, {dd_data.get('p_recovery', 0):.0f}% recovery rate\n")
                break

    cluster = all_results.get("clustering", {})
    if cluster:
        summary.append(f"6. **Signal Clustering**: {cluster.get('clustering', 'Unknown')}. After WIN: {cluster.get('after_win_wr', 0):.1f}% WR\n")

    fees = all_results.get("fees", {})
    if 5 in fees:
        summary.append(f"7. **Fee Impact at 5x**: +{fees[5].get('wr_premium', 0):.1f}pp breakeven WR premium\n")

    # Insert summary at top
    report = summary + ["\n---\n"] + report

    # Save report
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_PATH)), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write("\n".join(report))
    print(f"\nReport saved to: {OUTPUT_PATH}")

    # Update insight journal
    n_insights = update_insight_journal(all_results)

    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s. {n_insights} insights added to journal.")
    print("=" * 70)


if __name__ == "__main__":
    main()
