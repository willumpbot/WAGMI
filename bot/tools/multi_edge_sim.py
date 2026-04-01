"""
Multi-Edge Simulator — Tests ALL parameter configs simultaneously on live data.

Instead of picking one config and waiting days, this runs 10+ configs in parallel
on every signal. Each config tracks its own equity curve independently.

Run periodically to see which config is winning in real-time:
    cd bot && python -m tools.multi_edge_sim --status
    cd bot && python -m tools.multi_edge_sim --run    # Feed from live sniper signals

Or backtest all configs against historical data:
    cd bot && python -m tools.multi_edge_sim --backtest
"""
import json
import os
import sys
import time
import argparse
import numpy as np
import pandas as pd
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA_DIR = os.path.join("data", "manual")
STATUS_PATH = os.path.join(DATA_DIR, "multi_edge_status.json")
TRADES_PATH = os.path.join(DATA_DIR, "multi_edge_trades.jsonl")

# ═══════════════════════════════════════════════════════════════
# EDGE CONFIGS — Every combination we want to test simultaneously
# ═══════════════════════════════════════════════════════════════

EDGE_CONFIGS = {
    # (name, sl_pct, tp_pct, leverage, time_stop_hours)

    # Scalp configs (fast resolution, high leverage)
    "scalp_tight":    {"sl": 0.8, "tp": 1.2, "lev": 20, "ts_h": 3, "desc": "Tight scalp 20x"},
    "scalp_mid":      {"sl": 1.0, "tp": 1.5, "lev": 15, "ts_h": 4, "desc": "Mid scalp 15x"},
    "scalp_wide":     {"sl": 1.5, "tp": 2.2, "lev": 10, "ts_h": 6, "desc": "Wide scalp 10x"},

    # BTC high-leverage configs
    "btc_sniper":     {"sl": 0.5, "tp": 1.0, "lev": 30, "ts_h": 2, "desc": "BTC sniper 30x"},
    "btc_scalp":      {"sl": 0.8, "tp": 1.5, "lev": 20, "ts_h": 3, "desc": "BTC scalp 20x"},
    "btc_swing":      {"sl": 1.5, "tp": 3.0, "lev": 10, "ts_h": 12, "desc": "BTC swing 10x"},

    # Current baseline
    "baseline":       {"sl": 2.5, "tp": 3.75, "lev": 6, "ts_h": 12, "desc": "Current baseline 6x"},

    # Fat tail configs (wider targets)
    "fat_tail":       {"sl": 3.0, "tp": 6.0, "lev": 5, "ts_h": 24, "desc": "Fat tail 5x"},

    # Asymmetric R:R configs
    "asym_2to1":      {"sl": 1.0, "tp": 2.0, "lev": 15, "ts_h": 6, "desc": "2:1 R:R 15x"},
    "asym_3to1":      {"sl": 1.0, "tp": 3.0, "lev": 12, "ts_h": 8, "desc": "3:1 R:R 12x"},
    "asym_5to1":      {"sl": 0.8, "tp": 4.0, "lev": 10, "ts_h": 12, "desc": "5:1 R:R 10x"},

    # Ultra-scalp (sub-1% moves, very high leverage)
    "ultra_scalp":    {"sl": 0.4, "tp": 0.6, "lev": 40, "ts_h": 1, "desc": "Ultra scalp 40x"},
    "micro_scalp":    {"sl": 0.3, "tp": 0.5, "lev": 50, "ts_h": 1, "desc": "Micro scalp 50x"},
}


@dataclass
class EdgePosition:
    config_name: str
    symbol: str
    side: str
    entry: float
    sl: float
    tp: float
    leverage: float
    opened_at: float
    time_stop_s: float
    risk_pct: float = 0.05  # 5% of equity risked


@dataclass
class EdgeTracker:
    config_name: str
    equity: float = 100.0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_equity: float = 100.0
    max_drawdown_pct: float = 0.0
    open_positions: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)


def walk_candles(df, entry_idx, side, sl_pct, tp_pct, ts_bars):
    """Walk forward through candles, check TP/SL/time-stop."""
    entry = df["close"].iloc[entry_idx]
    if side == "BUY":
        sl = entry * (1 - sl_pct / 100)
        tp = entry * (1 + tp_pct / 100)
    else:
        sl = entry * (1 + sl_pct / 100)
        tp = entry * (1 - tp_pct / 100)

    for bars in range(1, min(ts_bars + 1, len(df) - entry_idx)):
        c = df.iloc[entry_idx + bars]

        if side == "BUY":
            sl_hit = c["low"] <= sl
            tp_hit = c["high"] >= tp
        else:
            sl_hit = c["high"] >= sl
            tp_hit = c["low"] <= tp

        if sl_hit and tp_hit:
            sl_first = (c["open"] < entry) if side == "BUY" else (c["open"] > entry)
            if sl_first:
                tp_hit = False
            else:
                sl_hit = False

        if sl_hit:
            return "LOSS", bars, sl
        if tp_hit:
            return "WIN", bars, tp

    # Time stop
    last = df.iloc[min(entry_idx + ts_bars, len(df) - 1)]
    if side == "BUY":
        move = (last["close"] - entry) / entry * 100
    else:
        move = (entry - last["close"]) / entry * 100
    return ("TS_WIN" if move > 0 else "TS_LOSS"), ts_bars, last["close"]


def should_enter(df, i, side):
    """Basic entry filter."""
    if i < 20:
        return False
    close = df["close"].iloc[i]
    sma20 = df["close"].iloc[i-20:i].mean()
    if side == "BUY" and close < sma20 * 0.95:
        return False
    if side == "SELL" and close > sma20 * 1.05:
        return False
    return True


def run_backtest():
    """Backtest ALL edge configs against 30-day 1h data."""
    from data.fetcher import DataFetcher

    fetcher = DataFetcher()
    symbols = {
        "HYPE": ("hyperliquid", "BUY"),
        "SOL": ("solana", "SELL"),
        "BTC": ("bitcoin", "BUY"),
    }

    print("=" * 70)
    print("  MULTI-EDGE BACKTEST — All configs, all symbols, 30 days")
    print("=" * 70)

    all_results = {}

    for sym, (coin_id, default_side) in symbols.items():
        df = fetcher.fetch_ohlcv(sym, coin_id, "1h")
        if df is None or df.empty:
            continue
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True)
        print(f"\n{sym} ({len(df)} candles, side={default_side})")

        for config_name, cfg in EDGE_CONFIGS.items():
            # Skip BTC-specific configs for non-BTC
            if config_name.startswith("btc_") and sym != "BTC":
                continue
            # Skip non-BTC configs for BTC if leverage > BTC max
            max_lev = 50 if sym == "BTC" else 25
            lev = min(cfg["lev"], max_lev)

            sl_pct = cfg["sl"]
            tp_pct = cfg["tp"]
            ts_bars = cfg["ts_h"]

            equity = 100.0
            peak = 100.0
            max_dd = 0.0
            trades = []
            last_entry = -999
            cooldown = max(ts_bars, 3)

            for i in range(20, len(df) - ts_bars - 1):
                if i - last_entry < cooldown:
                    continue
                if not should_enter(df, i, default_side):
                    continue

                outcome, bars, exit_price = walk_candles(
                    df, i, default_side, sl_pct, tp_pct, ts_bars
                )

                # PnL calculation
                entry = df["close"].iloc[i]
                if outcome == "WIN":
                    move_pct = tp_pct
                elif outcome == "LOSS":
                    move_pct = -sl_pct
                else:
                    if default_side == "BUY":
                        move_pct = (exit_price - entry) / entry * 100
                    else:
                        move_pct = (entry - exit_price) / entry * 100

                risk_frac = 0.05  # 5% equity risked
                pnl = equity * risk_frac * (move_pct / sl_pct) if sl_pct > 0 else 0
                equity += pnl
                peak = max(peak, equity)
                dd = (peak - equity) / peak * 100
                max_dd = max(max_dd, dd)

                trades.append({
                    "outcome": outcome, "bars": bars, "pnl": pnl,
                    "move_pct": move_pct, "entry": entry,
                })
                last_entry = i

            if not trades:
                continue

            wins = sum(1 for t in trades if t["outcome"] in ("WIN", "TS_WIN"))
            total = len(trades)
            wr = wins / total * 100 if total else 0
            gp = sum(t["pnl"] for t in trades if t["pnl"] > 0)
            gl = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
            pf = gp / gl if gl > 0 else float("inf")

            key = f"{sym}_{config_name}"
            all_results[key] = {
                "symbol": sym, "config": config_name, "desc": cfg["desc"],
                "sl": sl_pct, "tp": tp_pct, "lev": lev, "ts_h": ts_bars,
                "trades": total, "wins": wins, "wr": wr, "pf": pf,
                "equity": equity, "max_dd": max_dd,
                "net_return": equity - 100,
            }

    # Sort by PF and print
    print(f"\n{'=' * 70}")
    print(f"{'Config':25s} {'Sym':5s} {'Trades':>6s} {'WR':>5s} {'PF':>6s} {'$100->':>8s} {'DD':>5s}")
    print(f"{'-' * 70}")

    sorted_results = sorted(all_results.values(), key=lambda x: x["pf"] if x["pf"] < 100 else 0, reverse=True)
    for r in sorted_results:
        pf_str = f"{r['pf']:.2f}" if r["pf"] < 100 else "INF"
        print(f"{r['desc']:25s} {r['symbol']:5s} {r['trades']:6d} {r['wr']:4.0f}% {pf_str:>6s} ${r['equity']:7.2f} {r['max_dd']:4.1f}%")

    # Save results
    report_path = os.path.join(DATA_DIR, "MULTI_EDGE_RESULTS.md")
    lines = ["# Multi-Edge Backtest Results", ""]
    lines.append(f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Configs tested**: {len(EDGE_CONFIGS)}")
    lines.append(f"**Symbols**: HYPE (BUY), SOL (SELL), BTC (BUY)")
    lines.append("")
    lines.append("## Results (sorted by Profit Factor)")
    lines.append("")
    lines.append(f"| Config | Symbol | SL% | TP% | Lev | TS | Trades | WR | PF | $100-> | DD |")
    lines.append(f"|--------|--------|-----|-----|-----|----|----|----|----|--------|-------|")
    for r in sorted_results:
        pf_str = f"{r['pf']:.2f}" if r["pf"] < 100 else "INF"
        lines.append(
            f"| {r['desc']} | {r['symbol']} | {r['sl']}% | {r['tp']}% | "
            f"{r['lev']}x | {r['ts_h']}h | {r['trades']} | {r['wr']:.0f}% | "
            f"{pf_str} | ${r['equity']:.2f} | {r['max_dd']:.1f}% |"
        )
    lines.append("")
    lines.append("## Key Insights")
    lines.append("")
    if sorted_results:
        best = sorted_results[0]
        lines.append(f"**Best PF**: {best['desc']} on {best['symbol']} (PF={best['pf']:.2f}, WR={best['wr']:.0f}%)")
    # Find best by net return
    best_return = max(sorted_results, key=lambda x: x["net_return"])
    lines.append(f"**Best return**: {best_return['desc']} on {best_return['symbol']} (${best_return['equity']:.2f}, +{best_return['net_return']:.0f}%)")
    # Find lowest drawdown with positive return
    positive = [r for r in sorted_results if r["net_return"] > 0]
    if positive:
        safest = min(positive, key=lambda x: x["max_dd"])
        lines.append(f"**Safest profitable**: {safest['desc']} on {safest['symbol']} (DD={safest['max_dd']:.1f}%, PF={safest['pf']:.2f})")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", action="store_true", help="Backtest all configs")
    parser.add_argument("--status", action="store_true", help="Show current sim status")
    args = parser.parse_args()

    if args.backtest:
        run_backtest()
    else:
        print("Usage: python -m tools.multi_edge_sim --backtest")
        print(f"Configs available: {len(EDGE_CONFIGS)}")
        for name, cfg in EDGE_CONFIGS.items():
            print(f"  {name:20s}: SL={cfg['sl']}% TP={cfg['tp']}% {cfg['lev']}x {cfg['ts_h']}h — {cfg['desc']}")
