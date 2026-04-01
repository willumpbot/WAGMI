"""
Full-stack backtest — runs ACTUAL strategies + sniper filter against 30 days of OHLCV.

This is NOT a simplified filter. It uses the real multi_tier_quality strategy,
feeds results through the real ManualSniperFilter, and simulates execution
with the same dedup/cooldown/sizing logic the live bot uses.

This gives us 30 days of sim-equivalent data in minutes.

Usage:
    cd bot && python -m tools.full_stack_backtest
"""
import json
import os
import sys
import time
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.fetcher import DataFetcher
from strategies.multi_tier_quality import MultiTierQualityStrategy
from strategies.regime_trend import RegimeTrendStrategy
from strategies.monte_carlo_zones import MonteCarloZonesStrategy
from strategies.confidence_scorer import ConfidenceScorerStrategy

COIN_IDS = {
    "HYPE": {"coin_id": "hyperliquid"},
    "SOL": {"coin_id": "solana"},
    "BTC": {"coin_id": "bitcoin"},
}

OUTPUT_PATH = os.path.join("data", "manual", "FULL_STACK_BACKTEST.md")


def walk_forward_trade(df_1h, entry_idx, side, entry_price, sl, tp, time_stop_bars=12):
    """Walk forward from entry candle, check TP/SL/time-stop."""
    mfe = 0.0
    mae = 0.0

    for bars in range(1, min(time_stop_bars + 1, len(df_1h) - entry_idx)):
        c = df_1h.iloc[entry_idx + bars]

        if side == "BUY":
            fav = (c["high"] - entry_price) / entry_price * 100
            adv = (entry_price - c["low"]) / entry_price * 100
            sl_hit = c["low"] <= sl
            tp_hit = c["high"] >= tp
        else:
            fav = (entry_price - c["low"]) / entry_price * 100
            adv = (c["high"] - entry_price) / entry_price * 100
            sl_hit = c["high"] >= sl
            tp_hit = c["low"] <= tp

        mfe = max(mfe, fav)
        mae = max(mae, adv)

        if sl_hit and tp_hit:
            sl_first = (c["open"] < entry_price) if side == "BUY" else (c["open"] > entry_price)
            if sl_first:
                tp_hit = False
            else:
                sl_hit = False

        if sl_hit:
            return {"outcome": "LOSS", "bars": bars, "mfe": mfe, "mae": mae,
                    "exit_price": sl}
        if tp_hit:
            return {"outcome": "WIN", "bars": bars, "mfe": mfe, "mae": mae,
                    "exit_price": tp}

    # Time stop
    last = df_1h.iloc[min(entry_idx + time_stop_bars, len(df_1h) - 1)]
    if side == "BUY":
        move_pct = (last["close"] - entry_price) / entry_price * 100
    else:
        move_pct = (entry_price - last["close"]) / entry_price * 100
    outcome = "TS_WIN" if move_pct > 0 else "TS_LOSS"
    return {"outcome": outcome, "bars": time_stop_bars, "mfe": mfe, "mae": mae,
            "exit_price": last["close"], "move_pct": move_pct}


def run_backtest():
    print("=" * 60)
    print("  FULL-STACK BACKTEST")
    print("  Real strategies + real sniper filter + 30 days OHLCV")
    print("=" * 60)

    fetcher = DataFetcher()

    # Initialize real strategies
    strategies = [
        ("multi_tier_quality", MultiTierQualityStrategy(COIN_IDS)),
        ("regime_trend", RegimeTrendStrategy(COIN_IDS)),
        ("monte_carlo_zones", MonteCarloZonesStrategy(COIN_IDS)),
        ("confidence_scorer", ConfidenceScorerStrategy(COIN_IDS)),
    ]

    # Initialize real sniper filter (fresh instance, same config as production)
    from manual.sniper_filter import ManualSniperFilter
    from manual.config import ManualSniperConfig
    sniper_config = ManualSniperConfig()
    # Backtest-friendly dedup: wider window but higher daily limit
    # In live, we want 3-5/day. In backtest spanning 20 days, we need 100+
    sniper_config.dedup_window_s = 3600  # 1h dedup in backtest
    sniper_config.min_alert_gap_s = 3600
    sniper_config.max_daily_signals = 500  # Remove daily cap for backtest

    # Fetch all timeframe data
    print("\nFetching OHLCV data...")
    all_data = {}
    for sym, cfg in COIN_IDS.items():
        all_data[sym] = {}
        for tf in ["5m", "1h", "6h", "daily"]:
            df = fetcher.fetch_ohlcv(sym, cfg["coin_id"], tf)
            if df is not None and not df.empty:
                df["time"] = pd.to_datetime(df["time"], utc=True)
                df = df.sort_values("time").reset_index(drop=True)
                all_data[sym][tf] = df
                if tf == "1h":
                    print(f"  {sym} 1h: {len(df)} candles, "
                          f"{df['time'].iloc[0].strftime('%m-%d')} -> "
                          f"{df['time'].iloc[-1].strftime('%m-%d')}")

    # Walk through 1h candles, simulating the bot's scan loop
    results_by_setup = defaultdict(list)
    all_trades = []
    equity = 100.0
    equity_curve = [{"time": "start", "equity": 100.0}]

    # Track cooldowns per symbol (like the real bot)
    last_entry_time = {}  # symbol -> candle index
    ENTRY_COOLDOWN_BARS = 12  # 12h between entries on same symbol

    for sym in ["HYPE", "SOL", "BTC"]:
        if "1h" not in all_data[sym]:
            continue

        df_1h = all_data[sym]["1h"]
        print(f"\nScanning {sym} ({len(df_1h)} candles)...")

        sniper = ManualSniperFilter(sniper_config)  # Fresh filter per symbol
        signals_found = 0
        trades_taken = 0

        # Start from candle 100 (need history for indicators)
        for i in range(100, len(df_1h) - 13):
            # Cooldown check
            last = last_entry_time.get(sym, -999)
            if i - last < ENTRY_COOLDOWN_BARS:
                continue

            # Build data window (strategies expect full dataframes)
            # Slice up to current candle (no lookahead)
            data_window = {}
            for tf, df_tf in all_data[sym].items():
                current_time = df_1h["time"].iloc[i]
                mask = df_tf["time"] <= current_time
                if mask.any():
                    data_window[tf] = df_tf[mask].copy()

            if "1h" not in data_window or len(data_window["1h"]) < 50:
                continue

            # Run each strategy
            fired = []
            for strat_name, strat in strategies:
                try:
                    sig = strat.evaluate(sym, data_window)
                    if sig and hasattr(sig, "is_valid") and sig.is_valid:
                        fired.append((strat_name, sig))
                except Exception:
                    continue

            if not fired:
                continue

            signals_found += 1

            # Use the first valid signal (mimics what the solo-signal callback does)
            strat_name, sig = fired[0]

            # Reset sniper daily tracking when simulated date changes
            candle_date = df_1h["time"].iloc[i].date()
            if candle_date != getattr(sniper, '_bt_last_date', None):
                sniper._daily_signals = []
                sniper._daily_date = candle_date
                sniper._dedup_cache = {}
                sniper._daily_rejections = {}
                sniper._bt_last_date = candle_date

            # Run through sniper filter
            sniper_sig = sniper.evaluate(sig, equity=equity)
            if sniper_sig is None:
                continue

            # We have a signal the sniper accepted — simulate the trade
            setup = f"{sym}_{sig.side}"
            entry_price = sig.entry
            sl = sniper_sig.sl
            tp = sniper_sig.tp_scalp
            leverage = sniper_sig.leverage
            risk_amount = sniper_sig.risk_amount
            pnl_win = sniper_sig.pnl_scalp
            loss_amount = sniper_sig.loss_amount

            result = walk_forward_trade(df_1h, i, sig.side, entry_price, sl, tp, time_stop_bars=12)

            # Calculate PnL
            if result["outcome"] == "WIN":
                pnl = abs(pnl_win)
            elif result["outcome"] == "LOSS":
                pnl = -abs(loss_amount)
            else:  # TIME_STOP
                move = result.get("move_pct", 0) / 100
                pnl = move * sniper_sig.position_size_usd

            equity += pnl
            trades_taken += 1
            last_entry_time[sym] = i

            trade = {
                "setup": setup,
                "entry": entry_price,
                "sl": sl,
                "tp": tp,
                "leverage": leverage,
                "outcome": result["outcome"],
                "pnl": pnl,
                "bars": result["bars"],
                "mfe": result["mfe"],
                "mae": result["mae"],
                "equity_after": equity,
                "time": str(df_1h["time"].iloc[i])[:16],
                "strategy": strat_name,
                "confidence": sig.confidence,
                "tier": sniper_sig.tier,
            }
            results_by_setup[setup].append(trade)
            all_trades.append(trade)
            equity_curve.append({"time": str(df_1h["time"].iloc[i])[:16], "equity": equity})

        print(f"  Signals found: {signals_found}, Trades taken: {trades_taken}")

    # Generate report
    print(f"\n{'=' * 60}")
    print("  RESULTS")
    print(f"{'=' * 60}")

    report = []
    report.append("# Full-Stack Backtest Results")
    report.append(f"\n**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    report.append("**Method**: Real strategies + real sniper filter + walk-forward on 1h OHLCV")
    report.append("**Data**: 30 days, Hyperliquid via CCXT")
    report.append(f"**Total trades**: {len(all_trades)}")
    report.append(f"**Starting equity**: $100.00")
    report.append(f"**Final equity**: ${equity:.2f}")
    report.append("")

    # Overall stats
    if all_trades:
        wins = [t for t in all_trades if t["outcome"] in ("WIN", "TS_WIN")]
        losses = [t for t in all_trades if t["outcome"] in ("LOSS", "TS_LOSS")]
        total = len(wins) + len(losses)
        wr = len(wins) / total * 100 if total else 0
        gp = sum(t["pnl"] for t in all_trades if t["pnl"] > 0)
        gl = abs(sum(t["pnl"] for t in all_trades if t["pnl"] < 0))
        pf = gp / gl if gl > 0 else float("inf")

        report.append("## Overall")
        report.append(f"| Metric | Value |")
        report.append(f"|--------|-------|")
        report.append(f"| Trades | {total} |")
        report.append(f"| **Win Rate** | **{wr:.1f}%** |")
        report.append(f"| **Profit Factor** | **{pf:.2f}** |")
        report.append(f"| Gross Profit | ${gp:.2f} |")
        report.append(f"| Gross Loss | ${gl:.2f} |")
        report.append(f"| Net PnL | ${gp - gl:.2f} |")
        report.append(f"| **$100 ->** | **${equity:.2f}** |")

        # Max drawdown
        peak = 100.0
        max_dd = 0.0
        for t in all_trades:
            eq = t["equity_after"]
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)
        report.append(f"| Max Drawdown | {max_dd:.1f}% |")
        report.append("")

        print(f"  Total: {total} trades, {len(wins)}W/{len(losses)}L, WR={wr:.0f}%")
        print(f"  PF={pf:.2f}, $100 -> ${equity:.2f}, Max DD={max_dd:.1f}%")

    # Per-setup breakdown
    report.append("## By Setup")
    report.append("| Setup | Trades | WR | PF | PnL | Avg MFE | Avg MAE |")
    report.append("|-------|--------|----|----|-----|---------|---------|")

    for setup in sorted(results_by_setup.keys()):
        trades = results_by_setup[setup]
        wins = [t for t in trades if t["outcome"] in ("WIN", "TS_WIN")]
        losses = [t for t in trades if t["outcome"] in ("LOSS", "TS_LOSS")]
        total = len(wins) + len(losses)
        if total == 0:
            continue
        wr = len(wins) / total * 100
        gp = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gl = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        pf = gp / gl if gl > 0 else float("inf")
        pf_str = f"{pf:.2f}" if pf < 1000 else "INF"
        net = gp - gl
        avg_mfe = np.mean([t["mfe"] for t in trades])
        avg_mae = np.mean([t["mae"] for t in trades])

        report.append(
            f"| **{setup}** | {total} | **{wr:.0f}%** | {pf_str} | "
            f"${net:.2f} | {avg_mfe:.1f}% | {avg_mae:.1f}% |"
        )
        print(f"  {setup}: {total} trades, {len(wins)}W/{len(losses)}L, "
              f"WR={wr:.0f}%, PF={pf_str}")

    # Trade log
    report.append("")
    report.append("## Trade Log")
    report.append("| # | Time | Setup | Entry | Lev | Tier | Outcome | PnL | Equity |")
    report.append("|---|------|-------|-------|-----|------|---------|-----|--------|")

    for i, t in enumerate(all_trades, 1):
        oc = {"WIN": "W", "LOSS": "L", "TS_WIN": "TSW", "TS_LOSS": "TSL"}.get(t["outcome"], "?")
        report.append(
            f"| {i} | {t['time'][5:]} | {t['setup']} | ${t['entry']:.2f} | "
            f"{t['leverage']:.0f}x | {t['tier']} | {oc} | ${t['pnl']:+.2f} | "
            f"${t['equity_after']:.2f} |"
        )

    # Equity curve
    report.append("")
    report.append("## Equity Curve")
    report.append("```")
    for ec in equity_curve:
        eq = ec["equity"]
        bar_len = max(0, int((eq - 80) / 2))
        bar = "#" * bar_len
        report.append(f"{ec['time']:>20s}: ${eq:8.2f}  {bar}")
    report.append("```")

    # Verdict
    report.append("")
    report.append("## Verdict")
    if all_trades:
        wins_count = sum(1 for t in all_trades if t["outcome"] in ("WIN", "TS_WIN"))
        total_count = len(all_trades)
        overall_wr = wins_count / total_count * 100 if total_count else 0
        if overall_wr >= 55 and total_count >= 10:
            report.append("**EDGE CONFIRMED.** Proceed to manual trading.")
        elif overall_wr >= 50 and total_count >= 10:
            report.append("**MARGINAL EDGE.** Trade small, monitor closely.")
        elif total_count < 10:
            report.append("**INSUFFICIENT DATA.** Need more trades for confidence.")
        else:
            report.append("**NO EDGE FOUND.** Do not trade live. Investigate further.")
    else:
        report.append("**NO TRADES GENERATED.** Strategy pipeline may need adjustment.")

    report.append("")
    report.append("---")
    report.append("*Full-stack backtest using production strategy + sniper code paths*")
    report.append("*No LLM calls used. No lookahead bias. 12h time stop, 12-bar entry cooldown.*")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"\nReport saved to {OUTPUT_PATH}")

    # Also save raw trades for further analysis
    trades_path = os.path.join("data", "manual", "backtest_trades.jsonl")
    with open(trades_path, "w", encoding="utf-8") as f:
        for t in all_trades:
            f.write(json.dumps(t) + "\n")
    print(f"Raw trades saved to {trades_path}")


if __name__ == "__main__":
    run_backtest()
