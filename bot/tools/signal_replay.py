"""
Signal Replay Engine — Walks historical sniper signals forward through real OHLCV data.

For each unique signal, fetches 1h candles from the signal timestamp forward and checks
whether TP_scalp, SL, or time stop (3h/12h/24h) would have hit first. Produces a full
P&L report with breakdown by setup type, equity curve, and profitability metrics.

Usage:
    cd bot && python -m tools.signal_replay
    cd bot && python -m tools.signal_replay --time-stop 12
    cd bot && python -m tools.signal_replay --output data/manual/REPLAY_RESULTS.md
"""

import json
import logging
import os
import sys
import argparse
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import DataFetcher

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("signal_replay")

# ── CoinGecko IDs for fallback ────────────────────────────────────────
COIN_IDS = {
    "HYPE": "hyperliquid",
    "SOL": "solana",
    "BTC": "bitcoin",
    "DOGE": "dogecoin",
    "ETH": "ethereum",
}

# ── Time stop configs ─────────────────────────────────────────────────
DEFAULT_TIME_STOPS = [3, 12, 24]  # hours — we'll test all three


@dataclass
class ReplayResult:
    """Result of walking one signal forward through price data."""
    symbol: str
    side: str
    tier: str
    entry: float
    sl: float
    tp_scalp: float
    leverage: float
    risk_pct: float
    position_size_usd: float
    risk_amount: float
    pnl_scalp: float
    loss_amount: float
    confidence: float
    num_agree: int
    regime: str
    signal_ts: str
    # Outcome
    outcome: str = ""         # WIN / LOSS / TIME_STOP
    exit_price: float = 0.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    bars_held: int = 0
    hold_hours: float = 0.0
    mfe_pct: float = 0.0     # Max favorable excursion %
    mae_pct: float = 0.0     # Max adverse excursion %
    exit_reason: str = ""
    time_stop_hours: float = 0.0


def parse_signals(path: str) -> List[Dict]:
    """Load and deduplicate sniper signals."""
    signals = []
    seen = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Deduplicate by (symbol, side, entry, sl, tp, timestamp_hour)
            ts = r.get("timestamp", "")
            ts_hour = ts[:13] if ts else ""  # Group by hour
            key = (r["symbol"], r["side"], r.get("entry"), r.get("sl"),
                   r.get("tp_scalp"), ts_hour)
            if key in seen:
                continue
            seen.add(key)
            signals.append(r)
    return signals


def fetch_ohlcv_for_symbol(fetcher: DataFetcher, symbol: str) -> Optional[pd.DataFrame]:
    """Fetch 1h OHLCV data for a symbol."""
    coin_id = COIN_IDS.get(symbol, symbol.lower())
    try:
        df = fetcher.fetch_ohlcv(symbol, coin_id, "1h")
        if df is not None and not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)
            return df
    except Exception as e:
        logger.error(f"Failed to fetch {symbol} 1h data: {e}")
    return None


def walk_forward(signal: Dict, ohlcv: pd.DataFrame,
                 time_stop_hours: float = 24.0) -> Optional[ReplayResult]:
    """
    Walk forward through 1h candles from signal timestamp.
    Check if TP_scalp, SL, or time stop hits first.
    """
    entry = signal["entry"]
    sl = signal["sl"]
    tp = signal["tp_scalp"]
    side = signal["side"]
    ts_str = signal.get("timestamp", "")

    if not ts_str or not entry or not sl or not tp:
        return None

    try:
        signal_time = pd.Timestamp(ts_str).tz_convert("UTC") if "+" in ts_str or "Z" in ts_str \
            else pd.Timestamp(ts_str, tz="UTC")
    except Exception:
        return None

    # Find candles after signal time
    mask = ohlcv["time"] >= signal_time
    forward = ohlcv[mask]

    if forward.empty:
        return None

    time_stop_s = time_stop_hours * 3600
    mfe = 0.0  # Max favorable excursion %
    mae = 0.0  # Max adverse excursion %

    leverage = signal.get("leverage", 1.0)
    risk_amount = signal.get("risk_amount", 0.0)
    pnl_scalp = signal.get("pnl_scalp", 0.0)
    loss_amount = signal.get("loss_amount", 0.0)
    position_size = signal.get("position_size_usd", 0.0)

    result = ReplayResult(
        symbol=signal["symbol"],
        side=side,
        tier=signal.get("tier", "UNKNOWN"),
        entry=entry,
        sl=sl,
        tp_scalp=tp,
        leverage=leverage,
        risk_pct=signal.get("risk_pct", 0.0),
        position_size_usd=position_size,
        risk_amount=risk_amount,
        pnl_scalp=pnl_scalp,
        loss_amount=loss_amount,
        confidence=signal.get("confidence", 0.0),
        num_agree=signal.get("num_agree", 0),
        regime=signal.get("regime", "unknown"),
        signal_ts=ts_str,
        time_stop_hours=time_stop_hours,
    )

    for i, (_, candle) in enumerate(forward.iterrows()):
        elapsed_s = (candle["time"] - signal_time).total_seconds()

        # Track MFE/MAE
        if side == "BUY":
            fav = ((candle["high"] - entry) / entry) * 100
            adv = ((entry - candle["low"]) / entry) * 100
        else:
            fav = ((entry - candle["low"]) / entry) * 100
            adv = ((candle["high"] - entry) / entry) * 100
        mfe = max(mfe, fav)
        mae = max(mae, adv)

        # Check SL hit (check before TP — conservative)
        if side == "BUY":
            sl_hit = candle["low"] <= sl
            tp_hit = candle["high"] >= tp
        else:
            sl_hit = candle["high"] >= sl
            tp_hit = candle["low"] <= tp

        # If both hit in same candle, check open direction
        if sl_hit and tp_hit:
            # Conservative: assume SL hit first if candle opened unfavorably
            if side == "BUY":
                sl_hit_first = candle["open"] < entry
            else:
                sl_hit_first = candle["open"] > entry
            if sl_hit_first:
                tp_hit = False
            else:
                sl_hit = False

        if sl_hit:
            result.outcome = "LOSS"
            result.exit_price = sl
            result.exit_reason = "sl"
            if side == "BUY":
                move_pct = (sl - entry) / entry
            else:
                move_pct = (entry - sl) / entry
            result.pnl_pct = move_pct * leverage * 100
            result.pnl_usd = -abs(loss_amount) if loss_amount else move_pct * position_size
            result.bars_held = i + 1
            result.hold_hours = elapsed_s / 3600
            result.mfe_pct = mfe
            result.mae_pct = mae
            return result

        if tp_hit:
            result.outcome = "WIN"
            result.exit_price = tp
            result.exit_reason = "tp_scalp"
            if side == "BUY":
                move_pct = (tp - entry) / entry
            else:
                move_pct = (entry - tp) / entry
            result.pnl_pct = move_pct * leverage * 100
            result.pnl_usd = abs(pnl_scalp) if pnl_scalp else move_pct * position_size
            result.bars_held = i + 1
            result.hold_hours = elapsed_s / 3600
            result.mfe_pct = mfe
            result.mae_pct = mae
            return result

        # Time stop
        if elapsed_s >= time_stop_s:
            result.outcome = "TIME_STOP"
            result.exit_price = candle["close"]
            result.exit_reason = f"time_stop_{int(time_stop_hours)}h"
            if side == "BUY":
                move_pct = (candle["close"] - entry) / entry
            else:
                move_pct = (entry - candle["close"]) / entry
            result.pnl_pct = move_pct * leverage * 100
            result.pnl_usd = move_pct * position_size
            result.bars_held = i + 1
            result.hold_hours = elapsed_s / 3600
            result.mfe_pct = mfe
            result.mae_pct = mae
            return result

    # Never resolved (data ran out)
    if len(forward) > 0:
        last = forward.iloc[-1]
        result.outcome = "UNRESOLVED"
        result.exit_price = last["close"]
        result.exit_reason = "data_end"
        if side == "BUY":
            move_pct = (last["close"] - entry) / entry
        else:
            move_pct = (entry - last["close"]) / entry
        result.pnl_pct = move_pct * leverage * 100
        result.pnl_usd = move_pct * position_size
        result.bars_held = len(forward)
        result.hold_hours = (forward.iloc[-1]["time"] - signal_time).total_seconds() / 3600
        result.mfe_pct = mfe
        result.mae_pct = mae
        return result

    return None


def compute_metrics(results: List[ReplayResult]) -> Dict[str, Any]:
    """Compute aggregate P&L metrics from replay results."""
    if not results:
        return {}

    resolved = [r for r in results if r.outcome in ("WIN", "LOSS", "TIME_STOP")]
    wins = [r for r in resolved if r.outcome == "WIN"]
    losses = [r for r in resolved if r.outcome == "LOSS"]
    time_stops = [r for r in resolved if r.outcome == "TIME_STOP"]
    ts_wins = [r for r in time_stops if r.pnl_usd > 0]
    ts_losses = [r for r in time_stops if r.pnl_usd <= 0]

    total_pnl = sum(r.pnl_usd for r in resolved)
    gross_profit = sum(r.pnl_usd for r in resolved if r.pnl_usd > 0)
    gross_loss = abs(sum(r.pnl_usd for r in resolved if r.pnl_usd < 0))

    win_rate = len(wins) / len(resolved) * 100 if resolved else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_win = np.mean([r.pnl_usd for r in wins]) if wins else 0
    avg_loss = np.mean([abs(r.pnl_usd) for r in losses]) if losses else 0
    avg_hold_win = np.mean([r.hold_hours for r in wins]) if wins else 0
    avg_hold_loss = np.mean([r.hold_hours for r in losses]) if losses else 0

    # Equity curve (starting at $100)
    equity = 100.0
    equity_curve = [equity]
    for r in sorted(resolved, key=lambda x: x.signal_ts):
        # Scale PnL to $100 account
        if r.risk_amount > 0:
            pnl_scaled = r.pnl_usd * (equity / (r.risk_amount / r.risk_pct)) if r.risk_pct > 0 else 0
        else:
            pnl_scaled = r.pnl_usd
        equity += pnl_scaled
        equity_curve.append(equity)

    max_equity = max(equity_curve)
    drawdowns = [(max(equity_curve[:i+1]) - v) / max(equity_curve[:i+1]) * 100
                 for i, v in enumerate(equity_curve)]
    max_dd = max(drawdowns) if drawdowns else 0

    return {
        "total_signals": len(results),
        "resolved": len(resolved),
        "unresolved": len([r for r in results if r.outcome == "UNRESOLVED"]),
        "wins": len(wins),
        "losses": len(losses),
        "time_stops": len(time_stops),
        "time_stop_wins": len(ts_wins),
        "time_stop_losses": len(ts_losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_rr_realized": avg_win / avg_loss if avg_loss > 0 else float("inf"),
        "avg_hold_win_h": avg_hold_win,
        "avg_hold_loss_h": avg_hold_loss,
        "equity_start": 100.0,
        "equity_end": equity,
        "equity_curve": equity_curve,
        "max_drawdown_pct": max_dd,
        "avg_mfe": np.mean([r.mfe_pct for r in resolved]) if resolved else 0,
        "avg_mae": np.mean([r.mae_pct for r in resolved]) if resolved else 0,
    }


def format_report(all_results: Dict[str, List[ReplayResult]],
                  all_metrics: Dict[str, Dict],
                  overall_metrics: Dict,
                  time_stop_hours: float) -> str:
    """Generate markdown report."""
    lines = []
    lines.append("# Sniper Signal Replay Results")
    lines.append(f"\n**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Time Stop**: {time_stop_hours}h")
    lines.append("")

    # Overall summary
    m = overall_metrics
    lines.append("## Overall Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Signals (deduplicated) | {m.get('total_signals', 0)} |")
    lines.append(f"| Resolved | {m.get('resolved', 0)} |")
    lines.append(f"| Unresolved (data ended) | {m.get('unresolved', 0)} |")
    lines.append(f"| **Win Rate** | **{m.get('win_rate', 0):.1f}%** |")
    lines.append(f"| **Profit Factor** | **{m.get('profit_factor', 0):.2f}** |")
    lines.append(f"| Total PnL (raw $) | ${m.get('total_pnl', 0):.2f} |")
    lines.append(f"| Gross Profit | ${m.get('gross_profit', 0):.2f} |")
    lines.append(f"| Gross Loss | ${m.get('gross_loss', 0):.2f} |")
    lines.append(f"| Avg Win | ${m.get('avg_win', 0):.2f} |")
    lines.append(f"| Avg Loss | ${m.get('avg_loss', 0):.2f} |")
    lines.append(f"| Realized R:R | {m.get('avg_rr_realized', 0):.2f} |")
    lines.append(f"| Avg Hold (winners) | {m.get('avg_hold_win_h', 0):.1f}h |")
    lines.append(f"| Avg Hold (losers) | {m.get('avg_hold_loss_h', 0):.1f}h |")
    lines.append(f"| Equity $100 → | **${m.get('equity_end', 100):.2f}** |")
    lines.append(f"| Max Drawdown | {m.get('max_drawdown_pct', 0):.1f}% |")
    lines.append(f"| Avg MFE | {m.get('avg_mfe', 0):.2f}% |")
    lines.append(f"| Avg MAE | {m.get('avg_mae', 0):.2f}% |")
    lines.append("")

    # Breakdown by setup
    lines.append("## Breakdown by Setup")
    lines.append("")
    lines.append("| Setup | Trades | WR | PF | Total PnL | Avg Win | Avg Loss | Avg Hold |")
    lines.append("|-------|--------|----|----|-----------|---------|----------|----------|")

    for setup_key in sorted(all_metrics.keys()):
        sm = all_metrics[setup_key]
        resolved = sm.get("resolved", 0)
        if resolved == 0:
            continue
        lines.append(
            f"| {setup_key} | {resolved} | "
            f"{sm.get('win_rate', 0):.0f}% | "
            f"{sm.get('profit_factor', 0):.2f} | "
            f"${sm.get('total_pnl', 0):.2f} | "
            f"${sm.get('avg_win', 0):.2f} | "
            f"${sm.get('avg_loss', 0):.2f} | "
            f"{sm.get('avg_hold_win_h', 0):.1f}h |"
        )
    lines.append("")

    # Individual trade log
    lines.append("## Trade Log (chronological)")
    lines.append("")
    lines.append("| # | Setup | Entry | SL | TP | Lev | Outcome | PnL | Bars | MFE | MAE |")
    lines.append("|---|-------|-------|----|----|-----|---------|-----|------|-----|-----|")

    all_trades = []
    for setup_results in all_results.values():
        all_trades.extend(setup_results)
    all_trades.sort(key=lambda r: r.signal_ts)

    for i, r in enumerate(all_trades, 1):
        setup = f"{r.symbol}_{r.side}"
        outcome_emoji = {"WIN": "W", "LOSS": "L", "TIME_STOP": "TS", "UNRESOLVED": "??"}.get(r.outcome, "?")
        lines.append(
            f"| {i} | {setup} | {r.entry} | {r.sl} | {r.tp_scalp} | "
            f"{r.leverage:.0f}x | {outcome_emoji} | "
            f"${r.pnl_usd:.2f} | {r.bars_held} | "
            f"{r.mfe_pct:.1f}% | {r.mae_pct:.1f}% |"
        )
    lines.append("")

    # Equity curve (text)
    if m.get("equity_curve"):
        lines.append("## Equity Curve")
        lines.append("```")
        curve = m["equity_curve"]
        for i, eq in enumerate(curve):
            bar_len = max(0, int((eq - 80) / 2))
            bar = "#" * bar_len
            lines.append(f"Trade {i:3d}: ${eq:8.2f}  {bar}")
        lines.append("```")
        lines.append("")

    # Key insights
    lines.append("## Key Insights")
    lines.append("")
    for setup_key, sm in sorted(all_metrics.items()):
        resolved = sm.get("resolved", 0)
        if resolved == 0:
            continue
        wr = sm.get("win_rate", 0)
        pf = sm.get("profit_factor", 0)
        if wr >= 60:
            verdict = "PROFITABLE EDGE"
        elif wr >= 50:
            verdict = "MARGINAL"
        else:
            verdict = "NEGATIVE EV"
        lines.append(f"- **{setup_key}**: {wr:.0f}% WR, PF {pf:.2f} — {verdict}")

    lines.append("")
    lines.append("---")
    lines.append(f"*Replay of {m.get('total_signals', 0)} unique signals against 1h OHLCV data*")
    lines.append(f"*Time stop: {time_stop_hours}h | Conservative SL-first assumption on same-bar hits*")

    return "\n".join(lines)


def run_replay(signals_path: str, time_stop_hours: float = 24.0,
               output_path: str = None) -> Dict:
    """Main replay execution."""
    logger.info("=" * 60)
    logger.info("SNIPER SIGNAL REPLAY ENGINE")
    logger.info("=" * 60)

    # Load and deduplicate signals
    logger.info(f"\nLoading signals from {signals_path}...")
    signals = parse_signals(signals_path)
    logger.info(f"  {len(signals)} unique signals after deduplication")

    # Group by symbol
    by_symbol = defaultdict(list)
    for s in signals:
        by_symbol[s["symbol"]].append(s)

    logger.info(f"  Symbols: {', '.join(f'{k}({len(v)})' for k, v in by_symbol.items())}")

    # Fetch OHLCV data
    fetcher = DataFetcher()
    ohlcv_cache = {}
    for symbol in by_symbol:
        logger.info(f"\nFetching {symbol} 1h OHLCV data...")
        df = fetch_ohlcv_for_symbol(fetcher, symbol)
        if df is not None:
            ohlcv_cache[symbol] = df
            logger.info(f"  {len(df)} candles: {df['time'].iloc[0]} → {df['time'].iloc[-1]}")
        else:
            logger.warning(f"  FAILED — skipping {symbol}")

    # Walk forward for each signal
    logger.info(f"\nWalking forward with {time_stop_hours}h time stop...")
    all_results = defaultdict(list)
    all_flat = []

    for signal in signals:
        symbol = signal["symbol"]
        if symbol not in ohlcv_cache:
            continue
        result = walk_forward(signal, ohlcv_cache[symbol], time_stop_hours)
        if result:
            setup_key = f"{symbol}_{signal['side']}"
            all_results[setup_key].append(result)
            all_flat.append(result)

    # Compute metrics per setup
    logger.info("\nComputing metrics...")
    setup_metrics = {}
    for setup_key, results in all_results.items():
        setup_metrics[setup_key] = compute_metrics(results)
        sm = setup_metrics[setup_key]
        logger.info(
            f"  {setup_key}: {sm['resolved']} trades, "
            f"WR={sm['win_rate']:.0f}%, PF={sm['profit_factor']:.2f}, "
            f"PnL=${sm['total_pnl']:.2f}"
        )

    # Overall metrics
    overall = compute_metrics(all_flat)
    logger.info(f"\n  OVERALL: {overall['resolved']} trades, "
                f"WR={overall['win_rate']:.0f}%, PF={overall['profit_factor']:.2f}, "
                f"PnL=${overall['total_pnl']:.2f}, "
                f"$100 → ${overall['equity_end']:.2f}")

    # Generate report
    report = format_report(all_results, setup_metrics, overall, time_stop_hours)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info(f"\nReport saved to {output_path}")

    return {
        "overall": overall,
        "by_setup": setup_metrics,
        "report": report,
    }


def run_multi_timestop(signals_path: str, output_dir: str):
    """Run replay with multiple time stop settings for comparison."""
    logger.info("\n" + "=" * 60)
    logger.info("MULTI-TIME-STOP COMPARISON")
    logger.info("=" * 60)

    summaries = {}
    for ts in DEFAULT_TIME_STOPS:
        logger.info(f"\n--- Time Stop: {ts}h ---")
        result = run_replay(
            signals_path, time_stop_hours=ts,
            output_path=os.path.join(output_dir, f"REPLAY_{ts}h.md")
        )
        summaries[ts] = result["overall"]

    # Comparison summary
    lines = ["# Time Stop Comparison", ""]
    lines.append("| Time Stop | Trades | WR | PF | PnL | Equity $100→ | Max DD |")
    lines.append("|-----------|--------|----|----|-----|-------------|--------|")
    for ts in DEFAULT_TIME_STOPS:
        m = summaries[ts]
        lines.append(
            f"| {ts}h | {m['resolved']} | {m['win_rate']:.0f}% | "
            f"{m['profit_factor']:.2f} | ${m['total_pnl']:.2f} | "
            f"${m['equity_end']:.2f} | {m['max_drawdown_pct']:.1f}% |"
        )
    lines.append("")
    lines.append("*Best time stop = highest PF with acceptable DD*")

    comp_path = os.path.join(output_dir, "TIME_STOP_COMPARISON.md")
    with open(comp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"\nComparison saved to {comp_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay sniper signals against OHLCV data")
    parser.add_argument("--signals", default="data/manual/sniper_signals.jsonl",
                        help="Path to sniper signals JSONL file")
    parser.add_argument("--time-stop", type=float, default=24.0,
                        help="Time stop in hours (default: 24)")
    parser.add_argument("--output", default="data/manual/REPLAY_RESULTS.md",
                        help="Output report path")
    parser.add_argument("--compare-timestops", action="store_true",
                        help="Run comparison across 3h/12h/24h time stops")
    args = parser.parse_args()

    if args.compare_timestops:
        run_multi_timestop(args.signals, "data/manual")
    else:
        result = run_replay(args.signals, args.time_stop, args.output)
        print(f"\n{'=' * 60}")
        print(f"FINAL: {result['overall']['resolved']} trades, "
              f"WR={result['overall']['win_rate']:.0f}%, "
              f"PF={result['overall']['profit_factor']:.2f}")
        print(f"$100 → ${result['overall']['equity_end']:.2f}")
        print(f"{'=' * 60}")
