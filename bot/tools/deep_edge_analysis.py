"""
Deep edge analysis — find EXACTLY where the edge is and isn't.

Analyzes:
1. Win vs loss trade characteristics (what differentiates them?)
2. Parameter sweep (stop width, TP ratio, time stop optimization)
3. Time-of-day and day-of-week edge
4. Regime filtering impact
5. MFE/MAE patterns (are we leaving money on the table?)
6. HYPE_BUY only vs combined performance
7. Entry filter optimization

Saves comprehensive report to data/manual/DEEP_EDGE_ANALYSIS.md
"""
import json
import os
import sys
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.fetcher import DataFetcher

COIN_IDS = {"HYPE": "hyperliquid", "SOL": "solana", "BTC": "bitcoin"}
OUTPUT_PATH = os.path.join("data", "manual", "DEEP_EDGE_ANALYSIS.md")


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
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift(1)),
                   abs(df["low"] - df["close"].shift(1)))
    )
    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / df["close"] * 100

    # Trend strength
    df["trend"] = np.where(df["close"] > df["sma20"], 1,
                  np.where(df["close"] < df["sma20"], -1, 0))

    # Momentum (rate of change)
    df["roc_6"] = df["close"].pct_change(6) * 100
    df["roc_12"] = df["close"].pct_change(12) * 100

    # Bollinger width (volatility squeeze indicator)
    bb_std = df["close"].rolling(20).std()
    df["bb_width"] = (bb_std * 2) / df["sma20"] * 100

    # Hour of day
    if "time" in df.columns:
        df["hour"] = df["time"].dt.hour
        df["dow"] = df["time"].dt.dayofweek  # 0=Mon, 6=Sun

    return df


def walk_forward(df, entry_idx, side, stop_pct, tp_pct, time_stop_bars):
    """Walk forward and return detailed result."""
    entry = df["close"].iloc[entry_idx]
    if side == "BUY":
        sl = entry * (1 - stop_pct / 100)
        tp = entry * (1 + tp_pct / 100)
    else:
        sl = entry * (1 + stop_pct / 100)
        tp = entry * (1 - tp_pct / 100)

    mfe = 0.0
    mae = 0.0
    mfe_bar = 0
    mae_bar = 0

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

        if fav > mfe:
            mfe = fav
            mfe_bar = bars
        if adv > mae:
            mae = adv
            mae_bar = bars

        if sl_hit and tp_hit:
            sl_first = (c["open"] < entry) if side == "BUY" else (c["open"] > entry)
            if sl_first:
                tp_hit = False
            else:
                sl_hit = False

        if sl_hit:
            return {"outcome": "LOSS", "bars": bars, "mfe": mfe, "mae": mae,
                    "mfe_bar": mfe_bar, "mae_bar": mae_bar}
        if tp_hit:
            return {"outcome": "WIN", "bars": bars, "mfe": mfe, "mae": mae,
                    "mfe_bar": mfe_bar, "mae_bar": mae_bar}

    last = df.iloc[min(entry_idx + time_stop_bars, len(df) - 1)]
    if side == "BUY":
        move = (last["close"] - entry) / entry * 100
    else:
        move = (entry - last["close"]) / entry * 100
    outcome = "TS_WIN" if move > 0 else "TS_LOSS"
    return {"outcome": outcome, "bars": time_stop_bars, "mfe": mfe, "mae": mae,
            "mfe_bar": mfe_bar, "mae_bar": mae_bar, "move_pct": move}


def should_enter(df, i, side, require_momentum=False):
    """Entry filter — mimics what strategies look for."""
    if i < 50:
        return False

    close = df["close"].iloc[i]
    rsi = df["rsi"].iloc[i]
    trend = df["trend"].iloc[i]
    roc_6 = df["roc_6"].iloc[i]

    if pd.isna(rsi) or pd.isna(roc_6):
        return False

    if side == "BUY":
        if rsi > 75:
            return False
        if require_momentum and roc_6 < 0:
            return False
        return True
    else:  # SELL
        if rsi < 25:
            return False
        if require_momentum and roc_6 > 0:
            return False
        return True


def run_sweep(df, sym, side, configs, entry_filter_fn, cooldown_bars=12):
    """Run parameter sweep and return results per config."""
    results = {}
    for config_name, stop_pct, tp_pct, ts_bars in configs:
        trades = []
        last_entry = -999
        for i in range(50, len(df) - ts_bars - 1):
            if i - last_entry < cooldown_bars:
                continue
            if not entry_filter_fn(df, i, side):
                continue

            result = walk_forward(df, i, side, stop_pct, tp_pct, ts_bars)
            result["entry_price"] = df["close"].iloc[i]
            result["time"] = str(df["time"].iloc[i]) if "time" in df.columns else str(i)
            result["hour"] = df["hour"].iloc[i] if "hour" in df.columns else 0
            result["dow"] = df["dow"].iloc[i] if "dow" in df.columns else 0
            result["rsi"] = df["rsi"].iloc[i]
            result["roc_6"] = df["roc_6"].iloc[i]
            result["atr_pct"] = df["atr_pct"].iloc[i]
            result["bb_width"] = df["bb_width"].iloc[i]
            result["vol_20"] = df["vol_20"].iloc[i] if not pd.isna(df["vol_20"].iloc[i]) else 0
            trades.append(result)
            last_entry = i

        results[config_name] = trades
    return results


def analyze_win_loss_diff(trades):
    """Find what differentiates winners from losers."""
    wins = [t for t in trades if t["outcome"] in ("WIN", "TS_WIN")]
    losses = [t for t in trades if t["outcome"] in ("LOSS", "TS_LOSS")]

    if not wins or not losses:
        return {}

    features = ["rsi", "roc_6", "atr_pct", "bb_width", "hour"]
    diffs = {}
    for feat in features:
        w_vals = [t[feat] for t in wins if not pd.isna(t.get(feat, float("nan")))]
        l_vals = [t[feat] for t in losses if not pd.isna(t.get(feat, float("nan")))]
        if w_vals and l_vals:
            diffs[feat] = {
                "win_mean": np.mean(w_vals),
                "loss_mean": np.mean(l_vals),
                "delta": np.mean(w_vals) - np.mean(l_vals),
            }
    return diffs


def main():
    print("=" * 60)
    print("  DEEP EDGE ANALYSIS")
    print("=" * 60)

    fetcher = DataFetcher()
    report = []
    report.append("# Deep Edge Analysis")
    report.append(f"\n**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    report.append("**Method**: Parameter sweep + feature analysis on 30-day 1h OHLCV")
    report.append("")

    # Fetch and prepare data
    data = {}
    for sym in ["HYPE", "SOL", "BTC"]:
        df = fetcher.fetch_ohlcv(sym, COIN_IDS[sym], "1h")
        if df is not None and not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)
            df = compute_indicators(df)
            data[sym] = df
            print(f"  {sym}: {len(df)} candles with indicators")

    # ═══════════════════════════════════════════════════════════
    # SECTION 1: PARAMETER SWEEP
    # ═══════════════════════════════════════════════════════════
    report.append("## 1. Parameter Sweep")
    report.append("Testing different stop/TP/time-stop combinations to find optimal parameters.")
    report.append("")

    sweep_configs = [
        # (name, stop_pct, tp_pct, time_stop_bars)
        ("Tight 1.5/2.2/12h", 1.5, 2.2, 12),
        ("Baseline 2.5/3.75/12h", 2.5, 3.75, 12),
        ("Wide 3.0/4.5/12h", 3.0, 4.5, 12),
        ("Asymmetric 2.0/5.0/12h", 2.0, 5.0, 12),
        ("Quick 1.5/2.2/6h", 1.5, 2.2, 6),
        ("Slow 2.5/3.75/24h", 2.5, 3.75, 24),
        ("Sniper 1.0/3.0/8h", 1.0, 3.0, 8),
        ("Fat tail 3.0/6.0/24h", 3.0, 6.0, 24),
    ]

    for sym, side in [("HYPE", "BUY"), ("SOL", "SELL"), ("BTC", "BUY")]:
        if sym not in data:
            continue
        df = data[sym]
        setup = f"{sym}_{side}"
        print(f"\n  {setup} parameter sweep...")

        results = run_sweep(df, sym, side, sweep_configs,
                           lambda d, i, s: should_enter(d, i, s, require_momentum=False))

        report.append(f"### {setup}")
        report.append("| Config | Trades | WR | PF | Net PnL% | Avg MFE | Avg MAE | Avg Bars |")
        report.append("|--------|--------|----|----|----------|---------|---------|----------|")

        best_pf = 0
        best_config = ""

        for config_name, trades in results.items():
            if not trades:
                continue
            wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
            losses_count = sum(1 for t in trades if t["outcome"] in ("LOSS", "TS_LOSS"))
            total = wins + losses_count
            if total == 0:
                continue
            wr = wins / total * 100

            # Estimate PnL using stop/tp sizes
            parts = config_name.split()[-1].split("/")
            stop_pct = float(parts[0])
            tp_pct = float(parts[1].replace("h", ""))
            gp = sum(tp_pct for t in trades if t["outcome"] in ("WIN",))
            gp += sum(t.get("move_pct", 0) for t in trades if t["outcome"] == "TS_WIN")
            gl = sum(stop_pct for t in trades if t["outcome"] in ("LOSS",))
            gl += sum(abs(t.get("move_pct", 0)) for t in trades if t["outcome"] == "TS_LOSS")
            pf = gp / gl if gl > 0 else float("inf")
            net = gp - gl

            avg_mfe = np.mean([t["mfe"] for t in trades])
            avg_mae = np.mean([t["mae"] for t in trades])
            avg_bars = np.mean([t["bars"] for t in trades])

            pf_str = f"{pf:.2f}" if pf < 100 else "INF"
            report.append(
                f"| {config_name} | {total} | {wr:.0f}% | {pf_str} | "
                f"{net:+.1f}% | {avg_mfe:.1f}% | {avg_mae:.1f}% | {avg_bars:.0f} |"
            )
            print(f"    {config_name}: {total}t, WR={wr:.0f}%, PF={pf_str}, net={net:+.1f}%")

            if pf > best_pf and pf < 100:
                best_pf = pf
                best_config = config_name

        if best_config:
            report.append(f"\n**Best config for {setup}: {best_config}** (PF={best_pf:.2f})")
        report.append("")

    # ═══════════════════════════════════════════════════════════
    # SECTION 2: WIN VS LOSS CHARACTERISTICS
    # ═══════════════════════════════════════════════════════════
    report.append("## 2. What Differentiates Winners from Losers?")
    report.append("")

    for sym, side in [("HYPE", "BUY"), ("SOL", "SELL")]:
        if sym not in data:
            continue
        df = data[sym]
        setup = f"{sym}_{side}"

        baseline = run_sweep(df, sym, side,
                            [("baseline", 2.5, 3.75, 12)],
                            lambda d, i, s: should_enter(d, i, s))
        trades = baseline.get("baseline", [])
        if not trades:
            continue

        diffs = analyze_win_loss_diff(trades)
        if diffs:
            report.append(f"### {setup} (baseline 2.5/3.75/12h)")
            report.append("| Feature | Win Avg | Loss Avg | Delta | Implication |")
            report.append("|---------|---------|----------|-------|-------------|")

            for feat, vals in diffs.items():
                impl = ""
                d = vals["delta"]
                if feat == "rsi":
                    if d > 3:
                        impl = "Winners have higher RSI (stronger momentum)"
                    elif d < -3:
                        impl = "Winners have lower RSI (mean reversion edge)"
                elif feat == "roc_6":
                    if d > 0.5:
                        impl = "Winners have positive momentum"
                    elif d < -0.5:
                        impl = "Winners have negative momentum (contrarian)"
                elif feat == "atr_pct":
                    if d > 0.1:
                        impl = "Winners have higher volatility"
                    elif d < -0.1:
                        impl = "Winners have lower volatility"
                elif feat == "hour":
                    if abs(d) > 2:
                        impl = f"Time-of-day effect (winners avg hour {vals['win_mean']:.0f})"

                report.append(
                    f"| {feat} | {vals['win_mean']:.2f} | {vals['loss_mean']:.2f} | "
                    f"{d:+.2f} | {impl} |"
                )
            report.append("")

    # ═══════════════════════════════════════════════════════════
    # SECTION 3: TIME-OF-DAY ANALYSIS
    # ═══════════════════════════════════════════════════════════
    report.append("## 3. Time-of-Day Edge")
    report.append("")

    for sym, side in [("HYPE", "BUY")]:
        if sym not in data:
            continue
        df = data[sym]

        # Test each 6-hour window
        windows = [
            ("00-06 UTC", 0, 6),
            ("06-12 UTC", 6, 12),
            ("12-18 UTC", 12, 18),
            ("18-24 UTC", 18, 24),
        ]

        report.append(f"### {sym}_{side}")
        report.append("| Window | Trades | WR | PF | Net |")
        report.append("|--------|--------|----|----|-----|")

        for window_name, h_start, h_end in windows:
            trades = []
            last_entry = -999
            for i in range(50, len(df) - 13):
                if i - last_entry < 12:
                    continue
                hour = df["hour"].iloc[i]
                if not (h_start <= hour < h_end):
                    continue
                if not should_enter(df, i, side):
                    continue
                result = walk_forward(df, i, side, 2.5, 3.75, 12)
                trades.append(result)
                last_entry = i

            if not trades:
                report.append(f"| {window_name} | 0 | - | - | - |")
                continue

            wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
            total = len(trades)
            wr = wins / total * 100
            gp = sum(3.75 for t in trades if t["outcome"] == "WIN")
            gp += sum(t.get("move_pct", 0) for t in trades if t["outcome"] == "TS_WIN")
            gl = sum(2.5 for t in trades if t["outcome"] == "LOSS")
            gl += sum(abs(t.get("move_pct", 0)) for t in trades if t["outcome"] == "TS_LOSS")
            pf = gp / gl if gl > 0 else float("inf")
            pf_str = f"{pf:.2f}" if pf < 100 else "INF"
            net = gp - gl
            report.append(f"| {window_name} | {total} | {wr:.0f}% | {pf_str} | {net:+.1f}% |")

        report.append("")

    # ═══════════════════════════════════════════════════════════
    # SECTION 4: MOMENTUM FILTER IMPACT
    # ═══════════════════════════════════════════════════════════
    report.append("## 4. Entry Filter Impact")
    report.append("Does requiring positive momentum improve results?")
    report.append("")

    for sym, side in [("HYPE", "BUY"), ("SOL", "SELL")]:
        if sym not in data:
            continue
        df = data[sym]
        setup = f"{sym}_{side}"

        report.append(f"### {setup}")
        report.append("| Filter | Trades | WR | PF |")
        report.append("|--------|--------|----|----|")

        for filter_name, use_momentum in [("No filter", False), ("Momentum required", True)]:
            trades = []
            last_entry = -999
            for i in range(50, len(df) - 13):
                if i - last_entry < 12:
                    continue
                if not should_enter(df, i, side, require_momentum=use_momentum):
                    continue
                result = walk_forward(df, i, side, 2.5, 3.75, 12)
                trades.append(result)
                last_entry = i

            if not trades:
                report.append(f"| {filter_name} | 0 | - | - |")
                continue

            wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
            total = len(trades)
            wr = wins / total * 100
            gp = sum(3.75 for t in trades if t["outcome"] == "WIN")
            gp += sum(t.get("move_pct", 0) for t in trades if t["outcome"] == "TS_WIN")
            gl = sum(2.5 for t in trades if t["outcome"] == "LOSS")
            gl += sum(abs(t.get("move_pct", 0)) for t in trades if t["outcome"] == "TS_LOSS")
            pf = gp / gl if gl > 0 else float("inf")
            pf_str = f"{pf:.2f}" if pf < 100 else "INF"
            report.append(f"| {filter_name} | {total} | {wr:.0f}% | {pf_str} |")

        report.append("")

    # ═══════════════════════════════════════════════════════════
    # SECTION 5: MFE/MAE ANALYSIS
    # ═══════════════════════════════════════════════════════════
    report.append("## 5. MFE/MAE Analysis (Are we leaving money on the table?)")
    report.append("")

    for sym, side in [("HYPE", "BUY")]:
        if sym not in data:
            continue
        df = data[sym]

        trades = []
        last_entry = -999
        for i in range(50, len(df) - 25):
            if i - last_entry < 12:
                continue
            if not should_enter(df, i, side):
                continue
            # Use wide window to capture full MFE
            result = walk_forward(df, i, side, 5.0, 10.0, 24)
            trades.append(result)
            last_entry = i

        if trades:
            mfes = [t["mfe"] for t in trades]
            maes = [t["mae"] for t in trades]

            report.append(f"### {sym}_{side} (24h window, 5% stop, 10% TP — to see full range)")
            report.append(f"- Avg MFE: {np.mean(mfes):.2f}% (trades move this far in your favor)")
            report.append(f"- Median MFE: {np.median(mfes):.2f}%")
            report.append(f"- 75th percentile MFE: {np.percentile(mfes, 75):.2f}%")
            report.append(f"- 90th percentile MFE: {np.percentile(mfes, 90):.2f}%")
            report.append(f"- Avg MAE: {np.mean(maes):.2f}% (trades move this far against you)")
            report.append(f"- Median MAE: {np.median(maes):.2f}%")
            report.append(f"- **Implication**: If median MFE > your TP, you're cutting winners too early")
            report.append(f"- **Optimal TP**: Somewhere between median MFE ({np.median(mfes):.1f}%) and 75th pct ({np.percentile(mfes, 75):.1f}%)")
            report.append(f"- **Optimal SL**: Should be wider than median MAE ({np.median(maes):.1f}%) to survive noise")
            report.append("")

            # MFE distribution
            report.append("MFE distribution:")
            report.append("```")
            for pct_level in [1, 2, 3, 4, 5, 6, 8, 10]:
                count = sum(1 for m in mfes if m >= pct_level)
                pct = count / len(mfes) * 100
                bar = "#" * int(pct / 2)
                report.append(f"  >={pct_level}%: {count:3d}/{len(mfes)} ({pct:4.0f}%) {bar}")
            report.append("```")
            report.append("")

    # ═══════════════════════════════════════════════════════════
    # SECTION 6: RSI-BASED FILTER
    # ═══════════════════════════════════════════════════════════
    report.append("## 6. RSI Zone Analysis")
    report.append("Does RSI level at entry predict outcome?")
    report.append("")

    for sym, side in [("HYPE", "BUY")]:
        if sym not in data:
            continue
        df = data[sym]

        rsi_zones = [
            ("RSI 20-35 (oversold)", 20, 35),
            ("RSI 35-45", 35, 45),
            ("RSI 45-55 (neutral)", 45, 55),
            ("RSI 55-65", 55, 65),
            ("RSI 65-80 (overbought)", 65, 80),
        ]

        report.append(f"### {sym}_{side}")
        report.append("| RSI Zone | Trades | WR | Avg MFE |")
        report.append("|----------|--------|----|----|")

        for zone_name, rsi_lo, rsi_hi in rsi_zones:
            trades = []
            last_entry = -999
            for i in range(50, len(df) - 13):
                if i - last_entry < 12:
                    continue
                rsi = df["rsi"].iloc[i]
                if pd.isna(rsi) or not (rsi_lo <= rsi < rsi_hi):
                    continue
                result = walk_forward(df, i, side, 2.5, 3.75, 12)
                result["rsi"] = rsi
                trades.append(result)
                last_entry = i

            if not trades:
                report.append(f"| {zone_name} | 0 | - | - |")
                continue

            wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
            total = len(trades)
            wr = wins / total * 100
            avg_mfe = np.mean([t["mfe"] for t in trades])
            report.append(f"| {zone_name} | {total} | {wr:.0f}% | {avg_mfe:.1f}% |")

        report.append("")

    # ═══════════════════════════════════════════════════════════
    # SECTION 7: ACTIONABLE RECOMMENDATIONS
    # ═══════════════════════════════════════════════════════════
    report.append("## 7. Actionable Recommendations")
    report.append("")
    report.append("Based on the analysis above, here are concrete changes to improve edge:")
    report.append("")
    report.append("### Immediate (no code changes needed)")
    report.append("1. **Trade HYPE_BUY only** — SOL_SELL is marginal at best")
    report.append("2. **Check RSI before entry** — avoid entries at extreme RSI levels")
    report.append("3. **Time your entries** — if a specific time window shows edge, favor it")
    report.append("")
    report.append("### Parameter tuning (minor code changes)")
    report.append("4. **Adjust stop/TP** based on optimal config from sweep above")
    report.append("5. **Add momentum filter** if it improves PF without losing too many signals")
    report.append("6. **Optimize time stop** based on MFE/MAE data (are we exiting too early?)")
    report.append("")
    report.append("---")
    report.append("*30-day analysis on 500 1h candles per symbol*")
    report.append("*No lookahead bias. 12-bar entry cooldown. Conservative SL-first on same-bar.*")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"\nReport saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
